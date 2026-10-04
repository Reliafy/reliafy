"""RePyability 0.12 in repairable RBDs: discounted total costs (#219) and
repair crews around nested sub-diagrams (#222), checked against the library.

#219: a diagram's (or a request's) discount rate, in % a year, makes the
total cost of ownership and the cheapest design's totals present values —
RePyability's ``total_cost`` / ``allocate_redundancy(discount_rate=r)`` with
``r`` the continuous rate per unit time of the diagram's unit.

#222: a standby group repaired one unit at a time is a nested RepairableRBD
with its own crew; with the diagram's crews limited, RePyability 0.11 refused
the expected events, cost and capacity over time for such a diagram, so the
app had only the simulation. 0.12 works them out (its #162), and the app now
gives them exactly, as the library does.
"""

import math

import matplotlib

matplotlib.use("Agg")

import pytest  # noqa: E402
import surpyval as sv  # noqa: E402
from repyability import RepairableRBD  # noqa: E402

from backend.services import rbd_analysis as ra  # noqa: E402
from backend.services import rbd_costs, rbd_export, rbd_maintenance  # noqa: E402
from backend.services.rbd_analysis import AnalysisError  # noqa: E402
from backend.services.rbds import availability_cache_key  # noqa: E402
from backend.tests.test_availability_paid import PRO, client  # noqa: E402,F401 - client is a fixture
from backend.tests.test_mcp import A, _call, _err, _ok, env  # noqa: E402,F401 - env is a fixture
from backend.tests.test_mcp_rbd_edit import _doc, _edit  # noqa: E402
from backend.tests.test_rbd_costs import _exp, _node, _plant, _pump, _series  # noqa: E402
from backend.tests.test_rbd_crews_maintenance import _standby  # noqa: E402
from backend.tests.test_rbd_export import WHEN, _run  # noqa: E402

E = sv.Exponential.from_params
TEN_YEARS = 87600.0
SEVEN = math.log(1.07) / 8760  # 7% a year, continuous, per hour (RePyability's own example)


def _one_pump(**costs):
    """RePyability's total_cost example: a pump bought for 20,000, failing
    every 1000 h on average, repaired in 10 h at 500, lost production 100/h."""
    return _series(_pump(costs={"acquisition": 20000}),
                   costs={"downtime_rate": 100, "horizon": TEN_YEARS, **costs})


def _library_pump():
    return RepairableRBD(
        [("s", "p"), ("p", "t")],
        {"p": {"reliability": E([1e-3]), "repairability": E([0.1]), "repair_cost": 500.0,
               "acquisition_cost": 20000.0}},
        input_node="s", output_node="t", downtime_cost_rate=100.0)


# ---------------------------------------------------------------------------
# #219: the total cost of ownership as a present value
# ---------------------------------------------------------------------------
def test_the_total_cost_is_the_librarys_present_value():
    """7% a year over ten years: 114,538 (RePyability's docstring), the
    undiscounted 150,099 beside it."""
    c = ra.analyze_availability(_one_pump(discount_rate=7), simulate=False)["costs"]
    assert c["discount_rate"] == 7 and c["discount_rate_per_unit"] == pytest.approx(SEVEN, rel=1e-15)
    lib = _library_pump()
    assert c["total_cost"] == pytest.approx(lib.total_cost(TEN_YEARS, discount_rate=SEVEN), rel=1e-12)
    assert round(c["total_cost"]) == 114538 and round(c["undiscounted_total_cost"]) == 150099
    assert c["running_cost"] == pytest.approx(c["total_cost"] - 20000, rel=1e-12)
    # Undiscounted (no rate, or 0): as before, no discount fields.
    for costs in ({}, {"discount_rate": 0}):
        plain = ra.analyze_availability(_one_pump(**costs), simulate=False)["costs"]
        assert round(plain["total_cost"]) == 150099
        assert plain["discount_rate"] is None and plain["undiscounted_total_cost"] is None


