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
    # The whole workspace's, for the tree: only positions with any RCM, checked the same way.
    every = api.get(f"{M}/rcm").json()
    assert [p["id"] for p in every["positions"]] == [pump["id"]]
    assert every["positions"][0]["functions"][0]["failures"][0]["modes"][0]["decision"]["status"] == "contradicted"
    assert every["rollup"]["contradicted"] == 1
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


def test_move_rcm_over_the_routes(api):
    M = "/api/maintenance"
    a = api.post(f"{M}/positions", json={"name": "Pump A"}).json()
    b = api.post(f"{M}/positions", json={"name": "Pump B"}).json()
    fn = api.post(f"{M}/positions/{a['id']}/functions", json={"text": "Pump water"}).json()
    ff = api.post(f"{M}/functions/{fn['id']}/failures", json={"text": "No flow"}).json()
    mode = api.post(f"{M}/positions/{a['id']}/failure-modes",
                    json={"text": "Bearing seizes", "functional_failure_id": ff["id"]}).json()
    loose = api.post(f"{M}/positions/{a['id']}/failure-modes", json={"text": "Seal leaks"}).json()
    task = api.post(f"{M}/positions/{a['id']}/tasks", json={"name": "Grease", "interval": 3, "unit": "months"}).json()

    r = api.post(f"{M}/functions/{fn['id']}/move", json={"position_id": b["id"]})
    assert r.status_code == 200, r.text
    assert r.json()["failure_modes_moved"] == 1 and r.json()["position_id"] == b["id"]
    sheet = api.get(f"{M}/positions/{b['id']}/rcm?scope=this").json()["positions"][0]
    assert sheet["functions"][0]["failures"][0]["modes"][0]["id"] == mode["id"]

    ff_b = sheet["functions"][0]["failures"][0]["id"]
    r = api.post(f"{M}/failure-modes/{loose['id']}/move", json={"position_id": b["id"], "functional_failure_id": ff_b})
    assert r.status_code == 200 and r.json()["position_id"] == b["id"], r.text
    r = api.post(f"{M}/tasks/{task['id']}/move", json={"position_id": b["id"]})
    assert r.status_code == 200 and r.json()["id"] == task["id"], r.text

    # Refusals are a 422 with what to do; a missing thing is a 404.
    r = api.post(f"{M}/tasks/{task['id']}/move", json={"position_id": b["id"]})
    assert r.status_code == 422 and "already on Pump B" in r.json()["detail"]
    r = api.post(f"{M}/failure-modes/{mode['id']}/move", json={"position_id": a["id"], "functional_failure_id": ff_b})
    assert r.status_code == 422 and "on Pump B, not Pump A" in r.json()["detail"]
    assert api.post(f"{M}/functions/{fn['id']}/move", json={}).status_code == 422
    assert api.post(f"{M}/functions/nope/move", json={"position_id": a["id"]}).status_code == 404


def test_move_rcm_over_mcp(env):  # noqa: F811
    async def go(client):
        a = _ok(await _do(client, "maintenance_positions", "create", name="Pump A"))
        b = _ok(await _do(client, "maintenance_positions", "create", name="Pump B"))
        fn = _ok(await _do(client, "maintenance_failure_modes", "add_function", position_id=a["id"], text="Pump"))
        ff = _ok(await _do(client, "maintenance_failure_modes", "add_functional_failure", function_id=fn["id"],
                           text="No flow"))
        mode = _ok(await _do(client, "maintenance_failure_modes", "add", position_id=a["id"], text="Seal",
                             functional_failure_id=ff["id"]))
        _ok(await _do(client, "maintenance_failure_modes", "decide", failure_mode_id=mode["id"],
                      decision={"outcome": "fixed_interval", "interval": 6, "interval_unit": "months",
                                "task": "Replace seal"}))
        moved = _ok(await _do(client, "maintenance_failure_modes", "move_function", function_id=fn["id"],
                              position_id=b["id"]))
        assert moved["failure_modes_moved"] == 1 and moved["tasks_moved"] == 1
        back = _ok(await _do(client, "maintenance_failure_modes", "move", failure_mode_id=mode["id"],
                             position_id=a["id"]))
        assert back["position_id"] == a["id"] and back["decision"]["task"] == "Replace seal"
        spare = _ok(await _do(client, "maintenance_tasks", "create", position_id=a["id"], name="Grease",
                              interval=3))
        task = _ok(await _do(client, "maintenance_tasks", "move", task_id=spare["id"], position_id=b["id"]))
        assert task["id"] == spare["id"]
        sheet = _ok(await _get(client, "rcm", a["id"], scope="this"))
        assert sheet["positions"][0]["unassigned"][0]["id"] == mode["id"]
        refused = await _do(client, "maintenance_tasks", "move", task_id=spare["id"], position_id=b["id"])
        assert refused.is_error and "already on Pump B" in refused.content[0].text
        missing = await _do(client, "maintenance_failure_modes", "move", failure_mode_id=mode["id"])
        assert missing.is_error and "action 'move' needs position_id" in missing.content[0].text
        return True

    assert _session(env["token"], go)


