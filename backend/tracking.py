"""CRUD for everything the user logs by hand.

Food, water, workouts, body measurements, sleep, and goals. Body measurements
and manual sleep share the imported tables (tagged source='manual') so they
appear on the same charts and survive a re-import.
"""
from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

from .config import (
    DEFAULT_WATER_GOAL_ML,
    GOAL_CATEGORIES,
    MANUAL_METRICS,
)
from .store import SOURCE_MANUAL, SOURCE_SCALE, connect, init_db


def _now() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


def _today() -> str:
    return _dt.date.today().isoformat()


def _norm_date(date: str | None) -> str:
    return date or _today()


# ---------------------------------------------------------------------------
# Food database (lookup / search)
# ---------------------------------------------------------------------------
def search_foods(query: str = "", limit: int = 30, db_path: Path | None = None) -> list[dict]:
    """Search the food database, most-used first. Empty query → common foods."""
    init_db(db_path)
    with connect(db_path) as conn:
        if query.strip():
            rows = conn.execute(
                "SELECT * FROM foods WHERE name LIKE ? "
                "ORDER BY uses DESC, name LIMIT ?",
                (f"%{query.strip()}%", limit)).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM foods ORDER BY uses DESC, builtin DESC, name LIMIT ?",
                (limit,)).fetchall()
    return [dict(r) for r in rows]


def upsert_food(name: str, kcal: float, protein: float, carbs: float, fat: float,
                serving: str = "", category: str = "custom",
                db_path: Path | None = None) -> dict:
    """Add a custom food to the database (or return the existing match)."""
    init_db(db_path)
    name = name.strip()
    with connect(db_path) as conn:
        existing = conn.execute(
            "SELECT * FROM foods WHERE name = ? COLLATE NOCASE", (name,)).fetchone()
        if existing:
            return dict(existing)
        cur = conn.execute(
            "INSERT INTO foods (name, category, serving, kcal, protein, carbs, fat, builtin) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 0)",
            (name, category, serving, kcal, protein, carbs, fat))
        fid = cur.lastrowid
        row = conn.execute("SELECT * FROM foods WHERE id = ?", (fid,)).fetchone()
    return dict(row)


# ---------------------------------------------------------------------------
# Food log
# ---------------------------------------------------------------------------
def add_food(name: str, kcal: float, protein: float = 0, carbs: float = 0,
             fat: float = 0, meal: str = "snack", qty: float = 1,
             serving: str = "", date: str | None = None,
             food_id: int | None = None, fiber: float | None = None,
             sugar: float | None = None, sodium: float | None = None,
             db_path: Path | None = None) -> dict:
    """Log a food entry. Macros are per single serving; qty scales them.

    ``fiber``/``sugar`` are grams and ``sodium`` is milligrams (optional micros,
    e.g. estimated from a food photo); they're scaled by ``qty`` like the macros.
    """
    init_db(db_path)
    date = _norm_date(date)
    scale = lambda v: v * qty if v is not None else None  # noqa: E731
    with connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO food_log "
            "(date, meal, name, qty, serving, kcal, protein, carbs, fat, "
            " fiber, sugar, sodium, source, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (date, meal, name.strip(), qty, serving,
             kcal * qty, protein * qty, carbs * qty, fat * qty,
             scale(fiber), scale(sugar), scale(sodium),
             SOURCE_MANUAL, _now()))
        eid = cur.lastrowid
        if food_id:
            conn.execute("UPDATE foods SET uses = uses + 1 WHERE id = ?", (food_id,))
        row = conn.execute("SELECT * FROM food_log WHERE id = ?", (eid,)).fetchone()
    return dict(row)


def list_food(date: str | None = None, db_path: Path | None = None) -> dict:
    """All food logged on a day, grouped by meal, with totals."""
    init_db(db_path)
    date = _norm_date(date)
    with connect(db_path) as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM food_log WHERE date = ? ORDER BY created_at", (date,))]
    totals = {"kcal": 0.0, "protein": 0.0, "carbs": 0.0, "fat": 0.0}
    by_meal: dict[str, list] = {}
    for r in rows:
        by_meal.setdefault(r["meal"], []).append(r)
        for k in totals:
            totals[k] += r[k] or 0
    totals = {k: round(v, 1) for k, v in totals.items()}
    return {"date": date, "entries": rows, "by_meal": by_meal, "totals": totals}


def recent_food(days: int = 7, limit: int = 50,
                db_path: Path | None = None) -> list[dict]:
    """Recent individual food-log entries (most recent first) over a window."""
    init_db(db_path)
    cutoff = (_dt.date.today() - _dt.timedelta(days=days)).isoformat()
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT id, date, meal, name, qty, serving, kcal, protein, carbs, fat, "
            "fiber, sugar, sodium FROM food_log WHERE date >= ? "
            "ORDER BY date DESC, created_at DESC LIMIT ?",
            (cutoff, limit)).fetchall()
    return [dict(r) for r in rows]


