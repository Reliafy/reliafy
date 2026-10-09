"""Regression tests for the MCP check of the 5 Oct release (#262).

Through the real MCP mount (helpers and the ``env`` fixture from test_mcp)
or, for the shared pieces, the services the app uses too.
"""

import numpy as np
import pytest
import surpyval
from surpyval import AcceleratedLife

from backend.tests.test_mcp import A, GRAPH, _call, _err, _ok, _run, env  # noqa: F401 - env is a fixture

LOGNORMAL_REPAIR = {"distribution_id": "lognormal",
                    "params": [{"name": "mu", "value": 1.0}, {"name": "sigma", "value": 0.3}]}


def _weibull(alpha, beta):
    return {"distribution_id": "weibull", "params": [{"name": "alpha", "value": alpha},
                                                     {"name": "beta", "value": beta}]}


def _repairable_nodes(**extra):
    """GRAPH's controller and two pumps, repairable."""
    return [n if n["type"] in ("input", "output") else {**n, "repair": LOGNORMAL_REPAIR, **extra.get(n["id"], {})}
            for n in GRAPH["nodes"]]


def _create(env, **args):
    return _ok(_call(env.token[A], "create_rbd", {"name": "Pumps", "repairable": True,
                                                  "nodes": _repairable_nodes(), "edges": GRAPH["edges"], **args}))


@pytest.fixture()
def pro(env, monkeypatch):
    from backend.services import billing as billing_service

    monkeypatch.setattr(billing_service, "premium_compute_allowed", lambda db, user: True)
    return env


# ---- 1. costs: published, and cheapest_design reachable from them ---------------------------

def test_create_rbd_takes_the_diagram_costs(env):
    out = _create(env, costs={"downtime_rate": 500, "horizon": 87600, "discount_rate": 0})
    graph = env.db.rbds.find_one({"_id": out["id"]})["graph"]
    assert graph["costs"] == {"downtime_rate": 500, "horizon": 87600}  # 0 = not set
    msg = _err(_call(env.token[A], "create_rbd", {"name": "x", "nodes": GRAPH["nodes"], "edges": GRAPH["edges"],
                                                  "costs": {"horizon": 100}}))
    assert "costs" in msg and "repairable" in msg


def test_cheapest_design_says_which_fields_to_set_and_works_once_they_are(pro):
    rid = _create(pro)["id"]
    msg = _err(_call(pro.token[A], "cheapest_design", {"rbd_id": rid}))
    assert "horizon" in msg and "{op: 'set', costs: {horizon:" in msg
    _ok(_call(pro.token[A], "edit_rbd", {"rbd_id": rid, "ops": [{"op": "set", "costs": {"horizon": 87600}}]}))
    msg = _err(_call(pro.token[A], "cheapest_design", {"rbd_id": rid}))
    assert "purchase price" in msg and "costs: {acquisition:" in msg
    _ok(_call(pro.token[A], "edit_rbd", {"rbd_id": rid, "ops": [
        {"op": "update_node", "ids": ["p1", "p2"], "costs": {"acquisition": 2000}}]}))
    no_rate = _ok(_call(pro.token[A], "cheapest_design", {"rbd_id": rid}))
    assert no_rate["available"] is True and "downtime_rate" in no_rate["note"]
    _ok(_call(pro.token[A], "edit_rbd", {"rbd_id": rid, "ops": [{"op": "set", "costs": {"downtime_rate": 5000}}]}))
    out = _ok(_call(pro.token[A], "cheapest_design", {"rbd_id": rid}))
    assert out["available"] is True and out["horizon"] == 87600 and out["design"]


# ---- 2. simulation_note names analyze_rbd's real parameter -------------------------------------

