"""The MCP RBD tools on diagrams that use the R2 builder features.

Diagrams drawn in the app can carry node data the MCP node schema doesn't
describe yet (#141): repeated blocks (``repeat_of``), warm standby
(``dormancy``, ``standbyModel``, ``startProb``), and a repairable block's
costs, scheduled replacement and proof tests. ``get_rbd``, ``edit_rbd``,
``analyze_rbd``, ``clone_rbd`` and ``export_rbd_python`` must work on such
diagrams and carry those keys through untouched.
"""

import copy

from backend.tests.test_mcp import A, _call, _ok, env  # noqa: F401 - env is a fixture
from backend.tests.test_mcp_rbd_edit import _create, _doc, _edit, _node


def _exp(rate):
    return {"source": "params", "distribution": "Exponential", "distribution_id": "exponential",
            "params": [{"name": "failure_rate", "value": rate}]}


def _weibull(alpha, beta):
    return {"source": "params", "distribution": "Weibull", "distribution_id": "weibull",
            "params": [{"name": "alpha", "value": alpha}, {"name": "beta", "value": beta}]}


def _lognormal(mu, sigma):
    return {"source": "params", "distribution": "LogNormal", "distribution_id": "lognormal",
            "params": [{"name": "mu", "value": mu}, {"name": "sigma", "value": sigma}]}


def _n(nid, ntype, label, x=0, **data):
    return {"id": nid, "type": ntype, "position": {"x": x, "y": 0}, "data": {"label": label, **data}}


def _io():
    return [_n("input", "input", "Input"), _n("output", "output", "Output", 900)]


def _edges(*pairs):
    return [{"id": f"e-{s}-{t}", "source": s, "target": t} for s, t in pairs]


# Two pump trains share one power supply (drawn twice), behind a warm-standby
# controller pair.
NON_REPAIRABLE = {
    "unit": "hours",
    "nodes": [*_io(),
              _n("ctl", "standby", "Controllers", 100, model=_weibull(8000, 1.5), spares=1, dormancy=0.3,
                 standbyModel=_weibull(6000, 1.5), startProb=0.98),
              _n("a", "component", "Pump A", 300, model=_exp(2e-3)),
              _n("b", "component", "Pump B", 300, model=_exp(3e-3)),
              _n("psu", "component", "Power supply", 500, model=_exp(5e-4)),
              _n("psu2", "component", "Power supply", 500, repeat_of="psu")],
    "edges": _edges(("input", "ctl"), ("ctl", "a"), ("ctl", "b"), ("a", "psu"), ("b", "psu2"),
                    ("psu", "output"), ("psu2", "output")),
}

# A wearing pump on age replacement, a proof-tested shutdown valve, and a
# priced, instantly repaired filter, with lost production.
REPAIRABLE = {
    "unit": "hours",
    "repairable": True,
    "costs": {"downtime_rate": 500, "horizon": 87600},
    "nodes": [*_io(),
              _n("p", "component", "Pump", 200, model=_weibull(1000, 2.5), repair=_lognormal(3.0, 0.5),
                 costs={"replace": {"min": 4000, "max": 6000}, "acquisition": 20000, "downtime": 50},
                 preventive={"policy": "age", "interval": 580, "duration": 7, "cost": 1000}),
              _n("v", "component", "Shutdown valve", 400, model=_exp(1e-4), instant_repair=True,
                 inspection={"interval": 1000, "cost": 50}),
              _n("f", "component", "Filter", 600, model=_exp(5e-4), instant_repair=True,
                 costs={"replace": 300})],
    "edges": _edges(("input", "p"), ("p", "v"), ("v", "f"), ("f", "output")),
}

R2_KEYS = ("repeat_of", "dormancy", "standbyModel", "startProb", "costs", "preventive", "inspection",
           "instant_repair")


def _saved(env, graph, name="R2 diagram"):
    """A saved diagram of A's holding ``graph`` as the builder saved it."""
    rid = _create(env, name=name)["id"]
    env.db.rbds.update_one({"_id": rid}, {"$set": {"graph": copy.deepcopy(graph)}})
    return rid


