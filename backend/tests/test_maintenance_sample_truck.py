"""The sample truck: a copy-in template for the Explorer. "Add the sample truck"
copies the sample delivery truck, with its RCM, into the caller's own tree
through the ordinary service methods (events), once unless asked again; over
the app's route, MCP (maintenance_positions add_sample_truck) and the CLI."""

import mongomock
import pytest

from backend.maintenance import rcm_graph, templates
from backend.maintenance.service import PROJECTORS, Maintenance
from backend.maintenance.store import GraphStore
from backend.tests.test_maintenance_mcp import _do, _get, _ok, _session
from backend.tests.test_maintenance_mcp import env  # noqa: F401
from backend.tests.test_maintenance_rcm_api import api  # noqa: F401

ORG, OTHER = "user-a", "user-b"


@pytest.fixture()
def store():
    return GraphStore(":memory:", PROJECTORS)


@pytest.fixture()
def db():
    from backend.services import samples

    d = mongomock.MongoClient()["sample_truck"]
    samples.seed_samples(d)
    return d


def _modes(sheet: dict) -> list[dict]:
    return [mo for p in sheet["positions"] for fn in p["functions"] for f in fn["failures"] for mo in f["modes"]]


def _template_modes() -> list[dict]:
    return [mo for fn in templates.SAMPLE_TRUCK_FUNCTIONS for f in fn["failures"] for mo in f["modes"]]


def test_the_copy_has_the_whole_rcm_with_new_ids(store):
    m = Maintenance(store, ORG, "tester")
    out = templates.add_sample_truck(m)
    assert out["added"] and out["position"]["name"] == "Delivery truck (sample)"
    assert {k: out[k] for k in ("functions", "functional_failures", "failure_modes", "decisions", "tasks")} == {
        "functions": 2, "functional_failures": 2, "failure_modes": 5, "decisions": 5, "tasks": 1}
    assert "2 functions, 5 failure modes, each with its decision, and 1 scheduled task" in out["message"]
    pid = out["position"]["id"]
    assert [p["id"] for p in store.nodes(ORG, "Position")] == [pid]

    sheet = m.rcm_worksheet(pid, "this")
    [p] = sheet["positions"]
    assert [fn["text"] for fn in p["functions"]] == [fn["text"] for fn in templates.SAMPLE_TRUCK_FUNCTIONS]
    assert [f["text"] for fn in p["functions"] for f in fn["failures"]] == [
        "Insufficient braking force", "Wheel does not rotate freely"]
    assert p["unassigned"] == []
    got, want = _modes(sheet), _template_modes()
    assert [mo["text"] for mo in got] == [mo["text"] for mo in want]
    for g, w in zip(got, want):
        assert g["consequence"] == w["consequence"] and g["effects"] == w["effects"]
        d, wd = g["decision"], w["decision"]
        assert d["outcome"] == wd["outcome"] and d.get("rtf_basis") == wd.get("rtf_basis")
        assert d.get("evidence") == wd.get("evidence")
        assert (d.get("notes") or "") == wd.get("notes", "")
    bearing = next(mo for mo in got if mo["text"] == "Wheel-bearing fatigue")
    assert bearing["decision"]["interval"] == 580 and bearing["decision"]["interval_unit"] == "hours"
    [task] = m._tasks_on(pid)
    assert task["interval"] == 580 and task["unit"] == "hours" and task["outcome"] == "fixed_interval"
    assert task["name"] == "Replace wheel bearings preventively."

    # New ids everywhere: nothing carries the template's ids, and nothing writes the
    # fields the earlier RCM studies left on nodes.
    ids = {n["id"] for label in ("Position", "Function", "FunctionalFailure", "FailureMode", "Task")
           for n in store.nodes(ORG, label)}
    assert len(ids) == 1 + 2 + 2 + 5 + 1 and not any(i.startswith("sample-") for i in ids)
    assert all(not n.get("rcm_mode_id") and not n.get("study_id") for n in store.nodes(ORG, "FailureMode"))

    # Events only: the graph rebuilds the same from the log.
    before = store.snapshot()
    store.rebuild()
    assert store.snapshot() == before


def test_the_evidence_check_on_the_copy(store, db):
    from backend.services.samples import SAMPLE_OWNER

    m = Maintenance(store, ORG, "tester")
    pid = templates.add_sample_truck(m)["position"]["id"]
    graph = rcm_graph.resolve(db, m.rcm_worksheet(pid, "this"), [ORG, SAMPLE_OWNER])
    statuses = {mo["text"]: mo["decision"].get("status") for mo in _modes(graph)}
    assert statuses["Wheel-bearing failure — legacy run-to-failure plan"] == "contradicted"
    assert {"supported", "contradicted"} <= set(statuses.values())
    assert graph["rollup"] == {"modes": 5, "decided": 5, "supported": 3, "contradicted": 1,
                               "inconclusive": 0, "unevidenced": 0, "stale": 0}


