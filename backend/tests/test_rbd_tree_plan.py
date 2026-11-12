"""A repairable RBD's maintenance plan read from the tree (rbd_tree_plan.py): a block standing for a
position takes its planned work from that position's tasks (kind from the RCM, interval, LSA time
off-line, cost, package), read each time, never copied into the diagram; blanks are flagged, never
filled in; a saved calculation says when the tasks it used have changed."""

import mongomock
import pytest

from backend.maintenance import position_models as pm
from backend.maintenance import rbd_tree_plan as tp
from backend.maintenance.service import PROJECTORS, Maintenance
from backend.maintenance.store import GraphStore
from backend.tests.test_maintenance_rcm_api import api  # noqa: F401
from backend.tests.test_maintenance_mcp import env  # noqa: F401

ORG = "org-tree-plan"
OWNERS = [ORG, "__samples__"]
SAMPLE = "sample-model-bearings-weibull"
M = "/api/maintenance"


@pytest.fixture()
def m():
    return Maintenance(GraphStore(":memory:", PROJECTORS), ORG, "tester")


@pytest.fixture()
def db():
    from backend.services import samples

    d = mongomock.MongoClient()["rbd_tree_plan"]
    samples.seed_samples(d)
    return d


def _same_after_rebuild(m):
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before


def _station(m, db):
    """A pump station with two pumps (each with a life model), built into a repairable RBD."""
    plant = m.create_position("Pump station")["id"]
    a = m.create_position("Pump A", parent_id=plant)["id"]
    b = m.create_position("Pump B", parent_id=plant)["id"]
    for p in (a, b):
        pm.link_saved(m, db, OWNERS, set(), p, "model", SAMPLE)
    link = pm.build_rbd(m, db, OWNERS, set(), plant)
    db.rbds.update_one({"_id": link["model_id"]}, {"$set": {"graph.repairable": True, "graph.unit": "Hours"}})
    return plant, a, b, link["model_id"]


def _graph(db, rbd_id):
    return db.rbds.find_one({"_id": rbd_id})["graph"]


def _block_of(graph, label):
    return next(n for n in graph["nodes"] if (n.get("data") or {}).get("label") == label)


def test_a_fixed_interval_task_is_an_age_replacement_in_the_diagrams_unit(m, db):
    plant, a, _, rbd = _station(m, db)
    task = m.create_task(a, "Replace the seal", 6, "months", outcome="fixed_interval")
    m.set_task_resources(task["id"], {"duration_hours": 8, "labour": [{"trade": "Fitter", "people": 2, "hours": 4}]})
    m.set_task_cost(task["id"], 1200)
    plans = tp.plans_for_graph(m, rbd, _graph(db, rbd))
    assert plans["position"]["id"] == plant
    row = plans["blocks"][_block_of(_graph(db, rbd), "Pump A")["id"]]
    assert row["used"] == task["id"] and row["position"]["name"] == "Pump A"
    assert row["plan"] == {"task": "age", "interval": 6 * 730.5, "operating_interval": None, "duration": 8.0,
                           "cost": 1200, "inspection_cost": None, "group": None}
    assert row["restoration"]["kind"] == "as_new" and row["restoration"]["words"] == "As new"
    assert row["tasks"][0]["crew"] == "Fitter ×2 · 8 h of labour"
    assert "No repair time" in row["repair_missing"]  # never invented
    # Pump B has no tasks: it runs to failure.
    b_row = plans["blocks"][_block_of(_graph(db, rbd), "Pump B")["id"]]
    assert b_row["used"] is None and b_row["plan"] is None and b_row["tasks"] == []
    _same_after_rebuild(m)


def test_each_rcm_kind_and_what_is_left_blank(m, db):
    _, a, b, rbd = _station(m, db)
    m.create_task(a, "Check the vibration", 1, "months", outcome="on_condition")
    m.create_task(b, "Test the standby start", 12, "months", outcome="failure_finding")
    m.create_task(b, "Wipe down", 1, "weeks")  # routine work: no RCM kind
    plans = tp.plans_for_graph(m, rbd, _graph(db, rbd))
    ra = plans["blocks"][_block_of(_graph(db, rbd), "Pump A")["id"]]
    assert ra["plan"]["task"] == "condition" and ra["plan"]["interval"] == 730.5
    assert ra["plan"]["inspection_cost"] is None and ra["plan"]["cost"] is None
    assert any("No cost" in f or "No time" in f for f in ra["flags"]) is False  # the replacement is the RBD's
    rb = plans["blocks"][_block_of(_graph(db, rbd), "Pump B")["id"]]
    assert rb["plan"]["task"] == "test" and rb["restoration"] is None
    assert any("No cost" in f for f in rb["flags"]) and any("No time off-line" in f for f in rb["flags"])
    assert any("routine work" in n for n in rb["notes"])
    assert [t["modelled"] for t in rb["tasks"]] == [True, False]


