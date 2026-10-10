"""RePyability 0.13's cost, compare and unavailability calls in repairable
RBDs, checked against the library called directly.

#319: the cost of ownership over several horizons at once — from new
(``expected_cost(t, discount_rate=r)``) and at the long-run rate
(``total_cost`` with an array of horizons, and an endless one when
discounted: the net present cost) — in the availability result's costs, the
cheapest design, the export and MCP; Reliafy works out no discount factor of
its own.

#321: Compare with… gives the exact difference where both designs have exact
values over the window (``compare``, exact by default since 0.13) and
simulates only where it must; its cost comparison counts the purchases
(``compare(quantity="cost")``).

#322: a safety function's PFD(t) is the library's ``point_unavailability``
(and its mean over the window ``mission_unavailability``), not 1 − A(t); the
margin to the SIL band's limit is the PFDavg's.
"""

import copy
import math

import matplotlib

matplotlib.use("Agg")

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from backend.services import rbd_analysis as ra  # noqa: E402
from backend.services import rbd_compare, rbd_costs, rbd_discount, rbd_export  # noqa: E402
from backend.services.rbd_analysis import AnalysisError  # noqa: E402
from backend.tests.test_availability_answers import _sif  # noqa: E402
from backend.tests.test_availability_paid import PRO, client  # noqa: E402,F401 - client is a fixture
from backend.tests.test_mcp import A, _call, _err, _ok, env  # noqa: E402,F401 - env is a fixture
from backend.tests.test_rbd_costs import _exp, _ln, _node, _plant, _pump, _series, _w  # noqa: E402
from backend.tests.test_rbd_export import WHEN, _run  # noqa: E402

TEN_YEARS = 87600.0
SEVEN = math.log(1.07) / 8760  # 7% a year, continuous, per hour
YEARS = np.array([5.0, 10.0, 20.0]) * 8760


def _priced(rate=7):
    g = _plant()
    if rate:
        g["costs"]["discount_rate"] = rate
    return g


def _lib(graph):
    return ra._build_repairable_rbd(graph)[0]


def _crews():
    """Limited crews for wear-out lives: no exact long-run cost rate."""
    g = _series(_node("a", model=_w(1000, 2), repair=_ln(2, 0.5), costs={"repair": 100, "acquisition": 1000}),
                _node("b", model=_w(800, 1.5), repair=_ln(2, 0.5), costs={"repair": 100, "acquisition": 500}),
                costs={"downtime_rate": 100, "horizon": 8760})
    g["repair_crews"] = {"crews": 1}
    return g


# ---------------------------------------------------------------------------
# #319: ownership over several horizons, from new and at the long-run rate
# ---------------------------------------------------------------------------
def test_costs_by_horizon_are_the_librarys():
    g = _priced()
    c = ra.analyze_availability(g, simulate=False)["costs"]
    lib = _lib(g)
    rows = c["by_horizon"]["rows"]
    assert [r["horizon"] for r in rows] == [*YEARS.tolist(), None]
    assert [r["years"] for r in rows] == [5.0, 10.0, 20.0, None]
    assert [r["set"] for r in rows] == [False, True, False, False] and rows[-1]["endless"]
    # At the long-run rate: total_cost over the array, and endless (the net present cost).
    long_run = lib.total_cost(np.append(YEARS, np.inf), discount_rate=SEVEN)
    assert [r["total_cost"] for r in rows] == pytest.approx(long_run, rel=1e-12)
    assert rows[-1]["total_cost"] == pytest.approx(lib.acquisition_cost + lib.expected_cost_rate() / SEVEN, rel=1e-12)
    # From new: expected_cost, discounted from when each cost falls; none for ever.
    # (The library integrates a discounted cost from new to 1e-8 of itself;
    # the set horizon is worked out on its own, the others together.)
    new = lib.expected_cost(YEARS, discount_rate=SEVEN).total
    assert [r["from_new"] for r in rows[:3]] == pytest.approx(new, rel=1e-8)
    assert rows[-1]["from_new"] is None and c["by_horizon"]["from_new_basis"] in ("exact", "numerical")
    assert [r["undiscounted_total_cost"] for r in rows[:3]] == pytest.approx(lib.total_cost(YEARS), rel=1e-12)
    # The headline is the set horizon's, unchanged in meaning (#219).
    assert c["total_cost"] == pytest.approx(rows[1]["total_cost"], rel=1e-15)
    assert c["total_cost_from_new"] == pytest.approx(rows[1]["from_new"], rel=1e-15)
    assert c["running_cost"] == pytest.approx(c["total_cost"] - 26000, rel=1e-12)


