"""Covariates that change over time on RBD blocks (#52): the locked-down
expression evaluator, lowering to SurPyval's StepSchedule, the block as
RePyability's RegressionNode in the analysis (every number checked against
SurPyval / RePyability called directly), the modal's preview route, MCP,
graph normalisation and the exports."""

import io
import math
import time

import matplotlib

matplotlib.use("Agg")

import mongomock
import numpy as np
import pandas as pd
import pytest
import surpyval as sp
from repyability import NonRepairableRBD, RegressionNode

from backend import fitting
from backend.services import rbd_analysis, rbd_export, rbd_graph, rbd_json, rbd_tvc, samples
from backend.services.rbd_analysis import AnalysisError, analyze, validate_graph
from backend.services.tvc_expression import Expression, ExpressionError, change_points

INTERVALS = {"i": "pump", "xl": "start_h", "xr": "stop_h", "c": "censored"}


def _pumps() -> pd.DataFrame:
    spec = next(d for d in samples.SAMPLE_DATASETS if d["id"] == "sample-ds-pump-load")
    return fitting.read_dataframe(spec["csv"])


@pytest.fixture(scope="module")
def entry():
    """The pump sample's Weibull PH fit on load (60–90 %), as the analysis
    resolves a saved model."""
    r = fitting.fit("weibull_ph", _pumps(), INTERVALS, ["load_pct"], unit="hours",
                    covariate_units={"load_pct": "%"})
    return fitting._MODEL_STORE[r["functions"]["model_id"]]


@pytest.fixture(scope="module")
def ref():
    return sp.WeibullPH.fit_tvc_from_df(_pumps(), "pump", "start_h", "stop_h", "censored", Z_cols=["load_pct"])


def _graph(schedules, fields, ntype="component", extra=None, repairable=False):
    data = {"label": "Pump", "model": {"kind": "regression", "modelId": "M", "covariates": fields},
            "covariate_schedules": schedules, **(extra or {})}
    if repairable:
        data["repair"] = {"distribution_id": "exponential", "params": [{"name": "failure_rate", "value": 0.1}]}
    return {"unit": "Hours", "repairable": repairable, "nodes": [
        {"id": "input", "type": "input", "data": {}},
        {"id": "c1", "type": ntype, "data": data},
        {"id": "output", "type": "output", "data": {}}],
        "edges": [{"source": "input", "target": "c1"}, {"source": "c1", "target": "output"}]}


# ---- The expression sandbox ----------------------------------------------------

@pytest.mark.parametrize("text, t, want", [
    ("60 if t < 1000 else (90 if t < 3000 else 75)", 2000, 90),
    ("90 if t % 24 < 8 else 30", 30, 90),
    ("60 + 5 * floor(t / 500)", 1499, 70),
    ("60 * 1.1 ** floor(t / 1000)", 2500, 72.6),
    ("max(60, min(90, 50 + 10 * ceil(t / 100)))", 250, 80),
    ("sqrt(4) * 30 + log(e) + exp(0) - abs(-2) + sin(0) + cos(0) + tan(0) + log2(4)", 7, 63),
    ("75", 123, 75),
    ("t >= 100", 100, 1),
    ("t // 100", 250, 2),
])
def test_allowed_expressions_evaluate_per_scalar_t(text, t, want):
    assert Expression(text)(t) == pytest.approx(want)


