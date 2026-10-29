"""Rearranging the RCM tree (the backend behind drag and drop): a functional
failure moved under another function (same position or another) with its modes
and tasks, siblings reordered, every move's result naming where the thing came
from, and a batch of moves (maintenance_apply over MCP, POST /rcm/apply in the
app) that is all or nothing and answers with the operations that undo it."""

import pytest

from backend.maintenance.service import PROJECTORS, Invalid, Maintenance
from backend.maintenance.store import GraphStore, new_id
from backend.tests.test_maintenance_apply import _apply
from backend.tests.test_maintenance_mcp import _do, _get, _ok, _session
from backend.tests.test_maintenance_mcp import env  # noqa: F401
from backend.tests.test_maintenance_rcm_api import UID as API_UID
from backend.tests.test_maintenance_rcm_api import api  # noqa: F401

ORG = "user-a"
M = "/api/maintenance"

pytestmark = pytest.mark.usefixtures("mcp_on")


@pytest.fixture()
def m():
    return Maintenance(GraphStore(":memory:", PROJECTORS), ORG, "tester")


def _rebuilds_the_same(m):
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before


def _events(m, type):
    return [e for e in m.s.events(ORG, 1000) if e["type"] == type]


def _rcm(m, position_id):
    return m.rcm_worksheet(position_id, "this")["positions"][0]


def _pump(m, name="Pump A"):
    """A position with two functions. The first has a standard and a functional
    failure breaching it, with a decided mode (and its task) and a deleted mode
    under it; the second has a functional failure of its own."""
    pump = m.create_position(name)
    fn = m.add_function(pump["id"], "Pump 50 L/s")
    st = m.add_standard(fn["id"], "At least 50 L/s")
    ff = m.add_functional_failure(fn["id"], "No flow", standard_id=st["id"])
    mode = m.add_failure_mode(pump["id"], "Bearing seizes", functional_failure_id=ff["id"])
    m.decide_failure_mode(mode["id"], "operational", {
        "outcome": "fixed_interval", "task": "Replace bearings", "interval": 90, "interval_unit": "days",
        "evidence": {"type": "model", "id": "some-model"}})
    gone = m.add_failure_mode(pump["id"], "Casing cracks", functional_failure_id=ff["id"])
    m.retire_failure_mode(gone["id"])
    other = m.add_function(pump["id"], "Contain the water")
    m.add_functional_failure(other["id"], "Leaks")
    return pump, fn, st, ff, mode, gone, other, m._mode_task(mode["id"])


# ---- functional_failure.moved: on its own position -----------------------------------

def test_a_functional_failure_moves_under_another_function_on_its_position(m):
    pump, fn, st, ff, mode, gone, other, task = _pump(m)
    before = m.rcm_mode(mode["id"])

    out = m.move_functional_failure(ff["id"], other["id"])
    assert out["from_function_id"] == fn["id"] and out["function_id"] == other["id"]
    assert out["position_id"] == out["from_position_id"] == pump["id"]
    assert out["from_standard_id"] == st["id"] and out["failure"]["standard"] is None
    assert out["failure_modes_moved"] == 1 and out["tasks_moved"] == 0 and out["links_removed"] == 0

    assert [f["id"] for f in m.s.inn(ORG, ff["id"], "FAILS_AS")] == [other["id"]]
    assert m.s.out(ORG, ff["id"], "BREACHES") == []  # the standard stayed with the old function
    # Its modes (the deleted one too) stay under it, on the same position, with the task as it was.
    assert {x["id"] for x in m.s.out(ORG, ff["id"], "CAUSED_BY")} == {mode["id"], gone["id"]}
    assert [p["id"] for p in m.s.inn(ORG, mode["id"], "CAN_FAIL_AS")] == [pump["id"]]
    assert [p["id"] for p in m.s.out(ORG, task["id"], "ON")] == [pump["id"]]
    assert m.rcm_mode(mode["id"]) == before
    sheet = _rcm(m, pump["id"])
    assert [f["text"] for f in sheet["functions"]] == ["Pump 50 L/s", "Contain the water"]
    assert sheet["functions"][0]["failures"] == []
    assert [x["text"] for x in sheet["functions"][1]["failures"]] == ["Leaks", "No flow"]  # last there
    assert sheet["functions"][1]["failures"][1]["modes"][0]["id"] == mode["id"]

    [event] = _events(m, "functional_failure.moved")
    p = event["payload"]
    assert p["failure_mode_ids"] == sorted([mode["id"], gone["id"]]) and p["task_ids"] == []
    assert "standard_id" not in p and p["on"] == m.today() and event["actor"] == "tester"
    _rebuilds_the_same(m)


def test_it_may_breach_one_of_the_new_functions_standards(m):
    pump, fn, st, ff, mode, gone, other, task = _pump(m)
    st_b = m.add_standard(other["id"], "No visible leak")
    with pytest.raises(Invalid, match="standard of another function"):
        m.move_functional_failure(ff["id"], other["id"], standard_id=st["id"])
    out = m.move_functional_failure(ff["id"], other["id"], standard_id=st_b["id"])
    assert out["failure"]["standard"] == {"id": st_b["id"], "text": "No visible leak"}
    assert [s["id"] for s in m.s.out(ORG, ff["id"], "BREACHES")] == [st_b["id"]]
    assert _events(m, "functional_failure.moved")[0]["payload"]["standard_id"] == st_b["id"]
    # Back where it was, breaching the old standard again.
    back = m.move_functional_failure(ff["id"], fn["id"], standard_id=st["id"])
    assert back["from_standard_id"] == st_b["id"] and back["failure"]["standard"]["id"] == st["id"]
    _rebuilds_the_same(m)


def test_refusals_on_the_same_position(m):
    pump, fn, st, ff, mode, gone, other, task = _pump(m)
    with pytest.raises(Invalid, match="already under"):
        m.move_functional_failure(ff["id"], fn["id"])
    with pytest.raises(Invalid, match="which function"):
        m.move_functional_failure(ff["id"], None)
    with pytest.raises(Invalid, match="no function with that id"):
        m.move_functional_failure(ff["id"], "nope")
    m.remove_function(other["id"])
    with pytest.raises(Invalid, match="deleted"):
        m.move_functional_failure(ff["id"], other["id"])
    assert _events(m, "functional_failure.moved") == []


# ---- functional_failure.moved: to another position -----------------------------------

