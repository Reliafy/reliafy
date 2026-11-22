"""A task counted in running hours (A19, #365): each replacement and proof test stores its unit as
entered (``basis``: calendar, or "operating" = running hours), goes to RePyability as written with
``"basis": "operating"`` and the block's duty, and the interval tools answer in it. Blocks saved
with ``operating_interval`` give the same numbers as before."""

import json

import matplotlib

matplotlib.use("Agg")

import pytest  # noqa: E402
import surpyval as sv  # noqa: E402
from repyability import RepairableRBD  # noqa: E402

from backend.maintenance import rbd_tree_plan as tp  # noqa: E402
from backend.services import rbd_analysis as ra  # noqa: E402
from backend.services import rbd_export, rbd_graph, rbd_import, rbd_intervals, rbd_json  # noqa: E402
from backend.services import rbd_maintenance as rm  # noqa: E402
from backend.services import rbd_sensitivity  # noqa: E402
from backend.services.rbd_analysis import AnalysisError  # noqa: E402
from backend.tests.test_rbd_costs import N, _ln, _node, _series, _w  # noqa: E402
from backend.tests.test_rbd_export import WHEN, _run  # noqa: E402
from backend.tests.test_rbd_tree_plan import _block_of, _graph, _station, db, m  # noqa: E402,F401


def _pump(**extra):
    """A wear-out pump (life in operating hours), replaced on failure for 5000, 500/h lost."""
    p = _node("p", model=_w(1000, 2.5), repair=_ln(3.0, 0.5), costs={"replace": 5000}, **extra)
    return _series(p, costs={"downtime_rate": 500})


def _figures(graph):
    r = ra.analyze_availability(graph, n_simulations=N)
    assert r["availability_basis"] == "exact"
    return r["steady_state_availability"], r["costs"]["cost_rate"]


# ---------------------------------------------------------------------------
# Replacements: the same numbers before (operating_interval) and after (basis)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("policy", ["age", "block"])
def test_a_replacement_in_running_hours_gives_the_numbers_it_gave_before(policy):
    old = {"policy": policy, "operating_interval": 580, "interval": 1160, "duration": 7, "cost": 1000}
    new = {"policy": policy, "interval": 580, "basis": "operating", "duration": 7, "cost": 1000}
    calendar = {"policy": policy, "interval": 1160, "duration": 7, "cost": 1000}
    before = _figures(_pump(duty=0.5, preventive=old))
    assert _figures(_pump(duty=0.5, preventive=new)) == pytest.approx(before, rel=1e-12)
    assert _figures(_pump(duty=0.5, preventive=calendar)) == pytest.approx(before, rel=1e-12)


def test_condition_based_replacement_in_running_hours():
    run = {"policy": "condition", "interval": 180, "basis": "operating", "threshold": 0.05, "cost": 1000}
    cal = {**run, "interval": 720, "basis": None}
    assert _figures(_pump(duty=0.25, preventive=run)) == pytest.approx(_figures(_pump(duty=0.25, preventive=cal)),
                                                                        rel=1e-12)


def test_a_saved_early_renewal_age_moves_into_running_hours_with_the_interval():
    data = {"duty": 0.5, "maintenance_group": "north",
            "preventive": {"policy": "age", "operating_interval": 500, "interval": 1000, "opportunity": 600}}
    pm = rm.with_task_basis(data)["preventive"]
    assert pm == {"policy": "age", "interval": 500, "basis": "operating", "opportunity": 300.0}
    spec = rm.preventive_spec(data, "Pump")
    assert (spec["interval"], spec["opportunity"], spec["basis"]) == (500, 300, "operating")
    # Nothing stored is changed by reading it.
    assert data["preventive"]["operating_interval"] == 500


def test_runs_blank_is_all_the_time_so_running_hours_are_calendar_hours():
    spec = rm.preventive_spec({"preventive": {"policy": "age", "interval": 500, "basis": "operating"}}, "Pump")
    assert spec["interval"] == 500 and "basis" not in spec
    assert rm.calendar_time(500, {"inspection": {"basis": "operating"}}, "inspection") == 500
    assert rm.calendar_time(500, {"duty": 0.25, "inspection": {"basis": "operating"}}, "inspection") == 2000