HOSTILE = [
    "__import__('os').system('echo hi')",  # dunder
    "().__class__.__bases__[0].__subclasses__()",
    "t.__class__",
    "(1).real",  # attribute access
    "t.real",
    "9 ** 9 ** 9 ** 9",  # huge powers
    "2 ** 99999999",
    "10 ** 10 ** 10",
    "'a' * 10 ** 9",  # strings
    "'x' * 99999",
    "f'{t}'",
    "lambda: 1",  # lambdas
    "(lambda x: x)(t)",
    "[i for i in range(10 ** 9)]",  # comprehensions
    "{i: i for i in range(9)}",
    "sum(i for i in range(10 ** 9))",
    "[1, 2, 3]",  # compound types
    "(1, 2)",
    "{1, 2}",
    "{'a': 1}",
    "open('x')",  # unknown functions and names
    "eval('1')",
    "x + 1",
    "max(*[1, 2])",
    "round(t, ndigits=2)",
    "(y := 3)",
    "1; 2",
    "1 << 10000",
    "1 if t in (1, 2) else 2",
    "-" * 399 + "1",  # deeply nested
    "abs(" * 60 + "1" + ")" * 60,
    "1 + " * 200 + "1",  # too long
    "sin(t)",  # smooth in t: not a step
    "t",
    "0.3 + 1e-4 * t",
]


@pytest.mark.parametrize("text", HOSTILE)
def test_hostile_expressions_are_refused_quickly(text):
    start = time.perf_counter()
    with pytest.raises(ExpressionError):
        Expression(text)
    assert time.perf_counter() - start < 0.2


def test_evaluation_errors_are_plain_and_overflow_is_infinity():
    with pytest.raises(ExpressionError, match="divides by zero at t = 0"):
        Expression("1 / floor(t / 10)")
    with pytest.raises(ExpressionError, match="no value at t = 0"):
        Expression("log(floor(t / 10))")
    # A float power that overflows is infinity (clipped later), never a big int.
    assert Expression("10 ** (400 + floor(t))")(1) == math.inf
    assert Expression("exp(1000 + floor(t))")(0) == math.inf
    assert Expression("-2 ** 3")(0) == -8


def test_steps_are_found_exactly_by_bisection():
    times, values = change_points(Expression("60 if t < 1000 else (90 if t < 3000 else 75)"), 0, 10000)
    assert times == [0, 1000, 3000] and values == [60, 90, 75]
    times, values = change_points(Expression("t > 100"), 0, 1000)
    assert times == [0, 100] and values == [0, 1]
    times, _ = change_points(Expression("60 + 5 * floor(t / 7.3)"), 0, 30)
    assert times == pytest.approx([0, 7.3, 14.6, 21.9, 29.2])
    # Two steps inside one sample interval are both found.
    times, values = change_points(Expression("1 if t < 5000.2 else (2 if t < 5000.4 else 3)"), 0, 10000)
    assert values == [1, 2, 3] and times[1:] == pytest.approx([5000.2, 5000.4])


def test_a_repeating_expression_is_spotted():
    assert Expression("90 if t % 24 < 8 else 30").period == 24
    assert Expression("(t % 24 < 8) * 60 + (t % 24 >= 8) * 30").period == 24
    assert Expression("90 if t % 24 < 8 else 30 + floor(t / 1000)").period is None
    assert Expression("90 if t % 24 < 8 else (t % 12 < 1)").period is None


def test_a_path_changing_faster_than_it_can_be_followed_is_refused_quickly():
    start = time.perf_counter()
    with pytest.raises(ExpressionError, match="changes too often"):
        change_points(Expression("floor(t * 1000) % 2"), 0, 1e9)
    assert time.perf_counter() - start < 3


# ---- Lowering to a StepSchedule ------------------------------------------------

def test_phases_match_surpyval_along_change_points(entry, ref):
    graph = _graph({"load_pct": {"expression": "60 if t < 3000 else 90"}}, entry["fields"])
    out = analyze(graph, t_max=8000, resolve_model=lambda _: entry, at_times=[1000, 3000, 6000])
    want = ref.sf_tvc(np.array([1000, 3000, 6000.0]), sp.StepSchedule.from_changepoints([0, 3000], [[60.0], [90.0]]))
    assert out["at"]["sf"] == pytest.approx(want, rel=1e-6)
    node = next(n for n in out["nodes"] if n["id"] == "c1")
    assert node["sf"] == pytest.approx(out["system"]["sf"])
    assert out["mttf"] and "warnings" not in out


