"""Missions on RePyability's ``PhasedMission.from_diagram`` (A18, 16 Nov 2026).

Missions without a block on standby give the numbers they gave before (pinned here from the old
engine); missions with standby use true standby (called on when needed, with a start chance) and
come out lower than the old stand-in, as hand calculations say. Exact answers are free; a mission
only a simulation can work out (standby without constant rates) needs Pro.
"""

import math

import pytest

from backend.services import rbd_graph, rbd_phases, rbd_standby
from backend.tests.test_mcp import _call, _ok, env  # noqa: F401 - env is a fixture
from backend.tests.test_mcp import A as MCP_A
from backend.tests.test_rbd_missions import _aircraft, _compact, _e, _exp, _io, _node, _wb

e = math.exp


def _pumps(phases, model=None, valve=None):
    """Duty and standby pumps in parallel, then a valve in series."""
    m = model or _exp(0.001)
    return {"nodes": _io() + [_node("a", label="Pump A", model=m), _node("b", label="Pump B", model=m),
                              _node("v", label="Valve", model=valve or _wb(5000, 1.5))],
            "edges": [_e("input", "a"), _e("input", "b"), _e("a", "v"), _e("b", "v"), _e("v", "output")],
            "unit": "Hours", "phases": phases}


# The old engine's figures (app dev b57df011, before A18), to the last digit: missions with no
# block on standby must give exactly these.
UNCHANGED = [
    (_aircraft(), None, 0.8969017093658305, [0.0019989993341666, 0.002373814276615257, 0.09872547702338791]),
    (_aircraft(phases=[{"name": "Take-off", "duration": 0.1, "votes": {"k1": 2}, "guaranteed": ["gear"]},
                       {"name": "Cruise", "duration": 5, "not_needed": ["gear"]},
                       {"name": "Landing", "duration": 0.2, "votes": {"k1": 2}}]), None,
     0.8969026062679881, [0.0019980013326669336, 0.00237381665043072, 0.09872557574891429]),
    (_pumps([{"name": "Start", "duration": 10}, {"name": "Duty", "duration": 500, "not_needed": ["v"]}]), None,
     0.8403210534901279, [0.0001884356726857407, 0.1594905108371862]),
    (_pumps([{"name": "Start", "duration": 10}, {"name": "Duty", "duration": 500}], model=_wb(3000, 2)),
     {"a": {"age": 400}}, 0.9659759658382996, [8.944871377108534e-05, 0.0339345854479293]),
    (_pumps([{"name": "Start", "duration": 10, "guaranteed": ["a"]}, {"name": "Duty", "duration": 500}],
            model=_wb(3000, 2)), None, 0.9671635334040655, [8.943871921924588e-05, 0.03274702787671529]),
    (_pumps([{"name": "Start", "duration": 10}, {"name": "Duty", "duration": 500}]), {"b": {"failed": True}},
     0.5812489156549108, [0.0100387150399257, 0.40871236930516347]),
]


@pytest.mark.parametrize("graph,state,reliability,failing", UNCHANGED)
def test_missions_without_standby_give_the_same_numbers(graph, state, reliability, failing):
    got = rbd_phases.analyze_phases(graph, current_state=state, weakest=True)
    assert got["method"] == "exact"
    assert got["reliability"] == pytest.approx(reliability, rel=1e-12, abs=1e-15)
    assert [p["failure_probability"] for p in got["phases"]] == pytest.approx(failing, rel=1e-9, abs=1e-15)
    # One whole-mission curve, ending at the mission's reliability.
    assert got["curve"]["t"][0] == 0 and got["curve"]["t"][-1] == pytest.approx(got["duration"])
    assert got["curve"]["reliability"][-1] == pytest.approx(reliability, rel=1e-9)


