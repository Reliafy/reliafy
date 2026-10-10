"""Production availability (#122): block capacities and the share of a demand
delivered.

The figures are checked against RePyability called directly; capacities
survive the compact graph, edit_rbd, the JSON export and import and the
"Download as Python" script; analyze_rbd reports them; the solar-farm sample
reports its energy lost.
"""

import json
import math

import mongomock
import pytest
import surpyval as surv
from repyability import NonRepairableRBD, RepairableRBD
from repyability.rbd.serialisation import rbd_from_dict

from backend.services import rbd_capacity as rc
from backend.services import rbd_edit, rbd_graph, rbd_json, samples
from backend.services.rbd_capacity import CapacityError

LEVELS = [{"value": 50.0, "probability": 0.8}, {"value": 25.0, "probability": 0.2}]


def _exp(rate):
    return {"source": "params", "distribution": "Exponential", "distribution_id": "exponential",
            "params": [{"name": "failure_rate", "value": rate}]}


def _node(nid, ntype="component", **data):
    return {"id": nid, "type": ntype, "position": {"x": 0, "y": 0}, "data": {"label": nid.title(), **data}}


def _plant(repairable=True, demand=100.0, period=500.0):
    """Three pumps (a, b at 50; c at 50 or 25) in parallel feeding a pipe of 120."""
    def extra(rate):
        return {"repair": _exp(rate)} if repairable else {}
    nodes = [_node("input", "input"), _node("output", "output"),
             _node("a", model=_exp(0.01), capacity=50, **extra(0.5)),
             _node("b", model=_exp(0.01), capacity=50, **extra(0.5)),
             _node("c", model=_exp(0.02), capacity=LEVELS, **extra(0.25)),
             _node("pipe", model=_exp(0.001), capacity=120, **extra(0.1))]
    edges = [("input", "a"), ("input", "b"), ("input", "c"), ("a", "pipe"), ("b", "pipe"), ("c", "pipe"),
             ("pipe", "output")]
    graph = {"nodes": nodes, "edges": [{"id": f"{s}-{t}", "source": s, "target": t} for s, t in edges],
             "unit": "Hours", "production": {"demand": demand, "unit": "m3/h", "period": period}}
    if repairable:
        graph["repairable"] = True
    return graph


CAPS = {"a": 50.0, "b": 50.0, "c": {50.0: 0.8, 25.0: 0.2}, "pipe": 120.0}
EDGES = [("s", "a"), ("s", "b"), ("s", "c"), ("a", "pipe"), ("b", "pipe"), ("c", "pipe"), ("pipe", "t")]
RATES = {"a": (0.01, 0.5), "b": (0.01, 0.5), "c": (0.02, 0.25), "pipe": (0.001, 0.1)}


def _library_repairable():
    comps = {n: {"reliability": surv.Exponential.from_params([f]),
                 "repairability": surv.Exponential.from_params([r])} for n, (f, r) in RATES.items()}
    return RepairableRBD(EDGES, comps, input_node="s", output_node="t", capacity=CAPS)


def _library_nonrepairable():
    rel = {n: surv.Exponential.from_params([f]) for n, (f, _) in RATES.items()}
    return NonRepairableRBD(EDGES, rel, input_node="s", output_node="t", capacity=CAPS)


# ---- the figures ---------------------------------------------------------------------