@pytest.mark.parametrize("unit, per_hour", [("days", 24), ("Weeks", 168), ("years", 8760)])
def test_the_rate_follows_the_diagrams_time_unit(unit, per_hour):
    """The same pump in days, weeks or years — its rates, downtime cost and
    horizon rescaled — has the same present value at 7% a year."""
    pump = _node("pump", model=_exp(1e-3 * per_hour), repair=_exp(0.1 * per_hour),
                 costs={"repair": 500, "acquisition": 20000})
    g = _series(pump, unit=unit, costs={"downtime_rate": 100 * per_hour, "horizon": TEN_YEARS / per_hour,
                                        "discount_rate": 7})
    c = ra.analyze_availability(g, simulate=False)["costs"]
    assert c["total_cost"] == pytest.approx(114538.2028066, rel=1e-9)
    assert c["discount_rate_per_unit"] == pytest.approx(SEVEN * per_hour, rel=1e-12)


@pytest.mark.parametrize("unit", ["cycles", "km", ""])
def test_a_non_calendar_unit_cannot_be_discounted(unit):
    g = _one_pump(discount_rate=7)
    g["unit"] = unit
    v = ra.validate_graph(g)
    assert not v["valid"] and any("calendar time unit" in e for e in v["errors"]), v["errors"]
    with pytest.raises(AnalysisError, match="calendar time unit"):
        rbd_maintenance.discount(g)
    # ...unless it is cleared.
    g["costs"]["discount_rate"] = 0
    assert ra.validate_graph(g)["valid"]


@pytest.mark.parametrize("rate, needle", [(-1, "non-negative"), (101, "at most 100%"), ("x", "a number")])
def test_bad_discount_rates_are_clear_errors(rate, needle):
    v = ra.validate_graph(_one_pump(discount_rate=rate))
    assert not v["valid"] and any(needle in e for e in v["errors"]), v["errors"]


def test_the_discount_rate_is_in_the_cache_key():
    assert availability_cache_key(_one_pump(discount_rate=7)) != availability_cache_key(_one_pump())


def test_with_discount_reprices_a_result_without_running_it_again():
    c = ra.analyze_availability(_one_pump(), simulate=False)["costs"]
    g = _one_pump()
    assert rbd_costs.with_discount(c, g, 7)["total_cost"] == pytest.approx(
        _library_pump().total_cost(TEN_YEARS, discount_rate=SEVEN), rel=1e-12)
    assert rbd_costs.with_discount(c, g, 0)["total_cost"] == pytest.approx(c["total_cost"], rel=1e-15)
    assert rbd_costs.with_discount(c, g, None) is c


@pytest.mark.parametrize("pct", [7, 30])
def test_cheapest_design_is_the_lowest_present_value(pct):
    """Against the library's total_cost of every design: the second pump pays
    at 7% a year but not at 30%, where the downtime it saves later is worth
    less than its price now."""
    r = math.log1p(pct / 100) / 8760
    g = _one_pump(discount_rate=pct)
    out = rbd_costs.cheapest_design(g)
    totals = {n: ra._build_repairable_rbd(rbd_costs.apply_copies(g, {"pump": n}))[0].total_cost(
        TEN_YEARS, discount_rate=r) for n in range(1, 6)}
    best = min(totals, key=totals.get)
    assert out["design"]["units"] == {"pump": best} and best == (2 if pct == 7 else 1)
    assert out["design"]["total_cost"] == pytest.approx(totals[best], rel=1e-9)
    assert out["current"]["total_cost"] == pytest.approx(totals[1], rel=1e-12)
    assert out["discount_rate"] == pct and out["discount_rate_per_unit"] == pytest.approx(r, rel=1e-15)
    # The request's rate overrides the diagram's; 0 is undiscounted.
    flat = rbd_costs.cheapest_design(g, discount_rate=0)
    assert flat["discount_rate"] is None and round(flat["design"]["total_cost"]) == 127591


