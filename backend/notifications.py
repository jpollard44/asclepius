"""Notification preferences, suppression rules, and message construction.

This is the brain of the reminder system. ``scheduler.py`` decides *when* a job
fires; this module decides whether it *should* actually go out right now, and
what it should say. Keeping that logic here (separate from APScheduler wiring)
keeps it unit-testable and lets the API reuse it.

Every reminder funnels through ``fire(ntype)``, which applies, in order:

  1. master + per-type enable switches (user preferences),
  2. Do-Not-Disturb quiet hours,
  3. "app is open" suppression (don't nudge someone already in the app),
  4. the per-type relevance check (already logged this meal? on pace for water?),
  5. de-duplication (never send the same reminder twice).

Only if all pass is the push handed to ``push.send_to_all``.
"""
from __future__ import annotations

import datetime as _dt
import logging

from . import analytics, push, store
from .config import (
    APP_OPEN_WINDOW_SEC,
    DEFAULT_DND_END,
    DEFAULT_DND_START,
    DEFAULT_WATER_GOAL_ML,
    NOTIFICATION_TYPES,
    WATER_REMINDER_END_HOUR,
    WATER_REMINDER_START_HOUR,
)
from .store import connect

log = logging.getLogger("asclepius.notifications")

_PREFS_KEY = "notification_prefs"
ML_PER_OZ = 29.5735


# ---------------------------------------------------------------------------
# Preferences
# ---------------------------------------------------------------------------
def default_prefs() -> dict:
    """Out-of-the-box preferences derived from the NOTIFICATION_TYPES catalogue."""
    types = {}
    for key, cfg in NOTIFICATION_TYPES.items():
        entry = {"enabled": True}
        if cfg.get("time"):
            entry["time"] = cfg["time"]
        if cfg.get("time_weekend"):
            entry["time_weekend"] = cfg["time_weekend"]
        types[key] = entry
    return {
        "enabled": True,
        "dnd_start": DEFAULT_DND_START,
        "dnd_end": DEFAULT_DND_END,
        "types": types,
    }


def get_prefs(db_path=None) -> dict:
    """Stored preferences merged over current defaults.

    Merging over defaults means a type added to the catalogue in a later release
    shows up enabled with its default time even for users who saved prefs before
    it existed.
    """
    stored = store.kv_get(_PREFS_KEY, default=None, db_path=db_path) or {}
    prefs = default_prefs()
    if isinstance(stored.get("enabled"), bool):
        prefs["enabled"] = stored["enabled"]
    for fld in ("dnd_start", "dnd_end"):
        if isinstance(stored.get(fld), str) and _valid_hhmm(stored[fld]):
            prefs[fld] = stored[fld]
    for key, entry in (stored.get("types") or {}).items():
        if key not in prefs["types"] or not isinstance(entry, dict):
            continue
        if isinstance(entry.get("enabled"), bool):
            prefs["types"][key]["enabled"] = entry["enabled"]
        for tfld in ("time", "time_weekend"):
            # Only honour a stored time for a type that actually has that slot.
            if tfld in prefs["types"][key] and _valid_hhmm(entry.get(tfld, "")):
                prefs["types"][key][tfld] = entry[tfld]
    return prefs


def save_prefs(patch: dict, db_path=None) -> dict:
    """Apply a (possibly partial) preference update and return the merged result.

    Validates and clamps everything through ``get_prefs``'s merge so a malformed
    payload can never corrupt the stored prefs.
    """
    current = get_prefs(db_path=db_path)
    if isinstance(patch.get("enabled"), bool):
        current["enabled"] = patch["enabled"]
    for fld in ("dnd_start", "dnd_end"):
        if _valid_hhmm(patch.get(fld, "")):
            current[fld] = patch[fld]
    for key, entry in (patch.get("types") or {}).items():
        if key not in current["types"] or not isinstance(entry, dict):
            continue
        if isinstance(entry.get("enabled"), bool):
            current["types"][key]["enabled"] = entry["enabled"]
        for tfld in ("time", "time_weekend"):
            if tfld in current["types"][key] and _valid_hhmm(entry.get(tfld, "")):
                current["types"][key][tfld] = entry[tfld]
    store.kv_set(_PREFS_KEY, current, db_path=db_path)
    return current


