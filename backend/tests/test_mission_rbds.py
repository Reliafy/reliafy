"""One RBD per mission, and each block's state in each phase (working, standby, not needed).

A new mission on a position gets an RBD of its own, built from what's inside the position and
marked ``mission_of`` that position (never linked as one of its models). Missions stored on a
position's RBD, as before, read and work out exactly as they did. In a phase, a block on standby
neither ages nor fails (its clock stops) and counts as working if it was working when the phase
began; a block not needed lets the phase work without it while its clock keeps running. The
figures are checked against hand-worked exponential cases."""

import math

import mongomock
import numpy as np
import pytest

from backend.maintenance import position_models as pm
from backend.maintenance.service import PROJECTORS, Invalid, Maintenance
from backend.maintenance.store import GraphStore
from backend.services import rbd_missions as rm
from backend.services import rbd_phases
from backend.services.rbd_analysis import AnalysisError
from backend.services.rbd_graph import normalize_graph

ORG = "org-mission-rbds"
OWNERS = [ORG, "__samples__"]
SAMPLE = "sample-model-bearings-weibull"
RATE = 0.01  # per hour


def _exp(rate=RATE):
    return {"distribution_id": "exponential", "params": [{"name": "failure_rate", "value": rate}]}


def _weibull(alpha, beta):
    return {"distribution_id": "weibull", "params": [{"name": "alpha", "value": alpha}, {"name": "beta", "value": beta}]}


def _diagram(edges, models):
    nodes = [{"id": "input", "type": "input", "data": {}}, {"id": "output", "type": "output", "data": {}}]
    nodes += [{"id": nid, "type": "component", "data": {"label": nid.upper(), "model": model}} for nid, model in models.items()]
    return {"unit": "hours", "nodes": nodes, "edges": [{"source": s, "target": t} for s, t in edges]}


def _parallel():
    return _diagram([("input", "a"), ("input", "b"), ("a", "output"), ("b", "output")], {"a": _exp(), "b": _exp()})


def _series():
    return _diagram([("input", "a"), ("a", "b"), ("b", "output")], {"a": _exp(), "b": _exp()})


def _reliability(graph, phases):
    return rbd_phases.analyze_phases(graph, phases=phases)


def _two(first=None, second=None):
    """Phase 1 lasts 10 hours, phase 2 20 hours; each with the extra settings given."""
    return [{"name": "One", "duration": 10, **(first or {})}, {"name": "Two", "duration": 20, **(second or {})}]


e = math.exp


# ---- the stored shape -------------------------------------------------------------------------

def test_a_phase_keeps_its_standby_blocks_and_refuses_a_block_both_standby_and_not_needed():
    [p] = rbd_phases.parse_phases([{"name": "Cruise", "duration": 1, "standby": ["b", "b"], "not_needed": ["c"]}])
    assert p == {"name": "Cruise", "duration": 1.0, "not_needed": ["c"], "standby": ["b"]}
    with pytest.raises(rbd_phases.PhaseError, match="either on standby or not needed"):
        rbd_phases.parse_phases([{"name": "Cruise", "duration": 1, "standby": ["b"], "not_needed": ["b"]}])
    with pytest.raises(rbd_phases.PhaseError, match="standby must be a list"):
        rbd_phases.parse_phases([{"name": "Cruise", "duration": 1, "standby": "b"}])
    # Kept through every save of the diagram.
    g = normalize_graph({**_parallel(), "phases": _two({"standby": ["b"]})})
    assert g["phases"][0]["standby"] == ["b"]


# ---- the figures, by hand ---------------------------------------------------------------------

def test_every_block_working_is_the_usual_phased_mission():
    got = _reliability(_parallel(), _two())
    assert got["reliability"] == pytest.approx(1 - (1 - e(-RATE * 30)) ** 2, rel=1e-9)
    assert rbd_phases.STANDBY_NOTE not in got["notes"] and rbd_phases.NOT_NEEDED_NOTE not in got["notes"]