def test_a_functional_failure_moves_to_a_function_on_another_position(m):
    pump, fn, st, ff, mode, gone, other, task = _pump(m)
    m.set_last_done(task["id"], "2026-01-10")
    b = m.create_position("Pump B")
    fn_b = m.add_function(b["id"], "Pump 20 L/s")
    before = m.rcm_mode(mode["id"])

    out = m.move_functional_failure(ff["id"], fn_b["id"])
    assert out["from_position_id"] == pump["id"] and out["position_id"] == b["id"]
    assert out["failure_modes_moved"] == 1 and out["tasks_moved"] == 1

    assert [f["id"] for f in m.s.inn(ORG, ff["id"], "FAILS_AS")] == [fn_b["id"]]
    assert [p["id"] for p in m.s.inn(ORG, mode["id"], "CAN_FAIL_AS")] == [b["id"]]
    assert [p["id"] for p in m.s.out(ORG, task["id"], "ON")] == [b["id"]]
    # The deleted mode is history on Pump A: it stays there and leaves the failure.
    assert [p["id"] for p in m.s.inn(ORG, gone["id"], "CAN_FAIL_AS")] == [pump["id"]]
    assert m.s.inn(ORG, gone["id"], "CAUSED_BY") == []
    # Ids, decision, evidence and the task's dates stay.
    assert m.rcm_mode(mode["id"]) == before
    assert m._get(task["id"], "Task")["last_done"] == "2026-01-10"
    assert _rcm(m, b["id"])["functions"][0]["failures"][0]["modes"][0]["id"] == mode["id"]
    assert _rcm(m, pump["id"])["functions"][0]["failures"] == []
    p = _events(m, "functional_failure.moved")[0]["payload"]
    assert p["failure_mode_ids"] == [mode["id"]] and p["task_ids"] == [task["id"]]
    _rebuilds_the_same(m)


def test_links_go_when_the_cause_leaves_its_effects_position_and_stay_otherwise(m):
    plant = m.create_position("Plant")
    pump = m.create_position("Pump", parent_id=plant["id"])
    fn_plant = m.add_function(plant["id"], "Supply water")
    effect = m.add_functional_failure(fn_plant["id"], "No supply")
    fn = m.add_function(pump["id"], "Pump water")
    cause = m.add_functional_failure(fn["id"], "No flow")
    m.add_failure_mode(pump["id"], "Bearing seizes", functional_failure_id=cause["id"])
    m.link_cause(effect["id"], cause["id"])
    # Inside the plant still: the link stays.
    motor = m.create_position("Motor", parent_id=plant["id"])
    fn_motor = m.add_function(motor["id"], "Turn the pump")
    kept = m.move_functional_failure(cause["id"], fn_motor["id"])
    assert kept["links_removed"] == 0 and "note" not in kept
    assert [c["id"] for c in m.s.out(ORG, effect["id"], "RESULTS_FROM")] == [cause["id"]]
    # Out of the plant: the link goes, and the move says so.
    elsewhere = m.create_position("Spare pump")
    fn_e = m.add_function(elsewhere["id"], "Pump water")
    out = m.move_functional_failure(cause["id"], fn_e["id"])
    assert out["links_removed"] == 1 and "no longer on a position inside" in out["note"]
    assert m.s.out(ORG, effect["id"], "RESULTS_FROM") == []
    assert len(_events(m, "functional_failure.unlinked")) == 1
    _rebuilds_the_same(m)


def test_refusals_across_positions(m):
    pump, fn, st, ff, mode, gone, other, task = _pump(m)
    b = m.create_position("Pump B")
    fn_b = m.add_function(b["id"], "Pump 20 L/s")
    # The target has a mode of the same name.
    m.add_failure_mode(b["id"], "Bearing seizes")
    with pytest.raises(Invalid, match="already has the failure mode"):
        m.move_functional_failure(ff["id"], fn_b["id"])
    c = m.create_position("Pump C")
    fn_c = m.add_function(c["id"], "Pump")
    # An open work order on the mode's task.
    wo = m.open_work_order(pump["id"], "Bearings", "preventive", task_id=task["id"])
    with pytest.raises(Invalid, match="open work order"):
        m.move_functional_failure(ff["id"], fn_c["id"])
    m.cancel_work_order(wo["id"], "not needed")
    # A failure recorded against the mode.
    m.fit(pump["id"], new_item={"name": "P-1"})
    m.remove(pump["id"], m.today(), "failure", mode["id"])
    with pytest.raises(Invalid, match="split that history"):
        m.move_functional_failure(ff["id"], fn_c["id"])
    # A retired target position.
    m.retire_position(c["id"])
    with pytest.raises(Invalid, match="retired"):
        m.move_functional_failure(ff["id"], fn_c["id"])
    assert _events(m, "functional_failure.moved") == []


@pytest.mark.sqlite_only
def test_the_projector_is_idempotent_and_older_code_passes_the_event_over(m):
    pump, fn, st, ff, mode, gone, other, task = _pump(m)
    b = m.create_position("Pump B")
    fn_b = m.add_function(b["id"], "Pump 20 L/s")
    m.move_functional_failure(ff["id"], fn_b["id"])
    before = m.s.snapshot()
    m.s._conn.execute("BEGIN")
    PROJECTORS["functional_failure.moved"](m.s, ORG, _events(m, "functional_failure.moved")[0]["payload"])
    m.s._conn.execute("COMMIT")
    assert m.s.snapshot() == before
    # Code from before the event shows the failure where it was, and skips nothing else.
    older = {k: v for k, v in PROJECTORS.items() if k != "functional_failure.moved"}
    old = GraphStore(":memory:", older)
    for e in m.s.log.since(0, 10_000):
        old.log.append({"id": new_id(), "org": e["org"], "type": e["type"], "at": "", "actor": None,
                        "payload": e["payload"]})
    old.sync()
    assert [f["id"] for f in old.inn(ORG, ff["id"], "FAILS_AS")] == [fn["id"]]
    assert len(old.skipped()) == 1


# ---- order -------------------------------------------------------------------------

