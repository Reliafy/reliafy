"""Demonstration test plans that keep both risks (#223): RePyability 0.12's
``demonstration_plan`` / ``mtbf_demonstration_plan`` behind the calculator's
``producer_risk``, the operating-characteristic curve, the saved analysis,
the REST endpoints and the MCP tool."""

import mongomock
import pytest
from repyability import (
    demonstration_pass_probability,
    demonstration_plan,
    mtbf_demonstration_plan,
    mtbf_pass_probability,
)
from scipy import stats

from backend.services import strategy_store
from backend.services.strategy import StrategyError, demonstration_test
from backend.tests.test_demonstration import client  # noqa: F401 - a fixture
from backend.tests.test_mcp import A, _call, _err, _ok, env  # noqa: F401 - env is a fixture


# ---- the library's own examples -----------------------------------------------------


def test_attribute_plan_is_the_librarys_and_keeps_both_risks():
    # RePyability's docstring: 90% at 90% confidence, a 95% design passing >= 80%: 128 units, 8 failures.
    out = demonstration_test(0.9, 0.9, design_reliability=0.95, producer_risk=0.2,
                             mission_time=1000, unit="hours", failures=0)  # failures is the plan's own
    plan = demonstration_plan(0.9, 0.95, confidence=0.9, producer_risk=0.2)
    assert (out["units"], out["failures"]) == (plan.n, plan.failures) == (128, 8)
    assert out["two_risk"] is True and out["producer_risk_target"] == 0.2
    assert out["consumer_risk"] == pytest.approx(plan.consumer_risk, rel=1e-12)
    assert out["producer_risk"] == pytest.approx(plan.producer_risk, rel=1e-12)
    assert out["consumer_risk"] <= 0.1 and out["producer_risk"] <= 0.2
    # Against a direct binomial computation.
    assert out["consumer_risk"] == pytest.approx(stats.binom.cdf(8, 128, 0.1), rel=1e-12)
    assert out["producer_risk"] == pytest.approx(1 - stats.binom.cdf(8, 128, 0.05), rel=1e-12)
    assert out["summary"] == (
        "Test 128 units for 1,000 hours each with at most 8 failures to show R(1,000 hours) ≥ 90% at 90% "
        "confidence. The plan keeps both risks: a design at the target passes 9.7% of the time (consumer's "
        "risk, at most 10%), and one whose true reliability is 95% fails 19.2% of the time (producer's "
        "risk, at most 20%).")
    assert any("producer's risk, at most 20%" in a for a in out["assumptions"])
    # The trade-off gains the plan's own column, its cell the plan.
    t = out["tradeoff"]
    assert t["failures"] == [0, 1, 2, 3, 8] and t["rows"][0]["values"][-1] == 128


def test_the_success_run_alone_fails_the_good_design_often():
    # The motivation: the 22-unit success run passes a 95% design only a third of the time.
    alone = demonstration_test(0.9, 0.9, design_reliability=0.95)
    assert (alone["units"], alone["failures"]) == (22, 0) and alone["two_risk"] is False
    assert alone["producer_risk"] == pytest.approx(1 - demonstration_pass_probability(0.95, 22))
    assert alone["producer_risk"] > 0.6 and alone["producer_risk_target"] is None


def test_a_longer_test_with_a_weibull_shape():
    out = demonstration_test(0.9, 0.9, design_reliability=0.95, producer_risk=0.2, test_multiple=2, shape=1.5)
    plan = demonstration_plan(0.9, 0.95, confidence=0.9, producer_risk=0.2, test_multiple=2.0, shape=1.5)
    assert (out["units"], out["failures"]) == (plan.n, plan.failures)
    assert out["producer_risk"] == pytest.approx(plan.producer_risk, rel=1e-12)


