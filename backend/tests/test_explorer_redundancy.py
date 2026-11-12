"""Redundancy sets marked in the Explorer (Nov 2026): positions on a parent that back each other up
(any k of n, or duty and standby) are recorded as events, shown on the tree, and wired by the RBDs
built from the tree as redundancy, never in series.

The W04 walkthrough's station (two pump sets, each a pump and its motor, one duty and one standby,
and a discharge valve) is built from the tree, its sub-systems expanded, and its availability
checked against the diagram the walkthrough wired by hand (the two trains in parallel, each running
half the time)."""

import math

import mongomock
import pytest

from backend.maintenance import position_models as pm
from backend.maintenance import rbd_derive
from backend.maintenance.service import PROJECTORS, Invalid, Maintenance
from backend.maintenance.store import GraphStore
from backend.services import rbd_analysis as ra
from backend.services import rbd_flatten
from backend.services import rbd_missions as rm
from backend.services.rbd_graph import normalize_graph

ORG = "org-redundancy"
OWNERS = [ORG, "__samples__"]


def _exp(rate):
    return {"distribution_id": "exponential", "params": [{"name": "failure_rate", "value": rate}]}


@pytest.fixture()
def m():
    return Maintenance(GraphStore(":memory:", PROJECTORS), ORG, "tester")


@pytest.fixture()
def db():
    return mongomock.MongoClient()["explorer_redundancy"]


def _same(m):
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before


# ---- the events -------------------------------------------------------------------------------

def test_a_standby_set_keeps_its_switching_and_replays_to_the_same_graph(m):
    st = m.create_position("Station")["id"]
    a = m.create_position("Pump A", parent_id=st)["id"]
    b = m.create_position("Pump B", parent_id=st)["id"]
    c = m.create_position("Pump C", parent_id=st)["id"]
    g = m.create_group("Pumps", [a, b], mode="standby", standby="cold", start_probability=0.98)
    assert (g["start_probability"], g["dormancy"]) == (0.98, None)
    types = sorted(e["type"] for e in m.s.events(ORG) if e["type"].startswith("group."))
    assert types == ["group.created", "group.member_added", "group.member_added", "group.standby_set"]
    g = m.update_group(g["id"], standby="warm", dormancy=0.2, add=[c], k=2)
    assert (g["standby"], g["dormancy"], g["n"], g["k"]) == ("warm", 0.2, 3, 2)
    g = m.update_group(g["id"], start_probability="")  # '' clears it
    assert g["start_probability"] is None and g["dormancy"] == 0.2
    events = m.s.event_count(ORG)
    m.update_group(g["id"], dormancy=0.2)  # nothing changes: nothing written
    assert m.s.event_count(ORG) == events
    _same(m)
    for bad in (0, 1.5, "lots"):
        with pytest.raises(Invalid, match="start"):
            m.update_group(g["id"], start_probability=bad)
    with pytest.raises(Invalid, match="ages"):
        m.update_group(g["id"], dormancy=-0.1)


def test_a_position_is_in_one_set_and_a_set_keeps_two_members(m):
    st = m.create_position("Station")["id"]
    a, b, c = (m.create_position(n, parent_id=st)["id"] for n in ("Pump A", "Pump B", "Pump C"))
    g = m.create_group("Pumps", [a, b])
    with pytest.raises(Invalid, match="already in the redundancy set Pumps"):
        m.create_group("Again", [b, c])
    with pytest.raises(Invalid, match="at least two"):
        m.update_group(g["id"], remove=[a])
    m.retire_group(g["id"])
    assert m.create_group("Again", [b, c])["n"] == 2  # a retired set holds nobody


def test_the_tree_and_the_pane_show_the_sets(m):
    st = m.create_position("Station")["id"]
    a, b, v = (m.create_position(n, parent_id=st)["id"] for n in ("Pump A", "Pump B", "Valve"))
    g = m.create_group("Pumps", [a, b], mode="standby")
    rows = {r["id"]: r for r in m.tree_rows()["positions"]}
    assert rows[a]["redundancy"] == {"id": g["id"], "name": "Pumps", "k": 1, "n": 2, "mode": "standby",
                                     "standby": "cold"}
    assert "redundancy" not in rows[v] and "redundancy" not in rows[st]
    inside = m.redundancy_inside(st)
    assert [(c["name"], c["set_id"]) for c in inside["children"]] == [
        ("Pump A", g["id"]), ("Pump B", g["id"]), ("Valve", None)]
    assert [s["name"] for s in inside["sets"]] == ["Pumps"] and inside["sets"][0]["outside"] == []
    m.retire_group(g["id"])
    assert "redundancy" not in {r["id"]: r for r in m.tree_rows()["positions"]}[a]
    assert m.redundancy_inside(st)["sets"] == []


