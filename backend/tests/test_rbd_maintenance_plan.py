"""The Maintenance plan's backend: a block's duty (the share of the time it
runs), replacements given in operating time, the planned/unplanned split and
what the scheduled replacements buy against running to failure."""

import math

import matplotlib

matplotlib.use("Agg")

import pytest  # noqa: E402

from backend.services import rbd_analysis as ra  # noqa: E402
from backend.services import rbd_edit, rbd_export, rbd_graph, rbd_intervals, rbd_maintenance  # noqa: E402
from backend.services.rbd_analysis import AnalysisError  # noqa: E402
from backend.tests.test_rbd_costs import N, _ln, _node, _series, _w  # noqa: E402


def _pump(**extra):
    """A wear-out pump (life in operating hours), replaced on failure for
    5000, down ~23 h, with lost production at 500/h."""
    p = _node("p", model=_w(1000, 2.5), repair=_ln(3.0, 0.5), costs={"replace": 5000}, **extra)
    return _series(p, costs={"downtime_rate": 500})


def test_a_duty_stretches_the_life_onto_the_calendar():
    """Running a quarter of the time, a 1000 h (operating) life is a 4000 h
    life on the calendar: the same as the calendar model, exactly."""
    duty = ra.analyze_availability(_pump(duty=0.25), n_simulations=N)
    calendar = ra.analyze_availability(
        _series(_node("p", model=_w(4000, 2.5), repair=_ln(3.0, 0.5), costs={"replace": 5000}),
                costs={"downtime_rate": 500}), n_simulations=N)
    assert duty["availability_basis"] == "exact"
    assert duty["steady_state_availability"] == pytest.approx(calendar["steady_state_availability"], rel=1e-9)
    # A duty of 1 (all the time) changes nothing.
    full = ra.analyze_availability(_pump(duty=1), n_simulations=N)
    plain = ra.analyze_availability(_pump(), n_simulations=N)
    assert full["steady_state_availability"] == pytest.approx(plain["steady_state_availability"], rel=1e-12)


def test_an_operating_time_interval_goes_through_the_duty():
    pm = {"policy": "age", "operating_interval": 580, "interval": 1, "duration": 7, "cost": 1000}
    by_duty = ra.analyze_availability(_pump(duty=0.5, preventive=pm), n_simulations=N)
    on_clock = ra.analyze_availability(
        _pump(duty=0.5, preventive={**pm, "interval": 1160, "operating_interval": None}), n_simulations=N)
    assert by_duty["steady_state_availability"] == pytest.approx(on_clock["steady_state_availability"], rel=1e-12)
    spec = rbd_maintenance.preventive_spec({"duty": 0.5, "preventive": pm}, "P")
    assert spec["interval"] == pytest.approx(1160)


def test_an_operating_time_interval_without_a_duty_is_refused_in_plain_words():
    data = {"preventive": {"policy": "age", "operating_interval": 500}}
    with pytest.raises(AnalysisError, match="has no duty"):
        rbd_maintenance.preventive_spec(data, "Pump")
    errors = rbd_maintenance.validation_errors(_pump(**data))
    assert any("Set its duty" in e for e in errors)


@pytest.mark.parametrize("duty", [0, -0.2, 1.5, "lots"])
def test_a_bad_duty_is_a_clear_error(duty):
    errors = rbd_maintenance.validation_errors(_pump(duty=duty))
    assert errors and "duty" in errors[0]