def test_the_one_pump_totals_are_unchanged():
    """RePyability's own example: 114,538 at the long-run rate, 114,528 from
    new, 150,099 undiscounted."""
    g = _series(_pump(costs={"acquisition": 20000}),
                costs={"downtime_rate": 100, "horizon": TEN_YEARS, "discount_rate": 7})
    c = ra.analyze_availability(g, simulate=False)["costs"]
    assert round(c["total_cost"]) == 114538 and round(c["undiscounted_total_cost"]) == 150099
    assert round(c["total_cost_from_new"]) == 114528


def test_undiscounted_horizons_have_no_endless_row():
    c = ra.analyze_availability(_priced(rate=0), simulate=False)["costs"]
    rows = c["by_horizon"]["rows"]
    assert all(not r["endless"] for r in rows) and len(rows) == 3
    lib = _lib(_priced(rate=0))
    assert [r["from_new"] for r in rows] == pytest.approx(lib.expected_cost(YEARS).total, rel=1e-12)
    assert all(r["undiscounted_total_cost"] is None for r in rows)


def test_a_non_calendar_unit_prices_only_its_own_horizon():
    g = {**_priced(rate=0), "unit": "cycles"}
    rows = ra.analyze_availability(g, simulate=False)["costs"]["by_horizon"]["rows"]
    assert [r["horizon"] for r in rows] == [TEN_YEARS] and rows[0]["years"] is None


def test_horizons_given_replace_the_defaults_and_are_checked():
    rows = rbd_discount.horizons(_priced(), 1000.0, {"annual": 7}, [500.0, 1000.0, 2000.0])
    assert [r["horizon"] for r in rows] == [500.0, 1000.0, 2000.0, None]
    assert rbd_discount.parse_horizons(None) is None
    with pytest.raises(AnalysisError, match="up to 6"):
        rbd_discount.parse_horizons(list(range(1, 9)))
    with pytest.raises(AnalysisError, match="positive"):
        rbd_discount.parse_horizons([-1])


def test_a_simulated_rate_has_no_present_value():
    """No exact long-run rate: the library can't discount the simulated one,
    so the present values are left out and say why; undiscounted totals stay."""
    g = _crews()
    g["costs"]["discount_rate"] = 7
    c = ra.analyze_availability(g, n_simulations=40)["costs"]
    assert c["cost_rate_basis"] == "simulation"
    assert c["total_cost"] is None and c["running_cost"] is None
    assert "No present value" in c["present_value_note"]
    assert c["undiscounted_total_cost"] == pytest.approx(1500 + c["cost_rate"] * 8760, rel=1e-12)
    rows = c["by_horizon"]["rows"]
    assert all(r["total_cost"] is None for r in rows) and rows[-1]["endless"]
    # Undiscounted, the simulated rate prices each horizon as before.
    del g["costs"]["discount_rate"]
    plain = ra.analyze_availability(g, n_simulations=40)["costs"]
    assert plain["total_cost"] == pytest.approx(1500 + plain["cost_rate"] * 8760, rel=1e-12)
    assert plain["present_value_note"] is None


def test_with_discount_reprices_every_horizon():
    c = ra.analyze_availability(_priced(rate=0), simulate=False)["costs"]
    g = _priced(rate=0)
    out = rbd_costs.with_discount(c, g, 7)
    lib = _lib(g)
    assert out["total_cost"] == pytest.approx(lib.total_cost(TEN_YEARS, discount_rate=SEVEN), rel=1e-12)
    rows = out["by_horizon"]["rows"]
    assert rows[-1]["endless"] and rows[-1]["total_cost"] == pytest.approx(
        lib.total_cost(np.inf, discount_rate=SEVEN), rel=1e-12)
    # The library integrates a discounted cost from new to 1e-8 of itself:
    # the same horizon among others agrees with it alone to that.
    assert out["total_cost_from_new"] == pytest.approx(
        lib.expected_cost(TEN_YEARS, discount_rate=SEVEN).total, rel=1e-8)


