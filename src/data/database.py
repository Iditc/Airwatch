"""SQLite database module for AirWatch."""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent.parent / "data" / "airwatch.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS stations (
    station_id TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    short_name TEXT,
    city       TEXT,
    latitude   REAL,
    longitude  REAL,
    pollutants TEXT,
    envista_id TEXT
);

CREATE TABLE IF NOT EXISTS measurements (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp  TEXT    NOT NULL,
    station_id TEXT    NOT NULL REFERENCES stations(station_id),
    pollutant  TEXT    NOT NULL,
    value      REAL    NOT NULL,
    unit       TEXT    NOT NULL DEFAULT 'ppm',
    source     TEXT    NOT NULL DEFAULT 'openaq',
    UNIQUE(timestamp, station_id, pollutant)
);

CREATE INDEX IF NOT EXISTS idx_meas_lookup
    ON measurements(station_id, pollutant, timestamp);

CREATE TABLE IF NOT EXISTS exceedances_israel (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    measurement_id INTEGER NOT NULL REFERENCES measurements(id),
    station_id     TEXT    NOT NULL REFERENCES stations(station_id),
    timestamp      TEXT    NOT NULL,
    pollutant      TEXT    NOT NULL,
    value          REAL    NOT NULL,
    threshold      REAL    NOT NULL,
    ratio          REAL    NOT NULL,
    severity       TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_exc_israel_lookup
    ON exceedances_israel(station_id, pollutant, timestamp);

CREATE TABLE IF NOT EXISTS exceedances_who (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    station_id   TEXT    NOT NULL REFERENCES stations(station_id),
    window_end   TEXT    NOT NULL,
    pollutant    TEXT    NOT NULL,
    window_hours INTEGER NOT NULL,
    avg_value    REAL    NOT NULL,
    threshold    REAL    NOT NULL,
    ratio        REAL    NOT NULL,
    severity     TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_exc_who_lookup
    ON exceedances_who(station_id, pollutant, window_end);

CREATE TABLE IF NOT EXISTS agent_results (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    exceedance_type TEXT NOT NULL CHECK(exceedance_type IN ('israel', 'who')),
    exceedance_id   INTEGER NOT NULL,
    agent_type      TEXT NOT NULL CHECK(agent_type IN ('root_cause', 'alert', 'sensor_health')),
    created_at      TEXT NOT NULL,
    result_json     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_agent_lookup
    ON agent_results(exceedance_type, exceedance_id);
"""


def get_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def create_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


def classify_severity(ratio: float) -> str:
    if ratio < 1.5:
        return "low"
    if ratio < 2.0:
        return "medium"
    return "high"
