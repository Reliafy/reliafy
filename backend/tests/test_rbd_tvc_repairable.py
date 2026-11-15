"""Covariate schedules on repairable blocks and within mission phases (planning #372).

* A repairable block on a schedule is RePyability's repairable ``"covariates"``: the schedule
  belongs to the plant (repairs reset age, never the schedule). Checked against RePyability called
  directly (the same seed gives the same run) and against a two-state Markov chain worked out by
  hand (exponential baseline: constant rates within each step).
* RePyability's refusals reach the user in plain words (no Python).
* Such a diagram has no exact figures, so it is simulated: Pro, with the free quick run.
* A covariate can follow a schedule within a mission phase: the same mission as splitting the
  phase into phases of one value each.
* Exports carry both (the Python script reproduces the app's simulation, seeded).
* Repeats found across several terms, and the summed survival matches SurPyval's own.
"""

import io
import math

import matplotlib

matplotlib.use("Agg")

import numpy as np
import pandas as pd
import pytest
import surpyval as sp
from repyability import RepairableRBD
from scipy.linalg import expm

from backend.services import rbd_analysis as ra
from backend.services import rbd_export, rbd_json, rbd_missions, rbd_phases, rbd_tvc
from backend.services.rbd_analysis import AnalysisError
from backend.services.tvc_expression import Expression, ExpressionError, change_points

FIELDS = [{"name": "load", "type": "number", "min": 1, "max": 2, "default": 1}]
MU = 0.1  # repairs a tenth of an hour-unit


def _fit(cls, beta=1.0):
    rng = np.random.default_rng(7)
    load = np.repeat([1.0, 2.0], 40)
    x = 100.0 * rng.weibull(beta, load.size) / load**2
    return cls.fit_from_df(pd.DataFrame({"x": x, "load": load}), x_col="x", Z_cols=["load"])


def _entry(model):
    return {"model": model, "fields": FIELDS, "grid": np.linspace(0, 300, 50)}


@pytest.fixture(scope="module")
def exp_ph():
    return _entry(_fit(sp.ExponentialPH))


SCHED = {"load": {"table": [{"t": 0, "value": 1}, {"t": 200, "value": 2}]}}


def _graph(schedules=SCHED, extra=None, ntype="component", repairable=True):
    data = {"label": "Pump", "model": {"kind": "regression", "modelId": "M", "covariates": FIELDS},
            "covariate_schedules": schedules, **(extra or {})}
    if repairable:
        data.setdefault("repair", {"distribution_id": "exponential",
                                   "params": [{"name": "failure_rate", "value": MU}]})
    return {"unit": "Hours", "repairable": repairable, "nodes": [
        {"id": "input", "type": "input", "data": {}},
        {"id": "c1", "type": ntype, "data": data},
        {"id": "output", "type": "output", "data": {}}],
        "edges": [{"source": "input", "target": "c1"}, {"source": "c1", "target": "output"}]}


def _two_state_window_mean(l1: float, l2: float, mu: float, change: float, t_end: float) -> float:
    """Mean availability over [0, t_end] of one unit up/down: failure rate l1 before ``change`` and
    l2 after (the plant's schedule), repair rate mu, starting up. The generator's integral by
    the augmented-matrix trick."""
    def block(lam, p0, span):
        Q = np.array([[-lam, lam], [mu, -mu]])
        A = np.zeros((4, 4))
        A[:2, :2] = Q.T
        A[2:, :2] = np.eye(2)
        E = expm(A * span)
        p = E[:2, :2] @ p0
        integral = E[2:, :2] @ p0
        return p, integral[0]

    p1, up1 = block(l1, np.array([1.0, 0.0]), change)
    _, up2 = block(l2, p1, t_end - change)
    return (up1 + up2) / t_end