def _r2_data(graph):
    return {n["id"]: {k: v for k, v in (n.get("data") or {}).items() if k in R2_KEYS}
            for n in graph["nodes"]}


def test_get_rbd_reports_the_r2_keys(env):
    rid = _saved(env, NON_REPAIRABLE)
    out = _ok(_call(env.token[A], "get_rbd", {"rbd_id": rid}))
    nodes = {n["id"]: n for n in out["graph"]["nodes"]}
    assert nodes["psu2"]["repeat_of"] == "psu"
    assert nodes["ctl"]["dormancy"] == 0.3 and nodes["ctl"]["startProb"] == 0.98
    assert nodes["ctl"]["standbyModel"]["distribution_id"] == "weibull"


def test_edit_rbd_keeps_r2_node_data_untouched(env):
    for graph in (NON_REPAIRABLE, REPAIRABLE):
        rid = _saved(env, graph)
        before = _r2_data(_doc(env, rid)["graph"])
        target = "a" if not graph.get("repairable") else "f"
        out = _ok(_edit(env, rid, {"op": "update_node", "id": target, "label": "Renamed"},
                        {"op": "set", "name": "Renamed diagram"}))
        assert out["applied"][0].startswith("updated")
        saved = _doc(env, rid)["graph"]
        assert _r2_data(saved) == before
        assert _node(env, rid, target)["data"]["label"] == "Renamed"
        if graph.get("repairable"):
            assert saved["costs"] == graph["costs"]


def test_edit_rbd_rewiring_a_diagram_with_a_repeated_block(env):
    rid = _saved(env, NON_REPAIRABLE)
    out = _ok(_edit(env, rid, {"op": "add_node", "parallel_to": "b",
                               "node": {"id": "c", "type": "component", "label": "Pump C",
                                        "model": {"distribution_id": "exponential",
                                                  "params": [{"name": "failure_rate", "value": 3e-3}]}}}))
    assert "c" in {n["id"] for n in out["nodes"]}
    saved = _doc(env, rid)["graph"]
    assert _node(env, rid, "psu2")["data"]["repeat_of"] == "psu"
    assert ("ctl", "c") in {(e["source"], e["target"]) for e in saved["edges"]}


def test_analyze_rbd_on_r2_diagrams(env):
    rid = _saved(env, NON_REPAIRABLE)
    out = _ok(_call(env.token[A], "analyze_rbd", {"rbd_id": rid, "times": [100.0, 1000.0]}))
    assert out["available"] and out["kind"] == "non_repairable"
    assert out["mttf"] > 0 and len(out["reliability_at"]) == 2
    # The repeated supply is reported once, under the original.
    assert "Power supply" in out["importance"]["birnbaum"]
    assert all(0.0 <= v <= 1.0 for v in out["importance"]["fussell_vesely"].values() if v is not None)

    rid = _saved(env, REPAIRABLE, name="Plant")
    out = _ok(_call(env.token[A], "analyze_rbd", {"rbd_id": rid}))
    # Billing is off in these tests, so the (paid) simulation runs.
    assert out["kind"] == "repairable" and out["available"]
    assert 0.0 < out["steady_state_availability"] < 1.0
    assert out["precision"]["n_simulations"] > 0


def test_clone_and_export_r2_diagrams(env):
    for graph in (NON_REPAIRABLE, REPAIRABLE):
        rid = _saved(env, graph)
        clone = _ok(_call(env.token[A], "clone_rbd", {"rbd_id": rid, "name": "Copy"}))
        assert _r2_data(_doc(env, clone["id"])["graph"]) == _r2_data(graph)
        out = _ok(_call(env.token[A], "export_rbd_python", {"rbd_id": rid}))
        assert out["filename"].endswith(".py") and "RePyability" in out["script"]
        compile(out["script"], out["filename"], "exec")
