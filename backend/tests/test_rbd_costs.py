"""Cost of ownership (#99) and scheduled maintenance / proof tests (#100) on
repairable RBDs: block costs, instant repair, preventive maintenance and
hidden failures go into RePyability 0.9's RepairableRBD, and come back as the
exact cost rate and its breakdown, the total cost of ownership, the simulated
cost of the window, the failures/maintenance downtime split, the cheapest
design, and a cost difference in "Compare with…"."""

import copy
import hashlib
import itertools
import json
import math

import matplotlib

matplotlib.use("Agg")

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from backend.services import rbd_analysis as ra  # noqa: E402
from backend.services import rbd_compare, rbd_costs, rbd_export, rbd_maintenance  # noqa: E402
from backend.services import samples  # noqa: E402
from backend.services.rbd_analysis import AnalysisError  # noqa: E402
from backend.services.rbds import availability_cache_key  # noqa: E402
from backend.tests.test_availability_paid import FREE, PRO, client  # noqa: E402,F401 - fixture
from backend.tests.test_rbd_export import WHEN, _run  # noqa: E402

N = 400  # fixed simulation counts keep the suite quick


def _exp(rate):
    return {"source": "params", "distribution": "Exponential", "distribution_id": "exponential",
            "params": [{"name": "lambda", "value": rate}]}


def _w(alpha, beta):
    return {"source": "params", "distribution": "Weibull", "distribution_id": "weibull",
            "params": [{"name": "alpha", "value": alpha}, {"name": "beta", "value": beta}]}


def _ln(mu, sigma):
    return {"source": "params", "distribution": "Lognormal", "distribution_id": "lognormal",
            "params": [{"name": "mu", "value": mu}, {"name": "sigma", "value": sigma}]}


def _node(nid, x=0, y=0, **data):
    return {"id": nid, "type": "component", "position": {"x": x, "y": y},
            "data": {"label": nid.title(), **data}}


def _io():
    return [{"id": "input", "type": "input", "position": {"x": 0, "y": 0}, "data": {"label": "Input"}},
            {"id": "output", "type": "output", "position": {"x": 900, "y": 0}, "data": {"label": "Output"}}]


def _series(*nodes, **graph):
    ids = ["input", *(n["id"] for n in nodes), "output"]
    return {"repairable": True, "unit": "hours", "nodes": [*_io(), *nodes],
            "edges": [{"id": f"e{i}", "source": a, "target": b} for i, (a, b) in enumerate(zip(ids, ids[1:]))],
            **graph}


def _pump(**extra):
    """MTTF 1000 h, MTTR 10 h (both exponential), 500 per repair."""
    return _node("pump", 200, 0, model=_exp(1e-3), repair=_exp(0.1),
                 costs={"repair": 500, **extra.pop("costs", {})}, **extra)


# ---------------------------------------------------------------------------
# Exact cost rate against a hand calculation
# ---------------------------------------------------------------------------
def test_exact_cost_rate_matches_a_hand_calculation():
    """One pump (MTTF 1000, MTTR 10, 500 per repair, 20,000 to buy) with lost
    production at 100/h: it fails 1/1010 times per hour and is down 10/1010 of
    the time, so the rate is (500 + 100·10)/1010 and ten years cost
    20,000 + 87,600 × that."""
    g = _series(_pump(costs={"acquisition": 20000}), costs={"downtime_rate": 100, "horizon": 87600})
    r = ra.analyze_availability(g, n_simulations=N)
    c = r["costs"]
    assert c["cost_rate_basis"] == "exact"
    assert c["cost_rate"] == pytest.approx((500 + 100 * 10) / 1010, rel=1e-12)
    assert c["by_category"]["repair"] == pytest.approx(500 / 1010, rel=1e-12)
    assert c["by_category"]["system_downtime"] == pytest.approx(1000 / 1010, rel=1e-12)
    assert math.fsum(c["by_category"].values()) == pytest.approx(c["cost_rate"], rel=1e-12)
    assert c["acquisition_cost"] == 20000
    assert c["horizon"] == 87600 and c["horizon_basis"] == "set"
    assert c["total_cost"] == pytest.approx(20000 + 87600 * 1500 / 1010, rel=1e-12)
    assert round(c["total_cost"]) == 150099  # RePyability's documented figure
    [block] = c["blocks"]
    assert block["id"] == "pump" and block["rate"] == pytest.approx(500 / 1010)
    assert block["downtime_share"] == pytest.approx(1.0)
    # The window's simulated cost, from the availability simulation itself.
    sim = c["simulated"]
    assert sim["n_simulations"] == N and sim["lower"] <= sim["mean"] <= sim["upper"]
    assert set(sim["percentiles"]) == {"10", "50", "90"}
    assert "downtime" not in r  # nothing maintained


