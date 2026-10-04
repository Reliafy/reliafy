"""Fault trees with common-cause groups (#229, RePyability 0.12's
``FaultTree(ccf_groups=...)``).

The Fault tree tab draws each group's shared cause as one basic event under
every member (each member fails on its own OR by the shared cause), so it is a
cut set of its own, as PRA codes list it. RePyability 0.12 keeps the members
as the basic events and folds the shared cause into the cut sets'
probabilities (``FaultTree.from_rbd`` now keeps a diagram's groups): the two
must give the same top event, importance and member probabilities. Open-PSA
files keep their beta-factor groups (on the rate basis, #210), and the MCP
tool returns the shared causes.
"""

import copy

import numpy as np
import pytest
from repyability import FaultTree

from backend.services import rbd_analysis as ra
from backend.services import rbds as rbds_service
from backend.services import samples
from backend.services.rbd_fault_tree import fault_tree
from backend.services.rbd_graph import normalize_graph
from backend.tests.test_mcp import A, _call, _ok, env  # noqa: F401 - env is a fixture
from backend.tests.test_rbd_import_openpsa import TWO_TRAIN, one

T = 5000.0


def _air(basis=None):
    g = samples._instrument_air_design_graph()
    for group in g.get("ccf_groups") or []:
        if basis:
            group["basis"] = basis
    return g


def _native(graph, t):
    """RePyability's own tree of the calculator's diagram, groups kept."""
    rbd = ra._build_rbd(graph, None, None, None, None)[0]
    tree = FaultTree.from_rbd(rbd)
    assert tree.ccf_groups  # 0.12 keeps them (#184 there)
    return rbd, tree


@pytest.mark.filterwarnings("ignore:Common-cause group")  # the probability basis past Q = 0.1
@pytest.mark.parametrize("basis", ["rate", "probability"])
def test_the_drawn_shared_cause_agrees_with_repyabilitys_ccf_tree(basis):
    g = _air(basis)
    res = fault_tree(g, t=T)
    rbd, tree = _native(g, T)
    with np.errstate(all="ignore"):
        top = float(tree.top_event_probability(T))
    assert res["top_event_probability"] == pytest.approx(top, rel=1e-12)
    assert top == pytest.approx(1.0 - float(rbd.sf(T)), rel=1e-12)
    # Importance of the events outside the group is the same either way.
    fv = tree.fussell_vesely(T)
    events = {e["id"]: e for e in res["events"]}
    outside = [e for e in fv if e in events]
    assert outside
    for e in outside:
        assert events[e]["importance"]["fussell_vesely"] == pytest.approx(float(np.atleast_1d(fv[e])[0]), rel=1e-9)
    # A pair of members fails together by the shared cause, or both on their own.
    (cc,) = res["common_cause"]
    q_ind = events["compA:independent"]["probability"]
    pair = cc["probability"] + (1.0 - cc["probability"]) * q_ind ** 2
    native = {frozenset(c): p for c, p in tree.ranked_cut_sets(T)}
    assert native[frozenset({"compA", "compB"})] == pytest.approx(pair, rel=1e-12)


def test_common_cause_summary_is_the_shared_events_share_of_the_top_event():
    res = fault_tree(_air(), t=T)
    (cc,) = res["common_cause"]
    shared = next(e for e in res["events"] if e["node_type"] == "ccf")
    assert cc["event"] == shared["id"] and cc["members"] == ["Compressor A", "Compressor B", "Compressor C"]
    assert cc["beta"] == 0.1 and cc["basis"] == "rate"
    assert cc["probability"] == shared["probability"]
    assert cc["share"] == shared["importance"]["fussell_vesely"] and 0 < cc["share"] < 1
    # The shared cause alone is a ranked cut set, and the summary counts it.
    assert cc["cut_sets_listed"] == sum(1 for c in res["cut_sets"]["listed"] if shared["id"] in c["events"]) >= 1
    assert any(c["events"] == [shared["id"]] for c in res["cut_sets"]["listed"])
    # Rate basis: R ** beta not to have occurred.
    rbd = ra._build_rbd(_air(), None, None, None, None)[0]
    r = float(rbd.reliabilities["compA"].sf(T))
    assert cc["probability"] == pytest.approx(1.0 - r ** 0.1, rel=1e-12)
    assert res["notes"] == []


def test_a_probability_basis_group_past_its_range_is_noted():
    res = fault_tree(_air("probability"), t=T)
    (note,) = res["notes"]
    assert "probability basis" in note and "Set the group's basis to rate" in note
    # Early on, where Q is small, there's nothing to say.
    assert fault_tree(_air("probability"), t=50.0)["notes"] == []


