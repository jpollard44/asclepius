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

from .config import COMMON_FOODS, DAILY_GOAL_METRICS, DB_PATH

# Marker for rows that came from an Apple Health export. Anything the user types
# in by hand is stored as 'manual'. On re-import we only clear IMPORT rows.
SOURCE_IMPORT = "apple"
SOURCE_MANUAL = "manual"
# Smart-scale body-composition imports. Kept distinct from 'apple' so a
# re-import of an Apple Health export (which clears SOURCE_IMPORT rows) never
# wipes scale data, and distinct from 'manual' so the two are reportable apart.
SOURCE_SCALE = "scale"


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
    fiber      REAL,
    sugar      REAL,
    sodium     REAL,   -- mg
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

-- Quick-add favorites: meals/drinks the user logs over and over, saved once so
-- they can be logged with a single tap. Macros are stored per single serving
-- and copied straight into food_log when logged. Survives a re-import (it's
-- user-authored, like manual food). Optional micros are nullable.
CREATE TABLE IF NOT EXISTS favorites (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    description TEXT,                               -- ingredients / details
    calories    REAL NOT NULL DEFAULT 0,
    protein_g   REAL NOT NULL DEFAULT 0,
    carbs_g     REAL NOT NULL DEFAULT 0,
    fat_g       REAL NOT NULL DEFAULT 0,
    fiber_g     REAL,
    sugar_g     REAL,
    sodium_mg   REAL,
    category    TEXT NOT NULL DEFAULT 'snack',      -- breakfast/lunch/dinner/snack/drink
    sort_order  INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_favorites_order ON favorites(sort_order);

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

-- Persistent coach chat history, so conversations survive page reloads and the
-- advisor can load prior turns back into its context. tool_calls/tool_results
-- hold the JSON the coach used on a turn (nullable; kept for the record).
CREATE TABLE IF NOT EXISTS chat_messages (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp    TEXT NOT NULL,
    role         TEXT NOT NULL,              -- 'user' | 'assistant'
    content      TEXT NOT NULL DEFAULT '',
    tool_calls   TEXT,                       -- JSON, nullable
    tool_results TEXT                        -- JSON, nullable
);
CREATE INDEX IF NOT EXISTS idx_chat_messages_id ON chat_messages(id);

-- Web push subscriptions, one row per browser/device the user enabled. The
-- whole PushSubscription JSON is kept verbatim so pywebpush can send to it.
-- NOT cleared on re-import — push survives uploading a new Apple Health export.
CREATE TABLE IF NOT EXISTS push_subscriptions (
    endpoint     TEXT PRIMARY KEY,
    subscription TEXT NOT NULL,   -- full PushSubscription JSON
    user_agent   TEXT,
    created_at   TEXT
);

-- Small key/value store for app settings that must outlive a re-import
-- (notification preferences, last-activity timestamp). Deliberately separate
-- from `meta`, which replace_data() wipes on every import.
CREATE TABLE IF NOT EXISTS app_kv (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- One row per notification actually sent, so a restart or overlapping job never
-- double-fires the same reminder. dedup_key is e.g. "breakfast:2026-06-10" or
-- "water:2026-06-10:14".
CREATE TABLE IF NOT EXISTS notification_log (
    dedup_key TEXT PRIMARY KEY,
    ntype     TEXT NOT NULL,
    title     TEXT,
    body      TEXT,
    sent_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_notif_sent ON notification_log(sent_at);
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

    # food_log gained micronutrient columns for photo-based logging.
    food_cols = _table_columns(conn, "food_log")
    if food_cols:
        for col in ("fiber", "sugar", "sodium"):
            if col not in food_cols:
                conn.execute(f"ALTER TABLE food_log ADD COLUMN {col} REAL")

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

    # Persistent coach chat history is newer than the first builds. init_db runs
    # SCHEMA (CREATE IF NOT EXISTS) before this, so the table normally already
    # exists — but create it idempotently here too so an older DB picked up
    # outside init_db is brought current.
    conn.execute(
        "CREATE TABLE IF NOT EXISTS chat_messages ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " timestamp TEXT NOT NULL,"
        " role TEXT NOT NULL,"
        " content TEXT NOT NULL DEFAULT '',"
        " tool_calls TEXT,"
        " tool_results TEXT)")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_chat_messages_id ON chat_messages(id)")


def init_db(db_path: Path | None = None) -> None:
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)
        _seed_foods(conn)
        _seed_favorites(conn)


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


def _seed_favorites(conn: sqlite3.Connection) -> None:
    """Pre-load the user's regular quick-add items on first run.

    Only runs while the table is empty, so a user who later clears or edits
    their favorites never has these re-appear.
    """
    if conn.execute("SELECT COUNT(*) AS n FROM favorites").fetchone()["n"]:
        return
    now = _now()
    seeds = [
        # name, description, kcal, P, C, F, category
        ("Protein Matcha",
         "12 oz whole milk, 2 scoops OM Master Blend, 3 tbsp OM matcha latte powder",
         445, 43, 18, 11, "drink"),
        ("Chobani 30g Protein Drink, Strawberry",
         "Single bottle", 170, 30, 8, 2, "drink"),
    ]
    conn.executemany(
        "INSERT INTO favorites "
        "(name, description, calories, protein_g, carbs_g, fat_g, category, "
        " sort_order, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [(name, desc, kcal, p, c, f, cat, i, now)
         for i, (name, desc, kcal, p, c, f, cat) in enumerate(seeds)],
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


# ---------------------------------------------------------------------------
# Coach chat history
# ---------------------------------------------------------------------------
def _loads(value):
    if not value:
        return None
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return value


def _chat_row(r: sqlite3.Row) -> dict:
    return {
        "id": r["id"],
        "timestamp": r["timestamp"],
        "role": r["role"],
        "content": r["content"] or "",
        "tool_calls": _loads(r["tool_calls"]),
        "tool_results": _loads(r["tool_results"]),
    }


def add_chat_message(role: str, content: str, tool_calls=None,
                     tool_results=None, db_path: Path | None = None) -> dict:
    """Append one message to the persistent coach conversation."""
    init_db(db_path)
    ts = _now()
    with connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO chat_messages "
            "(timestamp, role, content, tool_calls, tool_results) "
            "VALUES (?, ?, ?, ?, ?)",
            (ts, role, content or "",
             json.dumps(tool_calls) if tool_calls is not None else None,
             json.dumps(tool_results) if tool_results is not None else None),
        )
        msg_id = cur.lastrowid
    return {"id": msg_id, "timestamp": ts, "role": role, "content": content or "",
            "tool_calls": tool_calls, "tool_results": tool_results}


def get_chat_history(limit: int = 50, before: int | None = None,
                     db_path: Path | None = None) -> dict:
    """Return a page of chat messages in chronological (oldest-first) order.

    Without ``before`` this is the most recent ``limit`` messages. With
    ``before`` (a message id) it's the ``limit`` messages immediately older than
    that id — the building block for scrolling back through history. ``has_more``
    is True when still-older messages exist beyond the page returned.
    """
    init_db(db_path)
    limit = max(1, min(int(limit or 50), 200))
    with connect(db_path) as conn:
        if before:
            rows = conn.execute(
                "SELECT * FROM chat_messages WHERE id < ? ORDER BY id DESC LIMIT ?",
                (int(before), limit)).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM chat_messages ORDER BY id DESC LIMIT ?",
                (limit,)).fetchall()
        messages = [_chat_row(r) for r in reversed(rows)]
        has_more = False
        if messages:
            has_more = conn.execute(
                "SELECT 1 FROM chat_messages WHERE id < ? LIMIT 1",
                (messages[0]["id"],)).fetchone() is not None
    return {"messages": messages, "has_more": has_more}


