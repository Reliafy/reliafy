"""As of now: the time to the next failure and its cause (#220), and the mean
residual life (#221), with RePyability 0.12.

A repairable diagram's simulation from the blocks' states now
(``simulate_timelines(state=...)``) gives each history's next system failure
and the block that caused it; their mean is the mean residual life, checked
here against closed forms and RePyability's own non-repairable
``mean_residual_life``. A non-repairable diagram's mean remaining life as of
now is RePyability's ``mean_residual_life(state)``, exact. "Download as
Python" runs the same code and gives the same numbers.
"""

import json

import matplotlib

matplotlib.use("Agg")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
import surpyval as surv  # noqa: E402
from repyability import NodeState, NonRepairableRBD  # noqa: E402

from backend.services import rbd_analysis as ra  # noqa: E402
from backend.services import rbd_export  # noqa: E402
from backend.services import rbd_next_failure as nf  # noqa: E402
from backend.tests.test_exact_availability import _voting_graph  # noqa: E402
from backend.tests.test_mcp_plans import FREE, PRO, _call, _repairable, env  # noqa: E402,F401
from backend.tests.test_mcp import A, GRAPH, _ok, env as mcp_env  # noqa: E402,F401
from backend.tests.test_rbd_as_of_now import _pumps, _repy  # noqa: E402
from backend.tests.test_rbd_costs import _exp, _node, _series, _w  # noqa: E402
from backend.tests.test_rbd_export import WHEN, _run  # noqa: E402

W = surv.Weibull.from_params


def _build(graph):
    rbd, labels, gates, working, broken = ra._build_repairable_rbd(graph)
    return rbd, labels, {"working_nodes": working | gates, "broken_nodes": broken}


def _next(graph, state, window, n=2000):
    rbd, labels, overrides = _build(graph)
    return nf.next_failure(rbd, labels, overrides, ra._node_states(state), window, budget=None, max_n=n)


def _close(value, expected, out, k=4.0):
    """Within k standard errors of the simulated mean."""
    assert abs(value - expected) <= k * out["standard_error"], (value, expected, out["standard_error"])


# ---- the next failure, against closed forms and RePyability -------------------


def test_one_block_next_failure_is_its_residual_life():
    """One wear-out block running for 600 h: its next failure is its own
    residual life, whose mean RePyability gives exactly (non-repairable)."""
    graph = _series(_node("p", model=_w(1000, 2.5), repair=_exp(0.1)))
    out = _next(graph, {"p": {"age": 600.0}}, 3000.0)
    json.dumps(out)
    exact = NonRepairableRBD([("s", "p"), ("p", "t")], {"p": W([1000, 2.5])}).mean_residual_life(
        {"p": NodeState(age=600.0)})
    assert out["failed_share"] == 1.0 and out["mean_is_lower_bound"] is False
    _close(out["mean"], exact, out)
    assert out["mean_lower"] < exact < out["mean_upper"]
    assert out["causes"] == [{"id": "p", "label": "P", "count": 2000, "share": 1.0}]
    assert out["down_now"] == 0.0 and out["from"] == "now" and out["method"] == "simulated"
    # The new block lives longer.
    new = NonRepairableRBD([("s", "p"), ("p", "t")], {"p": W([1000, 2.5])}).mean()
    assert out["mean"] < 0.75 * new
    # The curve is P(failed by t), rising to 1.
    cdf = np.array(out["curve"]["cdf"])
    assert cdf[0] == 0.0 and 0.995 <= cdf[-1] <= 1.0 and np.all(np.diff(cdf) >= 0)
    p = out["percentiles"]
    assert p["p10"] < p["p50"] < p["p90"]


def test_series_of_exponentials_is_memoryless_and_shares_by_rate():
    """Exponential blocks in series: the next failure is exponential with the
    summed rate whatever their ages, and each block causes it in proportion
    to its rate."""
    graph = _series(_node("a", model=_exp(1e-3), repair=_exp(0.5)),
                    _node("b", model=_exp(3e-3), repair=_exp(0.5)))
    out = _next(graph, {"a": {"age": 5000.0}, "b": {"age": 10.0}}, 2000.0)
    _close(out["mean"], 250.0, out)
    shares = {c["id"]: c["share"] for c in out["causes"]}
    sd = np.sqrt(0.25 * 0.75 / 2000)
    assert shares["a"] == pytest.approx(0.25, abs=4 * sd) and shares["b"] == pytest.approx(0.75, abs=4 * sd)
    assert out["causes"][0]["id"] == "b"  # most likely first
    # The median of an exponential: ln 2 times its mean.
    assert out["percentiles"]["p50"] == pytest.approx(250.0 * np.log(2), rel=0.1)


def test_a_block_down_now_restores_before_the_next_failure():
    """A block down now: the system starts down, and its next failure comes
    after the repair (exponential, so what is left of it is its mean) and a
    fresh life."""
    graph = _series(_node("a", model=_exp(1e-2), repair=_exp(0.05)))
    out = _next(graph, {"a": {"down": True, "since": 3.0}}, 2000.0)
    assert out["down_now"] == 1.0
    _close(out["mean"], 20.0 + 100.0, out)


