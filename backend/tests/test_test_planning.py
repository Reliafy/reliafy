"""The Test planning page's calculators (backend.services.test_planning), each
against SurPyval's ``test_planning`` directly; their REST routes; the
simulation check's Pro gate and job; and the MCP actions."""
from __future__ import annotations

import json
import re

import numpy as np
import pytest
import surpyval
from surpyval import test_planning as tp
from surpyval.univariate.regression import accelerated_life as _al

from backend.services import compute_core
from backend.services import test_planning as T
from backend.services.strategy import StrategyError
from backend.tests.test_demonstration import client  # noqa: F401  (the REST fixture)
from backend.tests.test_mcp import A, _call, _err, _ok, env  # noqa: F401  (the MCP fixture)

WEIBULL = [{"name": "alpha", "value": 1000}, {"name": "beta", "value": 2}]
ARRHENIUS = [{"name": "a", "value": 6694}, {"name": "b", "value": 2e-5}]


def _strict(out: dict) -> None:
    json.dumps(out, allow_nan=False)


# ---- Sequential --------------------------------------------------------------------------

def test_sequential_mtbf_matches_surpyval():
    out = T.sequential_test(mtbf=1000, good_mtbf=2000, confidence=0.9, producer_risk=0.1, unit="hours")
    # Truncated, the lines drawn for 10% / 10% run at 12% / 10%: the plan
    # draws them tighter until the test as run keeps both risks.
    ref = _seq_mtbf()
    assert ref.consumer_risk <= 0.1 and ref.producer_risk <= 0.1
    assert tp.sequential_mtbf_test(1000, 2000, alpha_ci=0.1, producer_risk=0.1).consumer_risk > 0.1
    assert out["summary"].startswith("As run, this test shows the target with 90.4% confidence (90% asked)")
    _strict(out)
    assert out["max_time"] == pytest.approx(ref.max_time) and out["max_failures"] == ref.max_failures
    assert out["consumer_risk"] == pytest.approx(ref.consumer_risk)
    assert out["producer_risk"] == pytest.approx(ref.producer_risk)
    assert out["boundaries"]["accept"][3] == pytest.approx(ref.accept_time(3))
    assert out["boundaries"]["reject"][:4] == [None] * 4  # no reject line before the 4th failure
    assert out["boundaries"]["reject"][5] == pytest.approx(ref.reject_time(5))
    assert out["expected"]["at_good"] == pytest.approx(float(ref.expected_test_time(2000)))
    fixed = tp.mtbf_demonstration_plan(1000, 2000, alpha_ci=0.1, producer_risk=0.1)
    assert out["expected"]["fixed_length"] == pytest.approx(fixed.test_time)
    oc = out["oc_curve"]
    assert len(oc["x"]) == len(oc["pass_probability"]) == len(oc["expected"])
    assert oc["pass_probability"][0] < 0.01 and oc["pass_probability"][-1] > 0.99
    assert np.all(np.diff(oc["pass_probability"]) >= -1e-9)
    assert "12,834 hours on average" in out["summary"]


def _seq_mtbf(producer_risk=0.1):
    return T._keeping_risks(lambda a, b: tp.sequential_mtbf_test(1000, 2000, alpha_ci=a, producer_risk=b),
                            0.1, producer_risk)


def test_sequential_decision():
    ref = _seq_mtbf(0.1)
    for r, t in ((0, 100.0), (0, 5100.0), (6, 1000.0)):
        out = T.sequential_test(mtbf=1000, good_mtbf=2000, confidence=0.9, failures_seen=r, time_seen=t)
        assert out["decision"]["verdict"] == ref.decide(r, t)
    assert T.sequential_test(mtbf=1000, good_mtbf=2000, confidence=0.9, failures_seen=0,
                             time_seen=5100)["decision"]["text"].startswith("Accept")


def test_sequential_attribute_matches_surpyval():
    out = T.sequential_test(method="attribute", reliability=0.9, good_reliability=0.97, confidence=0.9,
                            producer_risk=0.1, failures_seen=1, units_seen=40)
    ref = T._keeping_risks(
        lambda a, b: tp.sequential_demonstration_test(0.9, 0.97, alpha_ci=a, producer_risk=b), 0.1, 0.1)
    assert ref.consumer_risk <= 0.1 and ref.producer_risk <= 0.1
    _strict(out)
    assert out["max_units"] == ref.max_units
    assert out["boundaries"]["reject"][10] == ref.reject_failures(10)
    assert out["boundaries"]["accept"][0] is None  # can't accept yet
    assert out["expected"]["at_good"] == pytest.approx(float(ref.expected_units(0.97)))
    assert out["decision"]["verdict"] == ref.decide(40, 1)