def test_the_working_behind_a_standard_over_mcp(env):  # noqa: F811
    """standard_basis on add_function / update_function ('' clears it), read in full with kind function."""
    async def go(client):
        pool = _ok(await _do(client, "maintenance_positions", "create", name="Tank"))
        fn = _ok(await _do(client, "maintenance_failure_modes", "add_function", position_id=pool["id"],
                           text="Hold water", standard="10 kL", standard_basis="## Sizing\n\n2 days x 5 kL"))
        assert fn["standard_basis"] == "## Sizing\n\n2 days x 5 kL" and fn["has_basis"]
        got = _ok(await _get(client, "function", fn["id"]))
        assert got["standard_basis"] == fn["standard_basis"] and got["position"]["id"] == pool["id"]
        cleared = _ok(await _do(client, "maintenance_failure_modes", "update_function", function_id=fn["id"],
                                standard_basis=""))
        assert cleared["standard_basis"] == "" and not cleared["has_basis"]
        too_long = await _do(client, "maintenance_failure_modes", "update_function", function_id=fn["id"],
                             standard_basis="x" * 20_001)
        assert too_long.is_error and "attach it as a PDF" in too_long.content[0].text
        return True

    assert _session(env["token"], go)


def test_link_a_cause_over_the_routes(api):
    M = "/api/maintenance"
    pool = api.post(f"{M}/positions", json={"name": "Swimming Pool"}).json()
    cell = api.post(f"{M}/positions", json={"name": "Chlorinator cell", "parent_id": pool["id"]}).json()
    fn = api.post(f"{M}/positions/{pool['id']}/functions", json={"text": "Sanitise the water"}).json()
    top = api.post(f"{M}/functions/{fn['id']}/failures", json={"text": "Free chlorine below 1 ppm"}).json()
    fn2 = api.post(f"{M}/positions/{cell['id']}/functions", json={"text": "Produce chlorine"}).json()
    low = api.post(f"{M}/functions/{fn2['id']}/failures", json={"text": "No chlorine produced"}).json()
    mode = api.post(f"{M}/positions/{cell['id']}/failure-modes",
                    json={"text": "Plates scaled", "functional_failure_id": low["id"]}).json()
    api.put(f"{M}/failure-modes/{mode['id']}/decision",
            json={"consequence": "operational", "decision": {"outcome": "rtf", "rtf_basis": "random"}})

    r = api.post(f"{M}/functional-failures/{top['id']}/causes", json={"cause_id": low["id"]})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["covered"] is True and out["explained_below"] is True
    assert [(c["id"], c["position"]["name"], c["inside"]) for c in out["causes"]] == [
        (low["id"], "Chlorinator cell", True)]
    rows = {p["name"]: p for p in api.get(f"{M}/tree").json()["positions"]}
    assert "not_analysed" not in rows["Swimming Pool"]  # the tree's mark follows the links
    sheet = api.get(f"{M}/positions/{pool['id']}/rcm").json()
    assert sheet["positions"][0]["analysed"] is True
    assert sheet["positions"][1]["functions"][0]["failures"][0]["effects"][0]["id"] == top["id"]
    # The other way round is refused, saying what to do.
    r = api.post(f"{M}/functional-failures/{low['id']}/causes", json={"cause_id": top["id"]})
    assert r.status_code == 422 and "inside Chlorinator cell" in r.json()["detail"]
    assert api.post(f"{M}/functional-failures/{top['id']}/causes", json={}).status_code == 422
    assert api.post(f"{M}/functional-failures/nope/causes", json={"cause_id": low["id"]}).status_code == 404

    r = api.delete(f"{M}/functional-failures/{top['id']}/causes/{low['id']}")
    assert r.status_code == 200 and r.json()["causes"] == [] and r.json()["covered"] is False
    # Retiring a position says how many links went.
    api.post(f"{M}/functional-failures/{top['id']}/causes", json={"cause_id": low["id"]})
    api.delete(f"{M}/failure-modes/{mode['id']}")
    r = api.post(f"{M}/positions/{cell['id']}/retire", json={})
    assert r.status_code == 200 and r.json() == {"retired": cell["id"], "links_removed": 1}


def test_link_a_cause_over_mcp(env):  # noqa: F811
    async def go(client):
        pool = _ok(await _do(client, "maintenance_positions", "create", name="Swimming Pool"))
        salt = _ok(await _do(client, "maintenance_positions", "create", name="Salt chlorinator",
                             parent_id=pool["id"]))
        fn = _ok(await _do(client, "maintenance_failure_modes", "add_function", position_id=pool["id"],
                           text="Sanitise the water"))
        top = _ok(await _do(client, "maintenance_failure_modes", "add_functional_failure", function_id=fn["id"],
                            text="Free chlorine below 1 ppm"))
        fn2 = _ok(await _do(client, "maintenance_failure_modes", "add_function", position_id=salt["id"],
                            text="Produce up to 25 g/h"))
        low = _ok(await _do(client, "maintenance_failure_modes", "add_functional_failure", function_id=fn2["id"],
                            text="No output"))
        linked = _ok(await _do(client, "maintenance_failure_modes", "link_cause", functional_failure_id=top["id"],
                               cause_id=low["id"]))
        assert [c["id"] for c in linked["causes"]] == [low["id"]] and linked["covered"] is False
        sheet = _ok(await _get(client, "rcm", pool["id"]))
        failure = sheet["positions"][0]["functions"][0]["failures"][0]
        assert failure["explained_below"] is True and failure["causes"][0]["position"]["name"] == "Salt chlorinator"
        assert sheet["positions"][1]["functions"][0]["failures"][0]["effects"][0]["id"] == top["id"]
        refused = await _do(client, "maintenance_failure_modes", "link_cause", functional_failure_id=low["id"],
                            cause_id=top["id"])
        assert refused.is_error and "inside Salt chlorinator" in refused.content[0].text
        missing = await _do(client, "maintenance_failure_modes", "link_cause", functional_failure_id=top["id"])
        assert missing.is_error and "needs cause_id" in missing.content[0].text
        gone = _ok(await _do(client, "maintenance_failure_modes", "unlink_cause", functional_failure_id=top["id"],
                             cause_id=low["id"]))
        assert gone["causes"] == []
        return True

    assert _session(env["token"], go)
