"""One RBD per mission, and each block's state in each phase (working, standby, not needed).

A new mission on a position gets an RBD of its own, built from what's inside the position and
marked ``mission_of`` that position (never linked as one of its models). Missions stored on a
position's RBD, as before, read and work out exactly as they did. In a phase, a block on standby
is idle until the phase needs it, then runs (RePyability's true standby, A18); a block not needed
lets the phase work without it while its clock keeps running. The
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


def test_standby_in_parallel_is_true_standby_called_on_when_needed():
    # A18: B stands by through phase 1, idle until A fails, then runs; in phase 2 both run. By hand:
    # A survives phase 1 and the pair runs 20 h, or A fails at s < 10 and B runs from s to 30 h.
    working = _reliability(_parallel(), _two())["reliability"]
    got = _reliability(_parallel(), _two({"standby": ["b"]}))
    hand = e(-RATE * 10) * (1 - (1 - e(-RATE * 20)) ** 2) + RATE * 10 * e(-RATE * 30)
    assert got["method"] == "exact"  # constant rates: RePyability's Markov chain
    assert got["reliability"] == pytest.approx(hand, rel=1e-9)
    # Lower than the old stand-in (B's clock stopped and it couldn't fail), higher than both running.
    stand_in = 1 - (1 - e(-RATE * 30)) * (1 - e(-RATE * 20))
    assert working < got["reliability"] < stand_in
    assert got["phases"][0]["standby"] == ["B"]
    assert rbd_phases.STANDBY_NOTE in got["notes"]


def test_a_spare_that_may_not_start():
    # Cold standby with a 90% start chance: B fails to start one time in ten when A fails.
    got = _reliability(_parallel(), _two({"standby": ["b"], "start_probability": {"b": 0.9}}))
    hand = e(-RATE * 10) * (1 - (1 - e(-RATE * 20)) ** 2) + 0.9 * RATE * 10 * e(-RATE * 30)
    assert got["reliability"] == pytest.approx(hand, rel=1e-9)
    # Kept for standby blocks only, and only below 1.
    [p] = rbd_phases.parse_phases([{"name": "x", "duration": 1, "standby": ["b"],
                                    "start_probability": {"b": 0.9, "a": 0.5, "c": 1}}])
    assert p["start_probability"] == {"b": 0.9}
    with pytest.raises(rbd_phases.PhaseError, match="from 0 to 1"):
        rbd_phases.parse_phases([{"name": "x", "duration": 1, "standby": ["b"], "start_probability": {"b": 2}}])


def test_standby_in_series_is_needed_at_once_so_it_runs():
    # A spare with nothing to back it up is needed from the phase's start: it runs (the old
    # stand-in stopped its clock, which was optimistic).
    working = _reliability(_series(), _two())["reliability"]
    assert working == pytest.approx(e(-2 * RATE * 30), rel=1e-9)
    got = _reliability(_series(), _two({"standby": ["b"]}))["reliability"]
    assert got == pytest.approx(working, rel=1e-9)
    assert got < e(-RATE * 30) * e(-RATE * 20)


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


def test_a_weibull_standby_mission_is_simulated_for_pro_only():
    from backend.services import rbd_standby

    g = _diagram([("input", "a"), ("input", "b"), ("a", "output"), ("b", "output")],
                 {"a": _weibull(100, 2), "b": _weibull(100, 2)})
    phases = [{"name": "Out", "duration": 20}, {"name": "Wait", "duration": 50, "standby": ["b"]},
              {"name": "Back", "duration": 30}]
    # Free: refused, saying why and what Pro adds.
    with pytest.raises(rbd_standby.SimulationNeedsPro, match="only be simulated"):
        _reliability(g, phases)
    # Without standby it stays exact and free.
    assert _reliability(g, [{k: v for k, v in p.items() if k != "standby"} for p in phases])["method"] == "exact"
    with rbd_standby.simulation("run"):
        got = rbd_phases.analyze_phases(g, phases=phases, weakest=True)
        again = rbd_phases.analyze_phases(g, phases=phases, weakest=True)
    assert got["method"] == "simulated" and got["interval"]["n_samples"] == rbd_phases.SIM_MISSIONS
    assert got["reliability"] == again["reliability"]  # seeded
    assert "simulated" in got["method_reason"] and got["curve"]["lower"]
    # RePyability called directly, same seed: the same numbers.
    mission, *_ = rbd_phases.build_mission(g, phases=phases)
    direct = mission.summary(method="simulate", mc_samples=rbd_phases.SIM_MISSIONS, seed=rbd_phases.SIM_SEED,
                             confidence=rbd_phases.SIM_CONFIDENCE)
    assert got["reliability"] == pytest.approx(direct.reliability, abs=1e-15)
    # Lower than the old stand-in (B paused in Wait, both run in Out and Back).
    from surpyval import Weibull

    w = Weibull.from_params([100, 2])
    stand_in = 1 - float(w.ff(100.0)) * float(w.ff(50.0))
    assert got["reliability"] < stand_in


def test_an_aged_exponential_block_keeps_the_mission_exact():
    got = _reliability(_parallel(), _two({"standby": ["b"]}))
    aged = rbd_phases.analyze_phases(_parallel(), phases=_two({"standby": ["b"]}), current_state={"a": {"age": 500}})
    assert aged["method"] == "exact" and aged["reliability"] == pytest.approx(got["reliability"], rel=1e-12)


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


def test_python_export_reproduces_a_standby_mission(tmp_path):
    # Download as Python builds the same PhasedMission.from_diagram: exact (constant rates) gives
    # the same figures to the last digit.
    from backend.services import rbd_export
    from backend.tests.test_rbd_export import _run

    g = {**_parallel(), "phases": _two({"standby": ["b"], "dormancy": {"b": 0.5}, "start_probability": {"b": 0.9}},
                                       {"models": {"a": _weibull(200, 1)}})}
    code = rbd_export.to_python(g, "Standby")
    assert "PhasedMission.from_diagram" in code and 'BlockSetting(state="standby"' in code
    assert "start_probability=0.9" in code and "dormancy_factor=0.5" in code
    results, _ = _run(code, tmp_path)
    app = rbd_phases.analyze_phases(g)
    assert results["phased_mission"]["method"] == "exact"
    assert results["phased_mission"]["reliability"] == pytest.approx(app["reliability"], abs=1e-12)


def test_python_export_reproduces_a_simulated_standby_mission(tmp_path):
    # Simulated (Weibull spare): the same seed and number of missions give the same numbers.
    from backend.services import rbd_export, rbd_standby
    from backend.tests.test_rbd_export import _run

    g = {**_diagram([("input", "a"), ("input", "b"), ("a", "output"), ("b", "output")],
                    {"a": _weibull(100, 2), "b": _weibull(100, 2)}), "phases": _two({"standby": ["b"]})}
    results, _ = _run(rbd_export.to_python(g, "Weibull standby"), tmp_path)
    with rbd_standby.simulation("run"):
        app = rbd_phases.analyze_phases(g)
    assert app["method"] == "simulated"
    assert results["phased_mission"]["method"].startswith("simulated")
    assert results["phased_mission"]["reliability"] == pytest.approx(app["reliability"], abs=1e-12)
    assert list(results["phased_mission"]["phase_failure_probabilities"].values()) == pytest.approx(
        [p["failure_probability"] for p in app["phases"]], abs=1e-12)


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
    # Nothing inside is connected, so the pumps went in series: the mission says so until it's rewired.
    assert doc["graph"]["mission_of"] == {"position_id": plant, "built_in_series": True, "built_from": "tree"}
    assert doc["graph"]["mission_name"] == "Duty run" and "placed in series" in one["series_warning"]
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


def _parallel_station_rbd(m, db, plant, repairable=False):
    """The station's own RBD, rewired by hand: the two pumps in parallel (duty and standby)."""
    link = pm.build_rbd(m, db, OWNERS, set(), plant)
    doc = db.rbds.find_one({"_id": link["model_id"]})
    g = doc["graph"]
    blocks = [n["id"] for n in g["nodes"] if n["type"] == "component"]
    ins = next(n["id"] for n in g["nodes"] if n["type"] == "input")
    outs = next(n["id"] for n in g["nodes"] if n["type"] == "output")
    g["edges"] = [{"id": f"e{i}{j}", "source": s, "target": t}
                  for i, b in enumerate(blocks) for j, (s, t) in enumerate([(ins, b), (b, outs)])]
    if repairable:
        g["repairable"] = True
        g["costs"] = {"downtime_cost": 800}
        for n in g["nodes"]:
            if n["type"] == "component":
                n["data"]["repair"] = _exp(0.1)
                n["data"]["duty"] = 0.5
                n["data"]["tree_settings"] = {"threshold": 0.05}
    db.rbds.update_one({"_id": link["model_id"]}, {"$set": {"graph": g}})
    return link["model_id"]


