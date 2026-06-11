"""Imperial / US-customary conversion for the coach.

Asclepius stores everything in canonical metric units (kg, km, cm, ml, °C) so
the analytics math stays consistent and a re-import never has to rewrite old
rows. The *user* reads US units, though — the frontend converts for display and
back for entry, and this module does the same for the advisor so the coach
cites pounds, miles, fluid ounces and Fahrenheit instead of metric.

Food macros (protein/carbs/fat/fiber/sugar in grams, sodium in mg, energy in
kcal) are left as-is — those are reported in the same units on US nutrition
labels — while food *serving sizes* are described in ounces in the food DB.
"""
from __future__ import annotations

from copy import deepcopy

KG_TO_LB = 2.2046226218
KM_TO_MI = 0.6213711922
CM_TO_IN = 0.3937007874
ML_TO_FLOZ = 0.0338140227
G_TO_OZ = 0.0352739619

# Canonical metric unit -> (imperial label, linear factor). Temperature is
# handled separately because it's affine (offset + scale), not just a scale.
_LINEAR = {
    "kg": ("lb", KG_TO_LB),
    "km": ("mi", KM_TO_MI),
    "cm": ("in", CM_TO_IN),
    "ml": ("fl oz", ML_TO_FLOZ),
}

# Numeric fields that share a sibling "unit" key in analytics payloads.
_VALUE_KEYS = {
    "value", "latest", "average", "avg", "avg_90d", "min", "max", "current",
    "target", "baseline", "first_half_avg", "second_half_avg",
}
# A spread (std deviation) scales but doesn't take the temperature offset.
_SPREAD_KEYS = {"std_dev"}

# Keys whose metric unit is baked into the name. We convert the value AND rename
# the key so the model never has to guess what unit a number is in.
_KEY_RENAME = {
    "total_km": ("total_mi", "km"),
    "distance_km": ("distance_mi", "km"),
    "total_ml": ("total_floz", "ml"),
    "goal_ml": ("goal_floz", "ml"),
    "amount_ml": ("amount_floz", "ml"),
    "water_ml": ("water_floz", "ml"),
}
# Weights with no unit sibling (strength volume, lifts) — always kilograms.
_WEIGHT_KEYS = {"weight", "e1rm", "volume", "total_volume"}


def imperial_unit(unit: str | None) -> str | None:
    """The US label for a metric unit, or None if it doesn't change."""
    if not isinstance(unit, str):
        return None
    if unit in _LINEAR:
        return _LINEAR[unit][0]
    if unit == "degC":
        return "°F"
    return None


# Imperial -> canonical metric, for writing user input back into the DB. The
# coach takes US units from the user (lb, mi, fl oz, in) and these put them back
# into the kg/km/ml/cm the store expects.
def lb_to_kg(value: float) -> float:
    return value / KG_TO_LB


def mi_to_km(value: float) -> float:
    return value / KM_TO_MI


def in_to_cm(value: float) -> float:
    return value / CM_TO_IN


def floz_to_ml(value: float) -> float:
    return value / ML_TO_FLOZ


def convert_value(value, unit: str, spread: bool = False) -> float:
    """Convert one number from a metric unit to its US equivalent."""
    if not isinstance(value, (int, float)):
        return value
    if unit in _LINEAR:
        return value * _LINEAR[unit][1]
    if unit == "degC":
        return value * 9.0 / 5.0 if spread else value * 9.0 / 5.0 + 32.0
    return value


def localize(obj):
    """Deep-convert an analytics payload from metric to US units.

    Handles three shapes: dicts carrying a ``unit`` key (with sibling numeric
    fields), keys whose unit is in their name (``*_km`` / ``*_ml``), and bare
    weight fields that are always kilograms.
    """
    if isinstance(obj, list):
        return [localize(x) for x in obj]
    if not isinstance(obj, dict):
        return obj

    unit = obj.get("unit") if isinstance(obj.get("unit"), str) else None
    imp = imperial_unit(unit)
    out = {}
    for key, val in obj.items():
        if key == "unit" and imp:
            out[key] = imp
        elif imp and key in _VALUE_KEYS and isinstance(val, (int, float)):
            out[key] = round(convert_value(val, unit), 2)
        elif imp and key in _SPREAD_KEYS and isinstance(val, (int, float)):
            out[key] = round(convert_value(val, unit, spread=True), 2)
        elif key in _KEY_RENAME:
            new_key, src = _KEY_RENAME[key]
            out[new_key] = round(convert_value(val, src), 2) if isinstance(val, (int, float)) else localize(val)
        elif key in _WEIGHT_KEYS and isinstance(val, (int, float)):
            out[key] = round(val * KG_TO_LB, 2)
        else:
            out[key] = localize(val)
    return out


def localized(obj):
    """``localize`` on a deep copy, so the source payload is left untouched."""
    return localize(deepcopy(obj))