def prefs_view(db_path=None) -> dict:
    """Preferences annotated with catalogue metadata for the settings UI.

    The UI needs labels, descriptions and which times are editable; those live in
    config, not in the saved prefs. This stitches them together.
    """
    prefs = get_prefs(db_path=db_path)
    types = []
    for key, cfg in NOTIFICATION_TYPES.items():
        entry = prefs["types"].get(key, {})
        types.append({
            "key": key,
            "label": cfg["label"],
            "desc": cfg["desc"],
            "enabled": entry.get("enabled", True),
            "editable_time": cfg.get("editable_time", False),
            "time": entry.get("time"),
            "time_weekend": entry.get("time_weekend"),
            "has_weekend": "time_weekend" in cfg,
        })
    return {
        "enabled": prefs["enabled"],
        "dnd_start": prefs["dnd_start"],
        "dnd_end": prefs["dnd_end"],
        "types": types,
        "push_enabled": push.enabled(),
        "subscriptions": store.count_push_subscriptions(db_path=db_path),
    }


def _valid_hhmm(value) -> bool:
    if not isinstance(value, str):
        return False
    try:
        h, m = value.split(":")
        return 0 <= int(h) <= 23 and 0 <= int(m) <= 59
    except (ValueError, AttributeError):
        return False


def _parse_hhmm(value: str, fallback: str) -> tuple[int, int]:
    if not _valid_hhmm(value):
        value = fallback
    h, m = value.split(":")
    return int(h), int(m)


# ---------------------------------------------------------------------------
# Suppression
# ---------------------------------------------------------------------------
def _in_dnd(now: _dt.datetime, prefs: dict) -> bool:
    """Is ``now`` inside the (possibly overnight) Do-Not-Disturb window?"""
    start = _parse_hhmm(prefs.get("dnd_start", DEFAULT_DND_START), DEFAULT_DND_START)
    end = _parse_hhmm(prefs.get("dnd_end", DEFAULT_DND_END), DEFAULT_DND_END)
    cur = (now.hour, now.minute)
    if start <= end:  # same-day window, e.g. 01:00–06:00
        return start <= cur < end
    return cur >= start or cur < end  # overnight window, e.g. 23:00–07:00


def _app_is_open(db_path=None) -> bool:
    """True if the app pinged the API very recently (so it's likely foregrounded)."""
    last = store.last_activity(db_path=db_path)
    if not last:
        return False
    try:
        seen = _dt.datetime.fromisoformat(last)
    except ValueError:
        return False
    return (_dt.datetime.now() - seen).total_seconds() < APP_OPEN_WINDOW_SEC


# ---------------------------------------------------------------------------
# Per-type relevance + message building
# ---------------------------------------------------------------------------
def _today() -> str:
    return _dt.date.today().isoformat()


def _meal_logged(meal: str, db_path=None) -> bool:
    with connect(db_path) as conn:
        return conn.execute(
            "SELECT 1 FROM food_log WHERE date = ? AND meal = ? LIMIT 1",
            (_today(), meal)).fetchone() is not None


def _workout_logged_today(db_path=None) -> bool:
    with connect(db_path) as conn:
        return conn.execute(
            "SELECT 1 FROM workouts WHERE date = ? LIMIT 1",
            (_today(),)).fetchone() is not None


def _water_today_ml(db_path=None) -> float:
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT SUM(amount_ml) AS ml FROM water_log WHERE date = ?",
            (_today(),)).fetchone()
    return float(row["ml"] or 0)


def _oz(ml: float) -> int:
    return round(ml / ML_PER_OZ)


_MEAL_COPY = {
    "breakfast": ("🍳 Good morning!", "Log your breakfast to start the day on track."),
    "lunch": ("🥗 Lunchtime", "Log what you ate so your coach stays in the loop."),
    "dinner": ("🍽️ Dinner", "Log your dinner to close out today's nutrition."),
}


def _build(ntype: str, now: _dt.datetime, db_path=None) -> dict | None:
    """Return {title, body, url, tag} for ``ntype`` if it's worth sending now,
    else None (relevance check failed — e.g. meal already logged)."""
    if ntype in _MEAL_COPY:
        meal = ntype
        if _meal_logged(meal, db_path=db_path):
            return None
        title, body = _MEAL_COPY[meal]
        return {"title": title, "body": body, "url": "/?tab=food"}

    if ntype == "water":
        goal = _water_goal(db_path)
        total = _water_today_ml(db_path)
        # Expected intake is linear across the active window (8am→10pm). Only
        # nudge when meaningfully behind (>1 glass short of pace).
        span = max(1, WATER_REMINDER_END_HOUR - WATER_REMINDER_START_HOUR)
        elapsed = min(span, max(0, (now.hour + now.minute / 60) - WATER_REMINDER_START_HOUR))
        expected = goal * (elapsed / span)
        if total >= expected - ML_PER_OZ * 8:  # within ~8oz of pace → on track
            return None
        return {
            "title": "💧 Stay hydrated",
            "body": f"You've had {_oz(total)} oz today — goal is {_oz(goal)} oz.",
            "url": "/?tab=dashboard",
        }

    if ntype == "workout":
        if _workout_logged_today(db_path=db_path):
            return None
        n = analytics._workouts_this_week(db_path)
        tail = (f"You've worked out {n} times this week."
                if n else "You haven't trained yet this week.")
        return {"title": "💪 Time to train!", "body": tail, "url": "/?tab=workouts"}

    if ntype == "sleep":
        return {"title": "😴 Wind down",
                "body": "Aim for 7+ hours tonight — start easing toward bed.",
                "url": "/?tab=sleep"}

    if ntype == "coach":
        return {"title": "👋 Your coach has insights",
                "body": "Check in for your daily brief.",
                "url": "/?tab=coach"}

    if ntype == "weekly":
        return _weekly_message(db_path)

    return None


