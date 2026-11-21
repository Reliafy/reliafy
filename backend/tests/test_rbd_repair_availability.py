"""Availability with repairs for any block diagram (backend/services/rbd_repair_availability.py).

Every figure is checked against a hand calculation or RePyability built directly: two blocks in
series (A = product of MTBF / (MTBF + MTTR)), a parallel pair (1 - q^2), the same pair drawn as
one block of two units, a cold standby pair (its Markov chain by hand) and the mean availability
over a period (each block's A(t) integrated). The repair times' sources (typed, the block's own,
the outage history, the position's maintainability prediction) are said, a block with none is
asked for and never guessed, and the REST route and the MCP tool give the same answer.
"""

import math

import matplotlib

matplotlib.use("Agg")

import mongomock  # noqa: E402
import numpy as np  # noqa: E402
import pytest  # noqa: E402
from scipy.integrate import quad  # noqa: E402

from backend.services import rbd_repair_availability as rra  # noqa: E402
from backend.services.rbd_analysis import AnalysisError  # noqa: E402


def _exp(rate):
    return {"source": "params", "distribution": "Exponential", "distribution_id": "exponential",
            "params": [{"name": "failure_rate", "value": rate}]}


def _node(nid, ntype="component", **data):
    return {"id": nid, "type": ntype, "position": {"x": 0, "y": 0}, "data": {"label": nid.upper(), **data}}


def _graph(nodes, edges, unit="Hours", **extra):
    return {"unit": unit, "nodes": [_node("input", "input"), _node("output", "output"), *nodes],
            "edges": [{"id": f"{a}-{b}", "source": a, "target": b} for a, b in edges], **extra}


def _series(unit="Hours"):
    """Two blocks in series: MTBF 1,000 h and 500 h."""
    return _graph([_node("a", model=_exp(1 / 1000)), _node("b", model=_exp(1 / 500))],
                  [("input", "a"), ("a", "b"), ("b", "output")], unit=unit)


def _answer(graph, typed=None, **kw):
    return rra.analyse(graph, rra.repair_rows(graph, typed=typed or {}), **kw)


def test_series_matches_the_product_of_each_blocks_availability():
    out = _answer(_series(), {"a": 10, "b": 4}, period=8766)
    hand = (1000 / 1010) * (500 / 504)
    assert out["status"] == "ok"
    assert out["inherent"]["steady_state"] == pytest.approx(hand, rel=1e-9)
    # Shares of the downtime: each block's unavailability over the sum (rare-event; exact
    # criticality here): a 0.0099, b 0.0079.
    shares = {d["id"]: d["share"] for d in out["drivers"]}
    qa, qb = 10 / 1010, 4 / 504
    assert shares["a"] == pytest.approx(qa / (qa + qb), rel=0.01)
    assert out["drivers"][0]["id"] == "a"
    assert out["answer"].startswith("Available ")
    assert "mostly A" in out["answer"]
    assert out["kind_words"] == "inherent: repairs only"
    assert all(r["source"] == "typed" for r in out["repairs"])


def test_the_mean_availability_over_a_period_matches_the_integral_from_new():
    """From new, each exponential block's A(t) = mu/(l+mu) + l/(l+mu) e^-(l+mu)t; the series is
    their product (independent repairs), averaged over the period."""
    period = 2000.0
    out = _answer(_series(), {"a": 10, "b": 4}, period=period)
    blocks = [(1 / 1000, 1 / 10), (1 / 500, 1 / 4)]

    def a_sys(t):
        return np.prod([mu / (lam + mu) + lam / (lam + mu) * math.exp(-(lam + mu) * t) for lam, mu in blocks])

    hand = quad(a_sys, 0, period, limit=200)[0] / period
    assert out["inherent"]["period_availability"] == pytest.approx(hand, rel=1e-6)
    assert out["inherent"]["downtime"] == pytest.approx((1 - hand) * period, rel=1e-4)
    assert out["inherent"]["downtime_hours"] == pytest.approx((1 - hand) * period, rel=1e-4)