@pytest.mark.parametrize("kwargs, message", [
    (dict(mtbf=1000), "good design"),
    (dict(mtbf=1000, good_mtbf=900), "must be above"),
    (dict(mtbf=1000, good_mtbf=1100), "1.25 times"),
    (dict(method="attribute", reliability=0.9, good_reliability=0.8), "must be above"),
    (dict(method="nope"), "method"),
    (dict(mtbf=1000, good_mtbf=2000, failures_seen=1), "total test time"),
])
def test_sequential_refusals(kwargs, message):
    with pytest.raises(StrategyError, match=message):
        T.sequential_test(**kwargs)


# ---- Life test ---------------------------------------------------------------------------

def test_life_test_precision_matches_surpyval():
    out = T.life_test(params=WEIBULL, units=30, censor_time=500, confidence=0.95, unit="hours")
    ref = tp.life_test_precision(surpyval.Weibull, (1000, 2), 30, censor_time=500)
    _strict(out)
    assert out["precision"] == pytest.approx(ref.precision) and out["estimate"] == pytest.approx(ref.estimate)
    assert out["interval"] == pytest.approx([ref.estimate / ref.precision, ref.estimate * ref.precision])
    assert out["label"] == "B10" and "30 units" in out["summary"]
    curve = out["curve"]
    assert 30 in curve["x"] and curve["selected"] == 30
    assert all(a >= b for a, b in zip(curve["precision"], curve["precision"][1:]))  # more units, tighter


def test_life_test_sample_size_and_length_match_surpyval():
    out = T.life_test(solve_for="units", params={"alpha": 1000, "beta": 2}, precision=30, censor_time=600,
                      confidence=0.9)
    assert out["n"] == tp.life_test_sample_size(surpyval.Weibull, (1000, 2), 1.3, censor_time=600,
                                                alpha_ci=0.1).n == 72
    out = T.life_test(solve_for="length", params=(1000, 2), units=40, precision=50, confidence=0.9)
    ref = tp.life_test_length(surpyval.Weibull, (1000, 2), 40, 1.5, alpha_ci=0.1)
    assert out["censor_time"] == pytest.approx(ref.censor_time)
    out = T.life_test(solve_for="length", params=(1000, 2), units=40, precision=50, confidence=0.9,
                      test_end="failures")
    assert out["failures"] == tp.life_test_length(surpyval.Weibull, (1000, 2), 40, 1.5, alpha_ci=0.1,
                                                  failure_censored=True).failures


def test_life_test_mean_of_a_lognormal():
    out = T.life_test(distribution="lognormal", params=[{"name": "mu", "value": 6}, {"name": "sigma", "value": 0.5}],
                      units=20, test_end="all", quantity="mean", confidence=0.95)
    ref = tp.life_test_precision(surpyval.LogNormal, (6, 0.5), 20, quantity="mean")
    assert out["precision"] == pytest.approx(ref.precision) and out["label"] == "the mean life"


@pytest.mark.parametrize("kwargs, message", [
    (dict(params=WEIBULL, units=30), "test length"),
    (dict(params=[{"name": "alpha", "value": 1000}], units=30, censor_time=500), "planning values"),
    (dict(solve_for="length", params=WEIBULL, units=5, precision=20), "test more units"),
    (dict(params=WEIBULL, units=30, test_end="failures"), "share of units failed"),
    (dict(distribution="gamma", params=WEIBULL, units=30), "weibull"),
])
def test_life_test_refusals(kwargs, message):
    with pytest.raises(StrategyError, match=message):
        T.life_test(**kwargs)


# ---- Accelerated -------------------------------------------------------------------------

