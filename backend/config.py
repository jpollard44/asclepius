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

# Body & vitals metrics a user can log by hand. These share the daily_metrics
# table with imported data (stored with source='manual'), so manual entries
# survive a re-import and show up on the same charts.
MANUAL_METRICS = {
    "body_mass": {"label": "Weight", "unit": "kg", "area": "body", "agg": "avg"},
    "body_fat": {"label": "Body Fat", "unit": "%", "area": "body", "agg": "avg"},
    "lean_body_mass": {"label": "Lean Body Mass", "unit": "kg", "area": "body", "agg": "avg"},
    "waist": {"label": "Waist", "unit": "cm", "area": "body", "agg": "avg"},
    "chest": {"label": "Chest", "unit": "cm", "area": "body", "agg": "avg"},
    "hips": {"label": "Hips", "unit": "cm", "area": "body", "agg": "avg"},
    "arm": {"label": "Arm", "unit": "cm", "area": "body", "agg": "avg"},
    "thigh": {"label": "Thigh", "unit": "cm", "area": "body", "agg": "avg"},
    "resting_heart_rate": {"label": "Resting Heart Rate", "unit": "bpm", "area": "heart", "agg": "avg"},
    "bp_systolic": {"label": "Blood Pressure (Systolic)", "unit": "mmHg", "area": "heart", "agg": "avg"},
    "bp_diastolic": {"label": "Blood Pressure (Diastolic)", "unit": "mmHg", "area": "heart", "agg": "avg"},
}

# Meal slots for the food log, in the order they're shown.
MEALS = ["breakfast", "lunch", "dinner", "snack"]

# Workout categories. Strength workouts carry an exercises list (sets/reps/
# weight); cardio workouts carry distance/pace; "other" is freeform.
WORKOUT_TYPES = ["strength", "cardio", "other"]

# Goal categories the user can set. Each maps loosely to a metric/area so the
# coach and the milestone engine know how to score progress.
GOAL_CATEGORIES = {
    "weight": {"label": "Weight", "metric": "body_mass", "unit": "kg"},
    "body_fat": {"label": "Body fat", "metric": "body_fat", "unit": "%"},
    "nutrition_calories": {"label": "Daily calories", "metric": "calories", "unit": "kcal"},
    "nutrition_protein": {"label": "Daily protein", "metric": "protein", "unit": "g"},
    "sleep": {"label": "Sleep", "metric": "asleep_hours", "unit": "h"},
    "steps": {"label": "Daily steps", "metric": "steps", "unit": "steps"},
    "activity": {"label": "Weekly workouts", "metric": "workouts_per_week", "unit": "/wk"},
    "water": {"label": "Daily water", "metric": "water_ml", "unit": "ml"},
    "custom": {"label": "Custom", "metric": None, "unit": ""},
}

# Default daily water goal (ml) when the user hasn't set one.
DEFAULT_WATER_GOAL_ML = 2500

