"""Reliafy Maintenance: organisations kept apart in the graph (rows keyed by
organisation and id), older graphs and events brought into that layout, and the
shared log applied strictly in sequence."""

import json
import sqlite3

import mongomock
import pytest

from backend.maintenance import store as store_mod
from backend.maintenance.service import PROJECTION_VERSION, PROJECTORS, Maintenance, class_id
from backend.maintenance.store import GraphStore, MongoEventLog

UID = "user-l"


@pytest.fixture()
def store():
    return GraphStore(":memory:", PROJECTORS)



# ---- organisations kept apart ----------------------------------------------------------

def test_position_class_ids_are_per_organisation(store):
    a, b = Maintenance(store, "org-a"), Maintenance(store, "org-b")
    a.create_position("Pump 1", position_class="Centrifugal pump")
    b.create_position("Their pump", position_class="centrifugal  PUMP")
    a.set_class_costs("Centrifugal pump", 1000, 10000)
    b.set_class_costs("centrifugal  PUMP", 1, 2)
    assert class_id("org-a", "Centrifugal pump") != class_id("org-b", "Centrifugal pump")
    assert class_id("org-a", "Centrifugal pump") == class_id("org-a", " centrifugal   PUMP ")
    assert a.position_class("Centrifugal pump")["costs"]["planned_cost"] == 1000
    assert b.position_class("centrifugal  PUMP")["costs"]["planned_cost"] == 1


def test_the_same_id_in_two_organisations_keeps_two_rows(store):
    with store._lock:
        store._conn.execute("BEGIN")
        store.put_node("org-a", "n1", "Position", {"name": "A"})
        store.put_node("org-b", "n1", "Position", {"name": "B"})
        store.put_node("org-a", "n2", "Position", {"name": "A2"})
        store.put_node("org-b", "n2", "Position", {"name": "B2"})
        store.put_edge("org-a", "PART_OF", "n1", "n2")
        store.put_edge("org-b", "PART_OF", "n1", "n2")
        store.delete_edge("org-b", "PART_OF", "n1", "n2")
        store._conn.execute("COMMIT")
    assert store.node("org-a", "n1")["name"] == "A" and store.node("org-b", "n1")["name"] == "B"
    assert [n["name"] for n in store.out("org-a", "n1", "PART_OF")] == ["A2"]
    assert store.out("org-b", "n1", "PART_OF") == []


def test_ids_of_the_wrong_type_read_as_missing(store):
    assert store.node(UID, {"$ne": ""}) is None and store.out(UID, ["x"], "ON") == []
    m = Maintenance(store, UID)
    with pytest.raises(KeyError):
        m.create_position("Pump", parent_id={"a": 1})


