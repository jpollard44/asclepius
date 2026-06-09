"""Analytics over the stored health data.

These functions back both the dashboard endpoints and the advisor's tools,
so their output is kept compact and JSON-friendly.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from statistics import mean, pstdev

from .config import (
    ACHIEVEMENTS,
    DEFAULT_WATER_GOAL_ML,
    GOAL_CATEGORIES,
    MANUAL_METRICS,
    QUANTITY_TYPES,
)
from .store import connect, get_meta

# Metrics surfaced as headline cards on the dashboard overview.
HEADLINE_METRICS = [
    "steps", "active_energy", "exercise_time",
    "resting_heart_rate", "hrv", "vo2_max",
    "body_mass", "blood_oxygen",
]


def _meta_for_key(key: str) -> dict:
    for cfg in QUANTITY_TYPES.values():
        if cfg["key"] == key:
            return cfg
    if key in MANUAL_METRICS:
        return {"key": key, **MANUAL_METRICS[key]}
    return {"key": key, "label": key, "unit": "", "area": "other"}


def date_range(db_path=None) -> dict:
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT MIN(date) AS start, MAX(date) AS end FROM daily_metrics"
        ).fetchone()
    return {"start": row["start"], "end": row["end"]}


def available_metrics(db_path=None) -> list[dict]:
    """List metrics present in the data, with label, unit, area and coverage."""
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT metric, COUNT(*) AS days, MIN(date) AS start, "
            "MAX(date) AS end, unit FROM daily_metrics GROUP BY metric"
        ).fetchall()
    out = []
    for r in rows:
        cfg = _meta_for_key(r["metric"])
        out.append({
            "key": r["metric"],
            "label": cfg["label"],
            "unit": r["unit"] or cfg.get("unit", ""),
            "area": cfg.get("area", "other"),
            "days": r["days"],
            "start": r["start"],
            "end": r["end"],
        })
    out.sort(key=lambda m: (m["area"], m["label"]))
    return out


def metric_series(key: str, days: int | None = None, db_path=None) -> list[dict]:
    """Return the daily series for a metric, optionally limited to recent days."""
    sql = "SELECT date, value, min, max, unit FROM daily_metrics WHERE metric = ?"
    params: list = [key]
    if days:
        cutoff = (date.today() - timedelta(days=days)).isoformat()
        sql += " AND date >= ?"
        params.append(cutoff)
    sql += " ORDER BY date"
    with connect(db_path) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def _trend(values: list[float]) -> dict | None:
    """Compare the mean of the first half vs the second half of a series."""
    if len(values) < 4:
        return None
    half = len(values) // 2
    first = mean(values[:half])
    second = mean(values[half:])
    if first == 0:
        return {"direction": "flat", "pct_change": 0.0}
    pct = (second - first) / abs(first) * 100.0
    direction = "up" if pct > 2 else "down" if pct < -2 else "flat"
    return {"direction": direction, "pct_change": round(pct, 1),
            "first_half_avg": round(first, 2), "second_half_avg": round(second, 2)}


def metric_summary(key: str, days: int = 90, db_path=None) -> dict:
    """Headline statistics for a metric over a recent window."""
    series = metric_series(key, days=days, db_path=db_path)
    cfg = _meta_for_key(key)
    if not series:
        return {"key": key, "label": cfg["label"], "available": False}
    values = [r["value"] for r in series]
    return {
        "key": key,
        "label": cfg["label"],
        "unit": series[-1]["unit"] or cfg.get("unit", ""),
        "available": True,
        "window_days": days,
        "data_points": len(values),
        "latest": series[-1]["value"],
        "latest_date": series[-1]["date"],
        "average": round(mean(values), 2),
        "min": round(min(values), 2),
        "max": round(max(values), 2),
        "std_dev": round(pstdev(values), 2) if len(values) > 1 else 0.0,
        "trend": _trend(values),
    }


def sleep_series(days: int | None = None, db_path=None) -> list[dict]:
    sql = "SELECT * FROM sleep"
    params: list = []
    if days:
        cutoff = (date.today() - timedelta(days=days)).isoformat()
        sql += " WHERE date >= ?"
        params.append(cutoff)
    sql += " ORDER BY date"
    with connect(db_path) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def sleep_summary(days: int = 30, db_path=None) -> dict:
    series = [r for r in sleep_series(days=days, db_path=db_path)
              if r["asleep_hours"] and r["asleep_hours"] > 0]
    if not series:
        return {"available": False}
    asleep = [r["asleep_hours"] for r in series]
    rem = [r["rem_hours"] for r in series if r["rem_hours"]]
    deep = [r["deep_hours"] for r in series if r["deep_hours"]]
    return {
        "available": True,
        "window_days": days,
        "nights_recorded": len(series),
        "avg_asleep_hours": round(mean(asleep), 2),
        "min_asleep_hours": round(min(asleep), 2),
        "max_asleep_hours": round(max(asleep), 2),
        "consistency_std_hours": round(pstdev(asleep), 2) if len(asleep) > 1 else 0.0,
        "avg_rem_hours": round(mean(rem), 2) if rem else None,
        "avg_deep_hours": round(mean(deep), 2) if deep else None,
        "latest": series[-1],
        "trend": _trend(asleep),
    }


def workouts_summary(days: int = 30, db_path=None) -> dict:
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT activity, COUNT(*) AS n, "
            "ROUND(SUM(duration_min), 1) AS total_min, "
            "ROUND(SUM(distance_km), 2) AS total_km, "
            "ROUND(SUM(energy_kcal), 0) AS total_kcal "
            "FROM workouts WHERE date >= ? GROUP BY activity "
            "ORDER BY n DESC",
            (cutoff,),
        ).fetchall()
        total = conn.execute(
            "SELECT COUNT(*) AS n FROM workouts WHERE date >= ?", (cutoff,)
        ).fetchone()
    return {
        "window_days": days,
        "total_workouts": total["n"],
        "by_activity": [dict(r) for r in rows],
    }


def overview(db_path=None) -> dict:
    """Everything the dashboard needs for its summary view."""
    rng = date_range(db_path)
    cards = []
    for key in HEADLINE_METRICS:
        summ = metric_summary(key, days=30, db_path=db_path)
        if summ.get("available"):
            cards.append(summ)
    return {
        "meta": get_meta(db_path),
        "date_range": rng,
        "headline": cards,
        "sleep": sleep_summary(30, db_path),
        "workouts": workouts_summary(30, db_path),
    }


def full_digest(db_path=None) -> dict:
    """A compact, model-friendly snapshot of the whole dataset.

    Used to seed the advisor with context so it can answer many questions
    without a tool call, while still being free to drill in via tools.
    """
    digest = {
        "date_range": date_range(db_path),
        "metrics": {},
        "sleep": sleep_summary(30, db_path),
        "workouts": workouts_summary(30, db_path),
    }
    for m in available_metrics(db_path):
        s = metric_summary(m["key"], days=90, db_path=db_path)
        if s.get("available"):
            digest["metrics"][m["key"]] = {
                "label": s["label"], "unit": s["unit"], "latest": s["latest"],
                "avg_90d": s["average"], "trend": s["trend"],
            }
    digest["nutrition"] = nutrition_summary(7, db_path)
    digest["goals"] = goals_progress(db_path)
    digest["streaks"] = streaks(db_path)
    digest["workout_volume"] = workout_volume(30, db_path)
    return digest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _today() -> str:
    return date.today().isoformat()


def _metric_value_on(key: str, day: str, db_path=None) -> float | None:
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT value FROM daily_metrics WHERE metric = ? AND date = ?",
            (key, day)).fetchone()
    return row["value"] if row else None


def _latest_metric(key: str, db_path=None) -> dict | None:
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT date, value, unit FROM daily_metrics WHERE metric = ? "
            "ORDER BY date DESC LIMIT 1", (key,)).fetchone()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Nutrition
# ---------------------------------------------------------------------------
def nutrition_summary(days: int = 30, db_path=None) -> dict:
    """Daily calorie/macro series plus averages over the window."""
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT date, ROUND(SUM(kcal)) AS kcal, ROUND(SUM(protein)) AS protein, "
            "ROUND(SUM(carbs)) AS carbs, ROUND(SUM(fat)) AS fat, COUNT(*) AS items "
            "FROM food_log WHERE date >= ? GROUP BY date ORDER BY date",
            (cutoff,)).fetchall()
    series = [dict(r) for r in rows]
    if not series:
        return {"available": False, "window_days": days, "series": [],
                "days_logged": 0}
    avg = lambda k: round(mean([r[k] for r in series]), 0)  # noqa: E731
    return {
        "available": True,
        "window_days": days,
        "days_logged": len(series),
        "series": series,
        "avg_kcal": avg("kcal"),
        "avg_protein": avg("protein"),
        "avg_carbs": avg("carbs"),
        "avg_fat": avg("fat"),
        "trend": _trend([r["kcal"] for r in series]),
    }


def today_nutrition(db_path=None) -> dict:
    """Calorie/macro totals logged today, against any active nutrition goals."""
    today = _today()
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT ROUND(SUM(kcal)) AS kcal, ROUND(SUM(protein)) AS protein, "
            "ROUND(SUM(carbs)) AS carbs, ROUND(SUM(fat)) AS fat, COUNT(*) AS items "
            "FROM food_log WHERE date = ?", (today,)).fetchone()
        goal_rows = conn.execute(
            "SELECT category, target FROM goals WHERE status = 'active' "
            "AND category IN ('nutrition_calories', 'nutrition_protein')").fetchall()
    goals = {r["category"]: r["target"] for r in goal_rows}
    totals = {k: (row[k] or 0) for k in ("kcal", "protein", "carbs", "fat")}
    return {
        "date": today,
        "items": row["items"] or 0,
        **totals,
        "kcal_goal": goals.get("nutrition_calories"),
        "protein_goal": goals.get("nutrition_protein"),
    }


# ---------------------------------------------------------------------------
# Workout volume & PRs
# ---------------------------------------------------------------------------
def _strength_workouts(days: int, db_path=None) -> list[dict]:
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT date, exercises FROM workouts "
            "WHERE date >= ? AND exercises IS NOT NULL ORDER BY date",
            (cutoff,)).fetchall()
    out = []
    for r in rows:
        try:
            ex = json.loads(r["exercises"])
        except (json.JSONDecodeError, TypeError):
            continue
        if ex:
            out.append({"date": r["date"], "exercises": ex})
    return out


def workout_volume(days: int = 30, db_path=None) -> dict:
    """Strength training volume (Σ reps×weight) per day and per exercise."""
    workouts = _strength_workouts(days, db_path)
    by_date: dict[str, float] = {}
    by_exercise: dict[str, float] = {}
    total = 0.0
    sessions = 0
    for w in workouts:
        day_vol = 0.0
        for ex in w["exercises"]:
            name = (ex.get("name") or "Exercise").strip()
            for s in ex.get("sets", []):
                reps = _num(s.get("reps"))
                weight = _num(s.get("weight"))
                vol = reps * weight if weight else reps
                day_vol += vol
                by_exercise[name] = by_exercise.get(name, 0) + vol
        if day_vol:
            by_date[w["date"]] = by_date.get(w["date"], 0) + day_vol
            total += day_vol
            sessions += 1
    series = [{"date": d, "volume": round(v)} for d, v in sorted(by_date.items())]
    top = sorted(by_exercise.items(), key=lambda kv: kv[1], reverse=True)
    return {
        "window_days": days,
        "total_volume": round(total),
        "sessions": sessions,
        "series": series,
        "by_exercise": [{"name": n, "volume": round(v)} for n, v in top],
    }


def personal_records(db_path=None) -> list[dict]:
    """Heaviest weight (and best est. 1RM) lifted per exercise, all-time."""
    workouts = _strength_workouts(3650, db_path)
    best: dict[str, dict] = {}
    for w in workouts:
        for ex in w["exercises"]:
            name = (ex.get("name") or "Exercise").strip()
            for s in ex.get("sets", []):
                weight = _num(s.get("weight"))
                reps = _num(s.get("reps"))
                if weight <= 0:
                    continue
                # Epley estimated one-rep max.
                e1rm = weight * (1 + reps / 30.0) if reps else weight
                cur = best.get(name)
                if not cur or weight > cur["weight"] or (
                        weight == cur["weight"] and reps > cur["reps"]):
                    best[name] = {"name": name, "weight": weight, "reps": reps,
                                  "e1rm": round(e1rm, 1), "date": w["date"]}
    return sorted(best.values(), key=lambda r: r["e1rm"], reverse=True)


def _num(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------------------
# Streaks
# ---------------------------------------------------------------------------
def _logged_dates(table: str, db_path=None) -> set[str]:
    with connect(db_path) as conn:
        rows = conn.execute(f"SELECT DISTINCT date FROM {table}").fetchall()
    return {r["date"] for r in rows}


def _current_streak(days_with_activity: set[str]) -> int:
    """Consecutive days up to (and including) today or yesterday with activity."""
    if not days_with_activity:
        return 0
    today = date.today()
    # Allow the streak to be "alive" if today isn't logged yet but yesterday was.
    start = today if today.isoformat() in days_with_activity else today - timedelta(days=1)
    streak = 0
    cur = start
    while cur.isoformat() in days_with_activity:
        streak += 1
        cur -= timedelta(days=1)
    return streak


def streaks(db_path=None) -> dict:
    food_days = _logged_dates("food_log", db_path)
    workout_days = _logged_dates("workouts", db_path)
    # Water days that hit the goal.
    goal = _active_water_goal(db_path)
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT date, SUM(amount_ml) AS ml FROM water_log GROUP BY date").fetchall()
    water_days = {r["date"] for r in rows if r["ml"] and r["ml"] >= goal}
    return {
        "food": _current_streak(food_days),
        "workout": _current_streak(workout_days),
        "water": _current_streak(water_days),
        "food_days_total": len(food_days),
        "workout_days_total": len(workout_days),
    }


def _active_water_goal(db_path=None) -> float:
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT target FROM goals WHERE category = 'water' AND status = 'active' "
            "ORDER BY created_at DESC LIMIT 1").fetchone()
    if row and row["target"]:
        return float(row["target"])
    return float(DEFAULT_WATER_GOAL_ML)


# ---------------------------------------------------------------------------
# Goals
# ---------------------------------------------------------------------------
def _goal_current_value(category: str, db_path=None) -> float | None:
    """Best-effort current value for a goal category, read from the data."""
    if category in ("weight",):
        m = _latest_metric("body_mass", db_path)
        return m["value"] if m else None
    if category == "body_fat":
        m = _latest_metric("body_fat", db_path)
        return m["value"] if m else None
    if category == "nutrition_calories":
        n = nutrition_summary(7, db_path)
        return n["avg_kcal"] if n.get("available") else None
    if category == "nutrition_protein":
        n = nutrition_summary(7, db_path)
        return n["avg_protein"] if n.get("available") else None
    if category == "sleep":
        s = sleep_summary(14, db_path)
        return s["avg_asleep_hours"] if s.get("available") else None
    if category == "steps":
        s = metric_summary("steps", days=14, db_path=db_path)
        return s["average"] if s.get("available") else None
    if category == "activity":
        w = workouts_summary(7, db_path)
        return w["total_workouts"]
    if category == "water":
        ws = _today_water_total(db_path)
        return ws
    return None


def _today_water_total(db_path=None) -> float:
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT SUM(amount_ml) AS ml FROM water_log WHERE date = ?",
            (_today(),)).fetchone()
    return round(row["ml"] or 0)


def goals_progress(db_path=None) -> list[dict]:
    """Active goals annotated with current value and a 0-100 progress percent."""
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM goals WHERE status = 'active' "
            "ORDER BY created_at DESC").fetchall()
    out = []
    for r in rows:
        g = dict(r)
        current = _goal_current_value(g["category"], db_path)
        g["current"] = current
        g["progress"] = _progress_pct(g, current)
        out.append(g)
    return out


def _progress_pct(goal: dict, current: float | None) -> float | None:
    target = goal.get("target")
    if current is None or target is None:
        return None
    baseline = goal.get("baseline")
    direction = goal.get("direction", "increase")
    if direction == "maintain":
        # Closeness to target as a percent (within 10% band = 100).
        if target == 0:
            return 100.0 if current == 0 else 0.0
        off = abs(current - target) / abs(target)
        return round(max(0.0, min(1.0, 1 - off / 0.1)) * 100, 0)
    if baseline is None:
        # No baseline: fraction of target reached (or remaining for decrease).
        if direction == "decrease":
            return round(min(100.0, target / current * 100), 0) if current else 100.0
        return round(min(100.0, current / target * 100), 0) if target else 0.0
    span = target - baseline
    if span == 0:
        return 100.0
    pct = (current - baseline) / span * 100
    return round(max(0.0, min(100.0, pct)), 0)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
def dashboard(db_path=None) -> dict:
    """Everything the home tab shows: today's snapshot across all areas."""
    today = _today()
    steps_today = _metric_value_on("steps", today, db_path)
    energy_today = _metric_value_on("active_energy", today, db_path)
    weight = _latest_metric("body_mass", db_path)

    # Water against goal.
    water_goal = _active_water_goal(db_path)
    water_total = _today_water_total(db_path)

    return {
        "date": today,
        "nutrition": today_nutrition(db_path),
        "water": {"total_ml": water_total, "goal_ml": water_goal,
                  "pct": round(water_total / water_goal * 100) if water_goal else 0},
        "steps_today": steps_today,
        "active_energy_today": energy_today,
        "weight": weight,
        "sleep_last": _last_sleep(db_path),
        "workouts_week": _workouts_this_week(db_path),
        "streaks": streaks(db_path),
        "goals": goals_progress(db_path),
        "headline": [c for c in (metric_summary(k, days=30, db_path=db_path)
                                 for k in HEADLINE_METRICS) if c.get("available")],
    }