@pytest.mark.parametrize("repairable", [False, True])
def test_a_mission_starts_from_the_positions_own_rbd_wired_as_it_is(m, db, repairable):
    """Redundancy stays redundancy: a mission on a station whose RBD has its pumps in parallel is
    flown on that wiring, never rebuilt from the tree in series (which understated the station)."""
    plant = _station(m, db)
    src = _parallel_station_rbd(m, db, plant, repairable)
    made = pm.build_mission_rbd(m, db, OWNERS, set(), plant, ORG, "Summer")
    assert made["built_from"] == "copy" and made["series_warning"] is None
    assert made["notes"][0].startswith("Started from a copy of Pump station (from the tree), wired as it is")
    graph = db.rbds.find_one({"_id": made["rbd"]["id"]})["graph"]
    # It says which diagram it was copied from, so the RBD list shows it under that one.
    assert graph["mission_of"] == {"position_id": plant, "from_rbd": src, "built_from": "copy"} and not graph.get("repairable") \
        and "costs" not in graph
    from backend.schema import Rbd
    from backend.services import rbds as rbds_service

    rows = [rbds_service.from_doc(Rbd, d) for d in db.rbds.find({"_id": {"$in": [src, made["rbd"]["id"]]}})]
    assert rbds_service.list_parents(rows) == {made["rbd"]["id"]: src}
    for n in graph["nodes"]:
        assert not {"repair", "duty", "tree_settings"} & set(n.get("data") or {})
    g, _ = rm.save(graph, rm.LEGACY_ID, phases=[{"name": "Run", "duration": 500}])
    got = rm.analyze(db, OWNERS, g, g["phases"])
    assert "series_warning" not in got
    # The same two pumps in series (what the tree's build gives) complete with r²; in parallel,
    # as drawn on the station, 1 − (1 − r)²: the higher figure is the one flown.
    other = _station(m, db)
    tree = pm.build_mission_rbd(m, db, OWNERS, set(), other, ORG, "Summer")
    tg, _ = rm.save(db.rbds.find_one({"_id": tree["rbd"]["id"]})["graph"], rm.LEGACY_ID,
                    phases=[{"name": "Run", "duration": 500}])
    r = math.sqrt(rm.analyze(db, OWNERS, tg, tg["phases"])["reliability"])
    assert got["reliability"] == pytest.approx(1 - (1 - r) ** 2, rel=1e-6)
    assert got["reliability"] > r * r


