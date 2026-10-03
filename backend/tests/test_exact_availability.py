"""Exact availability over time (#154) and from the current state (#155).

RePyability 0.11 computes A(t), the mission availability and the window's
expected failures, outages, downtime and cost with no simulation, wherever
``analysis_routes()`` has an exact or numerical route. Every user gets them;
the simulation stays paid. These tests check the figures against the
simulation, the routes fallback, the cache and the size cap, the current
state, and that "Download as Python" makes the same calls.
"""

import copy
import math

import matplotlib

matplotlib.use("Agg")

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from backend.services import rbd_analysis as ra  # noqa: E402
from backend.services import rbd_export, samples  # noqa: E402
from backend.services import rbds as rbds_service  # noqa: E402
from backend.services.rbd_analysis import AnalysisError  # noqa: E402
from backend.tests.test_availability_paid import FREE, PRO, _analyze, _save, client  # noqa: E402,F401
from backend.tests.test_public_rbd_links import _rbd_graph  # noqa: E402
from backend.tests.test_rbd_costs import _exp, _ln, _node, _w  # noqa: E402
from backend.tests.test_rbd_export import WHEN, _run  # noqa: E402


def _sample_graph():
    s = next(s for s in samples.SAMPLE_RBDS if s["id"] == "sample-rbd-instrument-air-availability")
    return copy.deepcopy(s["graph"])


def _voting_graph():
    """2-of-3 pumps (wear-out lives, lognormal repairs, priced) in series with
    a controller, lost production priced too: a voting gate, costs and
    non-exponential lives together."""
    io = [{"id": "input", "type": "input", "position": {"x": 0, "y": 0}, "data": {"label": "Input"}},
          {"id": "output", "type": "output", "position": {"x": 900, "y": 0}, "data": {"label": "Output"}}]
    pumps = [_node(p, model=_w(900 + 50 * i, 1.8), repair=_ln(2.5, 0.6), costs={"repair": 400})
             for i, p in enumerate(("pa", "pb", "pc"))]
    ctrl = _node("ctrl", model=_exp(2e-4), repair=_ln(1.5, 0.4), costs={"repair": 900})
    vote = {"id": "vote", "type": "knode", "position": {"x": 0, "y": 0}, "data": {"label": "2oo3", "n": 2, "k": 3}}
    edges = [("input", p) for p in ("pa", "pb", "pc")] + [(p, "vote") for p in ("pa", "pb", "pc")]
    edges += [("vote", "ctrl"), ("ctrl", "output")]
    return {
        "repairable": True, "unit": "hours", "nodes": [*io, *pumps, ctrl, vote],
        "edges": [{"id": f"e{i}", "source": a, "target": b} for i, (a, b) in enumerate(edges)],
        "costs": {"downtime_rate": 150},
    }


def _simulate(graph, horizon, n=2000, state=None):
    rbd, _, gates, working, broken = ra._build_repairable_rbd(graph)
    extra = {"state": ra._node_states(state)} if state else {}
    return rbd.availability(t_simulation=horizon, mc_samples=n, method="c", seed=1, antithetic=True,
                            working_nodes=working | gates, broken_nodes=broken, **extra)


def _poisson_close(simulated, exact, n):
    """A simulated mean count within 4 standard errors of the exact one
    (counts vary at least as much as Poisson ones: generous, never flaky)."""
    return abs(simulated - exact) <= 4 * math.sqrt(max(exact, 1e-6) / n) + 1e-9


