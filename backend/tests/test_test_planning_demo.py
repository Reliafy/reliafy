"""The demonstration-test calculator moved from RePyability's ``demonstration``
module to SurPyval 0.25's ``test_planning``. Its answers must not change: run
the calculator on a grid of inputs on both engines and compare the whole
response, every number exactly. Also the failure-terminated MTBF option the
move brought in."""
from __future__ import annotations

import itertools

import pytest
from repyability import demonstration as old_engine
from surpyval import test_planning as tp

from backend.services import demo_engine
from backend.services import strategy as st
from backend.services.strategy import StrategyError, demonstration_test
from backend.tests.test_demonstration import client  # noqa: F401  (the REST fixture)


def _both(monkeypatch, **kwargs):
    """The calculator's answer (or refusal) on the old engine, then the new."""
    out = []
    for engine in (old_engine, demo_engine):
        monkeypatch.setattr(st, "_demo_engine", lambda engine=engine: engine)
        try:
            out.append(("ok", demonstration_test(**kwargs)))
        except StrategyError as exc:
            out.append(("error", str(exc)))
    return out


ATTRIBUTE = [
    dict(reliability=R, confidence=c, failures=r, mission_time=t, unit="hours")
    for R, c, r, t in itertools.product((0.8, 0.9, 0.95, 0.99), (0.8, 0.9, 0.95), (0, 1, 3), (None, 1000))
] + [
    dict(reliability=0.9, confidence=0.9, failures=r, test_multiple=k, shape=b, mission_time=500)
    for r, k, b in itertools.product((0, 2), (0.5, 2.0, 3.0), (1.2, 2.5))
] + [
    dict(reliability=0.95, confidence=c, failures=r, units=n, shape=b, mission_time=100, unit="cycles")
    for c, r, n, b in itertools.product((0.9, 0.95), (0, 1), (10, 25), (1.5, 3.0))
] + [
    dict(reliability=0.9, confidence=0.9, design_reliability=0.98, producer_risk=pr, **extra)
    for pr, extra in itertools.product((0.1, 0.2), ({}, {"units": 40, "shape": 2.0},
                                                     {"test_multiple": 2.0, "shape": 1.5}))
] + [
    dict(b_life=10, mission_time=1000, confidence=0.9, shape=2.0, shape_interval=[1.4, 2.8], test_multiple=1.5,
         shape_model="Pump bearings"),
    dict(b_life=1, mission_time=200, confidence=0.95, shape=1.8, shape_interval=[1.2, 2.6], units=30),
    dict(reliability=0.9, design_reliability=0.95, confidence=0.9),
    dict(reliability=0.9, confidence=0.9, design_reliability=0.905, producer_risk=0.05),  # no plan
]

MTBF = [
    dict(method="mtbf", mtbf=m, confidence=c, failures=r, units=n, unit="hours")
    for m, c, r, n in itertools.product((500, 1000), (0.8, 0.9, 0.95), (0, 1, 4), (None, 5))
] + [
    dict(method="mtbf", mtbf=1000, confidence=c, design_mtbf=g, producer_risk=pr)
    for c, g, pr in itertools.product((0.8, 0.9), (1500, 3000), (0.1, 0.2))
] + [
    dict(method="mtbf", mtbf=1000, confidence=0.9, design_mtbf=2500, failures=2),
]


@pytest.mark.parametrize("kwargs", ATTRIBUTE + MTBF)
def test_old_and_new_engines_give_identical_plans(monkeypatch, kwargs):
    old, new = _both(monkeypatch, **kwargs)
    assert old == new


def test_the_grid_covers_every_engine_function(monkeypatch):
    """Every function the calculator calls is reached by the grid above."""
    called = set()

    class Spy:
        def __getattr__(self, name):
            called.add(name)
            return getattr(demo_engine, name)

    monkeypatch.setattr(st, "_demo_engine", lambda: Spy())
    for kwargs in ATTRIBUTE + MTBF:
        try:
            demonstration_test(**kwargs)
        except StrategyError:
            pass
    assert called >= {"demonstration_sample_size", "demonstrated_reliability", "demonstration_test_multiple",
                      "demonstration_pass_probability", "mtbf_test_time", "mtbf_pass_probability",
                      "demonstration_plan", "mtbf_demonstration_plan"}


