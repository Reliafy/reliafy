"""#271: a diagram with nothing to analyse yet — only Input and Output, or
blocks with no path through them from Input to Output — gets one plain
message from every analysis (a 422 for API callers, a tool error over MCP),
and the validate step flags it as ``empty`` so the app shows a next step
rather than an error. The app itself doesn't call the analyses then (see
frontend/src/rbdReadiness.js)."""

import pytest

from backend.services import outage_logs
from backend.services import rbd_analysis as ra
from backend.services.rbd_graph import GAP_MESSAGES, NO_BLOCKS, NOT_CONNECTED, diagram_gap
from backend.tests.test_availability_paid import PRO, client  # noqa: F401 - fixture
from backend.tests.test_mcp import GRAPH, A, _call, _err, _ok, env  # noqa: F401 - fixture
from backend.tests.test_rbd_analysis import _component, _edge, _io_nodes, _repairable_component

NO_BLOCKS_TEXT = GAP_MESSAGES[NO_BLOCKS]
NOT_CONNECTED_TEXT = GAP_MESSAGES[NOT_CONNECTED]


def _w(nid):
    return _component(nid, nid.upper(), "weibull", [("alpha", 900), ("beta", 1.5)])


def _r(nid):
    node = _repairable_component(nid, nid.upper(), 900, 1.5, 1.0)
    node["data"]["costs"] = {"acquisition": 1000}
    return node


def _graph(nodes, edges, repairable=False):
    g = {"nodes": _io_nodes() + nodes, "edges": [_edge(s, t) for s, t in edges], "unit": "hours"}
    if repairable:
        g.update(repairable=True, costs={"downtime_rate": 100, "horizon": 8760})
    return g


def _empty(repairable=False):
    """What a new user saves: Input and Output, nothing between."""
    return _graph([], [], repairable)


def _io_wired(repairable=False):
    return _graph([], [("input", "output")], repairable)


def _loose(repairable=False):
    """A block on the canvas, not wired to anything."""
    return _graph([(_r if repairable else _w)("a")], [], repairable)


def _half(repairable=False):
    """Wired from Input, never reaching Output."""
    return _graph([(_r if repairable else _w)("a")], [("input", "a")], repairable)


GAPS = [
    (_empty, NO_BLOCKS), (_io_wired, NO_BLOCKS), (_loose, NOT_CONNECTED), (_half, NOT_CONNECTED),
]


# ---- what counts as empty -----------------------------------------------------------------

@pytest.mark.parametrize("make, gap", GAPS)
def test_gaps(make, gap):
    assert diagram_gap(make()) == gap
    assert diagram_gap(make(repairable=True)) == gap


def test_a_connected_diagram_has_no_gap():
    assert diagram_gap(_graph([_w("a")], [("input", "a"), ("a", "output")])) is None
    # One path through is enough: a block left dangling beside it is the
    # analyses' own (structural) problem to explain.
    g = _graph([_w("a"), _w("b")], [("input", "a"), ("a", "output"), ("input", "b")])
    assert diagram_gap(g) is None
    # Through a vote node.
    vote = {"id": "v", "type": "knode", "data": {"label": "1oo2", "n": 1, "k": 2}}
    g = _graph([_w("a"), _w("b"), vote],
               [("input", "a"), ("input", "b"), ("a", "v"), ("b", "v"), ("v", "output")])
    assert diagram_gap(g) is None


def test_edges_run_one_way():
    """Wired backwards (Output to block to Input) is no path."""
    assert diagram_gap(_graph([_w("a")], [("output", "a"), ("a", "input")])) == NOT_CONNECTED


def test_without_one_input_and_output_the_analyses_say_so_themselves():
    g = {"nodes": [_w("a")], "edges": []}
    assert diagram_gap(g) is None
    assert diagram_gap({"nodes": [], "edges": []}) == NO_BLOCKS
    assert diagram_gap(None) is None and diagram_gap("x") is None


# ---- the services ---------------------------------------------------------------------------

@pytest.mark.parametrize("make, gap", GAPS)
def test_validate_flags_it_with_one_plain_message(make, gap):
    for repairable in (False, True):
        v = ra.validate_graph(make(repairable))
        assert v["empty"] == gap
        assert v["errors"] == [GAP_MESSAGES[gap]]
        assert v["valid"] is False and v["can_calculate"] is False and v["warnings"] == []
        if repairable:
            assert v["availability_routes"] is None


def test_validate_of_a_real_diagram_has_no_empty_flag():
    v = ra.validate_graph(_graph([_w("a")], [("input", "a"), ("a", "output")]))
    assert v["valid"] is True and "empty" not in v


