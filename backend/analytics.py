"""Analytics over the stored health data.

These functions back both the dashboard endpoints and the advisor's tools,
so their output is kept compact and JSON-friendly.
"""
from __future__ import annotations

from datetime import date, timedelta
from statistics import mean, pstdev

from .config import QUANTITY_TYPES
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
    return digest
