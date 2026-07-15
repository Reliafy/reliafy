"""Fleet failure forecasting: math, CRUD, caps, isolation, sample."""

import json
import math

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
def session(monkeypatch):
    from backend import db

    test_db = mongomock.MongoClient()["reliafy_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    yield test_db


@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", True)
    test_db = mongomock.MongoClient()["reliafy_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    tc = TestClient(app)

    def act_as(uid):
        app.dependency_overrides[get_current_user] = lambda: USERS[uid]
        email = USERS[uid]["email"]
        test_db.users.update_one(
            {"_id": uid},
            {"$set": {"email": email, "email_lc": email, "name": USERS[uid]["name"], "plan": "pro"}},
            upsert=True,
        )

    tc.act_as = act_as
    tc.db = test_db
    try:
        yield tc
    finally:
        app.dependency_overrides.clear()


def _csv(kind="wear") -> bytes:
    rng = np.random.default_rng(7)
    x = np.round(rng.weibull(3.0, 80) * 100, 2) if kind == "wear" else np.round(rng.exponential(100, 80), 2)
    buf = io.StringIO()
    pd.DataFrame({"t": x}).to_csv(buf, index=False)
    return buf.getvalue().encode()


def _make_model(session, owner, distribution="weibull", kind="wear"):
    from backend.services import datasets as ds
    from backend.services import models as ms

    dataset = ds.create_dataset(session, f"{kind}.csv", _csv(kind), owner)
    return ms.save_model(session, f"{kind} model", dataset, distribution, {"x": "t"}, [], None, owner_id=owner)


def _fleet_with(session, owner, model, items, method="single", periods=12, rate=50.0):
    from backend.services import fleet as fs

    fleet = fs.create_fleet(session, "F", model.id, owner)
    fleet = fs.replace_items(
        session, fleet.id,
        {"periods": periods, "period_label": "months", "default_rate": rate, "method": method},
        items, owner,
    )
    return fleet


# ---- Math ---------------------------------------------------------------------

def test_single_method_exponential_is_memoryless(session):
    """Exponential + 'single': p = 1 - exp(-λu) regardless of item age."""
    from backend.services import fleet as fs

    model = _make_model(session, A, distribution="exponential", kind="random")
    lam = next(p["value"] for p in model.results["params"] if "rate" in p["name"] or p["name"] == "failure_rate")
    items = [
        {"name": "new", "current_use": 0},
        {"name": "old", "current_use": 500},
    ]
    fleet = _fleet_with(session, A, model, items, method="single", periods=10, rate=10.0)
    f = fs.compute(session, fleet, A)
    assert f["status"] == "ok"
    expected_p = 1 - math.exp(-lam * 100)  # u = 10 periods × 10/period
    for row in f["per_item"]:
        assert row["prob_any"] == pytest.approx(expected_p, rel=1e-6)
    assert f["expected"] == pytest.approx(2 * expected_p, rel=1e-6)
    # Per-period sums back to the total.
    assert sum(f["per_period"]) == pytest.approx(f["expected"], rel=1e-6)


def test_renewals_close_to_single_on_short_windows(session):
    """When failures are rare in the window, both methods agree."""
    from backend.services import fleet as fs

    model = _make_model(session, A)  # weibull, alpha ~90
    items = [{"name": f"i{k}", "current_use": 10.0 * k} for k in range(5)]
    single = fs.compute(session, _fleet_with(session, A, model, items, "single", periods=2, rate=2.0), A)
    renew = fs.compute(session, _fleet_with(session, A, model, items, "renewals", periods=2, rate=2.0), A)
    assert renew["expected"] == pytest.approx(single["expected"], rel=0.15, abs=0.02)


def test_renewals_exceed_single_on_long_windows(session):
    """Replacement means an item can fail more than once over a long horizon."""
    from backend.services import fleet as fs

    model = _make_model(session, A)
    items = [{"name": "i", "current_use": 50.0}]
    single = fs.compute(session, _fleet_with(session, A, model, items, "single", periods=12, rate=50.0), A)
    renew = fs.compute(session, _fleet_with(session, A, model, items, "renewals", periods=12, rate=50.0), A)
    # 600 use vs alpha≈90: many renewals expected; single caps at 1.
    assert single["expected"] <= 1.0
    assert renew["expected"] > 2.0
    assert renew["interval"][0] <= renew["expected"] <= renew["interval"][1]
    # Deterministic (seeded).
    renew2 = fs.compute(session, _fleet_with(session, A, model, items, "renewals", periods=12, rate=50.0), A)
    assert renew2["expected"] == renew["expected"]
    assert sum(renew["per_period"]) == pytest.approx(renew["expected"], rel=1e-6)


def test_stale_when_model_deleted(session):
    from backend.services import fleet as fs
    from backend.services import models as ms

    model = _make_model(session, A)
    fleet = _fleet_with(session, A, model, [{"name": "i", "current_use": 0}])
    ms.delete_model(session, model.id, A)
    f = fs.compute(session, fleet, A)
    assert f["status"] == "stale"


def test_regression_model_rejected(session):
    from backend.services import fleet as fs

    # Fake a regression model result on a saved doc.
    model = _make_model(session, A)
    session.models.update_one({"_id": model.id}, {"$set": {"results.kind": "regression"}})
    with pytest.raises(fs.FleetValidationError):
        fs.create_fleet(session, "F", model.id, A)


# ---- API: caps, isolation, conflict ------------------------------------------------

def test_api_flow_caps_isolation_conflict(client, monkeypatch):
    from backend import config

    monkeypatch.setattr(config, "FREE_MAX_FLEETS", 1)
    client.act_as(A)
    # A pro fixture user: make free to test the cap.
    client.db.users.update_one({"_id": A}, {"$set": {"plan": "free"}})

    r = client.post("/api/models", data={"name": "M", "distribution": "weibull", "x": "t"},
                    files={"file": ("d.csv", _csv(), "text/csv")})
    mid = r.json()["id"]
    r = client.post("/api/fleet/fleets", json={"name": "F1", "model_id": mid})
    assert r.status_code == 200, r.json()
    fid = r.json()["id"]
    # Cap bites on the second fleet.
    r = client.post("/api/fleet/fleets", json={"name": "F2", "model_id": mid})
    assert r.status_code == 402 and r.json()["code"] == "cap"

    # Items round-trip and forecast computes.
    r = client.put(f"/api/fleet/fleets/{fid}/items", json={
        "settings": {"periods": 6, "period_label": "months", "default_rate": 30, "method": "single"},
        "items": [{"name": "Truck 1", "current_use": 100},
                  {"name": "Truck 2", "current_use": 40, "rate": 10}],
    })
    assert r.status_code == 200
    body = r.json()
    assert body["forecast"]["status"] == "ok"
    assert body["forecast"]["expected"] > 0
    assert len(body["forecast"]["per_period"]) == 6
    loaded_at = body["updated_at"]

    # Optimistic lock: stale stamp conflicts.
    ok = client.put(f"/api/fleet/fleets/{fid}/items", json={
        "settings": body["settings"], "items": body["items"], "expected_updated_at": loaded_at,
    })
    assert ok.status_code == 200
    stale = client.put(f"/api/fleet/fleets/{fid}/items", json={
        "settings": body["settings"], "items": body["items"], "expected_updated_at": loaded_at,
    })
    assert stale.status_code == 409 and stale.json()["code"] == "conflict"

    # Validation errors are 422.
    r = client.put(f"/api/fleet/fleets/{fid}/items", json={
        "settings": {"periods": 0}, "items": [],
    })
    assert r.status_code == 422

    # Isolation: B sees nothing.
    client.act_as(B)
    assert client.get(f"/api/fleet/fleets/{fid}").status_code == 404
    assert all(f["id"] != fid for f in client.get("/api/fleet/fleets").json()["fleets"])


def test_share_fleet_grants_model_read(client):
    client.act_as(B)
    client.act_as(A)
    r = client.post("/api/models", data={"name": "M", "distribution": "weibull", "x": "t"},
                    files={"file": ("d.csv", _csv(), "text/csv")})
    mid = r.json()["id"]
    fid = client.post("/api/fleet/fleets", json={"name": "F", "model_id": mid}).json()["id"]
    client.put(f"/api/fleet/fleets/{fid}/items", json={
        "settings": {"periods": 12, "default_rate": 20, "method": "single"},
        "items": [{"name": "T1", "current_use": 10}],
    })
    assert client.post("/api/shares", json={"collection": "fleets", "artifact_id": fid, "email": "b@x.com"}).status_code == 200

    client.act_as(B)
    got = client.get(f"/api/fleet/fleets/{fid}")
    assert got.status_code == 200
    assert got.json()["read_only"] is True
    assert got.json()["forecast"]["status"] == "ok"
    # Transitive: the linked model opens for the recipient.
    assert client.get(f"/api/models/{mid}").status_code == 200
    # Read-only: edits blocked.
    assert client.put(f"/api/fleet/fleets/{fid}/items", json={"settings": {}, "items": []}).status_code == 403


def test_sample_fleet_seeds_and_computes(session, monkeypatch):
    from backend import config
    from backend.services import fleet as fs
    from backend.services import samples

    monkeypatch.setattr(config, "SEED_SAMPLES", True)
    samples.seed_samples(session)
    fleet = fs.get_fleet(session, "sample-fleet-trucks", A)
    assert fleet is not None and len(fleet.items) == 8
    f = fs.compute(session, fleet, A)
    assert f["status"] == "ok" and f["expected"] > 0
    # Idempotent.
    samples.seed_samples(session)
    assert session.fleets.count_documents({"_id": "sample-fleet-trucks"}) == 1


# ---- Tracked fleets (degradation tracking groups) ----------------------------------

def test_tracked_fleets_many_per_model(client):
    client.act_as(A)
    # Fit a degradation model.
    rows = []
    rng = np.random.default_rng(9)
    for i in range(6):
        slope = 0.004 + rng.normal(0, 0.0005)
        for t in (200, 800, 1400, 2000):
            rows.append({"i": f"u{i}", "x": t, "y": round(slope * t + rng.normal(0, 0.05), 3)})
    buf = io.StringIO(); pd.DataFrame(rows).to_csv(buf, index=False)
    dm = client.post("/api/degradation/models", data={
        "name": "D", "i": "i", "x": "x", "y": "y", "threshold": "8",
    }, files={"file": ("d.csv", buf.getvalue().encode(), "text/csv")}).json()

    # Two fleets on ONE model.
    f1 = client.post("/api/fleet/tracked", json={"name": "Sydney", "model_id": dm["id"]}).json()
    f2 = client.post("/api/fleet/tracked", json={"name": "Brisbane", "model_id": dm["id"]}).json()
    assert f1["id"] != f2["id"] and f1["model_id"] == f2["model_id"]

    # Items land in their fleet and stay isolated between fleets.
    client.post(f"/api/degradation/models/{dm['id']}/items",
                json={"name": "SYD-1", "fleet_id": f1["id"],
                      "measurements": [{"t": 100, "y": 1.0}, {"t": 500, "y": 2.5}]})
    client.post(f"/api/degradation/models/{dm['id']}/items",
                json={"name": "BNE-1", "fleet_id": f2["id"],
                      "measurements": [{"t": 200, "y": 1.2}]})
    d1 = client.get(f"/api/fleet/tracked/{f1['id']}").json()
    d2 = client.get(f"/api/fleet/tracked/{f2['id']}").json()
    assert [it["name"] for it in d1["items"]] == ["SYD-1"]
    assert [it["name"] for it in d2["items"]] == ["BNE-1"]
    assert d1["tracking"]["healthy"] + d1["tracking"]["plan"] + d1["tracking"]["replace"] + d1["tracking"]["monitoring"] == 1
    assert d1["model"]["threshold"] == 8.0

    # Deleting a fleet removes only its items.
    assert client.delete(f"/api/fleet/tracked/{f1['id']}").status_code == 200
    assert client.db.tracked_items.count_documents({"fleet_id": f1["id"]}) == 0
    assert client.db.tracked_items.count_documents({"fleet_id": f2["id"]}) == 1


def test_item_prediction_at_confidence(client):
    client.act_as(A)
    rows = []
    rng = np.random.default_rng(11)
    for i in range(6):
        slope = 0.004 + rng.normal(0, 0.0004)
        for t in (200, 800, 1400, 2000):
            rows.append({"i": f"u{i}", "x": t, "y": round(slope * t + rng.normal(0, 0.04), 3)})
    buf = io.StringIO(); pd.DataFrame(rows).to_csv(buf, index=False)
    dm = client.post("/api/degradation/models", data={
        "name": "D", "i": "i", "x": "x", "y": "y", "threshold": "8", "unit": "h",
    }, files={"file": ("d.csv", buf.getvalue().encode(), "text/csv")}).json()
    fleet = client.post("/api/fleet/tracked", json={"name": "Fleet", "model_id": dm["id"]}).json()
    item = client.post(f"/api/degradation/models/{dm['id']}/items",
                       json={"name": "asset", "fleet_id": fleet["id"],
                             "measurements": [{"t": 200, "y": 0.9}, {"t": 900, "y": 3.6},
                                              {"t": 1600, "y": 6.4}]}).json()
    base = f"/api/degradation/models/{dm['id']}/items/{item['id']}/prediction"

    def width(conf):
        r = client.get(f"{base}?confidence={conf}")
        assert r.status_code == 200, r.text
        p = r.json()
        json.dumps(p, allow_nan=False)
        assert p["alpha_ci"] == pytest.approx(1 - conf)
        lo, hi = p["failure_time_interval"]
        # Point estimate is confidence-independent; it sits inside the interval.
        assert lo <= p["failure_time"] <= hi
        return hi - lo

    # A wider confidence gives a wider crossing interval; the point is stable.
    assert width(0.95) > width(0.80)

    # Bad inputs.
    assert client.get(f"{base}?confidence=1.5").status_code == 422
    assert client.get(
        f"/api/degradation/models/{dm['id']}/items/nope/prediction"
    ).status_code == 404


def test_orphan_items_adopted_into_fleet(client):
    client.act_as(A)
    rows = []
    rng = np.random.default_rng(4)
    for i in range(6):
        slope = 0.004 + rng.normal(0, 0.0005)
        for t in (200, 800, 1400, 2000):
            rows.append({"i": f"u{i}", "x": t, "y": round(slope * t + rng.normal(0, 0.05), 3)})
    buf = io.StringIO(); pd.DataFrame(rows).to_csv(buf, index=False)
    dm = client.post("/api/degradation/models", data={
        "name": "D", "i": "i", "x": "x", "y": "y", "threshold": "8",
    }, files={"file": ("d.csv", buf.getvalue().encode(), "text/csv")}).json()
    # Legacy item: no fleet_id.
    client.post(f"/api/degradation/models/{dm['id']}/items",
                json={"name": "legacy", "measurements": [{"t": 100, "y": 1.0}]})
    fleets = client.get("/api/fleet/tracked").json()["fleets"]
    mine = [f for f in fleets if not f["is_sample"]]
    assert len(mine) == 1 and mine[0]["n_items"] == 1
    detail = client.get(f"/api/fleet/tracked/{mine[0]['id']}").json()
    assert [it["name"] for it in detail["items"]] == ["legacy"]