@pytest.mark.parametrize("make, gap", GAPS)
def test_both_builders_refuse_it_in_plain_words(make, gap):
    with pytest.raises(ra.AnalysisError) as exc:
        ra._build_rbd(make())
    assert str(exc.value) == GAP_MESSAGES[gap]
    with pytest.raises(ra.AnalysisError) as exc:
        ra._build_repairable_rbd(make(repairable=True))
    assert str(exc.value) == GAP_MESSAGES[gap]


def test_an_empty_sub_system_is_named():
    g = _graph([{"id": "s", "type": "subsystem", "data": {"label": "Skid", "rbd": {"id": "sub", "name": "Pumps"}}}],
               [("input", "s"), ("s", "output")])
    with pytest.raises(ra.AnalysisError, match="Skid: sub-system 'Pumps' has no blocks yet"):
        ra._build_rbd(g, lambda sid: _empty())
    with pytest.raises(ra.AnalysisError, match="Skid: sub-system 'Pumps' has no blocks connected"):
        ra._build_rbd(g, lambda sid: _loose())
    v = ra.validate_graph(g, lambda sid: _empty())
    assert "empty" not in v and v["errors"] == ["Skid: sub-system 'Pumps' has no blocks yet."]


@pytest.mark.parametrize("make, gap", GAPS)
def test_outage_history_merge_says_the_same(make, gap):
    with pytest.raises(outage_logs.OutageLogError) as exc:
        outage_logs._structure(make())
    assert str(exc.value) == GAP_MESSAGES[gap]


# ---- every endpoint a builder tab calls -------------------------------------------------------

ENDPOINTS = [
    # (path, extra body, repairable diagram?)
    ("/api/rbds/analyze", {}, False),
    ("/api/rbds/analyze", {}, True),
    ("/api/rbds/fault-tree", {}, False),
    ("/api/rbds/fault-tree", {}, True),
    ("/api/rbds/design", {"t": 100, "budget": {"cost": 3}}, False),
    ("/api/rbds/design/cheapest", {}, True),
    ("/api/rbds/sensitivity", {}, True),
    ("/api/rbds/intervals", {}, True),
]


@pytest.mark.parametrize("path, extra, repairable", ENDPOINTS)
@pytest.mark.parametrize("make, gap", GAPS)
def test_endpoints_answer_422_in_plain_words(client, path, extra, repairable, make, gap):
    client.act_as(PRO)
    r = client.post(path, json={"graph": make(repairable), **extra})
    assert r.status_code == 422, r.text
    assert r.json() == {"detail": GAP_MESSAGES[gap]}


@pytest.mark.parametrize("path", ["/api/rbds/sensitivity", "/api/rbds/intervals", "/api/rbds/design/cheapest"])
def test_no_blocks_comes_before_repairable_only(client, path):
    """A new, empty (non-repairable) diagram hears that it's empty first."""
    client.act_as(PRO)
    r = client.post(path, json={"graph": _empty()})
    assert r.status_code == 422 and r.json()["detail"] == NO_BLOCKS_TEXT


@pytest.mark.parametrize("make, gap", GAPS)
def test_validate_endpoint(client, make, gap):
    client.act_as(PRO)
    r = client.post("/api/rbds/validate", json={"graph": make()})
    assert r.status_code == 200
    assert r.json()["empty"] == gap and r.json()["errors"] == [GAP_MESSAGES[gap]]


def test_saved_empty_diagram(client):
    """Saving an empty diagram is fine; analysing it by id says it's empty."""
    client.act_as(PRO)
    r = client.post("/api/rbds", json={"name": "New", "graph": _empty()})
    assert r.status_code == 200, r.text
    rid = r.json()["id"]
    r = client.get(f"/api/rbds/{rid}/analyze")
    assert r.status_code == 422 and r.json()["detail"] == NO_BLOCKS_TEXT
    r = client.get(f"/api/rbds/{rid}/validate")
    assert r.status_code == 200 and r.json()["empty"] == NO_BLOCKS


# ---- MCP ---------------------------------------------------------------------------------------

def _saved(env, graph):
    rid = _ok(_call(env.token[A], "create_rbd", {"name": "Empty", **GRAPH}))["id"]
    env.db.rbds.update_one({"_id": rid}, {"$set": {"graph": graph}})
    return rid


@pytest.mark.parametrize("make, gap", [(_empty, NO_BLOCKS), (_half, NOT_CONNECTED)])
def test_mcp_tools_answer_in_plain_words(env, make, gap):
    rid = _saved(env, make())
    for tool in ("analyze_rbd", "rbd_fault_tree"):
        assert GAP_MESSAGES[gap] in _err(_call(env.token[A], tool, {"rbd_id": rid})), tool
    rid = _saved(env, make(repairable=True))
    for tool in ("analyze_rbd", "rbd_fault_tree", "rbd_sensitivity", "optimise_maintenance_intervals"):
        assert GAP_MESSAGES[gap] in _err(_call(env.token[A], tool, {"rbd_id": rid})), tool
