"""Allocation (#53): what each block needs for the system to meet a target.

Every method's answer is checked against RePyability called directly on the
same diagram; unreachable targets report the reachable range; the endpoint
and the MCP tool give the same figures.
"""

import mongomock
import numpy as np
import pytest
import surpyval as surv
from repyability import NonRepairableRBD, RepairableRBD

from backend.services import rbd_allocation as ra
from backend.services.rbd_allocation import AllocationError

T = 100.0
RATES = {"a": 1e-3, "b": 1e-3, "c": 1e-4}
REPAIRS = {"a": 1.0, "b": 1.0, "c": 0.5}  # repair rates (MTTR 1 h, 1 h, 2 h)


def _exp(rate):
    return {"source": "params", "distribution": "Exponential", "distribution_id": "exponential",
            "params": [{"name": "failure_rate", "value": rate}]}


def _node(nid, ntype="component", **data):
    return {"id": nid, "type": ntype, "position": {"x": 0, "y": 0}, "data": {"label": nid.upper(), **data}}


def _pumps(repairable=False):
    """Two parallel pumps a, b in series with a valve c."""
    nodes = [_node("input", "input"), _node("output", "output")]
    for nid, rate in RATES.items():
        extra = {"repair": _exp(REPAIRS[nid])} if repairable else {}
        nodes.append(_node(nid, model=_exp(rate), **extra))
    edges = [("input", "a"), ("input", "b"), ("a", "c"), ("b", "c"), ("c", "output")]
    graph = {"nodes": nodes, "edges": [{"id": f"{s}-{t}", "source": s, "target": t} for s, t in edges],
             "unit": "Hours"}
    if repairable:
        graph["repairable"] = True
    return graph


def _series():
    nodes = [_node("input", "input"), _node("output", "output")]
    rates = {"a": 3e-3, "b": 2e-3, "c": 1e-3, "d": 5e-4}
    for nid, rate in rates.items():
        nodes.append(_node(nid, model=_exp(rate)))
    chain = ["input", *rates, "output"]
    return {"nodes": nodes, "edges": [{"id": f"{s}-{t}", "source": s, "target": t} for s, t in zip(chain, chain[1:])],
            "unit": "Hours"}, rates


def _library():
    """The same pumps-and-valve diagram, built straight in RePyability."""
    edges = [("s", "a"), ("s", "b"), ("a", "c"), ("b", "c"), ("c", "t")]
    rel = {n: surv.Exponential.from_params([r]) for n, r in RATES.items()}
    return NonRepairableRBD(edges, rel, input_node="s", output_node="t")


def _library_repairable():
    edges = [("s", "a"), ("s", "b"), ("a", "c"), ("b", "c"), ("c", "t")]
    comps = {n: {"reliability": surv.Exponential.from_params([RATES[n]]),
                 "repairability": surv.Exponential.from_params([REPAIRS[n]])} for n in RATES}
    return RepairableRBD(edges, comps, input_node="s", output_node="t")


def _required(res):
    return {b["id"]: b["required"] for b in res["blocks"]}


# ---- non-repairable --------------------------------------------------------------------

def test_every_non_repairable_method_matches_the_library():
    lib = _library()
    current = {n: float(v) for n, v in lib.node_sf(T).items() if n in RATES}
    expected = {
        "equal": lib.equal_allocation(0.999),
        "simple": lib.simple_allocation(0.999, weights={"a": 1.0, "b": 1.0, "c": 2.0}),
        "improvement": lib.improvement_allocation(0.999, current, fixed=["a"]),
        "cost_based": lib.cost_based_allocation(0.999, current, max_probabilities={"c": 0.9995},
                                                feasibility={"c": 0.2}),
    }
    options = {
        "equal": {},
        "simple": {"weights": {"c": 2}},
        "improvement": {"fixed": ["a"]},
        "cost_based": {"max": {"c": 0.9995}, "feasibility": {"c": 0.2}},
    }
    for method, want in expected.items():
        res = ra.allocate(_pumps(), 0.999, method, t=T, options=options[method])
        got = _required(res)
        for nid in RATES:
            assert got[nid] == pytest.approx(want[nid], rel=1e-9, abs=1e-12), (method, nid)
        assert res["system"]["current"] == pytest.approx(float(lib.sf(T)), rel=1e-12)
        assert res["system"]["allocated"] == pytest.approx(0.999, rel=1e-8)
        assert res["kind"] == "reliability" and res["t"] == T
    rows = {b["id"]: b for b in ra.allocate(_pumps(), 0.999, "improvement", t=T, options={"fixed": ["a"]})["blocks"]}
    assert rows["a"]["fixed"] and rows["a"]["required"] == pytest.approx(rows["a"]["current"])
    assert rows["a"]["label"] == "A"


