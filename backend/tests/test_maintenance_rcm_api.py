"""A position's RCM over the app's routes and over MCP: functions, functional
failures, decisions with the evidence check, and the evidence-link check on
write (the same as a study's)."""

import mongomock
import pytest

from backend.maintenance.service import PROJECTORS
from backend.maintenance.store import GraphStore
from backend.tests.test_maintenance_mcp import _do, _get, _ok, _session
from backend.tests.test_maintenance_mcp import env  # noqa: F401

UID = "user-r"


@pytest.fixture()
def api(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app
    from backend.routers import maintenance as router
    from backend.services import samples

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    monkeypatch.setattr(config, "MAINTENANCE_ENABLED", True)
    monkeypatch.setattr(config, "MAINTENANCE_EMAILS", {"r@example.org"})
    test_db = mongomock.MongoClient()["maint_rcm_api"]
    samples.seed_samples(test_db)
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    monkeypatch.setattr(router, "_store", GraphStore(":memory:", PROJECTORS))
    user = {"uid": UID, "email": "r@example.org", "name": "R", "email_verified": True}
    test_db.users.insert_one({"_id": UID, "email": "r@example.org", "name": "R", "email_verified": True})
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_build_a_positions_rcm_over_the_routes(api):
    M = "/api/maintenance"
    plant = api.post(f"{M}/positions", json={"name": "Plant"}).json()
    pump = api.post(f"{M}/positions", json={"name": "Pump", "parent_id": plant["id"]}).json()
    fn = api.post(f"{M}/positions/{pump['id']}/functions", json={"text": "Pump water", "standard": "50 L/s"}).json()
    ff = api.post(f"{M}/functions/{fn['id']}/failures", json={"text": "No flow"}).json()
    mode = api.post(f"{M}/positions/{pump['id']}/failure-modes",
                    json={"text": "Bearing seizes", "functional_failure_id": ff["id"]}).json()
    r = api.put(f"{M}/failure-modes/{mode['id']}/decision", json={
        "consequence": "operational",
        "decision": {"outcome": "rtf", "rtf_basis": "random",
                     "evidence": {"type": "model", "id": "sample-model-bearings-weibull"}}})
    assert r.status_code == 200, r.text
    assert r.json()["decision"]["status"] == "contradicted"  # the sample bearing model shows wear-out
    assert api.patch(f"{M}/failure-modes/{mode['id']}", json={"effects": "Pump stops"}).status_code == 200

    sheet = api.get(f"{M}/positions/{plant['id']}/rcm").json()
    assert [p["name"] for p in sheet["positions"]] == ["Plant", "Pump"]
    pos = sheet["positions"][1]
    got = pos["functions"][0]["failures"][0]["modes"][0]
    assert got["effects"] == "Pump stops" and got["decision"]["artifact_link_path"].startswith("/models/m/")
    assert sheet["rollup"]["contradicted"] == 1 and pos["rollup"]["modes"] == 1
    assert api.get(f"{M}/positions/{plant['id']}/rcm?scope=this").json()["positions"][0]["functions"] == []
    assert api.get(f"{M}/positions/{plant['id']}/rcm?scope=nope").status_code == 422
    tree = {r["name"]: r for r in api.get(f"{M}/tree").json()["positions"]}
    assert tree["Plant"]["not_analysed"] and "not_analysed" not in tree["Pump"]

    # A refused decision is a 422 with the reason.
    bad = api.put(f"{M}/failure-modes/{mode['id']}/decision",
                  json={"decision": {"outcome": "rtf", "rtf_basis": "random",
                                     "evidence": {"type": "model", "id": "not-mine"}}})
    assert bad.status_code == 200  # an id that exists nowhere is a stale link, allowed (as in a study)
    assert api.put(f"{M}/failure-modes/{mode['id']}/decision", json={"decision": {"outcome": "rtf"}}).status_code == 422

    assert api.patch(f"{M}/functions/{fn['id']}", json={"text": "Pump water at 4 bar"}).json()["text"] == \
        "Pump water at 4 bar"
    assert api.patch(f"{M}/functional-failures/{ff['id']}", json={"text": "No flow at all"}).status_code == 200
    assert api.post(f"{M}/failure-modes/{mode['id']}/assign", json={"functional_failure_id": None}).status_code == 200
    assert api.delete(f"{M}/functional-failures/{ff['id']}").json()["failure_modes_unassigned"] == 0
    assert api.delete(f"{M}/functions/{fn['id']}").status_code == 200
    assert api.delete(f"{M}/failure-modes/{mode['id']}").json()["removed"] == mode["id"]
    assert api.get(f"{M}/positions/nope/rcm").status_code == 404


def test_someone_elses_model_cant_be_linked(api, monkeypatch):
    from backend import db

    db._db.models.insert_one({"_id": "theirs", "owner_id": "someone-else", "name": "Theirs"})
    M = "/api/maintenance"
    pump = api.post(f"{M}/positions", json={"name": "Pump"}).json()
    mode = api.post(f"{M}/positions/{pump['id']}/failure-modes", json={"text": "Seal"}).json()
    r = api.put(f"{M}/failure-modes/{mode['id']}/decision",
                json={"decision": {"outcome": "rtf", "rtf_basis": "random", "evidence": {"type": "model", "id": "theirs"}}})
    assert r.status_code == 422 and r.json()["code"] == "unreadable_reference"


def test_the_same_over_mcp(env):  # noqa: F811
    async def go(client):
        pump = _ok(await _do(client, "maintenance_positions", "create", name="Pump"))
        fn = _ok(await _do(client, "maintenance_failure_modes", "add_function", position_id=pump["id"],
                           text="Pump water", standard="50 L/s"))
        ff = _ok(await _do(client, "maintenance_failure_modes", "add_functional_failure", function_id=fn["id"],
                           text="No flow"))
        mode = _ok(await _do(client, "maintenance_failure_modes", "add", position_id=pump["id"], text="Seal",
                             functional_failure_id=ff["id"]))
        decided = _ok(await _do(client, "maintenance_failure_modes", "decide", failure_mode_id=mode["id"],
                                consequence="safety", decision={"outcome": "fixed_interval", "interval": 6,
                                                                "interval_unit": "months", "task": "Replace seal"}))
        assert decided["decision"]["status"] == "unevidenced" and decided["decision"]["task"] == "Replace seal"
        sheet = _ok(await _get(client, "rcm", pump["id"], scope="this"))
        assert sheet["positions"][0]["functions"][0]["failures"][0]["modes"][0]["id"] == mode["id"]
        assert sheet["rollup"]["unevidenced"] == 1
        for action, args in (("update_function", {"function_id": fn["id"], "text": "Pump"}),
                             ("update_functional_failure", {"functional_failure_id": ff["id"], "text": "Low"}),
                             ("assign", {"failure_mode_id": mode["id"]}),
                             ("remove_functional_failure", {"functional_failure_id": ff["id"]}),
                             ("remove_function", {"function_id": fn["id"]}),
                             ("retire", {"failure_mode_id": mode["id"]})):
            _ok(await _do(client, "maintenance_failure_modes", action, **args))
        bad = await _do(client, "maintenance_failure_modes", "decide", failure_mode_id=mode["id"],
                        decision={"outcome": "rtf"})
        assert bad.is_error
        return True

    assert _session(env["token"], go)