def test_breakdown_by_block_and_category_adds_up():
    """Two blocks in series: per-block repair, replacement and own-downtime
    costs, and the system's lost production, sum to expected_cost_rate."""
    a = _node("a", 200, 0, model=_exp(1e-3), repair=_exp(0.1), costs={"repair": 300, "replace": 200})
    b = _node("b", 400, 0, model=_exp(2e-3), repair=_exp(0.05), costs={"downtime": 40})
    g = _series(a, b, costs={"downtime_rate": 250})
    r = ra.analyze_availability(g, n_simulations=N)
    c = r["costs"]
    ua, ub = 10 / 1010, 20 / 520
    expected = {
        "repair": 300 / 1010, "replace": 200 / 1010, "component_downtime": 40 * ub,
        "system_downtime": 250 * (1 - (1 - ua) * (1 - ub)), "preventive": 0.0, "inspection": 0.0,
    }
    for k, v in expected.items():
        assert c["by_category"][k] == pytest.approx(v, rel=1e-10, abs=1e-15), k
    assert c["cost_rate"] == pytest.approx(sum(expected.values()), rel=1e-10)
    rows = {row["id"]: row for row in c["blocks"]}
    assert rows["a"]["rate"] == pytest.approx(500 / 1010)
    assert rows["b"]["categories"]["component_downtime"] == pytest.approx(40 * ub)
    assert sum(row["cost_share"] for row in c["blocks"]) == pytest.approx(1.0)
    # The horizon defaults to the simulated window.
    assert c["horizon_basis"] == "window" and c["horizon"] == r["t_simulation"]


def test_instant_repair_needs_no_repair_model_and_is_never_down():
    fuse = _node("fuse", model=_exp(0.1), instant_repair=True, costs={"replace": 40})
    g = _series(fuse)
    assert ra.validate_graph(g)["valid"]
    r = ra.analyze_availability(g, n_simulations=N)
    assert r["steady_state_availability"] == 1.0
    assert r["costs"]["cost_rate"] == pytest.approx(4.0)  # 40 × 0.1 failures per hour


# ---------------------------------------------------------------------------
# Maintenance: preventive replacement and proof-tested hidden failures
# ---------------------------------------------------------------------------
def _wearing(preventive=None):
    """A wear-out pump replaced on failure for 5000, down ~23 h, with lost
    production at 500/h (RePyability's costs guide)."""
    extra = {"preventive": preventive} if preventive else {}
    p = _node("p", model=_w(1000, 2.5), repair=_ln(3.0, 0.5), costs={"replace": 5000}, **extra)
    return _series(p, costs={"downtime_rate": 500})