def test_repairable_production_matches_the_library():
    res = rc.production(_plant())
    lib = _library_repairable()
    long_run = lib.capacity_distribution()
    assert res["basis"] == "long_run" and res["demand"] == 100.0 and res["capacity_unit"] == "m3/h"
    assert [lv["capacity"] for lv in res["levels"]] == [x for x, p in zip(long_run.levels, long_run.probabilities)
                                                        if p > 0]
    assert res["production_availability"] == pytest.approx(long_run.delivered_fraction(100.0), rel=1e-12)
    assert res["meets_demand"] == pytest.approx(long_run.meets(100.0), rel=1e-12)
    assert res["mean_capacity"] == pytest.approx(long_run.mean, rel=1e-12)
    assert res["availability"] == pytest.approx(lib.mean_availability(), rel=1e-9)
    assert res["shortfall_rate"] == pytest.approx(100.0 * (1 - long_run.delivered_fraction(100.0)))
    window = lib.mission_capacity(500.0)
    assert res["period"]["production_availability"] == pytest.approx(window.delivered_fraction(100.0), rel=1e-9)
    assert res["period"]["lost"] == pytest.approx(100.0 * 500.0 * (1 - window.delivered_fraction(100.0)), rel=1e-9)
    # Partial outages cost output: the production availability is below the plain availability.
    assert res["production_availability"] < res["availability"]


def test_nonrepairable_production_at_a_time_matches_the_library():
    res = rc.production(_plant(repairable=False), t=40.0)
    dist = _library_nonrepairable().capacity_distribution(40.0)
    assert res["basis"] == "at_time" and res["t"] == 40.0
    assert res["production_availability"] == pytest.approx(dist.delivered_fraction(100.0), rel=1e-12)
    assert res["availability"] == pytest.approx(float(_library_nonrepairable().sf(40.0)), rel=1e-9)
    # Without a time, the period is the time read at; with neither, a plain refusal.
    assert rc.production(_plant(repairable=False, period=40.0))["t"] == 40.0
    with pytest.raises(CapacityError, match="Give a time"):
        rc.production(_plant(repairable=False, period=None))


def test_no_capacity_no_demand_and_bad_values():
    graph = _plant()
    for n in graph["nodes"]:
        n["data"].pop("capacity", None)
    assert rc.production(graph) is None and not rc.has_capacity(graph)
    res = rc.production(_plant(demand=None))
    assert "production_availability" not in res and "Set a demand" in res["notes"][0]
    with pytest.raises(CapacityError, match="add up to 1"):
        rc.parse_capacity([{"value": 5, "probability": 0.5}])
    with pytest.raises(CapacityError, match="positive"):
        rc.parse_capacity(-3)
    assert rc.parse_capacity([{"value": 5, "probability": 1}]) == 5.0
    bad = _plant()
    bad["nodes"].append(_node("vote", "knode", n=1, capacity=10))
    with pytest.raises(CapacityError, match="can't carry a capacity"):
        rc.graph_capacities(bad)


def test_solar_farm_sample_reports_energy_lost():
    spec = next(s for s in samples.SAMPLE_RBDS if s["id"] == "sample-rbd-solar-farm")
    res = rc.production(spec["graph"])
    assert res["demand"] == 900.0 and res["capacity_unit"] == "kW"
    assert res["period"]["length"] == 8760.0 and res["period"]["lost"] > 0
    # Partial outages (one inverter down, or derated) cost more than whole-farm outages alone.
    assert res["period"]["lost"] > 900.0 * 8760.0 * (1 - res["period"]["availability"])
    assert 0.99 < res["production_availability"] < res["availability"] < 1


# ---- carried through the graph, edits and exports --------------------------------------