def test_the_histories_and_causes_are_repyabilitys():
    """The next failures are the timelines' first failures, and the cause is
    a block whose own history goes down at that instant (from new, in a
    series system, the block that fails first)."""
    graph = _voting_graph()
    graph["nodes"] = [n for n in graph["nodes"] if n["id"] != "vote"]
    graph["edges"] = [{"id": f"e{i}", "source": a, "target": b} for i, (a, b) in enumerate(
        [("input", "pa"), ("pa", "pb"), ("pb", "ctrl"), ("ctrl", "output")])]
    graph["nodes"] = [n for n in graph["nodes"] if n["id"] != "pc"]
    rbd, labels, overrides = _build(graph)
    state = ra._node_states({"pa": {"age": 800.0}, "pb": {"down": True, "since": 1.0}})
    runs, antithetic = nf.timelines_run(rbd, 4000.0, 400, {**overrides, "state": state})
    times, causes, up_now = nf.first_failures(runs)
    assert antithetic and np.array_equal(times, runs.system.first_failure)
    assert not up_now.any()  # pb is down now
    assert sum(c is not None for c in causes) == np.isfinite(times).sum() > 300
    for s, (t, cause) in enumerate(zip(times, causes)):
        if np.isfinite(t):
            own = runs.components[cause][s]
            assert t in own.changes and not own.state(t)
    # The same simulations the availability run makes from that state.
    res = rbd.availability(t_simulation=4000.0, mc_samples=400, seed=1, antithetic=True, method="c",
                           control_variate=False, conditional=False, state=state, **overrides)
    assert np.array_equal(res.uptimes, runs.system.uptime)

    # From new, all up: the block whose own history fails first.
    runs, _ = nf.timelines_run(rbd, 4000.0, 400, overrides)
    times, causes, _ = nf.first_failures(runs)
    first = {n: np.asarray(runs.components[n].first_failure) for n in ("pa", "pb", "ctrl")}
    for s, (t, cause) in enumerate(zip(times, causes)):
        if np.isfinite(t):
            assert first[cause][s] == t and all(first[n][s] >= t for n in first)


def test_the_window_grows_until_the_histories_have_failed(monkeypatch):
    """A redundant, quickly repaired pair rarely fails within the availability
    window: the window is lengthened until 99% of histories have; capped, the
    mean is of min(T, window) and said to be a lower bound."""
    unit = dict(model=_exp(1e-3), repair=_exp(0.01))
    a, b = _node("a", **unit), _node("b", **unit)
    graph = {"repairable": True, "unit": "hours", "nodes": [*_series()["nodes"], a, b],
             "edges": [{"id": f"e{i}", "source": s, "target": t} for i, (s, t) in enumerate(
                 [("input", "a"), ("input", "b"), ("a", "output"), ("b", "output")])]}
    out = _next(graph, {"a": {"age": 10.0}}, 5000.0, n=400)
    assert out["window"] > 5000.0 and out["failed_share"] >= 0.99
    # Two units, rate l, repair rate m: the mean time to both down is (3l + m) / (2 l^2).
    _close(out["mean"], (3e-3 + 0.01) / 2e-6, out)

    monkeypatch.setattr(nf, "NEXT_FAILURE_MAX_GROWTH", 1.0)
    capped = _next(graph, {"a": {"age": 10.0}}, 5000.0, n=400)
    assert capped["window"] == 5000.0 and capped["mean_is_lower_bound"] is True
    assert 0 < capped["failed_share"] < 0.9 and capped["mean"] < 5000.0
    assert capped["percentiles"]["p90"] is None


def test_availability_from_now_carries_the_next_failure():
    graph = _voting_graph()
    state = {"pa": {"down": True, "since": 1.0}, "pb": {"age": 1500.0}}
    res = ra.analyze_availability(graph, state=state, n_simulations=200)
    json.dumps(res)
    out = res["next_failure"]
    assert out["n_simulations"] == 200 and out["from"] == "now"
    assert {c["id"] for c in out["causes"]} <= {"pa", "pb", "pc", "ctrl"}
    assert sum(c["count"] for c in out["causes"]) == round(out["failed_share"] * 200)
    assert out["mean"] > 0
    # Not without the simulation, nor from new.
    assert "next_failure" not in ra.analyze_availability(graph, state=state, simulate=False)
    assert "next_failure" not in ra.analyze_availability(graph, n_simulations=20)


# ---- the mean residual life of a non-repairable diagram -----------------------