def recent_chat_messages(limit: int = 40,
                         db_path: Path | None = None) -> list[dict]:
    """Recent turns as plain {role, content} pairs for the advisor's context.

    Trimmed to start on a user turn so it can be handed straight to the model.
    """
    history = get_chat_history(limit=limit, db_path=db_path)["messages"]
    msgs = [{"role": m["role"], "content": m["content"]}
            for m in history if m["content"]]
    while msgs and msgs[0]["role"] != "user":
        msgs.pop(0)
    return msgs


def clear_chat_history(db_path: Path | None = None) -> int:
    """Delete the entire coach conversation. Returns rows removed."""
    init_db(db_path)
    with connect(db_path) as conn:
        return conn.execute("DELETE FROM chat_messages").rowcount


# ---------------------------------------------------------------------------
# Web push subscriptions
# ---------------------------------------------------------------------------
def save_push_subscription(subscription: dict, user_agent: str = "",
                           db_path: Path | None = None) -> None:
    """Store (or refresh) a browser push subscription, keyed by its endpoint."""
    init_db(db_path)
    endpoint = subscription.get("endpoint")
    if not endpoint:
        raise ValueError("subscription is missing an endpoint")
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO push_subscriptions (endpoint, subscription, user_agent, created_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(endpoint) DO UPDATE SET subscription=excluded.subscription, "
            "user_agent=excluded.user_agent",
            (endpoint, json.dumps(subscription), user_agent, _now()))


def list_push_subscriptions(db_path: Path | None = None) -> list[dict]:
    """Every stored subscription as a parsed PushSubscription dict."""
    init_db(db_path)
    with connect(db_path) as conn:
        rows = conn.execute("SELECT subscription FROM push_subscriptions").fetchall()
    out = []
    for r in rows:
        try:
            out.append(json.loads(r["subscription"]))
        except (json.JSONDecodeError, TypeError):
            continue
    return out


