"""Missions on an RBD (rbd_missions.py): named phased missions over one diagram, each phase with
its own duration, blocks it doesn't need, vote counts and Use / Environment covariate values. The
blocks age across the whole mission (one life through every phase, not a fresh start per phase);
a block whose covariates change by phase carries its age into the next. A phase missing a value
waits rather than guessing."""

import math

import mongomock
import numpy as np
import pytest

from backend.library import service as library
from backend.services import covariate_binding as cb
from backend.services import rbd_missions as rm
from backend.services import rbd_phases
from backend.services.rbd_analysis import AnalysisError
from backend.services.rbd_graph import GraphError, normalize_graph

OWNERS = ["org-missions", "__samples__"]
BEARING = "nswc-11:bearing-rolling-load-rating"
ALT = "sample-alt-seal"
PH = "sample-model-pump-load-weibull-ph"


@pytest.fixture(scope="module")
def db():
    from backend.services import samples

    d = mongomock.MongoClient()["rbd_missions"]
    samples.seed_samples(d)
    return d


def _weibull(alpha, beta):
    return {"distribution_id": "weibull", "params": [{"name": "alpha", "value": alpha}, {"name": "beta", "value": beta}]}


def _sf(alpha, beta, t):
    return math.exp(-((t / alpha) ** beta))


def _node(nid, label, model=None, **data):
    return {"id": nid, "type": "component", "data": {"label": label, **({"model": model} if model else {}), **data}}


IO = [{"id": "input", "type": "input", "data": {}}, {"id": "output", "type": "output", "data": {}}]


def _two_motors():
    """Motors A and B into a vote node (1 of 2 drawn), then a controller C in series."""
    nodes = [*IO, _node("a", "Motor A", _weibull(100, 2)), _node("b", "Motor B", _weibull(150, 1.5)),
             {"id": "k1", "type": "knode", "data": {"label": "Motors", "n": 1}}, _node("c", "Controller", _weibull(400, 1))]
    edges = [("input", "a"), ("input", "b"), ("a", "k1"), ("b", "k1"), ("k1", "c"), ("c", "output")]
    return {"unit": "hours", "nodes": nodes, "edges": [{"source": s, "target": t} for s, t in edges]}


# ---- the stored shape ------------------------------------------------------------------------

def test_missions_are_saved_renamed_and_deleted_on_the_rbd():
    g = _two_motors()
    g, one = rm.save(g, name="Corridor inspection", phases=[{"name": "Take-off", "duration": 0.1}])
    g, two = rm.save(g, name="Survey grid")
    assert [m["name"] for m in rm.missions_of(g)] == ["Corridor inspection", "Survey grid"]
    assert two["phases"] == [] and one["id"] != two["id"] and len(one["id"]) == 8
    g, _ = rm.save(g, two["id"], phases=[{"name": "Grid", "duration": "2", "values": {"Air temperature": "35"},
                                          "block_values": {"a": {"temp_C": 50}}}])
    phase = rm.find(g, two["id"])["phases"][0]
    assert phase == {"name": "Grid", "duration": 2.0, "values": {"Air temperature": 35.0},
                     "block_values": {"a": {"temp_C": 50.0}}}
    with pytest.raises(rm.MissionError, match="already a mission named"):
        rm.save(g, two["id"], name="corridor inspection")
    g, _ = rm.save(g, two["id"], name="Grid survey")
    # Normalising the diagram (every save, validate, analyse) keeps them.
    norm = normalize_graph(g)
    assert [m["name"] for m in norm["missions"]] == ["Corridor inspection", "Grid survey"]
    g = rm.remove(g, one["id"])
    assert [m["name"] for m in rm.missions_of(g)] == ["Grid survey"]
    with pytest.raises(rm.MissionError, match="isn't on this diagram"):
        rm.remove(g, one["id"])
    with pytest.raises(GraphError, match="two missions are named"):
        normalize_graph({**g, "missions": [{"id": "x1", "name": "A"}, {"id": "x2", "name": "a"}]})
    with pytest.raises(rm.MissionError, match="non-repairable"):
        rm.save({**g, "repairable": True}, name="No")


