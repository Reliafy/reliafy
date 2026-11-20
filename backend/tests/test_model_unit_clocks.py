"""A saved model meeting another clock of the same kind is converted (model_units):
Strategy answers, Compare two models, RCM evidence and Maintenance class proposals."""

from __future__ import annotations

import numpy as np
import pytest
import surpyval as sp

from backend.services import model_units, strategy
from backend.tests.test_mcp import A, _call, _ok, env  # noqa: F401 - env is a fixture

MONTH = 365.25 / 12
X_DAYS = np.array([120.0, 300, 450, 610, 800, 950, 1200, 1500, 1700, 2100])
C = np.array([0, 0, 0, 1, 0, 0, 0, 1, 0, 0])


def _params(fit):
    return [{"name": n, "value": float(v)} for n, v in zip(fit.dist.parameter_names, fit.params)]


# ---- Strategy: a days model asked in months equals the refit in months --------------------

def test_optimal_replacement_in_months_equals_the_refit_in_months():
    days, months = sp.Weibull.fit(X_DAYS, C), sp.Weibull.fit(X_DAYS / MONTH, C)
    params, extras, conv = model_units.convert_spec("weibull", _params(days), None, "Days", "Months")
    assert conv["factor"] == pytest.approx(1 / MONTH)
    got = strategy.optimal_replacement("weibull", params, 100.0, 2000.0, unit="Months")
    want = strategy.optimal_replacement("weibull", _params(months), 100.0, 2000.0, unit="Months")
    # The lowest cost rate agrees to 1e-9. The age it's reached at sits on a flat minimum, so the
    # optimiser places it only to about the square root of the rounding in the two models' last
    # digits (~1e-8): the same model in two units can't agree more closely than that there.
    assert got["optimal_cost_rate"] == pytest.approx(want["optimal_cost_rate"], rel=1e-9)
    assert got["run_to_failure_cost_rate"] == pytest.approx(want["run_to_failure_cost_rate"], rel=1e-9)
    assert got["mttf"] == pytest.approx(want["mttf"], rel=1e-9)
    assert got["optimal_time"] == pytest.approx(want["optimal_time"], rel=1e-6)
    assert model_units.used_note(conv) == \
        "model in days, answer in months: converted at 1 month = 30.4375 days, at 365.25 / 12 days a month"


def test_failure_finding_in_months_equals_the_refit_in_months():
    days, months = sp.Weibull.fit(X_DAYS, C), sp.Weibull.fit(X_DAYS / MONTH, C)
    params, _, _ = model_units.convert_spec("weibull", _params(days), None, "Days", "Months")
    got = strategy.failure_finding("weibull", params, 0.95, unit="Months")
    want = strategy.failure_finding("weibull", _params(months), 0.95, unit="Months")
    assert got["interval"] == pytest.approx(want["interval"], rel=1e-9)


def test_a_parameters_interval_converts_with_it():
    params, _, _ = model_units.convert_spec(
        "exponential", [{"name": "failure_rate", "value": 0.01, "ci": [0.005, 0.02]}], None, "Days", "Hours")
    assert params[0]["value"] == pytest.approx(0.01 / 24)
    assert params[0]["ci"] == pytest.approx([0.005 / 24, 0.02 / 24])


@pytest.mark.parametrize("model_unit,asked", [("Cycles", "Hours"), ("", "Months"), ("Days", ""), ("Days", "Days")])
def test_other_kinds_and_blank_units_are_left_as_given(model_unit, asked):
    params = [{"name": "alpha", "value": 100.0}, {"name": "beta", "value": 2.0}]
    out, _, conv = model_units.convert_spec("weibull", params, None, model_unit, asked)
    assert conv is None and out == params


def test_the_mcp_calculator_converts_a_saved_model_asked_in_another_unit(env):
    """The pumps sample is fitted in months: asked in days, the answer is the same life in days, and
    says so; asked in its own unit, nothing changes."""
    from backend.services import samples as samples_service

    samples_service.seed_samples(env.db)
    token = env.token[A]
    own = _ok(_call(token, "analyse", {"action": "optimal_replacement", "model_id": "sample-model-pumps-weibull",
                                       "planned_cost": 100, "unplanned_cost": 2000}))
    days = _ok(_call(token, "analyse", {"action": "optimal_replacement", "model_id": "sample-model-pumps-weibull",
                                        "planned_cost": 100, "unplanned_cost": 2000, "unit": "days"}))
    assert "unit_conversion" not in own
    assert days["unit_conversion"].startswith("model in months, answer in days: converted at 1 month = 30.4375 days")
    assert days["optimal_time"] == pytest.approx(own["optimal_time"] * MONTH, rel=1e-6)
    assert days["unit"] == "days"