def test_simulation_note_names_a_parameter_analyze_rbd_has(pro):
    rid = _create(pro)["id"]
    _ok(_call(pro.token[A], "analyze_rbd", {"rbd_id": rid, "simulate": True}))
    edited = _ok(_call(pro.token[A], "edit_rbd", {"rbd_id": rid, "ops": [
        {"op": "update_node", "id": "p1", "model": _weibull(500, 1.2)}]}))
    note = edited["simulation_note"]
    tools = {t.name: t for t in _run(pro.token[A], lambda c: c.list_tools()).tools}
    params = set(tools["analyze_rbd"].input_schema["properties"])
    import re

    named = set(re.findall(r"(\w+)=(?:true|false)", note))
    assert named and named <= params, named
    # And it does what the note says: a new simulation for the edited diagram.
    out = _ok(_call(pro.token[A], "analyze_rbd", {"rbd_id": rid, "simulate": True}))
    assert out["has_simulation"] is True and out["cached"] is False


# ---- 3. ALT: positive coefficients' Wald intervals stay positive ------------------------------

def _arrhenius_fit():
    from backend import alt

    rng = np.random.default_rng(3)
    T = np.repeat([350.0, 380.0, 410.0], 4)
    x = 1.0 * np.exp(3000.0 / T) * rng.weibull(1.8, size=T.size)
    model = AcceleratedLife(surpyval.Weibull, alt.LIFE_MODELS["arrhenius"]["model"]).fit(x=x, Z=T.reshape(-1, 1))
    return model, x, T


def test_log_scale_wald_interval_for_a_positive_coefficient():
    from backend import alt

    # The issue's numbers: b = 0.994 with 95% CI [-0.79, 2.78] on the linear scale.
    se = (2.78 + 0.79) / (2 * 1.959963984540054)
    lo, hi = alt.bounded_wald_interval(0.994, se, 0, None, 0.95)
    assert 0 < lo < 0.994 < hi
    assert lo * hi == pytest.approx(0.994 ** 2)  # symmetric on the log scale
    assert alt.bounded_wald_interval(0.0, se, 0, None, 0.95) is None  # on the bound: none


def test_alt_fit_and_use_level_keep_positive_coefficients_positive():
    from backend import alt

    model, _, _ = _arrhenius_fit()
    # Reliafy's Wald interval on b is on the log scale, so it stays positive;
    # a, which can be negative, keeps SurPyval's.
    lo, hi = alt.param_interval(model, "b", 0.95)
    b = float(model.params[model.parameter_names.index("b")])
    assert 0 < lo < b < hi
    # SurPyval's own went below zero until 0.24, which takes a positive
    # life-stress coefficient on the log scale too (#655): the two now agree.
    assert list(model.param_cb("b", alpha_ci=0.05)) == pytest.approx([lo, hi], rel=1e-9)
    assert alt.param_interval(model, "a", 0.95) == pytest.approx(list(model.param_cb("a", alpha_ci=0.05)))
    bounds = alt.use_level_bounds(model, [313.15], "arrhenius")
    by_name = {c["name"]: c for c in bounds["coefficients"]}
    assert by_name["b"]["ci"][0] > 0 and by_name["b"]["ci"] == pytest.approx([lo, hi])
    # A rehydrated (saved) model gives the same interval.
    again = alt.param_interval(surpyval.from_dict(model.to_dict()), "b", 0.95)
    assert again == pytest.approx([lo, hi])


def test_every_positive_life_stress_coefficient_is_bounded():
    """The coefficients SurPyval declares positive are exactly the ones
    Reliafy bounds; the rest stay on the linear scale."""
    from backend import alt

    expected = {"arrhenius": {"b"}, "inverse_power": {"a"}, "dual_exponential": {"c"},
                "power_exponential": {"c"}, "dual_power": {"c"}, "eyring": set(), "linear": set()}
    for key, entry in alt.LIFE_MODELS.items():
        model = entry["model"]
        positive = {name for name, off in model.phi_param_map.items() if model.phi_bounds[off][0] == 0}
        assert positive == expected[key], key