def test_accelerated_plan_matches_surpyval():
    out = T.accelerated_test(life_params=ARRHENIUS, shape=2, use_stress=323, high_stress=393, units=40,
                             censor_time=1000, unit="hours", stress_unit="K")
    ref = tp.accelerated_test_plan(surpyval.Weibull, _al.LIFE_MODELS["Exponential"], {"a": 6694, "b": 2e-5}, 2.0,
                                   use_stress=323, high_stress=393, n=40, censor_time=1000, alpha_ci=0.1)
    _strict(out)
    assert out["stresses"] == pytest.approx(list(ref.stresses)) and out["units"] == list(ref.units)
    assert out["precision"] == pytest.approx(ref.precision)
    assert [r["units"] for r in out["rows"]] == list(ref.units)
    assert out["total_expected_failures"] == pytest.approx(sum(ref.expected_failures))
    assert out["alternatives"][0]["levels"] == 3  # the compromise plan, for comparison
    assert out["summary"].startswith(f"Test {ref.units[0]} at ")


def test_accelerated_check_of_your_own_test():
    out = T.accelerated_test(mode="check", life_params={"a": 6694, "b": 2e-5}, shape=2, use_stress=323,
                             stresses=[353, 373, 393], units_at=[20, 10, 10], censor_time=1000)
    ref = tp.accelerated_test_precision(surpyval.Weibull, _al.LIFE_MODELS["Exponential"], {"a": 6694, "b": 2e-5},
                                        2.0, use_stress=323, stresses=[353, 373, 393], units=[20, 10, 10],
                                        censor_time=1000, alpha_ci=0.1)
    assert out["precision"] == pytest.approx(ref.precision)


def test_accelerated_warns_when_failures_are_few():
    out = T.accelerated_test(mode="check", life_params={"a": 6694, "b": 2e-5}, shape=2, use_stress=323,
                             stresses=[333, 393], units_at=[10, 10], censor_time=300)
    assert any("fewer than 3 failures" in w for w in out["warnings"])


# The planning values of a capacitor's Arrhenius-Weibull fit: B10 at 40 °C is about 136,500 hours.
CAPACITOR = dict(mode="check", life_params={"a": 6957, "b": 8.39e-5}, shape=2.236, censor_time=1000, unit="hours")


def test_accelerated_too_wide_to_quote_is_said_in_words():
    # 20 units at 100 °C expect about 0.1 failures, so the slope rests on 145 °C alone: the
    # precision factor is about 1,020 (an independent Fisher-information check gives 1,017).
    out = T.accelerated_test(**CAPACITOR, use_stress=313.15, stresses=[373.15, 418.15], units_at=[20, 20],
                             stress_unit="K")
    assert out["precision"] == pytest.approx(1017, rel=0.01)
    assert re.search(r"factor of 1,0\d\d at 90% confidence \(two-sided\)", out["summary"])
    assert "e+03" not in out["summary"]
    assert "too wide to quote" in out["summary"]
    assert any("can't say much" in w and "(373 K) expects 0.1 failures" in w for w in out["warnings"])


def test_accelerated_temperatures_in_celsius_are_worked_in_kelvin():
    k = T.accelerated_test(**CAPACITOR, use_stress=313.15, stresses=[373.15, 418.15], units_at=[20, 20],
                           stress_unit="K")
    c = T.accelerated_test(**CAPACITOR, use_stress=40, stresses=[100, 145], units_at=[20, 20], stress_unit="°C")
    assert c["precision"] == pytest.approx(k["precision"])
    assert [r["stress"] for r in c["rows"]] == pytest.approx([100, 145])
    assert "(40 °C: 136,500 hours" in c["summary"] and "20 at 100 °C" in c["summary"]
    plan = T.accelerated_test(life_params={"a": 6957, "b": 8.39e-5}, shape=2.236, censor_time=1000, units=40,
                              use_stress=40, high_stress=145, stress_unit="C")
    assert max(r["stress"] for r in plan["rows"]) == pytest.approx(145)
    # The simulation check rebuilds the same plan from the °C answer.
    _, sim_plan = T._plan_for("accelerated", dict(CAPACITOR, use_stress=40, stresses=[100, 145], units_at=[20, 20],
                                                  stress_unit="°C"))
    assert sim_plan.precision == pytest.approx(k["precision"])
    with pytest.raises(StrategyError, match="kelvin"):
        T.accelerated_test(**CAPACITOR, use_stress=-300, stresses=[373.15, 418.15], units_at=[20, 20], stress_unit="K")


@pytest.mark.parametrize("kwargs, message", [
    (dict(life_model="dual_power"), "life_model"),
    (dict(life_params=[{"name": "a", "value": 1}]), "planning values"),
    (dict(high_stress=None), "highest stress"),
    (dict(high_stress=300), "shorter"),
])
def test_accelerated_refusals(kwargs, message):
    base = dict(life_params=ARRHENIUS, shape=2, use_stress=323, high_stress=393, units=40, censor_time=1000)
    with pytest.raises(StrategyError, match=message):
        T.accelerated_test(**{**base, **kwargs})