def test_a_duty_cycle_is_surpyvals_cyclic_schedule(entry, ref):
    graph = _graph({"load_pct": {"expression": "90 if t % 24 < 8 else 60"}}, entry["fields"])
    out = analyze(graph, t_max=8000, resolve_model=lambda _: entry, at_times=[500, 4000])
    want = ref.sf_tvc(np.array([500, 4000.0]), sp.StepSchedule.cyclic([0, 8], [[90.0], [60.0]], 24))
    assert out["at"]["sf"] == pytest.approx(want, rel=1e-6)


def test_values_beyond_the_fitted_range_are_clipped_with_a_warning(entry, ref):
    graph = _graph({"load_pct": {"expression": "60 + 10 * floor(t / 2000)"}}, entry["fields"])
    out = analyze(graph, t_max=9000, resolve_model=lambda _: entry, at_times=[7000])
    # 60, 70, 80, 90, then 100 held at 90 (the highest load in the data).
    want = ref.sf_tvc(np.array([7000.0]),
                      sp.StepSchedule.from_changepoints([0, 2000, 4000, 6000], [[60.0], [70.0], [80.0], [90.0]]))
    assert out["at"]["sf"] == pytest.approx(want, rel=1e-6)
    assert any("load_pct goes above 90%" in w and "t = 8,000" in w for w in out["warnings"])


def test_a_constant_schedule_equals_the_fixed_covariate_block(entry):
    fixed = analyze(_graph(None, entry["fields"]), t_max=8000, resolve_model=lambda _: entry,
                    covariates={"c1": {"load_pct": 75}})
    sched = analyze(_graph({"load_pct": {"expression": "75"}}, entry["fields"]), t_max=8000,
                    resolve_model=lambda _: entry)
    assert sched["system"]["sf"] == pytest.approx(fixed["system"]["sf"], rel=1e-9)
    assert sched["mttf"] == pytest.approx(fixed["mttf"], rel=1e-9)


def test_the_block_is_repyabilitys_regression_node_and_composes_unchanged(entry, ref):
    """A TVC block in series with a Weibull block: the system is RePyability's
    product of the two, with the RegressionNode built directly."""
    graph = _graph({"load_pct": {"expression": "60 if t < 3000 else 90"}}, entry["fields"])
    graph["nodes"].insert(2, {"id": "w", "type": "component", "data": {"label": "Motor", "model": {
        "distribution_id": "weibull", "params": [{"name": "alpha", "value": 9000}, {"name": "beta", "value": 1.5}]}}})
    graph["edges"] = [{"source": "input", "target": "c1"}, {"source": "c1", "target": "w"},
                      {"source": "w", "target": "output"}]
    out = analyze(graph, t_max=8000, resolve_model=lambda _: entry, at_times=[2000, 5000])
    node = RegressionNode(ref, schedule=sp.StepSchedule.from_changepoints([0, 3000], [[60.0], [90.0]]))
    rbd = NonRepairableRBD([("in", "c1"), ("c1", "w"), ("w", "out")],
                           {"c1": node, "w": sp.Weibull.from_params([9000, 1.5])})
    assert out["at"]["sf"] == pytest.approx(rbd.sf(np.array([2000, 5000.0])), rel=1e-6)
    built = rbd_analysis._build_rbd(graph, None, None, lambda _: entry, None)[3]["c1"]
    assert isinstance(built, RegressionNode)


def test_parallel_count_blocks_and_conditional_age(entry, ref):
    sched = sp.StepSchedule.from_changepoints([0, 3000], [[60.0], [90.0]])
    graph = _graph({"load_pct": {"expression": "60 if t < 3000 else 90"}}, entry["fields"], ntype="parallel",
                   extra={"n": 2})
    out = analyze(graph, t_max=8000, resolve_model=lambda _: entry, at_times=[5000])
    r = ref.sf_tvc(np.array([5000.0]), sched)
    assert out["at"]["sf"] == pytest.approx(1 - (1 - r) ** 2, rel=1e-6)
    cond = analyze(_graph({"load_pct": {"expression": "60 if t < 3000 else 90"}}, entry["fields"]), t_max=3000,
                   resolve_model=lambda _: entry, conditional_age=2000, at_times=[2000])
    want = ref.sf_tvc(np.array([4000.0]), sched) / ref.sf_tvc(np.array([2000.0]), sched)
    assert cond["at"]["sf"] == pytest.approx(want, rel=1e-6)