def test_saving_writes_the_new_shape():
    node = rbd_graph.normalize_node({"id": "p", "type": "component", "label": "Pump", "duty": 0.5,
                                     "model": {"distribution_id": "weibull",
                                               "params": [{"name": "alpha", "value": 1000},
                                                          {"name": "beta", "value": 2.5}]},
                                     "preventive": {"policy": "age", "operating_interval": 500, "interval": 1000}})
    assert node["data"]["preventive"] == {"policy": "age", "interval": 500, "basis": "operating"}
    with pytest.raises(rbd_graph.GraphError, match="calendar.*operating"):
        rbd_graph.normalize_node({"id": "q", "type": "component", "label": "Q",
                                  "model": {"distribution_id": "exponential",
                                            "params": [{"name": "failure_rate", "value": 0.001}]},
                                  "inspection": {"interval": 100, "basis": "weekly"}})


# ---------------------------------------------------------------------------
# Proof tests: running hours = the calendar test at interval / duty (by hand)
# ---------------------------------------------------------------------------
def _valve(**test):
    return _node("v", model=_w(40000, 1.5), instant_repair=True, inspection={"cost": 300, **test})


def test_a_proof_test_in_running_hours_is_the_calendar_test_at_interval_over_duty():
    # Runs 25%: every 2,000 running hours is every 8,000 h on the calendar, the first test at 1,000
    # running hours is at 4,000 h, and a full test every 10,000 running hours is every 40,000 h.
    run = _valve(interval=2000, offset=1000, coverage=0.9, full_test=10000, basis="operating")
    cal = _valve(interval=8000, offset=4000, coverage=0.9, full_test=40000)
    a = ra.analyze_availability(_series({**run, "data": {**run["data"], "duty": 0.25}}), n_simulations=N)
    b = ra.analyze_availability(_series({**cal, "data": {**cal["data"], "duty": 0.25}}), n_simulations=N)
    assert a["steady_state_availability"] == pytest.approx(b["steady_state_availability"], rel=1e-12)
    assert a["costs"]["cost_rate"] == pytest.approx(b["costs"]["cost_rate"], rel=1e-12)
    spec = rm.inspection_spec({"duty": 0.25, "inspection": run["data"]["inspection"]}, "Valve")
    assert {k: spec[k] for k in ("interval", "offset", "full_test", "basis")} == {
        "interval": 2000, "offset": 1000, "full_test": 10000, "basis": "operating"}


# ---------------------------------------------------------------------------
# Refusals, in plain words with what to do
# ---------------------------------------------------------------------------
def _refusal(component, **kw):
    life, rep = sv.Weibull.from_params([1000, 3]), sv.Exponential.from_params([0.1])
    with pytest.raises(ValueError) as err:
        RepairableRBD([("s", "a"), ("a", "t")], {"a": {"reliability": life, "repairability": rep, **component}},
                      **kw)
    return ra._component_message(str(err.value), {"a": "Pump A"})


def test_a_task_in_running_hours_on_a_block_with_no_runs_share_runs_all_the_time():
    # RePyability 0.20 no longer refuses it: with no duty the block runs all the time (a share
    # of 1), so its running hours are calendar hours, as Reliafy reads a position with no duty.
    life, rep = sv.Weibull.from_params([1000, 3]), sv.Exponential.from_params([0.1])
    spec = {"reliability": life, "repairability": rep}
    RepairableRBD([("s", "a"), ("a", "t")], {"a": {**spec, "inspection": {"interval": 500, "basis": "operating"}}})


def test_refusals_say_what_to_do():
    shut = _refusal({"duty": 0.5, "preventive": {"policy": "age", "shutdown": "Annual", "basis": "operating"}},
                    shutdowns={"Annual": {"period": 8760, "duration": 10}})
    assert "done at a shutdown" in shut and "count it on the calendar" in shut
    cal = _refusal({"duty": 0.5, "preventive": {"policy": "calendar", "calendar": [100, 200], "basis": "operating"}})
    assert "calendar policy" in cal and "count it on the calendar" in cal
    for text in (shut, cal):
        assert "operating time" not in text and "basis" not in text


def test_the_app_refuses_a_basis_it_doesnt_know_and_running_hours_off_a_time_clock():
    with pytest.raises(AnalysisError, match="calendar or in running hours"):
        rm.preventive_spec({"duty": 0.5, "preventive": {"policy": "age", "interval": 5, "basis": "weekly"}}, "Pump")
    cycles = {**_pump(duty=0.5, preventive={"policy": "age", "interval": 500, "basis": "operating"}), "unit": "cycles"}
    errors = rm.validation_errors(cycles)
    assert any("counted in running hours" in e and "time unit" in e for e in errors)
    assert not any("running" in e for e in rm.validation_errors(_pump(duty=0.5, preventive={
        "policy": "age", "interval": 500, "basis": "operating"})))


