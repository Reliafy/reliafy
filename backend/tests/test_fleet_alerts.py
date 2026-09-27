"""Fleet alerts: CRUD + access, evaluation on usage ingest, email, MCP tools."""

import matplotlib

matplotlib.use("Agg")

import io

import mongomock
import numpy as np
import pandas as pd
import pytest

A = "user-a"
B = "user-b"
USERS = {
    A: {"uid": A, "email": "a@x.com", "name": "A"},
    B: {"uid": B, "email": "b@x.com", "name": "B"},
}


@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app
    from backend.routers import ingest as ingest_router

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    monkeypatch.setattr(config, "PUBLIC_BASE_URL", "https://reliafy.test")
    test_db = mongomock.MongoClient()["reliafy_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    ingest_router._hits.clear()

    tc = TestClient(app)

    def act_as(uid):
        if uid is None:
            app.dependency_overrides.pop(get_current_user, None)
        else:
            app.dependency_overrides[get_current_user] = lambda: USERS[uid]
            test_db.users.update_one(
                {"_id": uid},
                {"$set": {"email": USERS[uid]["email"], "name": USERS[uid]["name"]}},
                upsert=True,
            )

    tc.act_as = act_as
    tc.db = test_db
    try:
        yield tc
    finally:
        app.dependency_overrides.clear()


@pytest.fixture()
def outbox(monkeypatch):
    """Capture alert email instead of sending it (SMTP 'configured')."""
    from backend.services import email as email_service

    sent = []

    def fake_send_now(to, subject, body, html=None, reply_to=None, headers=None):
        sent.append({"to": to, "subject": subject, "text": body, "html": html})

    monkeypatch.setattr(email_service, "enabled", lambda: True)
    monkeypatch.setattr(email_service, "send_now", fake_send_now)
    return sent


def _save_model(client):
    rng = np.random.default_rng(2)
    csv = io.BytesIO(pd.DataFrame({"hours": rng.weibull(2, 120) * 1000}).to_csv(index=False).encode())
    r = client.post(
        "/api/models",
        data={"name": "Bearings", "distribution": "weibull", "x": "hours", "unit": "hours"},
        files={"file": ("lives.csv", csv, "text/csv")},
    )
    assert r.status_code == 200, r.text
    return r.json()


def _setup(client, periods=12):
    """A's fleet (analytic 'single' method → deterministic) + an API token."""
    client.act_as(A)
    model = _save_model(client)
    fleet = client.post("/api/fleet/fleets", json={"name": "Trucks", "model_id": model["id"]}).json()
    r = client.put(
        f"/api/fleet/fleets/{fleet['id']}/items",
        json={
            "settings": {"periods": periods, "period_label": "months", "default_rate": 20, "method": "single"},
            "items": [{"name": "Truck 01", "current_use": 100}, {"name": "Truck 02", "current_use": 100}],
        },
    )
    assert r.status_code == 200, r.text
    token = client.post("/api/tokens", json={"name": "cron"}).json()["token"]
    return fleet["id"], token


def _ingest(client, fleet_id, token, use, **extra):
    r = client.post(
        f"/api/ingest/fleets/{fleet_id}/usage",
        json={"items": [{"name": "Truck 01", "current_use": use, **extra},
                        {"name": "Truck 02", "current_use": use, **extra}]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    return r.json()


def _alerts_url(fleet_id):
    return f"/api/fleet/fleets/{fleet_id}/alerts"


# ---- window metric ------------------------------------------------------------------

def test_window_value_interpolates_and_truncates():
    from backend.services.fleet_alerts import window_value

    series = [1.0, 2.0, 4.0, 8.0]
    assert window_value(series, 2.5) == (1.0 + 2.0 + 0.5 * 4.0, False)
    assert window_value(series, 1) == (1.0, False)
    assert window_value(series, 0.25) == (0.25, False)
    assert window_value(series, 4) == (15.0, False)
    assert window_value(series, 6) == (15.0, True)  # horizon shortened below Y


# ---- CRUD, validation, access -------------------------------------------------------

def test_crud_validation_and_initial_state(client):
    fid, _ = _setup(client)
    url = _alerts_url(fid)

    listed = client.get(url).json()
    assert listed["alerts"] == [] and listed["max_alerts"] == 10
    now = listed["current_value"]
    assert now > 0

    above = client.post(url, json={"kind": "above", "threshold": now + 1}).json()
    assert above["kind"] == "above" and above["enabled"] is True
    assert above["last_value"] == pytest.approx(now) and above["armed"] is True
    already = client.post(url, json={"kind": "above", "threshold": now / 2}).json()
    assert already["armed"] is False  # already past it: no email until it re-crosses

    change = client.post(url, json={"kind": "change", "percent": 25}).json()
    assert change["baseline_value"] == pytest.approx(now)
    within = client.post(url, json={"kind": "within", "x": 0.5, "y_periods": 2.5}).json()
    assert within["x"] == 0.5 and within["y_periods"] == 2.5 and within["truncated"] is False

    for bad in (
        {"kind": "below", "threshold": 1},
        {"kind": "above"},
        {"kind": "above", "threshold": -1},
        {"kind": "change", "percent": 0},
        {"kind": "change", "percent": 1001},
        {"kind": "within", "x": 0, "y_periods": 2},
        {"kind": "within", "x": 1, "y_periods": 13},   # beyond the 12-month horizon
        {"kind": "within", "x": 1, "y_periods": 0},
    ):
        r = client.post(url, json=bad)
        assert r.status_code == 422, (bad, r.text)

    rules = client.get(url).json()["alerts"]
    assert [r["kind"] for r in rules] == ["above", "above", "change", "within"]
    assert all(r["mine"] for r in rules)
    assert next(r for r in rules if r["id"] == within["id"])["current_value"] < now

    # Edit: disable, change threshold, invalid edit, unknown id.
    r = client.patch(f"{url}/{above['id']}", json={"enabled": False})
    assert r.status_code == 200 and r.json()["enabled"] is False
    r = client.patch(f"{url}/{change['id']}", json={"percent": 50})
    assert r.json()["percent"] == 50
    assert client.patch(f"{url}/{change['id']}", json={"percent": -5}).status_code == 422
    assert client.patch(f"{url}/{within['id']}", json={"y_periods": 99}).status_code == 422
    assert client.patch(f"{url}/nope", json={"enabled": True}).status_code == 404

    assert client.delete(f"{url}/{already['id']}").status_code == 200
    assert client.delete(f"{url}/{already['id']}").status_code == 404
    assert len(client.get(url).json()["alerts"]) == 3


def test_limit_of_ten_per_fleet(client):
    fid, _ = _setup(client)
    url = _alerts_url(fid)
    for i in range(10):
        assert client.post(url, json={"kind": "above", "threshold": i + 1}).status_code == 200
    r = client.post(url, json={"kind": "above", "threshold": 99})
    assert r.status_code == 422 and "10" in r.json()["detail"]


def test_access_matches_fleet_editing(client):
    fid, _ = _setup(client)
    url = _alerts_url(fid)
    rule = client.post(url, json={"kind": "above", "threshold": 5}).json()

    # A stranger can't see the fleet at all.
    client.act_as(B)
    assert client.get(url).status_code == 404
    assert client.post(url, json={"kind": "above", "threshold": 1}).status_code == 404
    assert client.delete(f"{url}/{rule['id']}").status_code == 404

    # Shared with B (view-only): readable fleet, but alerts are an edit → 403.
    client.db.shares.insert_one({"_id": "s1", "recipient_uid": B, "grantor_uid": A,
                                 "collection": "fleets", "artifact_id": fid})
    assert client.get(f"/api/fleet/fleets/{fid}").status_code == 200
    assert client.get(url).status_code == 403
    assert client.post(url, json={"kind": "above", "threshold": 1}).status_code == 403
    assert client.patch(f"{url}/{rule['id']}", json={"enabled": False}).status_code == 403
    assert client.delete(f"{url}/{rule['id']}").status_code == 403

    # Deleting the fleet removes its rules.
    client.act_as(A)
    assert client.delete(f"/api/fleet/fleets/{fid}").status_code == 200
    assert client.db.fleet_alerts.count_documents({"fleet_id": fid}) == 0


# ---- evaluation on ingest -------------------------------------------------------------

def _probe(client, fid, token, use, back_to=100):
    """Expected failures at ``use`` (ingest it, read it, restore)."""
    high = _ingest(client, fid, token, use)["forecast"]["expected"]
    _ingest(client, fid, token, back_to)
    return high


def test_above_rule_is_edge_triggered(client, outbox):
    fid, token = _setup(client)
    low = client.get(_alerts_url(fid)).json()["current_value"]
    high = _probe(client, fid, token, 900)
    assert high > low
    threshold = round((low + high) / 2, 2)
    rule = client.post(_alerts_url(fid), json={"kind": "above", "threshold": threshold}).json()
    assert rule["armed"] is True

    body = _ingest(client, fid, token, 900)
    assert body["alerts_fired"] == 1
    assert set(body) >= {"fleet", "updated_items", "forecast"}  # contract unchanged
    assert len(outbox) == 1
    msg = outbox[0]
    assert msg["to"] == "a@x.com"
    assert msg["subject"] == f"Fleet alert: Trucks — expected failures above {threshold:g}"
    assert f"{low:.1f} → {high:.1f}" in msg["text"]
    assert "over the next 12 months" in msg["text"]
    assert "usage update received via the API" in msg["text"] and "UTC" in msg["text"]
    assert f"https://reliafy.test/fleet/forecasts/{fid}" in msg["text"]
    assert "Manage alerts: " in msg["text"] and "Brisbane, Australia" in msg["text"]
    assert "Fleet alert" in msg["html"] and "View the fleet" in msg["html"]
    assert f"https://reliafy.test/fleet/forecasts/{fid}" in msg["html"]

    # Still above: no second email.
    assert _ingest(client, fid, token, 950)["alerts_fired"] == 0
    assert len(outbox) == 1
    # Drop below (re-arms, silently), then rise again → second email.
    assert _ingest(client, fid, token, 100)["alerts_fired"] == 0
    assert client.db.fleet_alerts.find_one({"_id": rule["id"]})["armed"] is True
    assert _ingest(client, fid, token, 900)["alerts_fired"] == 1
    assert len(outbox) == 2

    events = list(client.db.fleet_alert_events.find({"alert_id": rule["id"]}))
    assert len(events) == 2 and all(e["sent"] for e in events)
    assert events[0]["uid"] == A and events[0]["kind"] == "above"
    assert events[0]["previous_value"] == pytest.approx(low)
    assert events[0]["new_value"] == pytest.approx(high)
    assert events[0]["threshold"] == threshold
    stored = client.db.fleet_alerts.find_one({"_id": rule["id"]})
    assert stored["last_fired_value"] == pytest.approx(high) and stored["last_fired_at"] is not None


def test_change_rule_fires_and_rebaselines(client, outbox):
    fid, token = _setup(client)
    base = client.get(_alerts_url(fid)).json()["current_value"]
    mid = _probe(client, fid, token, 300)
    high = _probe(client, fid, token, 900)
    pct_mid = abs(mid - base) / base * 100
    rule = client.post(_alerts_url(fid), json={"kind": "change", "percent": pct_mid * 0.9}).json()

    assert _ingest(client, fid, token, 300)["alerts_fired"] == 1
    assert "expected failures changed by" in outbox[-1]["subject"]
    stored = client.db.fleet_alerts.find_one({"_id": rule["id"]})
    assert stored["baseline_value"] == pytest.approx(mid)
    assert stored["last_fired_value"] == pytest.approx(mid)

    # Same value again: 0% change from the new baseline → nothing.
    assert _ingest(client, fid, token, 300)["alerts_fired"] == 0
    # A small move from the new baseline: nothing.
    assert _ingest(client, fid, token, 320)["alerts_fired"] == 0
    # A big move from the new baseline (not from the original) fires again.
    assert abs(high - mid) / mid * 100 >= pct_mid * 0.9
    assert _ingest(client, fid, token, 900)["alerts_fired"] == 1
    events = list(client.db.fleet_alert_events.find({"alert_id": rule["id"]}).sort("created_at", 1))
    assert len(events) == 2
    assert events[0]["baseline_value"] == pytest.approx(base) and events[0]["percent"] == pytest.approx(pct_mid * 0.9)
    assert events[1]["baseline_value"] == pytest.approx(mid) and events[1]["new_value"] == pytest.approx(high)


def test_disabled_rule_never_fires(client, outbox):
    fid, token = _setup(client)
    rule = client.post(_alerts_url(fid), json={"kind": "above", "threshold": 0, "enabled": False}).json()
    client.post(_alerts_url(fid), json={"kind": "change", "percent": 1, "enabled": False})
    assert rule["enabled"] is False
    assert _ingest(client, fid, token, 900)["alerts_fired"] == 0
    assert outbox == [] and client.db.fleet_alert_events.count_documents({}) == 0


def test_reenabling_does_not_fire_for_a_standing_breach(client, outbox):
    fid, token = _setup(client)
    rule = client.post(_alerts_url(fid), json={"kind": "above", "threshold": 0.001, "enabled": False}).json()
    _ingest(client, fid, token, 900)
    r = client.patch(f"{_alerts_url(fid)}/{rule['id']}", json={"enabled": True}).json()
    assert r["armed"] is False  # already above → wait for the next crossing
    assert _ingest(client, fid, token, 950)["alerts_fired"] == 0 and outbox == []


def test_email_failure_is_recorded_and_ingest_still_succeeds(client, monkeypatch):
    from backend.services import email as email_service

    def boom(*a, **k):
        raise OSError("SMTP down")

    monkeypatch.setattr(email_service, "enabled", lambda: True)
    monkeypatch.setattr(email_service, "send_now", boom)
    fid, token = _setup(client)
    client.post(_alerts_url(fid), json={"kind": "above", "threshold": 0.0001 + client.get(_alerts_url(fid)).json()["current_value"]})
    body = _ingest(client, fid, token, 900)
    assert body["alerts_fired"] == 1
    event = client.db.fleet_alert_events.find_one({})
    assert event["sent"] is False and "SMTP down" in event["error"]


def test_unconfigured_smtp_records_unsent(client, monkeypatch):
    from backend.services import email as email_service

    monkeypatch.setattr(email_service, "enabled", lambda: False)
    fid, token = _setup(client)
    client.post(_alerts_url(fid), json={"kind": "change", "percent": 1})
    assert _ingest(client, fid, token, 900)["alerts_fired"] == 1
    event = client.db.fleet_alert_events.find_one({})
    assert event["sent"] is False and "SMTP" in event["error"]


def test_evaluation_errors_never_break_ingest(client, outbox, monkeypatch):
    from backend.services import fleet_alerts

    fid, token = _setup(client)
    client.post(_alerts_url(fid), json={"kind": "change", "percent": 1})

    # A failure inside one rule is contained…
    def bad_rule(rule, value):
        raise RuntimeError("bug")

    monkeypatch.setattr(fleet_alerts, "_should_fire", bad_rule)
    assert _ingest(client, fid, token, 500)["alerts_fired"] == 0

    # …and so is a failure of the whole evaluation.
    def bad_eval(*a, **k):
        raise RuntimeError("bug")

    monkeypatch.setattr(fleet_alerts, "evaluate_fleet_alerts", bad_eval)
    body = _ingest(client, fid, token, 900)
    assert body["alerts_fired"] == 0 and body["updated_items"] == 2
    assert outbox == []
    client.act_as(A)
    items = client.get(f"/api/fleet/fleets/{fid}").json()["items"]
    assert {it["current_use"] for it in items} == {900}  # the usage still landed


def test_within_rule_fires_edge_triggered_and_flags_truncation(client, outbox):
    fid, token = _setup(client)
    url = _alerts_url(fid)
    probe = client.post(url, json={"kind": "within", "x": 1000, "y_periods": 3}).json()
    low = probe["last_value"]
    _ingest(client, fid, token, 900)
    high = client.get(url).json()["alerts"][0]["current_value"]
    _ingest(client, fid, token, 100)
    client.delete(f"{url}/{probe['id']}")
    assert high > low

    x = round((low + high) / 2, 3)
    rule = client.post(url, json={"kind": "within", "x": x, "y_periods": 3}).json()
    assert rule["armed"] is True
    assert _ingest(client, fid, token, 900)["alerts_fired"] == 1
    assert _ingest(client, fid, token, 900)["alerts_fired"] == 0
    msg = outbox[-1]
    assert "failures now expected within 3 months" in msg["subject"]
    assert msg["subject"].startswith("Fleet alert: Trucks — ≥ ")
    assert f"{low:.1f} → {high:.1f}" in msg["text"]
    event = client.db.fleet_alert_events.find_one({"alert_id": rule["id"]})
    assert event["x"] == x and event["y_periods"] == 3

    # Shorten the horizon below Y: still evaluated (over what's there), flagged.
    client.act_as(A)
    fleet = client.get(f"/api/fleet/fleets/{fid}").json()
    client.put(f"/api/fleet/fleets/{fid}/items", json={
        "settings": {**fleet["settings"], "periods": 2}, "items": fleet["items"],
    })
    listed = client.get(url).json()["alerts"][0]
    assert listed["truncated"] is True and listed["current_value"] is not None


# ---- MCP -------------------------------------------------------------------------------

from backend.tests.test_mcp import _call, _ok, env  # noqa: E402,F401  (fixture reuse)


def _mcp_fleet(env):
    from backend.services import datasets as ds
    from backend.services import fleet as fs
    from backend.services import models as ms

    rng = np.random.default_rng(7)
    buf = io.StringIO()
    pd.DataFrame({"t": np.round(rng.weibull(3.0, 80) * 100, 2)}).to_csv(buf, index=False)
    dataset = ds.create_dataset(env.db, "wear.csv", buf.getvalue().encode(), "user-a")
    model = ms.save_model(env.db, "wear", dataset, "weibull", {"x": "t"}, [], None, owner_id="user-a")
    fleet = fs.create_fleet(env.db, "Pumps", model.id, "user-a")
    fs.replace_items(env.db, fleet.id, {"periods": 6, "default_rate": 5, "method": "single"},
                     [{"name": "P1", "current_use": 40}], "user-a")
    return fleet.id


def test_mcp_fleet_alert_tools(env):
    fid = _mcp_fleet(env)
    a, b = env.token["user-a"], env.token["user-b"]

    created = _ok(_call(a, "create_fleet_alert", {"fleet_id": fid, "kind": "within", "x": 0.5, "y_periods": 3}))
    assert created["alert"]["kind"] == "within" and created["url"].endswith(f"/fleet/forecasts/{fid}#alerts")
    bad = _call(a, "create_fleet_alert", {"fleet_id": fid, "kind": "within", "x": 0.5, "y_periods": 7})
    assert bad.is_error and "horizon" in bad.content[0].text

    listed = _ok(_call(a, "list_fleet_alerts", {"fleet_id": fid}))
    assert len(listed["alerts"]) == 1 and listed["alerts"][0]["current_value"] is not None
    assert listed["expected_failures"] > 0

    # Another user: the fleet doesn't exist for them.
    assert _call(b, "list_fleet_alerts", {"fleet_id": fid}).is_error
    assert _call(b, "create_fleet_alert", {"fleet_id": fid, "kind": "above", "threshold": 1}).is_error
    assert env.db.fleet_alerts.count_documents({}) == 1
