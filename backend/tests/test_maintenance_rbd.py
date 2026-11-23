"""Reliafy Maintenance: connections, redundancy groups, impact, and the RBD
generated from the plant."""

import mongomock
import pytest

from backend.maintenance import rbd_derive
from backend.maintenance.service import PROJECTORS, Invalid, Maintenance
from backend.maintenance.store import GraphStore

ORG = "user-r"


@pytest.fixture()
def plant():
    """Pool system: tank -> (pump A | pump B, either will do) -> filter."""
    m = Maintenance(GraphStore(":memory:", PROJECTORS), ORG)
    pool = m.create_position("Pool system")["id"]
    tank = m.create_position("Balance tank", parent_id=pool)["id"]
    a = m.create_position("Pump A", parent_id=pool, position_class="Pool pump")["id"]
    b = m.create_position("Pump B", parent_id=pool, position_class="Pool pump")["id"]
    flt = m.create_position("Filter", parent_id=pool)["id"]
    for src, dst in ((tank, a), (tank, b), (a, flt), (b, flt)):
        m.connect(src, dst, "flow", "water")
    return m, {"pool": pool, "tank": tank, "a": a, "b": b, "filter": flt}


def test_connections_and_impact(plant):
    m, p = plant
    conn = m.connections(p["a"])
    assert [c["from"]["name"] for c in conn["upstream"]] == ["Balance tank"]
    assert [c["to"]["name"] for c in conn["downstream"]] == ["Filter"]
    with pytest.raises(Invalid):
        m.connect(p["a"], p["filter"], "flow")  # already connected
    tank = m.impact(p["tank"])
    assert {d["name"] for d in tank["downstream"]} == {"Pump A", "Pump B", "Filter"}
    m.create_group("Pool pumps", [p["a"], p["b"]], k=1, mode="standby")
    pump = m.impact(p["a"])
    assert pump["redundancy"] and "Pump B can carry it" in pump["summary"]


def test_groups_validate_and_duty(plant):
    m, p = plant
    with pytest.raises(Invalid):
        m.create_group("Too few", [p["a"]])
    with pytest.raises(Invalid):
        m.create_group("k too big", [p["a"], p["b"]], k=2)
    g = m.create_group("Pool pumps", [p["a"], p["b"]], mode="standby", standby="cold")
    assert g["n"] == 2 and g["k"] == 1
    assert m.set_duty(g["id"], p["b"])["duty"] == p["b"]
    with pytest.raises(Invalid):
        m.set_duty(g["id"], p["tank"])


def test_generated_rbd_wires_parallel_pumps_through_a_vote(plant):
    m, p = plant
    m.create_group("Pool pumps", [p["a"], p["b"]], k=1)
    built = rbd_derive.build(m, p["pool"])
    kinds = {n["type"] for n in built["graph"]["nodes"]}
    assert {"input", "output", "component", "knode"} <= kinds
    vote = next(n for n in built["graph"]["nodes"] if n["type"] == "knode")
    assert (vote["n"], vote["k"]) == (1, 2)
    edges = {(e["source"], e["target"]) for e in built["graph"]["edges"]}
    label = {n["id"]: n.get("label") for n in built["graph"]["nodes"]}
    named = {(label.get(s) or s, label.get(t) or t) for s, t in edges}
    assert ("Pump A", vote["label"]) in named and (vote["label"], "Filter") in named
    assert ("in", "Balance tank") in named and ("Filter", "out") in named
    assert set(built["placeholders"]) == {"Balance tank", "Pump A", "Pump B", "Filter"}


def test_unconnected_children_are_in_series_and_rbd_saves_and_solves():
    from backend.services.rbd_graph import normalize_graph

    m = Maintenance(GraphStore(":memory:", PROJECTORS), ORG)
    house = m.create_position("Hot water")["id"]
    for name in ("Element", "Thermostat", "Relief valve"):
        m.create_position(name, parent_id=house)
    built = rbd_derive.build(m, house)
    assert any("in series" in n for n in built["notes"])
    normalize_graph(built["graph"])  # a valid builder diagram
    db = mongomock.MongoClient()["rbd"]
    first = rbd_derive.save(m, db, house)
    again = rbd_derive.save(m, db, house, existing="rebuild")
    assert first["rbd_id"] == again["rbd_id"] and first["blocks"] == 3  # a rebuild updates the same RBD
    assert db.rbds.count_documents({}) == 1
    with pytest.raises(Invalid):
        rbd_derive.build(m, m.create_position("Empty")["id"])