def test_age_replacement_raises_availability_and_lowers_cost():
    run_to_failure = ra.analyze_availability(_wearing(), n_simulations=N)
    instant = ra.analyze_availability(
        _wearing({"policy": "age", "interval": 580, "cost": 1000}), n_simulations=N)
    timed = ra.analyze_availability(
        _wearing({"policy": "age", "interval": 580, "duration": 7, "cost": 1000}), n_simulations=N)
    # Renewing before wear-out avoids failures: more available, cheaper.
    assert instant["steady_state_availability"] > run_to_failure["steady_state_availability"]
    assert instant["costs"]["cost_rate"] < run_to_failure["costs"]["cost_rate"]
    assert run_to_failure["costs"]["cost_rate"] == pytest.approx(18.0, rel=0.01)  # the guide's figure
    assert instant["costs"]["by_category"]["preventive"] > 0
    # A replacement that takes time costs some of that availability back...
    assert timed["steady_state_availability"] < instant["steady_state_availability"]
    split = timed["downtime"]
    assert split["basis"] == "exact" and split["preventive_blocks"] == 1
    assert split["failures"] + split["maintenance"] == pytest.approx(1 - timed["steady_state_availability"])
    # ... all of it planned: the failures' share is the instant-PM downtime.
    assert split["failures"] == pytest.approx(1 - instant["steady_state_availability"], rel=1e-9)
    assert split["maintenance"] > 0 and split["planned_outages_per_window"] > 0
    assert instant["downtime"]["maintenance"] == 0.0


def test_block_replacement_is_simulated_and_labelled_so():
    r = ra.analyze_availability(
        _wearing({"policy": "block", "interval": 580, "duration": 7, "cost": 1000}), n_simulations=N)
    assert r["steady_state_availability"] is None and r["availability_basis"] == "simulation"
    assert r["costs"]["cost_rate_basis"] == "simulation"
    assert r["costs"]["cost_rate"] == pytest.approx(r["costs"]["simulated"]["cost_rate"])
    assert r["downtime"]["basis"] == "simulation"
    assert 0 < r["downtime"]["maintenance"] < r["downtime"]["total"]
    # The default window covers several replacement intervals.
    assert r["t_simulation"] >= 10 * 580


def test_proof_tested_hidden_failure_is_down_half_the_test_interval():
    """A hidden failure lies undetected until the next test: with a constant
    rate λ, tests every τ and instant repair, the channel is down
    1 − (1 − e^(−λτ))/(λτ) ≈ λτ/2 of the time (the PFDavg), and each failure
    about τ/2 on average."""
    lam, tau = 1e-4, 1000.0
    v = _node("valve", model=_exp(lam), instant_repair=True,
              inspection={"interval": tau, "cost": 50}, costs={"downtime": 20})
    r = ra.analyze_availability(_series(v), n_simulations=2000)
    u = 1 - (1 - math.exp(-lam * tau)) / (lam * tau)
    assert r["unavailability"] == pytest.approx(u, rel=1e-9)
    assert r["unavailability"] == pytest.approx(lam * tau / 2, rel=0.05)
    assert r["mean_down_time"] == pytest.approx(tau / 2, rel=0.02)
    # Test cost once per interval, plus the downtime cost of hidden time.
    assert r["costs"]["by_category"]["inspection"] == pytest.approx(50 / tau)
    assert r["costs"]["by_category"]["component_downtime"] == pytest.approx(20 * u)
    # Hidden time is failure downtime, not maintenance.
    assert r["downtime"]["maintenance"] == 0.0 and r["downtime"]["tested_blocks"] == 1
    # The simulation over the window agrees with the exact value.
    p = r["precision"]
    assert p["lower"] - 1e-3 <= 1 - u <= p["upper"] + 1e-3
    assert r["t_simulation"] >= 10 * tau


