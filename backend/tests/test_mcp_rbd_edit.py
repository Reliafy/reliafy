"""edit_rbd and clone_rbd: token-efficient changes to saved RBDs over MCP.

Through the real MCP mount (the helpers and ``env`` fixture come from
test_mcp), plus direct checks on what was saved.
"""

import json
from datetime import datetime, timezone

import pytest

from backend.tests.test_mcp import A, B, GRAPH, _call, _err, _ok, env  # noqa: F401 - env is a fixture


def _w(alpha=1000, beta=2.0):
    return {"distribution_id": "weibull", "params": [{"name": "alpha", "value": alpha}, {"name": "beta", "value": beta}]}


def _chain(*ids, model=None):
    nodes = [{"id": "input", "type": "input"}] + [
        {"id": i, "type": "component", "label": f"Block {i}", "model": model or _w()} for i in ids
    ] + [{"id": "output", "type": "output"}]
    names = [n["id"] for n in nodes]
    return {"nodes": nodes, "edges": [{"source": s, "target": t} for s, t in zip(names, names[1:])]}


def _create(env, graph=None, name="Pump skid", **kw):
    return _ok(_call(env.token[A], "create_rbd", {"name": name, "unit": "Hours", **(graph or GRAPH), **kw}))


def _edit(env, rid, *ops, token=None, **kw):
    return _call(token or env.token[A], "edit_rbd", {"rbd_id": rid, "ops": list(ops), **kw})


def _doc(env, rid):
    return env.db.rbds.find_one({"_id": rid})


def _edges(env, rid):
    return {(e["source"], e["target"]) for e in _doc(env, rid)["graph"]["edges"]}


def _node(env, rid, nid):
    return next(n for n in _doc(env, rid)["graph"]["nodes"] if n["id"] == nid)


GRAPH_EDGES = {("input", "ctl"), ("ctl", "p1"), ("ctl", "p2"), ("p1", "output"), ("p2", "output")}


def test_both_tools_are_on_every_plan():
    from backend.mcp_server import PRO_ONLY_TOOLS, UNGATED_TOOLS

    # Gated like any other tool: available on Free and Agent, counted against the daily quota.
    assert not {"edit_rbd", "clone_rbd"} & (PRO_ONLY_TOOLS | UNGATED_TOOLS)


# ---- create_rbd's lean response ----------------------------------------------------

def test_create_rbd_returns_node_ids_not_the_graph(env):
    out = _create(env)
    assert "graph" not in out
    assert {"id": "p2", "type": "component", "label": "Pump B"} in out["nodes"]
    assert {n["id"] for n in out["nodes"]} == {"input", "ctl", "p1", "p2", "output"}
    full = _create(env, include_graph=True)
    assert {n["id"] for n in full["graph"]["nodes"]} == {"input", "ctl", "p1", "p2", "output"}


# ---- add_node placements --------------------------------------------------------------

def test_add_node_parallel_to(env):
    rid = _create(env)["id"]
    out = _ok(_edit(env, rid, {"op": "add_node", "parallel_to": "p2",
                               "node": {"id": "p3", "type": "component", "label": "Pump C", "model": _w(900, 1.4)}}))
    assert out["applied"] == ["added p3 parallel to p2"]
    assert _edges(env, rid) == GRAPH_EDGES | {("ctl", "p3"), ("p3", "output")}
    assert {"id": "p3", "type": "component", "label": "Pump C"} in out["nodes"]
    assert out["n_blocks"] == 4 and "graph" not in out


