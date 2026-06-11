"""The health coach: a proactive agent grounded in the user's data.

Asclepius is framed as an ongoing advisor whose mission is to move the user
toward the optimal version of themselves. It reads real Apple Health data via
tools, and maintains a single living plan it can save and revise.
"""
from __future__ import annotations

import json
import os

import anthropic

from . import analytics, tracking, units
from .config import MODEL, VISION_MODEL
from .store import SOURCE_MANUAL, get_plan, save_plan

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

Goals and milestones:
- The user has trackable goals scored against their real data. Use `get_goals` \
to see active goals with current value and progress. When you and the user agree \
on a concrete target in conversation (e.g. "get to 175 lb", "hit 180g protein a \
day", "100 fl oz of water"), SET it with `create_goal` so progress tracks \
automatically; pick the right category and direction (increase/decrease/maintain) \
and pass the baseline you read from the data so progress is measured from where \
they are today. Revise a target, push a date, or mark a goal done with \
`update_goal`. Pass goal numbers in US units (lb, fl oz) just like the log tools.
- Use `get_achievements` to see earned and unearned badges/milestones. Celebrate \
newly-earned ones by name, and point out the next achievable badge as motivation.

Reading the detailed history:
- Beyond summaries, you can pull the actual logged records: `get_food_log` for \
recent meals/items the user ate, `get_water_history` for daily water over a \
range, and `get_sleep_log` for individual nights. Use these to reference \
specifics ("you've had chicken and rice three days running") rather than only \
citing averages.

Logging on the user's behalf:
- When the user tells you about something they did — a meal or snack, water, a \
workout, a body measurement (weight, body fat, or full body-composition from a \
smart scale: muscle mass, body water, bone mass, visceral fat, BMR, metabolic \
age, and more), or a night's sleep — LOG IT for them using the log_* tools, then \
confirm what you saved. Don't make them open another tab.
- For food, estimate the nutrition yourself from your knowledge (calories, \
protein, carbs, fat, and fiber/sugar/sodium when you can) for the portion they \
describe; lean on known values for common items. Pick the right meal slot from \
context (breakfast/lunch/dinner/snack), defaulting to snack.
- Take the user's words in US units (pounds, fluid ounces, miles) — the tools \
convert to the metric the database stores, so just pass what the user said.
- Default the date to today unless the user clearly means another day (e.g. \
"last night's sleep" logs to last night). After logging, weave a brief, natural \
confirmation into your coaching rather than dumping the raw record.