def test_a_repairable_block_follows_the_plants_schedule(exp_ph):
    out = ra.analyze_availability(_graph(), resolve_model=lambda _: exp_ph, t_simulation=400,
                                  n_simulations=2000, seed=3)
    assert out["steady_state_availability"] is None or math.isnan(out["steady_state_availability"]) and out["availability_basis"] == "simulation"
    assert "carries on under the load in force" in out["covariate_schedule"]["note"]
    sim = out["precision"]["simulated_window_availability"]
    se = out["precision"]["standard_error"]

    # RePyability directly, the same run: the same number.
    model = exp_ph["model"]
    schedule = sp.StepSchedule.from_changepoints([0.0, 200.0], [[1.0], [2.0]])
    rbd = RepairableRBD([("input", "c1"), ("c1", "output")],
                        {"c1": {"reliability": model, "repairability": sp.Exponential.from_params([MU]),
                                "covariates": schedule}}, input_node="input", output_node="output")
    res = rbd.availability(t_simulation=400.0, mc_samples=2000, method="c", seed=3, antithetic=True,
                           control_variate=False, conditional=False)
    assert float(res.mean_availability_interval(0.9).estimate) == pytest.approx(sim, rel=1e-12)

    # By hand: an exponential baseline is a constant rate in each step.
    l1 = float(model.Hf(np.array([1.0]), np.array([[1.0]]))[0])
    l2 = float(model.Hf(np.array([1.0]), np.array([[2.0]]))[0])
    assert l2 > l1
    want = _two_state_window_mean(l1, l2, MU, 200.0, 400.0)
    assert abs(sim - want) <= 4 * se


def test_extra_settings_and_constants_ride_along(exp_ph):
    # A cost and a block value for an unscheduled covariate keep the component a spec with the schedule.
    g = _graph(extra={"costs": {"repair": 100}, "covariate_values": {"load": 1.5}})
    rbd, *_ = ra._build_repairable_rbd(g, resolve_model=lambda _: exp_ph)
    life = rbd.components["c1"].reliability
    assert type(life).__name__ == "ScheduledLife"


@pytest.mark.parametrize("cls, extra, ntype, words", [
    (sp.WeibullAFT, {"repair_quality": {"model": "kijima1", "q": 0.5}}, "component", "virtual age"),
    (sp.WeibullPO, None, "component", "Proportional Odds model"),
    (sp.CoxPH, None, "component", "Cox model"),
    (sp.WeibullPH, {"spares": 1}, "standby", "switched in"),
    (sp.WeibullPH, {"duty": 0.5}, "component", "duty"),
])
def test_the_librarys_refusals_in_plain_words(cls, extra, ntype, words):
    entry = _entry(_fit(cls, beta=1.5))
    with pytest.raises(AnalysisError) as got:
        ra._build_repairable_rbd(_graph(extra=extra, ntype=ntype), resolve_model=lambda _: entry)
    text = str(got.value)
    assert words in text and "Pump" in text
    assert "surv." not in text and "kijima1" not in text and "surpyval" not in text


def test_an_aft_block_that_renews_is_taken():
    entry = _entry(_fit(sp.WeibullAFT, beta=1.5))
    rbd, *_ = ra._build_repairable_rbd(_graph(), resolve_model=lambda _: entry)
    assert rbd.analysis_routes()["availability"].route == "simulated"
    assert rbd.analysis_routes()["mean_availability"].route == "refused"


# ---- Pro gating: simulated by the routes ----------------------------------------------------------

from backend.tests.test_availability_paid import FREE, PRO, _paywall, client  # noqa: E402,F401 - fixture


def _pump_model(client):
    from backend import fitting
    from backend.services import samples

    spec = next(d for d in samples.SAMPLE_DATASETS if d["id"] == "sample-ds-pump-load")
    csv = fitting.read_dataframe(spec["csv"]).to_csv(index=False).encode()
    r = client.post("/api/models", data={"name": "Pumps", "distribution": "weibull_ph", "i": "pump",
                                         "xl": "start_h", "xr": "stop_h", "c": "censored", "z": ["load_pct"],
                                         "unit": "hours"},
                    files={"file": ("pumps.csv", io.BytesIO(csv), "text/csv")})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_a_scheduled_repairable_diagram_is_pro_with_the_quick_run(client):
    def diagram():
        g = _graph({"load_pct": {"expression": "90 if t % 24 < 8 else 60"}})
        g["nodes"][1]["data"]["model"] = {"kind": "regression", "modelId": _pump_model(client),
                                          "covariates": [{"name": "load_pct", "type": "number"}]}
        return g

    client.act_as(PRO)
    pro = client.post("/api/rbds/analyze", json={"graph": diagram(), "t_max": 2000})
    assert pro.status_code == 200, pro.text
    body = pro.json()
    assert body["covariate_schedule"]["note"] and body["has_simulation"]
    client.act_as(FREE)
    free = client.post("/api/rbds/analyze", json={"graph": diagram(), "t_max": 2000})
    assert _paywall(free), free.text


