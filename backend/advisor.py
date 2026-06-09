"""The health coach: a proactive agent grounded in the user's data.

Asclepius is framed as an ongoing advisor whose mission is to move the user
toward the optimal version of themselves. It reads real Apple Health data via
tools, and maintains a single living plan it can save and revise.
"""
from __future__ import annotations

import json
import os

import anthropic

from . import analytics
from .config import MODEL
from .store import get_plan, save_plan

SYSTEM_PROMPT = """\
You are Asclepius — the user's personal health coach and advisor. Your mission \
is singular: help this person become the optimal version of themselves. You \
think like a great longevity-and-performance coach who blends sleep, training, \
recovery, cardiovascular health, and body composition into one coherent \
strategy.

You are PROACTIVE, not a passive Q&A bot:
- Tell the user what matters in their data before they ask. Surface the signal, \
not every number.
- Form a point of view. Be direct and specific about what's working, what's \
holding them back, and what to do next.
- Think in terms of a plan and progress over time, always oriented toward the \
goal of being optimal.

Grounding (non-negotiable):
- Use the tools to read the user's actual data — summaries, trends, time series, \
sleep, workouts — before making claims. Never invent numbers.
- Cite real figures with units and time windows (e.g. "resting HR averaged \
57 bpm over 30 days, down 4% from the prior month — that's a good sign your \
aerobic base is improving").
- If a metric isn't recorded, say so and suggest how to start tracking it.

The living plan:
- You maintain ONE plan for the user via the `save_plan` tool. Call `get_plan` \
to see the current one. When you create or meaningfully revise the plan, SAVE it.
- A good plan has: a clear goal statement, 2-4 focus areas, and concrete, \
trackable weekly actions with target numbers tied to their data (e.g. "raise \
average sleep from 6.9h to 7.5h: lights-out by 11pm on 5+ nights"). Keep it \
realistic and sequenced — progress, not perfection.
- On later turns, check the plan, assess progress against it using the data, \
celebrate wins, and adjust.

Style: warm but direct, like a coach who believes in the user. Lead with the \
takeaway. Use short sections and bullets. Default to the metric system already \
in the data. Avoid hedging and filler.

Safety boundary: you are not a doctor and this is not medical diagnosis or \
treatment advice. For anything clinically concerning, symptoms, or decisions \
about medication, advise consulting a qualified professional; for anything that \
sounds like an emergency, urgent care. Keep this proportionate — a brief, \
relevant note when warranted, not a disclaimer on every message."""


BRIEFING_INSTRUCTION = (
    "Give me my health briefing. Read across my sleep, activity & fitness, "
    "heart health, and body & vitals. Tell me: what stands out, what's going "
    "well, and the 2-3 things most worth improving to become the optimal "
    "version of myself. Then build my initial plan with concrete weekly "
    "actions and targets tied to my numbers, and save it. Be specific and "
    "motivating."
)


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
                "days": {"type": "integer", "description": "Window in days (default 90)."},
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
                "days": {"type": "integer", "description": "Window in days (default 90)."},
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
    {
        "name": "get_plan",
        "description": "Retrieve the user's current saved health plan, if any.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "save_plan",
        "description": "Create or update the user's living health plan. Call this "
                       "whenever you build or meaningfully revise the plan.",
        "input_schema": {
            "type": "object",
            "properties": {
                "goal": {"type": "string",
                         "description": "One-sentence statement of the user's overarching goal."},
                "focus": {"type": "array", "items": {"type": "string"},
                          "description": "2-4 short focus areas, e.g. 'Sleep consistency', 'Aerobic base'."},
                "content": {"type": "string",
                            "description": "The full plan body in markdown: focus areas with "
                                           "concrete weekly actions and target numbers tied to the data."},
            },
            "required": ["goal", "focus", "content"],
        },
    },
]


def _downsample(series: list[dict], max_points: int = 26) -> list[dict]:
    if len(series) <= max_points:
        return [{"date": r["date"], "value": r["value"]} for r in series]
    from datetime import date as _d
    bucket: dict[str, list[float]] = {}
    for r in series:
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
        return {"metric_key": args["metric_key"], "unit": series[-1]["unit"],
                "points": _downsample(series)}
    if name == "get_sleep_summary":
        return analytics.sleep_summary(int(args.get("days", 30)))
    if name == "get_workouts_summary":
        return analytics.workouts_summary(int(args.get("days", 30)))
    if name == "get_plan":
        return get_plan() or {"plan": None, "note": "No plan saved yet."}
    if name == "save_plan":
        return save_plan(args["goal"], args.get("focus", []), args["content"])
    return {"error": f"unknown tool {name}"}


class AdvisorError(RuntimeError):
    pass


def chat(messages: list[dict], max_tool_turns: int = 10) -> dict:
    """Run a grounded coaching turn and return the reply plus message history."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise AdvisorError(
            "ANTHROPIC_API_KEY is not set. Add it to your environment or .env "
            "file so the coach can run.")

    client = anthropic.Anthropic()
    convo = list(messages)

    digest = json.dumps(analytics.full_digest(), default=str)
    plan = get_plan()
    plan_note = (f"\nThe user's current saved plan:\n{json.dumps(plan, default=str)}"
                 if plan else "\nThe user has no saved plan yet — build one when appropriate.")
    system = [
        {"type": "text", "text": SYSTEM_PROMPT},
        {"type": "text",
         "text": f"Snapshot of the user's current health data:\n{digest}{plan_note}"},
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
                except Exception as exc:  # surface tool errors to the model
                    result = {"error": str(exc)}
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result, default=str),
                })
        convo.append({"role": "user", "content": tool_results})

    return {
        "reply": "I dug into your data but couldn't wrap that up in time — "
                 "ask me to focus on one area and I'll go deeper.",
        "messages": convo,
    }


def briefing() -> dict:
    """Generate the proactive opening briefing (and initial plan)."""
    return chat([{"role": "user", "content": BRIEFING_INSTRUCTION}])