def _last_sleep(db_path=None) -> dict | None:
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM sleep WHERE asleep_hours > 0 ORDER BY date DESC LIMIT 1"
        ).fetchone()
    return dict(row) if row else None


def _workouts_this_week(db_path=None) -> int:
    monday = (date.today() - timedelta(days=date.today().weekday())).isoformat()
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM workouts WHERE date >= ?", (monday,)).fetchone()
    return row["n"]


# ---------------------------------------------------------------------------
# Achievements (milestone engine)
# ---------------------------------------------------------------------------
def achievements(db_path=None) -> list[dict]:
    """Evaluate all badges, unlock newly-earned ones, return all with status."""
    earned = _evaluate_achievements(db_path)
    with connect(db_path) as conn:
        existing = {r["key"]: r["unlocked_at"] for r in
                    conn.execute("SELECT key, unlocked_at FROM achievements")}
        now = datetime.now().isoformat(timespec="seconds")
        for key in earned:
            if key not in existing:
                conn.execute(
                    "INSERT OR IGNORE INTO achievements (key, unlocked_at) VALUES (?, ?)",
                    (key, now))
                existing[key] = now
    out = []
    for a in ACHIEVEMENTS:
        out.append({**a, "unlocked": a["key"] in existing,
                    "unlocked_at": existing.get(a["key"])})
    return out