# ---------------------------------------------------------------------------
# Exact against the simulation
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("which, horizon", [("sample", None), ("sample", 2000.0), ("voting", 3000.0)])
def test_exact_figures_agree_with_the_simulation(which, horizon):
    graph = _sample_graph() if which == "sample" else _voting_graph()
    exact = ra.exact_availability(graph, horizon=horizon)
    assert exact["status"] == "ok" and exact["from"] == "new"
    window = exact["window"]
    res = _simulate(graph, window)
    ci = res.mean_availability_interval(0.99)
    assert ci.lower <= exact["mission_availability"] <= ci.upper
    n = res.n_simulations
    assert _poisson_close(res.system_failures / n, exact["expected_failures"], n)
    assert exact["downtime"] == pytest.approx(window * (1 - exact["mission_availability"]), rel=1e-9)
    # A(t) starts at 1 (every block new) and is a probability throughout.
    a = np.array(exact["curve"]["availability"], dtype=float)
    assert exact["availability_start"] == pytest.approx(1.0) and np.all((a >= 0) & (a <= 1 + 1e-12))
    assert len(exact["curve"]["t"]) >= ra.EXACT_POINTS and exact["curve"]["t"][-1] == pytest.approx(window)
    # Each figure says how it was found.
    assert exact["method"]["curve"] == "numerical" and exact["method"]["steady_state"] == "exact"
    assert exact["routes"]["availability"]["route"] == "simulated"
    assert {r["id"] for r in exact["per_node"]} == {n["id"] for n in graph["nodes"] if n["type"] == "component"}
    if which == "voting":
        assert exact["cost"]["mean"] > 0 and exact["method"]["cost"] in ("exact", "numerical")
        cost = res.cost.mean_interval(0.99)
        assert cost.lower <= exact["cost"]["mean"] <= cost.upper
    else:
        assert exact["cost"] is None


def test_the_window_settles_at_the_long_run_value():
    graph = _sample_graph()
    exact = ra.exact_availability(graph)  # the default horizon reaches steady state
    steady = ra.analyze_availability(graph, simulate=False)["steady_state_availability"]
    assert exact["availability_end"] == pytest.approx(steady, abs=1e-6)


# ---------------------------------------------------------------------------
# Routes: simulation-only diagrams fall back
# ---------------------------------------------------------------------------
def _tested_graph():
    """Proof tests that take time: RePyability has no exact route."""
    graph = _rbd_graph(repairable=True)
    graph["nodes"][2]["data"]["inspection"] = {"interval": 500, "duration": 2}
    return graph


def test_simulation_only_diagram_says_so_and_computes_nothing():
    exact = ra.exact_availability(_tested_graph(), horizon=1000)
    assert exact["status"] == "simulation_only"
    assert "only the simulation gives it" in exact["message"]
    assert exact["routes"]["point_availability"]["route"] == "refused"
    assert "Controller" in exact["routes"]["point_availability"]["blocks"]
    assert "curve" not in exact and "mission_availability" not in exact


def test_validate_says_how_the_availability_is_computed():
    routes = ra.validate_graph(_rbd_graph(repairable=True))["availability_routes"]
    assert routes["long_run"]["route"] == "exact" and routes["over_time"]["route"] == "numerical"
    assert routes["simulation"]["route"] == "simulated"
    routes = ra.validate_graph(_tested_graph())["availability_routes"]
    assert routes["over_time"]["route"] == "refused" and routes["over_time"]["reason"]
    assert ra.validate_graph(_rbd_graph(repairable=False)).get("availability_routes") is None


def test_simulation_only_diagram_for_a_pro_user_simulates_as_before(client):
    client.act_as(PRO)
    r = _analyze(client, _tested_graph())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["has_simulation"] is True and body["simulation_status"]["state"] == "done"
    assert body["exact"]["status"] == "simulation_only" and body["precision"]
    assert client.sims["n"] == 1


# ---------------------------------------------------------------------------
# The API: free users, the cache, the size cap
# ---------------------------------------------------------------------------
def test_free_user_gets_the_exact_figures_and_routes(client):
    client.act_as(FREE)
    graph = _rbd_graph(repairable=True)
    body = _analyze(client, graph).json()
    exact = body["exact"]
    assert exact["status"] == "ok" and exact["cached"] is False
    assert exact["mission_availability"] > 0.99 and exact["expected_failures"] > 0
    assert body["steady_state_availability"] == pytest.approx(exact["availability_end"], abs=1e-5)
    assert body["importance"] and body["has_simulation"] is False and body["can_simulate"] is False
    assert set(exact["method"]) >= {"curve", "mission_availability", "expected_failures", "downtime"}
    assert client.sims["n"] == 0