def test_a_package_on_fixed_dates_makes_it_a_fixed_time_replacement_in_its_group(m, db):
    plant, a, _, rbd = _station(m, db)
    task = m.create_task(a, "Replace the seal", 3, "months", outcome="fixed_interval")
    m.create_package("Quarterly shut", position_id=plant, timing="fixed", every=3, unit="months",
                     tasks=[task["id"]])
    row = tp.plans_for_graph(m, rbd, _graph(db, rbd))["blocks"][_block_of(_graph(db, rbd), "Pump A")["id"]]
    assert row["plan"]["task"] == "block" and row["plan"]["group"] == "Quarterly shut"
    assert row["tasks"][0]["package"]["name"] == "Quarterly shut"


def test_merge_reads_the_task_and_keeps_only_the_diagrams_own_settings(m, db):
    _, a, b, rbd = _station(m, db)
    m.create_task(a, "Replace the seal", 6, "months", outcome="fixed_interval")
    graph = _graph(db, rbd)
    na, nb = _block_of(graph, "Pump A"), _block_of(graph, "Pump B")
    # Whatever was drawn on the blocks before doesn't count: the tree is the source.
    na["data"].update(preventive={"policy": "block", "interval": 1, "cost": 5}, duty=0.5, crew_priority=2,
                      tree_settings={"opportunity": 2000, "threshold": 0.1})
    nb["data"]["preventive"] = {"policy": "age", "interval": 100}
    out = tp.apply(graph, tp.plans_for_graph(m, rbd, graph))
    da, dbb = _block_of(out, "Pump A")["data"], _block_of(out, "Pump B")["data"]
    assert da["preventive"] == {"policy": "age", "interval": 4383.0, "opportunity": 2000}
    assert da["duty"] == 0.5 and da["crew_priority"] == 2
    assert da["tree_settings"] == {"opportunity": 2000, "threshold": 0.1}  # kept: merging again is the same
    assert da["tree_plan"]["position_id"] == a
    assert "preventive" not in dbb and dbb["tree_plan"] == {"position_id": b, "task_id": None}  # no tasks: run to failure
    # The diagram itself is untouched.
    assert _block_of(_graph(db, rbd), "Pump B")["data"].get("preventive") is None


def test_running_hours_go_through_the_duty(m, db):
    from backend.services import rbd_maintenance

    _, a, _, rbd = _station(m, db)
    point = m.add_point(a, "Run hours", kind="counter", unit="hours")
    m.create_task(a, "Replace the bearings", 500, "hours", outcome="fixed_interval", point_id=point["id"])
    graph = _graph(db, rbd)
    plans = tp.plans_for_graph(m, rbd, graph)
    row = plans["blocks"][_block_of(graph, "Pump A")["id"]]
    assert row["plan"]["interval"] is None and row["plan"]["operating_interval"] == 500
    _block_of(graph, "Pump A")["data"]["duty"] = 0.25
    data = _block_of(tp.apply(graph, plans), "Pump A")["data"]
    assert rbd_maintenance.preventive_spec(data, "Pump A")["interval"] == 2000


def test_a_task_change_changes_its_version(m, db):
    _, a, _, rbd = _station(m, db)
    task = m.create_task(a, "Replace the seal", 6, "months", outcome="fixed_interval")
    before = tp.fingerprint(tp.plans_for_graph(m, rbd, _graph(db, rbd)))
    assert set(before) == {task["id"]}
    m.set_task_cost(task["id"], 900)
    plans = tp.plans_for_graph(m, rbd, _graph(db, rbd))
    now = tp.fingerprint(plans)
    assert tp.changed_tasks(before, now, tp.task_names(plans)) == ["Replace the seal"]
    assert tp.changed_tasks(now, now) == []