def _water_goal(db_path=None) -> float:
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT target FROM goals WHERE category = 'water' AND status = 'active' "
            "ORDER BY created_at DESC LIMIT 1").fetchone()
    if row and row["target"]:
        return float(row["target"])
    return float(DEFAULT_WATER_GOAL_ML)


def _weekly_message(db_path=None) -> dict:
    """Build the Sunday recap from the last 7 days of logs."""
    cutoff = (_dt.date.today() - _dt.timedelta(days=7)).isoformat()
    nut = analytics.nutrition_summary(7, db_path)
    cal = round(nut["avg_kcal"]) if nut.get("available") else 0
    sleep = analytics.sleep_summary(7, db_path)
    sleep_h = round(sleep["avg_asleep_hours"], 1) if sleep.get("available") else 0
    with connect(db_path) as conn:
        workouts = conn.execute(
            "SELECT COUNT(*) AS n FROM workouts WHERE date >= ?", (cutoff,)
        ).fetchone()["n"]
        wrow = conn.execute(
            "SELECT AVG(daily) AS ml FROM (SELECT SUM(amount_ml) AS daily "
            "FROM water_log WHERE date >= ? GROUP BY date)", (cutoff,)
        ).fetchone()
    water_oz = _oz(wrow["ml"] or 0)
    body = (f"{cal} cal/day · {workouts} workouts · "
            f"{water_oz} oz water/day · {sleep_h} hrs sleep")
    return {"title": "📊 Weekly health recap", "body": body, "url": "/?tab=dashboard"}


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------
def fire(ntype: str, *, force: bool = False, db_path=None) -> dict:
    """Evaluate and (if warranted) send the ``ntype`` reminder.

    ``force`` bypasses suppression and de-dup (used by the manual "trigger now"
    debug endpoint). Returns a small status dict describing what happened.
    """
    now = _dt.datetime.now()
    prefs = get_prefs(db_path=db_path)
    type_pref = prefs["types"].get(ntype, {})

    if not force:
        if not prefs.get("enabled", True):
            return _skip(ntype, "master-disabled")
        if not type_pref.get("enabled", True):
            return _skip(ntype, "type-disabled")
        if _in_dnd(now, prefs):
            return _skip(ntype, "dnd")
        if _app_is_open(db_path=db_path):
            return _skip(ntype, "app-open")

    dedup = _dedup_key(ntype, now)
    if not force and store.notification_already_sent(dedup, db_path=db_path):
        return _skip(ntype, "already-sent")

    msg = _build(ntype, now, db_path=db_path)
    if msg is None:
        return _skip(ntype, "not-relevant")

    # Atomically claim the dedup slot before sending so two overlapping jobs
    # can't both deliver it. (Skipped under force, which intentionally re-sends.)
    if not force:
        if not store.record_notification(
                dedup, ntype, msg["title"], msg["body"], db_path=db_path):
            return _skip(ntype, "already-sent")

    result = push.send_to_all(
        msg["title"], msg["body"], tag=f"asclepius-{ntype}",
        url=msg.get("url", "/"), ntype=ntype)
    log.info("Fired %s: sent=%s failed=%s", ntype,
             result.get("sent"), result.get("failed"))
    return {"ntype": ntype, "fired": True, "title": msg["title"],
            "body": msg["body"], **result}


def _skip(ntype: str, reason: str) -> dict:
    log.debug("Skipped %s (%s)", ntype, reason)
    return {"ntype": ntype, "fired": False, "reason": reason}


def _dedup_key(ntype: str, now: _dt.datetime) -> str:
    if ntype == "water":
        return f"water:{now.date().isoformat()}:{now.hour}"
    if ntype == "weekly":
        iso = now.isocalendar()
        return f"weekly:{iso[0]}-W{iso[1]}"
    return f"{ntype}:{now.date().isoformat()}"