def test_exact_results_are_cached_by_graph_and_window(client, monkeypatch):
    calls = {"n": 0}
    real = ra.exact_availability

    def spy(*a, **k):
        calls["n"] += 1
        return real(*a, **k)

    monkeypatch.setattr(ra, "exact_availability", spy)
    client.act_as(FREE)
    graph = _rbd_graph(repairable=True)
    rbd_id = _save(client, graph)

    first = _analyze(client, graph, rbd_id).json()
    assert first["exact"]["cached"] is False and calls["n"] == 1
    entry = client.db.rbds.find_one({"_id": rbd_id})["exact_cache"]
    assert list(entry) == [rbds_service.exact_cache_key(graph, None, None)]
    again = _analyze(client, graph, rbd_id).json()
    assert again["exact"]["cached"] is True and calls["n"] == 1
    assert again["exact"]["mission_availability"] == first["exact"]["mission_availability"]
    # The document's copy survives a restart (the process cache emptied).
    rbds_service.clear_exact_lru()
    assert _analyze(client, graph, rbd_id).json()["exact"]["cached"] is True and calls["n"] == 1

    # Layout doesn't matter; a parameter or the window does.
    moved = copy.deepcopy(graph)
    moved["nodes"][3]["position"] = {"x": 5, "y": 5}
    assert _analyze(client, moved, rbd_id).json()["exact"]["cached"] is True
    r = client.post("/api/rbds/analyze", json={"graph": graph, "rbd_id": rbd_id, "t_max": 500})
    assert r.json()["exact"]["window"] == 500 and calls["n"] == 2
    changed = copy.deepcopy(graph)
    changed["nodes"][2]["data"]["model"]["params"][0]["value"] = 2500
    assert _analyze(client, changed, rbd_id).json()["exact"]["cached"] is False and calls["n"] == 3
    # A what-if (unsaved) graph is kept in the process cache, not on the document.
    assert _analyze(client, changed, rbd_id).json()["exact"]["cached"] is True and calls["n"] == 3
    keys = set(client.db.rbds.find_one({"_id": rbd_id})["exact_cache"])
    assert rbds_service.exact_cache_key(changed, None, None) not in keys
    assert "availability_cache" not in client.db.rbds.find_one({"_id": rbd_id})


def test_large_diagrams_compute_on_request(client, monkeypatch):
    calls = {"n": 0}
    real = ra.exact_availability

    def spy(*a, **k):
        calls["n"] += 1
        return real(*a, **k)

    monkeypatch.setattr(ra, "exact_availability", spy)
    monkeypatch.setattr(ra, "EXACT_AUTO_MAX_BLOCKS", 2)
    client.act_as(FREE)
    graph = _rbd_graph(repairable=True)  # 3 blocks

    body = _analyze(client, graph).json()
    assert body["exact"]["status"] == "on_request" and "3 blocks" in body["exact"]["message"]
    assert body["steady_state_availability"] > 0.9  # the long-run figures still come
    assert calls["n"] == 0
    r = client.post("/api/rbds/analyze", json={"graph": graph, "exact": True})
    assert r.json()["exact"]["status"] == "ok" and calls["n"] == 1

    monkeypatch.setattr(ra, "EXACT_MAX_BLOCKS", 2)
    rbds_service.clear_exact_lru()
    r = client.post("/api/rbds/analyze", json={"graph": graph, "exact": True})
    assert r.json()["exact"]["status"] == "too_large" and "Download it as Python" in r.json()["exact"]["message"]
    assert calls["n"] == 1


def test_count_blocks_leaves_out_gates_and_io():
    assert ra.count_blocks(_voting_graph()) == 4


def test_public_link_serves_the_saved_exact_figures_without_computing(client, monkeypatch):
    client.act_as(PRO)
    graph = _rbd_graph(repairable=True)
    rbd_id = _save(client, graph)
    token = client.post("/api/public-links", json={"collection": "rbds", "artifact_id": rbd_id}).json()["token"]
    client.act_as(None)
    assert client.get(f"/api/public/{token}").json()["artifact"]["analysis"] is None

    client.act_as(PRO)
    _analyze(client, graph, rbd_id, force=False)  # computes the exact figures and the simulation

    def boom(*a, **k):
        raise AssertionError("public links never compute")

    monkeypatch.setattr(ra, "exact_availability", boom)
    client.act_as(None)
    a = client.get(f"/api/public/{token}").json()["artifact"]["analysis"]
    assert a["has_simulation"] is True and a["exact"]["status"] == "ok"
    # Without a saved simulation the exact figures stand alone.
    client.db.rbds.update_one({"_id": rbd_id}, {"$unset": {"availability_cache": 1}})
    a = client.get(f"/api/public/{token}").json()["artifact"]["analysis"]
    assert a["has_simulation"] is False and a["exact"]["mission_availability"] > 0.9