def test_a_diagram_s_own_phases_read_as_one_mission_and_stay_where_they_are():
    g = {**_two_motors(), "phases": [{"name": "Take-off", "duration": 0.1}, {"name": "Cruise", "duration": 5}]}
    [own] = rm.missions_of(g)
    assert own["id"] == rm.LEGACY_ID and own["name"] == "Mission" and own["own"]
    g2, _ = rm.save(g, rm.LEGACY_ID, name="Delivery run", phases=[{"name": "Cruise", "duration": 4}])
    assert g2["phases"] == [{"name": "Cruise", "duration": 4.0}] and g2["mission_name"] == "Delivery run"
    assert "missions" not in g2
    g3, _ = rm.save(g2, name="Survey")
    assert [m["name"] for m in rm.missions_of(g3)] == ["Delivery run", "Survey"]
    assert rm.missions_of(rm.remove(g3, rm.LEGACY_ID))[0]["name"] == "Survey"


def test_summary_keeps_a_result_only_while_it_still_holds():
    g, m = rm.save(_two_motors(), name="M", phases=[{"name": "P", "duration": 1}])
    rec = rm.result_record(g, m["phases"], {"reliability": 0.9, "method": "exact"})
    s = rm.summary(g, m, {m["id"]: rec})
    assert s["result"]["reliability"] == 0.9 and s["phases"] == 1 and s["duration"] == 1.0
    g2, m2 = rm.save(g, m["id"], phases=[{"name": "P", "duration": 2}])
    assert "result" not in rm.summary(g2, m2, {m["id"]: rec})


def test_summary_carries_each_phase_s_own_length_beside_its_name():
    phases = [{"name": "Take-off", "duration": 0.1}, {"name": "Cruise", "duration": 5}, {"name": "Hold", "duration": 0}]
    g, m = rm.save({**_two_motors(), "unit": "Hours"}, name="Delivery run", phases=phases)
    s = rm.summary(g, m)
    assert s["phase_names"] == ["Take-off", "Cruise", "Hold"]
    assert s["phase_durations"] == [0.1, 5.0, 0.0]           # one per phase, in the phases' order
    assert s["duration"] == pytest.approx(sum(s["phase_durations"])) and s["unit"] == "Hours"
    assert rm.summary(g, {"id": "x", "name": "Empty", "phases": []})["phase_durations"] == []
    # The diagram's own phases (the mission kept on the RBD itself) read the same way.
    own = {**_two_motors(), "phases": [{"name": "Take-off", "duration": 0.1}, {"name": "Cruise", "duration": 5}]}
    assert rm.summary(own, rm.missions_of(own)[0])["phase_durations"] == [0.1, 5.0]


# ---- ageing across phases, blocks not needed, vote overrides ---------------------------------

def test_blocks_age_across_the_whole_mission_with_a_vote_override(db):
    """Both motors needed on take-off (2 of 2 for 10 h), either one in cruise (1 of 2 for 20 h),
    the controller throughout. By hand, with each motor's life carried from take-off into cruise:
    R = Ra(10)·Rb(10)·Rc(30) − (Ra(10) − Ra(30))·(Rb(10) − Rb(30))·Rc(30)."""
    g = _two_motors()
    phases = [{"name": "Take-off", "duration": 10, "votes": {"k1": 2}}, {"name": "Cruise", "duration": 20}]
    out = rm.analyze(db, OWNERS, g, phases)
    ra10, ra30 = _sf(100, 2, 10), _sf(100, 2, 30)
    rb10, rb30 = _sf(150, 1.5, 10), _sf(150, 1.5, 30)
    rc30 = _sf(400, 1, 30)
    hand = (ra10 * rb10 - (ra10 - ra30) * (rb10 - rb30)) * rc30
    assert out["method"] == "exact" and out["reliability"] == pytest.approx(hand, rel=1e-9)
    # A fresh start per phase would be a different (wrong) answer.
    fresh = ra10 * rb10 * _sf(400, 1, 10) * (1 - (1 - _sf(100, 2, 20)) * (1 - _sf(150, 1.5, 20))) * _sf(400, 1, 20)
    assert abs(out["reliability"] - fresh) > 1e-3
    take_off, cruise = out["phases"]
    assert take_off["reliability_at_end"] == pytest.approx(ra10 * rb10 * _sf(400, 1, 10), rel=1e-9)
    # The weakest block per phase: on take-off a motor; failures it removes add up.
    assert take_off["weakest"]["label"] in ("Motor A", "Motor B", "Controller")
    assert cruise["weakest"]["part"] > 0 and 0 < cruise["weakest"]["share"] <= 1