# The fixture for What's new: duty and standby pumps (1,000 h mean life each) and a valve (5,000 h),
# all exponential: 10 h start-up with both running, then 500 h duty with Pump B on cold standby.
WHATS_NEW = {"nodes": _io() + [_node("a", label="Pump A", model=_exp(0.001)),
                               _node("b", label="Pump B", model=_exp(0.001)),
                               _node("v", label="Valve", model=_exp(0.0002))],
             "edges": [_e("input", "a"), _e("input", "b"), _e("a", "v"), _e("b", "v"), _e("v", "output")],
             "unit": "Hours",
             "phases": [{"name": "Start-up", "duration": 10}, {"name": "Duty", "duration": 500, "standby": ["b"]}]}


def test_standby_matches_the_hand_calculation_and_is_lower_than_the_stand_in():
    one = {**WHATS_NEW, "phases": [{"name": "Duty", "duration": 500, "standby": ["b"]}]}
    got = rbd_phases.analyze_phases(one)
    # Cold standby of two 0.001/h pumps for 500 h: e^-0.5 (1 + 0.5); the valve e^-0.1.
    assert got["method"] == "exact"
    assert got["reliability"] == pytest.approx(e(-0.5) * 1.5 * e(-0.1), rel=1e-12)
    # The old stand-in: Pump B's clock stopped, so the pair never failed: the valve alone.
    assert got["reliability"] < e(-0.1)
    # With a 90% start chance: e^-0.5 (1 + 0.9 × 0.5).
    may = {**one, "phases": [{**one["phases"][0], "start_probability": {"b": 0.9}}]}
    assert rbd_phases.analyze_phases(may)["reliability"] == pytest.approx(e(-0.5) * 1.45 * e(-0.1), rel=1e-12)
    # Warm, ageing at 20% while idle: e^-λt + (1/0.2)(e^-λt − e^-1.2λt).
    warm = {**one, "phases": [{**one["phases"][0], "dormancy": {"b": 0.2}}]}
    hand = (e(-0.5) + 5 * (e(-0.5) - e(-0.6))) * e(-0.1)
    assert rbd_phases.analyze_phases(warm)["reliability"] == pytest.approx(hand, rel=1e-12)


def test_the_whats_new_fixture_before_and_after():
    got = rbd_phases.analyze_phases(WHATS_NEW, weakest=True)
    assert got["method"] == "exact"
    assert got["reliability"] == pytest.approx(0.816096, abs=5e-7)  # was 0.899440 (89.9% -> 81.6%)
    # Pump B on standby now drives Duty's failures alongside the valve.
    duty = got["phases"][1]
    assert {d["label"] for d in duty["drivers"]} >= {"Pump B", "Valve"}
    assert duty["weakest"] == duty["drivers"][0]


def test_matches_repyability_called_directly():
    from repyability import BlockSetting, MissionPhase, NonRepairableRBD, PhasedMission
    import surpyval as surv

    pump, valve = surv.Exponential.from_params([0.001]), surv.Exponential.from_params([0.0002])
    rbd = NonRepairableRBD([("input", "a"), ("input", "b"), ("a", "v"), ("b", "v"), ("v", "output")],
                           {"a": pump, "b": pump, "v": valve}, input_node="input", output_node="output")
    direct = PhasedMission.from_diagram(rbd, [MissionPhase("Start-up", 10.0),
                                              MissionPhase("Duty", 500.0, blocks={"b": BlockSetting(state="standby")})])
    got = rbd_phases.analyze_phases(WHATS_NEW)
    assert got["reliability"] == pytest.approx(direct.reliability(), rel=1e-12)