def test_cheapest_design_endpoint_takes_a_discount_rate(client):
    client.act_as(PRO)
    res = client.post("/api/rbds/design/cheapest", json={"graph": _plant(), "discount_rate": 30})
    assert res.status_code == 200, res.text
    assert res.json()["discount_rate"] == 30 and res.json()["design"]["units"] == {"pump": 1, "valve": 2}
    bad = client.post("/api/rbds/design/cheapest",
                      json={"graph": {**_plant(), "unit": "cycles"}, "discount_rate": 7})
    assert bad.status_code == 422 and "calendar time unit" in bad.json()["detail"]


def test_export_discounts_the_total_as_the_app_does(tmp_path):
    g = _one_pump(discount_rate=7)
    app = ra.analyze_availability(g, n_simulations=60)
    code = rbd_export.to_python(g, "Discounted", exported_at=WHEN)
    assert f"DISCOUNT_RATE = {SEVEN!r}" in code or "DISCOUNT_RATE = 7.7235900084" in code
    res, proc = _run(code, tmp_path, n_sims="60")
    c = res["costs"]
    assert c["total_cost"] == pytest.approx(app["costs"]["total_cost"], rel=1e-12)
    assert c["undiscounted_total_cost"] == pytest.approx(app["costs"]["undiscounted_total_cost"], rel=1e-12)
    assert c["discount_rate"] == 7
    assert "present value at 7% a year" in proc.stdout
    # Undiscounted diagrams export a zero rate and the same total as before.
    plain = rbd_export.to_python(_one_pump(), "Plain", exported_at=WHEN)
    assert "DISCOUNT_RATE = 0.0" in plain


# ---------------------------------------------------------------------------
# #219 over MCP: set the rate, read the present value, find the design
# ---------------------------------------------------------------------------
def _m(dist, **params):
    return {"distribution_id": dist, "params": [{"name": k, "value": v} for k, v in params.items()]}


def _mcp_pump(env):
    return _ok(_call(env.token[A], "create_rbd", {
        "name": "Pump", "unit": "Hours", "repairable": True,
        "nodes": [{"id": "input", "type": "input"}, {"id": "output", "type": "output"},
                  {"id": "pump", "type": "component", "label": "Pump", "model": _m("exponential", failure_rate=1e-3),
                   "repair": _m("exponential", failure_rate=0.1), "costs": {"repair": 500, "acquisition": 20000}}],
        "edges": [{"source": "input", "target": "pump"}, {"source": "pump", "target": "output"}]}))["id"]


def test_mcp_discounted_costs_and_cheapest_design(env):
    rid = _mcp_pump(env)
    out = _ok(_edit(env, rid, {"op": "set", "costs": {"downtime_rate": 100, "horizon": TEN_YEARS,
                                                      "discount_rate": 7}}))
    assert "discount rate 7% a year" in out["applied"][0]
    assert _doc(env, rid)["graph"]["costs"] == {"downtime_rate": 100.0, "horizon": TEN_YEARS, "discount_rate": 7.0}

    res = _ok(_call(env.token[A], "analyze_rbd", {"rbd_id": rid, "simulate": False}))
    c = res["costs"]
    assert c["present_value"] is True and c["discount_rate"] == 7
    assert round(c["total_cost"]) == 114538 and round(c["undiscounted_total_cost"]) == 150099
    # Another rate for this answer only: nothing saved, nothing re-run.
    flat = _ok(_call(env.token[A], "analyze_rbd", {"rbd_id": rid, "simulate": False, "discount_rate": 0}))["costs"]
    assert flat["present_value"] is False and round(flat["total_cost"]) == 150099
    assert _doc(env, rid)["graph"]["costs"]["discount_rate"] == 7.0

    design = _ok(_call(env.token[A], "cheapest_design", {"rbd_id": rid}))
    assert design["available"] and design["present_value"] and design["discount_rate"] == 7
    assert design["design"]["blocks"][0]["copies"] == 2 and design["changed"]
    assert round(design["design"]["total_cost"]) == round(rbd_costs.cheapest_design(
        _doc(env, rid)["graph"])["design"]["total_cost"])
    steep = _ok(_call(env.token[A], "cheapest_design", {"rbd_id": rid, "discount_rate": 30}))
    assert not steep["changed"] and steep["design"]["blocks"][0]["copies"] == 1

    # 0 clears a field; the rest are kept.
    _ok(_edit(env, rid, {"op": "set", "costs": {"discount_rate": 0}}))
    assert _doc(env, rid)["graph"]["costs"] == {"downtime_rate": 100.0, "horizon": TEN_YEARS}