def test_once_unless_asked_again_and_only_in_the_callers_workspace(store):
    m = Maintenance(store, ORG, "tester")
    first = templates.add_sample_truck(m)
    count = store.event_count(ORG)
    second = templates.add_sample_truck(m)
    assert second == {"added": False, "position": first["position"], "message": second["message"]}
    assert "already in your tree" in second["message"]
    assert store.event_count(ORG) == count  # nothing written

    again = templates.add_sample_truck(m, again=True)
    assert again["added"] and again["position"]["name"] == "Delivery truck (sample 2)"
    assert again["position"]["id"] != first["position"]["id"] and again["failure_modes"] == 5
    assert len(store.nodes(ORG, "FailureMode")) == 10

    # Another workspace: untouched, and its own first copy is the first.
    other = Maintenance(store, OTHER, "someone")
    assert store.nodes(OTHER, "Position") == [] and store.event_count(OTHER) == 0
    mine = templates.add_sample_truck(other)
    assert mine["added"] and mine["position"]["name"] == "Delivery truck (sample)"
    assert len(store.nodes(ORG, "Position")) == 2 and len(store.nodes(OTHER, "Position")) == 1

    # A retired copy doesn't count; a gap in the numbers is filled.
    m.retire_position(first["position"]["id"])
    third = templates.add_sample_truck(m)
    assert third["added"] is False and third["position"]["name"] == "Delivery truck (sample 2)"
    assert templates.add_sample_truck(m, again=True)["position"]["name"] == "Delivery truck (sample)"


def test_the_template_is_copied_fresh_each_time():
    assert templates.sample_truck_functions() == templates.SAMPLE_TRUCK_FUNCTIONS
    assert templates.sample_truck_functions() is not templates.SAMPLE_TRUCK_FUNCTIONS


def test_over_the_route(api, monkeypatch):  # noqa: F811
    from backend import config
    from backend.auth import get_current_user
    from backend.main import app

    M = "/api/maintenance"
    r = api.post(f"{M}/sample-truck")
    assert r.status_code == 200, r.text
    made = r.json()
    assert made["added"] and made["failure_modes"] == 5
    pid = made["position"]["id"]
    sheet = api.get(f"{M}/positions/{pid}/rcm?scope=this").json()
    assert sheet["rollup"]["modes"] == 5 and sheet["rollup"]["contradicted"] == 1
    again = api.post(f"{M}/sample-truck", json={})
    assert again.status_code == 200 and again.json()["added"] is False
    assert api.post(f"{M}/sample-truck", json={"again": True}).json()["position"]["name"] == "Delivery truck (sample 2)"
    assert [p["name"] for p in api.get(f"{M}/tree").json()["positions"]] == [
        "Delivery truck (sample)", "Delivery truck (sample 2)"]

    # Someone else's workspace doesn't see it.
    monkeypatch.setattr(config, "MAINTENANCE_EMAILS", {"r@example.org", "s@example.org"})
    app.dependency_overrides[get_current_user] = lambda: {
        "uid": "user-s", "email": "s@example.org", "name": "S", "email_verified": True}
    assert api.get(f"{M}/tree").json()["positions"] == []

    # Not allowed Maintenance: not there at all.
    monkeypatch.setattr(config, "MAINTENANCE_EMAILS", {"r@example.org"})
    assert api.post(f"{M}/sample-truck").status_code == 404


def test_over_mcp(env):  # noqa: F811
    from backend.services import samples

    samples.seed_samples(env["db"])

    async def go(client):
        made = _ok(await _do(client, "maintenance_positions", "add_sample_truck"))
        assert made["added"] and made["functions"] == 2 and made["failure_modes"] == 5 and made["tasks"] == 1
        sheet = _ok(await _get(client, "rcm", made["position"]["id"], scope="this"))
        assert sheet["rollup"]["decided"] == 5 and sheet["rollup"]["contradicted"] == 1
        twice = _ok(await _do(client, "maintenance_positions", "add_sample_truck"))
        assert twice["added"] is False and twice["position"] == made["position"]
        another = _ok(await _do(client, "maintenance_positions", "add_sample_truck", again=True))
        assert another["added"] and another["position"]["name"] == "Delivery truck (sample 2)"
        wrong = await _do(client, "maintenance_positions", "add_sample_truck", name="Truck")
        assert wrong.is_error and "doesn't take name" in wrong.content[0].text
        return True

    assert _session(env["token"], go)