def test_timed_proof_tests_take_the_channel_offline():
    lam, tau = 1e-4, 1000.0
    v = _node("valve", model=_exp(lam), instant_repair=True, inspection={"interval": tau, "duration": 5})
    r = ra.analyze_availability(_series(v), n_simulations=N)
    assert r["availability_basis"] == "simulation"  # no exact value with timed tests
    split = r["downtime"]
    # Each 5-hour test that takes the working channel off-line (the tests at
    # 1000, 2000, … 9000 h, less those that find it failed) is planned downtime.
    assert 8 < split["planned_outages_per_window"] < 9
    assert split["maintenance"] == pytest.approx(
        split["planned_outages_per_window"] * 5 / r["t_simulation"], rel=0.15)
    assert split["failures"] == pytest.approx(lam * tau / 2, rel=0.25)


# ---------------------------------------------------------------------------
# Validation, graph format, old diagrams, cache key
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("data, needle", [
    ({"costs": {"repair": -5}}, "repair cost must be a non-negative"),
    ({"costs": {"acquisition": "lots"}}, "purchase price must be a number"),
    ({"costs": {"repairs": 5}}, "unknown cost field"),
    ({"preventive": {"policy": "age"}}, "set the preventive-maintenance interval"),
    ({"preventive": {"policy": "sometimes", "interval": 5}}, "age or block"),
    ({"inspection": {"interval": 0}}, "proof-test interval must be a positive"),
    ({"preventive": {"interval": 5}, "inspection": {"interval": 5}}, "not both"),
])
def test_bad_cost_and_maintenance_inputs_are_clear_errors(data, needle):
    g = _series(_node("pump", model=_exp(1e-3), repair=_exp(0.1), **data))
    v = ra.validate_graph(g)
    assert not v["valid"] and any(needle in e for e in v["errors"]), v["errors"]
    with pytest.raises(AnalysisError, match="Pump"):
        ra._build_repairable_rbd(g)


def test_bad_diagram_downtime_cost_is_a_clear_error():
    v = ra.validate_graph(_series(_pump(), costs={"downtime_rate": -1}))
    assert any(e.startswith("The system downtime cost") for e in v["errors"]), v["errors"]


def test_graph_format_carries_costs_and_maintenance():
    from backend.services.rbd_graph import compact_graph, normalize_graph

    compact = {
        "repairable": True, "unit": "hours", "costs": {"downtime_rate": 100},
        "nodes": [
            {"id": "input", "type": "input"}, {"id": "output", "type": "output"},
            {"id": "p", "type": "component", "label": "Pump",
             "model": {"distribution_id": "exponential", "params": [{"name": "lambda", "value": 1e-3}]},
             "instant_repair": True, "costs": {"replace": 40},
             "preventive": {"interval": 500, "duration": {"distribution_id": "weibull",
                                                          "params": [{"name": "alpha", "value": 8},
                                                                     {"name": "beta", "value": 3}]}}},
        ],
        "edges": [{"source": "input", "target": "p"}, {"source": "p", "target": "output"}],
    }
    g = normalize_graph(compact)
    data = g["nodes"][[n["id"] for n in g["nodes"]].index("p")]["data"]
    assert data["instant_repair"] is True and data["costs"] == {"replace": 40}
    assert data["preventive"]["duration"]["distribution"] == "Weibull"
    assert g["costs"] == {"downtime_rate": 100}
    back = compact_graph(g)
    assert back["costs"] == {"downtime_rate": 100}
    p = next(n for n in back["nodes"] if n["id"] == "p")
    assert p["instant_repair"] is True and p["preventive"]["interval"] == 500
    r = ra.analyze_availability(g, n_simulations=N)
    assert r["costs"]["priced"]


def _old_key(graph, t_simulation=None):
    """The cache key as computed before #99 (no diagram-level costs)."""
    nodes = sorted(
        ({"id": n.get("id"), "type": n.get("type"),
          "data": {k: v for k, v in (n.get("data") or {}).items()}} for n in graph["nodes"]),
        key=lambda n: str(n["id"]),
    )
    edges = sorted({(str(e["source"]), str(e["target"])) for e in graph["edges"]})
    payload = {"v": 1, "graph": {"nodes": nodes, "edges": [list(e) for e in edges],
                                 "unit": (graph.get("unit") or "").strip(),
                                 "repairable": bool(graph.get("repairable")),
                                 "ccf_groups": graph.get("ccf_groups") or []},
               "t_simulation": t_simulation}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"),
                                     default=str).encode()).hexdigest()