def test_cheapest_design_by_horizon_is_allocate_redundancy_at_each():
    g = _priced()
    out = rbd_costs.cheapest_design(g)
    lib = _lib(g)
    rows = out["by_horizon"]["rows"]
    assert [r["horizon"] for r in rows] == [*YEARS.tolist(), None]
    for row, t in zip(rows, np.append(YEARS, np.inf)):
        alloc = lib.allocate_redundancy(float(t), max_units=rbd_costs.MAX_COPIES, discount_rate=SEVEN)
        assert {c["id"]: c["copies"] for c in row["copies"]} == alloc.units
        assert row["design_total"] == pytest.approx(alloc.total_cost, rel=1e-12)
        assert row["current_total"] == pytest.approx(lib.total_cost(float(t), discount_rate=SEVEN), rel=1e-12)
        assert row["saving"] == pytest.approx(row["current_total"] - row["design_total"], rel=1e-12)
    # Five years buys a second valve only; ten years a second pump too.
    assert {c["id"]: c["copies"] for c in rows[0]["copies"]} == {"pump": 1, "valve": 2}
    assert {c["id"]: c["copies"] for c in rows[1]["copies"]} == {"pump": 2, "valve": 2}
    # The set horizon's row is the design itself.
    assert rows[1]["design_total"] == pytest.approx(out["design"]["total_cost"], rel=1e-12)
    chosen = rbd_costs.cheapest_design(g, horizons=[1000, 50000])["by_horizon"]["rows"]
    assert [r["horizon"] for r in chosen] == [1000.0, 50000.0, TEN_YEARS, None]


def test_cheapest_design_endpoint_takes_horizons(client):
    client.act_as(PRO)
    res = client.post("/api/rbds/design/cheapest", json={"graph": _priced(rate=0), "horizons": [8760, 43800]})
    assert res.status_code == 200, res.text
    assert [r["horizon"] for r in res.json()["by_horizon"]["rows"]] == [8760.0, 43800.0, TEN_YEARS]
    bad = client.post("/api/rbds/design/cheapest", json={"graph": _priced(), "horizons": [0]})
    assert bad.status_code == 422 and "positive" in bad.json()["detail"]


def test_export_prices_the_horizons_as_the_app_does(tmp_path):
    g = _priced()
    app = ra.analyze_availability(g, n_simulations=60)["costs"]
    code = rbd_export.to_python(g, "Horizons", exported_at=WHEN)
    assert "COMPARE_HORIZONS = [43800, 175200]" in code or "COMPARE_HORIZONS = [43800.0, 175200.0]" in code
    assert "np.expm1" not in code  # no discount factor of its own
    res, proc = _run(code, tmp_path, n_sims="60")
    rows = res["costs"]["by_horizon"]
    assert [r["horizon"] for r in rows] == [r["horizon"] for r in app["by_horizon"]["rows"]]
    assert [r["total_cost"] for r in rows] == pytest.approx([r["total_cost"] for r in app["by_horizon"]["rows"]],
                                                            rel=1e-12)
    assert [r["from_new"] for r in rows[:3]] == pytest.approx(
        [r["from_new"] for r in app["by_horizon"]["rows"][:3]], rel=1e-12)
    assert res["costs"]["total_cost"] == pytest.approx(app["total_cost"], rel=1e-12)
    assert "net present cost" in proc.stdout


def test_export_with_a_simulated_rate_leaves_the_present_value_out(tmp_path):
    g = _crews()
    g["costs"]["discount_rate"] = 7
    res, proc = _run(rbd_export.to_python(g, "Crews", exported_at=WHEN), tmp_path, n_sims="40")
    assert res["costs"]["total_cost"] is None and res["costs"]["cost_rate_basis"] == "simulation"
    assert "no present value" in proc.stdout


# ---------------------------------------------------------------------------
# #321: Compare with… — exact where it can be, purchases counted
# ---------------------------------------------------------------------------
def test_compare_is_exact_where_both_designs_are():
    a = _priced(rate=0)
    b = rbd_costs.apply_copies(a, {"pump": 2})
    out = rbd_compare.compare_availability(a, b)
    assert out["method"] == "exact" and out["n_simulations"] == 0
    la, lb = _lib(a), _lib(b)
    t = out["t_simulation"]
    lib = lb.compare(la, t)
    assert lib.method == "exact"
    d = out["differences"]["availability"]
    assert d["method"] == "exact" and d["estimate"] == pytest.approx(lib.estimate, rel=1e-12)
    assert d["lower"] == d["upper"] == d["estimate"] and d["standard_error"] == 0.0
    assert d["verdict"] == "b_higher" and d["exact"] == pytest.approx(lb.mean_availability() - la.mean_availability())
    assert out["designs"]["a"]["window_availability"] == pytest.approx(la.mission_availability(t), rel=1e-12)
    assert out["designs"]["b"]["window_availability"] == pytest.approx(lb.mission_availability(t), rel=1e-12)
    # The cost of owning each for the window, the second pump's price included.
    cost = out["differences"]["cost"]
    assert cost["method"] == "exact" and cost["includes_acquisition"] is True
    assert cost["estimate"] == pytest.approx(lb.compare(la, t, quantity="cost").estimate, rel=1e-12)
    assert cost["acquisition"] == 20000.0
    assert cost["running"] == pytest.approx(lb.expected_cost(t).mean - la.expected_cost(t).mean, rel=1e-9)
    assert cost["verdict"] == "b_higher"  # a 20,000 pump doesn't pay over a few hundred hours
    assert out["designs"]["b"]["window_cost"] == pytest.approx(lb.expected_cost(t).total, rel=1e-12)
    assert out["designs"]["b"]["acquisition_cost"] == 46000.0