def test_a_life_model_per_phase():
    # One block at 0.01/h for 10 h, then on a phase model of 0.03/h for 20 h: e^-(0.1 + 0.6).
    g = {"nodes": _io() + [_node("a", model=_exp(0.01))], "edges": [_e("input", "a"), _e("a", "output")],
         "phases": [{"name": "Cruise", "duration": 10}, {"name": "Climb", "duration": 20, "models": {"a": _exp(0.03)}}]}
    got = rbd_phases.analyze_phases(g)
    assert got["reliability"] == pytest.approx(e(-0.7), rel=1e-12)
    assert rbd_phases.MODEL_NOTE in got["notes"] and got["phases"][1]["own_models"] == ["A"]
    # A Weibull's age is carried in and out: 10 h on W(100, 2), then 20 h on W(50, 2) from age 10.
    w = {**g, "nodes": _io() + [_node("a", model=_wb(100, 2))],
         "phases": [{"name": "Cruise", "duration": 10}, {"name": "Climb", "duration": 20, "models": {"a": _wb(50, 2)}}]}
    hand = e(-(10 / 100) ** 2) * e(-((30 / 50) ** 2 - (10 / 50) ** 2))
    assert rbd_phases.analyze_phases(w)["reliability"] == pytest.approx(hand, rel=1e-9)
    with pytest.raises(rbd_phases.PhaseError, match="distribution with its parameters"):
        rbd_phases.parse_phases([{"name": "x", "duration": 1, "models": {"a": {"model_id": "m1"}}}])


def test_simulated_missions_need_pro_and_are_seeded():
    g = _pumps([{"name": "Start", "duration": 10}, {"name": "Duty", "duration": 500, "standby": ["b"]}],
               model=_wb(3000, 2))
    with pytest.raises(rbd_standby.SimulationNeedsPro) as err:
        rbd_phases.analyze_phases(g)
    assert str(err.value) == rbd_phases.MISSION_PRO_MESSAGE
    with rbd_standby.simulation("run"):
        one = rbd_phases.analyze_phases(g, weakest=True)
        two = rbd_phases.analyze_phases(g, weakest=True)
    assert one["method"] == "simulated" and one["reliability"] == two["reliability"]
    assert one["interval"]["confidence"] == pytest.approx(0.9)
    assert len(one["curve"]["lower"]) == len(one["curve"]["t"])
    assert one["phases"][1]["drivers"] and one["drivers_note"]
    # Lower than the old stand-in's 0.967948 (B paused through Duty).
    assert one["reliability"] < 0.9679483949429663


def test_the_new_settings_round_trip_through_save_and_json():
    from backend.services import rbd_json
    from backend.services.rbd_import import import_file

    g = rbd_graph.normalize_graph({**WHATS_NEW, "phases": [
        {"name": "Start-up", "duration": 10, "models": {"a": _exp(0.002)}},
        {"name": "Duty", "duration": 500, "standby": ["b"], "dormancy": {"b": 0.1}, "start_probability": {"b": 0.95}}]})
    assert g["phases"][1]["start_probability"] == {"b": 0.95}
    assert g["phases"][0]["models"]["a"]["distribution_id"] == "exponential"
    back = rbd_graph.normalize_graph(import_file(rbd_json.to_json(rbd_json.to_document(g, "Pumps")).encode(),
                                                 "x.json")[0].graph)
    assert back["phases"] == g["phases"]


def test_a_kept_standby_result_from_the_old_engine_no_longer_holds():
    from backend.services import rbd_missions

    plain = [{"name": "Duty", "duration": 500}]
    standby = [{"name": "Duty", "duration": 500, "standby": ["b"]}]
    # The signature moves for missions with standby only, so their lists don't show the old figure.
    assert rbd_missions.signature(WHATS_NEW, standby) != rbd_missions.signature(
        WHATS_NEW, [{**standby[0], "standby": []}])
    assert "standby" not in str(rbd_missions.signature(WHATS_NEW, plain))