# ---------------------------------------------------------------------------
# The interval tools answer in the task's own unit
# ---------------------------------------------------------------------------
def _replaced(basis, interval, duty=0.5):
    pm = {"policy": "age", "interval": interval, "cost": 1000, "duration": _w(8, 3)}
    if basis:
        pm["basis"] = basis
    return _pump(duty=duty, preventive=pm)


def test_the_best_replacement_interval_comes_back_in_running_hours():
    run = rbd_intervals.optimise(_replaced("operating", 500))
    cal = rbd_intervals.optimise(_replaced(None, 1000))
    (r,), (c,) = run["blocks"], cal["blocks"]
    assert r["basis"] == "operating" and c["basis"] == "calendar"
    assert r["interval"] == pytest.approx(c["interval"] * 0.5, rel=1e-6)
    assert run["plan"]["cost_rate"] == pytest.approx(cal["plan"]["cost_rate"], rel=1e-9)
    assert r["unit_words"] == "running hours"
    assert any("counted in running hours: best every" in n and "running hours" in n for n in run["notes"])
    # Applied, the interval stays in running hours, and the numbers are the plan's.
    applied = rbd_intervals.apply_plan(_replaced("operating", 500), run["blocks"])
    pm = next(n for n in applied["nodes"] if n["id"] == "p")["data"]["preventive"]
    assert pm["basis"] == "operating" and pm["interval"] == r["interval"]
    assert _figures(applied)[1] == pytest.approx(run["plan"]["cost_rate"], rel=1e-9)


def test_the_best_proof_test_interval_comes_back_in_running_hours():
    v = _valve(interval=2000, basis="operating")
    graph = _series({**v, "data": {**v["data"], "duty": 0.25}}, costs={"downtime_rate": 500})
    out = rbd_intervals.optimise(graph)
    (row,) = out["blocks"]
    assert row["basis"] == "operating"
    # Chosen from the calendar at its Runs share (monthly is 730 h on the calendar: 180 running hours).
    assert 180.0 in out["allowed"]["v"] and 2000.0 in out["allowed"]["v"]
    assert row["interval"] in out["allowed"]["v"]


def test_the_levers_read_in_running_hours():
    v = _valve(interval=2000, basis="operating")
    graph = _series({**v, "data": {**v["data"], "duty": 0.25}})
    out = rbd_sensitivity.finish_rows(rbd_sensitivity.analyze_sensitivity(graph, simulate=False))
    lever = next(r for r in out["levers"] if r["lever"] == "inspection.interval")
    assert lever["running"] is True and lever["unit_word"] == " running hours"
    assert lever["value"] == pytest.approx(2000)


# ---------------------------------------------------------------------------
# Exports round-trip
# ---------------------------------------------------------------------------
def _plant():
    v = _valve(interval=2000, offset=500, basis="operating")
    p = _node("p", model=_w(1000, 2.5), repair=_ln(3.0, 0.5), costs={"replace": 5000}, duty=0.5,
              preventive={"policy": "age", "interval": 500, "basis": "operating", "cost": 1000, "duration": 7})
    return _series(p, {**v, "data": {**v["data"], "duty": 0.25}}, costs={"downtime_rate": 500})


def test_download_as_python_passes_the_basis_and_gives_the_apps_numbers(tmp_path):
    graph = _plant()
    code = rbd_export.to_python(graph, "Plant", exported_at=WHEN)
    assert code.count('"basis": "operating"') == 2
    res, _ = _run(code, tmp_path, n_sims="60")
    app = ra.analyze_availability(graph, n_simulations=N)
    assert res["steady_state_availability"] == pytest.approx(app["steady_state_availability"], rel=1e-12)