def test_a_hand_drawn_rbd_has_no_tree_plan(m, db):
    from backend.services import rbds as rbds_service

    rbd = rbds_service.save_rbd(db, "By hand", {"nodes": [{"id": "x", "type": "component", "data": {"label": "Pump A"}}],
                                                "edges": [], "repairable": True}, ORG)
    m.create_position("Pump A")
    assert tp.plans_for_graph(m, rbd.id, rbd.graph)["blocks"] == {}


def test_rbds_using_a_task(m, db):
    _, a, _, rbd = _station(m, db)
    used = m.create_task(a, "Replace the seal", 6, "months", outcome="fixed_interval")
    other = m.create_task(a, "Test the trip", 12, "months", outcome="failure_finding")
    rows = tp.rbds_using_tasks(m, db, OWNERS, set(), [used["id"], other["id"]])
    assert [(r["task"]["name"], r["used"]) for r in rows] == [("Replace the seal", True), ("Test the trip", False)]
    assert rows[0]["rbd"]["id"] == rbd and rows[0]["block"]["label"] == "Pump A" and rows[0]["last"] is None


# ---- over REST ----------------------------------------------------------------------------------

def _rest_station(api):
    plant = api.post(f"{M}/positions", json={"name": "Station"}).json()["id"]
    a = api.post(f"{M}/positions", json={"name": "Pump A", "parent_id": plant}).json()["id"]
    api.post(f"{M}/positions/{a}/models", json={"model_id": SAMPLE})
    link = api.post(f"{M}/positions/{plant}/models", json={"build_rbd": True}).json()
    rbd = api.get(f"/api/rbds/{link['model_id']}").json()
    graph = {**rbd["graph"], "repairable": True, "unit": "Hours"}
    for n in graph["nodes"]:
        if n["type"] == "component":
            n["data"]["repair"] = {"distribution_id": "exponential", "params": [{"name": "failure_rate", "value": 0.1}]}
    assert api.post("/api/rbds", json={"id": rbd["id"], "name": rbd["name"], "graph": graph}).status_code == 200
    return plant, a, rbd["id"], graph


def test_rest_plan_and_calculation_read_the_tasks(api):
    _, a, rbd_id, graph = _rest_station(api)
    task = api.post(f"{M}/positions/{a}/tasks", json={"name": "Replace the seal", "interval": 6,
                                        "unit": "months", "outcome": "fixed_interval"}).json()
    plan = api.post(f"{M}/rbd-tree-plan", json={"rbd_id": rbd_id}).json()
    [row] = plan["blocks"].values()
    assert row["used"] == task["id"] and row["plan"]["interval"] == 4383.0
    uses = api.get(f"{M}/rbd-plan-uses", params={"task_ids": task["id"]}).json()["uses"]
    assert [u["rbd"]["id"] for u in uses] == [rbd_id]
    res = api.post("/api/rbds/analyze", json={"graph": graph, "rbd_id": rbd_id, "simulate": False})
    assert res.status_code == 200, res.text
    assert res.json()["tree_plan"]["tasks"].keys() == {task["id"]}


@pytest.mark.parametrize("outcome,settings,where", [
    ("on_condition", {"threshold": 0.05, "cost": 4500, "duration": 8}, "preventive"),
    ("failure_finding", {"offset": 100, "coverage": 0.9, "full_test": 8766}, "inspection"),
    ("fixed_interval", {"opportunity": 2000}, "preventive"),
])
def test_the_diagrams_own_settings_survive_save_and_calculate(api, outcome, settings, where):
    """The browser calculates the diagram merged with the tree (rbdTreePlan.js) and the server
    merges what it's sent once more: the diagram's own settings for a tree-linked block (an
    on-condition threshold, a proof test's coverage, an early-renewal age) must survive both, or
    Calculate refuses ("set the replacement threshold") though they're saved."""
    _, a, rbd_id, graph = _rest_station(api)
    api.post(f"{M}/positions/{a}/tasks", json={"name": "The task", "interval": 6, "unit": "months",
                                               "outcome": outcome, "cost": 500})
    block = _block_of(graph, "Pump A")
    block["data"]["tree_settings"] = settings
    if outcome == "fixed_interval":
        block["data"]["maintenance_group"] = "Shut"
    assert api.post("/api/rbds", json={"id": rbd_id, "name": "Station", "graph": graph}).status_code == 200
    saved = api.get(f"/api/rbds/{rbd_id}").json()["graph"]
    assert _block_of(saved, "Pump A")["data"]["tree_settings"] == settings
    plan = api.post(f"{M}/rbd-tree-plan", json={"rbd_id": rbd_id}).json()
    sent = tp.apply(saved, plan)  # what the browser sends: already merged
    server = tp.apply(sent, plan)  # what the server then calculates
    got = _block_of(server, "Pump A")["data"][where]
    assert {k: got.get(k) for k in settings} == settings
    assert server == sent
    res = api.post("/api/rbds/analyze", json={"graph": sent, "rbd_id": rbd_id, "simulate": False})
    assert res.status_code == 200, res.text
    assert "set the replacement threshold" not in res.text.lower()