def test_standby_in_parallel_stops_the_spare_s_clock_and_raises_the_mission():
    # B stands by through phase 1: it can't fail there, so phase 1 always succeeds; in phase 2 it
    # has run 20 hours, not 30.
    working = _reliability(_parallel(), _two())["reliability"]
    got = _reliability(_parallel(), _two({"standby": ["b"]}))
    assert got["reliability"] == pytest.approx(1 - (1 - e(-RATE * 30)) * (1 - e(-RATE * 20)), rel=1e-9)
    assert got["reliability"] > working
    assert got["phases"][0]["failure_probability"] == pytest.approx(0, abs=1e-12)
    assert got["phases"][0]["standby"] == ["B"]
    assert rbd_phases.STANDBY_NOTE in got["notes"]


def test_standby_in_series_only_ages_the_block_while_it_runs():
    working = _reliability(_series(), _two())["reliability"]
    assert working == pytest.approx(e(-2 * RATE * 30), rel=1e-9)
    got = _reliability(_series(), _two({"standby": ["b"]}))["reliability"]
    assert got == pytest.approx(e(-RATE * 30) * e(-RATE * 20), rel=1e-9)
    assert got > working


def test_not_needed_lets_the_phase_work_without_the_block_while_it_still_ages():
    # B not needed in phase 2 of a series pair: the mission needs A all through, B only in phase 1.
    got = _reliability(_series(), _two(second={"not_needed": ["b"]}))
    assert got["reliability"] == pytest.approx(e(-RATE * 30) * e(-RATE * 10), rel=1e-9)
    assert rbd_phases.NOT_NEEDED_NOTE in got["notes"]
    # In parallel, B not needed in phase 2 makes phase 2 certain: only phase 1 can fail.
    par = _reliability(_parallel(), _two(second={"not_needed": ["b"]}))["reliability"]
    assert par == pytest.approx(1 - (1 - e(-RATE * 10)) ** 2, rel=1e-9)
    # Not needed in phase 1 but needed after: B still aged through phase 1 (unlike standby).
    later = _reliability(_series(), _two({"not_needed": ["b"]}))["reliability"]
    assert later == pytest.approx(e(-2 * RATE * 30), rel=1e-9)


def test_a_weibull_block_on_standby_in_the_middle_carries_its_age_on():
    g = _diagram([("input", "a"), ("a", "output")], {"a": _weibull(100, 2)})
    phases = [{"name": "Out", "duration": 20}, {"name": "Wait", "duration": 50, "standby": ["a"]},
              {"name": "Back", "duration": 30}]
    got = _reliability(g, phases)
    assert got["reliability"] == pytest.approx(e(-((50 / 100) ** 2)), rel=1e-9)
    assert got["phases"][1]["failure_probability"] == pytest.approx(0, abs=1e-12)


def test_the_paused_life_draws_match_its_reliability():
    from surpyval import Exponential

    life = rbd_phases._Paused(Exponential.from_params([RATE]), [(10, 30)])
    assert life.sf(np.array([5, 10, 20, 30, 50])) == pytest.approx(
        [e(-RATE * 5), e(-RATE * 10), e(-RATE * 10), e(-RATE * 10), e(-RATE * 30)])
    np.random.seed(3)
    draws = life.random(200_000)
    assert not ((draws > 10) & (draws < 30)).any()  # never fails while standing by
    assert (draws > 50).mean() == pytest.approx(e(-RATE * 30), abs=0.005)


def test_a_block_whose_values_change_by_phase_can_t_also_stand_by():
    with pytest.raises(AnalysisError, match="can't also stand by"):
        g = _parallel()
        rm_phases = _two({"standby": ["a"]})
        # Stand in for a block whose covariates change by phase: combine names it as varying.
        orig = rm.combine
        try:
            rm.combine = lambda bound, covs, starts: (orig(bound, covs, starts)[0], {}, frozenset({"a"}))
            rm.analyze(None, OWNERS, g, rm_phases, inputs_for=lambda b: [])
        finally:
            rm.combine = orig


def test_standby_isn_t_exported_to_python_without_saying_so():
    from backend.services import rbd_export

    g = {**_parallel(), "phases": _two({"standby": ["b"]})}
    code = rbd_export.to_python(g, "Standby")
    assert "stand by in" in code and "report_mission" not in code
    plain = rbd_export.to_python({**_parallel(), "phases": _two()}, "Plain")
    assert "report_mission" in plain


# ---- one RBD per mission ---------------------------------------------------------------------

@pytest.fixture()
def m():
    return Maintenance(GraphStore(":memory:", PROJECTORS), ORG, "tester")


@pytest.fixture()
def db():
    from backend.services import samples

    d = mongomock.MongoClient()["mission_rbds"]
    samples.seed_samples(d)
    return d