def test_a_block_not_needed_still_ages_and_its_failure_counts_later(db):
    """The controller isn't needed in phase 1 (10 h) but is in phase 2 (20 h), motors 1 of 2."""
    g = _two_motors()
    phases = [{"name": "Warm-up", "duration": 10, "not_needed": ["c"]}, {"name": "Run", "duration": 20}]
    out = rm.analyze(db, OWNERS, g, phases)
    ra30, rb30 = _sf(100, 2, 30), _sf(150, 1.5, 30)
    ra10, rb10 = _sf(100, 2, 10), _sf(150, 1.5, 10)
    p1 = 1 - (1 - ra10) * (1 - rb10)
    both = 1 - (1 - ra30) * (1 - rb30)  # a motor working at 30 h was working at 10 h too
    assert out["phases"][0]["reliability_at_end"] == pytest.approx(p1, rel=1e-9)
    assert out["reliability"] == pytest.approx(both * _sf(400, 1, 30), rel=1e-9)


def test_the_diagram_s_own_phases_still_work_as_before(db):
    g = {**_two_motors(), "phases": [{"name": "Take-off", "duration": 10, "votes": {"k1": 2}},
                                     {"name": "Cruise", "duration": 20}]}
    via_endpoint = rbd_phases.analyze_for_owner(db, g, OWNERS)
    assert via_endpoint["reliability"] == pytest.approx(rm.analyze(db, OWNERS, g, g["phases"])["reliability"])
    assert rbd_phases.agent_summary(via_endpoint)["mission_reliability"] == via_endpoint["reliability"]


# ---- covariates per phase ----------------------------------------------------------------------

def _bearing(nid, label, rating):
    return _node(nid, label, {"kind": "bound", "binding": {"source": "nswc", "ref": BEARING,
                                                            "fixed": {"L_S": rating, "X": 1.0, "Y": 0, "R": 50}}})


def _gearbox():
    nodes = [*IO, _bearing("i", "Input bearing", 5000), _bearing("o", "Output bearing", 8000)]
    edges = [("input", "i"), ("i", "o"), ("o", "output")]
    return {"unit": "hours", "nodes": nodes, "edges": [{"source": s, "target": t} for s, t in edges]}


def _rate(rating, **values):
    got = library.evaluate(BEARING, {"L_S": rating, "X": 1.0, "Y": 0, "R": 50, **values})["result"]["total"]
    return got / 1e6


def _inputs(b):
    return cb.inputs_of(b)