def test_non_repairable_mean_residual_life_is_repyabilitys():
    res = ra.analyze(_pumps(), current_state={"a": {"age": 50}, "b": {"failed": True}})
    nodes = {"a": NodeState(age=50), "b": NodeState(alive=False)}
    exact = _repy().mean_residual_life(nodes)
    assert res["mean_residual_life"] == {"value": pytest.approx(exact, rel=1e-12), "method": "exact"}
    assert res["mttf"] == pytest.approx(exact, rel=1e-12)
    # A pinned-failed block is a failed one; one pinned working takes the curve's area.
    graph = _pumps()
    b = next(n for n in graph["nodes"] if n["id"] == "b")
    b["data"]["state"] = "failed"
    pinned = ra.analyze(graph, current_state={"a": {"age": 50}})
    assert pinned["mean_residual_life"]["method"] == "exact"
    assert pinned["mean_residual_life"]["value"] == pytest.approx(exact, rel=1e-12)
    b["data"]["state"] = "working"
    held = ra.analyze(graph, current_state={"a": {"age": 50}})
    rbd = NonRepairableRBD([("s", "v"), ("v", "t")], {"v": W([500, 1.5])})
    assert held["mean_residual_life"]["method"] == "numerical"
    assert held["mean_residual_life"]["value"] == pytest.approx(rbd.mean(), rel=1e-3)
    # Failed now: none. From new: not given.
    failed = ra.analyze(_pumps(), current_state={"a": {"failed": True}, "b": {"failed": True}})
    assert "mean_residual_life" not in failed and failed["mttf"] is None
    assert "mean_residual_life" not in ra.analyze(_pumps())


# ---- MCP -------------------------------------------------------------------------


def test_mcp_next_failure_from_now(env):  # noqa: F811
    rid = _repairable(env, PRO, "Pumps")
    graph = env.db.rbds.find_one({"_id": rid})["graph"]
    ids = [n["id"] for n in graph["nodes"] if n["type"] == "component"]
    out = _ok(_call(env.oauth[PRO], "analyze_rbd", {
        "rbd_id": rid, "simulate": True, "current_state": {ids[0]: {"age": 1500.0}}}))
    nxt = out["next_failure"]
    assert nxt["method"] == "simulated" and nxt["n_simulations"] == 20
    assert len(nxt["p_failed_by"]) == 21 and nxt["p_failed_by"][0] == {"t": 0.0, "p": 0.0}
    assert all(set(c) == {"label", "count", "share"} for c in nxt["causes"])
    assert out["mean_residual_life"]["value"] == nxt["mean"] and out["mean_residual_life"]["method"] == "simulated"
    # From new, or without the simulation: none.
    plain = _ok(_call(env.oauth[PRO], "analyze_rbd", {"rbd_id": rid, "simulate": False,
                                                      "current_state": {ids[0]: {"age": 1500.0}}}))
    assert "next_failure" not in plain and "mean_residual_life" not in plain
    # Free: the exact figures, and the simulation's offer (no next failure).
    rid = _repairable(env, FREE, "Pumps")
    free = _ok(_call(env.oauth[FREE], "analyze_rbd", {"rbd_id": rid, "simulate": True,
                                                      "current_state": {ids[0]: {"age": 1500.0}}}))
    assert "next_failure" not in free and free["simulation"]["available"] is False


def test_mcp_non_repairable_mean_residual_life(mcp_env):  # noqa: F811
    rid = _ok(_call(mcp_env.token[A], "create_rbd", {"name": "Pump skid", "unit": "Hours", **GRAPH}))["id"]
    now = _ok(_call(mcp_env.token[A], "analyze_rbd", {
        "rbd_id": rid, "current_state": {"p1": {"failed": True}, "ctl": {"age": 400}}}))
    assert now["mean_residual_life"]["method"] == "exact"
    assert now["mean_residual_life"]["value"] == pytest.approx(now["mttf"], rel=1e-12)
    new = _ok(_call(mcp_env.token[A], "analyze_rbd", {"rbd_id": rid}))
    assert "mean_residual_life" not in new


# ---- Download as Python ----------------------------------------------------------


def test_export_script_gives_the_apps_next_failure(tmp_path):
    graph = _voting_graph()
    code = rbd_export.to_python(graph, "Pumps", exported_at=WHEN)
    assert "def next_failure_summary(" in code and "NEXT_FAILURE_TIME_BUDGET = None" in code
    results, _ = _run(code, tmp_path, n_sims="40")
    assert "next_failure" not in results  # from new: none

    state = {"pa": {"down": True, "since": 1.0}, "pb": {"age": 1500.0}}
    code = code.replace("STATE = {}", f"STATE = {state!r}")
    results, proc = _run(code, tmp_path, name="now.py", n_sims="40")
    got = results["next_failure"]
    app = _next(graph, state, results["t_simulation"], n=nf.NEXT_FAILURE_SIMS)
    for key in ("window", "n_simulations", "mean", "mean_lower", "mean_upper", "failed_share", "down_now"):
        assert got[key] == pytest.approx(app[key], rel=1e-12), key
    assert got["percentiles"] == app["percentiles"] and got["causes"] == app["causes"]
    assert "mean residual life" in proc.stdout