def test_a_mission_built_from_the_tree_in_series_says_so_until_it_is_rewired(m, db):
    plant = _station(m, db)
    made = pm.build_mission_rbd(m, db, OWNERS, set(), plant, ORG, "Summer")
    assert made["built_from"] == "tree" and "placed in series" in made["series_warning"]
    graph = db.rbds.find_one({"_id": made["rbd"]["id"]})["graph"]
    g, mission = rm.save(graph, rm.LEGACY_ID, phases=[{"name": "Run", "duration": 500}])
    got = rm.analyze(db, OWNERS, g, g["phases"])
    assert got["series_warning"] == made["series_warning"] and got["notes"][0] == made["series_warning"]
    assert rm.detail(db, OWNERS, g, mission)["series_warning"] == made["series_warning"]
    # Survives a save of the diagram (normalize_graph carries it).
    resolve = pm.fetcher(db, OWNERS, set())
    kept = normalize_graph(g, resolve_saved_model=lambda mid: resolve("model", mid))
    assert kept["mission_of"]["built_in_series"] is True
    # Rewired in parallel: nothing more to say.
    blocks = [n["id"] for n in g["nodes"] if n["type"] == "component"]
    ins = next(n["id"] for n in g["nodes"] if n["type"] == "input")
    outs = next(n["id"] for n in g["nodes"] if n["type"] == "output")
    rewired = {**g, "edges": [{"source": s, "target": t} for b in blocks for s, t in ((ins, b), (b, outs))]}
    assert rm.series_warning(rewired) is None
    assert "series_warning" not in rm.analyze(db, OWNERS, rewired, g["phases"])