def test_a_parallel_pair_and_one_block_of_two_units_agree_with_1_minus_q_squared():
    q = 10 / 1010
    drawn = _graph([_node("a", model=_exp(1e-3)), _node("b", model=_exp(1e-3))],
                   [("input", "a"), ("input", "b"), ("a", "output"), ("b", "output")])
    block = _graph([_node("p", "parallel", model=_exp(1e-3), n=2)], [("input", "p"), ("p", "output")])
    a1 = _answer(drawn, {"a": 10, "b": 10})["inherent"]["steady_state"]
    a2 = _answer(block, {"p": 10})
    assert a1 == pytest.approx(1 - q * q, rel=1e-12)
    assert a2["inherent"]["steady_state"] == pytest.approx(1 - q * q, rel=1e-12)
    assert "Each unit of a block of several is repaired on its own." in a2["notes"]
    assert [d["id"] for d in a2["drivers"]] == ["p"]  # the units roll up to their block


def test_a_parallel_block_feeding_a_vote_counts_once():
    """2-of-3: two single blocks and a block of two units (one input to the vote)."""
    g = _graph([_node("a", model=_exp(1e-3)), _node("b", model=_exp(1e-3)),
                _node("p", "parallel", model=_exp(1e-3), n=2), _node("v", "knode", n=2)],
               [("input", "a"), ("input", "b"), ("input", "p"), ("a", "v"), ("b", "v"), ("p", "v"), ("v", "output")])
    q = 10 / 1010
    qp = q * q  # the pair is down only when both units are
    avail = [1 - q, 1 - q, 1 - qp]
    # 2-of-3 of independent inputs: P(at least two up).
    hand = (avail[0] * avail[1] * avail[2] + (1 - avail[0]) * avail[1] * avail[2]
            + avail[0] * (1 - avail[1]) * avail[2] + avail[0] * avail[1] * (1 - avail[2]))
    out = _answer(g, {"a": 10, "b": 10, "p": 10})
    assert out["inherent"]["steady_state"] == pytest.approx(hand, rel=1e-10)


def test_a_cold_standby_pair_matches_its_markov_chain_and_repyability():
    """One running, one cold spare, each repaired on its own: states 0, 1, 2 down; up 0->1 and
    1->2 at lambda, down 1->0 at mu and 2->1 at 2 mu. P2 = P0 (l/mu)(l/2mu)."""
    from repyability import RepairableRBD
    import surpyval as surv

    lam, mu = 1e-3, 0.1
    g = _graph([_node("s", "standby", model=_exp(lam), spares=1, dormancy=0)], [("input", "s"), ("s", "output")])
    out = _answer(g, {"s": 10})
    r1, r2 = lam / mu, lam / (2 * mu)
    p0 = 1 / (1 + r1 + r1 * r2)
    hand = 1 - p0 * r1 * r2
    assert out["inherent"]["steady_state"] == pytest.approx(hand, rel=1e-9)
    direct = RepairableRBD([("in", "s"), ("s", "out")], {"s": {
        "reliability": surv.Exponential.from_params([lam]), "repairability": surv.Exponential.from_params([mu]),
        "standby": {"units": 2, "k": 1, "dormancy_factor": 0.0, "switching_probability": 1.0}}})
    assert out["inherent"]["steady_state"] == pytest.approx(float(direct.mean_availability()), rel=1e-9)


def test_a_block_with_no_repair_time_is_asked_for_never_guessed():
    out = _answer(_series(), {"a": 10})
    assert out["status"] == "needs_repairs"
    assert out["needs"] == ["B"]
    assert out["inherent"] is None and out["drivers"] == []
    assert "Give B a repair time" in out["answer"]
    assert next(r for r in out["repairs"] if r["id"] == "b")["source"] is None