def test_compact_graph_and_edit_rbd_carry_capacities():
    normal = rbd_graph.normalize_graph({
        "nodes": [{"id": "input", "type": "input"}, {"id": "p", "type": "component", "label": "P",
                                                     "model": {"distribution_id": "exponential",
                                                               "params": [{"name": "failure_rate", "value": 0.1}]},
                                                     "capacity": LEVELS},
                  {"id": "output", "type": "output"}],
        "edges": [{"source": "input", "target": "p"}, {"source": "p", "target": "output"}],
        "unit": "Hours", "production": {"demand": "40", "unit": "t/h"},
    })
    p = next(n for n in normal["nodes"] if n["id"] == "p")
    assert p["data"]["capacity"] == [{"value": 25.0, "probability": 0.2}, {"value": 50.0, "probability": 0.8}]
    assert normal["production"] == {"demand": 40.0, "unit": "t/h"}
    compact = rbd_graph.compact_graph(normal)
    assert compact["production"] == normal["production"]
    assert next(n for n in compact["nodes"] if n["id"] == "p")["capacity"] == p["data"]["capacity"]
    with pytest.raises(rbd_graph.GraphError, match="only component and standby"):
        rbd_graph.normalize_node({"id": "v", "type": "knode", "n": 1, "capacity": 5})

    res = rbd_edit.apply_ops(normal, [{"op": "update_node", "id": "p", "capacity": 70},
                                      {"op": "set", "production": {"demand": 60, "period": 100}}], "x")
    assert next(n for n in res.graph["nodes"] if n["id"] == "p")["data"]["capacity"] == 70.0
    assert res.graph["production"] == {"demand": 60.0, "unit": "t/h", "period": 100.0}
    res = rbd_edit.apply_ops(res.graph, [{"op": "update_node", "id": "p", "clear": ["capacity"]},
                                         {"op": "set", "production": {"demand": 0, "unit": "", "period": 0}}], "x")
    assert "capacity" not in next(n for n in res.graph["nodes"] if n["id"] == "p")["data"]
    assert "production" not in res.graph
    with pytest.raises(rbd_edit.EditError, match="positive"):
        rbd_edit.apply_ops(normal, [{"op": "update_node", "id": "p", "capacity": -1}], "x")


@pytest.mark.parametrize("repairable", [True, False])
def test_json_export_holds_the_capacities_and_imports_them(repairable):
    from backend.services.rbd_import import repyability as importer

    graph = _plant(repairable=repairable)
    doc = rbd_json.to_document(graph, "Pumps")
    entries = {e["node"]: e for e in doc["capacity"]}
    assert entries["a"] == {"node": "a", "capacity": 50.0}
    assert sorted(map(tuple, entries["c"]["levels"])) == [(25.0, 0.2), (50.0, 0.8)]
    rebuilt = rbd_from_dict(json.loads(rbd_json.to_json(doc)))
    assert rebuilt.capacity["c"] == {25.0: 0.2, 50.0: 0.8}
    # A file written outside Reliafy (no "reliafy" part) brings its capacities onto the blocks.
    plain = {k: v for k, v in doc.items() if k != rbd_json.EXTENSION_KEY}
    [diagram] = importer.parse(json.dumps(plain).encode(), "pumps.json")
    caps = {n["data"]["label"]: n["data"].get("capacity") for n in diagram.graph["nodes"]}
    assert caps["a"] == 50.0 and caps["pipe"] == 120.0
    assert caps["c"] == [{"value": 25.0, "probability": 0.2}, {"value": 50.0, "probability": 0.8}]
    # Reliafy's own file restores the diagram as it was, demand included.
    [again] = importer.parse(rbd_json.to_json(doc).encode(), "pumps.json")
    assert again.graph.get("production") == graph["production"]


@pytest.mark.parametrize("repairable", [True, False])
def test_python_export_runs_and_reports_the_production(repairable, tmp_path):
    from backend.services import rbd_export
    from backend.tests.test_rbd_export import _run

    graph = _plant(repairable=repairable, period=40.0 if not repairable else 500.0)
    code = rbd_export.to_python(graph, "Pumps")
    assert "capacity=CAPACITY" in code and "production()" in code
    _, proc = _run(code, tmp_path)
    if repairable:
        want = _library_repairable().capacity_distribution().delivered_fraction(100.0)
        assert f"Production availability: {want:.6f}" in proc.stdout
        assert "of output lost" in proc.stdout
    else:
        want = _library_nonrepairable().capacity_distribution(40.0).delivered_fraction(100.0)
        assert f"Share of the demand delivered: {want:.6f}" in proc.stdout


def test_python_export_without_capacities_is_unchanged():
    from backend.services import rbd_export

    graph = _plant()
    for n in graph["nodes"]:
        n["data"].pop("capacity", None)
    code = rbd_export.to_python(graph, "Pumps")
    assert "CAPACITY" not in code and "production()" not in code