def test_json_export_and_import_keep_the_basis():
    from repyability.rbd.serialisation import rbd_from_json

    graph = _plant()
    text = rbd_json.to_json(rbd_json.to_document(graph, "Plant"))
    by_node = {c["node"]: c["component"] for c in json.loads(text)["components"]}
    assert by_node["p"]["preventive"]["basis"] == "operating" and by_node["v"]["inspection"]["basis"] == "operating"
    rbd = rbd_from_json(text)
    app = ra.analyze_availability(graph, n_simulations=N)
    assert float(rbd.mean_availability()) == pytest.approx(app["steady_state_availability"], rel=1e-12)
    back = rbd_import.import_file(text.encode("utf-8"), "plant.json")[0].graph
    data = {n["id"]: n["data"] for n in back["nodes"]}
    assert data["p"]["preventive"]["basis"] == "operating" and data["p"]["preventive"]["interval"] == 500
    assert data["v"]["inspection"] == {**data["v"]["inspection"], "interval": 2000, "offset": 500, "basis": "operating"}


def test_a_library_document_with_a_basis_imports_it():
    life, rep = sv.Weibull.from_params([1000, 3]), sv.Exponential.from_params([0.1])
    rbd = RepairableRBD([("s", "a"), ("a", "t")], {"a": {
        "reliability": life, "repairability": rep, "duty": 0.5,
        "inspection": {"interval": 500, "offset": 100, "basis": "operating"}}}, input_node="s", output_node="t")
    back = rbd_import.import_file(rbd.to_json().encode("utf-8"), "lib.json")[0].graph
    (data,) = [n["data"] for n in back["nodes"] if n["type"] == "component"]
    assert data["inspection"]["basis"] == "operating" and data["inspection"]["interval"] == 500


# ---------------------------------------------------------------------------
# The Explorer: a task by use on an hours counter is a running-hours task
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("unit", ["hours", "flight hours"])
def test_a_proof_test_by_use_on_an_hours_counter_maps_to_running_hours(m, db, unit):  # noqa: F811
    _, a, _, rbd = _station(m, db)
    point = m.add_point(a, "Hours run", kind="counter", unit=unit)
    m.create_task(a, "Test the trip", 2000, unit, outcome="failure_finding", point_id=point["id"])
    graph = _graph(db, rbd)
    row = tp.plans_for_graph(m, rbd, graph)["blocks"][_block_of(graph, "Pump A")["id"]]
    assert row["plan"]["task"] == "test" and row["plan"]["interval"] == 2000 and row["plan"]["basis"] == "operating"
    assert not row["flags"] or not any("can't" in f for f in row["flags"] if "running" in f)
    _block_of(graph, "Pump A")["data"]["duty"] = 0.25
    data = _block_of(tp.apply(graph, tp.plans_for_graph(m, rbd, graph)), "Pump A")["data"]
    assert data["inspection"]["basis"] == "operating" and data["inspection"]["interval"] == 2000
    assert rm.inspection_spec(data, "Pump A")["basis"] == "operating"


def test_a_task_by_use_on_a_cycles_counter_is_still_flagged(m, db):  # noqa: F811
    _, a, _, rbd = _station(m, db)
    point = m.add_point(a, "Starts", kind="counter", unit="starts")
    m.create_task(a, "Overhaul", 500, "starts", outcome="fixed_interval", point_id=point["id"])
    graph = _graph(db, rbd)
    row = tp.plans_for_graph(m, rbd, graph)["blocks"][_block_of(graph, "Pump A")["id"]]
    assert row["plan"]["interval"] is None
    assert any("counts starts" in f for f in row["flags"])


# ---------------------------------------------------------------------------
# MCP / REST / CLI parity
# ---------------------------------------------------------------------------
def test_the_mcp_schemas_take_the_basis():
    from backend import mcp_server

    for model in (mcp_server.Preventive, mcp_server.ProofTest):
        field = model.model_fields["basis"]
        assert "running hours" in field.description
        assert model.model_validate({"interval": 5, "basis": "operating"}).basis == "operating"
        with pytest.raises(Exception):
            model.model_validate({"interval": 5, "basis": "weekly"})
    ops = mcp_server._interval_ops(
        _pump(duty=0.5, preventive={"policy": "age", "interval": 500, "basis": "operating", "duration": 7}),
        [{"id": "p", "changed": True, "interval": 420.0}])
    assert ops[0]["preventive"]["basis"] == "operating" and ops[0]["preventive"]["interval"] == 420.0
    old = _pump(duty=0.5, preventive={"policy": "age", "operating_interval": 500, "interval": 1000})
    (op,) = mcp_server._interval_ops(old, [{"id": "p", "changed": True, "interval": 420.0}])
    assert op["preventive"]["interval"] == 420.0 and "operating_interval" not in op["preventive"]
