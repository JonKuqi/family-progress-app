'''SQLite setup, CSV seeding, and consent persistence.'''

import csv
import sqlite3
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / 'data'
DATABASE_PATH = DATA_DIR / 'embreier.db'
SCHEMA_PATH = ROOT_DIR / 'sql' / 'schema.sql'

DIMENSIONS = (
    'settles_and_recovers',
    'stays_with_task',
    'connects_with_others',
)
PURPOSES = ('service_delivery', 'parent_reporting', 'research_analytics')

SEED_TABLES = (
    (
        'families.csv',
        'INSERT INTO families (family_id, family_name) '
        'VALUES (:family_id, :family_name)',
    ),
    (
        'children.csv',
        'INSERT INTO children (child_id, family_id, first_name) '
        'VALUES (:child_id, :family_id, :first_name)',
    ),
    (
        'sessions.csv',
        'INSERT INTO sessions (session_id, child_id, session_date) '
        'VALUES (:session_id, :child_id, :session_date)',
    ),
    (
        'observations.csv',
        'INSERT INTO observations (observation_id, session_id, dimension, score) '
        'VALUES (:observation_id, :session_id, :dimension, :score)',
    ),
    (
        'consents.csv',
        'INSERT INTO consents (family_id, purpose, granted) '
        'VALUES (:family_id, :purpose, :granted)',
    ),
)


class _ClosingConnection(sqlite3.Connection):
    '''Commit or roll back a context block, then release the database file.'''

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def get_connection(db_path: Path | str | None = None) -> sqlite3.Connection:
    '''Return a connection with foreign-key enforcement and named columns.'''
    path = Path(db_path) if db_path else DATABASE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, factory=_ClosingConnection)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA foreign_keys = ON')
    return connection


def initialize_database(db_path: Path | str | None = None) -> None:
    '''Create the database and load the static invented CSV data once.'''
    with get_connection(db_path) as connection:
        connection.executescript(SCHEMA_PATH.read_text(encoding='utf-8'))
        existing = connection.execute('SELECT COUNT(*) FROM families').fetchone()[0]
        if existing == 0:
            _seed_database(connection)


def set_consent(
    family_id: int,
    purpose: str,
    granted: bool,
    db_path: Path | str | None = None,
) -> None:
    '''Update one consent purpose without changing the other purposes.'''
    if purpose not in PURPOSES:
        raise ValueError(f'Unknown consent purpose: {purpose}')

    with get_connection(db_path) as connection:
        cursor = connection.execute(
            '''
            UPDATE consents
            SET granted = ?, updated_at = CURRENT_TIMESTAMP
            WHERE family_id = ? AND purpose = ?
            ''',
            (int(granted), family_id, purpose),
        )
        if cursor.rowcount == 0:
            raise ValueError('Consent record not found')


def reset_database(db_path: Path | str | None = None) -> None:
    '''Replace the local database with the original CSV demonstration data.'''
    path = Path(db_path) if db_path else DATABASE_PATH
    if path.exists():
        path.unlink()
    initialize_database(path)


def _seed_database(connection: sqlite3.Connection) -> None:
    '''Insert each static CSV file in foreign-key dependency order.'''
    for filename, statement in SEED_TABLES:
        connection.executemany(statement, _read_csv(filename))


def _read_csv(filename: str) -> list[dict[str, str]]:
    '''Read one invented seed dataset using Python's standard CSV parser.'''
    with (DATA_DIR / filename).open(encoding='utf-8', newline='') as source:
        return list(csv.DictReader(source))