def test_add_node_between_after_before_and_unconnected(env):
    rid = _create(env, _chain("a", "b"))["id"]
    out = _ok(_edit(env, rid,
                    {"op": "add_node", "between": ["a", "b"], "node": {"id": "m", "type": "component", "model": _w()}},
                    {"op": "add_node", "after": "b", "node": {"id": "z", "type": "component", "model": _w()}},
                    {"op": "add_node", "before": "a", "node": {"id": "s", "type": "component", "model": _w()}},
                    {"op": "add_node", "node": {"id": "x", "type": "component", "model": _w()}},
                    {"op": "add_edge", "source": "m", "target": "x"},
                    {"op": "add_edge", "source": "x", "target": "b"}))
    assert out["applied"] == ["added m between a and b", "added z after b", "added s before a",
                              "added x (unconnected: add its edges)", "added edge m→x", "added edge x→b"]
    assert _edges(env, rid) == {("input", "s"), ("s", "a"), ("a", "m"), ("m", "b"), ("m", "x"), ("x", "b"),
                                ("b", "z"), ("z", "output")}


def test_after_moves_every_outgoing_edge(env):
    rid = _create(env)["id"]
    _ok(_edit(env, rid, {"op": "add_node", "after": "ctl",
                         "node": {"id": "f", "type": "component", "label": "Filter", "model": _w()}}))
    assert _edges(env, rid) == {("input", "ctl"), ("ctl", "f"), ("f", "p1"), ("f", "p2"),
                                ("p1", "output"), ("p2", "output")}


def test_add_node_refusals(env):
    rid = _create(env)["id"]
    comp = {"type": "component", "model": _w()}
    cases = [
        ({"op": "add_node", "node": {"id": "p1", **comp}}, "already in use"),
        ({"op": "add_node", "between": ["ctl", "output"], "node": {"id": "q", **comp}}, "no edge ctl→output"),
        ({"op": "add_node", "after": "p1", "before": "p2", "node": {"id": "q", **comp}}, "at most one placement"),
        ({"op": "add_node", "after": "nope", "node": {"id": "q", **comp}}, "no node 'nope'"),
        ({"op": "add_node", "after": "output", "node": {"id": "q", **comp}}, "after the output"),
        ({"op": "add_node", "node": {"id": "in2", "type": "input"}}, "one input"),
        ({"op": "add_node", "node": {"id": "q", "type": "component", "model": {"distribution_id": "nope",
                                                                               "params": []}}}, "unsupported"),
    ]
    before = _doc(env, rid)
    for op, needle in cases:
        msg = _err(_edit(env, rid, op))
        assert needle in msg and "ops[0]" in msg and "Nothing was saved" in msg, (op, msg)
    assert _doc(env, rid) == before
    # Ids are case-sensitive: P1 is a new node.
    _ok(_edit(env, rid, {"op": "add_node", "parallel_to": "p1", "node": {"id": "P1", **comp}}))


# ---- remove_node ---------------------------------------------------------------------

def test_remove_node_heals_a_series_gap(env):
    rid = _create(env, _chain("a", "b", "c"))["id"]
    out = _ok(_edit(env, rid, {"op": "remove_node", "id": "b"}))
    assert out["applied"] == ["removed b; joined a→c"]
    assert _edges(env, rid) == {("input", "a"), ("a", "c"), ("c", "output")}


def test_remove_one_of_two_parallel_blocks_adds_no_bypass(env):
    rid = _create(env)["id"]
    out = _ok(_edit(env, rid, {"op": "remove_node", "id": "p2"}))
    assert out["applied"] == ["removed p2"]
    assert _edges(env, rid) == {("input", "ctl"), ("ctl", "p1"), ("p1", "output")}


def test_remove_a_series_block_feeding_a_parallel_pair_rejoins_all(env):
    rid = _create(env)["id"]
    out = _ok(_edit(env, rid, {"op": "remove_node", "id": "ctl"}))
    assert out["applied"] == ["removed ctl; joined input→p1, input→p2"]
    assert _edges(env, rid) == {("input", "p1"), ("input", "p2"), ("p1", "output"), ("p2", "output")}


def test_remove_node_without_reconnect_and_io_refusal(env):
    rid = _create(env, _chain("a", "b", "c"))["id"]
    msg = _err(_edit(env, rid, {"op": "remove_node", "id": "b", "reconnect": "none"}))
    assert "Nothing was saved" in msg and "invalid" in msg
    msg = _err(_edit(env, rid, {"op": "remove_node", "id": "input"}))
    assert "can't be removed" in msg
    # reconnect=none followed by the agent's own edge is fine.
    out = _ok(_edit(env, rid, {"op": "remove_node", "id": "b", "reconnect": "none"},
                    {"op": "add_edge", "source": "a", "target": "c"}))
    assert out["applied"] == ["removed b", "added edge a→c"]


