"""The maintenance graph's Neo4j side, as far as it goes without a Neo4j: the
changes the SQLite graph keeps for a mirror, the graph queries' Python answers,
and a mirror's trouble never reaching a request or the hourly job. (With a
Neo4j: test_maintenance_neo4j.py.)"""

import json

import pytest

from backend.maintenance import graph_query, mirror as mirror_mod
from backend.maintenance.service import PROJECTORS, Maintenance
from backend.maintenance.store import GraphStore
from backend.tests.neo4j_support import plant

ORG = "user-g"


@pytest.fixture()
def m():
    return Maintenance(GraphStore(":memory:", PROJECTORS), ORG, "tester")


# ---- what changed, for a mirror ----------------------------------------------------------

@pytest.mark.sqlite_only
def test_changes_record_the_last_event_to_write_each_node_and_edge(m):
    a = m.create_position("A")["id"]
    b = m.create_position("B", parent_id=a)["id"]
    applied, marks = m.s.change_marks()
    assert marks == {ORG: applied} and m.s.org_mark(ORG) == applied and m.s.org_mark("nobody") == 0
    whole = m.s.org_changes(ORG, None)
    assert {n[0] for n in whole["nodes"]} == {a, b} and [e[0] for e in whole["edges"]] == [f"PART_OF:{b}:{a}"]

    m.update_position(b, parent_id="")  # the PART_OF edge is deleted
    since = m.s.org_changes(ORG, applied)
    assert since["applied"] == applied + 1
    assert [n[0] for n in since["nodes"]] == [] and since["edges"] == []
    assert since["gone"] == [(f"PART_OF:{b}:{a}", "PART_OF", b, a)]
    assert m.s.org_changes(ORG, since["applied"]) == {"applied": since["applied"], "nodes": [], "edges": [],
                                                     "gone": []}
    # Another organisation's writes are its own.
    Maintenance(m.s, "user-other").create_position("C")
    assert m.s.org_changes(ORG, since["applied"])["nodes"] == []
    assert set(m.s.change_marks()[1]) == {ORG, "user-other"}


@pytest.mark.sqlite_only
def test_a_graph_kept_before_changes_were_counts_them_from_where_it_was(tmp_path):
    path = str(tmp_path / "g.sqlite")
    store = GraphStore(path, PROJECTORS)
    Maintenance(store, ORG).create_position("A")
    store._conn.execute("DROP TABLE changes")
    store._conn.close()
    reopened = GraphStore(path, PROJECTORS)
    assert reopened.changes_from() == 1  # a mirror older than this is copied whole
    reopened.rebuild()
    assert reopened.changes_from() == 0 and len(reopened.org_changes(ORG, 0)["nodes"]) == 1


# ---- the graph queries, in Python -------------------------------------------------------

def test_downstream_is_nearest_first_and_each_reached_one_way(m):
    p = plant(m)
    rows = m.impact(p["tank"])["downstream"]
    assert [(r["name"], r["depth"], r["from"], r["via"]) for r in rows] == [
        ("Pump A", 1, "Tank", "flow"), ("Pump B", 1, "Tank", "flow"),
        ("Filter", 2, "Pump A", "flow"),  # Pump A and Pump B both feed it: the first by name
        ("Outlet", 2, "Pump A", "signal"),  # the signal line is shorter than the flow through the filter
    ]  # the loop back to the tank isn't downstream of it; the removed connection to Header doesn't count
    assert graph_query.downstream(m, p["header"]) == []
    assert [r["name"] for r in graph_query.downstream(m, p["filter"])] == ["Outlet", "Tank", "Pump A", "Pump B"]