def test_the_path_is_extended_when_a_later_time_is_asked(entry, ref):
    node = rbd_tvc.build_node(entry, {"load_pct": {"expression": "60 if t < 50000 else 90"}}, None, "Pump")
    far = np.array([40000.0, 60000.0])
    want = ref.sf_tvc(far, sp.StepSchedule.from_changepoints([0, 50000], [[60.0], [90.0]]))
    assert node.sf(far) == pytest.approx(want, rel=1e-6)


def test_categorical_phase_table_is_encoded_as_the_model_design():
    rng = np.random.default_rng(3)
    n = 300
    site = rng.choice(["north", "south"], n)
    load = rng.uniform(50, 90, n)
    x = sp.Weibull.random(n, 1000, 2.0) * np.exp(-0.02 * (load - 70) - 0.5 * (site == "south"))
    df = pd.DataFrame({"t": x, "load": load, "site": site})
    r = fitting.fit("weibull_ph", df, {"x": "t"}, formula="load + C(site)")
    e = fitting._MODEL_STORE[r["functions"]["model_id"]]
    field = next(f for f in e["fields"] if f["name"] == "site")
    assert field["type"] == "category"
    schedules = {"site": {"table": [{"t": 0, "value": "north"}, {"t": 600, "value": "south"}]}}
    node = rbd_tvc.build_node(e, schedules, {"load": 70}, "Seal")
    model = e["model"]
    Z = model._prepare_Z(pd.DataFrame({"load": [70.0, 70.0], "site": ["north", "south"]}))
    want = model.sf_tvc(np.array([300.0, 900.0]), sp.StepSchedule.from_changepoints([0, 600], Z))
    assert node.sf(np.array([300.0, 900.0])) == pytest.approx(want, rel=1e-9)
    # Repeating phases: SurPyval's cyclic schedule.
    cyc = rbd_tvc.build_node(e, {"site": {**schedules["site"], "period": 1000}}, {"load": 70}, "Seal")
    want = model.sf_tvc(np.array([1500.0]), sp.StepSchedule.cyclic([0, 600], Z, 1000))
    assert cyc.sf(np.array([1500.0])) == pytest.approx(want, rel=1e-9)
    with pytest.raises(rbd_tvc.ScheduleError, match="isn't one of the model's levels"):
        rbd_tvc.build_node(e, {"site": {"table": [{"t": 0, "value": "east"}]}}, None, "Seal")
    with pytest.raises(rbd_tvc.ScheduleError, match="categorical"):
        rbd_tvc.build_node(e, {"site": {"expression": "1"}}, None, "Seal")


def test_the_range_comes_from_the_model_when_the_inputs_lack_it():
    rng = np.random.default_rng(1)
    load = rng.uniform(50, 90, 200)
    x = sp.Weibull.random(200, 1000, 2.0) * np.exp(-0.02 * (load - 70))
    r = fitting.fit("weibull_ph", pd.DataFrame({"t": x, "load": load}), {"x": "t"}, ["load"])
    e = fitting._MODEL_STORE[r["functions"]["model_id"]]
    assert "max" not in e["fields"][0]
    assert rbd_tvc.fitted_range(e["model"], e["fields"][0]) == pytest.approx((load.min(), load.max()))
    cox = fitting.fit("cox_ph", pd.DataFrame({"t": x, "load": load}), {"x": "t"}, ["load"])
    ce = fitting._MODEL_STORE[cox["functions"]["model_id"]]
    assert rbd_tvc.fitted_range(ce["model"], ce["fields"][0]) == pytest.approx((load.min(), load.max()))
    node = rbd_tvc.build_node(ce, {"load": {"expression": "60 if t < 500 else 80"}}, None, "Cox")
    want = ce["model"].sf_tvc(np.array([800.0]), sp.StepSchedule.from_changepoints([0, 500], [[60.0], [80.0]]))
    assert node.sf(np.array([800.0])) == pytest.approx(want)