def _sample():
    s = next(s for s in samples.SAMPLE_RBDS if s["id"] == "sample-rbd-instrument-air-availability")
    return copy.deepcopy(s["graph"])


def test_old_diagrams_build_and_analyse_exactly_as_before():
    from repyability import NonRepairable, RepairableRBD

    g = _sample()
    rbd, labels, gates, working, broken = ra._build_repairable_rbd(g)
    assert rbd.downtime_cost_rate == 0.0 and not rbd.has_costs and not rbd.acquisition_costs
    assert all(isinstance(c, NonRepairable) for c in rbd.components.values())
    # The same components, built the way they were before #99.
    old = RepairableRBD(
        rbd._init_args["edges"],
        {n: (c if n in gates else NonRepairable(c.reliability, c.time_to_replace))
         for n, c in rbd.components.items()},
        k=rbd._init_args["k"], input_node="input", output_node="output",
    )
    ov = {"working_nodes": working | gates, "broken_nodes": broken}
    assert rbd.mean_availability(**ov) == old.mean_availability(**ov)
    new_res = rbd.availability(t_simulation=5000, N=40, method="c", seed=1, antithetic=True, **ov)
    old_res = old.availability(t_simulation=5000, N=40, method="c", seed=1, antithetic=True, **ov)
    assert np.array_equal(new_res.uptimes, old_res.uptimes)
    r = ra.analyze_availability(g, n_simulations=40)
    assert "costs" not in r and "downtime" not in r and r["availability_basis"] == "exact"
    assert ra._availability_horizon(g) == r["t_simulation"]
    # An unpriced diagram keeps its saved-result key.
    assert availability_cache_key(g) == _old_key(g)
    assert availability_cache_key(g, 5000) == _old_key(g, 5000.0)


def test_cache_key_tracks_costs_and_maintenance():
    g = _series(_pump())
    base = availability_cache_key(g)
    priced = copy.deepcopy(g)
    priced["costs"] = {"downtime_rate": 100}
    assert availability_cache_key(priced) != base
    dearer = copy.deepcopy(priced)
    dearer["costs"]["downtime_rate"] = 200
    assert availability_cache_key(dearer) != availability_cache_key(priced)
    horizon = copy.deepcopy(priced)
    horizon["costs"]["horizon"] = 87600
    assert availability_cache_key(horizon) != availability_cache_key(priced)
    for change in ({"costs": {"repair": 600}}, {"instant_repair": True},
                   {"preventive": {"interval": 500}}, {"inspection": {"interval": 500}}):
        other = copy.deepcopy(g)
        other["nodes"][2]["data"].update(change)
        assert availability_cache_key(other) != base, change


# ---------------------------------------------------------------------------
# Download as Python reproduces the costs
# ---------------------------------------------------------------------------
def test_export_reproduces_costs_and_maintenance(tmp_path):
    a = _node("a", 200, 0, model=_w(1000, 2.5), repair=_ln(3.0, 0.5),
              costs={"replace": 5000, "acquisition": 12000},
              preventive={"policy": "age", "interval": 580, "duration": 7, "cost": 1000})
    b = _node("b", 400, 0, model=_exp(1e-4), instant_repair=True,
              inspection={"interval": 1000, "cost": 50}, costs={"downtime": 20})
    g = _series(a, b, costs={"downtime_rate": 500, "horizon": 87600})
    app = ra.analyze_availability(g, n_simulations=60)
    code = rbd_export.to_python(g, "Priced", exported_at=WHEN)
    assert "downtime_cost_rate=500.0" in code and '"repairability": "instant"' in code
    assert "HORIZON = 87600.0" in code
    res, proc = _run(code, tmp_path, n_sims="60")
    assert res["steady_state_availability"] == pytest.approx(app["steady_state_availability"], rel=1e-12)
    c = res["costs"]
    assert c["cost_rate_basis"] == "exact"
    assert c["cost_rate"] == pytest.approx(app["costs"]["cost_rate"], rel=1e-12)
    assert c["total_cost"] == pytest.approx(app["costs"]["total_cost"], rel=1e-12)
    assert c["acquisition_cost"] == 12000
    sim = app["costs"]["simulated"]
    assert c["simulated"]["mean"] == pytest.approx(sim["mean"], rel=1e-12)
    assert c["simulated"]["percentiles"]["90"] == pytest.approx(sim["percentiles"]["90"], rel=1e-12)
    assert "Long-run cost rate (exact)" in proc.stdout


