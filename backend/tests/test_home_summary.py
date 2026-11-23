"""Home's one request (GET /api/home/summary): each part is exactly what its own
endpoint answers on the same data; a part that fails is named in ``errors`` and the
rest still come back; Maintenance's parts only for those who have it."""

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from backend.maintenance.service import PROJECTORS
from backend.maintenance.store import GraphStore

ORG = "user-home"

# Each part and the endpoint Home used to read it from.
ENDPOINTS = {
    "models": "/api/models",
    "alt_models": "/api/alt/models",
    "recurrent_models": "/api/recurrent/models",
    "degradation_models": "/api/degradation/models",
    "joint_models": "/api/joint/models",
    "datasets": "/api/datasets",
    "rbds": "/api/rbds",
    "fleets": "/api/fleet/fleets",
    "strategy_analyses": "/api/strategy/analyses",
    "tracked_fleets": "/api/fleet/tracked",
    "changes": "/api/changes",
    "maintenance_overview": "/api/maintenance/overview?tree=false",
}


@pytest.fixture()
def client(monkeypatch):
    import mongomock

    from backend import config
    from backend import db as db_mod
    from backend.auth import get_current_user
    from backend.main import app
    from backend.routers import maintenance as router

    monkeypatch.setattr(db_mod, "_db", mongomock.MongoClient()["home_summary"])
    monkeypatch.setattr(db_mod, "_simulated", True)
    monkeypatch.setattr(router, "_store", GraphStore(":memory:", PROJECTORS))
    monkeypatch.setattr(config, "MAINTENANCE_ENABLED", True)
    monkeypatch.setattr(config, "MAINTENANCE_EMAILS", {"a@x.com"})
    user = {"uid": ORG, "email": "a@x.com", "name": "A", "email_verified": True}
    app.dependency_overrides[get_current_user] = lambda: user
    tc = TestClient(app)
    tc.user = user
    yield tc
    app.dependency_overrides.pop(get_current_user, None)


def _some_work(client):
    """A dataset of the user's own and some maintenance work, late and due."""
    csv = "x,c\n10,0\n20,0\n30,1\n45,0\n60,0\n"
    r = client.post("/api/datasets", files={"file": ("pumps.csv", csv, "text/csv")}, data={"name": "Pumps"})
    assert r.status_code == 200, r.text
    gate = client.post("/api/maintenance/positions", json={"name": "Gate"}).json()
    today = date.fromisoformat(client.get("/api/maintenance/tree").json()["today"])
    r = client.post("/api/maintenance/work-orders", json={
        "position_id": gate["id"], "title": "Fix the latch", "due": (today - timedelta(days=3)).isoformat()})
    assert r.status_code == 200, r.text


def _same_clock(payload):
    """What changed is "the last 30 days to now": the two reads differ only by when now was."""
    return {k: v for k, v in payload.items() if k not in ("since", "until")}


def test_each_part_is_what_its_own_endpoint_answers(client):
    _some_work(client)
    # Reading some lists notes things for "What changed" (a forecast's figures): read
    # once so both sides see the same data.
    assert client.get("/api/home/summary").status_code == 200
    singles = {name: client.get(url) for name, url in ENDPOINTS.items()}
    singles["rcm_rollup"] = client.get("/api/maintenance/rcm?rollup_only=true")
    r = client.get("/api/home/summary")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["errors"] == {}
    assert out["maintenance"] is True
    # What each part took, for the network panel.
    assert "changes;dur=" in r.headers["server-timing"] and "rcm;dur=" in r.headers["server-timing"]
    for name, res in singles.items():
        assert res.status_code == 200, (name, res.text)
    for name in ENDPOINTS:
        assert _same_clock(out["sections"][name]) == _same_clock(singles[name].json()), name
    assert out["sections"]["rcm_rollup"] == singles["rcm_rollup"].json()["rollup"]
    # Real data, not empty lists compared with empty lists.
    assert any(d["name"] == "Pumps" for d in out["sections"]["datasets"]["datasets"])
    assert out["sections"]["maintenance_overview"]["late"]["work_orders_late"] == 1