def test_repair_times_say_where_they_came_from_in_order():
    g = _series(unit="Days")
    g["nodes"][2]["data"]["repair"] = _exp(2.0)  # a: its own model, mean half a day
    recorded = {"b": {"mean": 0.25, "count": 3, "name": "Plant log"}}
    rows = rra.repair_rows(g, recorded=recorded, predictions={"b": {"hours": 9, "name": "Conveyor M", "position": "CV-02"}})
    by = {r["id"]: r for r in rows}
    assert (by["a"]["source"], by["a"]["mttr"]) == ("block", 12.0)  # hours, from 0.5 days
    # Recorded outages come before a prediction: 0.25 days = 6 hours, the mean of 3.
    assert (by["b"]["source"], by["b"]["mttr"]) == ("recorded", 6.0)
    assert "3 repairs in Plant log" in by["b"]["detail"]
    rows = rra.repair_rows(g, predictions={"b": {"hours": 9, "name": "Conveyor M", "position": "CV-02"}})
    b = next(r for r in rows if r["id"] == "b")
    assert (b["source"], b["mttr"], b["source_words"]) == ("prediction", 9.0, "maintainability prediction")
    # A typed time wins over everything.
    rows = rra.repair_rows(g, typed={"a": 3}, recorded=recorded)
    assert next(r for r in rows if r["id"] == "a")["source"] == "typed"


def test_typed_hours_on_a_diagram_in_days():
    """Lives in days, repairs typed in hours: MTBF 100 d and 50 d, MTTR 12 h and 6 h."""
    g = _graph([_node("a", model=_exp(1 / 100)), _node("b", model=_exp(1 / 50))],
               [("input", "a"), ("a", "b"), ("b", "output")], unit="Days")
    out = _answer(g, {"a": 12, "b": 6})
    hand = (100 / 100.5) * (50 / 50.25)
    assert out["repair_unit"] == "hours"
    assert out["inherent"]["steady_state"] == pytest.approx(hand, rel=1e-9)
    assert out["period"]["basis"] == "year" and out["period"]["length"] == pytest.approx(365.25)
    # Downtime over the year, in hours: about (1 - A) x 8,766 h.
    assert out["inherent"]["downtime_hours"] == pytest.approx((1 - hand) * 8766, rel=0.01)


def test_a_missions_length_is_the_default_period():
    g = _series()
    g["phases"] = [{"name": "Run", "duration": 300}, {"name": "Rest", "duration": 200}]
    out = _answer(g, {"a": 10, "b": 4})
    assert out["period"] == {"length": 500.0, "basis": "mission", "words": "the mission (500 hours)"}
    assert any("mission's length" in n for n in out["notes"])


def test_placeholder_lives_are_said_with_the_figure_without_them():
    g = _series()
    g["nodes"][3]["data"]["model"] = {**_exp(1e-3), "placeholder": True}  # b
    out = _answer(g, {"a": 10, "b": 4})
    assert out["placeholders"] == ["B"]
    assert "Not a real figure" in out["answer"]
    assert out["without_placeholders"]["steady_state"] == pytest.approx(1000 / 1010, rel=1e-9)


def test_a_load_sharing_block_is_refused_in_words():
    g = _graph([_node("l", "loadshare", model=_exp(1e-3))], [("input", "l"), ("l", "output")])
    with pytest.raises(AnalysisError, match="shares its load"):
        _answer(g, {"l": 5})


def test_planned_work_gives_the_achieved_figure_beside_the_inherent():
    """A block's own preventive replacement every 200 h taking 5 h: the achieved availability
    counts that downtime too (an exponential life gains nothing from it)."""
    g = _graph([_node("a", model=_exp(1 / 1000), preventive={"interval": 200, "duration": 5})],
               [("input", "a"), ("a", "output")])
    out = _answer(g, {"a": 10})
    assert out["inherent"]["steady_state"] == pytest.approx(1000 / 1010, rel=1e-9)
    assert out["achieved"] is not None
    assert out["achieved"]["steady_state"] < out["inherent"]["steady_state"]
    assert out["kind_words"] == "achieved: repairs and planned work"
    assert "Repairs alone (inherent)" in out["answer"]


