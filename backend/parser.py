"""Streaming parser for an Apple Health `export.xml`.

The export can be hundreds of megabytes, so we parse iteratively and clear
elements as we go, aggregating records into per-day buckets rather than
holding every record in memory.
"""
from __future__ import annotations

import zipfile
from datetime import datetime
from pathlib import Path
from xml.etree.ElementTree import iterparse

from .config import (
    ASLEEP_BUCKETS,
    PERCENT_KEYS,
    QUANTITY_TYPES,
    SLEEP_VALUES,
)


def _parse_date(value: str | None) -> datetime | None:
    """Parse Apple's `YYYY-MM-DD HH:MM:SS +ZZZZ` timestamps."""
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S %z")
    except ValueError:
        try:
            return datetime.strptime(value[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None


def _convert(value: float, unit: str | None, key: str) -> tuple[float, str]:
    """Normalise common units so daily aggregates stay consistent."""
    unit = (unit or "").strip()
    if unit == "mi":
        return value * 1.60934, "km"
    if unit in ("lb", "lbs"):
        return value * 0.453592, "kg"
    if unit == "degF":
        return (value - 32) * 5.0 / 9.0, "degC"
    if unit == "count/min":  # Apple's unit for heart rate / respiratory rate
        return value, "bpm" if "heart" in key or key.endswith("heart_rate") else "breaths/min"
    if key in PERCENT_KEYS and value <= 1.0:
        return value * 100.0, "%"
    return value, unit


def resolve_export_path(path: Path) -> Path:
    """Given an uploaded file, return the path to the `export.xml` to parse.

    Accepts the raw XML directly, or a `.zip` produced by "Export All Health
    Data" (in which case the XML is extracted next to the zip).
    """
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as zf:
            member = None
            for name in zf.namelist():
                base = name.rsplit("/", 1)[-1]
                if base == "export.xml":
                    member = name
                    break
            if member is None:
                raise ValueError("No export.xml found inside the zip archive.")
            target = path.parent / "export.xml"
            with zf.open(member) as src, open(target, "wb") as dst:
                while chunk := src.read(1 << 20):
                    dst.write(chunk)
            return target
    return path


def parse_export(path: Path) -> dict:
    """Parse the export and return structured, aggregated data.

    Returns a dict with keys: ``meta``, ``daily`` (per metric/day aggregates),
    ``sleep`` (per night), and ``workouts``.
    """
    xml_path = resolve_export_path(path)

    # (metric_key, date_iso) -> running aggregate
    daily: dict[tuple[str, str], dict] = {}
    # night_date_iso -> bucket hours
    sleep: dict[str, dict] = {}
    workouts: list[dict] = []
    meta: dict = {"export_date": None, "sources": set()}

    context = iterparse(str(xml_path), events=("start", "end"))
    _, root = next(context)  # the <HealthData> root, for periodic pruning
    for event, elem in context:
        if event != "end":
            continue
        tag = elem.tag
        if tag == "Record":
            _handle_record(elem, daily, sleep, meta)
        elif tag == "Workout":
            _handle_workout(elem, workouts)
        elif tag == "ExportDate":
            meta["export_date"] = elem.get("value")
        elif tag == "Me":
            meta["biological_sex"] = elem.get(
                "HKCharacteristicTypeIdentifierBiologicalSex")
            meta["date_of_birth"] = elem.get(
                "HKCharacteristicTypeIdentifierDateOfBirth")
            meta["blood_type"] = elem.get(
                "HKCharacteristicTypeIdentifierBloodType")
        else:
            # Child elements (e.g. WorkoutStatistics) are handled with their
            # parent; don't clear them here or we'd wipe data before use.
            continue

        # Free the fully-processed top-level element and drop it from the root
        # so memory stays bounded on multi-hundred-MB exports.
        elem.clear()
        root.clear()

    meta["sources"] = sorted(meta["sources"])
    return {
        "meta": meta,
        "daily": _finalise_daily(daily),
        "sleep": _finalise_sleep(sleep),
        "workouts": workouts,
    }


def _handle_record(elem, daily, sleep, meta) -> None:
    rtype = elem.get("type")
    source = elem.get("sourceName")
    if source:
        meta["sources"].add(source)

    if rtype in QUANTITY_TYPES:
        cfg = QUANTITY_TYPES[rtype]
        start = _parse_date(elem.get("startDate") or elem.get("creationDate"))
        if start is None:
            return
        try:
            value = float(elem.get("value"))
        except (TypeError, ValueError):
            return
        value, unit = _convert(value, elem.get("unit"), cfg["key"])
        day = start.date().isoformat()
        bucket = daily.setdefault(
            (cfg["key"], day),
            {"sum": 0.0, "count": 0, "min": value, "max": value, "unit": unit},
        )
        bucket["sum"] += value
        bucket["count"] += 1
        bucket["min"] = min(bucket["min"], value)
        bucket["max"] = max(bucket["max"], value)
        bucket["unit"] = unit

    elif rtype == "HKCategoryTypeIdentifierSleepAnalysis":
        bucket_name = SLEEP_VALUES.get(elem.get("value"))
        if bucket_name is None:
            return
        start = _parse_date(elem.get("startDate"))
        end = _parse_date(elem.get("endDate"))
        if start is None or end is None or end <= start:
            return
        hours = (end - start).total_seconds() / 3600.0
        # Attribute a sleep sample to the morning it ends on (the "wake day").
        night = end.date().isoformat()
        night_bucket = sleep.setdefault(
            night,
            {"in_bed": 0.0, "asleep": 0.0, "core": 0.0, "deep": 0.0,
             "rem": 0.0, "awake": 0.0},
        )
        night_bucket[bucket_name] += hours


def _handle_workout(elem, workouts) -> None:
    start = _parse_date(elem.get("startDate"))
    activity = (elem.get("workoutActivityType") or "")
    activity = activity.replace("HKWorkoutActivityType", "") or "Workout"

    duration = _safe_float(elem.get("duration"))
    if (elem.get("durationUnit") or "min") != "min" and duration is not None:
        # Apple normally exports minutes; convert if it ever differs.
        if elem.get("durationUnit") == "sec":
            duration /= 60.0

    distance_km = _safe_float(elem.get("totalDistance"))
    if distance_km is not None and elem.get("totalDistanceUnit") == "mi":
        distance_km *= 1.60934
    energy = _safe_float(elem.get("totalEnergyBurned"))

    # Newer exports put distance/energy in <WorkoutStatistics> children.
    for stat in elem.findall("WorkoutStatistics"):
        stype = stat.get("type", "")
        ssum = _safe_float(stat.get("sum"))
        if ssum is None:
            continue
        if "Distance" in stype and distance_km is None:
            distance_km = ssum * (1.60934 if stat.get("unit") == "mi" else 1.0)
        elif "EnergyBurned" in stype and "Active" in stype and energy is None:
            energy = ssum

    workouts.append({
        "date": start.date().isoformat() if start else None,
        "activity": activity,
        "duration_min": round(duration, 1) if duration is not None else None,
        "distance_km": round(distance_km, 3) if distance_km is not None else None,
        "energy_kcal": round(energy, 1) if energy is not None else None,
    })


def _safe_float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _finalise_daily(daily) -> list[dict]:
    rows = []
    for (key, day), b in daily.items():
        cfg_agg = "sum"
        # Look up the aggregation from QUANTITY_TYPES by key.
        for cfg in QUANTITY_TYPES.values():
            if cfg["key"] == key:
                cfg_agg = cfg["agg"]
                break
        value = b["sum"] if cfg_agg == "sum" else b["sum"] / max(b["count"], 1)
        rows.append({
            "metric": key,
            "date": day,
            "value": round(value, 3),
            "min": round(b["min"], 3),
            "max": round(b["max"], 3),
            "count": b["count"],
            "unit": b["unit"],
        })
    return rows


def _finalise_sleep(sleep) -> list[dict]:
    rows = []
    for night, b in sleep.items():
        asleep = sum(b[k] for k in ASLEEP_BUCKETS)
        rows.append({
            "date": night,
            "asleep_hours": round(asleep, 2),
            "in_bed_hours": round(b["in_bed"], 2),
            "rem_hours": round(b["rem"], 2),
            "deep_hours": round(b["deep"], 2),
            "core_hours": round(b["core"], 2),
            "awake_hours": round(b["awake"], 2),
        })
    return rows
