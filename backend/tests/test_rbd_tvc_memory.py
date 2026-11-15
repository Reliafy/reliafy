"""A block along a fine covariate schedule stays within memory (#52 follow-up).

An hourly-stepped flow repeating every 720 h, analysed with a survived-to age,
once laid out a (steps x query times) table of ~76 million cells and took a
2 GiB instance down. The block now sums the cumulative hazard step by step
(proportional hazards and odds) or evaluates in chunks (other models), and a
schedule too fine for the window is refused in plain words."""

import tracemalloc

import numpy as np
import pandas as pd
import pytest
import surpyval as sp

from backend import fitting
from backend.services import rbd_tvc
from backend.services.rbd_analysis import AnalysisError, analyze

VARYING = ("80 + 30 * sin(2 * pi * (floor(t % 720) % 24) / 24) + "
           "10 * sin(2 * pi * floor((t % 720) / 24) / 30)")
FIELDS = [{"name": "flow_pct", "type": "number", "default": 80.0, "min": 40.0, "max": 120.0,
           "unit": "% of rated flow"}]


@pytest.fixture(scope="module")
def entry():
    """A Weibull PH model of pump life on flow (simulated: Weibull 9,000 h,
    shape 2.2, +2 % risk per 1 % of rated flow), as the analysis resolves a
    saved model."""
    rng = np.random.default_rng(7)
    flow = np.repeat(np.arange(40, 121, 10), 45)[:400].astype(float)
    life = 9000 * rng.weibull(2.2, flow.size) * np.exp(-0.02 * (flow - 80) / 2.2)
    stop = rng.uniform(2000, 15000, flow.size)
    df = pd.DataFrame({"pump_id": [f"P{i:03d}" for i in range(flow.size)], "flow_pct": flow,
                       "hours": np.minimum(life, stop).round(1), "status": (life > stop).astype(int)})
    r = fitting.fit("weibull_ph", df, {"x": "hours", "c": "status"}, ["flow_pct"], unit="hours",
                    covariate_units={"flow_pct": "% of rated flow"})
    return fitting._MODEL_STORE[r["functions"]["model_id"]]


def _graph(expression):
    data = {"label": "Pump", "model": {"kind": "regression", "modelId": "M", "covariates": FIELDS},
            "covariate_schedules": {"flow_pct": {"expression": expression}}}
    return {"unit": "Hours", "nodes": [
        {"id": "input", "type": "input", "data": {}},
        {"id": "pump", "type": "component", "data": data},
        {"id": "output", "type": "output", "data": {}}],
        "edges": [{"source": "input", "target": "pump"}, {"source": "pump", "target": "output"}]}


def _direct(entry, expression):
    """The schedule as SurPyval's cyclic StepSchedule, built by hand."""
    plan = rbd_tvc.Plan(entry["model"], FIELDS, {"flow_pct": {"expression": expression}})
    return plan.schedule(1.0)


def _peak(fn):
    tracemalloc.start()
    try:
        out = fn()
        return out, tracemalloc.get_traced_memory()[1] / 2 ** 20
    finally:
        tracemalloc.stop()


@pytest.mark.parametrize("age", [None, 1000.0, 5000.0, 20000.0])
def test_varying_duty_conditional_analysis_stays_small_and_exact(entry, age):
    schedule = _direct(entry, VARYING)
    model = entry["model"]
    out, peak = _peak(lambda: analyze(_graph(VARYING), resolve_model=lambda _: entry, conditional_age=age,
                                      at_times=[2000.0, 8000.0]))
    assert peak < 300, f"peak {peak:.0f} MiB"
    s = age or 0.0
    t = np.array([2000.0, 8000.0])
    want = np.asarray(model.sf_tvc(s + t, schedule)) / (float(model.sf_tvc(np.array([s]), schedule)[0]) if s else 1)
    assert out["at"]["sf"] == pytest.approx(want, rel=1e-9)
    # The MTTF (mean residual life past an age) is given for a repeating schedule.
    assert out["mttf"] is not None and out["mttf"] > 0


def test_chunked_fallback_matches_and_stays_small(entry, monkeypatch):
    """A model the running total doesn't apply to goes through SurPyval's
    own sum, a chunk of query times at a time."""
    graph = _graph(VARYING)
    fast = analyze(graph, resolve_model=lambda _: entry, conditional_age=1000.0, at_times=[2000.0])
    monkeypatch.setattr(rbd_tvc, "_cumulative_applies", lambda *_: False)
    out, peak = _peak(lambda: analyze(graph, resolve_model=lambda _: entry, conditional_age=1000.0,
                                      at_times=[2000.0]))
    assert peak < 300, f"peak {peak:.0f} MiB"
    assert out["at"]["sf"] == pytest.approx(fast["at"]["sf"], rel=1e-9)
    # SurPyval's own sum is held to fewer steps, so the MTTF's long window
    # may be refused there: then it says why.
    if out["mttf"] is None:
        assert any("The MTTF isn't given" in w and "too fine" in w for w in out.get("warnings", []))
    else:
        assert out["mttf"] == pytest.approx(fast["mttf"], rel=1e-6)


def test_node_matches_surpyval_on_both_paths(entry, monkeypatch):
    x = np.array([0.0, 0.5, 23.9, 24.0, 719.99, 720.0, 1e4, 3.7e4, np.inf, np.nan])
    schedule = _direct(entry, VARYING)
    want_sf = np.asarray(entry["model"].sf_tvc(x[np.isfinite(x)], schedule))
    node = rbd_tvc.build_node(entry, {"flow_pct": {"expression": VARYING}}, None, "Pump")
    assert node._cumulative
    got = np.asarray(node.sf(x))
    assert got[:-2] == pytest.approx(want_sf, rel=1e-10)
    assert got[-2] == 0.0 and np.isnan(got[-1])
    assert np.asarray(node.ff(x[:-2])) == pytest.approx(1 - want_sf, rel=1e-9, abs=1e-15)
    monkeypatch.setattr(rbd_tvc, "_cumulative_applies", lambda *_: False)
    slow = rbd_tvc.build_node(entry, {"flow_pct": {"expression": VARYING}}, None, "Pump")
    assert not slow._cumulative
    near = x[:-3]  # SurPyval's own sum is held to fewer steps
    assert np.asarray(slow.sf(near)) == pytest.approx(want_sf[:-1], rel=1e-10)


def test_proportional_odds_uses_the_running_total_exactly():
    rng = np.random.default_rng(3)
    Z = rng.uniform(40, 120, (300, 1))
    x = 9000 * rng.weibull(2.2, 300) * np.exp(-0.01 * (Z[:, 0] - 80))
    model = sp.WeibullPO.fit(x, Z)
    schedule = sp.StepSchedule.cyclic([0.0, 8.0, 16.0], [[100.0], [60.0], [40.0]], 24.0)
    assert rbd_tvc._cumulative_applies(model, schedule)
    t = np.array([1.0, 30.0, 5000.0, 20000.0])
    table = (20000.0, *rbd_tvc._cumulative_table(model, schedule, 20000.0))
    assert rbd_tvc._cumulative_H(model, table, t) == pytest.approx(model.Hf_tvc(t, schedule), rel=1e-10)


def test_a_schedule_too_fine_for_the_window_is_refused_in_plain_words(entry, monkeypatch):
    monkeypatch.setattr(rbd_tvc, "MAX_CUMULATIVE_SEGMENTS", 5000)
    with pytest.raises(AnalysisError, match="too fine for this calculation over"):
        analyze(_graph(VARYING), resolve_model=lambda _: entry, conditional_age=20000.0, at_times=[2000.0])