def test_siblings_reorder_at_every_level(m):
    pump, fn, st, ff, mode, gone, other, task = _pump(m)
    second = m.add_failure_mode(pump["id"], "Impeller worn", functional_failure_id=ff["id"])
    leaks = m._failures_of(other["id"])[0]
    new_ff = m.add_functional_failure(fn["id"], "Flow below 50 L/s")

    out = m.reorder_rcm(pump["id"], [other["id"], fn["id"]])
    assert out == {"parent_id": pump["id"], "kind": "functions", "ids": [other["id"], fn["id"]],
                   "previous_ids": [fn["id"], other["id"]]}
    assert m.reorder_rcm(fn["id"], [new_ff["id"], ff["id"]])["kind"] == "functional_failures"
    assert m.reorder_rcm(ff["id"], [second["id"], mode["id"]])["kind"] == "failure_modes"
    sheet = _rcm(m, pump["id"])
    assert [f["text"] for f in sheet["functions"]] == ["Contain the water", "Pump 50 L/s"]
    assert [x["text"] for x in sheet["functions"][1]["failures"]] == ["Flow below 50 L/s", "No flow"]
    assert [x["text"] for x in sheet["functions"][1]["failures"][1]["modes"]] == ["Impeller worn", "Bearing seizes"]
    # The same order again writes nothing; the old order comes back the same way.
    n = m.s.event_count(ORG)
    m.reorder_rcm(pump["id"], [other["id"], fn["id"]])
    assert m.s.event_count(ORG) == n
    m.reorder_rcm(pump["id"], out["previous_ids"])
    assert [f["text"] for f in _rcm(m, pump["id"])["functions"]] == ["Pump 50 L/s", "Contain the water"]

    with pytest.raises(Invalid, match="once"):
        m.reorder_rcm(pump["id"], [fn["id"]])
    with pytest.raises(Invalid, match="once"):
        m.reorder_rcm(ff["id"], [mode["id"], second["id"], leaks["id"]])
    with pytest.raises(Invalid, match="parent_id is a position"):
        m.reorder_rcm(mode["id"], [])
    with pytest.raises(Invalid, match="whose children"):
        m.reorder_rcm(None, [])
    _rebuilds_the_same(m)


# ---- every move says where it came from ------------------------------------------------

def test_results_name_where_things_came_from(m):
    pump, fn, st, ff, mode, gone, other, task = _pump(m)
    leaks = m._failures_of(other["id"])[0]
    loose = m.add_failure_mode(pump["id"], "Motor overheats")
    assert m.assign_failure_mode(loose["id"], ff["id"])["from_functional_failure_id"] is None
    assert m.assign_failure_mode(loose["id"], leaks["id"])["from_functional_failure_id"] == ff["id"]
    assert m.assign_failure_mode(loose["id"], leaks["id"])["from_functional_failure_id"] == leaks["id"]  # no-op
    b = m.create_position("Pump B")
    assert m.move_failure_mode(loose["id"], b["id"])["from_functional_failure_id"] == leaks["id"]
    assert m.move_failure_mode(loose["id"], pump["id"])["from_functional_failure_id"] is None
    spare = m.create_task(pump["id"], "Check guard", 1, "months")
    assert m.move_task(spare["id"], b["id"])["from_position_id"] == pump["id"]
    assert m.update_functional_failure(ff["id"], standard_id=None)["from_standard_id"] == st["id"]
    assert m.update_functional_failure(ff["id"], standard_id=st["id"])["from_standard_id"] is None
    assert m.update_functional_failure(ff["id"], text="No flow at all")["from_standard_id"] == st["id"]
    st2 = m.add_standard(fn["id"], "At 4 bar")
    assert m.reorder_standards(fn["id"], [st2["id"], st["id"]])["previous_ids"] == [st["id"], st2["id"]]


# ---- one batch per drop, over MCP ----------------------------------------------------

def test_a_drop_over_maintenance_apply_is_all_or_nothing_and_undoes(env):
    async def flow(client):
        built = _ok(await _apply(client, [
            {"ref": "p", "do": "positions.create", "args": {"name": "Pump"}},
            {"ref": "f", "do": "failure_modes.add_function", "args": {"position_id": "@p", "text": "Pump water"}},
            {"ref": "a", "do": "failure_modes.add_functional_failure", "args": {"function_id": "@f", "text": "No flow"}},
            {"ref": "b", "do": "failure_modes.add_functional_failure", "args": {"function_id": "@f", "text": "Low flow"}},
            {"ref": "m1", "do": "failure_modes.add", "args": {"position_id": "@p", "functional_failure_id": "@a",
                                                               "text": "Bearing seizes"}},
            {"ref": "m2", "do": "failure_modes.add", "args": {"position_id": "@p", "functional_failure_id": "@a",
                                                               "text": "Impeller worn"}},
        ], dry_run=False))
        ids = {r["ref"]: r["id"] for r in built["results"]}
        # Two modes dragged onto the other functional failure, placed first and second.
        drop = _ok(await _apply(client, [
            {"do": "failure_modes.assign", "args": {"failure_mode_id": ids["m2"], "functional_failure_id": ids["b"]}},
            {"do": "failure_modes.assign", "args": {"failure_mode_id": ids["m1"], "functional_failure_id": ids["b"]}},
            {"do": "failure_modes.reorder", "args": {"parent_id": ids["b"], "ids": [ids["m1"], ids["m2"]]}},
        ], dry_run=False))
        after = _ok(await _get(client, "rcm", ids["p"]))
        undone = _ok(await _apply(client, drop["undo"], dry_run=False))
        back = _ok(await _get(client, "rcm", ids["p"]))
        # One refused operation (the failure is under that function already): nothing changes.
        refused = _ok(await _apply(client, [
            {"do": "failure_modes.assign", "args": {"failure_mode_id": ids["m1"], "functional_failure_id": ids["b"]}},
            {"do": "failure_modes.move_functional_failure", "args": {"functional_failure_id": ids["a"],
                                                                     "function_id": ids["f"]}},
        ], dry_run=False))
        still = _ok(await _get(client, "rcm", ids["p"]))
        return ids, drop, after, undone, back, refused, still

    ids, drop, after, undone, back, refused, still = _session(env["token"], flow)
    assert drop["ok"] and drop["applied"] == 3 and drop["irreversible"] == []
    assert drop["undo"] == [
        {"do": "failure_modes.reorder", "args": {"parent_id": ids["b"], "ids": [ids["m2"], ids["m1"]]}},
        {"do": "failure_modes.assign", "args": {"failure_mode_id": ids["m1"], "functional_failure_id": ids["a"]}},
        {"do": "failure_modes.assign", "args": {"failure_mode_id": ids["m2"], "functional_failure_id": ids["a"]}},
    ]
    fails = after["positions"][0]["functions"][0]["failures"]
    assert [[x["text"] for x in ff["modes"]] for ff in fails] == [[], ["Bearing seizes", "Impeller worn"]]
    assert undone["ok"] and undone["applied"] == 3
    fails = back["positions"][0]["functions"][0]["failures"]
    assert [[x["text"] for x in ff["modes"]] for ff in fails] == [["Bearing seizes", "Impeller worn"], []]
    assert refused["ok"] is False and refused["applied"] == 0 and "already under" in refused["failed"]["error"]
    assert still == back