def test_api_mission_needing_a_simulation_is_402_without_pro(monkeypatch):
    import mongomock
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app
    from backend.services import billing

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(db, "_db", mongomock.MongoClient()["reliafy_test_a18"])
    monkeypatch.setattr(db, "_simulated", True)
    app.dependency_overrides[get_current_user] = lambda: {"uid": "u-a18", "email": "a18@example.org"}
    g = _pumps([{"name": "Duty", "duration": 500, "standby": ["b"]}], model=_wb(3000, 2))
    try:
        client = TestClient(app)
        monkeypatch.setattr(billing, "premium_compute_allowed", lambda db_, user: False)
        r = client.post("/api/rbds/phases", json={"graph": g})
        assert r.status_code == 402 and r.json()["code"] == "pro_required"
        assert "simulations are part of Pro" in r.json()["detail"]
        rid = client.post("/api/rbds", json={"name": "Pumps", "graph": g}).json()["id"]
        r = client.post(f"/api/rbds/{rid}/missions/mission/calculate", json={})
        assert r.status_code == 402
        # Exact (exponential spares) stays free.
        exact = client.post("/api/rbds/phases", json={"graph": WHATS_NEW})
        assert exact.status_code == 200 and exact.json()["method"] == "exact"
        monkeypatch.setattr(billing, "premium_compute_allowed", lambda db_, user: True)
        r = client.post("/api/rbds/phases", json={"graph": g})
        assert r.status_code == 200 and r.json()["method"] == "simulated"
    finally:
        app.dependency_overrides.clear()


def test_mcp_mission_paths_route_free_and_pro(env, monkeypatch):
    from backend.services import billing

    g = _pumps([{"name": "Duty", "duration": 500, "standby": ["b"]}], model=_wb(3000, 2))
    compact = _compact({k: v for k, v in g.items() if k != "phases"})
    out = _ok(_call(env.token[MCP_A], "change", {"action": "rbd_create", "name": "Standby pumps", "unit": "Hours",
                                                  "nodes": compact["nodes"], "edges": compact["edges"],
                                                  "phases": g["phases"]}))
    args = {"action": "rbd_mission", "rbd_id": out["id"], "mission_id": "mission"}
    monkeypatch.setattr(billing, "premium_compute_allowed", lambda db_, user: False)
    free = _ok(_call(env.token[MCP_A], "analyse", args))["result"]
    assert free["code"] == "pro_required" and free["available"] is False
    listed = _ok(_call(env.token[MCP_A], "analyse", {"action": "rbd_mission", "rbd_id": out["id"]}))
    assert listed["missions"][0]["code"] == "pro_required"
    whole = _ok(_call(env.token[MCP_A], "analyse", {"action": "rbd", "rbd_id": out["id"]}))
    assert whole["phased_mission"]["code"] == "pro_required"
    monkeypatch.setattr(billing, "premium_compute_allowed", lambda db_, user: True)
    pro = _ok(_call(env.token[MCP_A], "analyse", args))["result"]
    assert pro["method"] == "simulated" and pro["interval"]["n_samples"] == rbd_phases.SIM_MISSIONS
    with rbd_standby.simulation("run"):
        assert pro["mission_reliability"] == rbd_phases.analyze_phases(g)["reliability"]  # seeded


def test_mcp_saves_start_chance_and_phase_models(env):
    compact = _compact({k: v for k, v in WHATS_NEW.items() if k != "phases"})
    out = _ok(_call(env.token[MCP_A], "change", {"action": "rbd_create", "name": "Pumps", "unit": "Hours",
                                                  "nodes": compact["nodes"], "edges": compact["edges"]}))
    phases = [{"name": "Start-up", "duration": 10, "models": {"a": _exp(0.002)}},
              {"name": "Duty", "duration": 500, "standby": ["b"], "start_probability": {"b": 0.9}}]
    _ok(_call(env.token[MCP_A], "change", {"action": "rbd_mission", "rbd_id": out["id"], "name": "Duty",
                                            "phases": phases}))
    listed = _ok(_call(env.token[MCP_A], "analyse", {"action": "rbd_mission", "rbd_id": out["id"]}))
    mid = listed["missions"][0]["id"]
    got = _ok(_call(env.token[MCP_A], "analyse", {"action": "rbd_mission", "rbd_id": out["id"], "mission_id": mid}))
    assert got["phases"][1]["start_probability"] == {"b": 0.9}
    assert got["phases"][0]["models"]["a"]["distribution_id"] == "exponential"
    direct = rbd_phases.analyze_phases({**WHATS_NEW, "phases": phases})
    assert got["result"]["method"] == "exact"
    assert got["result"]["mission_reliability"] == pytest.approx(direct["reliability"], rel=1e-12)
