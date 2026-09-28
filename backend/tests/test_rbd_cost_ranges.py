"""Costs as ranges (#100): a per-action cost (repair, parts, preventive
replacement, proof test) given as {min, max} goes to RePyability as a uniform
cost distribution, drawn afresh at every action — the exact cost rate takes
its mean, the simulated cost of the window spreads wider, and the
availability is untouched."""

import copy

import matplotlib

matplotlib.use("Agg")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
import surpyval as sp  # noqa: E402

from backend.services import rbd_analysis as ra  # noqa: E402
from backend.services import rbd_costs, rbd_export  # noqa: E402
from backend.services.rbd_analysis import AnalysisError  # noqa: E402
from backend.services.rbds import availability_cache_key  # noqa: E402
from backend.tests.test_rbd_costs import _exp, _ln, _node, _series, _w  # noqa: E402
from backend.tests.test_rbd_export import WHEN, _run  # noqa: E402

N = 400


def _pump(repair):
    """MTTF 1000 h, MTTR 10 h; nothing priced but the repair."""
    return _series(_node("pump", 200, 0, model=_exp(1e-3), repair=_exp(0.1), costs={"repair": repair}))


def test_a_range_keeps_the_exact_rate_at_its_mean_and_widens_the_simulated_spread():
    fixed = ra.analyze_availability(_pump(500), n_simulations=N)
    ranged = ra.analyze_availability(_pump({"min": 0, "max": 1000}), n_simulations=N)
    assert ranged["costs"]["cost_rate_basis"] == "exact"
    assert ranged["costs"]["cost_rate"] == pytest.approx(fixed["costs"]["cost_rate"], rel=1e-12)
    assert fixed["costs"]["cost_rate"] == pytest.approx(500 / 1010, rel=1e-12)
    # Same failures and repairs (RePyability draws costs from their own stream).
    assert ranged["steady_state_availability"] == fixed["steady_state_availability"]
    assert np.array_equal(ranged["curve"]["availability"], fixed["curve"]["availability"])
    a, b = fixed["costs"]["simulated"], ranged["costs"]["simulated"]
    assert b["std"] > a["std"]
    # ... around the same mean (each failure charges 500 on average).
    assert abs(b["mean"] - a["mean"]) < 4 * b["standard_error"]


def test_ranges_reach_repyability_as_uniform_distributions():
    g = _series(_node(
        "p", model=_w(1000, 2.5), repair=_ln(3.0, 0.5),
        costs={"repair": {"min": 100, "max": 300}, "replace": {"min": 1000, "max": 1000},
               "downtime": 5, "acquisition": 900},
        preventive={"policy": "age", "interval": 580, "cost": {"min": 150, "max": 250}},
    ))
    rbd = ra._build_repairable_rbd(g)[0]
    costs = rbd.costs["p"]
    assert type(costs["repair_cost"]).__name__ == "Parametric" and costs["repair_cost"].dist is sp.Uniform
    assert list(costs["repair_cost"].params) == [100.0, 300.0]
    assert costs["replace_cost"] == 1000.0  # a range of no width is the number
    assert list(costs["preventive_cost"].params) == [150.0, 250.0]
    assert costs["downtime_cost"] == 5.0 and rbd.acquisition_costs["p"] == 900.0
    # The exact breakdown charges each range at its mean.
    pointwise = copy.deepcopy(g)
    pointwise["nodes"][2]["data"].update(costs={"repair": 200, "replace": 1000, "downtime": 5,
                                                 "acquisition": 900})
    pointwise["nodes"][2]["data"]["preventive"]["cost"] = 200
    exact = rbd_costs.exact_breakdown(rbd, {})
    point = rbd_costs.exact_breakdown(ra._build_repairable_rbd(pointwise)[0], {})
    assert exact["total"] == pytest.approx(point["total"], rel=1e-12)
    for k, v in point["by_category"].items():
        assert exact["by_category"][k] == pytest.approx(v, rel=1e-12, abs=1e-15), k