def test_the_new_actions_over_mcp(env):
    async def flow(client):
        pump = _ok(await _do(client, "maintenance_positions", "create", name="Pump"))["id"]
        fn = _ok(await _do(client, "maintenance_failure_modes", "add_function", position_id=pump, text="Pump"))["id"]
        other = _ok(await _do(client, "maintenance_failure_modes", "add_function", position_id=pump,
                              text="Contain"))["id"]
        ff = _ok(await _do(client, "maintenance_failure_modes", "add_functional_failure", function_id=fn,
                           text="No flow"))["id"]
        st = _ok(await _do(client, "maintenance_failure_modes", "add_standard", function_id=other,
                           text="No drips"))["id"]
        moved = _ok(await _do(client, "maintenance_failure_modes", "move_functional_failure",
                              functional_failure_id=ff, function_id=other, standard_id=st))
        order = _ok(await _do(client, "maintenance_failure_modes", "reorder", parent_id=pump, ids=[other, fn]))
        unknown = await _do(client, "maintenance_failure_modes", "reorder", parent_id=pump, ids=[fn])
        return moved, order, unknown

    moved, order, unknown = _session(env["token"], flow)
    assert moved["failure"]["standard"]["text"] == "No drips" and moved["from_standard_id"] is None
    assert order["kind"] == "functions" and order["previous_ids"] == [order["ids"][1], order["ids"][0]]
    assert unknown.is_error and "once" in unknown.content[0].text


# ---- one batch per drop, in the app --------------------------------------------------

def test_the_rcm_tabs_batch_over_the_app_route(api):
    from backend.routers import maintenance as router

    pump = api.post(f"{M}/positions", json={"name": "Pump"}).json()
    other = api.post(f"{M}/positions", json={"name": "Pump B"}).json()
    fn = api.post(f"{M}/positions/{pump['id']}/functions", json={"text": "Pump water"}).json()
    fn_b = api.post(f"{M}/positions/{other['id']}/functions", json={"text": "Pump more water"}).json()
    a = api.post(f"{M}/functions/{fn['id']}/failures", json={"text": "No flow"}).json()
    b = api.post(f"{M}/functions/{fn['id']}/failures", json={"text": "Low flow"}).json()
    m1 = api.post(f"{M}/positions/{pump['id']}/failure-modes",
                  json={"text": "Bearing seizes", "functional_failure_id": a["id"]}).json()
    m2 = api.post(f"{M}/positions/{pump['id']}/failure-modes",
                  json={"text": "Impeller worn", "functional_failure_id": a["id"]}).json()
    task = api.post(f"{M}/failure-modes/{m1['id']}/tasks", json={"name": "Check bearings", "interval": 3}).json()

    def modes():
        rcm = api.get(f"{M}/positions/{pump['id']}/rcm?scope=this").json()["positions"][0]
        return [[x["text"] for x in ff["modes"]] for ff in rcm["functions"][0]["failures"]]

    # The single routes.
    r = api.put(f"{M}/rcm/order", json={"parent_id": a["id"], "ids": [m2["id"], m1["id"]]})
    assert r.status_code == 200 and r.json()["previous_ids"] == [m1["id"], m2["id"]]
    assert modes() == [["Impeller worn", "Bearing seizes"], []]
    r = api.post(f"{M}/functional-failures/{b['id']}/move", json={"function_id": fn_b["id"]})
    assert r.status_code == 200 and r.json()["position_id"] == other["id"]
    r = api.post(f"{M}/functional-failures/{b['id']}/move", json={"function_id": fn["id"]})
    assert r.status_code == 200 and r.json()["from_function_id"] == fn_b["id"]

    # A drop: two modes onto the other failure, then the task dragged onto the second mode.
    events = router.get_store().event_count(API_UID)
    ops = [{"do": "failure_modes.assign", "args": {"failure_mode_id": m1["id"], "functional_failure_id": b["id"]}},
           {"do": "failure_modes.assign", "args": {"failure_mode_id": m2["id"], "functional_failure_id": b["id"]}},
           {"do": "tasks.link", "args": {"task_id": task["id"], "failure_mode_id": m2["id"]}}]
    dry = api.post(f"{M}/rcm/apply", json={"operations": ops, "dry_run": True})
    assert dry.status_code == 200 and dry.json()["dry_run"] and dry.json()["would_apply"] == 3
    assert router.get_store().event_count(API_UID) == events and modes() == [["Impeller worn", "Bearing seizes"], []]
    done = api.post(f"{M}/rcm/apply", json={"operations": ops})
    assert done.status_code == 200, done.text
    out = done.json()
    assert out["ok"] and out["applied"] == 3 and out["dry_run"] is False and out["irreversible"] == []
    assert modes() == [[], ["Bearing seizes", "Impeller worn"]]
    assert out["undo"] == [
        {"do": "tasks.unlink", "args": {"task_id": task["id"], "failure_mode_id": m2["id"]}},
        {"do": "failure_modes.assign", "args": {"failure_mode_id": m2["id"], "functional_failure_id": a["id"]}},
        {"do": "failure_modes.assign", "args": {"failure_mode_id": m1["id"], "functional_failure_id": a["id"]}},
    ]
    undone = api.post(f"{M}/rcm/apply", json={"operations": out["undo"]})
    assert undone.status_code == 200 and undone.json()["applied"] == 3
    assert modes() == [["Impeller worn", "Bearing seizes"], []]
    assert api.get(f"{M}/failure-modes/{m2['id']}/tasks").json()["tasks"] == []

    # One refusal refuses the whole drop: nothing written, and the reason names the operation.
    events = router.get_store().event_count(API_UID)
    r = api.post(f"{M}/rcm/apply", json={"operations": [
        {"do": "failure_modes.assign", "args": {"failure_mode_id": m1["id"], "functional_failure_id": b["id"]}},
        {"do": "failure_modes.move", "args": {"failure_mode_id": m2["id"], "position_id": pump["id"]}}]})
    assert r.status_code == 422
    assert r.json()["detail"].startswith("Nothing was changed: op 1 (failure_modes.move): It's already on Pump")
    assert r.json()["failed"]["index"] == 1 and r.json()["results"][0]["status"] == "would"
    assert router.get_store().event_count(API_UID) == events and modes() == [["Impeller worn", "Bearing seizes"], []]
    # Only arranging actions run here; the shape is checked as maintenance_apply checks it.
    r = api.post(f"{M}/rcm/apply", json={"operations": [{"do": "positions.create", "args": {"name": "X"}}]})
    assert r.status_code == 422 and "arranging actions" in r.json()["detail"]
    r = api.post(f"{M}/rcm/apply", json={"operations": [{"do": "failure_modes.reorder", "args": {"parent_id": a["id"],
                                                                                                "ids": [], "x": 1}}]})
    assert r.status_code == 422 and "doesn't take x" in r.json()["detail"]
    r = api.post(f"{M}/rcm/apply", json={"operations": []})
    assert r.status_code == 422
    # A standard set and cleared through the batch, with 'none' as over MCP, undoes to what it was.
    st = api.post(f"{M}/functions/{fn['id']}/standards", json={"text": "50 L/s"}).json()
    r = api.post(f"{M}/rcm/apply", json={"operations": [
        {"do": "failure_modes.update_functional_failure", "args": {"functional_failure_id": a["id"],
                                                                   "standard_id": st["id"]}}]})
    assert r.status_code == 200 and r.json()["undo"] == [{"do": "failure_modes.update_functional_failure", "args": {
        "functional_failure_id": a["id"], "standard_id": "none"}}]
    r = api.post(f"{M}/rcm/apply", json={"operations": r.json()["undo"]})
    assert r.status_code == 200 and r.json()["results"][0]["result"]["standard"] is None