_OLD_GRAPH = """
CREATE TABLE nodes (id TEXT PRIMARY KEY, org TEXT NOT NULL, label TEXT NOT NULL, props TEXT NOT NULL);
CREATE TABLE edges (id TEXT PRIMARY KEY, org TEXT NOT NULL, type TEXT NOT NULL, src TEXT NOT NULL,
                    dst TEXT NOT NULL, props TEXT NOT NULL);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def _old_class_id(name: str) -> str:
    import hashlib

    return "class-" + hashlib.sha1(" ".join(name.lower().split()).encode()).hexdigest()[:16]


def _old_events(org: str) -> list[tuple[str, dict]]:
    return [
        ("position.created", {"id": f"{org}-p", "name": "Pump", "position_class": "Pool pump", "on": "2024-01-01"}),
        ("class.costs_set", {"id": _old_class_id("Pool pump"), "name": "Pool pump", "planned_cost": 100.0,
                             "failure_cost": 900.0 if org == "org-a" else 500.0, "availability_target": None}),
    ]


def test_a_graph_file_in_the_older_layout_is_rebuilt(tmp_path):
    path = str(tmp_path / "maintenance.db")
    conn = sqlite3.connect(path)
    conn.executescript(_OLD_GRAPH + store_mod._EVENTS_SCHEMA)
    seq = 0
    for org in ("org-a", "org-b"):
        for kind, payload in _old_events(org):
            seq += 1
            conn.execute("INSERT INTO events (id, org, type, at, actor, payload) VALUES (?, ?, ?, ?, ?, ?)",
                         (f"e{seq}", org, kind, "2024-01-01T00:00:00+00:00", None, json.dumps(payload)))
    # The old layout: the second organisation's class row replaced the first's.
    conn.execute("INSERT INTO nodes VALUES (?, 'org-b', 'PositionClass', '{}')", (_old_class_id("Pool pump"),))
    conn.executemany("INSERT INTO meta VALUES (?, ?)", [("version", "2"), ("applied", str(seq))])
    conn.commit()
    conn.close()

    s = GraphStore(path, PROJECTORS, version=PROJECTION_VERSION)
    assert s._schema_current()
    a, b = Maintenance(s, "org-a"), Maintenance(s, "org-b")
    assert a.position_class("Pool pump")["costs"]["failure_cost"] == 900
    assert b.position_class("Pool pump")["costs"]["failure_cost"] == 500
    # Opened again, it isn't rebuilt (and still reads the same).
    again = GraphStore(path, PROJECTORS, version=PROJECTION_VERSION)
    assert again.snapshot() == s.snapshot()


def test_older_class_events_in_a_shared_log_replay_per_organisation():
    mongo = mongomock.MongoClient()["maint_old_events"]
    log = MongoEventLog(mongo)
    for org in ("org-a", "org-b"):
        for kind, payload in _old_events(org):
            log.append({"id": store_mod.new_id(), "org": org, "type": kind, "at": "2024-01-01T00:00:00+00:00",
                        "actor": None, "payload": payload})
    s = GraphStore(":memory:", PROJECTORS, MongoEventLog(mongo), version=PROJECTION_VERSION)
    s.sync()
    assert Maintenance(s, "org-a").position_class("Pool pump")["costs"]["failure_cost"] == 900
    assert Maintenance(s, "org-b").position_class("Pool pump")["costs"]["failure_cost"] == 500


# ---- the log applied in order ------------------------------------------------------------

class _GappyLog:
    """A log whose events can be held back, as if another process had taken a
    number and not yet written its event."""

    def __init__(self):
        self.events, self.held = [], set()

    def add(self, seq, org, type, payload):
        self.events.append({"seq": seq, "org": org, "type": type, "payload": payload})

    def since(self, seq, limit=None):
        out = sorted((e for e in self.events if e["seq"] > seq and e["seq"] not in self.held),
                     key=lambda e: e["seq"])
        return out[:limit] if limit else out

    def count(self, org):
        return sum(1 for e in self.events if e["org"] == org)


def test_sync_waits_at_a_gap_in_the_log(monkeypatch):
    monkeypatch.setattr(store_mod, "GAP_WAIT", 0)
    log = _GappyLog()
    s = GraphStore(":memory:", PROJECTORS, log)
    log.add(1, UID, "position.created", {"id": "p1", "name": "One", "on": "2024-01-01"})
    log.add(2, UID, "position.created", {"id": "p2", "name": "Two", "on": "2024-01-01"})
    log.add(3, UID, "position.created", {"id": "p3", "name": "Three", "on": "2024-01-01"})
    log.held = {2}
    s.sync()
    assert s._applied() == 1 and s.node(UID, "p3") is None  # not past the gap
    log.held = set()
    s.sync()
    assert s._applied() == 3 and s.node(UID, "p2") and s.node(UID, "p3")


def test_a_gap_that_never_fills_is_passed_over_after_a_while(monkeypatch):
    monkeypatch.setattr(store_mod, "GAP_WAIT", 0)
    monkeypatch.setattr(store_mod, "GAP_TIMEOUT", 0)
    log = _GappyLog()
    s = GraphStore(":memory:", PROJECTORS, log)
    log.add(1, UID, "position.created", {"id": "p1", "name": "One", "on": "2024-01-01"})
    log.add(3, UID, "position.created", {"id": "p3", "name": "Three", "on": "2024-01-01"})
    s.sync()
    assert s._applied() == 3 and s.node(UID, "p3")
    assert s.skipped() == [{"seq": 2, "why": "missing from the log"}]


def test_an_event_that_cant_be_projected_is_passed_over(store):
    m = Maintenance(store, UID)
    m.create_position("Pump")
    for kind, payload in (("position.updated", {"id": "nope", "changes": {"name": "x"}}),
                          ("something.new", {"id": "x"})):
        store.log.append({"id": store_mod.new_id(), "org": UID, "type": kind, "at": "2024-01-01T00:00:00+00:00",
                          "actor": None, "payload": payload})
    store.sync()  # doesn't raise
    assert [s["why"] for s in store.skipped()] == ["KeyError in position.updated",
                                                   "UnknownEvent in something.new"]
    later = m.create_position("Filter")  # the graph carries on
    assert m.position(later["id"])["name"] == "Filter"