def test_a_mission_result_says_why_it_has_no_bound(m, db):
    g, _ = rm.save({**_parallel(), "mission_of": {"position_id": "p"}, "mission_name": "M"}, rm.LEGACY_ID,
                   phases=[{"name": "Run", "duration": 10}])
    got = rm.analyze(db, OWNERS, g, g["phases"])
    assert got["method"] == "exact" and "interval" not in got
    assert got["bound_note"].startswith("No bound:")
    assert rbd_phases.agent_summary(got)["bound_note"] == got["bound_note"]


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
    assert graph["mission_of"] == {"position_id": pump, "built_from": "model"}
    # It works out like the model on its own: one block in series.
    g, _ = rm.save(graph, rm.LEGACY_ID, phases=[{"name": "Run", "duration": 100}])
    got = rm.analyze(db, OWNERS, g, g["phases"])
    assert 0 < got["reliability"] < 1
    with pytest.raises(Invalid, match="no model in use"):
        pm.build_mission_rbd(m, db, OWNERS, set(), bare, ORG)


def test_a_mission_added_on_a_model_row_is_flown_on_that_model_and_says_so(m, db):
    """Add a mission… on a model's row (the Explorer's Models tab): on an RBD row, a copy of that
    RBD; on the model in use, one block. The mission keeps the row it was started on, and the
    missions read says so, so the tab shows it under that model."""
    from backend.services import rbds as rbds_service

    plant = _station(m, db)
    first = pm.build_rbd(m, db, OWNERS, set(), plant)
    other = rbds_service.save_rbd(db, "Station, as drawn", _parallel(), ORG)
    second = pm.link_rbd(m, db, OWNERS, set(), plant, other.id)
    # The station's own RBD would be picked by default (the one built there); the row asked for wins.
    made = pm.build_mission_rbd(m, db, OWNERS, set(), plant, ORG, "Night", link_id=second["id"])
    assert made["built_from"] == "copy" and made["notes"][0].startswith("Started from a copy of Station, as drawn")
    graph = db.rbds.find_one({"_id": made["rbd"]["id"]})["graph"]
    assert graph["mission_of"] == {"position_id": plant, "from_rbd": other.id, "on_link": second["id"], "built_from": "copy"}
    row = next(r for r in rm.position_missions(m, db, OWNERS) if r["rbd"] and r["rbd"]["id"] == made["rbd"]["id"])
    assert (row["rbd"]["from_rbd"], row["rbd"]["on_link"], row["rbd"]["built_from"]) == (other.id, second["id"], "copy")
    # From the position (no row): the default pick, as before (the RBD in use, else the one built
    # there), and no row of its own kept.
    plain = pm.build_mission_rbd(m, db, OWNERS, set(), plant, ORG, "Day")
    owner = db.rbds.find_one({"_id": plain["rbd"]["id"]})["graph"]["mission_of"]
    in_use = next(x for x in m.position_models(plant) if x.get("in_use"))
    assert owner["from_rbd"] == in_use["model_id"] in (first["model_id"], other.id) and "on_link" not in owner
    # A leaf's model in use: one block, kept as its row.
    pump = m.create_position("Lone pump")["id"]
    life = pm.link_saved(m, db, OWNERS, set(), pump, "model", SAMPLE)
    one = pm.build_mission_rbd(m, db, OWNERS, set(), pump, ORG, "Duty", link_id=life["id"])
    assert one["built_from"] == "model"
    assert db.rbds.find_one({"_id": one["rbd"]["id"]})["graph"]["mission_of"] == {
        "position_id": pump, "on_link": life["id"], "built_from": "model"}
    # A row that isn't the position's, or a model not in use: refused, in words.
    with pytest.raises(Invalid, match="isn't on this position"):
        pm.build_mission_rbd(m, db, OWNERS, set(), pump, ORG, "Again", link_id=second["id"])
    # With a second model linked, the one not in use flies a mission too: its own block, that model.
    pm.link_saved(m, db, OWNERS, set(), pump, "model", "sample-model-bearings-lognormal")
    idle = next(x for x in m.position_models(pump) if not x.get("in_use"))
    spare = pm.build_mission_rbd(m, db, OWNERS, set(), pump, ORG, "Spare", link_id=idle["id"])
    blocks = [n for n in db.rbds.find_one({"_id": spare["rbd"]["id"]})["graph"]["nodes"] if n["type"] == "component"]
    assert blocks[0]["data"]["model"].get("modelId") == idle["model_id"]
    # A covariate (PH) model in use flies a one-block mission too: its phases set the covariates.
    seal = m.create_position("Seal")["id"]
    ph = pm.link_saved(m, db, OWNERS, set(), seal, "model", "sample-model-seal-weibull-ph")
    cov = pm.build_mission_rbd(m, db, OWNERS, set(), seal, ORG, "Hot run", link_id=ph["id"])
    assert cov["built_from"] == "model"
    [row] = [r for r in rm.position_missions(m, db, OWNERS, position_ids=[seal]) if r["rbd"]]
    assert row["rbd"]["on_link"] == ph["id"] and row["missions"][0]["covariates"]