def test_units_given_the_plan_searches_the_test_length():
    out = demonstration_test(0.9, 0.9, design_reliability=0.95, producer_risk=0.2, units=60, shape=2,
                             mission_time=1000, unit="hours")
    plan = demonstration_plan(0.9, 0.95, confidence=0.9, producer_risk=0.2, n=60, shape=2.0)
    assert out["solve_for"] == "test_time" and out["units"] == 60
    assert out["failures"] == plan.failures and out["test_multiple"] == pytest.approx(plan.test_multiple)
    assert out["test_time_per_unit"] == pytest.approx(1000 * plan.test_multiple)
    assert out["producer_risk"] == pytest.approx(plan.producer_risk, rel=1e-9) and out["producer_risk"] <= 0.2


def test_mtbf_plan_is_mil_hdbk_781s():
    # RePyability's docstring: an MTBF of 1000 at 90%, a 2000 design passing >= 80%: ~14,206 h, 9 failures.
    out = demonstration_test(method="mtbf", mtbf=1000, confidence=0.9, design_mtbf=2000, producer_risk=0.2,
                             units=10, unit="hours")
    plan = mtbf_demonstration_plan(1000.0, 2000.0, confidence=0.9, producer_risk=0.2)
    assert out["failures"] == plan.failures == 9
    assert out["total_test_time"] == pytest.approx(plan.test_time, rel=1e-12)
    assert round(out["total_test_time"]) == 14206 and out["test_time_per_unit"] == pytest.approx(1420.6, rel=1e-4)
    assert out["producer_risk"] == pytest.approx(plan.producer_risk, rel=1e-12) and out["producer_risk"] <= 0.2
    assert out["consumer_risk"] == pytest.approx(stats.poisson.cdf(9, plan.test_time / 1000), rel=1e-12)
    assert "discrimination ratio of 2" in " ".join(out["assumptions"])
    assert out["summary"].endswith("(producer's risk, at most 20%).")


# ---- operating characteristic -------------------------------------------------------


def test_attribute_oc_curve_is_the_pass_probability():
    out = demonstration_test(0.9, 0.9, design_reliability=0.95, producer_risk=0.2)
    oc = out["oc_curve"]
    assert oc["x_kind"] == "reliability" and len(oc["x"]) == len(oc["pass_probability"]) == 81
    assert oc["x"][0] == 1.0 and oc["pass_probability"][0] == 1.0
    assert oc["x"] == sorted(oc["x"], reverse=True)  # from 1 down
    assert all(a >= b for a, b in zip(oc["pass_probability"], oc["pass_probability"][1:]))
    assert oc["pass_probability"][-1] <= 0.005 and oc["x"][-1] < 0.9
    for x, p in zip(oc["x"][1::10], oc["pass_probability"][1::10]):
        assert p == pytest.approx(demonstration_pass_probability(x, 128, 8), rel=1e-12)
    target, good = oc["points"]
    assert target == {"label": "Target", "x": 0.9, "pass_probability": out["consumer_risk"]}
    assert good["x"] == 0.95 and good["pass_probability"] == pytest.approx(1 - out["producer_risk"])


def test_mtbf_oc_curve_spans_both_tails():
    out = demonstration_test(method="mtbf", mtbf=1000, confidence=0.9, design_mtbf=2000, producer_risk=0.2)
    oc = out["oc_curve"]
    assert oc["x_kind"] == "mtbf" and oc["x"] == sorted(oc["x"])
    assert oc["pass_probability"][0] <= 0.005 and oc["pass_probability"][-1] >= 0.995
    assert oc["x"][0] < 1000 < 2000 < oc["x"][-1]
    x, p = oc["x"][40], oc["pass_probability"][40]
    assert p == pytest.approx(mtbf_pass_probability(x, out["total_test_time"], 9), rel=1e-12)


def test_every_plan_has_an_oc_curve():
    out = demonstration_test(0.95, 0.95)
    assert out["oc_curve"]["points"] == [{"label": "Target", "x": 0.95, "pass_probability": out["consumer_risk"]}]
    assert demonstration_test(method="mtbf", mtbf=500)["oc_curve"]["x_kind"] == "mtbf"


# ---- validation -------------------------------------------------------------------