def test_minimum_effort_on_a_series_system_and_its_refusal_otherwise():
    graph, rates = _series()
    edges = [("s", "a"), ("a", "b"), ("b", "c"), ("c", "d"), ("d", "t")]
    lib = NonRepairableRBD(edges, {n: surv.Exponential.from_params([r]) for n, r in rates.items()},
                           input_node="s", output_node="t")
    current = {n: float(v) for n, v in lib.node_sf(T).items() if n in rates}
    want = lib.minimum_effort_allocation(0.6, current)
    got = _required(ra.allocate(graph, 0.6, "minimum_effort", t=T))
    for nid in rates:
        assert got[nid] == pytest.approx(want[nid], rel=1e-12)
    with pytest.raises(AllocationError, match="series system only"):
        ra.allocate(_pumps(), 0.999, "minimum_effort", t=T)


def test_an_unreachable_target_gives_the_reachable_range():
    with pytest.raises(AllocationError) as err:
        ra.allocate(_pumps(), 0.99999, "improvement", t=T, options={"fixed": ["c"]})
    assert err.value.reachable == {"low": 0.0, "high": pytest.approx(0.99005, rel=1e-5), "high_reached": True}
    assert "can't be reached" in str(err.value) and "99.005%" in str(err.value)
    with pytest.raises(AllocationError) as err:
        ra.allocate(_pumps(), 0.9999, "cost_based", t=T, options={"max": {"c": 0.995}})
    reach = err.value.reachable
    assert reach["high_reached"] is False and reach["low"] == pytest.approx(0.981084, rel=1e-5)


def test_inputs_are_checked():
    with pytest.raises(AllocationError, match="mission time"):
        ra.allocate(_pumps(), 0.99, "equal")
    with pytest.raises(AllocationError, match="target reliability"):
        ra.allocate(_pumps(), 1.0, "equal", t=T)
    with pytest.raises(AllocationError, match="method must be one of"):
        ra.allocate(_pumps(), 0.99, "mttf_mttr", t=T)
    with pytest.raises(AllocationError, match="isn't a block"):
        ra.allocate(_pumps(), 0.99, "improvement", t=T, options={"fixed": ["zz"]})
    graph = {**_pumps(), "ccf_groups": [{"members": ["a", "b"], "beta": 0.1}]}
    with pytest.raises(AllocationError, match="common-cause"):
        ra.allocate(graph, 0.99, "equal", t=T)


def test_pins_are_ignored():
    graph = _pumps()
    graph["nodes"][2]["data"]["state"] = "failed"
    res = ra.allocate(graph, 0.999, "equal", t=T)
    assert res["system"]["current"] == pytest.approx(float(_library().sf(T)))


# ---- repairable ------------------------------------------------------------------------

@pytest.mark.parametrize("how", ["cost_based", "improvement", "equal"])
def test_availability_allocation_matches_the_library(how):
    want = _library_repairable().availability_allocation(0.9999, how)
    res = ra.allocate(_pumps(True), 0.9999, "availability", options={"availability_method": how})
    rows = {b["id"]: b for b in res["blocks"]}
    for nid in RATES:
        assert rows[nid]["required"] == pytest.approx(want.availability[nid], rel=1e-9)
        assert rows[nid]["mttf"] == pytest.approx(want.mttf[nid], rel=1e-9)
        assert rows[nid]["mttr"] == pytest.approx(want.mttr[nid], rel=1e-9)
        assert rows[nid]["current_mttf"] == pytest.approx(1 / RATES[nid])
        assert rows[nid]["current_mttr"] == pytest.approx(1 / REPAIRS[nid])
    assert res["system"]["allocated"] == pytest.approx(want.system_availability)
    assert res["system"]["current"] == pytest.approx(_library_repairable().mean_availability())
    assert res["availability_method"] == how


