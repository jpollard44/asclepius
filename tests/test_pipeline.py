"""End-to-end tests for the parse → store → analytics pipeline.

Generates a synthetic Apple Health export into a temp dir, loads it through a
temporary SQLite DB, and asserts the analytics layer returns sane results.
"""
import subprocess
import sys
from pathlib import Path

import pytest

from backend import analytics, parser, store

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def loaded_db(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("health")
    export = tmp / "export.xml"
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "generate_sample_export.py"),
         "60", str(export)],
        check=True,
    )
    db = tmp / "health.db"
    # Point analytics/store at the temp DB (store.DB_PATH is the default used
    # whenever db_path is None).
    original = store.DB_PATH
    store.DB_PATH = db
    parsed = parser.parse_export(export)
    store.replace_data(parsed)
    yield db
    store.DB_PATH = original


def test_parse_produces_records(loaded_db):
    assert store.has_data()
    rng = analytics.date_range()
    assert rng["start"] and rng["end"]


def test_metrics_available(loaded_db):
    keys = {m["key"] for m in analytics.available_metrics()}
    assert {"steps", "resting_heart_rate", "hrv", "body_mass"} <= keys


def test_heart_rate_unit_normalised(loaded_db):
    summ = analytics.metric_summary("resting_heart_rate", 90)
    assert summ["available"]
    assert summ["unit"] == "bpm"
    assert 40 <= summ["latest"] <= 100


def test_sleep_summary(loaded_db):
    s = analytics.sleep_summary(30)
    assert s["available"]
    assert 3 <= s["avg_asleep_hours"] <= 12
    assert s["nights_recorded"] > 0


def test_workouts_parsed_with_stats(loaded_db):
    w = analytics.workouts_summary(60)
    assert w["total_workouts"] > 0
    # At least one cardio activity should carry distance/energy from
    # the <WorkoutStatistics> children.
    assert any(a.get("total_kcal") for a in w["by_activity"])


def test_trend_direction_present(loaded_db):
    summ = analytics.metric_summary("steps", 60)
    assert summ["trend"]["direction"] in {"up", "down", "flat"}


def test_daily_goals_personalized_defaults(tmp_path):
    """Daily targets default to the personalized (non-FDA) values and every
    tracked metric is present."""
    db = tmp_path / "goals.db"
    goals = store.get_daily_goals(db_path=db)
    assert {"calories", "protein", "carbs", "fat", "fiber", "sugar",
            "sodium", "water", "steps", "active_energy", "sleep"} <= set(goals)
    # Active 127 lb male — not the 2,000 kcal / 50 g label defaults.
    assert goals["calories"]["target"] == 2200
    assert goals["protein"]["target"] == 130
    assert goals["sugar"]["lower_better"] is True
    assert goals["calories"]["customized"] is False


def test_daily_goals_override_and_reset(tmp_path):
    db = tmp_path / "goals.db"
    updated = store.set_daily_goals({"calories": 2400}, db_path=db)
    assert updated["calories"]["target"] == 2400
    assert updated["calories"]["customized"] is True
    # Other metrics keep their defaults.
    assert updated["protein"]["target"] == 130
    # A null value resets to the recommended default.
    reset = store.set_daily_goals({"calories": None}, db_path=db)
    assert reset["calories"]["target"] == 2200
    assert reset["calories"]["customized"] is False


def test_nutrition_goals_flow_from_daily_goals(tmp_path):
    """today_nutrition surfaces the daily targets under *_goal keys."""
    db = tmp_path / "goals.db"
    store.set_daily_goals({"protein": 140}, db_path=db)
    today = analytics.today_nutrition(db_path=db)
    assert today["protein_goal"] == 140
    assert today["kcal_goal"] == 2200
    assert today["sodium_goal"] == 2300
