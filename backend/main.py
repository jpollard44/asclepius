"""Asclepius web app: upload Apple Health data and chat with your advisor."""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import advisor, analytics, parser, store
from .config import DATA_DIR, FRONTEND_DIR

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
    if not store.has_data():
        return {"has_data": False}
    return {
        "has_data": True,
        "date_range": analytics.date_range(),
        "meta": store.get_meta(),
        "metrics": analytics.available_metrics(),
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
    return {"reply": result["reply"]}


# ---------------------------------------------------------------------------
# Frontend
# ---------------------------------------------------------------------------
@app.get("/")
def index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


app.mount("/", StaticFiles(directory=FRONTEND_DIR), name="static")