# ---- the RBD built from the tree --------------------------------------------------------------

def _station(m, pumps=("Pump A", "Pump B")):
    st = m.create_position("Station")["id"]
    ids = [m.create_position(n, parent_id=st)["id"] for n in pumps]
    valve = m.create_position("Valve", parent_id=st)["id"]
    return st, ids, valve


def _models(rates):
    """block_model giving each position the exponential rate named for it."""
    return lambda c: ({"model": _exp(rates[c["name"]])}, None)


def test_identical_standby_pumps_build_one_standby_block_with_their_switching(m):
    st, (a, b), _ = _station(m)
    m.create_group("Pumps", [a, b], mode="standby", standby="cold", start_probability=0.9)
    lam, valve, t = 0.001, 0.0002, 500.0
    built = rbd_derive.build(m, st, block_model=_models({"Pump A": lam, "Pump B": lam, "Valve": valve}),
                             unit="hours")
    kinds = sorted(n["type"] for n in built["graph"]["nodes"])
    assert kinds == ["component", "input", "output", "standby"]
    sb = next(n for n in built["graph"]["nodes"] if n["type"] == "standby")
    assert (sb["k"], sb["spares"], sb["dormancy"], sb["startProb"]) == (1, 1, 0.0, 0.9)
    assert built["redundancy"][0]["drawn"] == "standby"
    assert not any("in series)." in n and "every block" in n for n in built["notes"])
    graph = normalize_graph(built["graph"])
    got = ra.analyze(graph, at_times=[t])
    # Cold standby with a 90% start, then the valve: e^-λt (1 + p λt) · e^-μt, by hand.
    want = math.exp(-lam * t) * (1 + 0.9 * lam * t) * math.exp(-valve * t)
    value = got["at"]["sf"][0]
    assert value == pytest.approx(want, rel=2e-3)


def test_an_active_set_is_k_of_n_and_unlike_pumps_on_standby_take_turns(m):
    st, (a, b, c), _ = _station(m, ("Pump A", "Pump B", "Pump C"))
    m.create_group("Pumps", [a, b, c], k=2)
    built = rbd_derive.build(m, st, block_model=_models({"Pump A": 1e-3, "Pump B": 1e-3, "Pump C": 1e-3,
                                                         "Valve": 1e-4}), unit="hours")
    vote = next(n for n in built["graph"]["nodes"] if n["type"] == "knode")
    assert (vote["n"], vote["k"]) == (2, 3)
    assert not rm.all_in_series(normalize_graph(built["graph"]))

    st2, (d, e), _ = _station(m, ("Duty pump", "Standby pump"))
    m.create_group("Duty / standby", [d, e], mode="standby")
    built = rbd_derive.build(m, st2, block_model=_models({"Duty pump": 1e-3, "Standby pump": 2e-3, "Valve": 1e-4}),
                             unit="hours")
    pumps = [n for n in built["graph"]["nodes"] if n.get("label", "").endswith("pump")]
    assert [n["data"]["duty"] for n in pumps] == [0.5, 0.5]
    assert any("different models" in n and "50%" in n for n in built["notes"])


def _subsystems(m, db):
    """W04's station: pump sets (a pump and a motor each), duty and standby, and a valve."""
    st = m.create_position("Wallaby Gully booster pump station")["id"]
    sa = m.create_position("Pump set A (duty)", parent_id=st)["id"]
    sb = m.create_position("Pump set B (standby)", parent_id=st)["id"]
    m.create_position("Discharge valve", parent_id=st)
    for s, x in ((sa, "A"), (sb, "B")):
        m.create_position(f"Pump {x}", parent_id=s)
        m.create_position(f"Motor {x}", parent_id=s)
    return st, sa, sb


RATES = {"Pump": 1 / 13500, "Motor": 1 / 40000, "Discharge": 1 / 90000}
REPAIR = {"Pump": 1 / 24, "Motor": 1 / 12, "Discharge": 1 / 8}