def _station(m, db):
    plant = m.create_position("Pump station")["id"]
    a = m.create_position("Pump A", parent_id=plant)["id"]
    b = m.create_position("Pump B", parent_id=plant)["id"]
    pm.link_saved(m, db, OWNERS, set(), a, "model", SAMPLE)
    pm.link_saved(m, db, OWNERS, set(), b, "model", SAMPLE)
    return plant


def test_each_mission_builds_an_rbd_of_its_own_and_isn_t_a_model_of_the_position(m, db):
    plant = _station(m, db)
    events = m.s.event_count(m.org)
    one = pm.build_mission_rbd(m, db, OWNERS, set(), plant, ORG, "Duty run")
    two = pm.build_mission_rbd(m, db, OWNERS, set(), plant, ORG)
    assert one["rbd"]["name"] == "Pump station — Duty run" and two["mission"]["name"] == "Mission 2"
    assert one["rbd"]["id"] != two["rbd"]["id"]
    assert one["mission"]["id"] == rm.LEGACY_ID and one["mission"]["phases"] == 0
    doc = db.rbds.find_one({"_id": one["rbd"]["id"]})
    assert doc["graph"]["mission_of"] == {"position_id": plant} and doc["graph"]["mission_name"] == "Duty run"
    labels = sorted(n["data"]["label"] for n in doc["graph"]["nodes"] if n["type"] == "component")
    assert labels == ["Pump A", "Pump B"]
    # Not linked as a model: no event written, and the position's models are as they were.
    assert m.s.event_count(m.org) == events and m.position_models(plant) == []
    rows = rm.position_missions(m, db, OWNERS)
    mine = [r for r in rows if r["position_id"] == plant]
    assert [(r["rbd"]["name"], [x["name"] for x in r["missions"]], r["rbd"]["mission_rbd"]) for r in mine] == [
        ("Pump station — Duty run", ["Duty run"], True), ("Pump station — Mission 2", ["Mission 2"], True)]
    with pytest.raises(Invalid, match="already has a mission named"):
        pm.build_mission_rbd(m, db, OWNERS, set(), plant, ORG, "duty run")


def test_a_mission_s_rbd_keeps_its_mission_with_no_phases_and_takes_no_second(m, db):
    plant = _station(m, db)
    made = pm.build_mission_rbd(m, db, OWNERS, set(), plant, ORG, "Duty run")
    graph = db.rbds.find_one({"_id": made["rbd"]["id"]})["graph"]
    g, mission = rm.save(graph, rm.LEGACY_ID, phases=[{"name": "Start", "duration": 1, "standby": ["x"]}])
    assert mission["name"] == "Duty run" and mission["phases"][0]["standby"] == ["x"]
    g, mission = rm.save(g, rm.LEGACY_ID, phases=[])
    assert mission["name"] == "Duty run" and mission["phases"] == [] and g["mission_name"] == "Duty run"
    with pytest.raises(rm.MissionError, match="one mission's own"):
        rm.save(g, None, name="Another")
    with pytest.raises(rm.MissionError, match="delete the mission"):
        rm.remove(g, rm.LEGACY_ID)


def test_a_position_with_nothing_inside_starts_from_a_copy_of_its_rbd(m, db):
    pump = m.create_position("Lone pump")["id"]
    with pytest.raises(Invalid, match="nothing inside and no model in use"):
        pm.build_mission_rbd(m, db, OWNERS, set(), pump, ORG)
    from backend.services import rbds as rbds_service

    rbd = rbds_service.save_rbd(db, "Lone pump RBD", {**_series(), "missions": [{"id": "abcd1234", "name": "Old",
                                                                                   "phases": []}]}, ORG)
    pm.link_rbd(m, db, OWNERS, set(), pump, rbd.id)
    made = pm.build_mission_rbd(m, db, OWNERS, set(), pump, ORG, "Test")
    graph = db.rbds.find_one({"_id": made["rbd"]["id"]})["graph"]
    assert "missions" not in graph and graph["mission_of"]["position_id"] == pump
    assert made["notes"][0].startswith("Started from a copy of Lone pump RBD")