# ---- the database side: outage history and maintainability predictions ----------------------

def test_recorded_repairs_are_the_mean_of_the_finished_unplanned_outages():
    from types import SimpleNamespace

    from backend.routers import rbd_repair_availability as route
    from backend.services import outage_logs

    db = mongomock.MongoClient()["reliafy_repair_avail"]
    g = _series()
    rbd = SimpleNamespace(id="r1", owner_id="u1", graph=g)
    text = "asset,start,end,planned\nA,100,110,no\nA,500,504,no\nA,700,720,yes\nB,300,302,no\n"
    parsed = outage_logs.parse_log(text, g, window_start=0, window_end=1000)
    outage_logs.create_log(db, rbd, parsed, "u1", "Plant log")
    got = route.recorded_repairs(db, rbd, g, ["u1"])
    assert got["a"]["count"] == 2 and got["a"]["mean"] == pytest.approx(7.0)  # the planned one left out
    assert got["b"] == {"mean": pytest.approx(2.0), "count": 1, "name": "Plant log"}


def test_a_positions_maintainability_prediction_gives_its_mct():
    from backend.routers import rbd_repair_availability as route
    from backend.services import maintainability

    db = mongomock.MongoClient()["reliafy_repair_avail"]
    db[maintainability.COLLECTION].insert_one({"_id": "m1", "owner_id": "u1", "name": "CV-02 repairs",
                                               "inputs": {"product_id": "pos-cv02"},
                                               "results": {"mct_hours": 6.5}})
    got = route.prediction_repairs(db, {"b": {"id": "pos-cv02", "name": "CV-02"}}, ["u1"])
    assert got == {"b": {"hours": 6.5, "name": "CV-02 repairs", "position": "CV-02"}}
    assert route.prediction_repairs(db, {"b": {"id": "pos-cv02", "name": "CV-02"}}, ["someone-else"]) == {}


# ---- REST and MCP: the same answer -------------------------------------------------------------