# ---- standard.moved: a standard to another function, alone ------------------------------

def test_a_standard_moves_to_another_function_and_its_failures_stay(m):
    pump, fn, st, ff, mode, gone, other, task = _pump(m)
    st2 = m.add_standard(fn["id"], "At 4 bar")
    b = m.create_position("Pump B")
    fn_b = m.add_function(b["id"], "Pump 20 L/s")
    m.add_standard(fn_b["id"], "At least 20 L/s")

    out = m.move_standard(st["id"], fn_b["id"])
    assert out["from_function_id"] == fn["id"] and out["function_id"] == fn_b["id"]
    assert out["from_position_id"] == pump["id"] and out["position_id"] == b["id"]
    assert out["unlinked_functional_failure_ids"] == [ff["id"]] and out["failures_unlinked"] == 1
    assert out["previous_ids"] == [st["id"], st2["id"]] and "stays with the old function" in out["note"]
    # The standard went alone, last on its new function; the failure stayed, under no standard.
    assert [x["id"] for x in m.s.inn(ORG, st["id"], "HELD_TO")] == [fn_b["id"]]
    assert [x["id"] for x in m._standards_of(fn_b["id"])][-1] == st["id"]
    assert [x["id"] for x in m._standards_of(fn["id"])] == [st2["id"]]
    assert m.s.out(ORG, ff["id"], "BREACHES") == []
    assert [x["id"] for x in m.s.inn(ORG, ff["id"], "FAILS_AS")] == [fn["id"]]
    assert {x["id"] for x in m.s.out(ORG, ff["id"], "CAUSED_BY")} == {mode["id"], gone["id"]}
    sheet = _rcm(m, b["id"])
    assert [x["text"] for x in sheet["functions"][0]["standards"]] == ["At least 20 L/s", "At least 50 L/s"]
    _rebuilds_the_same(m)

    # Back, with the failure breaching it again (what the undo sends).
    back = m.move_standard(st["id"], fn["id"], [ff["id"]])
    assert back["unlinked_functional_failure_ids"] == [] and "note" not in back
    assert [x["id"] for x in m.s.out(ORG, ff["id"], "BREACHES")] == [st["id"]]
    _rebuilds_the_same(m)


def test_moving_a_standard_onto_a_function_with_its_one_text_keeps_that_text(m):
    pump, fn, st, ff, mode, gone, other, task = _pump(m)
    m.update_function(other["id"], standard="No visible leaks")
    m.move_standard(st["id"], other["id"])
    assert [x["text"] for x in m._standards_of(other["id"])] == ["No visible leaks", "At least 50 L/s"]
    _rebuilds_the_same(m)


def test_refusals_for_moving_a_standard(m):
    pump, fn, st, ff, mode, gone, other, task = _pump(m)
    leaks = m._failures_of(other["id"])[0]
    n = m.s.event_count(ORG)
    with pytest.raises(Invalid, match="already a standard of"):
        m.move_standard(st["id"], fn["id"])
    with pytest.raises(Invalid, match="no performance standard"):
        m.move_standard("nope", other["id"])
    with pytest.raises(Invalid, match="which function"):
        m.move_standard(st["id"], None)
    with pytest.raises(Invalid, match="no function with that id"):
        m.move_standard(st["id"], "nope")
    with pytest.raises(Invalid, match="functional failures of the function it moves to"):
        m.move_standard(st["id"], other["id"], [ff["id"]])
    b = m.create_position("Old pump")
    fn_b = m.add_function(b["id"], "Pump")
    m.retire_position(b["id"])
    n = m.s.event_count(ORG)
    with pytest.raises(Invalid, match="retired"):
        m.move_standard(st["id"], fn_b["id"])
    m.remove_standard(st["id"])
    n = m.s.event_count(ORG)
    with pytest.raises(Invalid, match="removed"):
        m.move_standard(st["id"], other["id"])
    assert m.s.event_count(ORG) == n and leaks


