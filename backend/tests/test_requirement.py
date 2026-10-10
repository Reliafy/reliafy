"""A B-life requirement on a fitted model, and a demonstration test to show
it (#295): the verdict on SurPyval's own lower bound, the B-life test mode,
and the warning when a fitted β is too poorly known for the plan."""

import matplotlib

matplotlib.use("Agg")

import io

import numpy as np
import pandas as pd
import pytest
from repyability import demonstration as demo
from surpyval import Weibull

from backend import fitting, life_bounds
from backend.life_requirement import check_requirement
from backend.services import strategy_store
from backend.services.strategy import StrategyError, demonstration_test
from backend.tests.test_life_bounds import A, B, client  # noqa: F401 - client is a fixture
from backend.tests.test_mcp import _call, _err, _ok, env  # noqa: F401 - env is a fixture
from backend.tests.test_mcp import A as MCP_USER

# Five failures: β ≈ 2.08 with a 95% interval of about [1.03, 4.21].
FIVE = [400, 900, 1300, 1600, 2400]


def _model(seed=7, n=60):
    rng = np.random.default_rng(seed)
    t = rng.weibull(2.0, n) * 1000
    c = (t > 1400).astype(int)
    return np.where(c == 1, 1400, t), c


def _b10(model, confidence):
    return float(model.qf(0.1)), float(model.quantile_cb(0.1, alpha_ci=1 - confidence, bound="lower"))


# ---- the verdict ------------------------------------------------------------------


def test_verdict_turns_on_surpyvals_lower_bound():
    model = Weibull.fit(*_model())
    est, lo = _b10(model, 0.9)
    assert lo < est

    meets = check_requirement(model, 10, lo * 0.99, 0.9, unit="Cycles")
    assert meets["verdict"] == "meets" and meets["meets"] is True
    assert meets["estimate"] == pytest.approx(est, rel=1e-9) and meets["lower"] == pytest.approx(lo, rel=1e-9)
    assert meets["label"] == "B10" and meets["confidence"] == 0.9
    assert meets["summary"].startswith("Meets: at 90% confidence B10 ≥ ") and " cycles" in meets["summary"]

    # The estimate meets it, the bound doesn't: does NOT meet, and says why.
    between = (lo + est) / 2
    out = check_requirement(model, 10, between, 0.9)
    assert out["verdict"] == "does_not_meet" and out["meets"] is False and out["estimate_meets"] is True
    assert out["summary"].startswith("Does not meet: at 90% confidence B10 ≥ ")
    assert "best estimate meets it" in out["summary"]

    # Both below.
    far = check_requirement(model, 10, est * 2, 0.9)
    assert far["verdict"] == "does_not_meet" and far["estimate_meets"] is False
    assert "best estimate meets it" not in far["summary"]

    # A higher confidence lowers the bound: what met at 80% may not at 99%.
    _, lo80 = _b10(model, 0.8)
    _, lo99 = _b10(model, 0.99)
    req = (lo80 + lo99) / 2
    assert check_requirement(model, 10, req, 0.8)["verdict"] == "meets"
    assert check_requirement(model, 10, req, 0.99)["verdict"] == "does_not_meet"


def test_other_b_lives_are_other_quantiles():
    model = Weibull.fit(*_model())
    out = check_requirement(model, 1, 10, 0.95)
    assert out["label"] == "B1"
    assert out["lower"] == pytest.approx(float(model.quantile_cb(0.01, alpha_ci=0.05, bound="lower")), rel=1e-9)
    assert check_requirement(model, 0.1, 10, 0.9)["label"] == "B0.1"


def test_a_model_without_bounds_cant_be_checked():
    r = fitting.result_from_params("weibull", [{"name": "alpha", "value": 1000}, {"name": "beta", "value": 2}])
    model = Weibull.from_params([1000, 2])
    out = check_requirement(model, 10, 100, 0.9, unit="hours")
    assert out["verdict"] == "unknown" and out["meets"] is None and out["lower"] is None
    assert out["estimate"] == pytest.approx(float(model.qf(0.1)))
    assert out["estimate_meets"] is True and "covariance" in out["bounds_note"]
    assert out["summary"].startswith("Can't check at 90% confidence") and "at or above" in out["summary"]
    assert r["life"]["bounds_note"] == out["bounds_note"]


@pytest.mark.parametrize("b, life", [(0, 100), (100, 100), ("x", 100), (10, 0), (10, -5), (10, "x"),
                                     (None, 100), (10, None)])
def test_bad_requirements_are_refused(b, life):
    model = Weibull.fit(*_model())
    with pytest.raises(ValueError):
        check_requirement(model, b, life, 0.9)
    with pytest.raises(ValueError):
        life_bounds.answer(model, {"requirement": {"b": b, "life": life}})