def test_a_phase_lists_every_open_covariate_with_the_blocks_it_feeds():
    rows = rm.gather(_gearbox(), _inputs)["rows"]
    names = [(r["role"], r["name"]) for r in rows]
    # Use first, then Environment; design covariates (fixed at the position) never appear.
    assert ("use", "Radial load") in names and ("environment", "Bearing operating temperature") in names
    assert names.index(("use", "Radial load")) < names.index(("environment", "Bearing operating temperature"))
    assert not any(r["name"].startswith("Dynamic load rating") for r in rows)
    radial = next(r for r in rows if r["name"] == "Radial load")
    assert radial["unit"] == "lbf" and [b["label"] for b in radial["blocks"]] == ["Input bearing", "Output bearing"]
    # One phase: a value set once reaches both; a block's own for the phase shows as an override.
    phase = {"name": "Climb", "duration": 1, "values": {"Radial load": 1000},
             "block_values": {"o": {"F_R": 1500}}}
    shown = {r["name"]: r for r in rm.phase_rows(rows, phase)}
    rad = shown["Radial load"]
    assert rad["value"] == 1000 and [b["source"] for b in rad["blocks"]] == ["phase", "override"]
    assert [b["used"] for b in rad["blocks"]] == [1000, 1500]
    speed = shown["Operating speed"]
    assert speed["missing"] == ["Input bearing", "Output bearing"]
    assert shown["Bearing operating temperature"]["blocks"][0]["source"] == "default"


def test_values_set_once_per_phase_with_a_block_override_age_the_blocks_across_phases(db):
    """Two phases at different speeds and temperatures: each bearing's rate is its phase's, and the
    mission's reliability is exp(−Σ rate × time) over both bearings and both phases."""
    g = _gearbox()
    phases = [
        {"name": "Take-off", "duration": 2, "values": {"Radial load": 1000, "Operating speed": 3600,
                                                        "Bearing operating temperature": 90}},
        {"name": "Cruise", "duration": 10, "values": {"Radial load": 600, "Operating speed": 1800,
                                                      "Bearing operating temperature": 60},
         "block_values": {"o": {"n": 2400}}},
    ]
    out = rm.analyze(db, OWNERS, g, phases)
    h = (_rate(5000, F_R=1000, n=3600, T_O=90) * 2 + _rate(8000, F_R=1000, n=3600, T_O=90) * 2
         + _rate(5000, F_R=600, n=1800, T_O=60) * 10 + _rate(8000, F_R=600, n=2400, T_O=60) * 10)
    assert out["reliability"] == pytest.approx(math.exp(-h), rel=1e-9)
    assert out["phases"][0]["reliability_at_end"] == pytest.approx(
        math.exp(-2 * (_rate(5000, F_R=1000, n=3600, T_O=90) + _rate(8000, F_R=1000, n=3600, T_O=90))), rel=1e-9)
    assert any("carry their age" in n for n in out["notes"])
    assert out["phases"][1]["weakest"]["label"] == "Input bearing"  # the lower load rating


def test_a_missing_value_makes_its_phase_wait_and_says_which_blocks_need_it(db):
    g = _gearbox()
    phases = [{"name": "Take-off", "duration": 2, "values": {"Radial load": 1000, "Operating speed": 3600}},
              {"name": "Cruise", "duration": 10, "values": {"Radial load": 600}}]
    out = rm.analyze(db, OWNERS, g, phases)
    assert out["reliability"] is None and out["through"]["phase"] == "Take-off"
    assert out["through"]["reliability"] == pytest.approx(out["phases"][0]["reliability_at_end"])
    assert out["phases"][1]["waiting"] is True
    [need] = out["needs"]
    assert need["phase"] == "Cruise"
    assert any("Input bearing needs Operating speed (Use, rpm)" in line for line in need["lines"])
    assert any("Output bearing needs Operating speed" in line for line in need["lines"])
    # The diagram's own mission refuses it outright, naming the phase and the blocks.
    with pytest.raises(AnalysisError, match="Cruise: Input bearing needs Operating speed"):
        rbd_phases.analyze_for_owner(db, {**g, "phases": phases}, OWNERS)
    # Nothing set at all: every phase waits.
    none = rm.analyze(db, OWNERS, g, [{"name": "Take-off", "duration": 1}])
    assert none["through"] is None and none["phases"][0]["waiting"] and none["needs"][0]["phase"] == "Take-off"