def test_a_part_that_fails_is_named_and_the_rest_still_come_back(client, monkeypatch):
    from backend.routers import workspace_changes

    def broken(*a, **k):
        raise RuntimeError("down")

    monkeypatch.setattr(workspace_changes, "changes_payload", broken)
    r = client.get("/api/home/summary")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["errors"] == {"changes": "Couldn't load what changed."}
    assert "changes" not in out["sections"]
    assert {"models", "datasets", "maintenance_overview", "rcm_rollup"} <= set(out["sections"])


def test_without_maintenance_its_parts_are_not_read(client, monkeypatch):
    from backend import config

    monkeypatch.setattr(config, "MAINTENANCE_EMAILS", set())
    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    out = client.get("/api/home/summary").json()
    assert out["maintenance"] is False
    assert "maintenance_overview" not in out["sections"] and "rcm_rollup" not in out["sections"]
    assert out["errors"] == {}


def test_a_team_workspace_reads_the_teams_lists(client):
    # Not a member: refused, as every list endpoint refuses it.
    r = client.get("/api/home/summary", headers={"X-Workspace-Id": "team-nobody"})
    assert r.status_code == 403


def test_what_changed_reads_the_rcm_once_and_says_the_same(client, monkeypatch):
    """The summary reads the RCM once for its counts and What changed: the evidence rows
    are the ones /api/changes finds reading the RCM itself."""
    from datetime import datetime, timezone

    from backend import db as db_mod
    from backend.maintenance.service import Maintenance
    from backend.routers import maintenance as maintenance_router
    from backend.services import workspace_changes as wc

    db = db_mod._db
    old = datetime.now(timezone.utc) - timedelta(days=90)
    weibull = {"kind": "distribution", "distribution_id": "weibull", "distribution": "Weibull",
               "params": [{"name": "alpha", "value": 1000.0}, {"name": "beta", "value": 2.0}], "n": 20,
               "unit": "Hours"}
    wear_out = {**weibull, "randomness": {"verdict": "wear_out", "beta": 3.1, "beta_ci": [2.2, 4.4]}}
    random_ = {**weibull, "randomness": {"verdict": "random", "beta": 1.1, "beta_ci": [0.7, 1.6]}}
    db.models.insert_one({"_id": "seal-model", "id": "seal-model", "name": "Seal", "owner_id": ORG,
                          "created_at": old, "updated_at": old, "results": wear_out})
    m = Maintenance(maintenance_router._store, ORG, ORG)
    pid = m.create_position("Pump")["id"]
    ff = m.add_functional_failure(m.add_function(pid, "Pump water")["id"], "No flow")
    mode = m.add_failure_mode(pid, "Seal leak", functional_failure_id=ff["id"])
    m.decide_failure_mode(mode["id"], "operational", {"outcome": "rtf", "rtf_basis": "random",
                                                       "evidence": {"type": "model", "id": "seal-model"}})
    wc.record_refit(db, "seal-model", ORG, random_, wear_out,
                    now=datetime.now(timezone.utc) - timedelta(days=4))

    calls = []
    real = Maintenance.rcm_all
    monkeypatch.setattr(Maintenance, "rcm_all", lambda self, *a, **k: calls.append(1) or real(self, *a, **k))
    out = client.get("/api/home/summary").json()
    assert out["errors"] == {}
    assert len(calls) == 1, "the RCM is read once"
    alone = client.get("/api/changes").json()
    assert [r["mode"] for r in out["sections"]["changes"]["rcm_evidence"]] == ["Seal leak"]
    assert _same_clock(out["sections"]["changes"]) == _same_clock(alone)
    assert out["sections"]["rcm_rollup"] == client.get("/api/maintenance/rcm?rollup_only=true").json()["rollup"]