def test_rest_and_mcp_give_the_same_answer(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.main import app
    from backend.services import rbds as rbds_service

    monkeypatch.setattr(config, "AUTH_DISABLED", True)
    test_db = mongomock.MongoClient()["reliafy_repair_avail_api"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    client = TestClient(app)
    g = _series()
    r = client.post("/api/rbds/repair-availability", json={"graph": g, "repairs": {"a": 10, "b": 4}})
    assert r.status_code == 200, r.text
    rest = r.json()
    assert rest["inherent"]["steady_state"] == pytest.approx((1000 / 1010) * (500 / 504), rel=1e-9)
    bad = client.post("/api/rbds/repair-availability", json={"graph": g, "repairs": {"a": -1}})
    assert bad.status_code == 422 and "more than 0" in bad.json()["detail"]

    # The MCP tool on the same diagram saved.
    from backend import mcp_server

    saved = rbds_service.save_rbd(test_db, "Line", g, "u-mcp")
    monkeypatch.setattr(mcp_server, "_caller", lambda ctx: {"uid": saved.owner_id, "email": "x@example.org"})
    monkeypatch.setattr(mcp_server, "_owners", lambda uid: [uid])
    out = mcp_server.analyze_rbd(None, saved.id, with_repairs=True, repair_times={"a": 10, "b": 4})
    assert out["rbd_id"] == saved.id
    assert out["inherent"]["steady_state"] == pytest.approx(rest["inherent"]["steady_state"], rel=1e-12)
    assert out["answer"] == rest["answer"]


# ---- a diagram built from the tree: the positions' predictions and tasks -----------------------

def test_a_diagram_built_from_the_tree_reads_its_positions(monkeypatch):
    """Pump A's repair time from its maintainability prediction, Pump B's typed; Pump A's
    fixed-interval task (8 h off-line) gives the achieved figure beside the inherent one."""
    from backend.maintenance import position_models as pm
    from backend.maintenance import rbd_tree_plan as tp
    from backend.maintenance.service import PROJECTORS, Maintenance
    from backend.maintenance.store import GraphStore
    from backend.routers import rbd_repair_availability as route
    from backend.services import maintainability, samples
    from backend.services import rbds as rbds_service

    org, owners = "org-repair-avail", ["org-repair-avail", "__samples__"]
    m = Maintenance(GraphStore(":memory:", PROJECTORS), org, "tester")
    db = mongomock.MongoClient()["reliafy_repair_avail_tree"]
    samples.seed_samples(db)
    plant = m.create_position("Pump station")["id"]
    a = m.create_position("Pump A", parent_id=plant)["id"]
    b = m.create_position("Pump B", parent_id=plant)["id"]
    for p in (a, b):
        pm.link_saved(m, db, owners, set(), p, "model", "sample-model-bearings-weibull")
    link = pm.build_rbd(m, db, owners, set(), plant)
    db[maintainability.COLLECTION].insert_one({"_id": "mp", "owner_id": org, "name": "Pump A repairs",
                                               "inputs": {"product_id": a}, "results": {"mct_hours": 6.0}})
    monkeypatch.setattr(tp, "maintenance_for", lambda ctx: m)
    rbd = rbds_service.get_rbd(db, link["model_id"], owners)
    graph = rbd.graph
    bid = {n["data"]["label"]: n["id"] for n in graph["nodes"] if n.get("type") == "component"}

    first = route.availability_payload(db, object(), graph, rbd, owners)
    assert first["status"] == "needs_repairs" and first["needs"] == ["Pump B"]
    rows = {r["label"]: r for r in first["repairs"]}
    assert rows["Pump A"]["source"] == "prediction" and rows["Pump A"]["mttr"] == 6.0
    assert rows["Pump A"]["position"]["id"] == a
    assert "Pump A repairs" in rows["Pump A"]["detail"]

    out = route.availability_payload(db, object(), graph, rbd, owners, repairs={bid["Pump B"]: 6})
    assert out["status"] == "ok" and out["achieved"] is None
    inherent = out["inherent"]["steady_state"]
    # The same diagram drawn as repairable by hand, each block repaired in 6 h (exponential).
    hand_graph = {**graph, "repairable": True, "nodes": [
        {**n, "data": {**n["data"], "repair": rra.exp_repair(rra._to_diagram(6.0, graph))}}
        if n.get("type") == "component" else n for n in graph["nodes"]]}
    from backend.services import rbd_analysis as ra

    _, resolve = rbds_service.resolvers(db, owners)
    hand = ra.analyze_availability(hand_graph, resolve_model=resolve, simulate=False)["steady_state_availability"]
    assert inherent == pytest.approx(hand, rel=1e-12)

    task = m.create_task(a, "Replace the bearing", 6, "months", outcome="fixed_interval")
    m.set_task_resources(task["id"], {"duration_hours": 8})
    planned = route.availability_payload(db, object(), graph, rbd, owners, repairs={bid["Pump B"]: 6})
    assert planned["achieved"] is not None
    assert planned["inherent"]["steady_state"] == pytest.approx(inherent, rel=1e-12)
    assert planned["kind_words"] == "achieved: repairs and planned work"


def test_a_diagram_only_a_simulation_can_answer_says_so():
    """A cold standby group on a wear-out life has no exact long-run value in RePyability: the
    answer says so and how to get it, with no figure made up."""
    w = {"source": "params", "distribution": "Weibull", "distribution_id": "weibull",
         "params": [{"name": "alpha", "value": 1000}, {"name": "beta", "value": 2}]}
    g = _graph([_node("s", "standby", model=w, spares=1, dormancy=0)], [("input", "s"), ("s", "output")])
    out = _answer(g, {"s": 10})
    assert out["status"] == "simulation_only"
    assert out["inherent"]["steady_state"] is None and out["inherent"]["period_availability"] is None
    assert out["answer"].startswith("Only a simulation can work out this diagram's availability")
    assert "repairable" in out["answer"]
