"""Asclepius web app: upload Apple Health data and chat with your advisor."""
from __future__ import annotations

import base64
import os
import tempfile
from pathlib import Path

# Load .env before anything reads ANTHROPIC_API_KEY, so the advisor works no
# matter how the server is started (launchctl, bare uvicorn, etc.).
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import (
    advisor,
    analytics,
    body_import,
    notifications,
    parser,
    push,
    scheduler,
    store,
    tracking,
)
from .config import (
    DATA_DIR,
    FRONTEND_DIR,
    GOAL_CATEGORIES,
    MANUAL_METRICS,
    MEALS,
    WORKOUT_TYPES,
)

app = FastAPI(title="Asclepius", description="Personal Apple Health advisor")


# ---------------------------------------------------------------------------
# Lifecycle & activity tracking
# ---------------------------------------------------------------------------
@app.on_event("startup")
def _startup() -> None:
    """Boot the reminder scheduler once the server is up (no-op without VAPID)."""
    scheduler.start()


@app.on_event("shutdown")
def _shutdown() -> None:
    scheduler.shutdown()


@app.middleware("http")
async def _track_activity(request: Request, call_next):
    """Stamp the last time the app talked to the API.

    The notification scheduler reads this to suppress reminders while the app is
    open in the foreground (no point nudging someone already using it).
    """
    if request.url.path.startswith("/api/"):
        try:
            store.touch_activity()
        except Exception:  # noqa: BLE001 - never block a request on bookkeeping
            pass
    return await call_next(request)


# ---------------------------------------------------------------------------
# Data ingestion
# ---------------------------------------------------------------------------
@app.post("/api/upload")
async def upload(file: UploadFile) -> JSONResponse:
    """Accept an Apple Health export (export.xml or the export .zip) and load it."""
    suffix = Path(file.filename or "export").suffix or ".dat"
    tmp = Path(tempfile.mkstemp(dir=DATA_DIR, suffix=suffix)[1])
    try:
        with open(tmp, "wb") as out:
            while chunk := await file.read(1 << 20):
                out.write(chunk)
        try:
            parsed = parser.parse_export(tmp)
        except Exception as exc:  # noqa: BLE001 - report parse failures to the UI
            raise HTTPException(status_code=400,
                                detail=f"Could not parse the export: {exc}")
        counts = store.replace_data(parsed)
    finally:
        tmp.unlink(missing_ok=True)
        # Clean up an extracted export.xml if one was produced from a zip.
        extracted = DATA_DIR / "export.xml"
        if extracted.exists():
            extracted.unlink(missing_ok=True)

    return JSONResponse({
        "status": "ok",
        "counts": counts,
        "date_range": analytics.date_range(),
        "metrics_found": len(analytics.available_metrics()),
    })


@app.post("/api/import/body")
async def import_body(file: UploadFile, sheet_name: str | None = None) -> dict:
    """Import a smart-scale body-composition .xlsx (Renpho/Withings-style).

    Reads the given sheet (default: first), reshapes each weigh-in into the
    body metrics Asclepius tracks, de-duplicates to one reading per day, and
    stores them in daily_metrics with source='scale'. Returns a summary of what
    was imported.
    """
    name = (file.filename or "").lower()
    if not name.endswith((".xlsx", ".xlsm")):
        raise HTTPException(status_code=400,
                            detail="Please upload an .xlsx body-measurement file.")
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="The file was empty.")
    try:
        summary = body_import.import_xlsx(raw, sheet_name=sheet_name)
    except body_import.BodyImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return summary


@app.get("/api/status")
def status() -> dict:
    advisor_ready = bool(os.environ.get("ANTHROPIC_API_KEY"))
    config = {
        "meals": MEALS,
        "workout_types": WORKOUT_TYPES,
        "goal_categories": GOAL_CATEGORIES,
        "manual_metrics": MANUAL_METRICS,
    }
    if not store.has_data():
        return {"has_data": False, "advisor_ready": advisor_ready,
                "has_import": False, "config": config}
    return {
        "has_data": True,
        "has_import": store.has_import(),
        "advisor_ready": advisor_ready,
        "date_range": analytics.date_range() if store.has_import() else None,
        "meta": store.get_meta(),
        "metrics": analytics.available_metrics(),
        "plan": store.get_plan(),
        "config": config,
    }


# ---------------------------------------------------------------------------
# Dashboard data
# ---------------------------------------------------------------------------
def _require_data() -> None:
    if not store.has_data():
        raise HTTPException(status_code=404,
                            detail="No health data loaded yet. Upload an export first.")


@app.get("/api/overview")
def overview() -> dict:
    _require_data()
    return analytics.overview()


@app.get("/api/metrics")
def metrics() -> dict:
    _require_data()
    return {"metrics": analytics.available_metrics()}