# ---------------------------------------------------------------------------
# The current state (#155)
# ---------------------------------------------------------------------------
def test_a_block_down_now_lowers_early_availability_and_recovers():
    graph = _rbd_graph(repairable=True)  # Controller in series with Pump A || Pump B
    new = ra.exact_availability(graph, horizon=200)
    down = ra.exact_availability(graph, horizon=200, state={"ctrl": {"down": True, "since": 0.0}})
    assert down["from"] == "now" and down["current_state"] == {"ctrl": {"down": True, "since": 0.0}}
    assert down["availability_start"] == 0.0 and new["availability_start"] == pytest.approx(1.0)
    t = np.array(down["curve"]["t"])
    a_down = np.array(down["curve"]["availability"])
    a_new = np.array(new["curve"]["availability"])
    early = (t > 0) & (t <= 5)
    assert np.all(a_down[early] < a_new[early])
    # It recovers within a few repair times (lognormal mu=2: ~8 h) to the same level.
    assert a_down[np.searchsorted(t, 50)] > a_down[np.searchsorted(t, 2)]
    assert down["availability_end"] == pytest.approx(new["availability_end"], abs=1e-4)
    assert down["mission_availability"] < new["mission_availability"]
    assert down["downtime"] > new["downtime"]
    assert down["availability_min"] == 0.0 and down["availability_min_at"] == 0.0

    # Further into its repair, it's back sooner.
    later = ra.exact_availability(graph, horizon=200, state={"ctrl": {"down": True, "since": 6.0}})
    assert later["mission_availability"] > down["mission_availability"]
    # A redundant pump down costs less than the controller down.
    pump = ra.exact_availability(graph, horizon=200, state={"pumpA": {"down": True, "since": 0.0}})
    assert down["mission_availability"] < pump["mission_availability"] < new["mission_availability"]
    # An old wear-out controller (Weibull shape 1.6) fails more in the window.
    aged = ra.exact_availability(graph, horizon=200, state={"ctrl": {"age": 3000.0}})
    assert aged["expected_failures"] > new["expected_failures"]

    # The simulation from the same state agrees.
    res = _simulate(graph, 200.0, state={"ctrl": {"down": True, "since": 0.0}})
    ci = res.mean_availability_interval(0.99)
    assert ci.lower <= down["mission_availability"] <= ci.upper


@pytest.mark.parametrize("raw, message", [
    ("down", "must be an object"),
    ({"nope": {"age": 1}}, "isn't a component block"),
    ({"input": {"age": 1}}, "isn't a component block"),
    ({"ctrl": 5}, "give"),
    ({"ctrl": {"age": -1}}, "≥ 0"),
    ({"ctrl": {"age": float("inf")}}, "finite"),
    ({"ctrl": {"age": "old"}}, "must be a number"),
    ({"ctrl": {"down": "yes"}}, "true or false"),
    ({"ctrl": {"since": 2}}, "set down: true"),
    ({"ctrl": {"down": True, "age": 5}}, "has no age"),
    ({"ctrl": {"down": True, "when": 2}}, "unknown current-state field"),
])
def test_current_state_is_validated(raw, message):
    with pytest.raises(AnalysisError) as err:
        ra.parse_current_state(_rbd_graph(repairable=True), raw)
    assert message in str(err.value)


def test_current_state_is_canonical():
    graph = _rbd_graph(repairable=True)
    assert ra.parse_current_state(graph, None) is None and ra.parse_current_state(graph, {}) is None
    assert ra.parse_current_state(graph, {"ctrl": {"age": 0}}) is None  # new
    assert ra.parse_current_state(graph, {"pumpB": {"age": 5}, "ctrl": {"down": True}}) == {
        "ctrl": {"down": True, "since": 0.0}, "pumpB": {"age": 5.0}}
    pinned = _rbd_graph(repairable=True)
    pinned["nodes"][3]["data"]["state"] = "failed"
    with pytest.raises(AnalysisError, match="pinned failed"):
        ra.parse_current_state(pinned, {"pumpA": {"age": 1}})


