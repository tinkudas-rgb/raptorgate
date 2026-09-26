"""SQLite persistence layer for RaptorGate.

One file, one connection per request, foreign keys on. The schema is the
data model documented in DATA-MODEL.md; keep the two in sync.
"""

import sqlite3

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id            TEXT PRIMARY KEY,
    email         TEXT UNIQUE NOT NULL,
    name          TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('participant', 'judge', 'organizer', 'admin')),
    password_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token      TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id                TEXT PRIMARY KEY,
    name              TEXT NOT NULL,
    description       TEXT NOT NULL DEFAULT '',
    submissions_close TEXT NOT NULL,
    judging_close     TEXT,
    prizes            TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS tracks (
    id       TEXT PRIMARY KEY,
    event_id TEXT NOT NULL REFERENCES events(id),
    name     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS teams (
    id          TEXT PRIMARY KEY,
    event_id    TEXT NOT NULL REFERENCES events(id),
    name        TEXT NOT NULL,
    invite_code TEXT UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS team_members (
    team_id    TEXT NOT NULL REFERENCES teams(id),
    user_email TEXT NOT NULL,
    PRIMARY KEY (team_id, user_email)
);

CREATE TABLE IF NOT EXISTS projects (
    id           TEXT PRIMARY KEY,
    event_id     TEXT NOT NULL REFERENCES events(id),
    team_id      TEXT NOT NULL REFERENCES teams(id),
    track_id     TEXT NOT NULL REFERENCES tracks(id),
    title        TEXT NOT NULL,
    summary      TEXT NOT NULL DEFAULT '',
    repo_url     TEXT NOT NULL DEFAULT '',
    status       TEXT NOT NULL DEFAULT 'submitted' CHECK (status IN ('draft', 'submitted')),
    submitted_at TEXT
);

CREATE TABLE IF NOT EXISTS judges (
    user_id  TEXT PRIMARY KEY REFERENCES users(id),
    event_id TEXT NOT NULL REFERENCES events(id)
);

CREATE TABLE IF NOT EXISTS judge_tracks (
    user_id  TEXT NOT NULL REFERENCES judges(user_id),
    track_id TEXT NOT NULL REFERENCES tracks(id),
    PRIMARY KEY (user_id, track_id)
);

CREATE TABLE IF NOT EXISTS judge_assignments (
    judge_id   TEXT NOT NULL REFERENCES users(id),
    project_id TEXT NOT NULL REFERENCES projects(id),
    PRIMARY KEY (judge_id, project_id)
);

CREATE TABLE IF NOT EXISTS rubric (
    event_id  TEXT NOT NULL REFERENCES events(id),
    criterion TEXT NOT NULL,
    weight    REAL NOT NULL DEFAULT 1.0,
    PRIMARY KEY (event_id, criterion)
);

CREATE TABLE IF NOT EXISTS scores (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    judge_id   TEXT NOT NULL REFERENCES users(id),
    project_id TEXT NOT NULL REFERENCES projects(id),
    criteria   TEXT NOT NULL,
    comment    TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE (judge_id, project_id)
);
"""


def connect(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(conn):
    conn.executescript(SCHEMA)
    conn.commit()