# ---- Where a schedule can't apply ----------------------------------------------

def test_validation_names_a_bad_schedule_without_the_fit(entry):
    v = validate_graph(_graph({"load_pct": {"expression": "60 + t"}}, entry["fields"]))
    assert not v["valid"] and any("changes in steps" in e for e in v["errors"])
    v = validate_graph(_graph({"speed": {"expression": "1"}}, entry["fields"]))
    assert any("Unknown covariate “speed”" in e for e in v["errors"])
    assert validate_graph(_graph({"load_pct": {"expression": "60"}}, entry["fields"]))["valid"]


def test_repairable_diagrams_and_standby_spares_refuse_schedules(entry):
    sched = {"load_pct": {"expression": "60 if t < 3000 else 90"}}
    with pytest.raises(AnalysisError, match="non-repairable diagrams only"):
        rbd_analysis._build_repairable_rbd(_graph(sched, entry["fields"], repairable=True),
                                           resolve_model=lambda _: entry)
    with pytest.raises(AnalysisError, match="switched in"):
        analyze(_graph(sched, entry["fields"], ntype="standby", extra={"spares": 1, "cold": True}),
                resolve_model=lambda _: entry)


def test_a_schedule_on_a_plain_distribution_is_ignored():
    graph = _graph({"x": {"expression": "1"}}, [])
    graph["nodes"][1]["data"]["model"] = {"distribution_id": "weibull", "params": [
        {"name": "alpha", "value": 100}, {"name": "beta", "value": 2}]}
    out = analyze(graph, t_max=100, at_times=[50])
    assert out["at"]["sf"] == pytest.approx(sp.Weibull.from_params([100, 2]).sf(np.array([50.0])))


# ---- The stored shape, graph normalisation, edits ------------------------------

def test_normalise_checks_shapes_and_names():
    fields = [{"name": "load", "type": "number"}, {"name": "site", "type": "category", "options": ["a", "b"]}]
    out = rbd_tvc.normalise({"load": {"expression": " 60 if t < 5 else 70 "},
                             "site": {"table": [{"t": 0, "value": "a"}, {"t": 5, "value": "b"}], "period": 10}},
                            fields)
    assert out == {"load": {"expression": "60 if t < 5 else 70"},
                   "site": {"table": [{"t": 0.0, "value": "a"}, {"t": 5.0, "value": "b"}], "period": 10.0}}
    for bad, msg in [
        ({"load": {"expression": "1", "table": []}}, "not both"),
        ({"load": {"table": [{"t": 5, "value": 1}]}}, "starts at time 0"),
        ({"load": {"table": [{"t": 0, "value": 1}, {"t": 0, "value": 2}]}}, "increasing"),
        ({"site": {"table": [{"t": 0, "value": "a"}, {"t": 12, "value": "b"}], "period": 10}}, "within one period"),
        ({"load": "60"}, "is {"),
        ({"nope": {"expression": "1"}}, "Unknown covariate"),
    ]:
        with pytest.raises(rbd_tvc.ScheduleError, match=msg):
            rbd_tvc.normalise(bad, fields)