def test_a_leaf_with_a_model_in_use_flies_a_one_block_mission(m, db):
    pump = m.create_position("Lone pump")["id"]
    bare = m.create_position("Bare pump")["id"]
    pm.link_saved(m, db, OWNERS, set(), pump, "model", SAMPLE)
    assert pm.blockable_positions(m, db, OWNERS, set(), m.all_position_models()) == [pump]
    made = pm.build_mission_rbd(m, db, OWNERS, set(), pump, ORG, "Duty")
    assert made["built_from"] == "model" and made["placeholders"] == []
    graph = db.rbds.find_one({"_id": made["rbd"]["id"]})["graph"]
    blocks = [n for n in graph["nodes"] if n["type"] == "component"]
    assert [b["data"]["label"] for b in blocks] == ["Lone pump"]
    assert blocks[0]["data"]["model"].get("modelId") == SAMPLE and not blocks[0]["data"]["model"].get("placeholder")
    assert graph["mission_of"] == {"position_id": pump}
    # It works out like the model on its own: one block in series.
    g, _ = rm.save(graph, rm.LEGACY_ID, phases=[{"name": "Run", "duration": 100}])
    got = rm.analyze(db, OWNERS, g, g["phases"])
    assert 0 < got["reliability"] < 1
    with pytest.raises(Invalid, match="no model in use"):
        pm.build_mission_rbd(m, db, OWNERS, set(), bare, ORG)


# ---- over REST --------------------------------------------------------------------------------

@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config
    from backend import db as db_mod
    from backend.auth import get_current_user
    from backend.main import app
    from backend.routers import maintenance as router
    from backend.services import samples

    d = mongomock.MongoClient()["mission_rbds_rest"]
    samples.seed_samples(d)
    monkeypatch.setattr(db_mod, "_db", d)
    monkeypatch.setattr(db_mod, "_simulated", True)
    monkeypatch.setattr(router, "_store", GraphStore(":memory:", PROJECTORS))
    monkeypatch.setattr(config, "MAINTENANCE_ENABLED", True)
    monkeypatch.setattr(config, "MAINTENANCE_EMAILS", {"a@x.com"})
    app.dependency_overrides[get_current_user] = lambda: {
        "uid": ORG, "email": "a@x.com", "name": "A", "email_verified": True}
    yield TestClient(app)
    app.dependency_overrides.pop(get_current_user, None)


def _ok(r):
    assert r.status_code == 200, r.text
    return r.json()


def test_rest_add_set_states_calculate_and_delete_a_mission_with_its_own_rbd(client):
    plant = _ok(client.post("/api/maintenance/positions", json={"name": "Pump station"}))["id"]
    for name in ("Pump A", "Pump B"):
        kid = _ok(client.post("/api/maintenance/positions", json={"name": name, "parent_id": plant}))["id"]
        _ok(client.post(f"/api/maintenance/positions/{kid}/models", json={"model_id": SAMPLE}))
    # The position's own RBD, with a mission stored on it the old way: it keeps working.
    old = _ok(client.post(f"/api/maintenance/positions/{plant}/models", json={"build_rbd": True}))["model_id"]
    legacy = _ok(client.post(f"/api/rbds/{old}/missions", json={
        "name": "Old way", "phases": [{"name": "Run", "duration": 1000}]}))["mission"]
    before = _ok(client.post(f"/api/rbds/{old}/missions/{legacy['id']}/calculate", json={}))

    made = _ok(client.post(f"/api/maintenance/positions/{plant}/missions", json={"name": "Duty and standby"}))
    rid = made["rbd"]["id"]
    assert made["mission"]["id"] == "mission" and made["rbd"]["name"] == "Pump station — Duty and standby"
    full = _ok(client.get(f"/api/rbds/{rid}/missions/mission"))
    ids = {b["label"]: b["id"] for b in full["blocks"]}
    phases = [{"name": "Day", "duration": 500, "standby": [ids["Pump B"]]},
              {"name": "Night", "duration": 500, "standby": [ids["Pump A"]]}]
    _ok(client.put(f"/api/rbds/{rid}/missions/mission", json={"phases": phases}))
    got = _ok(client.post(f"/api/rbds/{rid}/missions/mission/calculate", json={}))
    working = _ok(client.post(f"/api/rbds/{rid}/missions/mission/calculate",
                              json={"phases": [{"name": "Day", "duration": 500}, {"name": "Night", "duration": 500}]}))
    assert got["phases"][0]["standby"] == ["Pump B"] and any("Standby:" in n for n in got["notes"])
    # The built diagram puts the pumps in series (no redundancy drawn), so each standing by half
    # the time ages each half as much: the mission is likelier to complete.
    assert got["reliability"] > working["reliability"]

    listed = _ok(client.get("/api/maintenance/position-missions"))
    links = listed["links"]
    assert plant not in listed["has_model"] and len(listed["has_model"]) == 2  # the two pumps' models
    mine = [x for x in links if x["position_id"] == plant]
    # The RBD list labels a mission's own RBD with its mission and position.
    rows = {r["id"]: r for r in _ok(client.get("/api/rbds"))["rbds"]}
    assert rows[rid]["mission"] == {"name": "Duty and standby", "position_id": plant, "position": "Pump station"}
    assert "mission" not in rows[old]
    assert sorted(m["name"] for x in mine for m in x["missions"]) == ["Duty and standby", "Old way"]
    own = next(x for x in mine if x["rbd"]["id"] == rid)
    assert own["link_id"] is None and own["rbd"]["mission_rbd"] is True
    assert own["missions"][0]["result"]["reliability"] == pytest.approx(got["reliability"])
    # The legacy mission reads and works out exactly as before.
    again = _ok(client.post(f"/api/rbds/{old}/missions/{legacy['id']}/calculate", json={}))
    assert again["reliability"] == before["reliability"]

    # Deleting the mission deletes its RBD; the position's own RBD and its mission stay.
    _ok(client.delete(f"/api/rbds/{rid}/missions/mission"))
    assert client.get(f"/api/rbds/{rid}").status_code == 404
    links = _ok(client.get("/api/maintenance/position-missions"))["links"]
    assert [m["name"] for x in links if x["position_id"] == plant for m in x["missions"]] == ["Old way"]
    nothing = client.post(f"/api/maintenance/positions/{plant}/missions", json={"name": "Old way"})
    assert nothing.status_code == 422 and "already has a mission named" in nothing.json()["detail"]