# ---- Within a mission phase ----------------------------------------------------------------------

def test_a_phase_schedule_is_kept_and_checked():
    [p] = rbd_phases.parse_phases([{"name": "Run", "duration": 48, "values": {
        "flow": {"expression": " 100 if t % 24 < 16 else 40 "}}}])
    assert p["values"]["flow"] == {"expression": "100 if t % 24 < 16 else 40"}
    with pytest.raises(rbd_phases.PhaseError, match="changes in steps"):
        rbd_phases.parse_phases([{"name": "Run", "duration": 1, "values": {"flow": {"expression": "t"}}}])
    steps = rbd_missions.flat_steps(p)
    assert [t for t, _ in steps] == [0, 16, 24, 40]
    assert [f["values"]["flow"] for _, f in steps] == [100, 40, 100, 40]


@pytest.fixture()
def pump(monkeypatch, exp_ph):
    from backend.services import rbds as rbds_service

    monkeypatch.setattr(rbds_service, "resolvers", lambda db, owner: (None, lambda _: exp_ph))
    g = _graph(None, repairable=False)
    del g["nodes"][1]["data"]["covariate_schedules"]
    return g


def test_a_schedule_within_a_phase_equals_splitting_the_phase(pump):
    sched = [{"name": "Run", "duration": 300, "values": {"load": {"table": [{"t": 0, "value": 1},
                                                                            {"t": 120, "value": 2}]}}},
             {"name": "Rest", "duration": 50, "values": {"load": 1}}]
    split = [{"name": "Run A", "duration": 120, "values": {"load": 1}},
             {"name": "Run B", "duration": 180, "values": {"load": 2}},
             {"name": "Rest", "duration": 50, "values": {"load": 1}}]
    a = rbd_missions.analyze(None, [], pump, sched, inputs_for=lambda b: [])
    b = rbd_missions.analyze(None, [], pump, split, inputs_for=lambda b: [])
    assert a["reliability"] == pytest.approx(b["reliability"], rel=1e-9)
    assert a["phases"][0]["reliability_at_end"] == pytest.approx(b["phases"][1]["reliability_at_end"], rel=1e-9)
    assert [p["name"] for p in a["phases"]] == ["Run", "Rest"]


def test_a_repeating_schedule_within_one_phase(pump):
    one = [{"name": "Duty", "duration": 96, "values": {"load": {"expression": "2 if t % 24 < 16 else 1"}}}]
    split = []
    for day in range(4):
        split += [{"name": f"High {day}", "duration": 16, "values": {"load": 2}},
                  {"name": f"Low {day}", "duration": 8, "values": {"load": 1}}]
    a = rbd_missions.analyze(None, [], pump, one, inputs_for=lambda b: [])
    b = rbd_missions.analyze(None, [], pump, split, inputs_for=lambda b: [])
    assert a["reliability"] == pytest.approx(b["reliability"], rel=1e-9)
    assert a["method"] == b["method"]


# ---- Exports -------------------------------------------------------------------------------------

def test_python_export_reproduces_the_simulation(exp_ph, tmp_path):
    from backend.tests.test_rbd_export import _run

    g = _graph({"load": {"expression": "2 if t % 24 < 8 else 1"}})
    g["nodes"][1]["data"]["model"].update(distribution="Exponential PH", name="Pumps")
    code = rbd_export.to_python(g, "TVC", resolve_model=lambda _: exp_ph)
    compile(code, "tvc.py", "exec")
    assert "surv.StepSchedule(" in code and '"covariates": ' in code and "surv.from_dict(" in code
    out, proc = _run(code, tmp_path, n_sims="200")
    app = ra.analyze_availability(g, resolve_model=lambda _: exp_ph, n_simulations=200)
    assert out["t_simulation"] == pytest.approx(app["t_simulation"])
    # The same seeded run: the same number (within any simulation error, it is the very run).
    sim = app["precision"]["simulated_window_availability"]
    assert out["precision"]["simulated_window_availability"] == pytest.approx(sim, rel=1e-9)
    assert out["steady_state_availability"] is None or math.isnan(out["steady_state_availability"])