def test_rebuild_matches_with_interfaces_and_groups(plant):
    m, p = plant
    g = m.create_group("Pool pumps", [p["a"], p["b"]])
    m.set_duty(g["id"], p["a"])
    i = m.connections(p["tank"])["downstream"][0]
    m.disconnect(i["id"])
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before


def test_the_generated_rbd_solves(plant):
    """RePyability analyses the generated diagram: a 1-of-2 pump pair beats one pump."""
    from backend.services import rbd_analysis
    from backend.services.rbd_graph import normalize_graph

    m, p = plant
    m.create_group("Pool pumps", [p["a"], p["b"]], k=1)
    graph = normalize_graph(rbd_derive.build(m, p["pool"])["graph"])
    result = rbd_analysis.analyze(graph, t_max=2000, at_times=[500])
    assert result.get("mttf") or result.get("summary") or result
    single = Maintenance(GraphStore(":memory:", PROJECTORS), ORG)
    sys_ = single.create_position("One pump system")["id"]
    for name in ("Balance tank", "Pump A", "Filter"):
        single.create_position(name, parent_id=sys_)
    chain = normalize_graph(rbd_derive.build(single, sys_)["graph"])
    alone = rbd_analysis.analyze(chain, t_max=2000, at_times=[500])
    assert result["mttf"] > alone["mttf"]


def _edited(db, rbd_id):
    """The user's edits on a made RBD: repairable, an 8 h repair on every block."""
    doc = db.rbds.find_one({"_id": rbd_id})
    graph = doc["graph"]
    graph["repairable"] = True
    for n in graph["nodes"]:
        if n["type"] == "component":
            n["repair"] = {"dist": "exponential", "params": {"lambda": 0.125}}
    db.rbds.update_one({"_id": rbd_id}, {"$set": {"graph": graph}})
    return graph


def test_making_an_rbd_again_never_overwrites_the_users_edits():
    m = Maintenance(GraphStore(":memory:", PROJECTORS), ORG)
    house = m.create_position("Hot water")["id"]
    for name in ("Element", "Thermostat"):
        m.create_position(name, parent_id=house)
    db = mongomock.MongoClient()["rbd"]
    first = rbd_derive.save(m, db, house)
    edited = _edited(db, first["rbd_id"])
    # Check first says one exists; making it again with no choice only opens it.
    assert rbd_derive.save(m, db, house, check=True)["existing"]["rbd_id"] == first["rbd_id"]
    again = rbd_derive.save(m, db, house)
    assert again["existing"] is True and again["rbd_id"] == first["rbd_id"]
    assert db.rbds.find_one({"_id": first["rbd_id"]})["graph"] == edited
    assert rbd_derive.save(m, db, house, existing="open")["rbd_id"] == first["rbd_id"]
    # A new copy sits beside it; the edited one is untouched and stays the position's.
    copy = rbd_derive.save(m, db, house, existing="copy")
    assert copy["rbd_id"] != first["rbd_id"] and copy["name"].endswith("(copy)")
    assert db.rbds.count_documents({}) == 2
    assert db.rbds.find_one({"_id": first["rbd_id"]})["graph"] == edited
    assert m.s.node(m.org, house)["rbd_id"] == first["rbd_id"]
    # Rebuild is the only way to replace it, and the edits go.
    rebuilt = rbd_derive.save(m, db, house, existing="rebuild")
    assert rebuilt["rbd_id"] == first["rbd_id"]
    graph = db.rbds.find_one({"_id": first["rbd_id"]})["graph"]
    assert not graph.get("repairable") and not any(n.get("repair") for n in graph["nodes"])
    with pytest.raises(Invalid, match="open, copy or rebuild"):
        rbd_derive.save(m, db, house, existing="replace")


def test_a_deleted_rbd_is_made_again_without_asking():
    m = Maintenance(GraphStore(":memory:", PROJECTORS), ORG)
    house = m.create_position("Hot water")["id"]
    m.create_position("Element", parent_id=house)
    db = mongomock.MongoClient()["rbd"]
    first = rbd_derive.save(m, db, house)
    db.rbds.delete_one({"_id": first["rbd_id"]})
    assert "existing" not in rbd_derive.save(m, db, house, check=True)
    again = rbd_derive.save(m, db, house)
    assert not again.get("existing") and db.rbds.count_documents({}) == 1