def test_export_runs_block_replacement_to_the_same_precision_target(tmp_path):
    g = _wearing({"policy": "block", "interval": 580, "duration": 7, "cost": 1000})
    app = ra.analyze_availability(g)
    code = rbd_export.to_python(g, "Block", exported_at=WHEN)
    res, proc = _run(code, tmp_path, n_sims="")
    assert res["n_simulations"] == app["n_simulations"]
    assert res["precision"]["window_availability"] == pytest.approx(
        app["precision"]["window_availability"], rel=1e-12)
    assert res["precision"]["tolerance"] == pytest.approx(app["precision"]["tolerance"], rel=1e-12)
    assert res["costs"]["cost_rate_basis"] == "simulation"
    assert res["costs"]["cost_rate"] == pytest.approx(app["costs"]["cost_rate"], rel=1e-12)


def test_unpriced_export_is_unchanged():
    code = rbd_export.to_python(_sample(), "Sample", exported_at=WHEN)
    assert "report_costs" not in code and "HORIZON" not in code and "downtime_cost_rate" not in code


# ---------------------------------------------------------------------------
# Cheapest design (allocate_redundancy), checked by brute force
# ---------------------------------------------------------------------------
def _plant():
    pump = _node("pump", 200, 0, model=_exp(1e-3), repair=_exp(0.1),
                 costs={"repair": 500, "acquisition": 20000})
    valve = _node("valve", 400, 0, model=_exp(5e-4), repair=_exp(0.05),
                  costs={"replace": 800, "acquisition": 6000})
    return _series(pump, valve, costs={"downtime_rate": 100, "horizon": 87600})


def _drawn(graph, units):
    rbd = ra._build_repairable_rbd(rbd_costs.apply_copies(graph, units))[0]
    return rbd.total_cost(87600.0), rbd.mean_availability()


@pytest.mark.parametrize("floor", [None, 0.99995])
def test_cheapest_design_matches_brute_force(floor):
    g = _plant()
    out = rbd_costs.cheapest_design(g, horizon=87600, min_availability=floor)
    best = None
    for n_pump, n_valve in itertools.product(range(1, 5), repeat=2):
        total, avail = _drawn(g, {"pump": n_pump, "valve": n_valve})
        if floor is not None and avail < floor:
            continue
        if best is None or total < best[0]:
            best = (total, {"pump": n_pump, "valve": n_valve}, avail)
    assert out["design"]["units"] == best[1]
    assert out["design"]["total_cost"] == pytest.approx(best[0], rel=1e-9)
    assert out["design"]["availability"] == pytest.approx(best[2], rel=1e-9)
    # The copies drawn on the diagram give the same figures.
    total, avail = _drawn(out["graph"], {})
    assert total == pytest.approx(out["design"]["total_cost"], rel=1e-9)
    assert out["current"]["total_cost"] == pytest.approx(_drawn(g, {})[0], rel=1e-12)
    if floor is None:
        assert out["saving"] >= 0
    else:  # meeting the floor costs more than the design as drawn, which misses it
        assert out["current"]["availability"] < floor and out["saving"] < 0
        assert out["current"]["meets_floor"] is False