# ---- update_node ----------------------------------------------------------------------

def test_update_node_merges_only_given_fields(env):
    rid = _create(env)["id"]
    out = _ok(_edit(env, rid, {"op": "update_node", "id": "p1", "label": "Pump A (new)"}))
    assert out["applied"] == ["updated label of p1"]
    data = _node(env, rid, "p1")["data"]
    assert data["label"] == "Pump A (new)"
    assert data["model"]["params"][0] == {"name": "alpha", "value": 900.0}  # untouched


def test_update_node_ids_bulk(env):
    rid = _create(env)["id"]
    out = _ok(_edit(env, rid, {"op": "update_node", "ids": ["p1", "p2"], "model": _w(1200, 1.6)}))
    assert out["applied"] == ["updated model of p1, p2"]
    for nid in ("p1", "p2"):
        m = _node(env, rid, nid)["data"]["model"]
        assert m["distribution_id"] == "weibull" and m["params"][0]["value"] == 1200.0
        assert not m.get("placeholder")
    assert out["placeholders"] == []  # Pump B's guessed model was replaced
    assert _node(env, rid, "p1")["data"]["label"] == "Pump A"


def test_update_node_refusals(env):
    rid = _create(env)["id"]
    # The type can't change: remove and re-add instead.
    assert _edit(env, rid, {"op": "update_node", "id": "p1", "type": "parallel"}).is_error
    assert "no spares" in _err(_edit(env, rid, {"op": "update_node", "id": "p1", "spares": 1}))
    assert "exactly one of id or ids" in _err(_edit(env, rid, {"op": "update_node", "id": "p1", "ids": ["p2"],
                                                               "label": "x"}))
    assert "nothing to update" in _err(_edit(env, rid, {"op": "update_node", "id": "p1"}))
    assert "no node 'P9'" in _err(_edit(env, rid, {"op": "update_node", "ids": ["p1", "P9"], "label": "x"}))


# ---- edges ------------------------------------------------------------------------------

def test_edge_ops_and_their_errors(env):
    rid = _create(env)["id"]
    for op, needle in (({"op": "add_edge", "source": "ctl", "target": "nope"}, "no node 'nope'"),
                       ({"op": "add_edge", "source": "ctl", "target": "p1"}, "already exists"),
                       ({"op": "add_edge", "source": "p1", "target": "p1"}, "itself"),
                       ({"op": "remove_edge", "source": "p1", "target": "p2"}, "no edge p1→p2")):
        assert needle in _err(_edit(env, rid, op)), op
    out = _ok(_edit(env, rid, {"op": "remove_edge", "source": "ctl", "target": "p2"},
                    {"op": "add_edge", "source": "input", "target": "p2"}))
    assert out["applied"] == ["removed edge ctl→p2", "added edge input→p2"]
    assert ("input", "p2") in _edges(env, rid) and ("ctl", "p2") not in _edges(env, rid)


def test_removing_the_only_path_is_refused(env):
    rid = _create(env)["id"]
    before = _doc(env, rid)
    msg = _err(_edit(env, rid, {"op": "remove_edge", "source": "input", "target": "ctl"}))
    assert "Nothing was saved" in msg and "invalid" in msg
    assert _doc(env, rid) == before


# ---- set ----------------------------------------------------------------------------------

