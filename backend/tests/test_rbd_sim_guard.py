"""A mixture life repaired imperfectly can't run away (RePyability #295).

In RePyability 0.13 such a block simulates very slowly, and much faster
than linearly in the window (0.45 s for 100 replications over 2,000 h,
53 s over 15,000 h, over 9 minutes at 20,000 h), and Reliafy's time budgets
can't stop a batch once it starts. Before this guard, the reproduction
diagram at its default window (about 26,700 h) was still running after 60 s
with a 3 s budget. Now:

* the run is refused at once (checked in a subprocess with a strict timeout,
  so a regression fails here instead of hanging the suite), in process and
  on the calculation service's path;
* Validate says why, in plain words; a mixture with perfect repair, a
  single-mode life with Kijima repair, a pinned block and a reliability
  diagram are untouched;
* the runtime quote refuses it too, with the same reason;
* the app's analysis and MCP's create_rbd / edit_rbd refuse it.
"""

import subprocess
import sys
from pathlib import Path

import pytest

from backend.services import compute_core, rbd_sim_guard, runtime_quote
from backend.services import rbd_analysis as ra
from backend.services import rbd_graph
from backend.tests.test_availability_paid import PRO, client  # noqa: F401 - fixture
from backend.tests.test_mcp import A, _call, _err, _ok, env  # noqa: F401 - env is a fixture
from backend.tests.test_rbd_block_options import LN, MIX, W

KIJIMA = {"model": "kijima1", "q": 0.4}
MESSAGE = ("“A”: a two-failure-mode life with imperfect repair can't be simulated quickly yet; use one failure "
           "mode, or repair as good as new.")


def _graph(model=MIX, quality=KIJIMA, repairable=True, state=None):
    a = {"id": "a", "type": "component", "label": "A", "model": model, "repair": LN}
    if quality:
        a["repair_quality"] = quality
    b = {"id": "b", "type": "component", "label": "B", "model": W(3000, 2), "repair": LN}
    if not repairable:
        a.pop("repair"), b.pop("repair"), a.pop("repair_quality", None)
    graph = rbd_graph.normalize_graph({
        "nodes": [{"id": "input", "type": "input"}, a, b, {"id": "output", "type": "output"}],
        "edges": [{"source": s, "target": t} for s, t in [("input", "a"), ("a", "b"), ("b", "output")]],
        "unit": "Hours", "repairable": repairable})
    if state:  # pinned working or failed (the builder's what-if)
        graph["nodes"][1]["data"]["state"] = state
    return graph


_RUN = """
import json, sys, time, warnings
warnings.simplefilter("ignore")
from backend.services import rbd_analysis as ra
graph = json.loads(sys.argv[1])
t0 = time.perf_counter()
try:
    if sys.argv[2] == "quick":
        ra.analyze_availability(graph, time_budget_s=3.0)
    elif sys.argv[2] == "compute":
        from backend.services import compute_core
        compute_core.run_availability({"graph": graph, "options": {"time_budget_s": 3.0}})
    else:
        ra.analyze_availability(graph)
    print("RAN", time.perf_counter() - t0)
except ra.AnalysisError as exc:
    print("REFUSED", time.perf_counter() - t0, exc)
"""


@pytest.mark.parametrize("mode", ["quick", "full", "compute"])
def test_the_reproduction_is_refused_at_once_at_its_default_window(mode):
    import json

    graph = _graph()
    assert ra._availability_horizon(graph) > 20_000  # the window that ran for minutes
    root = Path(__file__).resolve().parents[2]
    out = subprocess.run([sys.executable, "-c", _RUN, json.dumps(graph), mode], cwd=root, capture_output=True,
                         text=True, timeout=60)
    line = out.stdout.strip().splitlines()[-1]
    assert line.startswith("REFUSED"), out.stdout + out.stderr
    assert float(line.split()[1]) < 5.0 and MESSAGE in line


def test_validate_says_why_and_leaves_the_rest_alone():
    check = ra.validate_graph(_graph())
    assert check["valid"] is False and MESSAGE in check["errors"]
    for fine in (_graph(quality=None),                     # a mixture, repaired as good as new
                 _graph(model=W(1000, 2.5)),               # one failure mode, Kijima repair
                 _graph(state="working"),                  # pinned: never simulated
                 _graph(repairable=False)):                # a reliability diagram
        assert rbd_sim_guard.slow_blocks(fine) == []
        assert not any("two-failure-mode" in e for e in ra.validate_graph(fine)["errors"])
    # Replacement at the N-th failure is imperfect repair too.
    assert rbd_sim_guard.slow_blocks(_graph(quality={"model": "kijima2", "q": 0.5, "replace_after": 3})) == ["A"]


def test_the_quote_refuses_it_with_the_reason():
    assert runtime_quote.features(_graph()) == {"available": False, "reason": MESSAGE}
    assert runtime_quote.quote_runtime(_graph())["available"] is False
    assert runtime_quote.features(_graph(quality=None))["available"] is True


def test_the_calculation_service_refuses_it():
    with pytest.raises(ra.AnalysisError, match="two-failure-mode"):
        compute_core.run_availability({"graph": _graph(), "options": {}})


def test_the_app_refuses_it(client):
    client.act_as(PRO)
    r = client.post("/api/rbds/analyze", json={"graph": _graph()})
    assert r.status_code == 422 and MESSAGE in r.json()["detail"]
    q = client.post("/api/rbds/quote", json={"graph": _graph()}).json()
    assert q == {"available": False, "reason": MESSAGE}
    v = client.post("/api/rbds/validate", json={"graph": _graph()}).json()
    assert MESSAGE in v["errors"]


def test_mcp_refuses_it(env):
    nodes = [{"id": "input", "type": "input"},
             {"id": "a", "type": "component", "label": "A", "model": MIX, "repair": LN, "repair_quality": KIJIMA},
             {"id": "output", "type": "output"}]
    edges = [{"source": "input", "target": "a"}, {"source": "a", "target": "output"}]
    msg = _err(_call(env.token[A], "create_rbd", {"name": "Worn mixture", "repairable": True,
                                                   "nodes": nodes, "edges": edges}))
    assert "two-failure-mode life with imperfect repair" in msg
    # A mixture repaired as good as new is fine; making its repair imperfect isn't.
    nodes[1].pop("repair_quality")
    rbd = _ok(_call(env.token[A], "create_rbd", {"name": "Mixture", "repairable": True, "nodes": nodes, "edges": edges}))
    msg = _err(_call(env.token[A], "edit_rbd", {"rbd_id": rbd["id"], "ops": [
        {"op": "update_node", "id": "a", "repair_quality": KIJIMA}]}))
    assert "two-failure-mode life with imperfect repair" in msg
