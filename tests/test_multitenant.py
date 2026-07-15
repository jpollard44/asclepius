"""Tests for the multi-tenant service mode: auth, isolation, sync, deletion.

Uses the dev login (email-only) so no Apple round-trip is needed; the Apple
path shares everything below the token-verification step.
"""
import pytest
from fastapi.testclient import TestClient

from backend import auth, config, main, store, tenancy


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """A TestClient running in multi-tenant mode against a temp data dir."""
    monkeypatch.setenv("ASCLEPIUS_MULTI_TENANT", "1")
    monkeypatch.setenv("ASCLEPIUS_DEV_LOGIN", "1")
    monkeypatch.setenv("ASCLEPIUS_SECRET", "test-secret")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    return TestClient(main.app)


def _login(client, email="a@example.com", name="Alex"):
    resp = client.post("/api/auth/dev", json={"email": email, "name": name})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _bearer(session):
    return {"Authorization": f"Bearer {session['access_token']}"}


SYNC_PAYLOAD = {
    "metrics": [
        {"metric": "steps", "date": "2026-07-14", "value": 9500, "unit": "count"},
        {"metric": "resting_heart_rate", "date": "2026-07-14", "value": 52,
         "unit": "bpm"},
        {"metric": "not_a_real_metric", "date": "2026-07-14", "value": 1},
    ],
    "sleep": [
        {"date": "2026-07-14", "asleep_hours": 7.4, "in_bed_hours": 8.0,
         "rem_hours": 1.5, "deep_hours": 1.1},
    ],
    "workouts": [
        {"external_id": "hk-uuid-1", "date": "2026-07-14",
         "activity": "Running", "duration_min": 31, "distance_km": 5.2,
         "energy_kcal": 320},
    ],
}


def test_health_is_public(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["multi_tenant"] is True


def test_api_requires_auth(client):
    assert client.get("/api/status").status_code == 401
    assert client.get("/api/dashboard").status_code == 401
    bad = client.get("/api/status", headers={"Authorization": "Bearer nope"})
    assert bad.status_code == 401


def test_dev_login_and_status(client):
    session = _login(client)
    assert session["user"]["email"] == "a@example.com"
    resp = client.get("/api/status", headers=_bearer(session))
    assert resp.status_code == 200
    assert resp.json()["has_data"] is False


def test_healthkit_sync_and_isolation(client):
    alex = _login(client, "a@example.com")
    resp = client.post("/api/sync/healthkit", json=SYNC_PAYLOAD,
                       headers=_bearer(alex))
    assert resp.status_code == 200
    body = resp.json()
    assert body["upserted"] == {"metrics": 2, "sleep": 1, "workouts": 1}
    assert body["skipped"] == 1  # the unknown metric key

    status = client.get("/api/status", headers=_bearer(alex)).json()
    assert status["has_data"] is True
    assert status["has_import"] is True
    metric = client.get("/api/metric/steps", headers=_bearer(alex)).json()
    assert metric["series"][-1]["value"] == 9500

    # A second user sees none of Alex's data.
    blake = _login(client, "b@example.com", name="Blake")
    assert client.get("/api/status", headers=_bearer(blake)).json()["has_data"] is False

    # And their manual logs stay separate too.
    client.post("/api/food", json={"name": "Oats", "kcal": 190},
                headers=_bearer(blake))
    alex_food = client.get("/api/food", headers=_bearer(alex)).json()
    blake_food = client.get("/api/food", headers=_bearer(blake)).json()
    assert alex_food["entries"] == []
    assert len(blake_food["entries"]) == 1


def test_healthkit_sync_is_idempotent(client):
    session = _login(client)
    for _ in range(2):
        resp = client.post("/api/sync/healthkit", json=SYNC_PAYLOAD,
                           headers=_bearer(session))
        assert resp.status_code == 200
    workouts = client.get("/api/workouts", headers=_bearer(session)).json()
    assert len(workouts["workouts"]) == 1  # deduped on external_id
    # Re-syncing a day updates rather than duplicates the daily metric.
    updated = dict(SYNC_PAYLOAD)
    updated["metrics"] = [{"metric": "steps", "date": "2026-07-14",
                           "value": 10001, "unit": "count"}]
    client.post("/api/sync/healthkit", json=updated, headers=_bearer(session))
    metric = client.get("/api/metric/steps", headers=_bearer(session)).json()
    values = [p["value"] for p in metric["series"] if p["date"] == "2026-07-14"]
    assert values == [10001]


def test_refresh_rotation(client):
    session = _login(client)
    resp = client.post("/api/auth/refresh",
                       json={"refresh_token": session["refresh_token"]})
    assert resp.status_code == 200
    renewed = resp.json()
    assert renewed["access_token"]
    # The presented refresh token was revoked by the rotation.
    again = client.post("/api/auth/refresh",
                        json={"refresh_token": session["refresh_token"]})
    assert again.status_code == 401
    # The new pair works.
    ok = client.get("/api/status", headers=_bearer(renewed))
    assert ok.status_code == 200


def test_logout_revokes_refresh(client):
    session = _login(client)
    client.post("/api/auth/logout",
                json={"refresh_token": session["refresh_token"]})
    resp = client.post("/api/auth/refresh",
                       json={"refresh_token": session["refresh_token"]})
    assert resp.status_code == 401


def test_account_deletion_removes_everything(client, tmp_path):
    session = _login(client)
    client.post("/api/sync/healthkit", json=SYNC_PAYLOAD,
                headers=_bearer(session))
    user_id = session["user"]["id"]
    assert tenancy.user_db_path(user_id, create=False).exists()

    resp = client.delete("/api/account", headers=_bearer(session))
    assert resp.status_code == 200
    assert resp.json()["status"] == "deleted"
    assert not tenancy.user_db_path(user_id, create=False).parent.exists()
    # The old access token no longer authenticates.
    assert client.get("/api/status", headers=_bearer(session)).status_code == 401


def test_device_registration(client):
    session = _login(client)
    resp = client.post("/api/devices",
                       json={"token": "abc123", "environment": "sandbox"},
                       headers=_bearer(session))
    assert resp.status_code == 200
    devices = auth.list_devices(session["user"]["id"])
    assert devices and devices[0]["token"] == "abc123"
    assert devices[0]["environment"] == "sandbox"
    gone = client.delete("/api/devices/abc123", headers=_bearer(session))
    assert gone.json()["removed"] is True


def test_coach_quota(client, monkeypatch):
    monkeypatch.setenv("ASCLEPIUS_CHAT_DAILY_LIMIT", "0")
    session = _login(client)
    client.post("/api/sync/healthkit", json=SYNC_PAYLOAD,
                headers=_bearer(session))
    resp = client.post("/api/chat",
                       json={"messages": [{"role": "user", "content": "hi"}]},
                       headers=_bearer(session))
    assert resp.status_code == 429


def test_local_mode_needs_no_auth(tmp_path, monkeypatch):
    monkeypatch.delenv("ASCLEPIUS_MULTI_TENANT", raising=False)
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "health.db")
    local = TestClient(main.app)
    resp = local.get("/api/status")
    assert resp.status_code == 200
    assert resp.json()["has_data"] is False
