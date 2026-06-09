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
