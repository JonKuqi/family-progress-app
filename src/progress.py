'''Progress calculations and privacy safeguards for the application.'''

from pathlib import Path

from src.database import DIMENSIONS, get_connection


DIMENSION_LABELS = {
    'settles_and_recovers': 'Settles and recovers',
    'stays_with_task': 'Stays with a task',
    'connects_with_others': 'Connects with other children',
}


def get_available_families(db_path: Path | str | None = None) -> list[dict]:
    '''Return families in their stable demonstration order.'''
    with get_connection(db_path) as connection:
        rows = connection.execute(
            'SELECT family_id, family_name FROM families ORDER BY family_id'
        ).fetchall()
    return [dict(row) for row in rows]


def get_children_for_family(
    family_id: int, db_path: Path | str | None = None
) -> list[dict]:
    '''Return every child belonging to the selected family.'''
    with get_connection(db_path) as connection:
        rows = connection.execute(
            '''
            SELECT child_id, first_name
            FROM children
            WHERE family_id = ?
            ORDER BY child_id
            ''',
            (family_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_available_months(
    child_id: int, db_path: Path | str | None = None
) -> list[str]:
    '''Return months that contain sessions for one explicit child.'''
    with get_connection(db_path) as connection:
        rows = connection.execute(
            '''
            SELECT DISTINCT substr(session_date, 1, 7) AS month
            FROM sessions
            WHERE child_id = ?
            ORDER BY month DESC
            ''',
            (child_id,),
        ).fetchall()
    return [row['month'] for row in rows]


def get_consent_status(
    family_id: int, db_path: Path | str | None = None
) -> dict[str, bool]:
    '''Return each independently stored consent purpose for a family.'''
    with get_connection(db_path) as connection:
        rows = connection.execute(
            'SELECT purpose, granted FROM consents WHERE family_id = ?',
            (family_id,),
        ).fetchall()
    return {row['purpose']: bool(row['granted']) for row in rows}


def get_parent_snapshot(
    child_id: int, month: str, db_path: Path | str | None = None
) -> dict:
    '''Return a consent-checked monthly snapshot for one explicit child.'''
    with get_connection(db_path) as connection:
        child = connection.execute(
            '''
            SELECT c.child_id, c.first_name, f.family_id, f.family_name
            FROM children c
            JOIN families f ON f.family_id = c.family_id
            WHERE c.child_id = ?
            ''',
            (child_id,),
        ).fetchone()
        if child is None:
            raise ValueError('Child not found')

        if not get_consent_status(child['family_id'], db_path).get(
            'parent_reporting', False
        ):
            raise PermissionError('Parent reporting consent is not active')

        rows = connection.execute(
            '''
            SELECT s.session_date, o.dimension, o.score
            FROM sessions s
            JOIN observations o ON o.session_id = s.session_id
            WHERE s.child_id = ? AND substr(s.session_date, 1, 7) = ?
            ORDER BY s.session_date, o.dimension
            ''',
            (child_id, month),
        ).fetchall()

    if not rows:
        raise ValueError('No sessions found for the selected month')

    weekly = _weekly_rows(rows)
    averages = {
        dimension: round(sum(week[dimension] for week in weekly) / len(weekly), 2)
        for dimension in DIMENSIONS
    }
    contact = evaluate_contact_rule(child_id, month, db_path)

    return {
        'family_id': child['family_id'],
        'family_name': child['family_name'],
        'child_id': child['child_id'],
        'child_name': child['first_name'],
        'month': month,
        'sessions_attended': len(weekly),
        'averages': averages,
        'weekly': weekly,
        'contact': contact,
        'summary': _build_parent_summary(
            child['first_name'], weekly, averages, contact
        ),
    }


def evaluate_contact_rule(
    child_id: int, month: str, db_path: Path | str | None = None
) -> dict:
    '''Find scores of two or lower in consecutive dated sessions.'''
    with get_connection(db_path) as connection:
        rows = connection.execute(
            '''
            SELECT s.session_date, o.dimension, o.score
            FROM sessions s
            JOIN observations o ON o.session_id = s.session_id
            WHERE s.child_id = ? AND substr(s.session_date, 1, 7) = ?
            ORDER BY o.dimension, s.session_date
            ''',
            (child_id, month),
        ).fetchall()

    patterns = []
    for dimension in DIMENSIONS:
        dimension_rows = [row for row in rows if row['dimension'] == dimension]
        for previous, current in zip(dimension_rows, dimension_rows[1:]):
            if previous['score'] <= 2 and current['score'] <= 2:
                patterns.append(
                    {
                        'dimension': dimension,
                        'sessions': [
                            previous['session_date'],
                            current['session_date'],
                        ],
                        'scores': [previous['score'], current['score']],
                    }
                )

    return {'triggered': bool(patterns), 'patterns': patterns}


def get_group_summary(
    child_ids: list[int], month: str, db_path: Path | str | None = None
) -> dict:
    '''Return aggregate values only when five selected children are eligible.'''
    selected_ids = list(dict.fromkeys(child_ids))
    if not selected_ids:
        return {
            'selected_children': 0,
            'eligible_children': 0,
            'excluded_children': 0,
            'suppressed': True,
            'averages': None,
        }

    placeholders = ','.join('?' for _ in selected_ids)
    with get_connection(db_path) as connection:
        eligible_rows = connection.execute(
            f'''
            SELECT DISTINCT c.child_id
            FROM children c
            JOIN consents co ON co.family_id = c.family_id
            JOIN sessions s ON s.child_id = c.child_id
            WHERE c.child_id IN ({placeholders})
              AND co.purpose = 'research_analytics'
              AND co.granted = 1
              AND substr(s.session_date, 1, 7) = ?
            ''',
            (*selected_ids, month),
        ).fetchall()
        eligible_ids = [row['child_id'] for row in eligible_rows]
        counts = {
            'selected_children': len(selected_ids),
            'eligible_children': len(eligible_ids),
            'excluded_children': len(selected_ids) - len(eligible_ids),
        }

        if len(eligible_ids) < 5:
            return {**counts, 'suppressed': True, 'averages': None}

        eligible_placeholders = ','.join('?' for _ in eligible_ids)
        average_rows = connection.execute(
            f'''
            SELECT o.dimension, ROUND(AVG(o.score), 2) AS average
            FROM observations o
            JOIN sessions s ON s.session_id = o.session_id
            WHERE s.child_id IN ({eligible_placeholders})
              AND substr(s.session_date, 1, 7) = ?
            GROUP BY o.dimension
            ''',
            (*eligible_ids, month),
        ).fetchall()

    return {
        **counts,
        'suppressed': False,
        'averages': {row['dimension']: row['average'] for row in average_rows},
    }


def _weekly_rows(rows) -> list[dict]:
    sessions = {}
    for row in rows:
        session = sessions.setdefault(
            row['session_date'], {'session_date': row['session_date']}
        )
        session[row['dimension']] = row['score']
    return list(sessions.values())


def _build_parent_summary(
    child_name: str,
    weekly: list[dict],
    averages: dict[str, float],
    contact: dict,
) -> str:
    strongest = max(DIMENSIONS, key=averages.get)
    improving = [
        dimension
        for dimension in DIMENSIONS
        if weekly[-1][dimension] > weekly[0][dimension] and dimension != strongest
    ]

    strength_text = {
        'settles_and_recovers': 'settled and recovered particularly well',
        'stays_with_task': 'stayed with tasks particularly well',
        'connects_with_others': 'connected consistently well with other children',
    }[strongest]
    first_sentence = f'{child_name} {strength_text} this month'
    if improving:
        improvement = {
            'settles_and_recovers': 'settling and recovering',
            'stays_with_task': 'staying with a task',
            'connects_with_others': 'connecting with other children',
        }[improving[0]]
        first_sentence += f', and {improvement} improved across the sessions'
    first_sentence += '.'

    if contact['triggered']:
        dimension = contact['patterns'][0]['dimension']
        difficulty = {
            'settles_and_recovers': 'Settling and recovering',
            'stays_with_task': 'Staying with a task',
            'connects_with_others': 'Connecting with other children',
        }[dimension]
        second_sentence = (
            f'{difficulty} was more difficult in two consecutive sessions, so a '
            'member of the team should review the pattern and consider contacting '
            'the family.'
        )
    else:
        second_sentence = 'No follow-up pattern was detected this month.'

    return f'{first_sentence} {second_sentence}'