def test_a_location_roll_up_is_the_location_views_positions_and_items(m):
    p = plant(m)
    for key in ("site", "area", "store", "yard"):
        got, view = graph_query.location_rollup(m, p[key]), m.location(p[key])
        assert len(got["positions"]) == view["counts"]["positions"]
        assert {i[0] for i in got["items"]} == {i["id"] for i in view["items"]}
    store = graph_query.location_rollup(m, p["store"])
    assert {i[0] for i in store["items"]} == {p["engine2"], p["spare"]}  # the moved spare is in the gallery now
    turbo2 = next(r for r in store["positions"] if r[2] == p["engine2"])
    assert m.s.node(ORG, turbo2[0])["name"] == "Turbo 2"  # inside the engine placed there
    yard = {m.s.node(ORG, r[0])["name"]: r[2] for r in graph_query.location_rollup(m, p["yard"])["positions"]}
    # Turbo 1's engine is fitted to Truck 14; Turbo 3's engine is out and not placed.
    assert yard == {"Truck 14": p["truck"], "Turbo 1": p["truck"], "Truck 15": yard["Truck 15"],
                    "Truck 16": yard["Truck 16"]}
    sub = {m.s.node(ORG, r[0])["name"] for r in graph_query.location_rollup(m, p["sub"])["positions"]}
    assert sub == {"MCC-3", "Feeder 13"}  # not the retired feeder, nor the trip unit (its fitment struck out)


def test_class_members_are_by_each_items_own_class_else_its_parts(m):
    p = plant(m)
    got = graph_query.class_members(m, p["pump"])
    assert got["classes"] == sorted([p["pump"], p["centrifugal"]])  # not the retired branch
    assert got["items"] == sorted([p["engine"], p["spare"], p["by_part"]])  # not the one with a class of its own
    assert got["parts"] == [p["part"]]
    assert p["own_class"] in graph_query.class_members(m, p["rotating"])["items"]


@pytest.mark.sqlite_only
def test_cypher_is_only_asked_when_there_is_a_neo4j_graph(m):
    pid = m.create_position("A")["id"]
    with pytest.raises(graph_query.Stale):
        graph_query.downstream(m, pid, use="cypher")
    assert graph_query.downstream(m, pid) == []


# ---- the mirror without a Neo4j -------------------------------------------------------------

@pytest.mark.sqlite_only
def test_large_changes_are_sent_in_parts_in_write_order():
    parts = list(mirror_mod._chunks([1, 2, 3], ["g"], [10, 11, 12, 13], 3))
    assert parts == [([1, 2, 3], [], []), ([], ["g"], [10, 11]), ([], [], [12, 13])]
    assert list(mirror_mod._chunks([], [], [], 3)) == []


class _Unreachable:
    def run(self, *a, **k):
        raise OSError("no route to host")

    def ping(self):
        raise OSError("no route to host")

    def ensure_schema(self):
        raise OSError("no route to host")


@pytest.mark.sqlite_only
def test_neo4j_unreachable_never_fails_a_write_or_the_hourly_job(m, monkeypatch):
    from backend import config
    from backend.routers import maintenance as router
    from backend.services import content_jobs

    mirror = mirror_mod.Neo4jMirror(m.s, _Unreachable(), namespace="x").attach()
    m.create_position("A")  # wakes the mirror, which fails in the background
    mirror._thread.join(timeout=0.5)
    got = mirror_mod.catch_up(m.s)
    assert got["step"] == "maintenance_mirror" and "OSError" in got["error"]

    monkeypatch.setattr(router, "_store", m.s)
    monkeypatch.setattr(config, "MAINTENANCE_GRAPH_MIRROR", "neo4j")
    step = content_jobs._maintenance_graph_step(dry_run=False)
    assert "error" in step and json.dumps(step)


@pytest.mark.sqlite_only
def test_no_mirror_unless_configured(monkeypatch):
    from backend import config

    store = GraphStore(":memory:", PROJECTORS)
    monkeypatch.setattr(config, "MAINTENANCE_GRAPH_MIRROR", "")
    assert mirror_mod.attach_from_config(store) is None and store.mirror is None and store.listeners == []
    assert mirror_mod.catch_up(store) == {"step": "maintenance_mirror", "skipped": "no mirror"}