def test_json_export_carries_a_repairable_schedule(exp_ph):
    from repyability.rbd.serialisation import rbd_from_dict

    doc = rbd_json.to_document(_graph(), "TVC", resolve_model=lambda _: exp_ph)
    comp = next(c["component"] for c in doc["components"] if c["node"] == "c1")
    assert comp["covariates"]["edges"][:2] == [0.0, 200.0]
    assert comp["reliability"]["model"]["kind"] == "Proportional Hazard"
    rbd = rbd_from_dict({k: v for k, v in doc.items() if k != "reliafy"})
    assert rbd.analysis_routes()["availability"].route == "simulated"
    assert doc["reliafy"]["graph"]["nodes"][1]["data"]["covariate_schedules"] == SCHED


# ---- Repeats and the summed survival -------------------------------------------------------------

WAVY = "80 + 30*sin(2*pi*floor(t)/24) + 10*sin(2*pi*floor(t/24)/30)"


@pytest.mark.parametrize("text, period", [
    (WAVY, 720.0),
    ("80 + 30*sin(2*pi*floor(t % 24)/24) + 10*sin(2*pi*floor((t % 720)/24)/30)", 720.0),
    ("90 if t % 24 < 8 else (60 if t % 36 < 12 else 70)", 72.0),
    ("90 if t % 24 < 8 else 30 + floor(t / 1000)", None),
    ("(t % 24 < 8) * 60 + floor(t * 0.0001)", None),
    ("sin(floor(t) / 1000)", None),
])
def test_repeats_found_across_terms(text, period):
    assert Expression(text).period == period


def test_too_often_says_how_to_write_a_repeat():
    with pytest.raises(ExpressionError, match=r"write every t as t % P"):
        change_points(Expression("floor(t * 1000) % 2 + floor(t / 1e7)"), 0, 1e9)


def test_the_summed_survival_is_surpyvals_and_gives_an_mttf():
    rng = np.random.default_rng(1)
    f = rng.uniform(40, 120, 80)
    x = 9941.19 * rng.weibull(2.2, 80) * np.exp(-0.0216 * f / 2.2)
    fit = sp.WeibullPH.fit_from_df(pd.DataFrame({"x": x, "flow_pct": f}), x_col="x", Z_cols=["flow_pct"])
    d = fit.to_dict()
    d["params"] = [9941.19, 2.20462, 0.0216237]
    model = sp.from_dict(d)
    ts = np.arange(720.0)
    z = 80 + 30 * np.sin(2 * np.pi * ts / 24) + 10 * np.sin(2 * np.pi * np.floor(ts / 24) / 30)
    sched = sp.StepSchedule.cyclic(list(ts), z[:, None], 720.0)
    grid = np.linspace(0, 3000, 300)
    fields = [{"name": "flow_pct", "type": "number", "min": 40, "max": 120, "default": 80, "unit": "%"}]
    entry = {"model": model, "fields": fields, "grid": np.linspace(0, 12000, 200)}
    g = _graph({"flow_pct": {"expression": WAVY}}, repairable=False)
    g["nodes"][1]["data"]["model"]["covariates"] = fields
    node = rbd_tvc.build_node(entry, {"flow_pct": {"expression": WAVY}}, None, "Pump")
    assert node.schedule.period == 720.0  # repeating: followed to any time
    assert node.sf(grid) == pytest.approx(model.sf_tvc(grid, sched), rel=1e-9)
    out = ra.analyze(g, t_max=4000, resolve_model=lambda _: entry, at_times=[2000])
    assert out["at"]["sf"][0] == pytest.approx(0.8322, abs=5e-4)
    assert out["mttf"] is not None and 3000 < out["mttf"] < 5000


def test_a_long_phase_schedule_has_as_many_steps_as_it_needs(pump, exp_ph):
    """A day/night duty over 2,000 hours is 167 steps, more than a typed table may have: the
    mission's own table of steps isn't held to that limit, and gives the cyclic schedule's figure."""
    one = [{"name": "Run", "duration": 2000, "values": {"load": {"expression": "2 if t % 24 < 16 else 1"}}}]
    got = rbd_missions.analyze(None, [], pump, one, inputs_for=lambda b: [])
    node = rbd_tvc.build_node(exp_ph, {"load": {"expression": "2 if t % 24 < 16 else 1"}}, None, "Pump")
    assert got["reliability"] == pytest.approx(float(node.sf(np.array([2000.0]))[0]), rel=1e-9)