def test_the_diagram_s_value_holds_in_a_phase_that_doesn_t_set_its_own(db):
    g = {**_gearbox(), "conditions": [{"name": "Operating speed", "role": "use", "unit": "rpm", "value": 1800}]}
    phases = [{"name": "Hover", "duration": 5, "values": {"Radial load": 800}}]
    shown = {r["name"]: r for r in rm.phase_rows(rm.gather(g, _inputs)["rows"], phases[0])}
    assert shown["Operating speed"]["blocks"][0]["source"] == "diagram"
    out = rm.analyze(db, OWNERS, g, phases)
    h = 5 * (_rate(5000, F_R=800, n=1800) + _rate(8000, F_R=800, n=1800))
    assert out["reliability"] == pytest.approx(math.exp(-h), rel=1e-9)


def test_an_alt_block_follows_its_phases_by_cumulative_exposure(db):
    from surpyval import StepSchedule

    from backend.services import alt as alt_service

    g = {"unit": "hours", "nodes": [*IO, _node("s", "Seal", {"kind": "bound", "binding": {
        "source": "alt", "ref": ALT, "fixed": {"load": 0.6}}})],
        "edges": [{"source": "input", "target": "s"}, {"source": "s", "target": "output"}]}
    rows = rm.gather(g, lambda b: cb.inputs_of(b, db, OWNERS))["rows"]
    [temp] = rows
    assert temp["role"] == "environment" and temp["blocks"][0]["label"] == "Seal"
    phases = [{"name": "Cool", "duration": 200, "values": {temp["name"]: 70}},
              {"name": "Hot", "duration": 300, "values": {temp["name"]: 95}}]
    out = rm.analyze(db, OWNERS, g, phases)
    live = alt_service.get_live_model(db, ALT, OWNERS)
    s = StepSchedule.from_changepoints([0.0, 200.0], np.array([[70, 0.6], [95, 0.6]]))
    want = float(live.sf_tvc(np.array([500.0]), s)[0])
    assert out["reliability"] == pytest.approx(want, rel=1e-6)
    assert out["reliability"] < out["phases"][0]["reliability_at_end"]


def test_a_ph_block_takes_its_phases_values_too(db, monkeypatch):
    from backend import db as db_module

    monkeypatch.setattr(db_module, "get_db", lambda: db)  # the PH model refits from its dataset there
    g = {"unit": "hours", "nodes": [*IO, _node("p", "Pump", {"kind": "bound", "binding": {
        "source": "ph", "ref": PH, "roles": {"load_pct": "use"}}})],
        "edges": [{"source": "input", "target": "p"}, {"source": "p", "target": "output"}]}
    rows = rm.gather(g, lambda b: cb.inputs_of(b, db, OWNERS))["rows"]
    assert any(r["name"] == "load_pct" and r["role"] == "use" for r in rows)
    light = rm.analyze(db, OWNERS, g, [{"name": "A", "duration": 300, "values": {"load_pct": 60}},
                                       {"name": "B", "duration": 300, "values": {"load_pct": 60}}])
    mixed = rm.analyze(db, OWNERS, g, [{"name": "A", "duration": 300, "values": {"load_pct": 60}},
                                       {"name": "B", "duration": 300, "values": {"load_pct": 90}}])
    assert math.isfinite(mixed["reliability"]) and mixed["reliability"] != pytest.approx(light["reliability"])
    # The first phase is the same in both: what happens later doesn't change it.
    assert mixed["phases"][0]["reliability_at_end"] == pytest.approx(light["phases"][0]["reliability_at_end"])
    assert mixed["reliability"] < light["reliability"]  # the heavier second phase
    # Past the model's data the value is held at its edge, and the notes say so.
    past = rm.analyze(db, OWNERS, g, [{"name": "A", "duration": 300, "values": {"load_pct": 60}},
                                      {"name": "B", "duration": 300, "values": {"load_pct": 120}}])
    assert any("held at 90%" in n for n in past["notes"])