def _set_models(graph):
    """Each block's life and repair by its name, as typed into both diagrams (exponential)."""
    for n in graph["nodes"]:
        if n["type"] == "component":
            kind = n["data"]["label"].split()[0]
            n["data"]["model"] = normalize_graph({"nodes": [{"id": "x", "type": "component", "label": "x",
                                                             "model": _exp(RATES[kind])}], "edges": []}
                                                 )["nodes"][0]["data"]["model"]
            n["data"]["repair"] = {"source": "params", "distribution_id": "exponential",
                                   "params": [{"name": "failure_rate", "value": REPAIR[kind]}]}
    graph["repairable"] = True
    return graph


def _hand_wired():
    """What W04 wired by hand (steps 22-27): the two trains in parallel, each pump and motor
    running half the time, then the valve."""
    def comp(i, label, duty=None):
        return {"id": i, "type": "component", "label": label, "model": _exp(1), **({"duty": duty} if duty else {})}
    nodes = [{"id": "in", "type": "input"}, {"id": "out", "type": "output"},
             comp("pa", "Pump A", 0.5), comp("ma", "Motor A", 0.5), comp("pb", "Pump B", 0.5),
             comp("mb", "Motor B", 0.5), comp("v", "Discharge valve")]
    edges = [("in", "pa"), ("pa", "ma"), ("in", "pb"), ("pb", "mb"), ("ma", "v"), ("mb", "v"), ("v", "out")]
    return normalize_graph({"unit": "Hours", "nodes": nodes,
                            "edges": [{"source": s, "target": t} for s, t in edges]})


def test_w04_duty_and_standby_pump_sets_build_as_standby_and_match_the_hand_wired_station(m, db):
    st, sa, sb = _subsystems(m, db)
    m.create_group("Pump sets", [sa, sb], mode="standby", standby="cold")
    link = pm.build_rbd(m, db, OWNERS, set(), st, ORG)
    assert not any("in series" in n and "Nothing inside" in n and "redundancy set" not in n for n in link["notes"])
    graph = db.rbds.find_one({"_id": link["model_id"]})["graph"]
    vote = next(n for n in graph["nodes"] if n["type"] == "knode")
    assert (vote["data"]["n"], vote["data"]["k"]) == (1, 2)
    sets = [n for n in graph["nodes"] if n["type"] == "subsystem"]
    assert sorted((n["data"]["label"], n["data"]["duty"]) for n in sets) == [
        ("Pump set A (duty)", 0.5), ("Pump set B (standby)", 0.5)]
    # Expand the sub-systems (the RBD's Expand), make it repairable and give the blocks their figures.
    flat = rbd_flatten.expand_saved(db, graph, OWNERS)["graph"]
    duties = {n["data"]["label"]: n["data"].get("duty") for n in flat["nodes"] if n["type"] == "component"}
    assert duties == {"Pump A": 0.5, "Motor A": 0.5, "Pump B": 0.5, "Motor B": 0.5, "Discharge valve": None}
    built = ra.analyze_availability(_set_models(flat))
    by_hand = ra.analyze_availability(_set_models(_hand_wired()))
    assert built["steady_state_availability"] == pytest.approx(by_hand["steady_state_availability"], rel=1e-9)
    # In series (what the tree built before) it would be lower.
    series = _set_models(_hand_wired())
    series["edges"] = [{"source": s, "target": t} for s, t in
                       (("in", "pa"), ("pa", "ma"), ("ma", "pb"), ("pb", "mb"), ("mb", "v"), ("v", "out"))]
    for n in series["nodes"]:
        n["data"].pop("duty", None)
    assert ra.analyze_availability(series)["steady_state_availability"] < built["steady_state_availability"]


def test_a_mission_built_from_a_tree_with_a_set_is_not_in_series(m, db):
    st, sa, sb = _subsystems(m, db)
    m.create_group("Pump sets", [sa, sb], mode="standby")
    made = pm.build_mission_rbd(m, db, OWNERS, set(), st, ORG, "Summer")
    assert made["built_from"] == "tree" and made["series_warning"] is None
    graph = db.rbds.find_one({"_id": made["rbd"]["id"]})["graph"]
    assert "built_in_series" not in graph["mission_of"]