def test_mcp_discount_errors_and_plan(env, monkeypatch):
    from backend.services import billing

    rid = _mcp_pump(env)
    _ok(_edit(env, rid, {"op": "set", "costs": {"downtime_rate": 100, "horizon": TEN_YEARS}}))
    # A non-calendar unit can't be discounted: nothing is saved.
    msg = _err(_edit(env, rid, {"op": "set", "unit": "Cycles", "costs": {"discount_rate": 7}}))
    assert "calendar time unit" in msg and "discount_rate" not in _doc(env, rid)["graph"]["costs"]
    assert "discount_rate" in _err(_call(env.token[A], "cheapest_design", {"rbd_id": rid, "discount_rate": 250}))
    # Paid as in the app.
    monkeypatch.setattr(billing, "premium_compute_allowed", lambda db, user: False)
    out = _ok(_call(env.token[A], "cheapest_design", {"rbd_id": rid}))
    assert out["available"] is False and out["code"] == "pro_required"


def test_mcp_cheapest_design_refuses_a_reliability_diagram(env):
    rid = _ok(_call(env.token[A], "create_rbd", {
        "name": "R", "nodes": [{"id": "input", "type": "input"}, {"id": "output", "type": "output"},
                               {"id": "a", "type": "component", "model": _m("exponential", failure_rate=1e-3)}],
        "edges": [{"source": "input", "target": "a"}, {"source": "a", "target": "output"}]}))["id"]
    assert "non-repairable" in _err(_call(env.token[A], "cheapest_design", {"rbd_id": rid}))
    assert "non-repairable" in _err(_call(env.token[A], "analyze_rbd", {"rbd_id": rid, "discount_rate": 7}))


# ---------------------------------------------------------------------------
# #222: repair crews around a nested sub-diagram, exact over time
# ---------------------------------------------------------------------------
WINDOW = 500.0


def _crews_around_a_sub_diagram(crews=1):
    """Two exponential blocks shared by the diagram's crews, in series with a
    cold 1+2 standby bank that has its own repairer (a nested RBD)."""
    g = _series(_node("a", model=_exp(0.01), repair=_exp(0.2), costs={"repair": 100}),
                _node("b", model=_exp(0.02), repair=_exp(0.3), costs={"repair": 50}),
                _standby("bank", repair_one_at_a_time=True), costs={"downtime_rate": 10})
    if crews:
        g["repair_crews"] = {"crews": crews}
    return g


def _library(crews=1):
    bank = RepairableRBD(
        [("in", "bank"), ("bank", "out")],
        {"bank": {"reliability": E([0.01]), "repairability": E([0.1]),
                  "standby": {"units": 3, "k": 1, "dormancy_factor": 0.0, "switching_probability": 1.0}}},
        repair_crews=1)
    return RepairableRBD(
        [("s", "a"), ("a", "b"), ("b", "bank"), ("bank", "t")],
        {"a": {"reliability": E([0.01]), "repairability": E([0.2]), "repair_cost": 100.0},
         "b": {"reliability": E([0.02]), "repairability": E([0.3]), "repair_cost": 50.0},
         "bank": bank},
        input_node="s", output_node="t", repair_crews=crews, downtime_cost_rate=10.0)