def test_a_saved_simulation_says_when_the_tasks_it_used_have_changed(api):
    from backend import db

    _, a, rbd_id, graph = _rest_station(api)
    task = api.post(f"{M}/positions/{a}/tasks", json={"name": "Replace the seal", "interval": 6,
                                                      "unit": "months", "outcome": "fixed_interval"}).json()
    # A simulation saved when the task said something else.
    db._db.rbds.update_one({"_id": rbd_id}, {"$set": {
        "availability_cache": {"key": "then", "result": {"steady_state_availability": 0.9}, "computed_at": "2026-11-01"},
        "tree_tasks": {"key": "then", "tasks": {task["id"]: "older"}}}})
    res = api.post("/api/rbds/analyze", json={"graph": graph, "rbd_id": rbd_id}).json()
    status = res["simulation_status"]
    assert status["tasks_changed"] == ["Replace the seal"] and status["saved_at"] == "2026-11-01"
    assert status["state"] != "done"  # not rerun unasked
    uses = api.get(f"{M}/rbd-plan-uses", params={"task_ids": task["id"]}).json()["uses"]
    assert uses[0]["outdated"] is True and uses[0]["last"]["availability"] == 0.9


# ---- Build from what's inside: each block the child's life model (Nov 2026) ----------------------

def test_children_with_models_build_with_no_placeholders_and_match_a_hand_built_rbd(m, db):
    from backend.services import rbds as rbds_service

    plant = m.create_position("Line")["id"]
    kids = [m.create_position(f"Pump {x}", parent_id=plant)["id"] for x in "ABC"]
    for k in kids:
        pm.link_saved(m, db, OWNERS, set(), k, "model", SAMPLE)
    link = pm.build_rbd(m, db, OWNERS, set(), plant)
    assert link["placeholders"] == []
    graph = _graph(db, link["model_id"])
    blocks = [n["data"] for n in graph["nodes"] if n["type"] == "component"]
    assert all(b["model"].get("modelId") == SAMPLE and b["model_source"].startswith("Its model in use") for b in blocks)
    # By hand: the same three in series.
    hand = {"unit": graph["unit"], "nodes": [{"id": "in", "type": "input"}, {"id": "out", "type": "output"}]
            + [{"id": f"b{i}", "type": "component", "label": f"Pump {x}", "model": {"saved_model_id": SAMPLE}}
               for i, x in enumerate("ABC")],
            "edges": [{"source": "in", "target": "b0"}, {"source": "b0", "target": "b1"},
                      {"source": "b1", "target": "b2"}, {"source": "b2", "target": "out"}]}
    from backend.services.rbd_graph import normalize_graph

    resolve = pm.fetcher(db, OWNERS, set())
    hand = normalize_graph(hand, resolve_saved_model=lambda mid: resolve("model", mid))
    built = rbds_service.analyze_graph(db, graph, OWNERS, at_times=[1000.0])
    by_hand = rbds_service.analyze_graph(db, hand, OWNERS, at_times=[1000.0])
    assert built["at"]["sf"][0] == pytest.approx(by_hand["at"]["sf"][0], rel=1e-9)
    assert built["mttf"] == pytest.approx(by_hand["mttf"], rel=1e-9)