@pytest.mark.parametrize("kwargs, message", [
    ({"reliability": 0.9, "producer_risk": 0.2}, "needs the good design's reliability"),
    ({"reliability": 0.9, "producer_risk": 0.2, "design_reliability": 0.9}, "must be above the target"),
    ({"reliability": 0.9, "producer_risk": 1.2, "design_reliability": 0.95}, "Producer's risk must be strictly"),
    ({"reliability": 0.9, "producer_risk": 0.2, "design_reliability": 0.9001}, "No plan allowing up to 100"),
    ({"reliability": 0.9, "producer_risk": 0.2, "design_reliability": 0.95, "units": 5, "shape": 2},
     "No test of these units keeps both risks"),
    ({"method": "mtbf", "mtbf": 100, "producer_risk": 0.2}, "needs the good design's MTBF"),
    ({"method": "mtbf", "mtbf": 100, "producer_risk": 0.2, "design_mtbf": 50}, "must be above the target"),
])
def test_validation(kwargs, message):
    with pytest.raises(StrategyError, match=message):
        demonstration_test(**kwargs)


def test_a_blank_producer_risk_is_ignored():
    out = demonstration_test(0.95, 0.95, design_reliability=0.99, producer_risk="")
    assert out["units"] == 59 and out["two_risk"] is False


# ---- saved analysis, REST, MCP -------------------------------------------------------


def test_saved_analysis_keeps_the_producer_risk(monkeypatch):
    from backend import db as db_module

    session = mongomock.MongoClient()["reliafy_test"]
    monkeypatch.setattr(db_module, "_db", session)
    monkeypatch.setattr(db_module, "_simulated", True)
    doc = strategy_store.save_analysis(session, "Two-risk", "demonstration_test", {
        "reliability": 0.9, "confidence": 0.9, "design_reliability": 0.95, "producer_risk": 0.2}, A)
    assert doc.results["units"] == 128 and doc.results["two_risk"] is True
    assert strategy_store.headline(doc) == "128 units × 1 mission, ≤8 failures"


def test_app_and_v1_endpoints_take_the_producer_risk(client):  # noqa: F811
    body = {"reliability": 0.9, "confidence": 0.9, "design_reliability": 0.95, "producer_risk": 0.2}
    r = client.post("/api/strategy/demonstration-test", json=body)
    assert r.status_code == 200, r.text
    assert (r.json()["units"], r.json()["failures"]) == (128, 8) and r.json()["oc_curve"]["points"]
    raw = client.post("/api/tokens", json={"name": "test"}).json()["token"]
    r = client.post("/api/v1/strategy/demonstration-test", headers={"Authorization": f"Bearer {raw}"},
                    json={"method": "mtbf", "mtbf": 1000, "confidence": 0.9, "design_mtbf": 2000,
                          "producer_risk": 0.2})
    assert r.status_code == 200, r.text
    assert r.json()["failures"] == 9
    r = client.post("/api/strategy/demonstration-test", json={"reliability": 0.9, "producer_risk": 0.2})
    assert r.status_code == 422 and "good design" in r.json()["detail"]


def test_mcp_plan_demonstration_test_keeps_both_risks(env):
    out = _ok(_call(env.token[A], "plan_demonstration_test", {
        "reliability": 0.9, "confidence": 0.9, "design_reliability": 0.95, "producer_risk": 0.2}))
    assert (out["units"], out["failures"]) == (128, 8)
    assert out["producer_risk"] <= out["producer_risk_target"] == 0.2 and out["consumer_risk"] <= 0.1
    assert "oc_curve" not in out  # lean: no plotting fields

    mtbf = _ok(_call(env.token[A], "plan_demonstration_test", {
        "method": "mtbf", "mtbf": 1000, "confidence": 0.9, "design_mtbf": 2000, "producer_risk": 0.2,
        "unit": "hours"}))
    assert mtbf["failures"] == 9 and round(mtbf["total_test_time"]) == 14206 and mtbf["design_mtbf"] == 2000
    assert "good design's reliability" in _err(_call(env.token[A], "plan_demonstration_test", {
        "reliability": 0.9, "producer_risk": 0.2}))