@pytest.mark.parametrize("levers", ["both", "mttr"])
def test_mttf_mttr_allocation_matches_the_library(levers):
    want = _library_repairable().mttf_mttr_allocation(0.9999, levers=levers, min_mttr={"c": 1.0})
    res = ra.allocate(_pumps(True), 0.9999, "mttf_mttr", options={"levers": levers, "min_mttr": {"c": 1.0}})
    rows = {b["id"]: b for b in res["blocks"]}
    for nid in RATES:
        assert rows[nid]["mttf"] == pytest.approx(want.mttf[nid], rel=1e-9)
        assert rows[nid]["mttr"] == pytest.approx(want.mttr[nid], rel=1e-9)
    assert res["levers"] == levers


def test_repairable_unreachable_and_refusals():
    with pytest.raises(AllocationError) as err:
        ra.allocate(_pumps(True), 0.999999, "availability", options={"fixed": ["c"]})
    assert err.value.reachable["high"] == pytest.approx(0.9998, rel=1e-4)
    with pytest.raises(AllocationError, match="series system only"):
        ra.allocate(_pumps(True), 0.9999, "availability", options={"availability_method": "minimum_effort"})
    with pytest.raises(AllocationError, match="availability or mttf_mttr"):
        ra.allocate(_pumps(True), 0.9999, "equal")


# ---- the endpoint and the MCP tool -----------------------------------------------------

USER = {"uid": "user-alloc", "email": "alloc@example.org", "name": "Allocator"}


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


def test_allocate_endpoint(client):
    r = client.post("/api/rbds/allocate", json={"graph": _pumps(), "target": 0.999, "method": "equal", "t": T})
    assert r.status_code == 200, r.text
    assert _required(r.json())["a"] == pytest.approx(_library().equal_allocation(0.999)["a"])
    r = client.post("/api/rbds/allocate", json={"graph": _pumps(), "target": 0.99999, "method": "improvement",
                                                "t": T, "options": {"fixed": ["c"]}})
    assert r.status_code == 422 and r.json()["reachable"]["high"] == pytest.approx(0.99005, rel=1e-5)


@pytest.mark.filterwarnings("ignore:the cost minimisation stopped")
def test_mcp_allocate_targets(monkeypatch):
    from backend import config, db
    from backend.services import rbds as rbds_service
    from backend.services import tokens
    from backend.tests.test_mcp import A, _call, _ok

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    test_db = mongomock.MongoClient()["reliafy_mcp_alloc"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    test_db.users.insert_one({"_id": A, "email": "a@example.org", "name": "A"})
    token = tokens.create_token(test_db, A, "mcp")["token"]
    nr = rbds_service.save_rbd(test_db, "Pumps", _pumps(), A)
    rep = rbds_service.save_rbd(test_db, "Pumps (repairable)", _pumps(True), A)

    out = _ok(_call(token, "allocate_targets", {"rbd_id": nr.id, "target": 0.999, "t": T}))
    assert out["reached"] is True and out["method"] == "cost_based" and out["kind"] == "reliability"
    want = _library().cost_based_allocation(
        0.999, {n: float(v) for n, v in _library().node_sf(T).items() if n in RATES})
    assert {b["id"]: b["required"] for b in out["blocks"]}["c"] == pytest.approx(want["c"], rel=1e-9)
    far = _ok(_call(token, "allocate_targets", {"rbd_id": nr.id, "target": 0.99999, "t": T,
                                                "method": "improvement", "fixed": ["c"]}))
    assert far["reached"] is False and far["reachable"]["high"] == pytest.approx(0.99005, rel=1e-5)
    avail = _ok(_call(token, "allocate_targets", {"rbd_id": rep.id, "target": 0.9999, "method": "mttf_mttr"}))
    assert avail["kind"] == "availability" and avail["system"]["allocated"] == pytest.approx(0.9999)
    err = _call(token, "allocate_targets", {"rbd_id": rep.id, "target": 0.9999, "method": "equal"})
    assert err.is_error and "repairable" in err.content[0].text
    err = _call(token, "allocate_targets", {"rbd_id": nr.id, "target": 0.99})
    assert err.is_error and "mission time" in err.content[0].text


def test_allocation_does_not_reimplement_the_engine():
    """The allocated system figure is the library's own system probability."""
    res = ra.allocate(_pumps(), 0.995, "simple", t=T)
    lib = _library()
    probs = {nid: np.atleast_1d(v) for nid, v in _required(res).items()}
    assert res["system"]["allocated"] == pytest.approx(float(lib.system_probability(probs)[0]), rel=1e-12)
