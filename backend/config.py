"""Configuration and metric definitions for Asclepius."""
import os
from pathlib import Path

# Project layout
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
FRONTEND_DIR = BASE_DIR / "frontend"

DATA_DIR.mkdir(exist_ok=True)

DB_PATH = Path(os.environ.get("ASCLEPIUS_DB", DATA_DIR / "health.db"))

# The advisor model. Opus 4.8 is the most capable model for grounded reasoning.
MODEL = os.environ.get("ASCLEPIUS_MODEL", "claude-opus-4-8")

# Apple Health quantity record types we ingest, mapped to a friendly key, the
# aggregation to apply per day ("sum" or "avg"), a display label, a unit, and
# the focus area it belongs to.
QUANTITY_TYPES = {
    # --- Activity & fitness ---
    "HKQuantityTypeIdentifierStepCount": {
        "key": "steps", "agg": "sum", "label": "Steps", "unit": "count", "area": "activity"},
    "HKQuantityTypeIdentifierDistanceWalkingRunning": {
        "key": "distance", "agg": "sum", "label": "Walking + Running Distance", "unit": "km", "area": "activity"},
    "HKQuantityTypeIdentifierActiveEnergyBurned": {
        "key": "active_energy", "agg": "sum", "label": "Active Energy", "unit": "kcal", "area": "activity"},
    "HKQuantityTypeIdentifierBasalEnergyBurned": {
        "key": "basal_energy", "agg": "sum", "label": "Resting Energy", "unit": "kcal", "area": "activity"},
    "HKQuantityTypeIdentifierAppleExerciseTime": {
        "key": "exercise_time", "agg": "sum", "label": "Exercise Time", "unit": "min", "area": "activity"},
    "HKQuantityTypeIdentifierAppleStandTime": {
        "key": "stand_time", "agg": "sum", "label": "Stand Time", "unit": "min", "area": "activity"},
    "HKQuantityTypeIdentifierFlightsClimbed": {
        "key": "flights_climbed", "agg": "sum", "label": "Flights Climbed", "unit": "count", "area": "activity"},
    "HKQuantityTypeIdentifierVO2Max": {
        "key": "vo2_max", "agg": "avg", "label": "VO2 Max", "unit": "mL/kg·min", "area": "activity"},
    # --- Heart health ---
    "HKQuantityTypeIdentifierHeartRate": {
        "key": "heart_rate", "agg": "avg", "label": "Heart Rate", "unit": "bpm", "area": "heart"},
    "HKQuantityTypeIdentifierRestingHeartRate": {
        "key": "resting_heart_rate", "agg": "avg", "label": "Resting Heart Rate", "unit": "bpm", "area": "heart"},
    "HKQuantityTypeIdentifierWalkingHeartRateAverage": {
        "key": "walking_heart_rate", "agg": "avg", "label": "Walking Heart Rate Avg", "unit": "bpm", "area": "heart"},
    "HKQuantityTypeIdentifierHeartRateVariabilitySDNN": {
        "key": "hrv", "agg": "avg", "label": "Heart Rate Variability (SDNN)", "unit": "ms", "area": "heart"},
    "HKQuantityTypeIdentifierBloodPressureSystolic": {
        "key": "bp_systolic", "agg": "avg", "label": "Blood Pressure (Systolic)", "unit": "mmHg", "area": "heart"},
    "HKQuantityTypeIdentifierBloodPressureDiastolic": {
        "key": "bp_diastolic", "agg": "avg", "label": "Blood Pressure (Diastolic)", "unit": "mmHg", "area": "heart"},
    # --- Body & vitals ---
    "HKQuantityTypeIdentifierBodyMass": {
        "key": "body_mass", "agg": "avg", "label": "Weight", "unit": "kg", "area": "body"},
    "HKQuantityTypeIdentifierBodyMassIndex": {
        "key": "bmi", "agg": "avg", "label": "BMI", "unit": "count", "area": "body"},
    "HKQuantityTypeIdentifierBodyFatPercentage": {
        "key": "body_fat", "agg": "avg", "label": "Body Fat", "unit": "%", "area": "body"},
    "HKQuantityTypeIdentifierLeanBodyMass": {
        "key": "lean_body_mass", "agg": "avg", "label": "Lean Body Mass", "unit": "kg", "area": "body"},
    "HKQuantityTypeIdentifierRespiratoryRate": {
        "key": "respiratory_rate", "agg": "avg", "label": "Respiratory Rate", "unit": "breaths/min", "area": "body"},
    "HKQuantityTypeIdentifierOxygenSaturation": {
        "key": "blood_oxygen", "agg": "avg", "label": "Blood Oxygen", "unit": "%", "area": "body"},
    "HKQuantityTypeIdentifierBodyTemperature": {
        "key": "body_temperature", "agg": "avg", "label": "Body Temperature", "unit": "degC", "area": "body"},
}

# Sleep analysis category values, grouped into the buckets we report on.
SLEEP_VALUES = {
    "HKCategoryValueSleepAnalysisInBed": "in_bed",
    "HKCategoryValueSleepAnalysisAsleep": "asleep",            # legacy
    "HKCategoryValueSleepAnalysisAsleepUnspecified": "asleep",
    "HKCategoryValueSleepAnalysisAsleepCore": "core",
    "HKCategoryValueSleepAnalysisAsleepDeep": "deep",
    "HKCategoryValueSleepAnalysisAsleepREM": "rem",
    "HKCategoryValueSleepAnalysisAwake": "awake",
}
# Which buckets count toward total time asleep.
ASLEEP_BUCKETS = {"asleep", "core", "deep", "rem"}

# Metrics where Apple may store a 0-1 fraction we want to show as a percentage.
PERCENT_KEYS = {"blood_oxygen", "body_fat"}