# ---- a mission on any life or covariate model; a plain one is a length from an age ------------

def _typed_weibull(db, alpha=1000.0, beta=2.0):
    from backend.services import models as models_service

    return models_service.import_model(db, ORG, "Typed Weibull", "weibull", unit="hours",
                                       params=[{"name": "alpha", "value": alpha}, {"name": "beta", "value": beta}])


@pytest.fixture()
def live_db(db, monkeypatch):
    """The seeded db as the app's own, so a saved fit can be brought back to bound it."""
    from backend import db as db_mod

    monkeypatch.setattr(db_mod, "_db", db)
    monkeypatch.setattr(db_mod, "_simulated", True)
    return db


def test_a_plain_life_model_s_mission_is_its_length_from_its_starting_age(m, live_db):
    """Hand checks: Weibull alpha 1000, beta 2. From new, 200 h: exp(-(200/1000)^2) = 0.9608. From
    age 500, 200 h more: R(700) / R(500) = exp(-(0.7^2 - 0.5^2)) = 0.7866."""
    db = live_db
    w = _typed_weibull(db)
    pump = m.create_position("Lone pump")["id"]
    link = pm.link_saved(m, db, OWNERS, set(), pump, "model", w.id)
    made = pm.build_mission_rbd(m, db, OWNERS, set(), pump, ORG, "Short run", link_id=link["id"])
    assert made["mission"]["simple"] is True and made["mission"]["start"] == {"new": True}
    graph = db.rbds.find_one({"_id": made["rbd"]["id"]})["graph"]
    assert "mission_start" not in graph and not graph.get("phases")  # no length invented
    g, _ = rm.save(graph, rm.LEGACY_ID, phases=[{"name": "Mission", "duration": 200}])
    got = rm.analyze(db, OWNERS, g, g["phases"])
    assert got["reliability"] == pytest.approx(0.9608, abs=5e-5)
    assert got["reliability"] == pytest.approx(math.exp(-(200 / 1000) ** 2), rel=1e-9)
    assert got["start"] == {"basis": "new", "age": 0.0}
    # Typed in: no fit, so no bound, and it says so.
    assert "lower_bound" not in got and got["bound_note"].startswith("No bound: its parameters were typed in")
    g, mission = rm.save(g, rm.LEGACY_ID, start={"age": 500})
    assert g["mission_start"] == {"age": 500.0} and rm.summary(g, mission)["start"] == {"age": 500.0}
    got = rm.analyze(db, OWNERS, g, g["phases"])
    assert got["reliability"] == pytest.approx(0.7866, abs=5e-5)
    assert got["reliability"] == pytest.approx(math.exp(-(0.7 ** 2 - 0.5 ** 2)), rel=1e-9)
    assert got["start"] == {"basis": "age", "age": 500.0}
    # Back to new; a bad age is refused in words.
    g, _ = rm.save(g, rm.LEGACY_ID, start=None)
    assert "mission_start" not in g
    with pytest.raises(rm.MissionError, match="starting age"):
        rm.save(g, rm.LEGACY_ID, start=-3)


def test_several_missions_on_one_model_compare_side_by_side(m, live_db):
    db = live_db
    w = _typed_weibull(db)
    pump = m.create_position("Lone pump")["id"]
    link = pm.link_saved(m, db, OWNERS, set(), pump, "model", w.id)
    for name, length in (("Short", 200), ("Long", 600)):
        made = pm.build_mission_rbd(m, db, OWNERS, set(), pump, ORG, name, link_id=link["id"])
        doc = db.rbds.find_one({"_id": made["rbd"]["id"]})
        g, _ = rm.save(doc["graph"], rm.LEGACY_ID, phases=[{"name": "Mission", "duration": length}])
        got = rm.analyze(db, OWNERS, g, g["phases"])
        db.rbds.update_one({"_id": doc["_id"]}, {"$set": {"graph": g, "mission_results.mission": rm.result_record(g, g["phases"], got)}})
    rows = [r for r in rm.position_missions(m, db, OWNERS, position_ids=[pump]) if r["rbd"]]
    got = {r["missions"][0]["name"]: r["missions"][0] for r in rows}
    assert {r["rbd"]["on_link"] for r in rows} == {link["id"]}
    assert got["Short"]["result"]["reliability"] == pytest.approx(math.exp(-0.04))
    assert got["Long"]["result"]["reliability"] == pytest.approx(math.exp(-0.36))
    assert got["Short"]["simple"] and got["Long"]["duration"] == 600