# ---- Comparison --------------------------------------------------------------------------

def test_logrank_matches_surpyval():
    out = T.comparison(hazard_ratio=0.6, event_probability=0.5, power=0.8, confidence=0.95)
    assert out["events"] == tp.logrank_events(0.6, 0.8) == 121
    assert (out["units_new"], out["units_old"]) == tp.logrank_sample_size(0.6, 0.5, 0.8)
    out = T.comparison(solve_for="power", hazard_ratio=0.6, event_probability=0.5, units_per_group=80)
    # 90% confidence by default, as every plan in the app.
    assert out["power"] == pytest.approx(tp.logrank_power(0.6, (80, 80), 0.5, alpha_ci=0.1))
    assert "below the usual 80%" in out["summary"]
    _strict(out)


def test_rate_ratio_matches_surpyval():
    rate = 40 / 100_000
    out = T.comparison(kind="rate_ratio", solve_for="exposure", failures_before=40, exposure_before=100_000,
                       rate_ratio=0.5, unit="hours")
    assert out["exposure_after"] == pytest.approx(tp.rate_ratio_exposure(0.5, rate, 100_000, 0.8, alpha_ci=0.1))
    out = T.comparison(kind="rate_ratio", solve_for="detectable", failures_before=40, exposure_before=100_000,
                       exposure_after=50_000)
    assert out["detectable_ratio"] == pytest.approx(tp.rate_ratio_detectable(rate, 100_000, 50_000, 0.8,
                                                                              alpha_ci=0.1))
    out = T.comparison(kind="rate_ratio", solve_for="power", failures_before=40, exposure_before=100_000,
                       exposure_after=50_000, rate_ratio=0.5, one_sided=True)
    assert out["power"] == pytest.approx(tp.rate_ratio_power(0.5, rate, 100_000, 50_000, alpha_ci=0.1,
                                                             alternative="one-sided"))
    _strict(out)


def test_rate_ratio_says_when_no_exposure_is_enough():
    out = T.comparison(kind="rate_ratio", solve_for="exposure", failures_before=3, exposure_before=30_000,
                       rate_ratio=0.5)
    _strict(out)
    assert out["exposure_after"] is None and "no amount of operation" in out["summary"]


@pytest.mark.parametrize("kwargs, message", [
    (dict(kind="nope"), "kind"),
    (dict(hazard_ratio=1, event_probability=0.5), "no change"),
    (dict(hazard_ratio=0.6), "chance a unit fails"),
    (dict(kind="rate_ratio", solve_for="exposure", failures_before=4, exposure_before=100), "change to detect"),
    (dict(kind="rate_ratio", solve_for="detectable", failures_before=4, exposure_before=100), "after the change"),
])
def test_comparison_refusals(kwargs, message):
    with pytest.raises(StrategyError, match=message):
        T.comparison(**kwargs)


# ---- Simulation check --------------------------------------------------------------------

def test_simulation_matches_surpyval_with_the_same_seed():
    request = T.simulation_request("life", {"params": WEIBULL, "units": 30, "censor_time": 500}, n_sim=60)
    out = compute_core.run("test_precision", request)
    ref = tp.life_test_precision(surpyval.Weibull, (1000, 2), 30, censor_time=500, alpha_ci=0.1).simulate(
        60, random_state=T.SIM_SEED)
    assert out["simulated"]["precision"] == pytest.approx(ref.precision)
    assert out["planned_precision"] == pytest.approx(1.4983, abs=1e-3)
    assert out["summary"].startswith("The plan holds up")


def test_simulation_request_checks_inputs_before_queueing():
    with pytest.raises(StrategyError, match="test length"):
        T.simulation_request("life", {"params": WEIBULL, "units": 30})
    with pytest.raises(StrategyError, match="kind"):
        T.simulation_request("sequential", {})
    with pytest.raises(StrategyError, match="Simulated tests"):
        T.simulation_request("life", {"params": WEIBULL, "units": 30, "censor_time": 1}, n_sim=1_000_000)
    assert "test_precision" in compute_core.KINDS


# ---- REST --------------------------------------------------------------------------------