def test_duty_travels_through_the_graph_format_edits_and_export():
    compact = {"repairable": True, "unit": "hours",
               "nodes": [{"id": "input", "type": "input"}, {"id": "output", "type": "output"},
                         {"id": "p", "type": "component", "label": "Pump", "duty": 0.25,
                          "model": {"distribution_id": "weibull",
                                    "params": [{"name": "alpha", "value": 1000}, {"name": "beta", "value": 2.5}]},
                          "repair": {"distribution_id": "exponential",
                                     "params": [{"name": "failure_rate", "value": 0.1}]}}],
               "edges": [{"source": "input", "target": "p"}, {"source": "p", "target": "output"}]}
    graph = rbd_graph.normalize_graph(compact)
    node = next(n for n in graph["nodes"] if n["id"] == "p")
    assert node["data"]["duty"] == 0.25
    edited = rbd_edit.apply_ops(graph, [{"op": "update_node", "id": "p", "duty": 0.5}], "Duty").graph
    assert next(n for n in edited["nodes"] if n["id"] == "p")["data"]["duty"] == 0.5
    cleared = rbd_edit.apply_ops(edited, [{"op": "update_node", "id": "p", "clear": ["duty"]}], "Duty").graph
    assert "duty" not in next(n for n in cleared["nodes"] if n["id"] == "p")["data"]
    code = rbd_export.to_python(edited, "Duty")
    assert '"duty": 0.5' in code


def test_applying_an_interval_keeps_an_operating_time_basis():
    g = _pump(duty=0.5, preventive={"policy": "age", "interval": 1000, "operating_interval": 500})
    out = rbd_intervals.apply_plan(g, [{"id": "p", "interval": 800}])
    pm = next(n for n in out["nodes"] if n["id"] == "p")["data"]["preventive"]
    assert pm["interval"] == 800 and pm["operating_interval"] == pytest.approx(400)


def test_planned_and_unplanned_split_downtime_and_cost():
    r = ra.analyze_availability(
        _pump(preventive={"policy": "age", "interval": 580, "duration": 7, "cost": 1000}), n_simulations=N)
    pu = r["planned_unplanned"]
    d = r["downtime"]
    assert pu["downtime"]["planned"] == pytest.approx(d["maintenance"])
    assert pu["downtime"]["unplanned"] == pytest.approx(d["failures"])
    cats = r["costs"]["by_category"]
    lost = cats["system_downtime"]
    c = pu["cost"]
    # Lost production is shared out as the downtime is.
    assert c["lost_production"]["planned"] == pytest.approx(lost * d["maintenance"] / d["total"])
    assert c["planned"] == pytest.approx(cats["preventive"] + c["lost_production"]["planned"])
    assert c["unplanned"] == pytest.approx(cats["replace"] + c["lost_production"]["unplanned"])
    assert c["planned"] + c["unplanned"] + c["not_split"] == pytest.approx(r["costs"]["cost_rate"], rel=1e-9)


def test_what_the_plan_buys_against_running_to_failure():
    pm = {"policy": "age", "interval": 580, "duration": 7, "cost": 1000}
    r = ra.analyze_availability(_pump(preventive=pm), n_simulations=N)
    rtf = ra.analyze_availability(_pump(), n_simulations=N)
    e = r["plan_effect"]
    assert e["available"] and e["basis"] == "exact"
    assert e["units_per_year"] == 8760
    (row,) = e["blocks"]
    assert row["id"] == "p" and row["failures_avoided"] > 0
    mttf, mttr = 1000 * math.gamma(1 + 1 / 2.5), math.exp(3.0 + 0.5**2 / 2)
    assert row["failures_run_to_failure"] == pytest.approx(1 / (mttf + mttr), rel=1e-6)
    assert e["unavailability"]["run_to_failure"] == pytest.approx(1 - rtf["steady_state_availability"], rel=1e-9)
    assert e["cost_rate"]["run_to_failure"] == pytest.approx(rtf["costs"]["cost_rate"], rel=1e-9)
    assert e["cost_rate"]["with_plan"] < e["cost_rate"]["run_to_failure"]
    # Nothing scheduled: nothing to compare.
    assert "plan_effect" not in rtf


def test_what_the_plan_buys_says_why_when_it_isnt_exact():
    g = _pump(preventive={"policy": "age", "interval": 580, "duration": 7}, repair_quality={"model": "kijima1", "q": 0.5})
    r = ra.analyze_availability(g, n_simulations=60)
    e = r.get("plan_effect")
    assert e is not None and e["available"] is False and e["reason"]