def test_a_sub_assembly_with_no_model_of_its_own_is_its_own_rbd_built_from_its_parts(m, db):
    """The cause of placeholders before: Build looked one level down only, so a sub-assembly whose
    lives are its parts' (Propulsion: motors and propellers) stood on a placeholder."""
    top = m.create_position("Drone")["id"]
    prop = m.create_position("Propulsion", parent_id=top)["id"]
    radio = m.create_position("Radio", parent_id=top)["id"]
    pm.link_saved(m, db, OWNERS, set(), radio, "model", SAMPLE)
    motor = m.create_position("Motor", parent_id=prop)["id"]
    pm.link_saved(m, db, OWNERS, set(), motor, "model", SAMPLE)
    m.create_position("ESC", parent_id=prop)  # no model anywhere: an honest placeholder, inside
    link = pm.build_rbd(m, db, OWNERS, set(), top)
    graph = _graph(db, link["model_id"])
    by_label = {n["data"]["label"]: n for n in graph["nodes"] if n["type"] in ("component", "subsystem")}
    assert by_label["Propulsion"]["type"] == "subsystem" and by_label["Radio"]["type"] == "component"
    by_label = {k: n["data"] for k, n in by_label.items()}
    sub_id = by_label["Propulsion"]["rbd"]["id"]
    assert "Its own RBD" in by_label["Propulsion"]["model_source"]
    assert link["placeholders"] == ["Propulsion › ESC"]
    sub = _graph(db, sub_id)
    assert {n["data"]["label"] for n in sub["nodes"] if n["type"] == "component"} == {"Motor", "ESC"}
    # The sub-assembly's RBD is its own (linked, in use there); building again reuses it.
    assert pm.built_rbd_link(m.position_models(prop))["model_id"] == sub_id
    again = pm.build_rbd(m, db, OWNERS, set(), top, replace_link_id=link["id"])
    assert again["model_id"] == link["model_id"]
    # The whole drone calculates, its sub-assembly as a sub-system.
    from backend.services import rbds as rbds_service

    res = rbds_service.analyze_graph(db, _graph(db, link["model_id"]), OWNERS + [ORG])
    assert res["mttf"] > 0
    _same_after_rebuild(m)


def test_a_rebuild_fills_a_placeholder_once_the_position_has_a_model(m, db):
    plant = m.create_position("Line")["id"]
    a = m.create_position("Pump A", parent_id=plant)["id"]
    link = pm.build_rbd(m, db, OWNERS, set(), plant)
    assert link["placeholders"] == ["Pump A"]
    pm.link_saved(m, db, OWNERS, set(), a, "model", SAMPLE)
    pm.build_rbd(m, db, OWNERS, set(), plant, replace_link_id=link["id"])
    [blk] = [n["data"] for n in _graph(db, link["model_id"])["nodes"] if n["type"] == "component"]
    assert blk["model"].get("modelId") == SAMPLE and not blk["model"].get("placeholder")


def test_new_blank_rbd_on_a_leaf(m, db):
    leaf = m.create_position("Pump A")["id"]
    empty = pm.new_rbd(m, db, OWNERS, set(), leaf, ORG)
    graph = _graph(db, empty["model_id"])
    assert [n["type"] for n in graph["nodes"]] == ["input", "output"] and not graph.get("repairable")
    assert empty["source"] == {"new": "blank", "repairable": False}
    # One block for the position itself: its model in use, or a placeholder (flagged) where it has none.
    ph = pm.new_rbd(m, db, OWNERS, set(), leaf, ORG, repairable=True, start="self")
    assert ph["placeholders"] == ["Pump A"]
    pm.link_saved(m, db, OWNERS, set(), leaf, "model", SAMPLE)
    one = pm.new_rbd(m, db, OWNERS, set(), leaf, ORG, repairable=True, start="self")
    graph = _graph(db, one["model_id"])
    [blk] = [n for n in graph["nodes"] if n["type"] == "component"]
    assert graph["repairable"] is True and blk["data"]["model"]["modelId"] == SAMPLE
    assert blk["data"]["model_source"].startswith("Its model in use")
    rows = {r["id"]: r for r in pm.describe(m, db, OWNERS, set(), m.position_models(leaf))}
    assert rows[one["id"]]["source_text"] == "New RBD (one block for the position itself)"
    # Its block reads the position's own tasks.
    task = m.create_task(leaf, "Replace the seal", 6, "months", outcome="fixed_interval")
    plans = tp.plans_for_graph(m, one["model_id"], graph)
    assert plans["blocks"][blk["id"]]["used"] == task["id"]
    _same_after_rebuild(m)


# ---- Sub-systems expanded into a repairable diagram (Nov 2026) ----------------------------------