@pytest.mark.sqlite_only
def test_standard_moved_is_idempotent_and_older_code_passes_it_over(m):
    pump, fn, st, ff, mode, gone, other, task = _pump(m)
    leaks = m._failures_of(other["id"])[0]
    m.move_standard(st["id"], other["id"], [leaks["id"]])
    before = m.s.snapshot()
    m.s._conn.execute("BEGIN")
    PROJECTORS["standard.moved"](m.s, ORG, _events(m, "standard.moved")[0]["payload"])
    m.s._conn.execute("COMMIT")
    assert m.s.snapshot() == before
    older = {k: v for k, v in PROJECTORS.items() if k != "standard.moved"}
    old = GraphStore(":memory:", older)
    for e in m.s.log.since(0, 10_000):
        old.log.append({"id": new_id(), "org": e["org"], "type": e["type"], "at": "", "actor": None,
                        "payload": e["payload"]})
    old.sync()
    assert [f["id"] for f in old.inn(ORG, st["id"], "HELD_TO")] == [fn["id"]]
    assert [x["id"] for x in old.out(ORG, ff["id"], "BREACHES")] == [st["id"]]
    assert len(old.skipped()) == 1


def test_a_standard_moved_through_the_app_batch_undoes_with_its_breaches(api):
    pump = api.post(f"{M}/positions", json={"name": "Pump"}).json()
    other = api.post(f"{M}/positions", json={"name": "Pump B"}).json()
    fn = api.post(f"{M}/positions/{pump['id']}/functions", json={"text": "Pump water"}).json()
    fn_b = api.post(f"{M}/positions/{other['id']}/functions", json={"text": "Pump more water"}).json()
    st = api.post(f"{M}/functions/{fn['id']}/standards", json={"text": "50 L/s"}).json()
    st2 = api.post(f"{M}/functions/{fn['id']}/standards", json={"text": "4 bar"}).json()
    a = api.post(f"{M}/functions/{fn['id']}/failures", json={"text": "No flow", "standard_id": st["id"]}).json()

    def breach():
        rcm = api.get(f"{M}/positions/{pump['id']}/rcm?scope=this").json()["positions"][0]
        f = rcm["functions"][0]
        return [s["text"] for s in f["standards"]], (f["failures"][0]["standard"] or {}).get("text")

    dry = api.post(f"{M}/rcm/apply", json={"dry_run": True, "operations": [
        {"do": "failure_modes.move_standard", "args": {"standard_id": st["id"], "function_id": fn_b["id"]}}]})
    assert dry.status_code == 200 and dry.json()["would_apply"] == 1 and breach() == (["50 L/s", "4 bar"], "50 L/s")
    r = api.post(f"{M}/rcm/apply", json={"operations": [
        {"do": "failure_modes.move_standard", "args": {"standard_id": st["id"], "function_id": fn_b["id"]}}]})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["irreversible"] == [] and breach() == (["4 bar"], None)
    assert out["results"][0]["result"]["unlinked_functional_failure_ids"] == [a["id"]]
    assert out["undo"] == [{"do": "failure_modes.move_standard", "args": {
        "standard_id": st["id"], "function_id": fn["id"], "ids": [a["id"]]}}]
    # The page adds the old order to the undo, so the standard comes back where it was.
    undo = out["undo"] + [{"do": "failure_modes.reorder_standards", "args": {
        "function_id": fn["id"], "standard_ids": [st["id"], st2["id"]]}}]
    r = api.post(f"{M}/rcm/apply", json={"operations": undo})
    assert r.status_code == 200, r.text
    assert breach() == (["50 L/s", "4 bar"], "50 L/s")
    # The single route, and a refusal before anything is written.
    r = api.post(f"{M}/standards/{st['id']}/move", json={"function_id": fn["id"]})
    assert r.status_code == 422 and "already a standard" in r.json()["detail"]
    r = api.post(f"{M}/standards/{st['id']}/move", json={"function_id": fn_b["id"]})
    assert r.status_code == 200 and r.json()["function_id"] == fn_b["id"]


def test_move_standard_over_mcp(env):
    async def flow(client):
        pump = _ok(await _do(client, "maintenance_positions", "create", name="Pump"))["id"]
        fn = _ok(await _do(client, "maintenance_failure_modes", "add_function", position_id=pump, text="Pump"))["id"]
        other = _ok(await _do(client, "maintenance_failure_modes", "add_function", position_id=pump,
                              text="Contain"))["id"]
        st = _ok(await _do(client, "maintenance_failure_modes", "add_standard", function_id=fn,
                           text="No drips"))["id"]
        leaks = _ok(await _do(client, "maintenance_failure_modes", "add_functional_failure", function_id=other,
                              text="Leaks"))["id"]
        moved = _ok(await _do(client, "maintenance_failure_modes", "move_standard", standard_id=st,
                              function_id=other, ids=[leaks]))
        again = await _do(client, "maintenance_failure_modes", "move_standard", standard_id=st, function_id=other)
        return moved, again, leaks

    moved, again, leaks = _session(env["token"], flow)
    assert moved["standard"]["text"] == "No drips" and moved["unlinked_functional_failure_ids"] == []
    assert again.is_error and "already a standard" in again.content[0].text


# ---- a standard dragged with everything under it (29 Oct) ------------------------------
# The RCM tab sends one batch: the standard's move, then each functional failure
# breaching it moved to the same function, breaching it again (their failure
# modes, decisions and tasks go with them). No new event: standard.moved and
# functional_failure.moved, all or nothing, and one undo.

def _batch(m, operations, dry_run=False):
    """What POST /rcm/apply does, on this Maintenance: the trial run on a copy,
    then (unless dry_run) the real one. Returns the answer, or raises
    BatchRefused-like AssertionError text on a refusal ({failed} in the answer)."""
    from backend.maintenance import apply as apply_mod
    from backend.maintenance.store import scratch_copy

    ops = apply_mod.parse_arranging(operations)

    def call(area, action, args):
        return apply_mod.arrange(apply_mod.ACTIVE_M.get(), f"{area}.{action}", args)

    copy = Maintenance(scratch_copy(m.s, m.org), m.org, m.actor)
    trial = apply_mod.run_pass(ops, call, copy, "stop", dry=True)
    if trial["failed"] or dry_run:
        return apply_mod.summarise(ops, trial, True, 0)
    real = apply_mod.run_pass(ops, call, m, "stop", dry=False)
    return apply_mod.summarise(ops, real, False, 0)


def _carry(standard_id, function_id, ff_ids):
    """The batch the RCM tab sends for a standard dragged onto a function."""
    return [{"do": "failure_modes.move_standard", "args": {"standard_id": standard_id, "function_id": function_id}}] + [
        {"do": "failure_modes.move_functional_failure",
         "args": {"functional_failure_id": x, "function_id": function_id, "standard_id": standard_id}}
        for x in ff_ids]