def test_a_proof_test_cost_range_is_priced_at_its_mean():
    def graph(cost):
        return _series(_node("sis", model=_exp(1e-4), instant_repair=True,
                             inspection={"interval": 1000, "cost": cost}))

    a = ra.analyze_availability(graph(50), n_simulations=N)
    b = ra.analyze_availability(graph({"min": 20, "max": 80}), n_simulations=N)
    assert b["costs"]["cost_rate_basis"] == "exact"
    assert b["costs"]["by_category"]["inspection"] == pytest.approx(50 / 1000, rel=1e-12)
    assert b["costs"]["cost_rate"] == pytest.approx(a["costs"]["cost_rate"], rel=1e-12)
    assert b["costs"]["simulated"]["std"] > a["costs"]["simulated"]["std"]


def test_the_cheapest_design_prices_a_range_at_its_mean():
    def plant(repair):
        return _series(_node("pump", model=_exp(1e-3), repair=_exp(0.1),
                             costs={"repair": repair, "acquisition": 1000}),
                       costs={"downtime_rate": 100})

    a = rbd_costs.cheapest_design(plant(500), horizon=87600)
    b = rbd_costs.cheapest_design(plant({"min": 200, "max": 800}), horizon=87600)
    assert b["design"]["units"] == a["design"]["units"]
    assert b["design"]["total_cost"] == pytest.approx(a["design"]["total_cost"], rel=1e-12)


@pytest.mark.parametrize("data, needle", [
    ({"costs": {"repair": {"min": 300, "max": 100}}}, "min is above its max"),
    ({"costs": {"repair": {"min": 100}}}, "needs both a min and a max"),
    ({"costs": {"repair": {"min": -1, "max": 100}}}, "repair cost minimum must be a non-negative"),
    ({"costs": {"repair": {"low": 1, "high": 2}}}, "takes only a min and a max"),
    ({"costs": {"acquisition": {"min": 1, "max": 2}}}, "purchase price must be a single number"),
    ({"costs": {"downtime": {"min": 1, "max": 2}}}, "downtime cost per unit time must be a single number"),
    ({"preventive": {"interval": 500, "cost": {"min": 5, "max": "x"}}}, "maximum must be a number"),
])
def test_bad_ranges_are_clear_errors(data, needle):
    g = _series(_node("pump", model=_exp(1e-3), repair=_exp(0.1), **data))
    v = ra.validate_graph(g)
    assert not v["valid"] and any(needle in e for e in v["errors"]), v["errors"]


def test_the_cache_key_tells_a_range_from_its_mean():
    assert availability_cache_key(_pump({"min": 0, "max": 1000})) != availability_cache_key(_pump(500))
    assert availability_cache_key(_pump({"min": 0, "max": 1000})) != availability_cache_key(
        _pump({"min": 100, "max": 900}))


def test_export_reproduces_ranged_costs(tmp_path):
    a = _node("a", 200, 0, model=_w(1000, 2.5), repair=_ln(3.0, 0.5),
              costs={"replace": {"min": 3000, "max": 7000}, "acquisition": 12000},
              preventive={"policy": "age", "interval": 580, "duration": 7, "cost": {"min": 800, "max": 1200}})
    b = _node("b", 400, 0, model=_exp(1e-4), instant_repair=True,
              inspection={"interval": 1000, "cost": {"min": 25, "max": 75}})
    g = _series(a, b, costs={"downtime_rate": 500, "horizon": 87600})
    app = ra.analyze_availability(g, n_simulations=60)
    code = rbd_export.to_python(g, "Ranged", exported_at=WHEN)
    assert "surv.Uniform.from_params([3000.0, 7000.0])" in code
    assert "surv.Uniform.from_params([800.0, 1200.0])" in code
    assert "drawn uniformly afresh at each action" in code
    res, _ = _run(code, tmp_path, n_sims="60")
    c = res["costs"]
    assert c["cost_rate"] == pytest.approx(app["costs"]["cost_rate"], rel=1e-12)
    assert c["total_cost"] == pytest.approx(app["costs"]["total_cost"], rel=1e-12)
    sim = app["costs"]["simulated"]
    assert c["simulated"]["mean"] == pytest.approx(sim["mean"], rel=1e-12)
    assert c["simulated"]["percentiles"]["10"] == pytest.approx(sim["percentiles"]["10"], rel=1e-12)
    assert c["simulated"]["percentiles"]["90"] == pytest.approx(sim["percentiles"]["90"], rel=1e-12)


def test_numbers_still_export_as_numbers():
    code = rbd_export.to_python(_pump(500), "Plain", exported_at=WHEN)
    assert '"repair_cost": 500.0' in code and "Uniform" not in code