@app.get("/api/metric/{key}")
def metric(key: str, days: int = 365) -> dict:
    _require_data()
    return {
        "summary": analytics.metric_summary(key, days=days),
        "series": analytics.metric_series(key, days=days),
    }


@app.get("/api/sleep")
def sleep(days: int = 90) -> dict:
    _require_data()
    return {
        "summary": analytics.sleep_summary(days=days),
        "series": analytics.sleep_series(days=days),
    }


# ---------------------------------------------------------------------------
# Advisor chat
# ---------------------------------------------------------------------------
class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]


@app.post("/api/chat")
def chat(req: ChatRequest) -> dict:
    _require_data()
    if not req.messages or req.messages[-1].role != "user":
        raise HTTPException(status_code=400, detail="Last message must be from the user.")
    user_text = req.messages[-1].content
    # Ground the turn in the persisted conversation so the coach remembers prior
    # chats even across page reloads, then append the new user message.
    convo = store.recent_chat_messages(limit=40)
    convo.append({"role": "user", "content": user_text})
    try:
        result = advisor.chat(convo)
    except advisor.AdvisorError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    # Persist only after a successful reply, so a failed turn never leaves a
    # dangling user message in the history.
    store.add_chat_message("user", user_text)
    store.add_chat_message("assistant", result["reply"])
    return {"reply": result["reply"], "plan": store.get_plan()}


@app.get("/api/chat/history")
def chat_history(limit: int = 50, before: int | None = None) -> dict:
    """Recent coach messages, oldest-first, paginated with ?limit & ?before=<id>."""
    return store.get_chat_history(limit=limit, before=before)


@app.delete("/api/chat/history")
def clear_chat_history() -> dict:
    """Wipe the coach conversation — backs the 'New chat' button."""
    return {"status": "ok", "cleared": store.clear_chat_history()}


@app.post("/api/briefing")
def briefing() -> dict:
    """Proactive opening briefing from the coach (also builds the initial plan)."""
    _require_data()
    try:
        result = advisor.briefing()
    except advisor.AdvisorError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    store.add_chat_message("assistant", result["reply"])
    return {"reply": result["reply"], "plan": store.get_plan()}


@app.get("/api/plan")
def plan() -> dict:
    return {"plan": store.get_plan(), "history": store.plan_history()}


class Recommendation(BaseModel):
    topic: str
    label: str | None = None


@app.post("/api/recommend")
def recommend(req: Recommendation) -> dict:
    _require_data()
    try:
        result = advisor.recommend(req.topic)
    except advisor.AdvisorError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    # Record the recommendation in the conversation so it persists in history.
    store.add_chat_message("user", req.label or req.topic)
    store.add_chat_message("assistant", result["reply"])
    return {"reply": result["reply"], "topic": req.topic}


# ---------------------------------------------------------------------------
# Dashboard & insights
# ---------------------------------------------------------------------------
@app.get("/api/dashboard")
def dashboard() -> dict:
    return analytics.dashboard()


@app.get("/api/streaks")
def streaks() -> dict:
    return analytics.streaks()


@app.get("/api/achievements")
def achievements() -> dict:
    return {"achievements": analytics.achievements()}


@app.get("/api/report/weekly")
def weekly_report() -> dict:
    return analytics.weekly_report()


# ---------------------------------------------------------------------------
# Food & nutrition
# ---------------------------------------------------------------------------
class FoodEntry(BaseModel):
    name: str
    kcal: float = 0
    protein: float = 0
    carbs: float = 0
    fat: float = 0
    meal: str = "snack"
    qty: float = 1
    serving: str = ""
    date: str | None = None
    food_id: int | None = None
    fiber: float | None = None
    sugar: float | None = None
    sodium: float | None = None


class CustomFood(BaseModel):
    name: str
    kcal: float = 0
    protein: float = 0
    carbs: float = 0
    fat: float = 0
    serving: str = ""
    category: str = "custom"


@app.get("/api/foods")
def foods(q: str = "", limit: int = 30) -> dict:
    return {"foods": tracking.search_foods(q, limit)}


@app.post("/api/foods")
def create_food(food: CustomFood) -> dict:
    return tracking.upsert_food(
        food.name, food.kcal, food.protein, food.carbs, food.fat,
        food.serving, food.category)


@app.get("/api/food")
def food_log(date: str | None = None) -> dict:
    return tracking.list_food(date)


@app.post("/api/food")
def add_food(entry: FoodEntry) -> dict:
    return tracking.add_food(
        entry.name, entry.kcal, entry.protein, entry.carbs, entry.fat,
        entry.meal, entry.qty, entry.serving, entry.date, entry.food_id,
        entry.fiber, entry.sugar, entry.sodium)