def _pump_station(m, db):
    """A station: a valve, and two pump sets each holding a pump and a motor (each with a model)."""
    station = m.create_position("Station")["id"]
    valve = m.create_position("Valve", parent_id=station)["id"]
    pm.link_saved(m, db, OWNERS, set(), valve, "model", SAMPLE)
    out = {"station": station, "valve": valve}
    for s in "AB":
        pset = m.create_position(f"Pump set {s}", parent_id=station)["id"]
        for part in ("Pump", "Motor"):
            pid = m.create_position(f"{part} {s}", parent_id=pset)["id"]
            pm.link_saved(m, db, OWNERS, set(), pid, "model", SAMPLE)
            out[f"{part} {s}"] = pid
        out[f"set {s}"] = pset
    return out


def _resolver(db):
    from backend.services import rbds as rbds_service

    return lambda sid: (lambda d: d.graph if d else None)(rbds_service.get_rbd(db, sid, OWNERS + [ORG]))


def test_expanding_sub_systems_keeps_the_figures(m, db):
    """Expanded, a diagram works out exactly as it did with its sub-system blocks: each pump set
    (pump and motor in series) stays in series, and the sets stay as wired around them."""
    from backend.services import rbd_flatten
    from backend.services import rbds as rbds_service

    ids = _pump_station(m, db)
    link = pm.build_rbd(m, db, OWNERS, set(), ids["station"])
    graph = _graph(db, link["model_id"])
    # Wire the two pump sets in parallel after the valve.
    by = {n["data"]["label"]: n["id"] for n in graph["nodes"] if n["type"] in ("component", "subsystem")}
    ins = next(n["id"] for n in graph["nodes"] if n["type"] == "input")
    outs = next(n["id"] for n in graph["nodes"] if n["type"] == "output")
    graph["edges"] = [{"source": ins, "target": by["Valve"]}, {"source": by["Valve"], "target": by["Pump set A"]},
                      {"source": by["Valve"], "target": by["Pump set B"]}, {"source": by["Pump set A"], "target": outs},
                      {"source": by["Pump set B"], "target": outs}]
    flat, expanded = rbd_flatten.expand(graph, _resolver(db))
    assert sorted(expanded) == ["Pump set A", "Pump set B"]
    assert not any(n["type"] == "subsystem" for n in flat["nodes"])
    assert {n["data"]["label"] for n in flat["nodes"] if n["type"] == "component"} == {
        "Valve", "Pump A", "Motor A", "Pump B", "Motor B"}
    before = rbds_service.analyze_graph(db, graph, OWNERS + [ORG], at_times=[5000.0])
    after = rbds_service.analyze_graph(db, flat, OWNERS + [ORG], at_times=[5000.0])
    assert after["at"]["sf"][0] == pytest.approx(before["at"]["sf"][0], rel=1e-9)
    assert after["mttf"] == pytest.approx(before["mttf"], rel=1e-6)


def test_a_sub_system_feeding_a_vote_stays_one_input(m, db):
    """Two parallel branches inside a sub-system feeding a 1-of-2 vote outside: a junction keeps it
    one input, so the vote counts what it counted before."""
    from backend.services import rbd_flatten

    def comp(nid):
        return {"id": nid, "type": "component", "data": {"label": nid, "model": {
            "distribution_id": "exponential", "params": [{"name": "failure_rate", "value": 0.01}]}}}

    sub = {"unit": "hours", "nodes": [{"id": "i", "type": "input"}, {"id": "o", "type": "output"}, comp("x"), comp("y")],
           "edges": [{"source": "i", "target": "x"}, {"source": "i", "target": "y"},
                     {"source": "x", "target": "o"}, {"source": "y", "target": "o"}]}
    top = {"unit": "hours", "nodes": [{"id": "in", "type": "input"}, {"id": "out", "type": "output"}, comp("z"),
                                      {"id": "s", "type": "subsystem", "data": {"label": "Set", "rbd": {"id": "sub"}}},
                                      {"id": "v", "type": "knode", "data": {"label": "2 of 2", "n": 2, "k": 2}}],
           "edges": [{"source": "in", "target": "s"}, {"source": "in", "target": "z"}, {"source": "s", "target": "v"},
                     {"source": "z", "target": "v"}, {"source": "v", "target": "out"}]}
    flat, _ = rbd_flatten.expand(top, lambda sid: sub if sid == "sub" else None)
    vote = next(n for n in flat["nodes"] if n["id"] == "v")
    assert vote["data"]["k"] == 2
    assert sorted(e["source"] for e in flat["edges"] if e["target"] == "v") == ["s-out", "z"]
    with pytest.raises(rbd_flatten.FlattenError, match="isn't there"):
        rbd_flatten.expand(top, lambda sid: None)