# ---- blocks with no model: a placeholder stands in, and the result says so --------------------

MTBF = 17520.0  # hours


def _genset(m, db):
    """A generator set of five positions: the engine (constant rate) and the alternator (Weibull)
    have models; the control panel, fuel system and battery have none."""
    from backend.services import models as models_service

    top = m.create_position("Generator set")["id"]
    ids = {n: m.create_position(n, parent_id=top)["id"]
           for n in ("Engine", "Alternator", "Control panel", "Fuel system", "Battery")}
    seal = models_service.import_model(db, ORG, "Seal", "exponential", unit="hours",
                                       params=[{"name": "failure_rate", "value": 1 / MTBF}])
    belt = models_service.import_model(db, ORG, "Belt", "weibull", unit="hours",
                                       params=[{"name": "alpha", "value": MTBF}, {"name": "beta", "value": 3}])
    pm.link_saved(m, db, OWNERS, set(), ids["Engine"], "model", seal.id)
    pm.link_saved(m, db, OWNERS, set(), ids["Alternator"], "model", belt.id)
    return top


DEPLOYMENT = [{"name": "Start and load", "duration": 2}, {"name": "Run", "duration": 98}]
MODELLED = e(-100 / MTBF) * e(-((100 / MTBF) ** 3))  # 99.43%: the engine and the alternator in series


