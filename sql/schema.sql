PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS families (
    family_id INTEGER PRIMARY KEY,
    family_name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS children (
    child_id INTEGER PRIMARY KEY,
    family_id INTEGER NOT NULL REFERENCES families(family_id),
    first_name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id INTEGER PRIMARY KEY,
    child_id INTEGER NOT NULL REFERENCES children(child_id),
    session_date TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS observations (
    observation_id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES sessions(session_id),
    dimension TEXT NOT NULL,
    score INTEGER NOT NULL CHECK (score BETWEEN 1 AND 5),
    UNIQUE (session_id, dimension),
    CHECK (dimension IN ('settles_and_recovers', 'stays_with_task', 'connects_with_others'))
);

CREATE TABLE IF NOT EXISTS consents (
    family_id INTEGER NOT NULL REFERENCES families(family_id),
    purpose TEXT NOT NULL,
    granted INTEGER NOT NULL CHECK (granted IN (0, 1)),
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (family_id, purpose),
    CHECK (purpose IN ('service_delivery', 'parent_reporting', 'research_analytics'))
);