def test_compare_holds_pins_exactly():
    """compare takes no pins: with one, the difference is the designs' own
    mission availabilities with it held."""
    a = _priced(rate=0)
    b = copy.deepcopy(a)
    b["nodes"][3]["data"]["state"] = "working"  # the valve pinned working in B
    out = rbd_compare.compare_availability(a, b)
    assert out["method"] == "exact"
    t = out["t_simulation"]
    held = _lib(a).mission_availability(t, working_nodes={"valve"})
    assert out["designs"]["b"]["window_availability"] == pytest.approx(held, rel=1e-12)
    assert out["differences"]["availability"]["estimate"] == pytest.approx(
        held - _lib(a).mission_availability(t), rel=1e-12)


def test_compare_simulates_only_what_has_no_exact_route():
    """Limited crews for wear-out lives have no exact values over the
    window: simulated, with common random numbers and an interval; the cost
    counts the purchases (the paired running costs plus the price difference)."""
    a = _crews()
    b = copy.deepcopy(a)
    b["repair_crews"] = {"crews": 2}
    b["nodes"][2]["data"]["costs"]["acquisition"] = 3000
    out = rbd_compare.compare_availability(a, b, t_simulation=2000, n_simulations=200)
    assert out["method"] == "simulated" and out["n_simulations"] == 200
    d = out["differences"]["availability"]
    assert d["method"] == "simulated" and d["lower"] < d["estimate"] < d["upper"]
    cost = out["differences"]["cost"]
    assert cost["method"] == "simulated" and cost["acquisition"] == 2000.0
    assert cost["running"] == pytest.approx(cost["estimate"] - 2000.0, rel=1e-12)
    da, db = out["designs"]["a"], out["designs"]["b"]
    assert db["window_cost"] - da["window_cost"] == pytest.approx(cost["estimate"], rel=1e-9)
    # Without a fixed count it is still simulated: there's no exact route.
    assert rbd_compare._exact_window(rbd_compare._design(a, None), rbd_compare._design(b, None), 2000.0,
                                     ("availability", "cost")) == {}


def test_designs_priced_by_purchases_alone_are_compared_by_cost():
    a = _series(_node("pump", 200, 0, model=_exp(1e-3), repair=_exp(0.1), costs={"acquisition": 1000}))
    b = copy.deepcopy(a)
    b["nodes"][2]["data"]["costs"]["acquisition"] = 1500
    out = rbd_compare.compare_availability(a, b, t_simulation=500)
    cost = out["differences"]["cost"]
    assert cost["estimate"] == pytest.approx(500.0) and cost["running"] == pytest.approx(0.0, abs=1e-9)
    assert out["differences"]["availability"]["estimate"] == 0.0
    assert out["differences"]["availability"]["verdict"] == "no_detectable_difference"


def test_compare_endpoint_is_exact(client):
    client.act_as(PRO)
    a = _priced(rate=0)
    saved = client.post("/api/rbds", json={"name": "Two pumps", "graph": rbd_costs.apply_copies(a, {"pump": 2})})
    res = client.post("/api/rbds/compare", json={"graph": a, "other_id": saved.json()["id"]})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["method"] == "exact" and body["differences"]["cost"]["acquisition"] == 20000.0