def test_expanded_into_a_repairable_diagram_the_tasks_inside_reach_the_plan(api):
    """A natural tree (pump sets holding a pump and a motor) built into a repairable diagram: once
    its sub-systems are expanded, Pump A's overhaul is Pump A's block's plan, and the task says
    which diagram uses it."""
    station = api.post(f"{M}/positions", json={"name": "Station"}).json()["id"]
    pumps = {}
    for s in "AB":
        pset = api.post(f"{M}/positions", json={"name": f"Pump set {s}", "parent_id": station}).json()["id"]
        for part in ("Pump", "Motor"):
            pid = api.post(f"{M}/positions", json={"name": f"{part} {s}", "parent_id": pset}).json()["id"]
            api.post(f"{M}/positions/{pid}/models", json={"model_id": SAMPLE})
            pumps[f"{part} {s}"] = pid
    link = api.post(f"{M}/positions/{station}/models", json={"build_rbd": True}).json()
    rbd = api.get(f"/api/rbds/{link['model_id']}").json()
    graph = {**rbd["graph"], "repairable": True}
    assert {n["type"] for n in graph["nodes"]} >= {"subsystem"}
    check = api.post("/api/rbds/validate", json={"graph": graph}).json()
    assert any("Expand it into its own blocks" in e for e in check.get("errors") or [])
    got = api.post("/api/rbds/expand-subsystems", json={"graph": graph})
    assert got.status_code == 200, got.text
    flat = got.json()["graph"]
    assert flat["repairable"] and "repair time" in " ".join(got.json()["notes"])
    for n in flat["nodes"]:
        if n["type"] == "component":
            n["data"]["repair"] = {"distribution_id": "exponential", "params": [{"name": "failure_rate", "value": 0.1}]}
    assert api.post("/api/rbds", json={"id": rbd["id"], "name": rbd["name"], "graph": flat}).status_code == 200
    task = api.post(f"{M}/positions/{pumps['Pump A']}/tasks", json={
        "name": "Overhaul pump", "interval": 12000, "unit": "hours", "outcome": "fixed_interval"}).json()
    plan = api.post(f"{M}/rbd-tree-plan", json={"rbd_id": rbd["id"]}).json()
    labels = {b: next(n["data"]["label"] for n in flat["nodes"] if n["id"] == b) for b in plan["blocks"]}
    assert sorted(labels.values()) == ["Motor A", "Motor B", "Pump A", "Pump B"]
    row = next(r for b, r in plan["blocks"].items() if labels[b] == "Pump A")
    assert row["used"] == task["id"] and row["plan"]["task"] == "age" and 12000.0 in (row["plan"]["interval"], row["plan"]["operating_interval"])
    uses = api.get(f"{M}/rbd-plan-uses", params={"task_ids": task["id"]}).json()["uses"]
    assert [(u["rbd"]["id"], u["block"]["label"]) for u in uses] == [(rbd["id"], "Pump A")]
    assert api.post("/api/rbds/validate", json={"graph": flat}).json()["valid"] is True


def test_an_rcm_task_named_as_one_on_the_position_is_that_task_with_its_cost(m):
    """Decided with the name of a task already on the position, the decision takes that task (its
    cost, LSA and package with it) rather than adding a second one with no cost."""
    pump = m.create_position("Pump A")["id"]
    overhaul = m.create_task(pump, "Overhaul pump", 10000, "hours")
    m.set_task_cost(overhaul["id"], 6500)
    fn = m.add_function(pump, "Deliver 120 L/s")["id"]
    ff = m.add_functional_failure(fn, "Delivers less")["id"]
    mode = m.add_failure_mode(pump, "Impeller wears", functional_failure_id=ff)["id"]
    m.decide_failure_mode(mode, "operational", {"outcome": "fixed_interval", "task": "overhaul  Pump",
                                                "interval": 14800, "interval_unit": "hours"})
    tasks = m._tasks_on(pump)
    assert [t["id"] for t in tasks] == [overhaul["id"]]
    view = m._task_view(tasks[0])
    assert view["cost"]["amount"] == 6500 and view["interval"] == 14800
    assert tp.task_kind(m, tasks[0]) == "fixed_interval"
    _same_after_rebuild(m)