def delete_food(entry_id: int, db_path: Path | None = None) -> bool:
    init_db(db_path)
    with connect(db_path) as conn:
        cur = conn.execute("DELETE FROM food_log WHERE id = ?", (entry_id,))
    return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Water log
# ---------------------------------------------------------------------------
def add_water(amount_ml: float, date: str | None = None,
              db_path: Path | None = None) -> dict:
    init_db(db_path)
    date = _norm_date(date)
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO water_log (date, amount_ml, created_at) VALUES (?, ?, ?)",
            (date, amount_ml, _now()))
    return get_water(date, db_path=db_path)


def get_water(date: str | None = None, db_path: Path | None = None) -> dict:
    init_db(db_path)
    date = _norm_date(date)
    goal = _water_goal(db_path)
    with connect(db_path) as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM water_log WHERE date = ? ORDER BY created_at", (date,))]
    total = round(sum(r["amount_ml"] for r in rows), 0)
    return {"date": date, "total_ml": total, "goal_ml": goal,
            "pct": round(total / goal * 100, 0) if goal else 0, "entries": rows}


def water_series(days: int = 30, db_path: Path | None = None) -> list[dict]:
    init_db(db_path)
    cutoff = (_dt.date.today() - _dt.timedelta(days=days)).isoformat()
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT date, ROUND(SUM(amount_ml)) AS total_ml FROM water_log "
            "WHERE date >= ? GROUP BY date ORDER BY date", (cutoff,)).fetchall()
    return [dict(r) for r in rows]


def delete_water(entry_id: int, db_path: Path | None = None) -> bool:
    init_db(db_path)
    with connect(db_path) as conn:
        cur = conn.execute("DELETE FROM water_log WHERE id = ?", (entry_id,))
    return cur.rowcount > 0


def _water_goal(db_path: Path | None = None) -> float:
    """The user's daily water goal, from an active water goal or the default."""
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT target FROM goals WHERE category = 'water' AND status = 'active' "
            "ORDER BY created_at DESC LIMIT 1").fetchone()
    if row and row["target"]:
        return float(row["target"])
    return float(DEFAULT_WATER_GOAL_ML)


# ---------------------------------------------------------------------------
# Workouts
# ---------------------------------------------------------------------------
def add_workout(activity: str, type: str = "other", date: str | None = None,
                duration_min: float | None = None, distance_km: float | None = None,
                energy_kcal: float | None = None, exercises: list | None = None,
                notes: str = "", db_path: Path | None = None) -> dict:
    """Log a workout. Strength workouts carry an ``exercises`` list of
    {name, sets: [{reps, weight}]}; cardio carries distance/duration."""
    init_db(db_path)
    date = _norm_date(date)
    ex_json = json.dumps(exercises) if exercises else None
    with connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO workouts "
            "(date, activity, type, duration_min, distance_km, energy_kcal, "
            " exercises, notes, source, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (date, activity.strip() or "Workout", type, duration_min, distance_km,
             energy_kcal, ex_json, notes, SOURCE_MANUAL, _now()))
        wid = cur.lastrowid
        row = conn.execute("SELECT * FROM workouts WHERE id = ?", (wid,)).fetchone()
    return _workout_row(row)


def list_workouts(days: int = 90, limit: int = 200,
                  db_path: Path | None = None) -> list[dict]:
    init_db(db_path)
    cutoff = (_dt.date.today() - _dt.timedelta(days=days)).isoformat()
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM workouts WHERE date >= ? "
            "ORDER BY date DESC, id DESC LIMIT ?", (cutoff, limit)).fetchall()
    return [_workout_row(r) for r in rows]


def delete_workout(workout_id: int, db_path: Path | None = None) -> bool:
    init_db(db_path)
    with connect(db_path) as conn:
        cur = conn.execute("DELETE FROM workouts WHERE id = ?", (workout_id,))
    return cur.rowcount > 0


def _workout_row(row) -> dict:
    d = dict(row)
    if d.get("exercises"):
        try:
            d["exercises"] = json.loads(d["exercises"])
        except (json.JSONDecodeError, TypeError):
            d["exercises"] = []
    else:
        d["exercises"] = []
    return d


# ---------------------------------------------------------------------------
# Body measurements & manual metrics
# ---------------------------------------------------------------------------
def log_metric(metric: str, value: float, date: str | None = None,
               db_path: Path | None = None) -> dict:
    """Record a manual body/vitals measurement into daily_metrics.

    Stored with source='manual'; overwrites any manual value already logged
    for that metric/day (a re-import won't clobber it).
    """
    init_db(db_path)
    date = _norm_date(date)
    cfg = MANUAL_METRICS.get(metric, {})
    unit = cfg.get("unit", "")
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO daily_metrics (metric, date, value, min, max, count, unit, source) "
            "VALUES (?, ?, ?, ?, ?, 1, ?, ?) "
            "ON CONFLICT(metric, date) DO UPDATE SET value=excluded.value, "
            "min=excluded.value, max=excluded.value, unit=excluded.unit, "
            "source=excluded.source",
            (metric, date, value, value, value, unit, SOURCE_MANUAL))
    return {"metric": metric, "date": date, "value": value, "unit": unit}