@app.post("/api/food/analyze")
async def analyze_food(file: UploadFile) -> dict:
    """Estimate macros & micros from a food photo via Claude's vision model.

    Returns the AI's best estimate so the UI can pre-fill the log form for the
    user to review and adjust before saving. Nothing is stored here.
    """
    media_type = file.content_type or ""
    if not media_type.startswith("image/"):
        # Fall back to a sensible default for camera captures with no type.
        media_type = "image/jpeg"
    if media_type not in ("image/jpeg", "image/png", "image/gif", "image/webp"):
        raise HTTPException(
            status_code=400,
            detail="Please use a JPEG, PNG, GIF or WebP photo.")
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="The photo was empty.")
    if len(raw) > 15 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="That photo is too large (max 15 MB).")
    image_data = base64.standard_b64encode(raw).decode("utf-8")
    try:
        estimate = advisor.analyze_food_photo(image_data, media_type)
    except advisor.AdvisorError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return {"estimate": estimate}


@app.delete("/api/food/{entry_id}")
def delete_food(entry_id: int) -> dict:
    if not tracking.delete_food(entry_id):
        raise HTTPException(status_code=404, detail="Entry not found.")
    return {"status": "ok"}


@app.get("/api/nutrition")
def nutrition(days: int = 30) -> dict:
    return analytics.nutrition_summary(days)


# ---------------------------------------------------------------------------
# Water
# ---------------------------------------------------------------------------
class WaterEntry(BaseModel):
    amount_ml: float
    date: str | None = None


@app.get("/api/water")
def water(date: str | None = None) -> dict:
    return tracking.get_water(date)


@app.post("/api/water")
def add_water(entry: WaterEntry) -> dict:
    return tracking.add_water(entry.amount_ml, entry.date)


@app.delete("/api/water/{entry_id}")
def delete_water(entry_id: int) -> dict:
    if not tracking.delete_water(entry_id):
        raise HTTPException(status_code=404, detail="Entry not found.")
    return {"status": "ok"}


@app.get("/api/water/series")
def water_series(days: int = 30) -> dict:
    return {"series": tracking.water_series(days)}


# ---------------------------------------------------------------------------
# Workouts
# ---------------------------------------------------------------------------
class WorkoutEntry(BaseModel):
    activity: str = "Workout"
    type: str = "other"
    date: str | None = None
    duration_min: float | None = None
    distance_km: float | None = None
    energy_kcal: float | None = None
    exercises: list | None = None
    notes: str = ""


@app.get("/api/workouts")
def workouts(days: int = 90) -> dict:
    return {"workouts": tracking.list_workouts(days),
            "summary": analytics.workouts_summary(days)}


@app.post("/api/workouts")
def add_workout(w: WorkoutEntry) -> dict:
    return tracking.add_workout(
        w.activity, w.type, w.date, w.duration_min, w.distance_km,
        w.energy_kcal, w.exercises, w.notes)


@app.delete("/api/workouts/{workout_id}")
def delete_workout(workout_id: int) -> dict:
    if not tracking.delete_workout(workout_id):
        raise HTTPException(status_code=404, detail="Workout not found.")
    return {"status": "ok"}


@app.get("/api/workouts/volume")
def workout_volume(days: int = 30) -> dict:
    return analytics.workout_volume(days)


@app.get("/api/workouts/prs")
def personal_records() -> dict:
    return {"records": analytics.personal_records()}


# ---------------------------------------------------------------------------
# Body measurements & manual metrics
# ---------------------------------------------------------------------------
class BodyEntry(BaseModel):
    metric: str
    value: float
    date: str | None = None


@app.post("/api/body")
def log_body(entry: BodyEntry) -> dict:
    if entry.metric not in MANUAL_METRICS:
        raise HTTPException(status_code=400,
                            detail=f"Unknown metric '{entry.metric}'.")
    return tracking.log_metric(entry.metric, entry.value, entry.date)


@app.get("/api/body")
def body_metrics(days: int = 365) -> dict:
    """Series for each manually-trackable body/vitals metric that has data."""
    out = []
    for key, cfg in MANUAL_METRICS.items():
        series = analytics.metric_series(key, days=days)
        if series:
            out.append({
                "key": key, "label": cfg["label"], "unit": cfg["unit"],
                "area": cfg["area"],
                "summary": analytics.metric_summary(key, days=days),
                "series": series,
            })
    return {"metrics": out}


# ---------------------------------------------------------------------------
# Manual sleep
# ---------------------------------------------------------------------------
class SleepEntry(BaseModel):
    date: str | None = None
    asleep_hours: float
    in_bed_hours: float | None = None
    rem_hours: float | None = None
    deep_hours: float | None = None


@app.post("/api/sleep")
def log_sleep(entry: SleepEntry) -> dict:
    return tracking.log_sleep(
        entry.date, entry.asleep_hours, entry.in_bed_hours,
        entry.rem_hours, entry.deep_hours)