def _evaluate_achievements(db_path=None) -> set[str]:
    earned: set[str] = set()
    s = streaks(db_path)
    if s["food_days_total"] > 0:
        earned.add("first_meal")
    if s["workout_days_total"] > 0:
        earned.add("first_workout")
    if s["food"] >= 7:
        earned.add("food_streak_7")

    # Water goal hit on any day.
    goal = _active_water_goal(db_path)
    with connect(db_path) as conn:
        wrow = conn.execute(
            "SELECT date, SUM(amount_ml) AS ml FROM water_log GROUP BY date "
            "HAVING ml >= ? LIMIT 1", (goal,)).fetchone()
        steps_row = conn.execute(
            "SELECT 1 FROM daily_metrics WHERE metric = 'steps' AND value >= 10000 "
            "LIMIT 1").fetchone()
        done_goal = conn.execute(
            "SELECT 1 FROM goals WHERE status = 'done' LIMIT 1").fetchone()
    if wrow:
        earned.add("hydrated")
    if steps_row:
        earned.add("10k_steps")
    if done_goal:
        earned.add("goal_crushed")

    # 3 consecutive weeks with at least one workout.
    if _workout_week_streak(db_path) >= 3:
        earned.add("workout_streak_3")

    # Protein goal hit on average over the last week.
    nut = nutrition_summary(7, db_path)
    with connect(db_path) as conn:
        prow = conn.execute(
            "SELECT target FROM goals WHERE category = 'nutrition_protein' "
            "AND status = 'active' ORDER BY created_at DESC LIMIT 1").fetchone()
    if nut.get("available") and prow and prow["target"] and \
            nut["avg_protein"] >= prow["target"]:
        earned.add("protein_hit")

    # 7.5h+ average sleep over a week.
    sl = sleep_summary(7, db_path)
    if sl.get("available") and sl["avg_asleep_hours"] >= 7.5:
        earned.add("early_bird")

    # Any strength PR recorded.
    if personal_records(db_path):
        earned.add("first_pr")
    return earned