# ---- the endpoint and MCP --------------------------------------------------------------

USER = {"uid": "user-prod", "email": "prod@example.org", "name": "Producer"}


@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    test_db = mongomock.MongoClient()["reliafy_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    app.dependency_overrides[get_current_user] = lambda: USER
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_production_endpoint(client):
    r = client.post("/api/rbds/production", json={"graph": _plant()})
    assert r.status_code == 200, r.text
    want = _library_repairable().capacity_distribution().delivered_fraction(100.0)
    assert r.json()["production"]["production_availability"] == pytest.approx(want, rel=1e-12)
    graph = _plant()
    for n in graph["nodes"]:
        n["data"].pop("capacity", None)
    assert client.post("/api/rbds/production", json={"graph": graph}).json() == {"production": None}
    r = client.post("/api/rbds/production", json={"graph": _plant(repairable=False, period=None)})
    assert r.status_code == 422 and "Give a time" in r.json()["detail"]


def test_mcp_capacity_and_production(monkeypatch):
    from backend import config, db
    from backend.services import tokens
    from backend.tests.test_mcp import A, _call, _ok

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    test_db = mongomock.MongoClient()["reliafy_mcp_prod"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    test_db.users.insert_one({"_id": A, "email": "a@example.org", "name": "A"})
    token = tokens.create_token(test_db, A, "mcp")["token"]

    def block(nid, cap, f, r):
        return {"id": nid, "type": "component", "label": nid, "capacity": cap,
                "model": {"distribution_id": "exponential", "params": [{"name": "failure_rate", "value": f}]},
                "repair": {"distribution_id": "exponential", "params": [{"name": "failure_rate", "value": r}]}}

    nodes = [{"id": "input", "type": "input"}, {"id": "output", "type": "output"},
             block("a", 50, 0.01, 0.5), block("b", 50, 0.01, 0.5), block("c", LEVELS, 0.02, 0.25),
             block("pipe", 120, 0.001, 0.1)]
    edges = [{"source": s, "target": t} for s, t in [("input", "a"), ("input", "b"), ("input", "c"),
                                                     ("a", "pipe"), ("b", "pipe"), ("c", "pipe"),
                                                     ("pipe", "output")]]
    created = _ok(_call(token, "create_rbd", {"name": "Pumps", "repairable": True, "nodes": nodes, "edges": edges,
                                              "production": {"demand": 100, "unit": "m3/h", "period": 500}}))
    out = _ok(_call(token, "analyze_rbd", {"rbd_id": created["id"], "summary_only": True}))
    prod = out["production"]
    want = _library_repairable().capacity_distribution().delivered_fraction(100.0)
    assert prod["available"] is True and prod["production_availability"] == pytest.approx(want, rel=1e-9)
    assert prod["period"]["lost"] > 0 and "levels" not in prod
    full = _ok(_call(token, "analyze_rbd", {"rbd_id": created["id"]}))
    assert math.isclose(sum(lv["probability"] for lv in full["production"]["levels"]), 1.0, rel_tol=1e-9)

    edited = _ok(_call(token, "edit_rbd", {"rbd_id": created["id"], "ops": [
        {"op": "update_node", "id": "c", "capacity": [{"value": 40, "probability": 1}]},
        {"op": "set", "production": {"demand": 80}}]}))
    assert edited["applied"]
    doc = test_db.rbds.find_one({"_id": created["id"]})
    assert next(n for n in doc["graph"]["nodes"] if n["id"] == "c")["data"]["capacity"] == 40.0
    assert doc["graph"]["production"]["demand"] == 80.0
    err = _call(token, "edit_rbd", {"rbd_id": created["id"], "ops": [
        {"op": "update_node", "id": "c", "capacity": [{"value": 40, "probability": 0.5}]}]})
    assert err.is_error and "add up to 1" in err.content[0].text