def test_a_rebuild_rewires_a_diagram_still_in_series_once_the_set_is_marked(m, db):
    st, (a, b), _ = _station(m)
    link = pm.build_rbd(m, db, OWNERS, set(), st, ORG)
    g = db.rbds.find_one({"_id": link["model_id"]})["graph"]
    assert rm.all_in_series(g)
    # Something set on a block survives the rewiring.
    for n in g["nodes"]:
        if n["type"] == "component" and n["data"]["label"] == "Valve":
            n["data"]["costs"] = {"repair": 120}
    db.rbds.update_one({"_id": link["model_id"]}, {"$set": {"graph": g}})
    m.create_group("Pumps", [a, b])
    again = pm.build_rbd(m, db, OWNERS, set(), st, ORG, replace_link_id=link["id"])
    assert again["model_id"] == link["model_id"] and again["notes"][0].startswith("Rewired from the redundancy sets")
    g = db.rbds.find_one({"_id": link["model_id"]})["graph"]
    assert not rm.all_in_series(g) and any(n["type"] == "knode" for n in g["nodes"])
    valve = next(n for n in g["nodes"] if n["type"] == "component" and n["data"]["label"] == "Valve")
    assert valve["data"]["costs"] == {"repair": 120}
    # A diagram rewired by hand is left as it is.
    m.retire_group(m.groups_of(a)[0]["id"])
    m.create_group("Pumps again", [a, b], mode="standby", standby="hot")
    third = pm.build_rbd(m, db, OWNERS, set(), st, ORG, replace_link_id=again["id"])
    assert not any(n.startswith("Rewired") for n in third["notes"])


def test_subsystem_runs_share_passes_to_the_blocks_inside():
    sub = {"unit": "Hours", "nodes": [{"id": "i", "type": "input"}, {"id": "o", "type": "output"},
                                      {"id": "p", "type": "component", "data": {"label": "P", "duty": 0.5}},
                                      {"id": "q", "type": "component", "data": {"label": "Q"}}],
           "edges": [{"source": "i", "target": "p"}, {"source": "p", "target": "q"}, {"source": "q", "target": "o"}]}
    top = {"unit": "Hours", "nodes": [{"id": "in", "type": "input"}, {"id": "out", "type": "output"},
                                      {"id": "s", "type": "subsystem", "data": {"label": "S", "rbd": {"id": "x"},
                                                                                 "duty": 0.5}}],
           "edges": [{"source": "in", "target": "s"}, {"source": "s", "target": "out"}]}
    flat, _ = rbd_flatten.expand(top, lambda _id: sub)
    assert {n["id"]: n["data"].get("duty") for n in flat["nodes"] if n["type"] == "component"} == {"p": 0.25,
                                                                                                    "q": 0.5}


# ---- over REST and the maintenance tool -------------------------------------------------------

@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config
    from backend import db as db_mod
    from backend.auth import get_current_user
    from backend.main import app
    from backend.routers import maintenance as router

    d = mongomock.MongoClient()["redundancy_rest"]
    monkeypatch.setattr(db_mod, "_db", d)
    monkeypatch.setattr(db_mod, "_simulated", True)
    monkeypatch.setattr(router, "_store", GraphStore(":memory:", PROJECTORS))
    monkeypatch.setattr(config, "MAINTENANCE_ENABLED", True)
    monkeypatch.setattr(config, "MAINTENANCE_EMAILS", {"a@x.com"})
    app.dependency_overrides[get_current_user] = lambda: {
        "uid": ORG, "email": "a@x.com", "name": "A", "email_verified": True}
    yield TestClient(app)
    app.dependency_overrides.pop(get_current_user, None)


def _ok(r):
    assert r.status_code == 200, r.text
    return r.json()


def test_rest_marks_a_standby_set_and_reads_it_back(client):
    st = _ok(client.post("/api/maintenance/positions", json={"name": "Station"}))["id"]
    a, b = (_ok(client.post("/api/maintenance/positions", json={"name": n, "parent_id": st}))["id"]
            for n in ("Pump A", "Pump B"))
    g = _ok(client.post("/api/maintenance/groups", json={"name": "Pumps", "member_ids": [a, b], "mode": "standby",
                                                         "standby": "cold", "start_probability": 0.95}))
    assert g["start_probability"] == 0.95
    g = _ok(client.patch(f"/api/maintenance/groups/{g['id']}", json={"standby": "warm", "dormancy": 0.3}))
    assert (g["standby"], g["dormancy"]) == ("warm", 0.3)
    inside = _ok(client.get(f"/api/maintenance/positions/{st}/redundancy"))
    assert inside["sets"][0]["id"] == g["id"] and {c["set_id"] for c in inside["children"]} == {g["id"]}
    tree = _ok(client.get("/api/maintenance/tree"))
    assert {r["name"]: r.get("redundancy", {}).get("mode") for r in tree["positions"]} == {
        "Station": None, "Pump A": "standby", "Pump B": "standby"}
