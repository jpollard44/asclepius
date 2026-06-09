"""The health advisor: Claude grounded in the user's data via tools."""
from __future__ import annotations

import json
import os

import anthropic

from . import analytics
from .config import MODEL

SYSTEM_PROMPT = """\
You are Asclepius, a personal health advisor analysing one individual's own \
Apple Health data. You are knowledgeable, encouraging, and precise.

Your job:
- Help the user understand their sleep, activity & fitness, heart health, and \
body & vitals.
- Ground every observation in their actual numbers. Use the tools to look up \
real values, trends, and time series before making claims — never invent data.
- When you cite a figure, say what it is, the value with units, and the time \
window (e.g. "your resting heart rate averaged 58 bpm over the last 30 days, \
down from 62 the month before").
- Surface patterns and correlations across areas (e.g. how sleep tracks with \
HRV or activity), and give specific, actionable suggestions.
- Be honest about data gaps. If a metric isn't recorded, say so rather than \
guessing.

Style: lead with the answer, keep it focused, use short sections or bullets \
for readouts. Default to the metric system already in the data.

Important safety boundary: you are not a doctor and this is not medical advice \
or diagnosis. For anything that looks clinically concerning, for symptoms, or \
for decisions about medication or treatment, advise the user to consult a \
qualified healthcare professional. If something suggests an emergency, tell \
them to seek urgent care. Keep this proportionate — a brief, relevant note, \
not a disclaimer on every message."""


TOOLS = [
    {
        "name": "list_metrics",
        "description": "List which health metrics are available in the user's "
                       "data, with units, focus area, and how many days each covers.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_metric_summary",
        "description": "Get headline statistics (latest value, average, min, "
                       "max, variability, and trend) for one metric over a recent window.",
        "input_schema": {
            "type": "object",
            "properties": {
                "metric_key": {"type": "string",
                               "description": "Metric key, e.g. 'steps', 'resting_heart_rate', 'hrv'."},
                "days": {"type": "integer",
                         "description": "Window in days (default 90)."},
            },
            "required": ["metric_key"],
        },
    },
    {
        "name": "get_metric_timeseries",
        "description": "Get the day-by-day series for one metric over a recent "
                       "window. Long series are downsampled to weekly averages.",
        "input_schema": {
            "type": "object",
            "properties": {
                "metric_key": {"type": "string"},
                "days": {"type": "integer",
                         "description": "Window in days (default 90)."},
            },
            "required": ["metric_key"],
        },
    },
    {
        "name": "get_sleep_summary",
        "description": "Get sleep statistics over a recent window: average time "
                       "asleep, consistency, REM/deep averages, and trend.",
        "input_schema": {
            "type": "object",
            "properties": {"days": {"type": "integer", "description": "Default 30."}},
        },
    },
    {
        "name": "get_workouts_summary",
        "description": "Get a breakdown of recorded workouts by activity over a "
                       "recent window: counts, total minutes, distance, and energy.",
        "input_schema": {
            "type": "object",
            "properties": {"days": {"type": "integer", "description": "Default 30."}},
        },
    },
]


def _downsample(series: list[dict], max_points: int = 26) -> list[dict]:
    """Collapse a daily series into weekly averages when it's long."""
    if len(series) <= max_points:
        return [{"date": r["date"], "value": r["value"]} for r in series]
    bucket: dict[str, list[float]] = {}
    for r in series:
        # ISO year-week key.
        from datetime import date as _d
        y, w, _ = _d.fromisoformat(r["date"]).isocalendar()
        bucket.setdefault(f"{y}-W{w:02d}", []).append(r["value"])
    return [{"week": k, "avg": round(sum(v) / len(v), 2), "n": len(v)}
            for k, v in sorted(bucket.items())]


def _run_tool(name: str, args: dict) -> dict:
    if name == "list_metrics":
        return {"metrics": analytics.available_metrics()}
    if name == "get_metric_summary":
        return analytics.metric_summary(args["metric_key"], int(args.get("days", 90)))
    if name == "get_metric_timeseries":
        days = int(args.get("days", 90))
        series = analytics.metric_series(args["metric_key"], days=days)
        if not series:
            return {"available": False, "metric_key": args["metric_key"]}
        return {
            "metric_key": args["metric_key"],
            "unit": series[-1]["unit"],
            "points": _downsample(series),
        }
    if name == "get_sleep_summary":
        return analytics.sleep_summary(int(args.get("days", 30)))
    if name == "get_workouts_summary":
        return analytics.workouts_summary(int(args.get("days", 30)))
    return {"error": f"unknown tool {name}"}


class AdvisorError(RuntimeError):
    pass


def chat(messages: list[dict], max_tool_turns: int = 8) -> dict:
    """Run a grounded advisor turn.

    ``messages`` is the running conversation in Anthropic format. Returns the
    assistant's reply text plus the updated message history (so tool_use /
    tool_result blocks are preserved for the next turn).
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise AdvisorError(
            "ANTHROPIC_API_KEY is not set. Add it to your environment or .env "
            "file so the advisor can run.")

    client = anthropic.Anthropic()
    convo = list(messages)

    # Ground every turn with a compact, current snapshot of the data so the
    # model always has context, then let it drill in via tools as needed.
    digest = json.dumps(analytics.full_digest(), default=str)
    system = [
        {"type": "text", "text": SYSTEM_PROMPT},
        {"type": "text",
         "text": f"Snapshot of the user's current health data:\n{digest}"},
    ]

    for _ in range(max_tool_turns):
        response = client.messages.create(
            model=MODEL,
            max_tokens=16000,
            thinking={"type": "adaptive"},
            output_config={"effort": "high"},
            system=system,
            tools=TOOLS,
            messages=convo,
        )
        convo.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            text = "".join(b.text for b in response.content if b.type == "text")
            return {"reply": text.strip(), "messages": convo}

        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                try:
                    result = _run_tool(block.name, block.input or {})
                except Exception as exc:  # surface tool errors back to the model
                    result = {"error": str(exc)}
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result, default=str),
                })
        convo.append({"role": "user", "content": tool_results})

    return {
        "reply": "I looked into your data but couldn't wrap up that analysis in "
                 "time. Could you narrow the question a little?",
        "messages": convo,
    }