def test_a_state_the_block_cant_be_in_is_a_clear_error(client):
    """A repair that can't still be running (RePyability's own check), with
    the block's label in the message."""
    client.act_as(FREE)
    graph = _rbd_graph(repairable=True)
    r = client.post("/api/rbds/analyze", json={
        "graph": graph, "current_state": {"ctrl": {"down": True, "since": 1e9}}})
    assert r.status_code == 422, r.text
    assert "Controller" in r.json()["detail"] and "can't be used" in r.json()["detail"]
    r = client.post("/api/rbds/analyze", json={"graph": graph, "current_state": {"ctrl": {"age": -2}}})
    assert r.status_code == 422 and "≥ 0" in r.json()["detail"]


def test_current_state_results_are_kept_apart_from_the_saved_ones(client):
    client.act_as(PRO)
    graph = _rbd_graph(repairable=True)
    rbd_id = _save(client, graph)
    saved = _analyze(client, graph, rbd_id).json()  # simulates and saves, from new
    assert saved["simulation_status"]["state"] == "done" and client.sims["n"] == 1
    doc = client.db.rbds.find_one({"_id": rbd_id})
    sim_entry, exact_entries = doc["availability_cache"], doc["exact_cache"]

    state = {"ctrl": {"down": True, "since": 1.0}}
    body = client.post("/api/rbds/analyze", json={
        "graph": graph, "rbd_id": rbd_id, "current_state": state, "t_max": 100, "simulate": False}).json()
    # The saved simulation is from new: never served for a state.
    assert body["has_simulation"] is False and body["current_state"] == state
    assert body["exact"]["from"] == "now" and body["exact"]["window"] == 100
    # Simulating from the state runs, but saves nothing.
    body = client.post("/api/rbds/analyze", json={
        "graph": graph, "rbd_id": rbd_id, "current_state": state, "t_max": 100, "simulate": True}).json()
    assert body["has_simulation"] is True and body["current_state"] == state and client.sims["n"] == 2
    assert body["t_simulation"] == 100
    doc = client.db.rbds.find_one({"_id": rbd_id})
    assert doc["availability_cache"] == sim_entry and doc["exact_cache"] == exact_entries
    # From new again: the saved result.
    again = _analyze(client, graph, rbd_id).json()
    assert again["cached"] is True and again["current_state"] is None and client.sims["n"] == 2


# ---------------------------------------------------------------------------
# Download as Python makes the same exact calls
# ---------------------------------------------------------------------------
def test_export_script_computes_the_same_exact_figures(tmp_path):
    graph = _voting_graph()
    code = rbd_export.to_python(graph, "Pumps", exported_at=WHEN)
    for call in ("rbd.point_availability(", "rbd.expected_events(", "rbd.expected_cost(", "STATE = {}"):
        assert call in code
    results, proc = _run(code, tmp_path, n_sims="40")
    app = ra.exact_availability(graph)
    got = results["exact"]
    assert got["from"] == "new" and got["window"] == pytest.approx(app["window"], rel=1e-12)
    for key in ("mission_availability", "expected_failures", "expected_outages", "downtime"):
        assert got[key] == pytest.approx(app[key], rel=1e-9), key
    assert got["cost"] == pytest.approx(app["cost"]["mean"], rel=1e-9)
    assert got["times"] == pytest.approx(app["curve"]["t"], rel=1e-12)
    assert got["availability"] == pytest.approx(app["curve"]["availability"], rel=1e-9, abs=1e-12)
    assert "Exact over" in proc.stdout

    # STATE starts it from now, as the app's "As of now".
    state = {"ctrl": {"down": True, "since": 1.0}}
    code = code.replace("STATE = {}", f"STATE = {state!r}")
    results, _ = _run(code, tmp_path, name="now.py", n_sims="40")
    app = ra.exact_availability(graph, state=state)
    assert results["exact"]["from"] == "now"
    assert results["exact"]["mission_availability"] == pytest.approx(app["mission_availability"], rel=1e-9)


def test_export_script_of_a_simulation_only_diagram_still_runs(tmp_path):
    code = rbd_export.to_python(_tested_graph(), "Tested", exported_at=WHEN)
    results, proc = _run(code, tmp_path, n_sims="20")
    assert results["exact"] is None and "No exact availability over time" in proc.stdout