def test_set_name_unit_and_repairable(env):
    rid = _create(env)["id"]
    out = _ok(_edit(env, rid, {"op": "set", "name": "Skid v2", "unit": "Days"}))
    assert out["name"] == "Skid v2" and out["unit"] == "Days"
    assert _doc(env, rid)["name"] == "Skid v2"
    # Repairable needs repair models: the app's own validation says so, and nothing is saved.
    msg = _err(_edit(env, rid, {"op": "set", "repairable": True}))
    assert "repair-time distribution" in msg and not _doc(env, rid)["graph"].get("repairable")
    repair = {"distribution_id": "lognormal", "params": [{"name": "mu", "value": 1}, {"name": "sigma", "value": 0.5}]}
    out = _ok(_edit(env, rid, {"op": "set", "repairable": True},
                    {"op": "update_node", "ids": ["ctl", "p1", "p2"], "repair": repair}))
    assert out["repairable"] is True


# ---- atomicity, dry run, concurrency, ownership ---------------------------------------------

def test_a_failing_op_saves_nothing(env):
    rid = _create(env)["id"]
    before = _doc(env, rid)
    msg = _err(_edit(env, rid, {"op": "update_node", "id": "p1", "label": "Changed"},
                     {"op": "add_node", "parallel_to": "p2", "node": {"id": "p3", "type": "component", "model": _w()}},
                     {"op": "remove_node", "id": "ghost"}))
    assert "ops[2] (remove_node ghost)" in msg and "no node 'ghost'" in msg
    assert _doc(env, rid) == before


def test_dry_run_reports_without_saving(env):
    rid = _create(env)["id"]
    before = _doc(env, rid)
    out = _ok(_edit(env, rid, {"op": "remove_node", "id": "p2"}, dry_run=True))
    assert out["dry_run"] is True and out["saved"] is False
    assert out["applied"] == ["removed p2"] and "p2" not in {n["id"] for n in out["nodes"]}
    assert _doc(env, rid) == before
    # A dry run still refuses an invalid result.
    assert "invalid" in _err(_edit(env, rid, {"op": "remove_edge", "source": "input", "target": "ctl"},
                                   dry_run=True))


def test_if_updated_at_refuses_a_stale_edit(env):
    created = _create(env)
    rid, seen = created["id"], created["updated_at"]
    # Someone saves in the web app.
    env.db.rbds.update_one({"_id": rid}, {"$set": {"updated_at": datetime(2030, 1, 2, tzinfo=timezone.utc)}})
    msg = _err(_edit(env, rid, {"op": "update_node", "id": "p1", "label": "x"}, if_updated_at=seen))
    assert "has changed since" in msg and "2030-01-02" in msg
    assert _node(env, rid, "p1")["data"]["label"] == "Pump A"
    current = _ok(_call(env.token[A], "get_rbd", {"rbd_id": rid}))["updated_at"]
    out = _ok(_edit(env, rid, {"op": "update_node", "id": "p1", "label": "x"}, if_updated_at=current))
    assert out["updated_at"] != current
    # The returned updated_at chains into the next edit.
    _ok(_edit(env, rid, {"op": "update_node", "id": "p1", "label": "y"}, if_updated_at=out["updated_at"]))


def test_only_the_owner_can_edit(env):
    rid = _create(env)["id"]
    assert "not found" in _err(_edit(env, rid, {"op": "update_node", "id": "p1", "label": "x"},
                                     token=env.token[B])).lower()
    assert "not found" in _err(_call(env.token[B], "clone_rbd", {"rbd_id": rid})).lower()


# ---- samples and clone_rbd ------------------------------------------------------------------

@pytest.fixture()
def sample(env):
    from backend import config
    from backend.services import rbd_graph, rbds as rbds_service

    graph = rbd_graph.normalize_graph({**GRAPH, "unit": "Hours"})
    rbd = rbds_service.save_rbd(env.db, "Sample skid", graph, config.SAMPLE_OWNER)
    return rbd.id


