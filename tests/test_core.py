'''Focused tests for seeded data, follow-up detection, and privacy safeguards.'''

import pytest

from src.database import get_connection, initialize_database, set_consent
from src.progress import (
    evaluate_contact_rule,
    get_available_families,
    get_consent_status,
    get_children_for_family,
    get_group_summary,
    get_parent_snapshot,
)


@pytest.fixture
def database(tmp_path):
    '''Create an isolated SQLite database from the static CSV inputs.'''
    path = tmp_path / 'test.db'
    initialize_database(path)
    return path


def _set_scores(database, child_id, dimension, scores):
    '''Replace one child's ordered scores to exercise the contact rule.'''
    with get_connection(database) as connection:
        session_ids = connection.execute(
            'SELECT session_id FROM sessions WHERE child_id = ? ORDER BY session_date',
            (child_id,),
        ).fetchall()
        for row, score in zip(session_ids, scores):
            connection.execute(
                '''
                UPDATE observations SET score = ?
                WHERE session_id = ? AND dimension = ?
                ''',
                (score, row['session_id'], dimension),
            )


def test_seeded_data_has_expected_totals(database):
    '''The CSV inputs should create the required longitudinal dataset.'''
    with get_connection(database) as connection:
        counts = {
            table: connection.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
            for table in ('families', 'children', 'sessions', 'observations')
        }
    assert counts == {
        'families': 5,
        'children': 6,
        'sessions': 24,
        'observations': 72,
    }


def test_family_structure_matches_demo(database):
    '''The selectors should expose the requested five-family hierarchy.'''
    families = get_available_families(database)
    structure = {
        family['family_name']: [
            child['first_name']
            for child in get_children_for_family(family['family_id'], database)
        ]
        for family in families
    }

    assert structure == {
        'Kovacs family': ['Maya', 'Leo'],
        'Martin family': ['Eli'],
        'Rossi family': ['Sofia'],
        'M\u00fcller family': ['Lina'],
        'Wilson family': ['Noah'],
    }


def test_parent_snapshot_uses_an_explicit_child(database):
    '''A snapshot should identify its requested child and count their sessions.'''
    snapshot = get_parent_snapshot(1, '2026-01', database)

    assert snapshot['child_name'] == 'Maya'
    assert snapshot['sessions_attended'] == 4


def test_isolated_low_score_does_not_trigger_follow_up(database):
    '''One low observation alone should not suggest contacting a family.'''
    _set_scores(database, 1, 'settles_and_recovers', [4, 2, 4, 4])

    result = evaluate_contact_rule(1, '2026-01', database)

    assert result['triggered'] is False


def test_consecutive_low_scores_trigger_follow_up(database):
    '''Two consecutive low scores in one dimension should trigger review.'''
    _set_scores(database, 1, 'settles_and_recovers', [4, 2, 2, 4])

    result = evaluate_contact_rule(1, '2026-01', database)

    assert result['triggered'] is True
    assert result['patterns'][0]['dimension'] == 'settles_and_recovers'
    assert result['patterns'][0]['scores'] == [2, 2]


def test_consent_withdrawal_is_independent(database):
    '''Withdrawing analytics must leave the other two purposes granted.'''
    set_consent(1, 'research_analytics', False, database)

    status = get_consent_status(1, database)

    assert status == {
        'service_delivery': True,
        'parent_reporting': True,
        'research_analytics': False,
    }


def test_four_eligible_children_are_suppressed(database):
    '''Four eligible children must return no group averages.'''
    result = get_group_summary([1, 2, 3, 4], '2026-01', database)

    assert result['eligible_children'] == 4
    assert result['suppressed'] is True
    assert result['averages'] is None


def test_three_of_six_eligible_children_are_suppressed(database):
    '''Eligibility counts should explain exclusions without exposing statistics.'''
    set_consent(4, 'research_analytics', False, database)
    set_consent(5, 'research_analytics', False, database)

    result = get_group_summary([1, 2, 3, 4, 5, 6], '2026-01', database)

    assert result['selected_children'] == 6
    assert result['eligible_children'] == 3
    assert result['excluded_children'] == 3
    assert result['averages'] is None


def test_five_eligible_children_receive_averages(database):
    '''Six selected children should yield the five-consenting-child aggregate.'''
    result = get_group_summary([1, 2, 3, 4, 5, 6], '2026-01', database)

    assert result['selected_children'] == 6
    assert result['eligible_children'] == 5
    assert result['excluded_children'] == 1
    assert result['suppressed'] is False
    assert result['averages'] == {
        'connects_with_others': 4.1,
        'settles_and_recovers': 3.4,
        'stays_with_task': 3.8,
    }