# ---- Compare two models --------------------------------------------------------------------

def test_compare_two_converts_a_side_in_another_unit():
    days, months = sp.Weibull.fit(X_DAYS, C), sp.Weibull.fit(X_DAYS / MONTH, C)
    a = {"label": "Pump A", "kind": "parametric", "distribution_id": "weibull", "params": _params(days),
         "unit": "Days"}
    b_months = {"label": "Pump B", "kind": "parametric", "distribution_id": "weibull", "params": _params(months),
                "unit": "Months"}
    b_days = {**b_months, "params": _params(days), "unit": "Days"}
    got = strategy.compare_two(a, b_months)
    want = strategy.compare_two(a, b_days)
    assert got["unit"] == "Days"
    np.testing.assert_allclose(got["b"]["sf"], want["b"]["sf"], atol=1e-9)
    assert got["b"]["metrics"]["b10"] == pytest.approx(want["b"]["metrics"]["b10"], rel=1e-9)
    assert got["unit_conversions"] == [
        "Pump B: model in months, comparison in days: converted at 1 month = 30.4375 days, at 365.25 / 12 days a month."]
    assert got["factors"] == {"b": pytest.approx(MONTH)}
    # Sides with no unit, or of another kind, are compared as given (as before).
    plain = strategy.compare_two({**a, "unit": None}, {**b_months, "unit": "Cycles"}, unit="Days")
    assert "unit_conversions" not in plain


# ---- Maintenance class proposals -------------------------------------------------------------

def test_a_class_model_in_km_proposes_for_a_task_in_miles():
    import mongomock

    from backend.maintenance import loop
    from backend.maintenance.service import PROJECTORS, Maintenance, class_id
    from backend.maintenance.store import GraphStore
    from backend.tests.rcm_tree import position_with_rcm

    def proposals(task_unit):
        m = Maintenance(GraphStore(":memory:", PROJECTORS), "user-k", "tester")
        functions = [{"id": "f", "text": "Haul", "failures": [{"id": "ff", "text": "Stops", "modes": [
            {"id": "m1", "text": "Tyre worn", "consequence": "operational",
             "decision": {"outcome": "fixed_interval", "interval": 9000, "interval_unit": task_unit,
                          "task": "Replace tyres"}}]}]}]
        pos = position_with_rcm(m, functions, "Truck")["position"]
        m.update_position(pos["id"], name="Truck 1", position_class="Haul truck")
        m.set_class_costs("Haul truck", planned_cost=400, failure_cost=4000)
        key = m._resolve_class("Haul truck")
        node = m.s.node(m.org, class_id(m.org, key))
        # A class model by use, in km (as fit_class_model saves one from a km counter).
        model = {"distribution": "weibull", "unit": "km", "failures": 8, "suspensions": 2,
                 "params": [{"name": "alpha", "value": 60000.0}, {"name": "beta", "value": 3.0}]}
        m.s.patch_node(m.org, node["id"], {"model": model})
        return loop.propose(m, "Haul truck"), model

    best_km = strategy.optimal_replacement("weibull", [{"name": "alpha", "value": 60000.0},
                                                       {"name": "beta", "value": 3.0}], 400, 4000, "km")["optimal_time"]
    (in_km,), _ = proposals("km")
    (in_miles,), _ = proposals("miles")
    assert in_km["proposed"]["interval"] == round(best_km)
    assert in_miles["proposed"]["interval"] == round(best_km / 1.609344)
    assert in_miles["proposed"]["unit"] == "miles"
    assert "(Model in kilometres, task in miles: converted at 1 mile = 1.60934 kilometres.)" in in_miles["reason"]
    assert "converted" not in in_km["reason"]
    # A distance never converts to a task on the calendar.
    assert proposals("days")[0] == []