def _two_under_a_standard(m):
    """Pump A's function with two standards: the first breached by two
    functional failures (one with a decided mode and its task, one with a
    plain mode), the second by one that stays. Pump B: a function with a
    standard of its own."""
    pump, fn, st, ff, mode, gone, other, task = _pump(m)
    st2 = m.add_standard(fn["id"], "At 4 bar")
    low = m.add_functional_failure(fn["id"], "Low flow", standard_id=st["id"])
    worn = m.add_failure_mode(pump["id"], "Impeller worn", functional_failure_id=low["id"])
    stays = m.add_functional_failure(fn["id"], "Low pressure", standard_id=st2["id"])
    b = m.create_position("Pump B")
    fn_b = m.add_function(b["id"], "Pump 20 L/s")
    st_b = m.add_standard(fn_b["id"], "At least 20 L/s")
    return dict(pump=pump, fn=fn, st=st, st2=st2, ff=ff, low=low, stays=stays, mode=mode, gone=gone, worn=worn,
                task=task, b=b, fn_b=fn_b, st_b=st_b)


def test_a_standard_dragged_to_another_position_carries_its_failures_modes_and_tasks(m):
    x = _two_under_a_standard(m)
    before_a, before_b = _rcm(m, x["pump"]["id"]), _rcm(m, x["b"]["id"])
    decided = m.rcm_mode(x["mode"]["id"])
    n = m.s.event_count(ORG)
    dry = _batch(m, _carry(x["st"]["id"], x["fn_b"]["id"], [x["ff"]["id"], x["low"]["id"]]), dry_run=True)
    assert dry["ok"] and m.s.event_count(ORG) == n  # the trial run writes nothing

    out = _batch(m, _carry(x["st"]["id"], x["fn_b"]["id"], [x["ff"]["id"], x["low"]["id"]]))
    assert out["ok"] and out["applied"] == 3 and out["irreversible"] == []
    # Only the existing events: one standard.moved, one functional_failure.moved per failure.
    assert len(_events(m, "standard.moved")) == 1 and len(_events(m, "functional_failure.moved")) == 2
    # The standard and both failures breaching it are on Pump B's function, in their order.
    assert [s["id"] for s in m.s.inn(ORG, x["st"]["id"], "HELD_TO")] == [x["fn_b"]["id"]]
    sheet = _rcm(m, x["b"]["id"])["functions"][0]
    assert [s["text"] for s in sheet["standards"]] == ["At least 20 L/s", "At least 50 L/s"]
    assert [(f["text"], f["standard"]["text"]) for f in sheet["failures"]] == [
        ("No flow", "At least 50 L/s"), ("Low flow", "At least 50 L/s")]
    assert [[md["text"] for md in f["modes"]] for f in sheet["failures"]] == [["Bearing seizes"], ["Impeller worn"]]
    # The modes and the task are on Pump B, the decision as it was; the deleted mode stays on Pump A.
    assert [p["id"] for p in m.s.inn(ORG, x["mode"]["id"], "CAN_FAIL_AS")] == [x["b"]["id"]]
    assert [p["id"] for p in m.s.inn(ORG, x["worn"]["id"], "CAN_FAIL_AS")] == [x["b"]["id"]]
    assert [p["id"] for p in m.s.out(ORG, x["task"]["id"], "ON")] == [x["b"]["id"]]
    assert [p["id"] for p in m.s.inn(ORG, x["gone"]["id"], "CAN_FAIL_AS")] == [x["pump"]["id"]]
    assert m.rcm_mode(x["mode"]["id"])["decision"] == decided["decision"]
    # What breached the other standard stays.
    left = _rcm(m, x["pump"]["id"])["functions"][0]
    assert [s["text"] for s in left["standards"]] == ["At 4 bar"]
    assert [(f["text"], f["standard"]["text"]) for f in left["failures"]] == [("Low pressure", "At 4 bar")]
    _rebuilds_the_same(m)

    # One undo (the server's list, then the page's reorders) puts all of it back: order and breaches too.
    undo = out["undo"] + [
        {"do": "failure_modes.reorder_standards", "args": {"function_id": x["fn"]["id"],
                                                           "standard_ids": [x["st"]["id"], x["st2"]["id"]]}},
        {"do": "failure_modes.reorder", "args": {"parent_id": x["fn"]["id"], "ids": [
            x["ff"]["id"], x["low"]["id"], x["stays"]["id"]]}}]
    back = _batch(m, undo)
    assert back["ok"], back.get("failed")
    assert _rcm(m, x["pump"]["id"]) == before_a and _rcm(m, x["b"]["id"]) == before_b
    assert m.rcm_mode(x["mode"]["id"]) == decided
    _rebuilds_the_same(m)


def test_the_undo_list_moves_the_failures_back_before_the_standard(m):
    x = _two_under_a_standard(m)
    out = _batch(m, _carry(x["st"]["id"], x["fn_b"]["id"], [x["ff"]["id"], x["low"]["id"]]))
    # Newest first: each failure back to the old function (breaching nothing yet), then the
    # standard back with both failures breaching it again.
    assert out["undo"] == [
        {"do": "failure_modes.move_functional_failure", "args": {"functional_failure_id": x["low"]["id"],
                                                                 "function_id": x["fn"]["id"]}},
        {"do": "failure_modes.move_functional_failure", "args": {"functional_failure_id": x["ff"]["id"],
                                                                 "function_id": x["fn"]["id"]}},
        {"do": "failure_modes.move_standard", "args": {"standard_id": x["st"]["id"], "function_id": x["fn"]["id"],
                                                       "ids": sorted([x["ff"]["id"], x["low"]["id"]])}},
    ]
    back = _batch(m, out["undo"])
    assert back["ok"]
    assert sorted(f["id"] for f in m.s.inn(ORG, x["st"]["id"], "BREACHES")) == sorted([x["ff"]["id"], x["low"]["id"]])
    assert [p["id"] for p in m.s.out(ORG, x["task"]["id"], "ON")] == [x["pump"]["id"]]
    _rebuilds_the_same(m)


