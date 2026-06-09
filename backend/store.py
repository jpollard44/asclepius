"""SQLite persistence for parsed Apple Health data."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .config import DB_PATH


SCHEMA = """
CREATE TABLE IF NOT EXISTS daily_metrics (
    metric TEXT NOT NULL,
    date   TEXT NOT NULL,
    value  REAL NOT NULL,
    min    REAL,
    max    REAL,
    count  INTEGER,
    unit   TEXT,
    PRIMARY KEY (metric, date)
);
CREATE INDEX IF NOT EXISTS idx_daily_metric ON daily_metrics(metric);

CREATE TABLE IF NOT EXISTS sleep (
    date         TEXT PRIMARY KEY,
    asleep_hours REAL,
    in_bed_hours REAL,
    rem_hours    REAL,
    deep_hours   REAL,
    core_hours   REAL,
    awake_hours  REAL
);

CREATE TABLE IF NOT EXISTS workouts (
    date         TEXT,
    activity     TEXT,
    duration_min REAL,
    distance_km  REAL,
    energy_kcal  REAL
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path or DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path | None = None) -> None:
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)


def replace_data(parsed: dict, db_path: Path | None = None) -> dict:
    """Wipe existing data and load a freshly parsed export. Returns counts."""
    init_db(db_path)
    with connect(db_path) as conn:
        conn.execute("DELETE FROM daily_metrics")
        conn.execute("DELETE FROM sleep")
        conn.execute("DELETE FROM workouts")
        conn.execute("DELETE FROM meta")

        conn.executemany(
            "INSERT OR REPLACE INTO daily_metrics "
            "(metric, date, value, min, max, count, unit) "
            "VALUES (:metric, :date, :value, :min, :max, :count, :unit)",
            parsed["daily"],
        )
        conn.executemany(
            "INSERT OR REPLACE INTO sleep "
            "(date, asleep_hours, in_bed_hours, rem_hours, deep_hours, "
            " core_hours, awake_hours) "
            "VALUES (:date, :asleep_hours, :in_bed_hours, :rem_hours, "
            ":deep_hours, :core_hours, :awake_hours)",
            parsed["sleep"],
        )
        conn.executemany(
            "INSERT INTO workouts "
            "(date, activity, duration_min, distance_km, energy_kcal) "
            "VALUES (:date, :activity, :duration_min, :distance_km, :energy_kcal)",
            parsed["workouts"],
        )
        meta = parsed["meta"]
        conn.executemany(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
            [(k, json.dumps(v)) for k, v in meta.items()],
        )

    return {
        "daily_rows": len(parsed["daily"]),
        "sleep_nights": len(parsed["sleep"]),
        "workouts": len(parsed["workouts"]),
    }


def has_data(db_path: Path | None = None) -> bool:
    init_db(db_path)
    with connect(db_path) as conn:
        row = conn.execute("SELECT COUNT(*) AS n FROM daily_metrics").fetchone()
        return row["n"] > 0


def get_meta(db_path: Path | None = None) -> dict:
    with connect(db_path) as conn:
        rows = conn.execute("SELECT key, value FROM meta").fetchall()
    out = {}
    for r in rows:
        try:
            out[r["key"]] = json.loads(r["value"])
        except (json.JSONDecodeError, TypeError):
            out[r["key"]] = r["value"]
    return out