def test_crews_around_a_sub_diagram_are_exact_over_time():
    g = _crews_around_a_sub_diagram()
    ex = ra.exact_availability(g, horizon=WINDOW)
    assert ex["status"] == "ok", ex.get("message")
    assert ex["method"]["expected_failures"] == "numerical" and ex["method"]["curve"] == "numerical"
    lib = _library()
    events = lib.expected_events(WINDOW)
    assert ex["expected_failures"] == pytest.approx(events.system_failures, rel=1e-9)
    assert ex["downtime"] == pytest.approx(events.system_downtime, rel=1e-9)
    assert ex["cost"]["mean"] == pytest.approx(lib.expected_cost(WINDOW).mean, rel=1e-9)
    assert ex["curve"]["availability"] == pytest.approx(
        list(lib.point_availability(ex["curve"]["t"])), rel=1e-9, abs=1e-12)
    # The long run is the crews' chain, exactly; the window cost is priced.
    r = ra.analyze_availability(g, simulate=False)
    assert r["long_run_method"]["route"] == "exact"
    assert r["steady_state_availability"] == pytest.approx(lib.mean_availability(), rel=1e-12)
    assert r["costs"]["cost_rate"] == pytest.approx(lib.expected_cost_rate(), rel=1e-12)
    assert r["repair_crews"]["own_repairer"] == ["BANK"] and r["repair_crews"]["limited"] is True


def test_a_crew_for_every_job_gives_the_independent_values():
    """Two jobs (a, b) and two crews: no job waits, so the chain gives the
    values of unlimited crews (RePyability: to 1e-7)."""
    two = ra.exact_availability(_crews_around_a_sub_diagram(crews=2), horizon=WINDOW)
    free = ra.exact_availability(_crews_around_a_sub_diagram(crews=None), horizon=WINDOW)
    for key in ("expected_failures", "downtime", "mission_availability"):
        assert two[key] == pytest.approx(free[key], rel=1e-6), key
    assert two["cost"]["mean"] == pytest.approx(free["cost"]["mean"], rel=1e-6)
    # One crew makes the jobs wait: more downtime.
    one = ra.exact_availability(_crews_around_a_sub_diagram(), horizon=WINDOW)
    assert one["downtime"] > two["downtime"]


def test_export_with_crews_around_a_sub_diagram_has_the_exact_figures(tmp_path):
    g = _crews_around_a_sub_diagram()
    code = rbd_export.to_python(g, "Crews", exported_at=WHEN)
    assert "repair_crews=1)" in code and "def exact_over_window" in code
    app = ra.analyze_availability(g, n_simulations=40)
    exact = ra.exact_availability(g)
    res, proc = _run(code, tmp_path, n_sims="40")
    assert "No exact availability over time" not in proc.stdout and "Exact over" in proc.stdout
    assert res["exact"]["expected_failures"] == pytest.approx(exact["expected_failures"], rel=1e-9)
    assert res["exact"]["mission_availability"] == pytest.approx(exact["mission_availability"], rel=1e-9)
    assert res["exact"]["cost"] == pytest.approx(exact["cost"]["mean"], rel=1e-9)
    assert res["costs"]["cost_rate"] == pytest.approx(app["costs"]["cost_rate"], rel=1e-12)


def test_mcp_analyze_rbd_gives_crews_around_a_sub_diagram_exactly(env):
    exp = _m("exponential", failure_rate=0.01)
    rid = _ok(_call(env.token[A], "create_rbd", {
        "name": "Crews", "unit": "Hours", "repairable": True, "repair_crews": 1,
        "nodes": [{"id": "input", "type": "input"}, {"id": "output", "type": "output"},
                  {"id": "a", "type": "component", "model": exp, "repair": _m("exponential", failure_rate=0.2)},
                  {"id": "bank", "type": "standby", "model": exp, "repair": _m("exponential", failure_rate=0.1),
                   "spares": 2, "dormancy": 0, "repair_one_at_a_time": True}],
        "edges": [{"source": "input", "target": "a"}, {"source": "a", "target": "bank"},
                  {"source": "bank", "target": "output"}]}))["id"]
    res = _ok(_call(env.token[A], "analyze_rbd", {"rbd_id": rid, "simulate": False, "t_max": WINDOW}))
    assert res["available"] is True and not res.get("needs_simulation")
    assert res["exact"]["status"] == "ok" and res["exact"]["expected_failures"] > 0