Style: warm but direct, like a coach who believes in the user. Lead with the \
takeaway. Use short sections and bullets. Use US customary units throughout — \
pounds (lb), feet/inches, miles, fluid ounces, and Fahrenheit. The data you \
read via tools and in the snapshot is already converted to US units, so cite it \
as-is (e.g. "weight is down to 178 lb", "you ran 3.1 mi"). Avoid hedging and \
filler.

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
        "name": "get_dashboard",
        "description": "Get today's snapshot across every area: nutrition totals "
                       "and goals, water, steps, last night's sleep, workouts this "
                       "week, current streaks, and goal progress.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_nutrition_summary",
        "description": "Get logged food statistics over a recent window: daily "
                       "calories and macros (protein/carbs/fat), averages, and trend.",
        "input_schema": {
            "type": "object",
            "properties": {"days": {"type": "integer", "description": "Default 7."}},
        },
    },
    {
        "name": "get_goals",
        "description": "List the user's active goals with their target, current "
                       "value read from the data, and progress percent.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_workout_volume",
        "description": "Get strength-training volume (sets×reps×weight) over a "
                       "window, broken down by exercise, plus session count.",
        "input_schema": {
            "type": "object",
            "properties": {"days": {"type": "integer", "description": "Default 30."}},
        },
    },
    {
        "name": "get_personal_records",
        "description": "Get the user's heaviest lift and estimated 1RM per "
                       "strength exercise, all-time.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_achievements",
        "description": "List every badge/milestone with its title, description, "
                       "and whether the user has earned it (and when). Use to "
                       "celebrate wins and point out the next reachable badge.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_water_history",
        "description": "Get daily water intake (total per day, in fluid ounces) "
                       "over a recent window — not just today.",
        "input_schema": {
            "type": "object",
            "properties": {"days": {"type": "integer", "description": "Default 30."}},
        },
    },
    {
        "name": "get_food_log",
        "description": "Get recent individual food-log entries — the actual items "
                       "the user logged (name, meal, serving, calories, macros), "
                       "most recent first. Use to reference what they actually ate.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "description": "Window in days (default 7)."},
                "limit": {"type": "integer", "description": "Max entries (default 50)."},
            },
        },
    },
    {
        "name": "get_sleep_log",
        "description": "Get individual night-by-night sleep entries (hours asleep, "
                       "in bed, REM/deep) over a recent window — not just the summary.",
        "input_schema": {
            "type": "object",
            "properties": {"days": {"type": "integer", "description": "Default 30."}},
        },
    },
    {
        "name": "create_goal",
        "description": "Create a trackable goal scored against the user's data. "
                       "Set this when you and the user agree on a concrete target. "
                       "Pass target/baseline in US units (lb for weight, fl oz for "
                       "water); other categories use their natural unit (%, kcal, "
                       "g, hours, steps). Provide the baseline you read from the "
                       "data so progress measures from where they are today.",
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "enum": ["weight", "body_fat", "nutrition_calories",
                             "nutrition_protein", "sleep", "steps", "activity",
                             "water", "custom"],
                    "description": "What the goal tracks (drives how progress is scored).",
                },
                "label": {"type": "string",
                          "description": "Short human label, e.g. 'Cut to 175 lb'."},
                "target_value": {"type": "number",
                                 "description": "Target value in US units for the category."},
                "baseline_value": {"type": "number",
                                   "description": "Starting value (US units), read from the data."},
                "direction": {"type": "string",
                              "enum": ["increase", "decrease", "maintain"],
                              "description": "Whether the target is above, below, or near "
                                             "baseline. Default 'increase'."},
                "target_date": {"type": "string",
                                "description": "Optional target date (YYYY-MM-DD)."},
                "notes": {"type": "string", "description": "Optional note."},
            },
            "required": ["category", "target_value"],
        },
    },
    {
        "name": "update_goal",
        "description": "Update an existing goal — change its target, push the date, "
                       "or mark it done. Use get_goals to find the goal_id. "
                       "Target/baseline are in US units, like create_goal.",
        "input_schema": {
            "type": "object",
            "properties": {
                "goal_id": {"type": "integer", "description": "ID of the goal to update."},
                "target_value": {"type": "number", "description": "New target (US units)."},
                "baseline_value": {"type": "number", "description": "New baseline (US units)."},
                "target_date": {"type": "string", "description": "New target date (YYYY-MM-DD)."},
                "direction": {"type": "string",
                              "enum": ["increase", "decrease", "maintain"]},
                "status": {"type": "string", "enum": ["active", "done", "archived"],
                           "description": "Set 'done' when the goal is achieved."},
                "label": {"type": "string", "description": "New label."},
                "notes": {"type": "string", "description": "New note."},
            },
            "required": ["goal_id"],
        },
    },
    {
        "name": "log_food",
        "description": "Log a food/meal the user says they ate to their food "
                       "diary. Estimate nutrition from your own knowledge for the "
                       "portion described (use known values for common foods). "
                       "Calories and macros are for the whole portion eaten.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string",
                         "description": "Short food/meal name, e.g. 'Chicken breast and rice'."},
                "kcal": {"type": "number", "description": "Calories for the whole portion eaten."},
                "protein": {"type": "number", "description": "Protein in grams. Default 0."},
                "carbs": {"type": "number", "description": "Carbohydrates in grams. Default 0."},
                "fat": {"type": "number", "description": "Fat in grams. Default 0."},
                "fiber": {"type": "number", "description": "Fiber in grams, if known."},
                "sugar": {"type": "number", "description": "Sugar in grams, if known."},
                "sodium": {"type": "number", "description": "Sodium in milligrams, if known."},
                "serving": {"type": "string",
                            "description": "Portion in US units, e.g. '6 oz', '1 cup', '1 plate'."},
                "meal": {"type": "string", "enum": ["breakfast", "lunch", "dinner", "snack"],
                         "description": "Meal slot. Default 'snack'."},
                "date": {"type": "string", "description": "ISO date (YYYY-MM-DD). Default today."},
            },
            "required": ["name", "kcal"],
        },
    },
    {
        "name": "log_water",
        "description": "Log water the user drank. Amount is in fluid ounces "
                       "(convert glasses/bottles to fl oz first, e.g. a glass ≈ 8 fl oz).",
        "input_schema": {
            "type": "object",
            "properties": {
                "amount_floz": {"type": "number", "description": "Amount of water in fluid ounces."},
                "date": {"type": "string", "description": "ISO date (YYYY-MM-DD). Default today."},
            },
            "required": ["amount_floz"],
        },
    },
    {
        "name": "log_workout",
        "description": "Log a workout the user did. For cardio pass duration and "
                       "distance; for strength pass an exercises list with sets "
                       "(reps and weight in pounds).",
        "input_schema": {
            "type": "object",
            "properties": {
                "activity": {"type": "string",
                             "description": "Activity name, e.g. 'Treadmill run', 'Push day'."},
                "type": {"type": "string", "enum": ["strength", "cardio", "other"],
                         "description": "Workout type. Default 'other'."},
                "duration_min": {"type": "number", "description": "Duration in minutes."},
                "distance_mi": {"type": "number", "description": "Distance in miles (cardio)."},
                "energy_kcal": {"type": "number", "description": "Calories burned, if known."},
                "exercises": {
                    "type": "array",
                    "description": "Strength exercises with their sets.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "Exercise name, e.g. 'Bench press'."},
                            "sets": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "reps": {"type": "number"},
                                        "weight": {"type": "number",
                                                   "description": "Weight in pounds."},
                                    },
                                },
                            },
                        },
                        "required": ["name"],
                    },
                },
                "notes": {"type": "string", "description": "Optional note."},
                "date": {"type": "string", "description": "ISO date (YYYY-MM-DD). Default today."},
            },
            "required": ["activity"],
        },
    },
    {
        "name": "log_body_measurement",
        "description": "Log a body measurement or full smart-scale body-composition "
                       "reading the user reports. Weights are in pounds, waist in "
                       "inches, percentages in percent. Pass only the fields the "
                       "user gave; the rest are skipped.",
        "input_schema": {
            "type": "object",
            "properties": {
                "weight_lb": {"type": "number", "description": "Body weight in pounds."},
                "body_fat_pct": {"type": "number", "description": "Body fat percentage."},
                "lean_body_mass_lb": {"type": "number", "description": "Lean body mass in pounds."},
                "waist_in": {"type": "number", "description": "Waist circumference in inches."},
                "muscle_mass_lb": {"type": "number", "description": "Muscle mass in pounds."},
                "muscle_mass_pct": {"type": "number", "description": "Muscle mass as percent of body weight."},
                "body_water_pct": {"type": "number", "description": "Body water percentage."},
                "bone_mass_lb": {"type": "number", "description": "Bone mass in pounds."},
                "protein_pct": {"type": "number", "description": "Protein percentage."},
                "visceral_fat": {"type": "number", "description": "Visceral fat rating (unitless)."},
                "bmr": {"type": "number", "description": "Basal metabolic rate in kcal/day."},
                "metabolic_age": {"type": "number", "description": "Metabolic age in years."},
                "skeletal_muscle_pct": {"type": "number", "description": "Skeletal muscle percentage."},
                "fat_content_lb": {"type": "number", "description": "Total fat mass in pounds."},
                "subcutaneous_fat_pct": {"type": "number", "description": "Subcutaneous fat percentage."},
                "bmi": {"type": "number", "description": "Body mass index (unitless)."},
                "date": {"type": "string", "description": "ISO date (YYYY-MM-DD). Default today."},
            },
        },
    },
    {
        "name": "log_sleep",
        "description": "Log a night of sleep the user reports. Hours asleep is "
                       "required; bed/wake times and quality are optional.",
        "input_schema": {
            "type": "object",
            "properties": {
                "asleep_hours": {"type": "number", "description": "Total hours actually asleep."},
                "in_bed_hours": {"type": "number", "description": "Hours in bed, if different."},
                "bed_time": {"type": "string", "description": "Time went to bed, e.g. '11:00 PM'."},
                "wake_time": {"type": "string", "description": "Time woke up, e.g. '6:30 AM'."},
                "quality": {"type": "string",
                            "description": "Subjective quality, e.g. 'good', 'restless'."},
                "date": {"type": "string",
                         "description": "ISO date the night belongs to (the morning's date). "
                                        "Default today; use yesterday for 'last night' logged "
                                        "in the morning only if the user means it."},
            },
            "required": ["asleep_hours"],
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
    if name == "get_dashboard":
        return analytics.dashboard()
    if name == "get_nutrition_summary":
        return analytics.nutrition_summary(int(args.get("days", 7)))
    if name == "get_goals":
        return {"goals": analytics.goals_progress()}
    if name == "get_workout_volume":
        return analytics.workout_volume(int(args.get("days", 30)))
    if name == "get_personal_records":
        return {"records": analytics.personal_records()}
    if name == "get_achievements":
        badges = analytics.achievements()
        return {"achievements": badges,
                "earned": sum(1 for b in badges if b["unlocked"]),
                "total": len(badges)}
    if name == "get_water_history":
        return {"days": int(args.get("days", 30)),
                "series": tracking.water_series(int(args.get("days", 30)))}
    if name == "get_food_log":
        return {"entries": tracking.recent_food(int(args.get("days", 7)),
                                               int(args.get("limit", 50)))}
    if name == "get_sleep_log":
        return {"entries": analytics.sleep_series(days=int(args.get("days", 30)))}
    if name == "create_goal":
        return _create_goal(args)
    if name == "update_goal":
        return _update_goal(args)
    if name == "log_food":
        return _log_food(args)
    if name == "log_water":
        return _log_water(args)
    if name == "log_workout":
        return _log_workout(args)
    if name == "log_body_measurement":
        return _log_body_measurement(args)
    if name == "log_sleep":
        return _log_sleep(args)
    if name == "get_plan":
        return get_plan() or {"plan": None, "note": "No plan saved yet."}
    if name == "save_plan":
        return save_plan(args["goal"], args.get("focus", []), args["content"])
    return {"error": f"unknown tool {name}"}


# ---------------------------------------------------------------------------
# Logging tools: take US units from the user, store the metric the DB expects,
# and return a confirmation the model can read back. _run_tool's result is run
# through units.localized(), so any metric fields here are re-localized to US
# units before the model sees them — keep the human-facing confirmation in the
# top-level keys (already US units) and let nested DB rows convert themselves.
# ---------------------------------------------------------------------------
def _log_food(args: dict) -> dict:
    entry = tracking.add_food(
        name=args["name"],
        kcal=float(args["kcal"]),
        protein=float(args.get("protein") or 0),
        carbs=float(args.get("carbs") or 0),
        fat=float(args.get("fat") or 0),
        fiber=args.get("fiber"),
        sugar=args.get("sugar"),
        sodium=args.get("sodium"),
        meal=args.get("meal") or "snack",
        serving=args.get("serving", ""),
        date=args.get("date"),
    )
    return {
        "logged": "food",
        "name": entry["name"],
        "meal": entry["meal"],
        "date": entry["date"],
        "kcal": round(entry["kcal"], 0),
        "protein_g": round(entry["protein"], 1),
        "carbs_g": round(entry["carbs"], 1),
        "fat_g": round(entry["fat"], 1),
        "confirmation": f"Logged {entry['name']} to {entry['meal']} "
                        f"({round(entry['kcal'])} kcal, {round(entry['protein'])}g protein).",
    }


def _log_water(args: dict) -> dict:
    floz = float(args["amount_floz"])
    result = tracking.add_water(units.floz_to_ml(floz), date=args.get("date"))
    total_floz = round(units.convert_value(result["total_ml"], "ml"), 0)
    return {
        "logged": "water",
        "date": result["date"],
        "amount_floz": round(floz, 0),
        "day_total_floz": total_floz,
        "confirmation": f"Logged {round(floz)} fl oz of water — "
                        f"{total_floz} fl oz total today.",
    }


def _log_workout(args: dict) -> dict:
    exercises = args.get("exercises")
    if exercises:  # convert each set's weight from lb to kg for storage
        converted = []
        for ex in exercises:
            sets = []
            for s in ex.get("sets") or []:
                kg = units.lb_to_kg(float(s["weight"])) if s.get("weight") is not None else None
                sets.append({"reps": s.get("reps"), "weight": kg})
            converted.append({"name": ex.get("name", "Exercise"), "sets": sets})
        exercises = converted
    distance_km = (units.mi_to_km(float(args["distance_mi"]))
                   if args.get("distance_mi") is not None else None)
    entry = tracking.add_workout(
        activity=args["activity"],
        type=args.get("type", "other"),
        duration_min=args.get("duration_min"),
        distance_km=distance_km,
        energy_kcal=args.get("energy_kcal"),
        exercises=exercises,
        notes=args.get("notes", ""),
        date=args.get("date"),
    )
    bits = [entry["activity"]]
    if entry.get("duration_min"):
        bits.append(f"{round(entry['duration_min'])} min")
    if args.get("distance_mi"):
        bits.append(f"{round(float(args['distance_mi']), 1)} mi")
    return {
        "logged": "workout",
        "activity": entry["activity"],
        "type": entry["type"],
        "date": entry["date"],
        "confirmation": "Logged workout: " + ", ".join(bits) + ".",
    }


# Body-measurement input field -> (canonical metric key, converter from the US
# input to the stored unit, human-readable confirmation formatter). kg/cm fields
# convert from lb/in; %, ratings and counts store as-is.
_BODY_FIELDS = [
    ("weight_lb", "body_mass", units.lb_to_kg, lambda v: f"weight {round(v, 1)} lb"),
    ("body_fat_pct", "body_fat", None, lambda v: f"body fat {round(v, 1)}%"),
    ("lean_body_mass_lb", "lean_body_mass", units.lb_to_kg,
     lambda v: f"lean mass {round(v, 1)} lb"),
    ("waist_in", "waist", units.in_to_cm, lambda v: f"waist {round(v, 1)} in"),
    ("muscle_mass_lb", "muscle_mass", units.lb_to_kg,
     lambda v: f"muscle mass {round(v, 1)} lb"),
    ("muscle_mass_pct", "muscle_mass_pct", None, lambda v: f"muscle {round(v, 1)}%"),
    ("body_water_pct", "body_water", None, lambda v: f"body water {round(v, 1)}%"),
    ("bone_mass_lb", "bone_mass", units.lb_to_kg, lambda v: f"bone mass {round(v, 1)} lb"),
    ("protein_pct", "protein_pct", None, lambda v: f"protein {round(v, 1)}%"),
    ("visceral_fat", "visceral_fat", None, lambda v: f"visceral fat {round(v, 1)}"),
    ("bmr", "bmr", None, lambda v: f"BMR {round(v)} kcal"),
    ("metabolic_age", "metabolic_age", None, lambda v: f"metabolic age {round(v)} yr"),
    ("skeletal_muscle_pct", "skeletal_muscle", None,
     lambda v: f"skeletal muscle {round(v, 1)}%"),
    ("fat_content_lb", "fat_content", units.lb_to_kg,
     lambda v: f"fat mass {round(v, 1)} lb"),
    ("subcutaneous_fat_pct", "subcutaneous_fat", None,
     lambda v: f"subcutaneous fat {round(v, 1)}%"),
    ("bmi", "bmi", None, lambda v: f"BMI {round(v, 1)}"),
]


def _log_body_measurement(args: dict) -> dict:
    date = args.get("date")
    values: dict[str, float] = {}
    saved = []
    for field, metric, conv, fmt in _BODY_FIELDS:
        if args.get(field) is None:
            continue
        raw = float(args[field])
        values[metric] = conv(raw) if conv else raw
        saved.append(fmt(raw))
    if not values:
        return {"error": "No measurement provided to log."}
    tracking.log_body_metrics(date, values, source=SOURCE_MANUAL)
    return {
        "logged": "body_measurement",
        "date": date or tracking._today(),
        "confirmation": "Logged " + ", ".join(saved) + ".",
    }


# Goal categories whose target/baseline arrive in US units and must be stored in
# the canonical unit. Other categories (%, kcal, g, hours, steps) store as-is.
_GOAL_INPUT_CONV = {
    "weight": units.lb_to_kg,    # lb -> kg
    "water": units.floz_to_ml,   # fl oz -> ml
}


def _create_goal(args: dict) -> dict:
    category = args["category"]
    conv = _GOAL_INPUT_CONV.get(category)
    target = args.get("target_value")
    baseline = args.get("baseline_value")
    if conv:
        if target is not None:
            target = conv(float(target))
        if baseline is not None:
            baseline = conv(float(baseline))
    row = tracking.create_goal(
        category=category,
        label=args.get("label", ""),
        target=target,
        baseline=baseline,
        direction=args.get("direction", "increase"),
        target_date=args.get("target_date"),
        notes=args.get("notes", ""),
    )
    disp_unit = units.imperial_unit(row["unit"]) or row["unit"] or ""
    target_txt = f" (target {args.get('target_value')} {disp_unit}".rstrip() + ")"
    return {
        "created": "goal",
        "goal_id": row["id"],
        "goal": row,
        "confirmation": f"Set goal '{row['label']}'{target_txt}.",
    }


def _update_goal(args: dict) -> dict:
    goal_id = int(args["goal_id"])
    existing = tracking.get_goal(goal_id)
    if not existing:
        return {"error": f"No goal with id {goal_id}."}
    conv = _GOAL_INPUT_CONV.get(existing["category"])
    fields: dict = {}
    if args.get("target_value") is not None:
        v = float(args["target_value"])
        fields["target"] = conv(v) if conv else v
    if args.get("baseline_value") is not None:
        v = float(args["baseline_value"])
        fields["baseline"] = conv(v) if conv else v
    for key in ("target_date", "direction", "status", "label", "notes"):
        if args.get(key) is not None:
            fields[key] = args[key]
    row = tracking.update_goal(goal_id, **fields)
    return {
        "updated": "goal",
        "goal_id": goal_id,
        "goal": row,
        "confirmation": f"Updated goal '{(row or existing).get('label')}'.",
    }


def _log_sleep(args: dict) -> dict:
    hours = float(args["asleep_hours"])
    notes = []
    if args.get("bed_time"):
        notes.append(f"bed {args['bed_time']}")
    if args.get("wake_time"):
        notes.append(f"wake {args['wake_time']}")
    if args.get("quality"):
        notes.append(f"quality: {args['quality']}")
    result = tracking.log_sleep(
        date=args.get("date"),
        asleep_hours=hours,
        in_bed_hours=args.get("in_bed_hours"),
    )
    conf = f"Logged {round(hours, 1)}h of sleep for {result['date']}"
    if notes:
        conf += " (" + ", ".join(notes) + ")"
    return {"logged": "sleep", "date": result["date"], "asleep_hours": hours,
            "confirmation": conf + "."}


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

    digest = json.dumps(units.localized(analytics.full_digest()), default=str)
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
                    "content": json.dumps(units.localized(result), default=str),
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


RECOMMENDATION_PROMPTS = {
    "meals": (
        "Based on what I've eaten recently and my nutrition goals, recommend "
        "specific meals or food swaps for the rest of today. Look at my logged "
        "food and remaining calories/protein. Give 2-3 concrete options with "
        "rough macros. Be practical."
    ),
    "workout": (
        "Recommend my next workout. Look at my recent training volume, what I've "
        "trained lately, and my goals. Give a specific session (exercises, sets, "
        "reps, target weights where you can) and say why."
    ),
    "recovery": (
        "Assess my recovery right now from sleep, resting heart rate, HRV, and "
        "recent training load. Tell me whether to push or pull back today, and "
        "what to do about it."
    ),
    "focus": (
        "Look across all my data and tell me the single most important thing to "
        "focus on this week to move toward my goals, with a concrete action."
    ),
}


def recommend(topic: str) -> dict:
    """Produce a focused, data-grounded recommendation on one topic."""
    instruction = RECOMMENDATION_PROMPTS.get(
        topic,
        f"Give me a specific, data-grounded recommendation about: {topic}.")
    return chat([{"role": "user", "content": instruction}])


# ---------------------------------------------------------------------------
# Photo-based food logging (vision)
# ---------------------------------------------------------------------------
FOOD_PHOTO_SYSTEM = """\
You are a nutrition estimator. You are shown a photo of a meal, snack, or drink. \
Identify the food and estimate its nutrition for the portion that is actually \
visible in the image, then call the `food_estimate` tool exactly once.

Rules:
- Use US units: describe the serving in ounces, cups, or natural units (e.g. \
"6 oz", "1 cup", "1 medium apple", "2 slices"). Energy in kilocalories.
- Macros (protein, carbs, fat, fiber, sugar) are in grams; sodium is in \
milligrams — this matches how US nutrition labels read.
- Estimate for the WHOLE portion shown, not per 100 g and not per generic \
serving. If there are multiple items on the plate, sum them and say so in notes.
- It's fine to be approximate — give your best single estimate, not a range. \
Briefly note assumptions (portion size, cooking method, hidden oils) in `notes`.
- If the image clearly is not food, set name to "Unknown" and all numbers to 0 \
and explain in `notes`."""

FOOD_PHOTO_TOOL = {
    "name": "food_estimate",
    "description": "Record the estimated nutrition for the food in the photo.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {"type": "string",
                     "description": "Short name of the food/meal, e.g. 'Grilled chicken salad'."},
            "serving": {"type": "string",
                        "description": "Portion shown, in US units, e.g. '6 oz', '1 cup', '2 slices'."},
            "kcal": {"type": "number", "description": "Calories for the whole portion shown."},
            "protein": {"type": "number", "description": "Protein in grams."},
            "carbs": {"type": "number", "description": "Carbohydrates in grams."},
            "fat": {"type": "number", "description": "Fat in grams."},
            "fiber": {"type": "number", "description": "Fiber in grams."},
            "sugar": {"type": "number", "description": "Sugar in grams."},
            "sodium": {"type": "number", "description": "Sodium in milligrams."},
            "notes": {"type": "string",
                      "description": "Brief note on assumptions or what's on the plate."},
        },
        "required": ["name", "serving", "kcal", "protein", "carbs", "fat",
                     "fiber", "sugar", "sodium", "notes"],
        "additionalProperties": False,
    },
}


def analyze_food_photo(image_data: str, media_type: str) -> dict:
    """Estimate macros/micros from a base64-encoded food photo via Claude vision.

    Returns the tool input dict (name, serving, kcal, macros, micros, notes).
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise AdvisorError(
            "ANTHROPIC_API_KEY is not set. Add it to your environment or .env "
            "file so photo analysis can run.")

    client = anthropic.Anthropic()
    response = client.messages.create(
        model=VISION_MODEL,
        max_tokens=1024,
        system=FOOD_PHOTO_SYSTEM,
        tools=[FOOD_PHOTO_TOOL],
        tool_choice={"type": "tool", "name": "food_estimate"},
        messages=[{
            "role": "user",
            "content": [
                {"type": "image",
                 "source": {"type": "base64", "media_type": media_type, "data": image_data}},
                {"type": "text",
                 "text": "Estimate the nutrition of the food in this photo for the "
                         "portion shown, then call the food_estimate tool."},
            ],
        }],
    )
    for block in response.content:
        if block.type == "tool_use" and block.name == "food_estimate":
            return dict(block.input)
    raise AdvisorError("The model did not return a food estimate. Try another photo.")