def test_graph_normalisation_and_compact_form_carry_schedules(entry):
    saved = type("M", (), {"id": "M", "kind": "regression", "name": "Pumps", "distribution_id": "weibull_ph",
                           "results": {"distribution": "Weibull PH", "distribution_id": "weibull_ph", "params": [],
                                       "functions": {"covariates": entry["fields"]}}})()
    raw = {"nodes": [{"id": "input", "type": "input"},
                     {"id": "p", "type": "component", "label": "Pump", "model": {"saved_model_id": "M"},
                      "covariate_schedules": {"load_pct": {"expression": "90 if t % 24 < 8 else 60"}}},
                     {"id": "output", "type": "output"}],
           "edges": [{"source": "input", "target": "p"}, {"source": "p", "target": "output"}]}
    graph = rbd_graph.normalize_graph(raw, resolve_saved_model=lambda _: saved)
    node = next(n for n in graph["nodes"] if n["id"] == "p")
    assert node["data"]["covariate_schedules"] == {"load_pct": {"expression": "90 if t % 24 < 8 else 60"}}
    compact = rbd_graph.compact_graph(graph)
    assert next(n for n in compact["nodes"] if n["id"] == "p")["covariate_schedules"]["load_pct"]
    raw["nodes"][1]["covariate_schedules"] = {"load_pct": {"expression": "t * 2"}}
    with pytest.raises(rbd_graph.GraphError, match="changes in steps"):
        rbd_graph.normalize_graph(raw, resolve_saved_model=lambda _: saved)
    raw["nodes"][1]["model"] = {"distribution_id": "weibull", "params": [{"name": "alpha", "value": 9},
                                                                       {"name": "beta", "value": 1}]}
    raw["nodes"][1]["covariate_schedules"] = {"load_pct": {"expression": "1"}}
    with pytest.raises(rbd_graph.GraphError, match="need a saved covariate"):
        rbd_graph.normalize_graph(raw)


# ---- Exports -------------------------------------------------------------------

def test_python_export_describes_the_schedule_and_runs_to_the_placeholder(entry, tmp_path):
    from backend.tests.test_rbd_export import _run

    graph = _graph({"load_pct": {"expression": "90 if t % 24 < 8 else 60"}}, entry["fields"])
    graph["nodes"][1]["data"]["model"].update(distribution="Weibull PH", name="Pumps")
    code = rbd_export.to_python(graph, "TVC", resolve_model=lambda _: None)
    compile(code, "tvc.py", "exec")
    flat = " ".join(line.lstrip("# ").strip() for line in code.splitlines())
    assert "load_pct = 90 if t % 24 < 8 else 60" in flat and "RegressionNode(model, schedule=schedule)" in flat
    _, proc = _run(code, tmp_path, expect_ok=False)
    last = proc.stderr.strip().splitlines()[-1]
    assert last.startswith("NotImplementedError: Block 'Pump' uses a fitted proportional-hazards")
    assert "covariate schedule" in last


def test_json_export_still_refuses_a_regression_block(entry):
    graph = _graph({"load_pct": {"expression": "60"}}, entry["fields"])
    with pytest.raises(rbd_json.ExportError, match="fitted proportional-hazards model"):
        rbd_json.to_document(graph, "TVC")


# ---- The preview route ---------------------------------------------------------