def _mcp_rbd(env, name, graph):
    rid = _ok(_call(env.token[A], "create_rbd", {
        "name": name, "unit": "Hours", "repairable": True,
        "nodes": [{"id": "input", "type": "input"}, {"id": "output", "type": "output"},
                  {"id": "pump", "type": "component",
                   "model": {"distribution_id": "exponential", "params": [{"name": "failure_rate", "value": 1e-3}]},
                   "repair": {"distribution_id": "exponential", "params": [{"name": "failure_rate", "value": 0.1}]}}],
        "edges": [{"source": "input", "target": "pump"}, {"source": "pump", "target": "output"}]}))["id"]
    env.db.rbds.update_one({"_id": rid}, {"$set": {"graph": graph}})
    return rid


def test_mcp_compare_rbds(env, monkeypatch):
    a = _priced(rate=0)
    ra_id = _mcp_rbd(env, "One pump", a)
    rb_id = _mcp_rbd(env, "Two pumps", rbd_costs.apply_copies(a, {"pump": 2}))
    out = _ok(_call(env.token[A], "compare_rbds", {"rbd_id": ra_id, "other_rbd_id": rb_id}))
    assert out["available"] and out["method"] == "exact"
    assert out["designs"]["a"]["name"] == "One pump" and out["designs"]["b"]["name"] == "Two pumps"
    direct = rbd_compare.compare_availability(a, rbd_costs.apply_copies(a, {"pump": 2}))
    assert out["differences"]["availability"]["estimate"] == pytest.approx(
        direct["differences"]["availability"]["estimate"], rel=1e-12)
    assert out["differences"]["cost"]["acquisition"] == 20000.0
    other = _ok(_call(env.token[A], "create_rbd", {
        "name": "R", "nodes": [{"id": "input", "type": "input"}, {"id": "output", "type": "output"},
                               {"id": "x", "type": "component", "model": {
                                   "distribution_id": "exponential", "params": [{"name": "failure_rate",
                                                                                 "value": 1e-3}]}}],
        "edges": [{"source": "input", "target": "x"}, {"source": "x", "target": "output"}]}))["id"]
    assert "non-repairable" in _err(_call(env.token[A], "compare_rbds", {"rbd_id": ra_id, "other_rbd_id": other}))
    from backend.services import billing

    monkeypatch.setattr(billing, "premium_compute_allowed", lambda db, user: False)
    paid = _ok(_call(env.token[A], "compare_rbds", {"rbd_id": ra_id, "other_rbd_id": rb_id}))
    assert paid["available"] is False and paid["code"] == "pro_required"


def test_mcp_costs_and_cheapest_design_by_horizon(env):
    rid = _mcp_rbd(env, "Plant", _priced())
    costs = _ok(_call(env.token[A], "analyze_rbd", {"rbd_id": rid, "simulate": False}))["costs"]
    rows = costs["by_horizon"]["rows"]
    assert [r["horizon"] for r in rows] == [*YEARS.tolist(), None] and rows[-1]["endless"]
    assert costs["total_cost_from_new"] == pytest.approx(rows[1]["from_new"], rel=1e-12)
    flat = _ok(_call(env.token[A], "analyze_rbd", {"rbd_id": rid, "simulate": False, "discount_rate": 0}))["costs"]
    assert all(not r.get("endless") for r in flat["by_horizon"]["rows"])
    design = _ok(_call(env.token[A], "cheapest_design", {"rbd_id": rid, "horizons": [43800]}))
    assert [r["horizon"] for r in design["by_horizon"]] == [43800.0, TEN_YEARS, None]
    assert design["by_horizon"][0]["copies"] == {"pump": 1, "valve": 2}


# ---------------------------------------------------------------------------
# #322: PFD(t) from the library's unavailability
# ---------------------------------------------------------------------------
def test_pfd_over_time_is_the_librarys_unavailability():
    g = _sif()
    e = ra.exact_availability(g)
    lib = _lib(g)
    t = np.asarray(e["curve"]["t"])
    assert e["curve"]["unavailability"] == pytest.approx(lib.point_unavailability(t), rel=1e-12, abs=1e-300)
    assert e["mission_unavailability"] == pytest.approx(lib.mission_unavailability(e["window"]), rel=1e-12)
    # Not a safety function: no PFD(t).
    plain = ra.exact_availability({**g, "safety_function": False})
    assert "unavailability" not in plain["curve"] and "mission_unavailability" not in plain