def _workout_week_streak(db_path=None) -> int:
    workout_days = _logged_dates("workouts", db_path)
    weeks = {date.fromisoformat(d).isocalendar()[:2] for d in workout_days}
    if not weeks:
        return 0
    iso = date.today().isocalendar()
    cur = (iso[0], iso[1])
    streak = 0
    # Walk backwards week by week.
    probe = date.today()
    while (probe.isocalendar()[0], probe.isocalendar()[1]) in weeks:
        streak += 1
        probe -= timedelta(days=7)
    return streak


# ---------------------------------------------------------------------------
# Weekly report
# ---------------------------------------------------------------------------
def weekly_report(db_path=None) -> dict:
    """Last 7 days vs the prior 7 across the metrics that matter most."""
    def window(metric_key, start, end):
        with connect(db_path) as conn:
            row = conn.execute(
                "SELECT AVG(value) AS avg FROM daily_metrics "
                "WHERE metric = ? AND date >= ? AND date < ?",
                (metric_key, start, end)).fetchone()
        return round(row["avg"], 1) if row["avg"] is not None else None

    today = date.today()
    this_start = (today - timedelta(days=7)).isoformat()
    prior_start = (today - timedelta(days=14)).isoformat()
    today_iso = today.isoformat()

    rows = []
    for key in ("steps", "active_energy", "resting_heart_rate", "body_mass"):
        this = window(key, this_start, today_iso)
        prior = window(key, prior_start, this_start)
        if this is None and prior is None:
            continue
        cfg = _meta_for_key(key)
        delta = round(this - prior, 1) if (this is not None and prior is not None) else None
        rows.append({"key": key, "label": cfg["label"], "unit": cfg["unit"],
                     "this_week": this, "prior_week": prior, "delta": delta})

    # Food / workout / water tallies for the week.
    with connect(db_path) as conn:
        food = conn.execute(
            "SELECT COUNT(DISTINCT date) AS days, ROUND(AVG(d.kcal)) AS avg_kcal FROM "
            "(SELECT date, SUM(kcal) AS kcal FROM food_log WHERE date >= ? "
            "GROUP BY date) d", (this_start,)).fetchone()
        workouts = conn.execute(
            "SELECT COUNT(*) AS n FROM workouts WHERE date >= ?", (this_start,)).fetchone()
    return {
        "this_week_start": this_start,
        "metrics": rows,
        "nutrition": {"days_logged": food["days"] or 0, "avg_kcal": food["avg_kcal"]},
        "workouts": workouts["n"],
        "sleep": sleep_summary(7, db_path),
    }
