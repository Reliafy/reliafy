"""The strategy and forecast answers, checked against hand-worked numbers.

Each case is a maintenance question with its numbers worked out independently
(numerical integration, a renewal-reward simulation): replacing impellers by
age, how often to bench-test relief valves, a crusher liner at the next shut or
a later one, and a fleet's budget under planned replacement.
"""

import math

import numpy as np
import pytest
import surpyval

from backend.services import fleet as fleet_service
from backend.services import fleet_strategy
from backend.services import strategy as st
from backend.services import strategy_calendar
from backend.services import strategy_store
from backend.services.strategy import StrategyError

# ---- failure finding: the interval from the model's curve ----------------------------

_VALVE_WEIBULL = [{"name": "alpha", "value": 282.7}, {"name": "beta", "value": 1.27}]
_VALVE_EXP = [{"name": "failure_rate", "value": 0.002491, "ci": [0.00174, 0.00357]}]


def _mean_unavailability(model, t):
    from scipy.integrate import quad

    return 1 - quad(lambda x: float(model.sf(x)), 0, t)[0] / t


def test_failure_finding_on_a_weibull_uses_its_curve_not_two_one_minus_a_mttf():
    """A Weibull (β 1.27) valve renewed at each bench test holds 99% at about
    14.4 months; 2(1 − A)·MTTF says 5.25, nearly three times as many tests."""
    r = st.failure_finding("weibull", _VALVE_WEIBULL, 0.99, "Months")
    model = surpyval.Weibull.from_params([282.7, 1.27])
    assert _mean_unavailability(model, r["interval"]) == pytest.approx(0.01, rel=1e-6)
    assert r["interval"] == pytest.approx(14.43, abs=0.02)
    assert r["shortcut_interval"] == pytest.approx(5.25, abs=0.01)
    assert r["method"] == "mean_unavailability" and r["renewed_at_test"] is True
    assert any("constant failure rate" in w for w in r["warnings"])
    # A test that leaves a working valve as it was: the other answer, said beside it.
    kept = st.failure_finding("weibull", _VALVE_WEIBULL, 0.99, "Months", renewed_at_test=False)
    assert kept["interval"] == pytest.approx(r["other_interval"]) and kept["interval"] < 6


def test_failure_finding_exponential_is_exact_and_bounded_one_sided():
    """Exponential: exact (8.08 months at 99%, the shortcut's 8.03 is a
    first-order approximation), and at 90%, 95%, 99.5% too; the cautious end is
    the interval at the rate's 90% one-sided upper bound."""
    r = st.failure_finding("exponential", _VALVE_EXP, 0.99, "Months")
    assert r["interval"] == pytest.approx(8.08, abs=0.01)
    assert r["warnings"] == []
    for target, months in ((0.995, 4.03), (0.95, 41.5), (0.90, 86.1)):
        assert st.failure_finding("exponential", _VALVE_EXP, target)["interval"] == pytest.approx(months, abs=0.06)
    bound = r["interval_bound"]
    # The stored interval is 90% two-sided (z 1.645); the one-sided 90% bound is at z 1.2816.
    se = math.log(0.00357 / 0.002491) / 1.6448536269514722
    upper = 0.002491 * math.exp(1.2815515655446004 * se)
    assert bound["value"] == pytest.approx(upper, rel=1e-6) and bound["side"] == "one-sided"
    exact = st.failure_finding("exponential", [{"name": "failure_rate", "value": upper}], 0.99)["interval"]
    assert bound["interval"] == pytest.approx(exact, rel=1e-6)
    assert 6.0 < bound["interval"] < 6.3  # six-monthly tests hold the target on the cautious end
    # Typed-in parameters carry no bounds, and say so.
    typed = st.failure_finding("exponential", [{"name": "failure_rate", "value": 0.002491}], 0.99)
    assert typed["interval_bound"] is None and "No bound" in typed["bound_note"]


def test_failure_finding_test_time_and_cost():
    r = st.failure_finding("exponential", _VALVE_EXP, 0.99, "Months", test_duration=0.01, test_cost=500)
    # Time off-line counts as unavailable: the interval shortens.
    assert r["interval"] < st.failure_finding("exponential", _VALVE_EXP, 0.99, "Months")["interval"]
    assert r["tests_per_year"] == pytest.approx(12 / (r["interval"] + 0.01))
    assert r["tests_cost_per_year"] == pytest.approx(500 * r["tests_per_year"])
    with pytest.raises(StrategyError, match="off-line"):
        st.failure_finding("exponential", _VALVE_EXP, 0.999, "Months", test_duration=2)


def test_saved_failure_finding_keeps_its_new_inputs():
    inputs = {"distribution_id": "exponential", "params": _VALVE_EXP, "target_availability": 0.99,
              "unit": "Months", "test_cost": 300, "renewed_at_test": False, "model_id": "m1", "model_name": "PSV"}
    out = strategy_store.compute("failure_finding", inputs)
    assert out["test_cost"] == 300 and out["renewed_at_test"] is False


# ---- optimal replacement: block replacement, the saving a year, the range -------------