def test_the_calculator_runs_on_surpyval_by_default():
    assert st._demo_engine() is demo_engine
    plan = demonstration_test(reliability=0.95, confidence=0.95)
    assert plan["units"] == tp.demonstration_sample_size(0.95, alpha_ci=0.05) == 59


# ---- failure-terminated MTBF tests ------------------------------------------------

def test_failure_terminated_matches_surpyval():
    out = demonstration_test(method="mtbf", mtbf=1000, confidence=0.9, failures=2, failure_terminated=True,
                             unit="hours")
    assert out["failure_terminated"] is True
    assert out["total_test_time"] == pytest.approx(tp.mtbf_test_time(1000, 2, alpha_ci=0.1,
                                                                      failure_terminated=True), rel=1e-12)
    # Shorter than the time-terminated test, which allows for one more failure's worth of time.
    timed = demonstration_test(method="mtbf", mtbf=1000, confidence=0.9, failures=2)
    assert out["total_test_time"] < timed["total_test_time"]
    assert "failure_terminated" not in timed
    assert out["summary"].startswith("Run until failure 2")
    assert out["tradeoff"]["failures"][0] == 1  # no column for zero failures
    assert out["consumer_risk"] == pytest.approx(0.1, abs=1e-9)


@pytest.mark.parametrize("kwargs, message", [
    (dict(failures=0), "at least 1 failure"),
    (dict(failures=1, design_mtbf=2000, producer_risk=0.2), "time-terminated"),
])
def test_failure_terminated_refusals(kwargs, message):
    with pytest.raises(StrategyError, match=message):
        demonstration_test(method="mtbf", mtbf=1000, failure_terminated=True, **kwargs)


def test_failure_terminated_is_only_for_mtbf_tests():
    with pytest.raises(StrategyError, match="MTBF test"):
        demonstration_test(reliability=0.9, failure_terminated=True)


def test_rest_endpoints_take_failure_terminated(client):  # noqa: F811
    res = client.post("/api/strategy/demonstration-test",
                      json={"method": "mtbf", "mtbf": 1000, "failures": 1, "failure_terminated": True})
    assert res.status_code == 200, res.text
    assert res.json()["failure_terminated"] is True
    # The default response is the same as before: no new key.
    res = client.post("/api/strategy/demonstration-test", json={"method": "mtbf", "mtbf": 1000, "failures": 1})
    assert "failure_terminated" not in res.json()


@pytest.mark.parametrize("body", [
    {"reliability": 0.95, "confidence": 0.95, "mission_time": 1000, "test_multiple": 2, "shape": 2,
     "unit": "hours", "design_reliability": 0.99},
    {"reliability": 0.9, "confidence": 0.9, "design_reliability": 0.98, "producer_risk": 0.2},
    {"b_life": 10, "mission_time": 800, "shape": 2.2, "shape_interval": [1.6, 3.0], "units": 20},
    {"method": "mtbf", "mtbf": 5000, "confidence": 0.9, "failures": 1, "unit": "hours", "units": 4},
    {"method": "mtbf", "mtbf": 5000, "confidence": 0.9, "design_mtbf": 12000, "producer_risk": 0.1},
])
def test_public_rest_response_is_unchanged(client, monkeypatch, body):  # noqa: F811
    """/api/v1/strategy/demonstration-test answers byte for byte as it did on
    RePyability."""
    raw = client.post("/api/tokens", json={"name": "test"}).json()["token"]
    auth = {"Authorization": f"Bearer {raw}"}
    answers = []
    for engine in (old_engine, demo_engine):
        monkeypatch.setattr(st, "_demo_engine", lambda engine=engine: engine)
        res = client.post("/api/v1/strategy/demonstration-test", headers=auth, json=body)
        assert res.status_code == 200, res.text
        answers.append(res.content)
    assert answers[0] == answers[1]