def test_a_fitted_plain_model_s_mission_has_its_90_percent_one_sided_lower_bound(m, live_db):
    """From new the bound is SurPyval's own lower bound on R(length) at 90% one-sided; from an age it
    is the delta-method bound on log(H(age + length) - H(age)), which is that at age 0."""
    from backend.services import models as models_service

    db = live_db
    pump = m.create_position("Lone pump")["id"]
    link = pm.link_saved(m, db, OWNERS, set(), pump, "model", SAMPLE)
    made = pm.build_mission_rbd(m, db, OWNERS, set(), pump, ORG, "Duty", link_id=link["id"])
    g = db.rbds.find_one({"_id": made["rbd"]["id"]})["graph"]
    g, _ = rm.save(g, rm.LEGACY_ID, phases=[{"name": "Mission", "duration": 200}])
    live = models_service.get_live_model(db, SAMPLE, OWNERS)["model"]
    got = rm.analyze(db, OWNERS, g, g["phases"])
    assert got["reliability"] == pytest.approx(float(live.sf(200)))
    ref = float(np.ravel(live.cb(np.array([200.0]), on="sf", alpha_ci=0.1, bound="lower"))[0])
    assert got["lower_bound"] == {"lower": pytest.approx(ref), "confidence": 0.9, "side": "lower"}
    assert "90% one-sided" in got["bound_note"]
    assert rm.conditional_lower(live, 1e-12, 200) == pytest.approx(ref, rel=1e-6)  # the delta method, at new
    g, _ = rm.save(g, rm.LEGACY_ID, start=500)
    got = rm.analyze(db, OWNERS, g, g["phases"])
    assert got["reliability"] == pytest.approx(float(live.sf(700) / live.sf(500)))
    assert got["lower_bound"]["lower"] < got["reliability"]
    # The tools carry the same.
    assert rbd_phases.agent_summary(got)["lower_bound"] == got["lower_bound"]


def test_a_plain_mission_on_a_fitted_item_starts_now_and_reads_its_age(m, live_db):
    db = live_db
    w = _typed_weibull(db)
    pump = m.create_position("Pump")["id"]
    item = m.create_item("Pump 7")["id"]
    m.fit(pump, item_id=item, on="2026-01-01")
    link = pm.link_saved(m, db, OWNERS, set(), pump, "model", w.id)
    made = pm.build_mission_rbd(m, db, OWNERS, set(), pump, ORG, "Next shift", link_id=link["id"])
    g = db.rbds.find_one({"_id": made["rbd"]["id"]})["graph"]
    assert g["mission_start"] == {"now": True}
    g, _ = rm.save(g, rm.LEGACY_ID, phases=[{"name": "Mission", "duration": 200}])
    got = rm.analyze(db, OWNERS, g, g["phases"], age_now={"age": 500, "note": "since it was fitted"})
    assert got["reliability"] == pytest.approx(0.7866, abs=5e-5)
    assert got["start"]["basis"] == "now" and got["start"]["age"] == 500
    # Its age can't be read: worked out from new, and said so.
    got = rm.analyze(db, OWNERS, g, g["phases"], age_now={"reason": "nothing is fitted at Pump"})
    assert got["reliability"] == pytest.approx(0.9608, abs=5e-5)
    assert got["notes"][0] == "From new: nothing is fitted at Pump."