def test_samples_are_read_only_and_clone_into_the_workspace(env, sample):
    msg = _err(_edit(env, sample, {"op": "update_node", "id": "p1", "label": "x"}))
    assert "read-only" in msg and "clone_rbd" in msg
    out = _ok(_call(env.token[A], "clone_rbd", {"rbd_id": sample}))
    assert out["id"] != sample and out["name"] == "Sample skid (copy)" and out["cloned_from"] == sample
    assert out["is_sample"] is False and out["placeholders"] == ["Pump B"]
    assert {n["id"] for n in out["nodes"]} == {"input", "ctl", "p1", "p2", "output"} and "graph" not in out
    doc = _doc(env, out["id"])
    assert doc["owner_id"] == A and doc["graph"] == _doc(env, sample)["graph"]
    # The copy is the user's to edit; the sample is untouched.
    _ok(_edit(env, out["id"], {"op": "update_node", "id": "p1", "label": "Mine"}))
    assert _node(env, sample, "p1")["data"]["label"] == "Pump A"
    named = _ok(_call(env.token[A], "clone_rbd", {"rbd_id": sample, "name": "Variant B"}))
    assert named["name"] == "Variant B"


def test_clone_copies_the_graph_only(env):
    from backend.services import public_links, rbds as rbds_service

    rid = _create(env)["id"]
    rbds_service.store_availability(env.db, rid, "some-key", {"steady_state_availability": 0.99}, A)
    public_links.create_link(env.db, "rbds", rid, {"uid": A})
    out = _ok(_call(env.token[A], "clone_rbd", {"rbd_id": rid}))
    doc = _doc(env, out["id"])
    assert "availability_cache" not in doc
    assert env.db.public_links.count_documents({"artifact_id": out["id"]}) == 0


def test_clone_counts_against_the_storage_cap(env, sample, monkeypatch):
    from backend.services import billing as billing_service

    monkeypatch.setattr(billing_service, "would_exceed_cap", lambda db, uid, kind: kind == "rbds")
    monkeypatch.setattr(billing_service, "account", lambda db, uid: {"active_plan": "free"})
    msg = _err(_call(env.token[A], "clone_rbd", {"rbd_id": sample}))
    assert "limit of" in msg and "saved RBDs" in msg
    assert env.db.rbds.count_documents({"owner_id": A}) == 0


# ---- common-cause groups --------------------------------------------------------------------

def _stage(n):
    return {"label": "Pumps", "common_cause_beta": 0.1, "components": [
        {"label": f"Pump {i + 1}", "distribution": "weibull",
         "params": [{"name": "alpha", "value": 900}, {"name": "beta", "value": 1.4}]} for i in range(n)]}


def test_removing_a_node_cleans_up_its_common_cause_group(env):
    out = _ok(_call(env.token[A], "create_rbd", {"name": "Pumps", "stages": [_stage(3)]}))
    rid = out["id"]
    ids = [n["id"] for n in out["nodes"] if n["type"] == "component"]
    gid = _doc(env, rid)["graph"]["ccf_groups"][0]["id"]
    first = _ok(_edit(env, rid, {"op": "remove_node", "id": ids[0]}))
    assert first["applied"] == [f"removed {ids[0]}; left common-cause group {gid}"]
    assert _doc(env, rid)["graph"]["ccf_groups"][0]["members"] == ids[1:]
    second = _ok(_edit(env, rid, {"op": "remove_node", "id": ids[1]}))
    assert second["applied"] == [f"removed {ids[1]}; dropped common-cause group {gid} (under 2 members)"]
    assert not _doc(env, rid)["graph"].get("ccf_groups")


def test_add_and_remove_ccf(env):
    rid = _create(env)["id"]
    out = _ok(_edit(env, rid, {"op": "add_ccf", "members": ["p1", "p2"], "beta": 0.05}))
    assert out["applied"] == ["added common-cause group ccf-1 (p1, p2; beta 0.05)"]
    assert _doc(env, rid)["graph"]["ccf_groups"] == [{"id": "ccf-1", "members": ["p1", "p2"], "beta": 0.05}]
    res = _ok(_call(env.token[A], "analyze_rbd", {"rbd_id": rid}))
    assert res["ccf"]
    for op, needle in (({"op": "add_ccf", "members": ["p1", "ctl"], "beta": 0.1}, "already in common-cause"),
                       ({"op": "add_ccf", "members": ["ctl", "input"], "beta": 0.1}, "isn't a component"),
                       ({"op": "add_ccf", "members": ["ctl", "p2"], "beta": 1.5}, "out of range"),
                       ({"op": "remove_ccf", "id": "ccf-9"}, "no common-cause group 'ccf-9'")):
        assert needle in _err(_edit(env, rid, op)), op
    out = _ok(_edit(env, rid, {"op": "remove_ccf", "id": "ccf-1"}))
    assert out["applied"] == ["removed common-cause group ccf-1"]
    assert not _doc(env, rid)["graph"].get("ccf_groups")