def test_the_life_paths_answer_a_requirement(client):  # noqa: F811 - the fixture
    t, c = _model()
    csv = io.BytesIO(pd.DataFrame({"t": t, "c": c}).to_csv(index=False).encode())
    fresh = client.post("/api/fit/weibull", data={"x": "t", "c": "c", "unit": "cycles"},
                        files={"file": ("d.csv", csv, "text/csv")}).json()
    est, lo = _b10(Weibull.fit(t, c), 0.9)
    out = client.post(fresh["functions"]["life_path"],
                      json={"requirement": {"b": 10, "life": est}, "confidence": 0.9, "unit": "cycles"}).json()
    assert out["verdict"] == "does_not_meet" and out["lower"] == pytest.approx(lo, rel=1e-6)
    assert "cycles" in out["summary"]
    assert client.post(fresh["functions"]["life_path"], json={"requirement": {"b": 10}}).status_code == 422

    csv.seek(0)
    saved = client.post("/api/models", data={"name": "Seals", "distribution": "weibull", "x": "t", "c": "c",
                                             "unit": "cycles"},
                        files={"file": ("d.csv", csv, "text/csv")}).json()
    path = f"/api/models/{saved['id']}/life"
    ok = client.post(path, json={"requirement": {"b": 10, "life": lo * 0.9}, "confidence": 0.9}).json()
    assert ok["verdict"] == "meets"
    client.who["uid"] = B
    assert client.post(path, json={"requirement": {"b": 10, "life": 1}}).status_code == 404
    client.who["uid"] = A


# ---- the demonstration test: a B-life requirement ----------------------------------


def test_a_b_life_requirement_is_the_reliability_over_that_life():
    by_b = demonstration_test(confidence=0.9, mission_time=50_000, b_life=10, unit="cycles")
    by_r = demonstration_test(0.9, 0.9, mission_time=50_000, unit="cycles")
    for k in ("units", "failures", "test_time_per_unit", "demonstrated_reliability", "consumer_risk"):
        assert by_b[k] == by_r[k]
    assert by_b["reliability"] == pytest.approx(0.9) and by_b["b_life"] == 10 and by_r["b_life"] is None
    assert by_b["summary"] == (
        "Test 22 units for 50,000 cycles each with no failures to show B10 ≥ 50,000 cycles at 90% confidence.")
    assert by_b["assumptions"][0].startswith("B10 ≥ 50,000 cycles means at most 10% fail by then")

    longer = demonstration_test(confidence=0.9, mission_time=50_000, b_life=10, test_multiple=2, shape=2,
                                unit="cycles")
    assert "(2× the life)" in longer["summary"]
    assert longer["units"] == demo.demonstration_sample_size(0.9, 0.9, 0, test_multiple=2, shape=2)


def test_a_b_life_needs_its_life_and_one_target():
    with pytest.raises(StrategyError, match="needs its life"):
        demonstration_test(confidence=0.9, b_life=10)
    with pytest.raises(StrategyError, match="not both"):
        demonstration_test(0.95, 0.9, mission_time=1000, b_life=10)
    # The same target twice is fine.
    assert demonstration_test(0.9, 0.9, mission_time=1000, b_life=10)["units"] == 22
    for bad in (0, 100, -1, "x"):
        with pytest.raises(StrategyError, match="B-life"):
            demonstration_test(confidence=0.9, mission_time=1000, b_life=bad)


# ---- the demonstration test: β from a fit, and how well it's known ------------------


def _five_failure_beta():
    r = fitting.fit("weibull", pd.DataFrame({"t": FIVE}), {"x": "t"}, unit="cycles")
    beta = next(p for p in r["params"] if p["name"] == "beta")
    return beta["value"], beta["ci"]


def test_a_poorly_known_beta_warns():
    est, (lo, hi) = _five_failure_beta()
    assert lo < 1.1 and hi > 4  # five failures: β's interval is wide

    plan = demonstration_test(confidence=0.9, mission_time=1000, b_life=10, test_multiple=3, shape=est,
                              shape_interval=[lo, hi], shape_model="Five seals", unit="cycles")
    s = plan["shape_sensitivity"]
    assert s["relevant"] and s["uses"] == "estimate" and s["unsafe"] == "lower"
    # What the planned units show if β is really at its lower bound: RePyability's own number.
    n = plan["units"]
    assert s["at_lower"]["demonstrated"] == pytest.approx(
        demo.demonstrated_reliability(n, 0.9, 0, test_multiple=3, shape=lo))
    assert s["at_lower"]["demonstrated"] < 0.9
    assert s["at_lower"]["units"] == demo.demonstration_sample_size(0.9, 0.9, 0, test_multiple=3, shape=lo)
    assert s["at_lower"]["units"] >= 1.25 * n
    assert s["warning"].startswith("β is poorly known")
    assert f"would need {s['at_lower']['units']} units, not {n}" in s["warning"]
    assert s["warning"] in plan["assumptions"] and plan["shape_model"] == "Five seals"

    # The conservative choice: plan with the lower bound — more units, no warning.
    safe = demonstration_test(confidence=0.9, mission_time=1000, b_life=10, test_multiple=3, shape=lo,
                              shape_interval=[lo, hi], unit="cycles")
    assert safe["shape_sensitivity"]["uses"] == "lower" and safe["shape_sensitivity"]["warning"] is None
    assert safe["units"] == s["at_lower"]["units"] > n


