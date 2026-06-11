"""Background scheduling of health reminders via APScheduler.

A single ``BackgroundScheduler`` runs inside the uvicorn process (the server is
long-lived) and fires cron jobs at the times defined by the user's preferences.
Each job just calls ``notifications.fire(ntype)`` — all the "should this actually
go out?" logic lives there, so this module is only concerned with *timing*.

Jobs are (re)built from preferences: every reminder type gets a job whether or
not it's currently enabled, because the enable check happens at fire time. Only a
*time* change requires a rebuild, which the prefs endpoint triggers via
``reschedule_all``.
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from . import notifications, push
from .config import WATER_REMINDER_END_HOUR, WATER_REMINDER_START_HOUR

log = logging.getLogger("asclepius.scheduler")

_scheduler: BackgroundScheduler | None = None

# Defaults applied to every job: collapse a backlog into one run, and tolerate a
# brief server restart around fire time without replaying hours-old reminders.
_JOB_DEFAULTS = {"coalesce": True, "misfire_grace_time": 30 * 60}


def _hhmm(prefs: dict, key: str, field: str, fallback: str) -> tuple[int, int]:
    value = prefs["types"].get(key, {}).get(field) or fallback
    h, m = notifications._parse_hhmm(value, fallback)
    return h, m


def _build_jobs(scheduler: BackgroundScheduler) -> None:
    """Define every reminder job from the current preferences."""
    prefs = notifications.get_prefs()

    def add(job_id: str, ntype: str, trigger: CronTrigger) -> None:
        scheduler.add_job(notifications.fire, trigger=trigger, args=[ntype],
                          id=job_id, replace_existing=True)

    # Meals — one daily cron each at the configured time.
    for meal in ("breakfast", "lunch", "dinner"):
        h, m = _hhmm(prefs, meal, "time",
                     {"breakfast": "08:00", "lunch": "12:30", "dinner": "18:30"}[meal])
        add(meal, meal, CronTrigger(hour=h, minute=m))

    # Water — top of every even hour across the active window.
    water_hours = ",".join(str(h) for h in range(
        WATER_REMINDER_START_HOUR, WATER_REMINDER_END_HOUR + 1, 2))
    add("water", "water", CronTrigger(hour=water_hours, minute=0))

    # Workout — weekday and weekend fire at (potentially) different times.
    wh, wm = _hhmm(prefs, "workout", "time", "17:30")
    add("workout_weekday", "workout",
        CronTrigger(day_of_week="mon-fri", hour=wh, minute=wm))
    eh, em = _hhmm(prefs, "workout", "time_weekend", "09:00")
    add("workout_weekend", "workout",
        CronTrigger(day_of_week="sat,sun", hour=eh, minute=em))

    # Sleep & coach — simple daily crons.
    sh, sm = _hhmm(prefs, "sleep", "time", "22:00")
    add("sleep", "sleep", CronTrigger(hour=sh, minute=sm))
    ch, cm = _hhmm(prefs, "coach", "time", "09:00")
    add("coach", "coach", CronTrigger(hour=ch, minute=cm))

    # Weekly recap — Sunday morning.
    yh, ym = _hhmm(prefs, "weekly", "time", "08:00")
    add("weekly", "weekly", CronTrigger(day_of_week="sun", hour=yh, minute=ym))

    log.info("Scheduled %d reminder jobs", len(scheduler.get_jobs()))


def start() -> None:
    """Start the scheduler. No-op if push is disabled or already running."""
    global _scheduler
    if not push.enabled():
        log.info("Push disabled (no VAPID key) — scheduler not started.")
        return
    if _scheduler and _scheduler.running:
        return
    _scheduler = BackgroundScheduler(job_defaults=_JOB_DEFAULTS)
    _build_jobs(_scheduler)
    _scheduler.start()
    log.info("Notification scheduler started.")


def reschedule_all() -> None:
    """Rebuild every job from current preferences (call after a prefs change)."""
    if not _scheduler or not _scheduler.running:
        return
    _build_jobs(_scheduler)
    log.info("Reminder jobs rescheduled from updated preferences.")


def shutdown() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        log.info("Notification scheduler stopped.")
    _scheduler = None


def jobs_summary() -> list[dict]:
    """Next-run times for each job — handy for the settings UI / debugging."""
    if not _scheduler:
        return []
    return [{"id": j.id,
             "next_run": j.next_run_time.isoformat() if j.next_run_time else None}
            for j in _scheduler.get_jobs()]
