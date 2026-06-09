"""SQLite persistence for Asclepius.

Holds both imported Apple Health data and everything the user logs by hand
(food, water, workouts, body measurements, sleep, goals). Imported and manual
data live in the same tables, distinguished by a ``source`` column, so a
re-import never wipes a user's hand-entered history.
"""
from __future__ import annotations

import datetime as _dt
import json
import sqlite3
from pathlib import Path

from .config import COMMON_FOODS, DB_PATH

# Marker for rows that came from an Apple Health export. Anything the user types
# in by hand is stored as 'manual'. On re-import we only clear IMPORT rows.
SOURCE_IMPORT = "apple"
SOURCE_MANUAL = "manual"


SCHEMA = """
CREATE TABLE IF NOT EXISTS daily_metrics (
    metric TEXT NOT NULL,
    date   TEXT NOT NULL,
    value  REAL NOT NULL,
    min    REAL,
    max    REAL,
    count  INTEGER,
    unit   TEXT,
    source TEXT NOT NULL DEFAULT 'apple',
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
    awake_hours  REAL,
    source       TEXT NOT NULL DEFAULT 'apple'
);

CREATE TABLE IF NOT EXISTS workouts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    date         TEXT,
    activity     TEXT,
    type         TEXT NOT NULL DEFAULT 'other',
    duration_min REAL,
    distance_km  REAL,
    energy_kcal  REAL,
    exercises    TEXT,   -- JSON: [{name, sets:[{reps,weight}]}]
    notes        TEXT,
    source       TEXT NOT NULL DEFAULT 'apple',
    created_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_workouts_date ON workouts(date);

CREATE TABLE IF NOT EXISTS food_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    date       TEXT NOT NULL,
    meal       TEXT NOT NULL DEFAULT 'snack',
    name       TEXT NOT NULL,
    qty        REAL NOT NULL DEFAULT 1,
    serving    TEXT,
    kcal       REAL NOT NULL DEFAULT 0,
    protein    REAL NOT NULL DEFAULT 0,
    carbs      REAL NOT NULL DEFAULT 0,
    fat        REAL NOT NULL DEFAULT 0,
    source     TEXT NOT NULL DEFAULT 'manual',
    created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_food_date ON food_log(date);

CREATE TABLE IF NOT EXISTS water_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    date       TEXT NOT NULL,
    amount_ml  REAL NOT NULL,
    created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_water_date ON water_log(date);

CREATE TABLE IF NOT EXISTS goals (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    category    TEXT NOT NULL,
    label       TEXT NOT NULL,
    target      REAL,
    baseline    REAL,
    unit        TEXT,
    direction   TEXT NOT NULL DEFAULT 'increase',  -- increase | decrease | maintain
    target_date TEXT,
    status      TEXT NOT NULL DEFAULT 'active',     -- active | done | archived
    notes       TEXT,
    created_at  TEXT,
    updated_at  TEXT,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS foods (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    name     TEXT NOT NULL,
    category TEXT,
    serving  TEXT,
    kcal     REAL NOT NULL DEFAULT 0,
    protein  REAL NOT NULL DEFAULT 0,
    carbs    REAL NOT NULL DEFAULT 0,
    fat      REAL NOT NULL DEFAULT 0,
    builtin  INTEGER NOT NULL DEFAULT 1,
    uses     INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_foods_name ON foods(name);

CREATE TABLE IF NOT EXISTS achievements (
    key         TEXT PRIMARY KEY,
    unlocked_at TEXT
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- The single living health plan the coach maintains for the user.
CREATE TABLE IF NOT EXISTS plan (
    id         INTEGER PRIMARY KEY CHECK (id = 1),
    goal       TEXT,
    focus      TEXT,   -- JSON array of focus areas
    content    TEXT,   -- markdown plan body
    updated_at TEXT
);

-- A snapshot is written every time the plan is saved, so the coach (and the
-- user) can see how the plan has evolved.
CREATE TABLE IF NOT EXISTS plan_history (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    goal       TEXT,
    focus      TEXT,
    content    TEXT,
    saved_at   TEXT
);
"""


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path or DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}


def _migrate(conn: sqlite3.Connection) -> None:
    """Bring older databases up to the current schema in place.

    The first version of Asclepius stored only imported data and had no
    ``source`` columns or manual-logging tables. We add what's missing without
    touching existing rows.
    """
    # source columns on the originally-import-only tables
    for table in ("daily_metrics", "sleep"):
        if "source" not in _table_columns(conn, table):
            conn.execute(
                f"ALTER TABLE {table} ADD COLUMN source TEXT NOT NULL "
                f"DEFAULT '{SOURCE_IMPORT}'")

    # workouts gained several columns (and an id) over time. The very first
    # build had no `id` primary key — SQLite can't ALTER one in — so when it's
    # missing we rebuild the table and copy the old rows across.
    wcols = _table_columns(conn, "workouts")
    if wcols and "id" not in wcols:
        conn.execute("ALTER TABLE workouts RENAME TO workouts_legacy")
        conn.executescript(SCHEMA)  # recreates workouts (idempotent for the rest)
        conn.execute(
            "INSERT INTO workouts "
            "(date, activity, type, duration_min, distance_km, energy_kcal, source) "
            f"SELECT date, activity, 'cardio', duration_min, distance_km, "
            f"energy_kcal, '{SOURCE_IMPORT}' FROM workouts_legacy")
        conn.execute("DROP TABLE workouts_legacy")
        wcols = _table_columns(conn, "workouts")
    if wcols:  # ensure any other missing columns exist (newer-than-v1 builds)
        for col, ddl in (
            ("type", "TEXT NOT NULL DEFAULT 'other'"),
            ("exercises", "TEXT"),
            ("notes", "TEXT"),
            ("source", f"TEXT NOT NULL DEFAULT '{SOURCE_IMPORT}'"),
            ("created_at", "TEXT"),
        ):
            if col not in wcols:
                conn.execute(f"ALTER TABLE workouts ADD COLUMN {col} {ddl}")