def test_mcp_fit_alt_model_and_alt_use_level_intervals_stay_positive(env):
    _, x, T = _arrhenius_fit()
    out = _ok(_call(env.token[A], "fit_alt_model", {
        "name": "Wide b", "life_model": "arrhenius", "data": x.tolist(), "stresses": [[t] for t in T],
        "unit": "hours"}))
    coeffs = {c["name"]: c for c in out["life_stress_coefficients"]}
    assert coeffs["b"]["ci_95"][0] > 0
    assert coeffs["a"]["ci_95"][0] < coeffs["a"]["value"] < coeffs["a"]["ci_95"][1]
    ev = _ok(_call(env.token[A], "alt_use_level", {"model_id": out["model_id"], "use_stress": [313.15]}))
    intervals = {c["name"]: c for c in ev["bounds"]["parameter_intervals"]}
    assert intervals["b"]["ci"][0] > 0


def test_a_fit_saved_before_the_fix_is_served_with_a_positive_interval():
    from backend import alt

    se = (2.78 + 0.79) / (2 * 1.959963984540054)
    old = {"life_model_id": "arrhenius", "coefficients": [
        {"name": "a", "value": 3000.0, "ci": [1000.0, 5000.0]},
        {"name": "b", "value": 0.994, "ci": [0.994 - 1.959963984540054 * se, 0.994 + 1.959963984540054 * se]}]}
    fixed = alt.positive_coefficient_intervals(old)
    a, b = fixed["coefficients"]
    assert a == old["coefficients"][0]  # unbounded: untouched
    assert b["ci"][0] > 0 and b["ci"] == pytest.approx(alt.bounded_wald_interval(0.994, se, 0, None, 0.95))
    assert alt.positive_coefficient_intervals(fixed) == fixed  # already log scale: unchanged
    assert old["coefficients"][1]["ci"][0] < 0  # the stored copy isn't mutated


# ---- 4. analyze_rbd's repairable answer ------------------------------------------------------

def test_no_simulation_when_every_figure_is_exact_unless_asked(pro):
    rid = _create(pro)["id"]
    out = _ok(_call(pro.token[A], "analyze_rbd", {"rbd_id": rid}))
    assert out["available"] is True and out["has_simulation"] is False
    assert out["simulation"]["on_request"] is True and "simulate=true" in out["simulation"]["message"]
    assert out["exact"]["status"] == "ok" and out["availability"]["basis"] == "exact"
    assert not pro.db.rbds.find_one({"_id": rid}).get("availability_cache")
    # simulate=false: the same, without the offer's flag being misread as a refusal.
    fast = _ok(_call(pro.token[A], "analyze_rbd", {"rbd_id": rid, "simulate": False}))
    assert fast["has_simulation"] is False and "code" not in fast["simulation"]
    # Asked: it runs and is saved; afterwards the saved one is served by default.
    ran = _ok(_call(pro.token[A], "analyze_rbd", {"rbd_id": rid, "simulate": True}))
    assert ran["has_simulation"] is True and ran["cached"] is False
    again = _ok(_call(pro.token[A], "analyze_rbd", {"rbd_id": rid}))
    assert again["has_simulation"] is True and again["cached"] is True
    # recompute asks too.
    assert _ok(_call(pro.token[A], "analyze_rbd", {"rbd_id": rid, "recompute": True}))["cached"] is False


def test_simulation_still_runs_where_a_figure_needs_it(pro):
    # One repair crew for wear-out lives: no exact route, so the default simulates.
    rid = _create(pro, repair_crews=1)["id"]
    out = _ok(_call(pro.token[A], "analyze_rbd", {"rbd_id": rid}))
    assert out["has_simulation"] is True and "on_request" not in out["simulation"]
    # From now (current_state) the simulation gives the next failure: it runs too.
    rid = _create(pro)["id"]
    now = _ok(_call(pro.token[A], "analyze_rbd", {"rbd_id": rid, "current_state": {"p1": {"down": True}}}))
    assert now["has_simulation"] is True