def test_a_mission_flies_on_any_covariate_model_in_use_or_not_however_it_was_fitted(m, live_db):
    """Covariate models fitted from readings that change over time are covariate models too: a
    mission flies on them, and on a model that isn't the one in use."""
    db = live_db
    seal = m.create_position("Seal")["id"]
    first = pm.link_saved(m, db, OWNERS, set(), seal, "model", SAMPLE)
    tvc = pm.link_saved(m, db, OWNERS, set(), seal, "model", "sample-model-pump-load-weibull-ph")
    ph = pm.link_saved(m, db, OWNERS, set(), seal, "model", "sample-model-seal-weibull-ph")
    joint = pm.link_saved(m, db, OWNERS, set(), seal, "model", "sample-joint-feed-pumps")
    flyable = pm.flyable_links(m, db, OWNERS, set(), m.all_position_models([seal]))
    assert set(flyable) == {first["id"], tvc["id"], ph["id"]}  # a condition-and-life model isn't, yet
    assert not next(x for x in m.position_models(seal) if x["id"] == tvc["id"]).get("in_use")
    made = pm.build_mission_rbd(m, db, OWNERS, set(), seal, ORG, "Load profile", link_id=tvc["id"])
    g = db.rbds.find_one({"_id": made["rbd"]["id"]})["graph"]
    assert not rm.is_simple(g) and not made["mission"].get("simple")
    g, _ = rm.save(g, rm.LEGACY_ID, phases=[{"name": "Low", "duration": 500, "values": {"load_pct": 60}},
                                            {"name": "High", "duration": 500, "values": {"load_pct": 90}}])
    got = rm.analyze(db, OWNERS, g, g["phases"])
    assert 0 < got["reliability"] < 1 and "lower_bound" not in got
    with pytest.raises(Invalid):
        pm.build_mission_rbd(m, db, OWNERS, set(), seal, ORG, "Joint", link_id=joint["id"])
    # A starting age is for a plain life model's mission only.
    with pytest.raises(rm.MissionError, match="starting age"):
        rm.save(g, rm.LEGACY_ID, start=100)


def test_a_ph_model_s_two_phase_mission_equals_the_engine_s_own_calculation(m, live_db):
    """A proportional-hazards block through two phases at two covariate values carries its age:
    H = H(t1 | z1) + H(t1 + t2 | z2) - H(t1 | z2), from the fitted model itself."""
    import pandas as pd

    from backend.services import models as models_service

    db = live_db
    seal = m.create_position("Seal")["id"]
    ph = pm.link_saved(m, db, OWNERS, set(), seal, "model", "sample-model-seal-weibull-ph")
    made = pm.build_mission_rbd(m, db, OWNERS, set(), seal, ORG, "Hot then cool", link_id=ph["id"])
    g = db.rbds.find_one({"_id": made["rbd"]["id"]})["graph"]
    z1, z2 = {"temp_C": 95, "load": 0.85}, {"temp_C": 65, "load": 0.6}  # inside the fitted ranges
    g, _ = rm.save(g, rm.LEGACY_ID, phases=[{"name": "Hot", "duration": 300, "values": z1},
                                            {"name": "Cool", "duration": 400, "values": z2}])
    got = rm.analyze(db, OWNERS, g, g["phases"])
    live = models_service.get_live_model(db, "sample-model-seal-weibull-ph", OWNERS)["model"]

    def hf(t, z):
        return float(np.ravel(live.Hf(np.array([float(t)]), pd.DataFrame([z])))[0])

    want = math.exp(-(hf(300, z1) + hf(700, z2) - hf(300, z2)))
    assert got["reliability"] == pytest.approx(want, rel=1e-6)


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
    # The built diagram puts the pumps in series (no redundancy drawn), so a pump on standby is
    # needed at once and runs: the same as both working (A18; the old stand-in stopped its clock).
    assert got["reliability"] == pytest.approx(working["reliability"], abs=0.02)

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


# ---- blocks with no model: nothing is invented, and the mission names them -------------------

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


def test_a_mission_with_blocks_on_no_model_names_them_and_gives_no_figure(m, db):
    """Nothing is invented for a block with no life model: the mission isn't worked out until
    each block a phase needs has one, and the refusal names them."""
    top = _genset(m, db)
    made = pm.build_mission_rbd(m, db, OWNERS, set(), top, ORG, "100-hour deployment")
    assert made["placeholders"] == ["Battery", "Control panel", "Fuel system"]
    graph = db.rbds.find_one({"_id": made["rbd"]["id"]})["graph"]
    g, mission = rm.save(graph, rm.LEGACY_ID, phases=DEPLOYMENT)
    # The pane's blocks say which have no model.
    blocks = {b["label"]: b["placeholder"] for b in rm.detail(db, OWNERS, g, mission)["blocks"]}
    assert blocks == {"Alternator": False, "Battery": True, "Control panel": True, "Engine": False, "Fuel system": True}
    with pytest.raises(AnalysisError) as exc:
        rm.analyze(db, OWNERS, g, g["phases"])
    assert "Battery, Control panel, Fuel system" in str(exc.value)
    assert [b["label"] for b in exc.value.blocks] == ["Battery", "Control panel", "Fuel system"]