# ---- the result is the diagram create_rbd would build ----------------------------------------

def test_edited_diagram_matches_a_create_rbd_equivalent(env):
    from backend.services import rbds as rbds_service

    rid = _create(env)["id"]
    _ok(_edit(env, rid,
              {"op": "add_node", "parallel_to": "p2",
               "node": {"id": "p3", "type": "component", "label": "Pump C", "model": _w(900, 1.4)}},
              {"op": "update_node", "id": "ctl", "model": _w(2500, 2.2)},
              {"op": "add_node", "before": "ctl",
               "node": {"id": "v", "type": "component", "label": "Valve", "model": _w(4000, 1.1)}}))
    nodes = [{**n, "model": _w(2500, 2.2)} if n["id"] == "ctl" else n for n in GRAPH["nodes"]] + [
        {"id": "p3", "type": "component", "label": "Pump C", "model": _w(900, 1.4)},
        {"id": "v", "type": "component", "label": "Valve", "model": _w(4000, 1.1)}]
    edges = [e for e in GRAPH["edges"] if e != {"source": "input", "target": "ctl"}] + [
        {"source": "ctl", "target": "p3"}, {"source": "p3", "target": "output"},
        {"source": "input", "target": "v"}, {"source": "v", "target": "ctl"}]
    ref = _create(env, {"nodes": nodes, "edges": edges}, name="Built directly")["id"]

    edited, built = _doc(env, rid)["graph"], _doc(env, ref)["graph"]
    assert rbds_service.canonical_analysis_graph(edited) == rbds_service.canonical_analysis_graph(built)
    a = _ok(_call(env.token[A], "analyze_rbd", {"rbd_id": rid, "times": [200, 800]}))
    b = _ok(_call(env.token[A], "analyze_rbd", {"rbd_id": ref, "times": [200, 800]}))
    assert a["mttf"] == pytest.approx(b["mttf"]) and a["reliability_at"] == b["reliability_at"]
    # Same layout create_rbd gives the same diagram.
    pos = lambda g: {n["id"]: n["position"] for n in g["nodes"]}  # noqa: E731
    assert pos(edited) == pos(built)


def test_layout_reruns_on_rewiring_and_is_kept_otherwise(env):
    rid = _create(env)["id"]
    # A hand arrangement from the builder survives a label/model-only batch.
    env.db.rbds.update_one({"_id": rid, "graph.nodes.id": "p1"}, {"$set": {"graph.nodes.$.position": {"x": 7, "y": 9}}})
    _ok(_edit(env, rid, {"op": "update_node", "id": "p1", "label": "Renamed"}))
    assert _node(env, rid, "p1")["position"] == {"x": 7, "y": 9}
    # Rewiring re-lays out: every node placed, none on top of another.
    _ok(_edit(env, rid, {"op": "add_node", "between": ["input", "ctl"],
                         "node": {"id": "f", "type": "component", "model": _w()}}))
    nodes = _doc(env, rid)["graph"]["nodes"]
    spots = [(n["position"]["x"], n["position"]["y"]) for n in nodes]
    assert len(set(spots)) == len(nodes) == 6
    assert _node(env, rid, "input")["position"]["x"] < _node(env, rid, "f")["position"]["x"] \
        < _node(env, rid, "ctl")["position"]["x"] < _node(env, rid, "p1")["position"]["x"]


# ---- saved results and sub-system references ---------------------------------------------

REPAIR = {"distribution_id": "lognormal", "params": [{"name": "mu", "value": 1.0}, {"name": "sigma", "value": 0.3}]}