def test_a_standard_carried_to_another_function_on_its_own_position(m):
    x = _two_under_a_standard(m)
    other = m._functions_of(x["pump"]["id"])[1]
    out = _batch(m, _carry(x["st"]["id"], other["id"], [x["ff"]["id"], x["low"]["id"]]))
    assert out["ok"]
    sheet = _rcm(m, x["pump"]["id"])["functions"]
    assert [f["text"] for f in sheet[1]["failures"]] == ["Leaks", "No flow", "Low flow"]
    assert [f["standard"]["text"] if f["standard"] else None for f in sheet[1]["failures"]] == [
        None, "At least 50 L/s", "At least 50 L/s"]
    # Same position: tasks and modes didn't move.
    assert [p["id"] for p in m.s.out(ORG, x["task"]["id"], "ON")] == [x["pump"]["id"]]
    _rebuilds_the_same(m)


def test_one_refusal_under_the_standard_refuses_the_whole_drag(m):
    x = _two_under_a_standard(m)
    n = m.s.event_count(ORG)
    before = _rcm(m, x["pump"]["id"])
    # An open work order on a task under the standard: nothing moves, the standard neither.
    wo = m.open_work_order(x["pump"]["id"], "Bearings", "preventive", task_id=x["task"]["id"])
    n = m.s.event_count(ORG)
    out = _batch(m, _carry(x["st"]["id"], x["fn_b"]["id"], [x["ff"]["id"], x["low"]["id"]]))
    assert out["ok"] is False and out["failed"]["index"] == 1 and "open work order" in out["failed"]["error"]
    assert m.s.event_count(ORG) == n and _rcm(m, x["pump"]["id"]) == before
    m.cancel_work_order(wo["id"], "not needed")
    # Failures recorded against a mode under it: it can't leave its position.
    m.fit(x["pump"]["id"], new_item={"name": "P-1"})
    m.remove(x["pump"]["id"], m.today(), "failure", x["worn"]["id"])
    n = m.s.event_count(ORG)
    out = _batch(m, _carry(x["st"]["id"], x["fn_b"]["id"], [x["ff"]["id"], x["low"]["id"]]))
    assert out["ok"] is False and out["failed"]["index"] == 2 and "split that history" in out["failed"]["error"]
    assert m.s.event_count(ORG) == n
    # A same-named mode on the other position.
    m.add_failure_mode(x["b"]["id"], "Bearing seizes")
    out = _batch(m, _carry(x["st"]["id"], x["fn_b"]["id"], [x["ff"]["id"]]))
    assert out["ok"] is False and "already has the failure mode" in out["failed"]["error"]
    assert m.s.event_count(ORG) == n + 1  # only the mode added above
    _rebuilds_the_same(m)


def test_a_carried_failures_links_that_would_no_longer_run_downwards_go_and_say_so(m):
    plant = m.create_position("Plant")
    pump = m.create_position("Pump", parent_id=plant["id"])
    fn_plant = m.add_function(plant["id"], "Supply water")
    effect = m.add_functional_failure(fn_plant["id"], "No supply")
    fn = m.add_function(pump["id"], "Pump water")
    st = m.add_standard(fn["id"], "50 L/s")
    cause = m.add_functional_failure(fn["id"], "No flow", standard_id=st["id"])
    m.link_cause(effect["id"], cause["id"])
    elsewhere = m.create_position("Spare pump")
    fn_e = m.add_function(elsewhere["id"], "Pump water")
    out = _batch(m, _carry(st["id"], fn_e["id"], [cause["id"]]))
    assert out["ok"]
    moved = out["results"][1]["result"]
    assert moved["links_removed"] == 1 and "no longer on a position inside" in moved["note"]
    assert m.s.out(ORG, effect["id"], "RESULTS_FROM") == []
    assert [x["id"] for x in m.s.out(ORG, cause["id"], "BREACHES")] == [st["id"]]
    _rebuilds_the_same(m)


def test_a_standard_carried_through_the_app_route_with_a_dry_run_first(api):
    pump = api.post(f"{M}/positions", json={"name": "Pump"}).json()
    other = api.post(f"{M}/positions", json={"name": "Pump B"}).json()
    fn = api.post(f"{M}/positions/{pump['id']}/functions", json={"text": "Pump water"}).json()
    fn_b = api.post(f"{M}/positions/{other['id']}/functions", json={"text": "Pump more water"}).json()
    st = api.post(f"{M}/functions/{fn['id']}/standards", json={"text": "50 L/s"}).json()
    a = api.post(f"{M}/functions/{fn['id']}/failures", json={"text": "No flow", "standard_id": st["id"]}).json()
    m1 = api.post(f"{M}/positions/{pump['id']}/failure-modes",
                  json={"text": "Bearing seizes", "functional_failure_id": a["id"]}).json()
    api.post(f"{M}/failure-modes/{m1['id']}/tasks", json={"name": "Check bearings", "interval": 3})

    def sheet(pid):
        return api.get(f"{M}/positions/{pid}/rcm?scope=this").json()["positions"][0]

    ops = _carry(st["id"], fn_b["id"], [a["id"]])
    before = sheet(pump["id"])
    dry = api.post(f"{M}/rcm/apply", json={"operations": ops, "dry_run": True})
    assert dry.status_code == 200 and dry.json()["would_apply"] == 2 and sheet(pump["id"]) == before
    done = api.post(f"{M}/rcm/apply", json={"operations": ops})
    assert done.status_code == 200, done.text
    f = sheet(other["id"])["functions"][0]
    assert [s["text"] for s in f["standards"]] == ["50 L/s"]
    assert [(x["text"], x["standard"]["text"], [md["text"] for md in x["modes"]]) for x in f["failures"]] == [
        ("No flow", "50 L/s", ["Bearing seizes"])]
    assert sheet(other["id"])["functions"][0]["failures"][0]["modes"][0]["tasks"][0]["name"] == "Check bearings"
    undone = api.post(f"{M}/rcm/apply", json={"operations": done.json()["undo"]})
    assert undone.status_code == 200, undone.text
    assert sheet(pump["id"]) == before and sheet(other["id"])["functions"][0]["failures"] == []
    # The same drag refused (the other position has a mode of that name): 422 with the reason, nothing written.
    api.post(f"{M}/positions/{other['id']}/failure-modes", json={"text": "Bearing seizes"})
    r = api.post(f"{M}/rcm/apply", json={"operations": ops, "dry_run": True})
    assert r.status_code == 422 and "op 1 (failure_modes.move_functional_failure)" in r.json()["detail"]
    assert "already has the failure mode" in r.json()["detail"] and sheet(pump["id"]) == before