def test_blocks_with_no_model_not_needed_in_any_phase_are_left_out(m, db):
    top = _genset(m, db)
    made = pm.build_mission_rbd(m, db, OWNERS, set(), top, ORG, "100-hour deployment")
    graph = db.rbds.find_one({"_id": made["rbd"]["id"]})["graph"]
    ids = {n["data"]["label"]: n["id"] for n in graph["nodes"] if n["type"] == "component"}
    off = [ids["Battery"], ids["Control panel"], ids["Fuel system"]]
    got = rm.analyze(db, OWNERS, graph, [{**p, "not_needed": off} for p in DEPLOYMENT])
    assert got["reliability"] == pytest.approx(MODELLED, rel=1e-9)
    assert got["placeholders"] == [] and got["without_placeholders"] is None
    assert "placeholders" not in rbd_phases.agent_summary(got) and "weakest_note" not in got
    # Needed in one phase only: it needs a model again.
    with pytest.raises(AnalysisError, match="needs a life model.*Battery"):
        rm.analyze(db, OWNERS, graph, [{**DEPLOYMENT[0], "not_needed": off}, {**DEPLOYMENT[1], "not_needed": off[1:]}])


def test_a_mission_with_a_model_on_every_block_says_nothing_about_placeholders(m, db):
    plant = _station(m, db)
    made = pm.build_mission_rbd(m, db, OWNERS, set(), plant, ORG, "Duty run")
    graph = db.rbds.find_one({"_id": made["rbd"]["id"]})["graph"]
    got = rm.analyze(db, OWNERS, graph, [{"name": "Run", "duration": 100}])
    assert got["placeholders"] == [] and got["without_placeholders"] is None and got["blocks"] == 2
    assert "weakest_note" not in got and got["phases"][0]["weakest"]
    record = rm.result_record(graph, rbd_phases.parse_phases([{"name": "Run", "duration": 100}]), got)
    assert "placeholders" not in record


def test_only_placeholders_gives_no_figure():
    ph = {**_exp(0.001), "placeholder": True}
    with pytest.raises(AnalysisError, match="These blocks need a life model"):
        rbd_phases.analyze_phases(_diagram([("input", "a"), ("a", "b"), ("b", "output")], {"a": ph, "b": ph}),
                                  phases=[{"name": "Run", "duration": 100}], weakest=True)


def test_rest_a_plain_mission_s_length_starting_age_and_bound(client):
    """Add a mission… on a life model that isn't in use; its length and starting age over REST, an
    unsaved age worked out without being kept, and the 90% one-sided bound with the answer."""
    pump = _ok(client.post("/api/maintenance/positions", json={"name": "Lone pump"}))["id"]
    _ok(client.post(f"/api/maintenance/positions/{pump}/models", json={"model_id": "sample-model-bearings-lognormal"}))
    _ok(client.post(f"/api/maintenance/positions/{pump}/models", json={"model_id": SAMPLE}))
    listed = _ok(client.get("/api/maintenance/position-missions"))
    links = _ok(client.get(f"/api/maintenance/position-models?position_ids={pump}"))["links"]
    weibull = next(x for x in links if x["model_id"] == SAMPLE)
    assert weibull["id"] in listed["flyable"]
    made = _ok(client.post(f"/api/maintenance/positions/{pump}/missions", json={"name": "Shift", "link_id": weibull["id"]}))
    rid = made["rbd"]["id"]
    assert made["mission"]["simple"] is True
    full = _ok(client.get(f"/api/rbds/{rid}/missions/mission"))
    assert full["summary"]["start"] == {"new": True} and full["age_now"]["reason"].startswith("nothing is fitted")
    _ok(client.put(f"/api/rbds/{rid}/missions/mission", json={"phases": [{"name": "Mission", "duration": 200}],
                                                               "start": {"age": 500}}))
    got = _ok(client.post(f"/api/rbds/{rid}/missions/mission/calculate", json={}))
    assert got["start"] == {"basis": "age", "age": 500.0}
    assert got["lower_bound"]["side"] == "lower" and got["lower_bound"]["lower"] < got["reliability"]
    new = _ok(client.post(f"/api/rbds/{rid}/missions/mission/calculate", json={"start": "new"}))
    assert new["start"]["basis"] == "new" and new["reliability"] > got["reliability"]
    # The row keeps the saved start's result (from 500 h), not the unsaved one.
    row = next(x for x in _ok(client.get("/api/maintenance/position-missions"))["links"] if x["rbd"] and x["rbd"]["id"] == rid)
    assert row["missions"][0]["result"]["reliability"] == pytest.approx(got["reliability"])
    assert row["missions"][0]["result"]["lower_bound"] == got["lower_bound"]