_IMPELLER = [{"name": "alpha", "value": 4146.7, "ci": [3660.0, 4700.0]},
             {"name": "beta", "value": 3.073, "ci": [2.40, 3.93]}]


def test_replacement_adds_block_replacement_and_the_saving_a_year():
    r = st.optimal_replacement("weibull", _IMPELLER, 2500, 14000, "Hours", use_per_year=6000, units=30)
    assert r["optimal_time"] == pytest.approx(1999, abs=2)
    assert r["optimal_cost_rate"] == pytest.approx(1.878, abs=1e-3)
    assert r["run_to_failure_cost_rate"] == pytest.approx(3.777, abs=1e-3)
    # Block replacement: (cp + cu M(T)) / T, M the renewal count — 1,934 h, $1.958 an hour.
    assert r["block"]["optimal_time"] == pytest.approx(1934, abs=5)
    assert r["block"]["optimal_cost_rate"] == pytest.approx(1.958, abs=2e-3)
    assert len(r["curve"]["block_cost_rate"]) == len(r["curve"]["t"])
    y = r["yearly"]
    assert y["saving_per_year"] == pytest.approx(11390, abs=10)
    assert y["fleet_saving_per_year"] == pytest.approx(30 * y["saving_per_year"])
    # The range on the best age across the fit's 90% bounds: 1,760–2,270 h.
    assert r["optimal_time_range"]["lower"] == pytest.approx(1764, abs=5)
    assert r["optimal_time_range"]["upper"] == pytest.approx(2266, abs=5)
    with pytest.raises(StrategyError):
        st.optimal_replacement("weibull", _IMPELLER, 2500, 14000, "Hours", use_per_year=-1)


def test_block_replacement_never_pays_for_a_constant_rate():
    r = st.optimal_replacement("exponential", [{"name": "failure_rate", "value": 1e-3}], 1, 10, "Hours")
    assert r["block"]["beneficial"] is False and r["block"]["optimal_time"] is None


# ---- one unit now: every coming shut is a choice ---------------------------------------

_LINER = [{"name": "alpha", "value": 29.81}, {"name": "beta", "value": 4.461}]
_SHUTS = dict(unit="Weeks", today="2026-11-12", failure_cost=160000, anytime_cost=95000,
              opportunities=[{"name": "Monthly crusher shut", "cost": 45000, "every": 4, "every_unit": "weeks",
                              "start": "2026-11-25"}])


def test_one_unit_now_offers_later_shuts_and_recommends_the_cheapest():
    """A 10-week liner: waiting to 20 Jan ($31,280) beats 25 Nov ($40,020);
    the recommendation agrees with the long-run rule."""
    young = strategy_calendar.calendar_next("weibull", _LINER, age=10, **_SHUTS)
    assert young["best"]["date"] == "2027-01-20"
    assert young["best"]["cost"] == pytest.approx(31280, rel=2e-3)
    nov = next(c for c in young["choices"] if c.get("date") == "2026-11-25")
    assert nov["cost"] == pytest.approx(40019, rel=2e-3)
    assert young["policy_next"]["date"] == young["best"]["date"]
    assert "20 Jan 2027" in young["recommendation"]
    # A 16-week liner: the next shut, with the shut after next on the list too.
    old = strategy_calendar.calendar_next("weibull", _LINER, age=16, **_SHUTS)
    assert old["best"]["date"] == "2026-11-25" and old["best"]["cost"] == pytest.approx(43549, rel=2e-3)
    dec = next(c for c in old["choices"] if c.get("date") == "2026-12-23")
    assert dec["cost"] == pytest.approx(47196, rel=2e-3)
    liner = surpyval.Weibull.from_params([29.81, 4.461])
    assert dec["fail_chance"] == pytest.approx(1 - liner.sf(16 + dec["time"]) / liner.sf(16), rel=1e-6)
    assert dec["fail_chance"] == pytest.approx(0.17, abs=0.005)  # "17% chance it fails before 23 Dec"
    outages = [c for c in old["choices"] if c["kind"] == "outage"]
    assert len(outages) >= 4 and len(outages) <= strategy_calendar._NEXT_SHUTS


def test_a_shutdown_calendar_answer_can_be_saved_exactly(monkeypatch):
    import mongomock

    db = mongomock.MongoClient()["t"]
    inputs = {"distribution_id": "weibull", "params": _LINER, **_SHUTS, "method": "dp", "model_name": "Liners"}
    doc = strategy_store.save_analysis(db, "Crusher liners", "calendar_replacement", inputs, "user-a")
    assert doc.results["kind"] == "calendar_replacement" and doc.results["today"] == "2026-11-12"
    assert strategy_store.headline(doc).endswith(".")
    with pytest.raises(StrategyError, match="exact"):
        strategy_store.save_analysis(db, "x", "calendar_replacement", {**inputs, "method": "sampling"}, "user-a")
    with pytest.raises(StrategyError, match="date"):
        strategy_store.save_analysis(db, "x", "calendar_replacement", {**inputs, "today": None}, "user-a")