def test_a_mission_resting_on_placeholders_says_which_blocks_and_what_it_is_without_them(m, db):
    top = _genset(m, db)
    made = pm.build_mission_rbd(m, db, OWNERS, set(), top, ORG, "100-hour deployment")
    assert made["placeholders"] == ["Battery", "Control panel", "Fuel system"]
    graph = db.rbds.find_one({"_id": made["rbd"]["id"]})["graph"]
    g, mission = rm.save(graph, rm.LEGACY_ID, phases=DEPLOYMENT)
    # The pane's blocks say which are placeholders.
    blocks = {b["label"]: b["placeholder"] for b in rm.detail(db, OWNERS, g, mission)["blocks"]}
    assert blocks == {"Alternator": False, "Battery": True, "Control panel": True, "Engine": False, "Fuel system": True}

    got = rm.analyze(db, OWNERS, g, g["phases"])
    # Each placeholder is a 1,000-hour MTBF: three of them take the figure to 73.7%.
    assert got["reliability"] == pytest.approx(MODELLED * e(-0.3), rel=1e-9)
    assert round(got["reliability"], 3) == 0.737
    assert sorted(p["label"] for p in got["placeholders"]) == ["Battery", "Control panel", "Fuel system"]
    assert got["blocks"] == 5 and got["placeholders_left_out"] == []
    # Without them: the two blocks with models, 99.43%.
    assert got["without_placeholders"]["reliability"] == pytest.approx(MODELLED, rel=1e-9)
    assert round(got["without_placeholders"]["reliability"], 4) == 0.9943
    # A placeholder is never named the weakest block: the weakest is one with a model.
    guessed = {p["id"] for p in got["placeholders"]}
    assert all(r["weakest"]["id"] not in guessed for r in got["phases"])
    assert {r["weakest"]["label"] for r in got["phases"]} == {"Engine"}
    assert "isn't ranked" in got["weakest_note"]
    # For the tools: said first, with the figure without them.
    summary = rbd_phases.agent_summary(got)
    assert summary["placeholders"] == ["Battery", "Control panel", "Fuel system"]
    assert summary["mission_reliability_without_placeholders"] == pytest.approx(MODELLED)
    assert summary["notes"][0].startswith("Battery, Control panel, Fuel system have no model: a placeholder")
    # Kept with the result for the lists.
    record = rm.result_record(g, rbd_phases.parse_phases(DEPLOYMENT), got)
    row = rm.summary(g, mission, {mission["id"]: record})
    assert row["result"]["placeholders"] == ["Battery", "Control panel", "Fuel system"]
    assert row["result"]["without_placeholders"] == pytest.approx(MODELLED)


def test_placeholders_not_needed_in_any_phase_are_left_out_and_the_result_no_longer_rests_on_them(m, db):
    top = _genset(m, db)
    made = pm.build_mission_rbd(m, db, OWNERS, set(), top, ORG, "100-hour deployment")
    graph = db.rbds.find_one({"_id": made["rbd"]["id"]})["graph"]
    ids = {n["data"]["label"]: n["id"] for n in graph["nodes"] if n["type"] == "component"}
    off = [ids["Battery"], ids["Control panel"], ids["Fuel system"]]
    got = rm.analyze(db, OWNERS, graph, [{**p, "not_needed": off} for p in DEPLOYMENT])
    assert got["reliability"] == pytest.approx(MODELLED, rel=1e-9)
    assert got["placeholders"] == [] and got["without_placeholders"] is None
    assert sorted(p["label"] for p in got["placeholders_left_out"]) == ["Battery", "Control panel", "Fuel system"]
    assert "placeholders" not in rbd_phases.agent_summary(got) and "weakest_note" not in got
    # Needed in one phase only: it counts again.
    part = rm.analyze(db, OWNERS, graph, [{**DEPLOYMENT[0], "not_needed": off}, {**DEPLOYMENT[1], "not_needed": off[1:]}])
    assert [p["label"] for p in part["placeholders"]] == ["Battery"]
    assert part["without_placeholders"]["reliability"] == pytest.approx(MODELLED, rel=1e-9)


def test_a_mission_with_a_model_on_every_block_says_nothing_about_placeholders(m, db):
    plant = _station(m, db)
    made = pm.build_mission_rbd(m, db, OWNERS, set(), plant, ORG, "Duty run")
    graph = db.rbds.find_one({"_id": made["rbd"]["id"]})["graph"]
    got = rm.analyze(db, OWNERS, graph, [{"name": "Run", "duration": 100}])
    assert got["placeholders"] == [] and got["without_placeholders"] is None and got["blocks"] == 2
    assert "weakest_note" not in got and got["phases"][0]["weakest"]
    record = rm.result_record(graph, rbd_phases.parse_phases([{"name": "Run", "duration": 100}]), got)
    assert "placeholders" not in record


def test_only_placeholders_gives_no_figure_without_them():
    ph = {**_exp(0.001), "placeholder": True}
    got = rbd_phases.analyze_phases(_diagram([("input", "a"), ("a", "b"), ("b", "output")], {"a": ph, "b": ph}),
                                    phases=[{"name": "Run", "duration": 100}], weakest=True)
    assert got["reliability"] == pytest.approx(e(-0.2))
    assert len(got["placeholders"]) == 2 and got["without_placeholders"] is None
    assert got["phases"][0]["weakest"] is None