def test_one_year_does_not_pay_for_a_second_pump():
    g = _series(_pump(costs={"acquisition": 20000}), costs={"downtime_rate": 100})
    ten = rbd_costs.cheapest_design(g, horizon=87600)
    assert ten["design"]["units"] == {"pump": 2} and round(ten["design"]["total_cost"]) == 127591
    one = rbd_costs.cheapest_design(g, horizon=8760)
    assert one["design"]["units"] == {"pump": 1} and not one["changed"] and one["graph"] is None


def test_applied_copies_join_a_vote_through_a_junction():
    """Copies of a block feeding a 2-out-of-3 vote must not add branches to
    the vote: they join at a junction first."""
    g = {"repairable": True, "unit": "hours", "nodes": [
        *_io(),
        _node("a", 200, -100, model=_exp(1e-3), repair=_exp(0.1), costs={"acquisition": 1}),
        _node("b", 200, 0, model=_exp(1e-3), repair=_exp(0.1)),
        _node("c", 200, 100, model=_exp(1e-3), repair=_exp(0.1)),
        {"id": "vote", "type": "knode", "position": {"x": 400, "y": 0}, "data": {"n": 2, "k": 3}},
    ], "edges": [
        {"source": "input", "target": x} for x in "abc"] + [
        {"source": x, "target": "vote"} for x in "abc"] + [{"source": "vote", "target": "output"}]}
    drawn = rbd_costs.apply_copies(g, {"a": 2})
    ids = {n["id"] for n in drawn["nodes"]}
    assert {"ax1", "aj"} <= ids
    into_vote = sorted(e["source"] for e in drawn["edges"] if e["target"] == "vote")
    assert into_vote == ["aj", "b", "c"]
    # Same as a parallel pair in place of a.
    rbd = ra._build_repairable_rbd(drawn)[0]
    a1 = 10 / 1010
    pa, p = 1 - a1 ** 2, 1 - a1
    two_of_three = pa * p * p + pa * p * (1 - p) * 2 + (1 - pa) * p * p
    gates = {"vote", "aj"}
    assert rbd.mean_availability(working_nodes=gates) == pytest.approx(two_of_three, rel=1e-12)


def test_cheapest_design_needs_prices_and_exact_costs():
    with pytest.raises(AnalysisError, match="purchase price"):
        rbd_costs.cheapest_design(_series(_pump()), horizon=1000)
    block = _wearing({"policy": "block", "interval": 580})
    block["nodes"][2]["data"]["costs"]["acquisition"] = 1000
    with pytest.raises(AnalysisError, match="block replacement"):
        rbd_costs.cheapest_design(block, horizon=1000)
    with pytest.raises(AnalysisError, match="horizon"):
        rbd_costs.cheapest_design(_plant() | {"costs": {"downtime_rate": 100}})


def test_cheapest_design_endpoint_is_paid(client):
    client.act_as(FREE)
    res = client.post("/api/rbds/design/cheapest", json={"graph": _plant()})
    assert res.status_code == 402 and res.json()["code"] == "pro_required"
    client.act_as(PRO)
    res = client.post("/api/rbds/design/cheapest", json={"graph": _plant(), "min_availability": 0.99995})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["design"]["availability"] >= 0.99995 and body["graph"]["nodes"]
    bad = client.post("/api/rbds/design/cheapest", json={"graph": _series(_pump()), "horizon": 100})
    assert bad.status_code == 422 and "purchase price" in bad.json()["detail"]