# ---- a fleet forecast under planned replacement ----------------------------------------

# W28's 30 slurry pumps: impeller run hours today, 500 hours a month each.
_PUMP_HOURS = [1300, 900, 3350, 2100, 2550, 2900, 3250, 2650, 1800, 550, 3200, 1550, 2400, 3650, 2150, 3650, 150,
               3400, 0, 1950, 1450, 1950, 3750, 2000, 300, 1650, 200, 1200, 3450, 1450]


def _w28(strategy: dict):
    items = [{"id": str(i), "name": f"P{i}", "current_use": h} for i, h in enumerate(_PUMP_HOURS)]
    dist = surpyval.Weibull.from_params([4146.7, 3.073])
    ages = np.array(_PUMP_HOURS, float)
    rates = np.full(len(items), 500.0)
    return fleet_strategy.renewals(dist, ages, rates * 12, rates, 12, items, strategy,
                                   fleet_service._forecast_renewals, 30.4375)


def test_fleet_forecast_under_planned_replacement_counts_planned_parts_and_cost():
    """Change each impeller at 2,000 h: about 9 failures and 86 planned changes
    a year, and the first quarter's catch-up. The cost, $14,000 a failure and
    $2,500 a planned change, against about $680,000 run to failure."""
    age = _w28({"strategy": "age", "replace_at": 2000, "failure_cost": 14000, "planned_cost": 2500})
    s = age["strategy"]
    assert s["kind"] == "age" and s["catch_up"] == sum(h >= 2000 for h in _PUMP_HOURS)
    year = s["yearly"][0]
    assert year["complete"] and (year["from_period"], year["to_period"]) == (1, 12)
    # A simulation of the same fleet (20,000 runs): 85.7 planned, 9.2 failures, $343,600 (90% $287,500–$408,500).
    assert year["planned"]["expected"] == pytest.approx(85.7, abs=1.0)
    assert year["failures"]["expected"] == pytest.approx(9.2, abs=0.5)
    assert year["cost"]["expected"] == pytest.approx(343600, rel=0.02)
    assert year["cost"]["expected"] == pytest.approx(
        14000 * year["failures"]["expected"] + 2500 * year["planned"]["expected"])
    lo, hi = year["cost"]["interval"]
    assert lo == pytest.approx(287500, rel=0.03) and hi == pytest.approx(408500, rel=0.03)
    # The first quarter needs about 27 impellers (not 16): every pump past 2,000 h is changed in month 1.
    q1 = sum(p["parts"]["expected"] for p in s["per_period"][:3])
    assert q1 == pytest.approx(27, abs=0.5)
    assert age["planned"]["catch_up"] == s["catch_up"]
    assert all(r["overdue"] == (h >= 2000) for r, h in zip(age["per_item"], _PUMP_HOURS))

    rtf = _w28({"failure_cost": 14000})
    r = rtf["strategy"]
    assert r["kind"] == "run_to_failure" and r["yearly"][0]["planned"]["expected"] == 0
    assert rtf["expected"] == pytest.approx(r["yearly"][0]["failures"]["expected"], rel=1e-9)
    assert rtf["expected"] == pytest.approx(48.7, abs=0.1) and rtf["interval"] == [44.0, 54.0]
    assert r["yearly"][0]["cost"]["expected"] == pytest.approx(14000 * rtf["expected"])
    assert r["yearly"][0]["cost"]["interval"] == [616000.0, 756000.0]
    # Planned replacement roughly halves the bill, as the cost rates say (1.878 vs 3.777 an hour).
    assert year["cost"]["expected"] < 0.6 * r["yearly"][0]["cost"]["expected"]


def test_fleet_strategy_settings_are_checked():
    clean = fleet_service._clean_settings
    assert "strategy" not in clean({"periods": 12})
    got = clean({"strategy": "age", "replace_at": "2000", "planned_cost": 2500, "failure_cost": 14000})
    assert got["strategy"] == "age" and got["replace_at"] == 2000.0 and got["planned_cost"] == 2500.0
    with pytest.raises(fleet_service.FleetValidationError, match="age to replace at"):
        clean({"strategy": "age"})
    with pytest.raises(fleet_service.FleetValidationError, match="failures with replacement"):
        clean({"strategy": "age", "replace_at": 10, "method": "single"})
    with pytest.raises(fleet_service.FleetValidationError):
        clean({"strategy": "block"})


def test_spares_under_planned_replacement_count_the_planned_parts():
    dist = surpyval.Weibull.from_params([4146.7, 3.073])
    ages = np.array(_PUMP_HOURS, float)
    rates = np.full(len(ages), 500.0)
    opts = {"lead_time": 3, "service_level": 0.95, "stock": 4}
    rtf = fleet_service.spares_answer(opts, "renewals", dist, ages, rates, 12, "months")
    age = fleet_service.spares_answer({**opts, "_replace_at": 2000}, "renewals", dist, ages, rates, 12, "months")
    assert rtf["hold"] == 16
    assert age["hold"] == 29 and "planned replacements" in age["basis"]  # 27 expected, 29 at 95%