def init_db(db_path: Path | None = None) -> None:
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)
        _seed_foods(conn)


def _now() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


def _today() -> str:
    return _dt.date.today().isoformat()


# ---------------------------------------------------------------------------
# Imported data
# ---------------------------------------------------------------------------
def replace_data(parsed: dict, db_path: Path | None = None) -> dict:
    """Load a freshly parsed export, replacing only previously-imported rows.

    Manual entries (source='manual') are left untouched.
    """
    init_db(db_path)
    with connect(db_path) as conn:
        conn.execute("DELETE FROM daily_metrics WHERE source = ?", (SOURCE_IMPORT,))
        conn.execute("DELETE FROM sleep WHERE source = ?", (SOURCE_IMPORT,))
        conn.execute("DELETE FROM workouts WHERE source = ?", (SOURCE_IMPORT,))
        conn.execute("DELETE FROM meta")

        conn.executemany(
            "INSERT OR REPLACE INTO daily_metrics "
            "(metric, date, value, min, max, count, unit, source) "
            "VALUES (:metric, :date, :value, :min, :max, :count, :unit, "
            f"'{SOURCE_IMPORT}')",
            parsed["daily"],
        )
        conn.executemany(
            "INSERT OR REPLACE INTO sleep "
            "(date, asleep_hours, in_bed_hours, rem_hours, deep_hours, "
            " core_hours, awake_hours, source) "
            "VALUES (:date, :asleep_hours, :in_bed_hours, :rem_hours, "
            f":deep_hours, :core_hours, :awake_hours, '{SOURCE_IMPORT}')",
            parsed["sleep"],
        )
        conn.executemany(
            "INSERT INTO workouts "
            "(date, activity, type, duration_min, distance_km, energy_kcal, source) "
            "VALUES (:date, :activity, 'cardio', :duration_min, :distance_km, "
            f":energy_kcal, '{SOURCE_IMPORT}')",
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
    """True once there's anything to coach on — imported or logged by hand."""
    init_db(db_path)
    with connect(db_path) as conn:
        for sql in (
            "SELECT 1 FROM daily_metrics LIMIT 1",
            "SELECT 1 FROM food_log LIMIT 1",
            "SELECT 1 FROM workouts LIMIT 1",
            "SELECT 1 FROM sleep LIMIT 1",
        ):
            if conn.execute(sql).fetchone():
                return True
    return False


def has_import(db_path: Path | None = None) -> bool:
    init_db(db_path)
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT 1 FROM daily_metrics WHERE source = ? LIMIT 1",
            (SOURCE_IMPORT,)).fetchone()
    return bool(row)


# ---------------------------------------------------------------------------
# Seed food database
# ---------------------------------------------------------------------------
def _seed_foods(conn: sqlite3.Connection) -> None:
    row = conn.execute("SELECT COUNT(*) AS n FROM foods WHERE builtin = 1").fetchone()
    if row["n"]:
        return
    conn.executemany(
        "INSERT INTO foods (name, category, serving, kcal, protein, carbs, fat, builtin) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 1)",
        [(name, cat, serving, kcal, p, c, f)
         for (name, cat, serving, kcal, p, c, f) in COMMON_FOODS],
    )


# ---------------------------------------------------------------------------
# The living plan
# ---------------------------------------------------------------------------
def save_plan(goal: str, focus: list[str], content: str,
              db_path: Path | None = None) -> dict:
    """Create or replace the user's living health plan, snapshotting history."""
    init_db(db_path)
    now = _now()
    focus_json = json.dumps(focus or [])
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO plan (id, goal, focus, content, updated_at) "
            "VALUES (1, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET goal=excluded.goal, "
            "focus=excluded.focus, content=excluded.content, "
            "updated_at=excluded.updated_at",
            (goal, focus_json, content, now),
        )
        conn.execute(
            "INSERT INTO plan_history (goal, focus, content, saved_at) "
            "VALUES (?, ?, ?, ?)",
            (goal, focus_json, content, now),
        )
    return get_plan(db_path)


def get_plan(db_path: Path | None = None) -> dict | None:
    init_db(db_path)
    with connect(db_path) as conn:
        row = conn.execute("SELECT * FROM plan WHERE id = 1").fetchone()
    if not row:
        return None
    try:
        focus = json.loads(row["focus"]) if row["focus"] else []
    except (json.JSONDecodeError, TypeError):
        focus = []
    return {
        "goal": row["goal"],
        "focus": focus,
        "content": row["content"],
        "updated_at": row["updated_at"],
    }


def plan_history(limit: int = 20, db_path: Path | None = None) -> list[dict]:
    init_db(db_path)
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT goal, focus, saved_at FROM plan_history "
            "ORDER BY saved_at DESC LIMIT ?", (limit,)).fetchall()
    out = []
    for r in rows:
        try:
            focus = json.loads(r["focus"]) if r["focus"] else []
        except (json.JSONDecodeError, TypeError):
            focus = []
        out.append({"goal": r["goal"], "focus": focus, "saved_at": r["saved_at"]})
    return out


def get_meta(db_path: Path | None = None) -> dict:
    init_db(db_path)
    with connect(db_path) as conn:
        rows = conn.execute("SELECT key, value FROM meta").fetchall()
    out = {}
    for r in rows:
        try:
            out[r["key"]] = json.loads(r["value"])
        except (json.JSONDecodeError, TypeError):
            out[r["key"]] = r["value"]
    return out