def test_detail_lists_blocks_votes_and_each_phase_s_covariates(db):
    g, m = rm.save(_gearbox(), name="Survey", phases=[{"name": "Grid", "duration": 3, "values": {"Radial load": 1}}])
    d = rm.detail(db, OWNERS, g, rm.find(g, m["id"]))
    assert [b["label"] for b in d["blocks"]] == ["Input bearing", "Output bearing"]
    assert d["phases"][0]["needs"] == ["Input bearing", "Output bearing"]  # no speed yet
    assert any(r["name"] == "Radial load" for r in d["covariates"])


# ---- over REST: a position's missions, its sub-position's own -----------------------------------

ORG = "org-missions-rest"


@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config
    from backend import db as db_mod
    from backend.auth import get_current_user
    from backend.main import app
    from backend.maintenance.service import PROJECTORS
    from backend.maintenance.store import GraphStore
    from backend.routers import maintenance as router
    from backend.services import samples

    d = mongomock.MongoClient()["rbd_missions_rest"]
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


def test_missions_over_rest_belong_to_their_position_and_are_not_inherited(client):
    drone = _ok(client.post("/api/maintenance/positions", json={"name": "Survey drone"}))["id"]
    gimbal = _ok(client.post("/api/maintenance/positions", json={"name": "Gimbal", "parent_id": drone}))["id"]
    rbd = _ok(client.post("/api/rbds", json={"name": "Drone RBD", "graph": _two_motors()}))["id"]
    small = _ok(client.post("/api/rbds", json={"name": "Gimbal RBD", "graph": _gearbox()}))["id"]
    _ok(client.post(f"/api/maintenance/positions/{drone}/models", json={"rbd_id": rbd}))
    _ok(client.post(f"/api/maintenance/positions/{gimbal}/models", json={"rbd_id": small}))

    made = _ok(client.post(f"/api/rbds/{rbd}/missions", json={"name": "Corridor inspection"}))["mission"]
    assert made["phases"] == 0 and made["name"] == "Corridor inspection"
    mid = made["id"]
    phases = [{"name": "Take-off", "duration": 10, "votes": {"k1": 2}}, {"name": "Cruise", "duration": 20}]
    _ok(client.put(f"/api/rbds/{rbd}/missions/{mid}", json={"phases": phases}))
    _ok(client.post(f"/api/rbds/{small}/missions", json={"name": "Stabilise",
        "phases": [{"name": "Hover", "duration": 1, "values": {"Radial load": 100, "Operating speed": 600}}]}))

    full = _ok(client.get(f"/api/rbds/{rbd}/missions/{mid}"))
    assert [p["name"] for p in full["phases"]] == ["Take-off", "Cruise"]
    assert full["votes"][0]["inputs"] == 2 and full["rbd"]["read_only"] is False
    got = _ok(client.post(f"/api/rbds/{rbd}/missions/{mid}/calculate", json={}))
    assert 0 < got["reliability"] < 1 and [r["name"] for r in got["phases"]] == ["Take-off", "Cruise"]
    # Unsaved phases are worked out without keeping the result.
    trial = _ok(client.post(f"/api/rbds/{rbd}/missions/{mid}/calculate", json={"phases": phases[:1]}))
    assert trial["reliability"] > got["reliability"]

    links = _ok(client.get("/api/maintenance/position-missions"))["links"]
    by_pos = {x["position_id"]: x for x in links}
    assert [m["name"] for m in by_pos[drone]["missions"]] == ["Corridor inspection"]
    assert by_pos[drone]["missions"][0]["result"]["reliability"] == pytest.approx(got["reliability"])
    # The gimbal has its own mission, and the drone's isn't there.
    assert [m["name"] for m in by_pos[gimbal]["missions"]] == ["Stabilise"]

    bad = client.put(f"/api/rbds/{rbd}/missions/{mid}", json={"phases": [{"name": "", "duration": 1}]})
    assert bad.status_code == 422 and "needs a name" in bad.json()["detail"]
    assert client.get(f"/api/rbds/{rbd}/missions/nope").status_code == 404
    _ok(client.delete(f"/api/rbds/{rbd}/missions/{mid}"))
    assert _ok(client.get(f"/api/rbds/{rbd}/missions"))["missions"] == []