def test_no_groups_no_common_cause():
    g = _air()
    g["ccf_groups"] = []
    assert fault_tree(g, t=T)["common_cause"] == []


# ---------------------------------------------------------------------------
# Open-PSA: groups kept, on the rate basis, into the tree
# ---------------------------------------------------------------------------
def test_open_psa_groups_reach_the_fault_tree():
    d = one(TWO_TRAIN)
    assert d.graph["ccf_groups"] and "basis" not in d.graph["ccf_groups"][0]  # rate: the lifetime default
    assert any("splitting each member's failure rate" in w and "“Pumps”" in w for w in d.warnings)
    g = normalize_graph(copy.deepcopy(d.graph))
    assert ra.ccf_basis(g["ccf_groups"][0]) == "rate"
    res = fault_tree(g, t=10000.0)
    (cc,) = res["common_cause"]
    assert cc["members"] == ["PumpA", "PumpB"] and cc["basis"] == "rate"
    rbd = ra._build_rbd(g, None, None, None, None)[0]
    assert res["top_event_probability"] == pytest.approx(1.0 - float(rbd.sf(10000.0)), rel=1e-12)


def test_open_psa_mgl_pair_is_a_beta_factor_group():
    d = one(TWO_TRAIN.replace('model="beta-factor"', 'model="MGL"'))
    ids = {n["label"]: n["id"] for n in d.graph["nodes"]}
    assert d.graph["ccf_groups"] == [{"members": [ids["PumpA"], ids["PumpB"]], "beta": 0.1}]
    assert not any("only beta-factor" in w for w in d.warnings)


def test_open_psa_mgl_of_three_is_still_skipped():
    xml = """<opsa-mef><define-gate name="T"><atleast min="2">
        <basic-event name="A"/><basic-event name="B"/><basic-event name="C"/></atleast></define-gate>
        <define-CCF-group name="Trio" model="MGL">
          <members><basic-event name="A"/><basic-event name="B"/><basic-event name="C"/></members>
          <distribution><exponential><float value="1e-3"/><system-mission-time/></exponential></distribution>
          <factors><factor level="2"><float value="0.1"/></factor><factor level="3"><float value="0.3"/></factor></factors>
        </define-CCF-group></opsa-mef>"""
    d = one(xml)
    assert "ccf_groups" not in d.graph
    assert any("“Trio” uses the MGL model" in w for w in d.warnings)


# ---------------------------------------------------------------------------
# MCP: rbd_fault_tree
# ---------------------------------------------------------------------------
def test_mcp_fault_tree_returns_the_shared_cause(env):
    g = _air()
    rbd = rbds_service.save_rbd(env.db, "Instrument air", g, A)
    out = _ok(_call(env.token[A], "rbd_fault_tree", {"rbd_id": rbd.id, "t": T, "max_cut_sets": 8}))
    app = fault_tree(g, t=T)
    assert out["kind"] == "reliability" and out["t"] == T
    assert out["top_event_probability"] == pytest.approx(app["top_event_probability"], rel=1e-12)
    assert out["reliability"] == pytest.approx(1.0 - app["top_event_probability"], rel=1e-12)
    assert len(out["cut_sets"]["listed"]) == 8 and out["cut_sets"]["count"] == app["cut_sets"]["count"]
    (cc,) = out["common_cause"]
    assert cc["members"] == ["Compressor A", "Compressor B", "Compressor C"] and cc["basis"] == "rate"
    shared = [c for c in out["cut_sets"]["listed"] if c["common_cause"]]
    assert shared and shared[0]["events"] == ["Common cause: Compressor A, Compressor B, Compressor C"]
    assert "gates" not in out
    with_gates = _ok(_call(env.token[A], "rbd_fault_tree", {"rbd_id": rbd.id, "include_gates": True}))
    assert with_gates["gates"][0]["id"] == "TOP" and with_gates["t"] == with_gates["t_default"]
    assert any(g["kind"] == "vote" for g in with_gates["gates"])


def test_mcp_fault_tree_of_a_repairable_diagram(env):
    from backend.tests.test_rbd_trains import _station

    rbd = rbds_service.save_rbd(env.db, "Station", _station(), A)
    out = _ok(_call(env.token[A], "rbd_fault_tree", {"rbd_id": rbd.id, "t": 100}))
    assert out["kind"] == "availability" and "t" not in out
    built = ra._build_repairable_rbd(_station())[0]
    assert out["unavailability"] == pytest.approx(1.0 - built.mean_availability(), rel=1e-9)
    assert out["common_cause"] == []