def test_a_well_known_beta_or_a_one_mission_test_doesnt_warn():
    narrow = demonstration_test(0.9, 0.9, mission_time=1000, test_multiple=2, shape=2.0,
                                shape_interval=[1.9, 2.1])
    assert narrow["shape_sensitivity"]["warning"] is None and narrow["shape_sensitivity"]["relevant"]
    one = demonstration_test(0.9, 0.9, mission_time=1000, shape=2.0, shape_interval=[1.0, 5.0])
    assert one["shape_sensitivity"]["relevant"] is False and one["shape_sensitivity"]["warning"] is None
    assert demonstration_test(0.9, 0.9)["shape_sensitivity"] is None


def test_solving_for_test_time_warns_with_the_time_needed():
    est, (lo, hi) = _five_failure_beta()
    plan = demonstration_test(confidence=0.9, mission_time=1000, b_life=10, units=3, shape=est,
                              shape_interval=[lo, hi], unit="cycles")
    s = plan["shape_sensitivity"]
    need = demo.demonstration_test_multiple(0.9, 3, 0.9, 0, shape=lo)
    assert s["at_lower"]["test_multiple"] == pytest.approx(need)
    assert "each unit would need" in s["warning"]


def test_bad_intervals_are_refused():
    for bad in ([2.0], [3.0, 2.0], [0, 2], ["a", "b"], [1, 1000]):
        with pytest.raises(StrategyError, match="shape_interval"):
            demonstration_test(0.9, 0.9, test_multiple=2, shape=2, shape_interval=bad)


def test_a_saved_analysis_keeps_the_requirement_and_the_interval():
    est, (lo, hi) = _five_failure_beta()
    inputs = {"b_life": 10, "confidence": 0.9, "mission_time": 1000, "test_multiple": 3, "shape": est,
              "shape_interval": [lo, hi], "shape_model": "Five seals", "unit": "cycles"}
    out = strategy_store.compute("demonstration_test", inputs)
    assert out["b_life"] == 10 and out["shape_sensitivity"]["warning"] and out["shape_model"] == "Five seals"


# ---- MCP -----------------------------------------------------------------------------


def test_mcp_check_life_requirement(env):  # noqa: F811 - the fixture
    t, c = _model()
    saved = _ok(_call(env.token[MCP_USER], "fit_and_save_model", {
        "data": t.tolist(), "censored": c.tolist(), "unit": "cycles", "name": "Seals"}))
    est, lo = _b10(Weibull.fit(t, c), 0.9)
    out = _ok(_call(env.token[MCP_USER], "check_life_requirement", {
        "model_id": saved["model_id"], "b_life": 10, "life": est, "confidence": 0.9}))
    assert out["verdict"] == "does_not_meet" and out["meets"] is False and out["unit"] == "Cycles"
    assert out["lower"] == pytest.approx(lo, rel=1e-3) and out["summary"].startswith("Does not meet")
    met = _ok(_call(env.token[MCP_USER], "check_life_requirement", {
        "model_id": saved["model_id"], "b_life": 10, "life": lo / 2}))
    assert met["verdict"] == "meets"
    assert "not found" in _err(_call(env.token[MCP_USER], "check_life_requirement", {
        "model_id": "nope", "b_life": 10, "life": 1}))


def test_mcp_plans_a_b_life_test_with_beta_from_a_saved_model(env):  # noqa: F811 - the fixture
    saved = _ok(_call(env.token[MCP_USER], "fit_and_save_model", {
        "data": FIVE, "unit": "cycles", "name": "Five seals"}))
    est, (lo, hi) = _five_failure_beta()
    args = {"b_life": 10, "confidence": 0.9, "mission_time": 1000, "test_multiple": 3,
            "shape_model_id": saved["model_id"]}
    out = _ok(_call(env.token[MCP_USER], "plan_demonstration_test", args))
    assert out["b_life"] == 10 and out["unit"] == "Cycles" and out["shape"] == pytest.approx(est, rel=1e-6)
    assert out["shape_model"] == "Five seals" and out["shape_sensitivity"]["warning"]
    assert "B10 ≥ 1,000 cycles" in out["summary"]

    safe = _ok(_call(env.token[MCP_USER], "plan_demonstration_test", {**args, "shape_bound": "lower"}))
    assert safe["shape"] == pytest.approx(lo, rel=1e-6) and safe["shape_sensitivity"]["warning"] is None
    assert safe["units"] > out["units"]

    assert "not both" in _err(_call(env.token[MCP_USER], "plan_demonstration_test", {**args, "shape": 2}))