@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    test_db = mongomock.MongoClient()["reliafy_rbd_tvc_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    app.dependency_overrides[get_current_user] = lambda: {"uid": "user-a", "email": "a@example.org", "name": "A"}
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_preview_route(client, ref):
    csv = _pumps().to_csv(index=False).encode()
    r = client.post("/api/models", data={"name": "Pumps", "distribution": "weibull_ph", **INTERVALS,
                                         "z": ["load_pct"], "unit": "hours"},
                    files={"file": ("pumps.csv", io.BytesIO(csv), "text/csv")})
    mid = r.json()["id"]
    got = client.post("/api/rbds/tvc-preview", json={
        "model_id": mid, "schedules": {"load_pct": {"expression": "60 if t < 3000 else 100"}}, "t_max": 6000})
    assert got.status_code == 200, got.text
    out = got.json()
    assert out["x"][-1] == 6000
    sched = sp.StepSchedule.from_changepoints([0, 3000], [[60.0], [90.0]])
    assert out["sf"] == pytest.approx(ref.sf_tvc(np.asarray(out["x"]), sched), rel=1e-6)
    cov = out["covariates"][0]
    assert cov["times"] == [0, 3000] and cov["values"] == [60, 90] and cov["range"] == [60, 90]
    assert "goes above 90," in out["warnings"][0]
    duty = client.post("/api/rbds/tvc-preview", json={
        "model_id": mid, "schedules": {"load_pct": {"expression": "90 if t % 24 < 8 else 60"}}}).json()
    assert duty["repeats_every"] == 24
    bad = client.post("/api/rbds/tvc-preview", json={
        "model_id": mid, "schedules": {"load_pct": {"expression": "().__class__"}}})
    assert bad.status_code == 422 and "Double underscores" in bad.json()["detail"]
    assert client.post("/api/rbds/tvc-preview", json={"model_id": "nope", "schedules": {}}).status_code == 404


# ---- MCP -----------------------------------------------------------------------

from backend.tests.test_mcp import env  # noqa: E402,F401 - the MCP fixture


def test_mcp_create_analyze_and_edit_schedules(env, ref):  # noqa: F811 - env is a fixture
    from backend.tests.test_mcp import A, _call, _err, _ok

    ds = _ok(_call(env.token[A], "upload_dataset", {"name": "Pumps", "csv": _pumps().to_csv(index=False)}))
    mid = _ok(_call(env.token[A], "fit_and_save_model", {
        "name": "Pumps TVC", "distribution": "weibull_ph", "dataset_id": ds["id"], "id_column": "pump",
        "time_column": "start_h", "time_right_column": "stop_h", "censor_column": "censored",
        "covariates": ["load_pct"]}))["model_id"]
    nodes = [{"id": "input", "type": "input"},
             {"id": "p", "type": "component", "label": "Pump", "model": {"saved_model_id": mid},
              "covariate_schedules": {"load_pct": {"expression": "60 if t < 3000 else 90"}}},
             {"id": "output", "type": "output"}]
    edges = [{"source": "input", "target": "p"}, {"source": "p", "target": "output"}]
    rid = _ok(_call(env.token[A], "create_rbd", {"name": "TVC", "unit": "Hours", "nodes": nodes,
                                                 "edges": edges}))["id"]
    got = _ok(_call(env.token[A], "get_rbd", {"rbd_id": rid}))
    node = next(n for n in got["graph"]["nodes"] if n["id"] == "p")
    assert node["covariate_schedules"] == {"load_pct": {"expression": "60 if t < 3000 else 90"}}
    out = _ok(_call(env.token[A], "analyze_rbd", {"rbd_id": rid, "times": [1000, 5000]}))
    sched = sp.StepSchedule.from_changepoints([0, 3000], [[60.0], [90.0]])
    assert [p["reliability"] for p in out["reliability_at"]] == pytest.approx(
        ref.sf_tvc(np.array([1000, 5000.0]), sched), rel=1e-6)

    # A stepped ramp past the data: clipped, with the warning relayed.
    _ok(_call(env.token[A], "edit_rbd", {"rbd_id": rid, "ops": [
        {"op": "update_node", "id": "p",
         "covariate_schedules": {"load_pct": {"expression": "60 + 10 * floor(t / 2000)"}}}]}))
    out = _ok(_call(env.token[A], "analyze_rbd", {"rbd_id": rid, "times": [9000], "t_max": 10000}))
    assert any("goes above" in w for w in out["warnings"])
    assert "changes in steps" in _err(_call(env.token[A], "edit_rbd", {"rbd_id": rid, "ops": [
        {"op": "update_node", "id": "p", "covariate_schedules": {"load_pct": {"expression": "t"}}}]}))
    _ok(_call(env.token[A], "edit_rbd", {"rbd_id": rid, "ops": [
        {"op": "update_node", "id": "p", "clear": ["covariate_schedules"]}]}))
    saved = env.db.rbds.find_one({"_id": rid})
    assert "covariate_schedules" not in next(n for n in saved["graph"]["nodes"] if n["id"] == "p")["data"]
    assert "need a saved covariate" in _err(_call(env.token[A], "create_rbd", {
        "name": "Bad", "unit": "Hours", "edges": edges, "nodes": [
            nodes[0], {**nodes[1], "model": {"distribution_id": "weibull", "params": [
                {"name": "alpha", "value": 9}, {"name": "beta", "value": 1}]}}, nodes[2]]}))