def test_saved_availability_goes_stale_after_an_edit(env, monkeypatch):
    from backend.services import billing as billing_service

    nodes = [n if n["type"] in ("input", "output") else {**n, "repair": REPAIR} for n in GRAPH["nodes"]]
    rid = _create(env, {"nodes": nodes, "edges": GRAPH["edges"]}, repairable=True)["id"]
    monkeypatch.setattr(billing_service, "premium_compute_allowed", lambda db, user: True)
    assert _ok(_call(env.token[A], "analyze_rbd", {"rbd_id": rid}))["available"]
    monkeypatch.setattr(billing_service, "premium_compute_allowed", lambda db, user: False)
    assert _ok(_call(env.token[A], "analyze_rbd", {"rbd_id": rid}))["cached"] is True

    # A dry run changes nothing; a real edit makes the saved result stale.
    _ok(_edit(env, rid, {"op": "update_node", "id": "p1", "model": _w(500, 1.2)}, dry_run=True))
    assert _ok(_call(env.token[A], "analyze_rbd", {"rbd_id": rid}))["available"]
    _ok(_edit(env, rid, {"op": "update_node", "id": "p1", "model": _w(500, 1.2)}))
    out = _ok(_call(env.token[A], "analyze_rbd", {"rbd_id": rid}))
    assert out["available"] is False and out["code"] == "pro_required"


def test_a_subsystem_reference_follows_the_edit(env):
    inner = _create(env, _chain("m"), name="Inner")["id"]
    outer = _create(env, {"nodes": [
        {"id": "input", "type": "input"}, {"id": "sub", "type": "subsystem", "label": "Drive", "subsystem_rbd_id": inner},
        {"id": "output", "type": "output"}],
        "edges": [{"source": "input", "target": "sub"}, {"source": "sub", "target": "output"}]}, name="Outer")["id"]
    before = _ok(_call(env.token[A], "analyze_rbd", {"rbd_id": outer}))["mttf"]
    _ok(_edit(env, inner, {"op": "add_node", "after": "m",
                           "node": {"id": "g", "type": "component", "label": "Gearbox", "model": _w()}}))
    after = _ok(_call(env.token[A], "analyze_rbd", {"rbd_id": outer}))["mttf"]
    assert after < before  # one more block in series inside the sub-system
    msg = _err(_edit(env, inner, {"op": "add_node", "parallel_to": "m",
                                  "node": {"id": "me", "type": "subsystem", "subsystem_rbd_id": inner}}))
    assert "embed itself" in msg


# ---- token efficiency -----------------------------------------------------------------------

def test_edit_response_is_much_smaller_than_get_rbd(env):
    ids = [f"b{i}" for i in range(20)]
    rid = _create(env, _chain(*ids))["id"]
    out = _ok(_edit(env, rid, {"op": "update_node", "id": "b3", "label": "Bearing 3"}))
    full = _ok(_call(env.token[A], "get_rbd", {"rbd_id": rid}))
    small, big = len(json.dumps(out)), len(json.dumps(full))
    assert small < big / 2, (small, big, out)
    assert "graph" in _ok(_edit(env, rid, {"op": "update_node", "id": "b3", "label": "B3"}, include_graph=True))


def test_edit_reports_only_the_warnings_it_introduced(env):
    rid = _create(env, {"nodes": [{"id": "input", "type": "input"},
                                  {"id": "a", "type": "component", "label": "Pump A", "model": _w()},
                                  {"id": "output", "type": "output"}],
                        "edges": [{"source": "input", "target": "a"}, {"source": "a", "target": "output"}]})["id"]
    out = _ok(_edit(env, rid, {"op": "add_node", "after": "a",
                               "node": {"id": "b", "type": "component", "label": "Pump B (standby)", "model": _w()}}))
    assert any("Pump A" in w and "Pump B (standby)" in w for w in out["warnings"])
    again = _ok(_edit(env, rid, {"op": "update_node", "id": "a", "model": _w(1100, 2)}))
    assert again["warnings"] == [] and again["warnings_unchanged"] == 1
