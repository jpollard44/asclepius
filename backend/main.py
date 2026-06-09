"""Asclepius web app: upload Apple Health data and chat with your advisor."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import advisor, analytics, parser, store, tracking
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
    history = [{"role": m.role, "content": m.content} for m in req.messages]
    if not history or history[-1]["role"] != "user":
        raise HTTPException(status_code=400, detail="Last message must be from the user.")
    try:
        result = advisor.chat(history)
    except advisor.AdvisorError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return {"reply": result["reply"], "plan": store.get_plan()}


@app.post("/api/briefing")
def briefing() -> dict:
    """Proactive opening briefing from the coach (also builds the initial plan)."""
    _require_data()
    try:
        result = advisor.briefing()
    except advisor.AdvisorError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return {"reply": result["reply"], "plan": store.get_plan()}


@app.get("/api/plan")
def plan() -> dict:
    return {"plan": store.get_plan(), "history": store.plan_history()}


class Recommendation(BaseModel):
    topic: str


@app.post("/api/recommend")
def recommend(req: Recommendation) -> dict:
    _require_data()
    try:
        result = advisor.recommend(req.topic)
    except advisor.AdvisorError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
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
        entry.meal, entry.qty, entry.serving, entry.date, entry.food_id)


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
# Frontend
# ---------------------------------------------------------------------------
@app.get("/")
def index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


app.mount("/", StaticFiles(directory=FRONTEND_DIR), name="static")