@pytest.mark.parametrize("path, body, key", [
    ("sequential", {"mtbf": 1000, "good_mtbf": 2000}, "boundaries"),
    ("life", {"params": WEIBULL, "units": 30, "censor_time": 500}, "precision"),
    ("accelerated", {"life_params": ARRHENIUS, "shape": 2, "use_stress": 323, "high_stress": 393, "units": 40,
                     "censor_time": 1000}, "rows"),
    ("comparison", {"hazard_ratio": 0.6, "event_probability": 0.5}, "events"),
])
def test_rest_routes(client, path, body, key):  # noqa: F811
    res = client.post(f"/api/test-planning/{path}", json=body)
    assert res.status_code == 200, res.text
    assert key in res.json()
    bad = client.post(f"/api/test-planning/{path}", json={**body, "nonsense": 1})
    assert bad.status_code == 422 and "nonsense" in bad.json()["detail"]


def test_rest_refusal_is_a_422(client):  # noqa: F811
    res = client.post("/api/test-planning/sequential", json={"mtbf": 1000, "good_mtbf": 500})
    assert res.status_code == 422 and "must be above" in res.json()["detail"]


SIM = {"kind": "life", "inputs": {"params": WEIBULL, "units": 30, "censor_time": 500}, "n_sim": 40}


def test_simulation_is_pro(client, monkeypatch):  # noqa: F811
    from backend import config

    monkeypatch.setattr(config, "BILLING_ENABLED", True)
    res = client.post("/api/test-planning/simulate", json=SIM)
    assert res.status_code == 402 and res.json()["code"] == "pro_required"
    # The plans themselves stay free.
    assert client.post("/api/test-planning/life", json=SIM["inputs"]).status_code == 200


def test_simulation_runs_in_process_without_a_queue(client):  # noqa: F811
    res = client.post("/api/test-planning/simulate", json=SIM)  # billing off: everyone is entitled
    assert res.status_code == 200, res.text
    assert res.json()["simulated"]["n_sim"] == 40


def test_simulation_queues_a_job(client, monkeypatch):  # noqa: F811
    from backend.services import compute_queue, rbd_jobs

    sent = []
    monkeypatch.setattr(compute_queue, "configured", lambda: True)
    monkeypatch.setattr(compute_queue, "enqueue", lambda job_id, kind, request: sent.append((job_id, kind)))
    res = client.post("/api/test-planning/simulate", json=SIM)
    assert res.status_code == 202, res.text
    job = res.json()["job"]
    assert sent == [(job["job_id"], "test_precision")]
    # Asked again while it runs: the same job.
    again = client.post("/api/test-planning/simulate", json=SIM).json()["job"]
    assert again["job_id"] == job["job_id"] and len(sent) == 1
    # Finished: the result as it came back, at the job's URL.
    result = compute_core.run("test_precision", client.db.rbd_jobs.find_one({"_id": job["job_id"]})["request"])
    rbd_jobs.finish(client.db, job["job_id"], "done", result=result)
    view = client.get(f"/api/rbd-jobs/{job['job_id']}").json()
    assert view["status"] == "done" and view["result"]["simulated"]["n_sim"] == 40


# ---- MCP ---------------------------------------------------------------------------------

def test_mcp_actions(env):  # noqa: F811
    tok = env.token[A]
    seq = _ok(_call(tok, "analyse", {"action": "plan_sequential_test", "mtbf": 1000,
                                                "design_mtbf": 2000, "unit": "hours", "failures_seen": 0,
                                                "time_seen": 5100}))
    assert seq["decision"]["verdict"] == "accept" and seq["boundaries"][0]["failures"] == 0
    assert "oc_curve" not in seq
    att = _ok(_call(tok, "analyse", {"action": "plan_sequential_test", "method": "attribute",
                                                "reliability": 0.9, "design_reliability": 0.97}))
    assert len(att["boundaries"]) < att["max_units"]  # stepped rows, not one per unit
    life = _ok(_call(tok, "analyse", {"action": "plan_life_test", "params": WEIBULL, "units": 30,
                                                 "censor_time": 500}))
    assert life["n"] == 30 and "curve" not in life
    alt = _ok(_call(tok, "analyse", {"action": "plan_accelerated_test", "life_params": ARRHENIUS,
                                                "shape": 2, "use_stress": [323], "high_stress": 393, "units": 40,
                                                "censor_time": 1000}))
    assert [r["units"] for r in alt["rows"]] and "fractions" not in alt
    cmp_ = _ok(_call(tok, "analyse", {"action": "plan_comparison", "kind": "logrank",
                                                 "solve_for": "sample_size", "hazard_ratio": 0.6,
                                                 "event_probability": 0.5}))
    assert cmp_["events"] == tp.logrank_events(0.6, 0.8, alpha_ci=0.1) == 95
    assert "must be above" in _err(_call(tok, "analyse", {"action": "plan_sequential_test",
                                                                     "mtbf": 1000, "design_mtbf": 500}))
    guide = _ok(_call(tok, "guide", {"topic": "test_planning"}))
    assert "plan_sequential_test" in guide["guide"]