# ---------------------------------------------------------------------------
# Goals
# ---------------------------------------------------------------------------
class GoalCreate(BaseModel):
    category: str
    label: str = ""
    target: float | None = None
    baseline: float | None = None
    unit: str = ""
    direction: str = "increase"
    target_date: str | None = None
    notes: str = ""


class GoalUpdate(BaseModel):
    label: str | None = None
    target: float | None = None
    baseline: float | None = None
    unit: str | None = None
    direction: str | None = None
    target_date: str | None = None
    status: str | None = None
    notes: str | None = None


@app.get("/api/goals")
def goals(status: str = "active") -> dict:
    return {"goals": analytics.goals_progress() if status == "active"
            else tracking.list_goals(status if status != "all" else None)}


@app.post("/api/goals")
def create_goal(g: GoalCreate) -> dict:
    if g.category not in GOAL_CATEGORIES:
        raise HTTPException(status_code=400,
                            detail=f"Unknown goal category '{g.category}'.")
    return tracking.create_goal(
        g.category, g.label, g.target, g.baseline, g.unit, g.direction,
        g.target_date, g.notes)


@app.put("/api/goals/{goal_id}")
def update_goal(goal_id: int, g: GoalUpdate) -> dict:
    updated = tracking.update_goal(goal_id, **g.model_dump(exclude_none=True))
    if not updated:
        raise HTTPException(status_code=404, detail="Goal not found.")
    return updated


@app.delete("/api/goals/{goal_id}")
def delete_goal(goal_id: int) -> dict:
    if not tracking.delete_goal(goal_id):
        raise HTTPException(status_code=404, detail="Goal not found.")
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Push notifications
# ---------------------------------------------------------------------------
class PushSubscription(BaseModel):
    subscription: dict
    user_agent: str = ""


class PushUnsubscribe(BaseModel):
    endpoint: str


class PushPrefs(BaseModel):
    enabled: bool | None = None
    dnd_start: str | None = None
    dnd_end: str | None = None
    types: dict | None = None


class PushTrigger(BaseModel):
    type: str


@app.get("/api/push/vapid")
def push_vapid() -> dict:
    """The VAPID public key the browser needs to create a subscription."""
    return {"public_key": push.public_key(), "enabled": push.enabled()}


@app.post("/api/push/subscribe")
def push_subscribe(req: PushSubscription) -> dict:
    if not push.enabled():
        raise HTTPException(status_code=503,
                            detail="Push is not configured on this server.")
    if not req.subscription.get("endpoint"):
        raise HTTPException(status_code=400, detail="Invalid subscription.")
    store.save_push_subscription(req.subscription, req.user_agent)
    return {"status": "ok", "subscriptions": store.count_push_subscriptions()}


@app.post("/api/push/unsubscribe")
def push_unsubscribe(req: PushUnsubscribe) -> dict:
    removed = store.delete_push_subscription(req.endpoint)
    return {"status": "ok", "removed": removed,
            "subscriptions": store.count_push_subscriptions()}


@app.get("/api/push/prefs")
def push_prefs() -> dict:
    """Notification preferences (annotated for the settings UI) + next-run times."""
    return {**notifications.prefs_view(), "jobs": scheduler.jobs_summary()}


@app.put("/api/push/prefs")
def update_push_prefs(req: PushPrefs) -> dict:
    """Update preferences and rebuild the schedule so time changes take effect."""
    saved = notifications.save_prefs(req.model_dump(exclude_none=True))
    scheduler.reschedule_all()
    return {"status": "ok", **notifications.prefs_view(),
            "jobs": scheduler.jobs_summary()}


@app.post("/api/push/send")
def push_send() -> dict:
    """Send a one-off test notification to every subscribed device (internal)."""
    if not push.enabled():
        raise HTTPException(status_code=503,
                            detail="Push is not configured on this server.")
    result = push.send_test()
    if not result.get("subscriptions"):
        raise HTTPException(status_code=400,
                            detail="No devices are subscribed yet.")
    return {"status": "ok", **result}


@app.post("/api/push/trigger")
def push_trigger(req: PushTrigger) -> dict:
    """Force-run a single reminder now, bypassing suppression (for debugging)."""
    if req.type not in notifications.NOTIFICATION_TYPES:
        raise HTTPException(status_code=400,
                            detail=f"Unknown notification type '{req.type}'.")
    return notifications.fire(req.type, force=True)


@app.get("/api/push/log")
def push_log() -> dict:
    """Recently-sent notifications (settings 'recent activity' view)."""
    return {"notifications": store.recent_notifications(limit=20)}


# ---------------------------------------------------------------------------
# Frontend
# ---------------------------------------------------------------------------
@app.get("/")
def index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


app.mount("/", StaticFiles(directory=FRONTEND_DIR), name="static")