# ---------------------------------------------------------------------------
# Compare with…: the cost difference
# ---------------------------------------------------------------------------
def test_compare_reports_the_cost_difference_with_its_sign():
    a = _series(_pump(), costs={"downtime_rate": 100})
    dearer = copy.deepcopy(a)
    dearer["nodes"][2]["data"]["costs"]["repair"] = 900  # same failures, dearer repairs
    out = rbd_compare.compare_availability(a, dearer, t_simulation=5000, n_simulations=400)
    d = out["differences"]["cost"]
    assert d["verdict"] == "b_higher" and d["lower"] > 0
    # Same failures (common random numbers): exactly 400 more per failure.
    assert d["exact"] == pytest.approx(400 / 1010, rel=1e-12)
    assert d["estimate"] == pytest.approx(400 / 1010 * 5000, rel=0.15)
    assert out["designs"]["a"]["cost_rate"] == pytest.approx(1500 / 1010)
    assert out["differences"]["availability"]["estimate"] == 0.0
    cheaper = rbd_compare.compare_availability(dearer, a, t_simulation=5000, n_simulations=400)
    assert cheaper["differences"]["cost"]["verdict"] == "a_higher"
    same = rbd_compare.compare_availability(a, copy.deepcopy(a), t_simulation=5000, n_simulations=200)
    assert same["differences"]["cost"]["estimate"] == 0.0


def test_compare_notes_when_only_one_design_is_priced():
    a = _series(_pump())
    bare = copy.deepcopy(a)
    del bare["nodes"][2]["data"]["costs"]
    out = rbd_compare.compare_availability(a, bare, t_simulation=2000, n_simulations=100)
    assert "cost" not in out["differences"] and "Only design A" in out["cost_note"]
    unpriced = rbd_compare.compare_availability(bare, bare, t_simulation=2000, n_simulations=100)
    assert "cost" not in unpriced["differences"] and unpriced["cost_note"] is None


def test_fault_tree_explains_why_block_replacement_has_no_tree():
    from backend.services.rbd_fault_tree import fault_tree

    with pytest.raises(AnalysisError, match="block replacement"):
        fault_tree(_wearing({"policy": "block", "interval": 580}))
    # Age replacement has exact long-run values, so its tree is drawn.
    assert fault_tree(_wearing({"policy": "age", "interval": 580}))["unavailability"] > 0


def test_costs_and_repeats_work_together_in_the_graph_format_and_refusals():
    """#99/#100 fields and #102 copies share the node data: both survive a
    compact round trip, and a priced *repairable* diagram with a copy is still
    refused (RePyability's repairable engine has no repeated nodes)."""
    from backend.services.rbd_analysis import AnalysisError, analyze_availability
    from backend.services.rbd_graph import compact_graph, normalize_graph

    life = {"distribution_id": "exponential", "params": [{"name": "failure_rate", "value": 1e-3}]}
    rep = {"distribution_id": "lognormal", "params": [{"name": "mu", "value": 2.0}, {"name": "sigma", "value": 0.4}]}
    graph = {
        "nodes": [
            {"id": "input", "type": "input"},
            {"id": "psu", "type": "component", "label": "PSU", "model": life, "repair": rep,
             "costs": {"repair": 500, "acquisition": 2000},
             "preventive": {"policy": "age", "interval": 800, "duration": 4, "cost": 100}},
            {"id": "psu2", "type": "component", "label": "PSU", "repeat_of": "psu"},
            {"id": "output", "type": "output"},
        ],
        "edges": [{"source": "input", "target": "psu"}, {"source": "psu", "target": "psu2"},
                  {"source": "psu2", "target": "output"}],
        "unit": "Hours", "repairable": True, "costs": {"downtime_rate": 1000},
    }
    norm = normalize_graph(graph)
    back = {n["id"]: n for n in compact_graph(norm)["nodes"]}
    assert back["psu2"]["repeat_of"] == "psu"
    assert back["psu"]["costs"]["repair"] == 500 and back["psu"]["preventive"]["interval"] == 800
    with pytest.raises(AnalysisError, match="(?i)repeat|more than one place|drawn"):
        analyze_availability(norm)