def test_simulation_calls_a_plan_weak_when_many_tests_cannot_be_fitted():
    """22 units for 1,000 h with B10 at 1,000 h: about 2.2 failures each, so
    about a third of real tests end with 0 or 1 failure and no estimate. The
    survivors' spread looks fine; the plan isn't."""
    from scipy.stats import binom

    alpha = 1000 / (-np.log(0.9)) ** 0.5  # B10 = 1,000 h with beta 2
    request = T.simulation_request("life", {"params": [alpha, 2], "units": 22, "censor_time": 1000}, n_sim=200)
    out = compute_core.run("test_precision", request)
    assert out["verdict"] == "weak"
    assert out["summary"].startswith("The plan is weak")
    # The share unfit is about P(<= 1 failure in 22 at 10% each) = 34%.
    assert out["unusable_share"] == pytest.approx(binom.cdf(1, 22, 0.1), abs=0.08)
    assert "1 in 3" in out["summary"]


def test_sequential_truncated_plan_keeps_the_confidence_asked():
    """90% vs 97%, 90% confidence, 20% producer's risk: Wald's lines cut at
    the fixed-length test ran at 87.7% confidence. The plan now keeps 90%
    and says so first."""
    out = T.sequential_test(method="attribute", reliability=0.9, good_reliability=0.97, confidence=0.9,
                            producer_risk=0.2)
    assert out["consumer_risk"] <= 0.1 + 1e-9 and out["producer_risk"] <= 0.2 + 1e-9
    assert out["summary"].startswith("As run, this test shows the target with 90.2% confidence (90% asked)")
    # Exact: the chance a design at the target passes, by the library's own OC.
    assert out["oc_curve"]["points"][0]["pass_probability"] == pytest.approx(out["consumer_risk"])


# ---- A saved sequential test ------------------------------------------------------------


def test_a_sequential_rule_is_saved_recomputed_and_reads_its_verdict(client):  # noqa: F811
    """The agreed rule goes on record before the data comes in, and again with each verdict;
    the server recomputes it from the inputs (never the client's result)."""
    body = {"method": "mtbf", "mtbf": 60000, "good_mtbf": 120000, "confidence": 0.9, "producer_risk": 0.1,
            "unit": "hours"}
    r = client.post("/api/strategy/analyses", json={"name": "Controller rule", "kind": "sequential_test",
                                                    "inputs": body})
    assert r.status_code == 200, r.text
    saved = r.json()
    plan = T.sequential_test(**body)
    assert saved["results"]["max_failures"] == plan["max_failures"]
    assert saved["results"]["max_time"] == pytest.approx(plan["max_time"])
    assert saved["headline"].startswith("Sequential test: at most ")
    assert saved["headline"].endswith(f"hours or {plan['max_failures']} failures")
    r = client.post("/api/strategy/analyses", json={"name": "Feb verdict", "kind": "sequential_test",
                                                    "inputs": {**body, "failures_seen": 2, "time_seen": 471168}})
    assert r.status_code == 200, r.text
    assert r.json()["results"]["decision"]["verdict"] == "accept"
    assert r.json()["headline"].startswith("Accept so far · Sequential test")
    attr = client.post("/api/strategy/analyses", json={"name": "Pass/fail", "kind": "sequential_test", "inputs": {
        "method": "attribute", "reliability": 0.9, "good_reliability": 0.97, "confidence": 0.9}})
    assert attr.status_code == 200, attr.text
    assert "units or" in attr.json()["headline"]
    bad = client.post("/api/strategy/analyses", json={"name": "Bad", "kind": "sequential_test",
                                                      "inputs": {"method": "mtbf", "mtbf": 1000}})
    assert bad.status_code == 422 and "good design" in bad.json()["detail"]