def delete_push_subscription(endpoint: str, db_path: Path | None = None) -> bool:
    """Remove a subscription (on unsubscribe, or when the push service 410s it)."""
    init_db(db_path)
    with connect(db_path) as conn:
        cur = conn.execute(
            "DELETE FROM push_subscriptions WHERE endpoint = ?", (endpoint,))
    return cur.rowcount > 0


def count_push_subscriptions(db_path: Path | None = None) -> int:
    init_db(db_path)
    with connect(db_path) as conn:
        return conn.execute(
            "SELECT COUNT(*) AS n FROM push_subscriptions").fetchone()["n"]


# ---------------------------------------------------------------------------
# App key/value store (survives re-import)
# ---------------------------------------------------------------------------
def kv_get(key: str, default=None, db_path: Path | None = None):
    init_db(db_path)
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT value FROM app_kv WHERE key = ?", (key,)).fetchone()
    if not row:
        return default
    try:
        return json.loads(row["value"])
    except (json.JSONDecodeError, TypeError):
        return row["value"]


def kv_set(key: str, value, db_path: Path | None = None) -> None:
    init_db(db_path)
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO app_kv (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value)))


# ---------------------------------------------------------------------------
# Personalized daily goals (survives re-import via app_kv)
# ---------------------------------------------------------------------------
def get_daily_goals(db_path: Path | None = None) -> dict:
    """The user's daily target for each tracked metric, with any saved overrides.

    Returns an ordered dict keyed by metric (calories, protein, …); each value
    carries the catalogue defaults from config plus the live ``target`` (an
    override if the user edited it, otherwise the personalized default) and a
    ``customized`` flag so the UI can show what's been changed from recommended.
    """
    overrides = kv_get("daily_goals", default={}, db_path=db_path) or {}
    out: dict[str, dict] = {}
    for key, cfg in DAILY_GOAL_METRICS.items():
        ov = overrides.get(key)
        out[key] = {
            "key": key,
            **cfg,
            "target": ov if ov is not None else cfg["target"],
            "default": cfg["target"],
            "customized": ov is not None,
        }
    return out


def set_daily_goals(patch: dict, db_path: Path | None = None) -> dict:
    """Apply a partial update to the daily targets and persist the overrides.

    ``patch`` maps a metric key to a new target. A value of ``None`` clears the
    override, resetting that metric to its personalized default. Unknown keys
    are ignored. Returns the full goals view (same shape as get_daily_goals).
    """
    overrides = kv_get("daily_goals", default={}, db_path=db_path) or {}
    for key, val in (patch or {}).items():
        if key not in DAILY_GOAL_METRICS:
            continue
        if val is None:
            overrides.pop(key, None)
        else:
            try:
                overrides[key] = max(0.0, float(val))
            except (TypeError, ValueError):
                continue
    kv_set("daily_goals", overrides, db_path=db_path)
    return get_daily_goals(db_path=db_path)


def daily_goal_target(key: str, db_path: Path | None = None) -> float | None:
    """Just the live numeric target for one metric (or None if not tracked)."""
    goals = get_daily_goals(db_path=db_path)
    g = goals.get(key)
    return g["target"] if g else None


def touch_activity(db_path: Path | None = None) -> None:
    """Record that the app just talked to the API (used to suppress reminders
    while it's open in the foreground). Written cheaply on every API call."""
    kv_set("last_activity", _now(), db_path=db_path)


def last_activity(db_path: Path | None = None) -> str | None:
    """ISO timestamp of the most recent API call, or None if never seen."""
    return kv_get("last_activity", default=None, db_path=db_path)


# ---------------------------------------------------------------------------
# Notification de-duplication log
# ---------------------------------------------------------------------------
def notification_already_sent(dedup_key: str, db_path: Path | None = None) -> bool:
    init_db(db_path)
    with connect(db_path) as conn:
        return conn.execute(
            "SELECT 1 FROM notification_log WHERE dedup_key = ?",
            (dedup_key,)).fetchone() is not None


def record_notification(dedup_key: str, ntype: str, title: str, body: str,
                        db_path: Path | None = None) -> bool:
    """Mark a notification as sent. Returns False if this dedup_key already fired
    (the INSERT is ignored), so callers can use it as an atomic claim."""
    init_db(db_path)
    with connect(db_path) as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO notification_log "
            "(dedup_key, ntype, title, body, sent_at) VALUES (?, ?, ?, ?, ?)",
            (dedup_key, ntype, title, body, _now()))
    return cur.rowcount > 0


def recent_notifications(limit: int = 20, db_path: Path | None = None) -> list[dict]:
    init_db(db_path)
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT dedup_key, ntype, title, body, sent_at FROM notification_log "
            "ORDER BY sent_at DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


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