def test_pfd_keeps_the_digits_one_less_the_availability_loses():
    """RePyability's own example: two valves failing at 1e-9 an hour in
    parallel are down together 6.4e-17 of the time, which 1 − A(t) rounds
    away."""
    valve = _node("v1", model=_exp(1e-9), repair=_exp(1 / 8))
    other = _node("v2", model=_exp(1e-9), repair=_exp(1 / 8))
    g = {"repairable": True, "unit": "hours", "safety_function": True,
         "nodes": [{"id": "input", "type": "input", "position": {"x": 0, "y": 0}, "data": {"label": "In"}},
                   {"id": "output", "type": "output", "position": {"x": 9, "y": 0}, "data": {"label": "Out"}},
                   valve, other],
         "edges": [{"id": f"e{i}", "source": s, "target": d} for i, (s, d) in
                   enumerate([("input", "v1"), ("input", "v2"), ("v1", "output"), ("v2", "output")])]}
    e = ra.exact_availability(g, horizon=1000.0)
    down = np.asarray(e["curve"]["unavailability"])
    up = np.asarray(e["curve"]["availability"])
    assert down[-1] == pytest.approx(6.4e-17, rel=1e-3, abs=0)
    # Lost below a number next to 1: 0 or 1.1e-16, not 6.4e-17.
    assert abs((1.0 - up[-1]) - 6.4e-17) > 3e-17


def test_safety_margin_is_the_pfdavgs():
    g = _sif()
    s = ra.analyze_availability(g, simulate=False)["safety"]
    assert s["margin"] == {"sil": 2, "limit": 0.01, "ratio": pytest.approx(s["pfd_avg"] / 0.01, rel=1e-15),
                           "of": "target"}
    untargeted = ra.analyze_availability({**g, "target_sil": None}, simulate=False)["safety"]
    assert untargeted["margin"]["of"] == "achieved" and untargeted["margin"]["sil"] == untargeted["sil"]


def test_export_gives_pfd_over_time_and_the_margin(tmp_path):
    g = _sif()
    res, proc = _run(rbd_export.to_python(g, "SIF", exported_at=WHEN), tmp_path, n_sims="40")
    e = ra.exact_availability(g)
    s = res["safety"]
    assert s["over_time"]["pfd"] == pytest.approx(e["curve"]["unavailability"], rel=1e-12, abs=1e-300)
    assert s["over_time"]["mission_unavailability"] == pytest.approx(e["mission_unavailability"], rel=1e-12)
    assert s["margin"]["ratio"] == pytest.approx(s["pfd_avg"] / 0.01, rel=1e-12)
    assert "x the SIL 2 limit" in proc.stdout


def test_mcp_analyze_rbd_gives_pfd_over_time(env):
    rid = _mcp_rbd(env, "SIF", _sif())
    out = _ok(_call(env.token[A], "analyze_rbd", {"rbd_id": rid, "simulate": False}))
    assert out["safety"]["margin"]["sil"] == 2
    assert out["exact"]["mission_unavailability"] == pytest.approx(out["safety"]["pfd_avg"], rel=1e-6)
    assert all("pfd" in p for p in out["exact"]["curve"])


def test_a_slow_or_refused_horizon_leaves_the_set_one():
    """A block replaced on condition, slow to follow from new (and refused
    over 20 years): a set horizon of a few checks keeps its cost from new, the
    others are left out and say why."""
    from backend.tests.test_rbd_crews_maintenance import _export_graph

    g = _export_graph()
    g["costs"] = {**(g.get("costs") or {}), "horizon": 200.0}  # 20 checks of the pump
    table = ra.analyze_availability(g, simulate=False)["costs"]["by_horizon"]
    news = [r["from_new"] for r in table["rows"]]
    assert table["rows"][0]["set"] and news[0] is not None and news[-1] is None
    assert table["from_new_note"]
    lib = _lib(g)
    assert news[0] == pytest.approx(lib.expected_cost(table["rows"][0]["horizon"]).total, rel=1e-12)


def test_calculate_skips_a_cost_from_new_over_many_condition_checks():
    """Over 100 checks of a block replaced on condition the cost from new
    takes seconds to follow, so Calculate leaves it out, saying why and
    where to get it, and stays quick."""
    import time

    from backend.tests.test_rbd_crews_maintenance import _export_graph

    g = _export_graph()  # the window: 1,000 hours, the pump checked every 10
    started = time.perf_counter()
    table = ra.analyze_availability(g, simulate=False)["costs"]["by_horizon"]
    assert time.perf_counter() - started < 3.0
    assert all(r["from_new"] is None for r in table["rows"])
    assert "“Pump” is replaced on condition" in table["from_new_note"]
    assert "Download as Python" in table["from_new_note"]