# A small built-in food database so logging on a phone is a couple of taps.
# Macros are per the listed serving. (name, category, serving, kcal, P, C, F)
COMMON_FOODS = [
    # Protein
    ("Chicken breast (cooked)", "protein", "100 g", 165, 31, 0, 3.6),
    ("Salmon (cooked)", "protein", "100 g", 208, 20, 0, 13),
    ("Lean beef (cooked)", "protein", "100 g", 217, 26, 0, 12),
    ("Eggs", "protein", "2 large", 156, 13, 1.1, 11),
    ("Greek yogurt (plain)", "protein", "170 g", 100, 17, 6, 0.7),
    ("Tofu (firm)", "protein", "100 g", 144, 17, 3, 9),
    ("Whey protein", "protein", "1 scoop", 120, 24, 3, 1.5),
    ("Canned tuna", "protein", "100 g", 116, 26, 0, 1),
    ("Shrimp (cooked)", "protein", "100 g", 99, 24, 0.2, 0.3),
    ("Cottage cheese", "protein", "100 g", 98, 11, 3.4, 4.3),
    # Carbs
    ("White rice (cooked)", "carbs", "1 cup", 205, 4.3, 45, 0.4),
    ("Brown rice (cooked)", "carbs", "1 cup", 216, 5, 45, 1.8),
    ("Oats (dry)", "carbs", "50 g", 190, 6.5, 33, 3.5),
    ("Sweet potato", "carbs", "1 medium", 112, 2, 26, 0.1),
    ("Banana", "carbs", "1 medium", 105, 1.3, 27, 0.4),
    ("Apple", "carbs", "1 medium", 95, 0.5, 25, 0.3),
    ("Whole-wheat bread", "carbs", "1 slice", 80, 4, 14, 1),
    ("Pasta (cooked)", "carbs", "1 cup", 220, 8, 43, 1.3),
    ("Bagel", "carbs", "1 medium", 250, 10, 48, 1.5),
    ("Potato", "carbs", "1 medium", 161, 4.3, 37, 0.2),
    # Fats / nuts
    ("Almonds", "fats", "30 g", 173, 6, 6, 15),
    ("Peanut butter", "fats", "2 tbsp", 188, 8, 6, 16),
    ("Avocado", "fats", "1/2", 120, 1.5, 6, 11),
    ("Olive oil", "fats", "1 tbsp", 119, 0, 0, 14),
    ("Cheddar cheese", "fats", "30 g", 120, 7, 0.4, 10),
    # Veg / fruit
    ("Broccoli", "veg", "100 g", 34, 2.8, 7, 0.4),
    ("Spinach", "veg", "100 g", 23, 2.9, 3.6, 0.4),
    ("Mixed salad", "veg", "1 bowl", 40, 2, 7, 0.5),
    ("Blueberries", "veg", "100 g", 57, 0.7, 14, 0.3),
    # Meals / misc
    ("Protein bar", "snack", "1 bar", 220, 20, 22, 7),
    ("Coffee (black)", "drink", "1 cup", 2, 0.3, 0, 0),
    ("Latte", "drink", "1 medium", 130, 8, 13, 5),
    ("Orange juice", "drink", "1 cup", 112, 1.7, 26, 0.5),
    ("Pizza slice", "meal", "1 slice", 285, 12, 36, 10),
    ("Burrito", "meal", "1", 450, 20, 55, 16),
    ("Chicken salad", "meal", "1 plate", 350, 30, 15, 18),
    ("Protein shake", "drink", "1", 160, 30, 5, 2.5),
]

# Badge definitions for the milestone engine. Each is evaluated against the
# user's logs in analytics.achievements().
ACHIEVEMENTS = [
    {"key": "first_meal", "icon": "🍽", "title": "First bite",
     "desc": "Logged your first meal."},
    {"key": "first_workout", "icon": "🏋", "title": "First rep",
     "desc": "Logged your first workout."},
    {"key": "hydrated", "icon": "💧", "title": "Hydrated",
     "desc": "Hit your water goal in a day."},
    {"key": "food_streak_7", "icon": "🔥", "title": "Week of logging",
     "desc": "Logged food 7 days in a row."},
    {"key": "workout_streak_3", "icon": "⚡", "title": "Consistency",
     "desc": "Worked out 3 weeks running."},
    {"key": "protein_hit", "icon": "💪", "title": "Protein on point",
     "desc": "Hit your protein goal."},
    {"key": "10k_steps", "icon": "👟", "title": "10k club",
     "desc": "Walked 10,000+ steps in a day."},
    {"key": "early_bird", "icon": "🌙", "title": "Well rested",
     "desc": "Averaged 7.5h+ sleep over a week."},
    {"key": "goal_crushed", "icon": "🏆", "title": "Goal crusher",
     "desc": "Completed a goal."},
    {"key": "first_pr", "icon": "📈", "title": "New PR",
     "desc": "Set a personal record on a lift."},
]