def log_body_metrics(date: str | None, values: dict[str, float | None],
                     source: str = SOURCE_SCALE,
                     db_path: Path | None = None) -> list[str]:
    """Write several body-composition metrics for one date as daily_metrics rows.

    ``values`` maps a metric key (e.g. ``"muscle_mass"``) to a value already in
    that metric's canonical unit (kg, %, kcal, …); ``None`` values are skipped.
    Each metric/day is upserted, so re-importing the same reading is idempotent.
    Used by the smart-scale importer (source='scale').
    """
    init_db(db_path)
    date = _norm_date(date)
    written: list[str] = []
    with connect(db_path) as conn:
        for metric, value in values.items():
            if value is None:
                continue
            unit = MANUAL_METRICS.get(metric, {}).get("unit", "")
            conn.execute(
                "INSERT INTO daily_metrics "
                "(metric, date, value, min, max, count, unit, source) "
                "VALUES (?, ?, ?, ?, ?, 1, ?, ?) "
                "ON CONFLICT(metric, date) DO UPDATE SET value=excluded.value, "
                "min=excluded.value, max=excluded.value, unit=excluded.unit, "
                "source=excluded.source",
                (metric, date, value, value, value, unit, source))
            written.append(metric)
    return written


def log_sleep(date: str | None, asleep_hours: float, in_bed_hours: float | None = None,
              rem_hours: float | None = None, deep_hours: float | None = None,
              db_path: Path | None = None) -> dict:
    """Record a night of sleep by hand (source='manual')."""
    init_db(db_path)
    date = _norm_date(date)
    in_bed = in_bed_hours if in_bed_hours is not None else asleep_hours
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO sleep "
            "(date, asleep_hours, in_bed_hours, rem_hours, deep_hours, core_hours, "
            " awake_hours, source) VALUES (?, ?, ?, ?, ?, 0, 0, ?) "
            "ON CONFLICT(date) DO UPDATE SET asleep_hours=excluded.asleep_hours, "
            "in_bed_hours=excluded.in_bed_hours, rem_hours=excluded.rem_hours, "
            "deep_hours=excluded.deep_hours, source=excluded.source",
            (date, asleep_hours, in_bed, rem_hours, deep_hours, SOURCE_MANUAL))
    return {"date": date, "asleep_hours": asleep_hours}


# ---------------------------------------------------------------------------
# Goals
# ---------------------------------------------------------------------------
def create_goal(category: str, label: str, target: float | None = None,
                baseline: float | None = None, unit: str = "",
                direction: str = "increase", target_date: str | None = None,
                notes: str = "", db_path: Path | None = None) -> dict:
    init_db(db_path)
    cfg = GOAL_CATEGORIES.get(category, {})
    unit = unit or cfg.get("unit", "")
    label = label or cfg.get("label", category)
    now = _now()
    with connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO goals "
            "(category, label, target, baseline, unit, direction, target_date, "
            " status, notes, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)",
            (category, label, target, baseline, unit, direction, target_date,
             notes, now, now))
        gid = cur.lastrowid
        row = conn.execute("SELECT * FROM goals WHERE id = ?", (gid,)).fetchone()
    return dict(row)


def list_goals(status: str | None = "active", db_path: Path | None = None) -> list[dict]:
    init_db(db_path)
    with connect(db_path) as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM goals WHERE status = ? ORDER BY created_at DESC",
                (status,)).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM goals ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]


def update_goal(goal_id: int, db_path: Path | None = None, **fields) -> dict | None:
    init_db(db_path)
    allowed = {"label", "target", "baseline", "unit", "direction", "target_date",
               "status", "notes"}
    sets = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not sets:
        return get_goal(goal_id, db_path=db_path)
    sets["updated_at"] = _now()
    if sets.get("status") == "done":
        sets["completed_at"] = _now()
    cols = ", ".join(f"{k} = ?" for k in sets)
    with connect(db_path) as conn:
        conn.execute(f"UPDATE goals SET {cols} WHERE id = ?",
                     (*sets.values(), goal_id))
    return get_goal(goal_id, db_path=db_path)


def get_goal(goal_id: int, db_path: Path | None = None) -> dict | None:
    init_db(db_path)
    with connect(db_path) as conn:
        row = conn.execute("SELECT * FROM goals WHERE id = ?", (goal_id,)).fetchone()
    return dict(row) if row else None


def delete_goal(goal_id: int, db_path: Path | None = None) -> bool:
    init_db(db_path)
    with connect(db_path) as conn:
        cur = conn.execute("DELETE FROM goals WHERE id = ?", (goal_id,))
    return cur.rowcount > 0