def test_exact_complete_reads_every_route():
    from backend.routers.rbds import exact_complete

    routes = {"mean_availability": {"route": "exact"}, "point_availability": {"route": "numerical"},
              "availability": {"route": "simulated"}}
    ok = {"steady_state_availability": 0.99, "long_run_method": {"route": "exact"},
          "exact": {"status": "ok", "routes": routes}}
    assert exact_complete(ok) is True
    assert exact_complete({**ok, "exact": {"status": "ok", "routes": {
        **routes, "expected_events": {"route": "simulated"}}}}) is False
    assert exact_complete({**ok, "long_run_method": {"route": "simulated"}}) is False
    assert exact_complete({**ok, "exact": {"status": "on_request", "routes": routes}}) is False
    assert exact_complete({**ok, "steady_state_availability": None}) is False


def test_per_node_downtime_is_per_run_and_the_total_is_labelled(pro):
    rid = _create(pro)["id"]
    out = _ok(_call(pro.token[A], "analyze_rbd", {"rbd_id": rid, "simulate": True}))
    n = out["n_simulations"]
    assert n > 1 and out["per_node"]
    for row in out["per_node"]:
        assert row["downtime"] == row["downtime_total_all_runs"]  # kept, as before
        assert row["downtime_per_run"] == pytest.approx(row["downtime_total_all_runs"] / n)
        assert row["downtime_per_run"] <= out["t_simulation"]
    assert f"{n:,} runs" in out["per_node_note"] and "downtime_per_run" in out["per_node_note"]


def test_precision_says_the_interval_is_centred_on_the_simulated_mean(pro):
    rid = _create(pro)["id"]
    p = _ok(_call(pro.token[A], "analyze_rbd", {"rbd_id": rid, "simulate": True}))["precision"]
    assert p["simulated_window_availability"] is not None
    if p.get("window_availability_basis") in ("exact", "numerical"):
        assert p["interval_centre"] == "simulated_window_availability"
        assert "around its own mean" in p["note"]
        assert p["lower"] <= p["simulated_window_availability"] <= p["upper"]
    else:
        assert p["interval_centre"] == "window_availability"


def test_headline_window_availability_shows_the_simulated_mean_beside_its_interval():
    from backend.services import availability_answer

    payload = {"has_simulation": True, "t_simulation": 1000.0, "unit": "hours", "precision": {
        "window_availability": 0.98, "window_availability_basis": "exact",
        "simulated_window_availability": 0.9812, "lower": 0.979, "upper": 0.9834, "confidence": 0.95}}
    head = availability_answer._headline({}, payload)
    assert head["value"] == 0.98 and head["basis"] == "exact"
    assert head["simulated_window_availability"] == 0.9812 and "own mean" in head["interval_note"]


# ---- 5. fault tree: the cut sets' shares aren't additive -----------------------------------

def test_fault_tree_cut_set_share_alone_and_the_overlap_note(env):
    rid = _ok(_call(env.token[A], "create_rbd", {"name": "FT", "nodes": GRAPH["nodes"],
                                                 "edges": GRAPH["edges"]}))["id"]
    out = _ok(_call(env.token[A], "rbd_fault_tree", {"rbd_id": rid}))
    cuts = out["cut_sets"]
    for row in cuts["listed"]:
        assert row["share_alone"] == row["share"]
        assert row["share_alone"] == pytest.approx(row["probability"] / out["top_event_probability"])
    # Overlapping cut sets: the shares add to more than 1, the sum exceeds the top event.
    assert sum(r["share_alone"] for r in cuts["listed"]) > 1
    assert cuts["probability_sum"] > out["top_event_probability"]
    assert "don't add up to 1" in cuts["note"] and "probability_sum" in cuts["note"]
    tools = {t.name: t for t in _run(env.token[A], lambda c: c.list_tools()).tools}
    assert "share_alone" in tools["rbd_fault_tree"].description
