"""Erasing part of a workspace with its history (purge.py): what's connected to the
roots goes, every event naming only that is overwritten in place (no gaps), an
event naming both sides refuses the purge, every process rebuilds on its next
sync, and the rest of the graph is exactly as it was."""

import time

import mongomock
import pytest

from backend.maintenance import purge
from backend.maintenance.service import PROJECTORS, Maintenance
from backend.maintenance.store import PURGED, GraphStore, MongoEventLog

ORG = "user-purge"
OTHER = "user-purge-other"


def _tree(m, name):
    """A small but full tree: positions, a location, an item fitted, a task, a
    work order, a measurement point with a reading, RCM rows."""
    loc = m.create_location(f"{name} bay")["id"]
    top = m.create_position(name)["id"]
    motor = m.create_position(f"{name} motor", parent_id=top, location_id=loc)["id"]
    m.fit(motor, new_item={"name": f"{name} motor SN1"}, on="2024-01-01")
    m.create_task(motor, f"Inspect {name}", 3, "months")
    m.open_work_order(motor, f"{name} noisy")
    point = m.add_point(motor, f"{name} vibration", unit="mm/s")["id"]
    m.record_reading(point, 2.5, on="2024-02-01")
    fn = m.add_function(motor, f"Turn the {name} prop")["id"]
    ff = m.add_functional_failure(fn, "Doesn't turn")["id"]
    m.add_failure_mode(motor, f"{name} bearing wears")
    return {"top": top, "motor": motor, "ff": ff, "loc": loc}


def _two_trees(m):
    keep, drop = _tree(m, "Pump"), _tree(m, "Drone")
    return keep, drop


@pytest.fixture()
def m():
    return Maintenance(GraphStore(":memory:", PROJECTORS), ORG, "tester")


def _names(store, org):
    return [row[3] for row in store.snapshot(org)[0]]


def test_a_purge_erases_one_tree_and_leaves_the_rest_exactly_as_it_was(m):
    keep, drop = _two_trees(m)
    other = Maintenance(m.s, OTHER, "tester")
    _tree(other, "Drone")  # the same names in another workspace: never touched
    before, before_other = m.s.snapshot(ORG), m.s.snapshot(OTHER)
    events = m.s.log.count(ORG)

    gone = purge.closure(m.s, ORG, [drop["top"]])
    assert keep["top"] not in gone and drop["motor"] in gone and drop["loc"] in gone
    plan = purge.plan(m.s, ORG, gone)
    assert plan["mixed"] == [] and plan["seqs"]
    assert m.s.log.purge(ORG, plan["seqs"], "2026-11-13") == len(plan["seqs"])

    m.s.sync()  # the purge count went up: this graph rebuilds by itself
    check = purge.compare(before, m.s.snapshot(ORG), gone)
    assert check["left"] == [] and check["nodes_changed"] == 0 and check["edges_changed"] == 0
    assert not any("Drone" in props for props in _names(m.s, ORG))
    assert any("Pump" in props for props in _names(m.s, ORG))
    assert m.s.snapshot(OTHER) == before_other
    # No gaps: every number is still there, the erased ones as tombstones.
    assert m.s.log.count(ORG) == events and m.s.skipped() == []
    erased = [e for e in m.s.events(ORG, limit=10_000) if e["seq"] in set(plan["seqs"])]
    assert {e["type"] for e in erased} == {PURGED}
    assert all(e["payload"] == {"purged": True, "on": "2026-11-13"} for e in erased)
    # A second plan finds nothing left, and a rebuild gives the same graph.
    assert purge.plan(m.s, ORG, gone)["seqs"] == []
    after = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == after


def test_an_event_naming_both_sides_refuses_the_purge(m):
    keep, drop = _two_trees(m)
    m.update_position(drop["motor"], location_id=keep["loc"])  # one event joins the two trees
    gone = purge.closure(m.s, ORG, [drop["top"]], barriers=[keep["loc"]])
    plan = purge.plan(m.s, ORG, gone)
    # The move names both; so does creating the motor at its old bay (now left behind, kept).
    assert {x["type"] for x in plan["mixed"]} == {"position.updated", "position.created"}
    # Without the barrier, the link makes everything one: the closure says so.
    assert keep["top"] in purge.closure(m.s, ORG, [drop["top"]])


def test_the_script_refuses_mixed_events_and_writes_nothing(m, monkeypatch, capsys):
    from backend.scripts import maintenance_purge

    keep, drop = _two_trees(m)
    m.update_position(drop["motor"], location_id=keep["loc"])
    monkeypatch.setattr(maintenance_purge, "_store", lambda: _replay(m.s.log))
    monkeypatch.setattr(maintenance_purge, "_db", lambda: None)
    before = m.s.snapshot()
    code = maintenance_purge.main(["--org", ORG, "--root", drop["top"], "--barrier", keep["loc"], "--apply"])
    assert code == 2 and "Refused" in capsys.readouterr().err
    m.s.sync()
    assert m.s.snapshot() == before


def _replay(log):
    store = GraphStore(":memory:", PROJECTORS, log)
    store.sync()
    return store


def test_the_script_dry_runs_then_applies(m, monkeypatch, capsys):
    import json

    from backend.scripts import maintenance_purge

    keep, drop = _two_trees(m)
    monkeypatch.setattr(maintenance_purge, "_store", lambda: _replay(m.s.log))
    monkeypatch.setattr(maintenance_purge, "_db", lambda: None)
    events = m.s.log.count(ORG)
    assert maintenance_purge.main(["--org", ORG, "--root", drop["top"]]) == 0
    dry = json.loads(capsys.readouterr().out)
    assert dry["dry_run"] is True and dry["events"] > 0 and dry["mixed"] == []
    assert dry["by_label"]["Position"] == 2 and dry["by_label"]["Reading"] == 1
    assert not any(e["type"] == PURGED for e in m.s.events(ORG, limit=10_000))

    code = maintenance_purge.main(["--org", ORG, "--root", drop["top"], "--apply", "--on", "2026-11-13"])
    out = json.loads(capsys.readouterr().out)
    assert code == 0, out
    assert out["erased"] == dry["events"] and out["check"]["left"] == [] and out["skipped"] == []
    assert m.s.log.count(ORG) == events
    m.s.sync()
    assert not any("Drone" in props for props in _names(m.s, ORG))
    assert m.s.node(ORG, keep["top"])["name"] == "Pump"


def test_every_process_on_a_shared_mongo_log_rebuilds_after_a_purge():
    """Another Cloud Run instance, already caught up, drops what was erased on its
    next sync; a fresh one replays the tombstones straight through (no gap waits)."""
    mongo = mongomock.MongoClient()["purge_log"]
    a = Maintenance(GraphStore(":memory:", PROJECTORS, MongoEventLog(mongo)), ORG)
    b = GraphStore(":memory:", PROJECTORS, MongoEventLog(mongo))
    keep, drop = _two_trees(a)
    b.sync()
    gone = purge.closure(a.s, ORG, [drop["top"]])
    plan = purge.plan(a.s, ORG, gone)
    MongoEventLog(mongo).purge(ORG, plan["seqs"], "2026-11-13")
    assert b.node(ORG, drop["top"]) is not None  # not until it syncs
    b.sync()
    assert b.node(ORG, drop["top"]) is None and b.node(ORG, keep["top"])["name"] == "Pump"
    a.s.sync()
    assert a.s.snapshot() == b.snapshot()
    started = time.monotonic()
    c = GraphStore(":memory:", PROJECTORS, MongoEventLog(mongo))
    c.sync()
    assert time.monotonic() - started < 5 and c.skipped() == []
    assert c.snapshot() == b.snapshot()
    # Writes after the purge carry on as usual, in every process.
    a.create_position("After")
    b.sync()
    assert any(p["name"] == "After" for p in b.nodes(ORG, "Position"))


@pytest.mark.sqlite_only
def test_a_rebuild_after_a_purge_asks_the_mirror_for_a_whole_copy(m):
    calls = []

    class Mirror:
        def resync_full(self):
            calls.append(True)

    _, drop = _two_trees(m)
    m.s.mirror = Mirror()
    m.s.sync()
    assert calls == []  # nothing erased: nothing owed
    m.s.log.purge(ORG, purge.plan(m.s, ORG, purge.closure(m.s, ORG, [drop["top"]]))["seqs"], "2026-11-13")
    m.s.sync()
    assert calls == [True]
    m.s.sync()
    assert calls == [True]  # once


@pytest.mark.sqlite_only
def test_many_tombstones_replay_quickly():
    s = GraphStore(":memory:", PROJECTORS)
    m = Maintenance(s, ORG, "tester")
    top = m.create_position("Drone")["id"]
    for i in range(300):
        m.create_position(f"Drone part {i}", parent_id=top)
    m.s.log.purge(ORG, purge.plan(s, ORG, purge.closure(s, ORG, [top]))["seqs"], "2026-11-13")
    started = time.monotonic()
    s.sync()
    assert time.monotonic() - started < 2
    assert s.nodes(ORG, "Position") == [] and s.skipped() == []


def test_other_records_that_name_only_what_goes_are_listed_to_go():
    db = mongomock.MongoClient()["purge_other"]
    gone, kept = {"a" * 32}, {"b" * 32}
    db.maintenance_photo_links.insert_many([
        {"_id": "l1", "org": ORG, "target": {"position_id": "a" * 32}},
        {"_id": "l2", "org": ORG, "target": {"position_id": "b" * 32}},
        {"_id": "l3", "org": ORG, "targets": ["a" * 32, "b" * 32]},
        {"_id": "l4", "org": OTHER, "target": {"position_id": "a" * 32}},
    ])
    db.maintenance_series.insert_one({"_id": "s1", "m": {"org": ORG, "point": "a" * 32}, "v": 1.0})
    db.maintenance_events.insert_one({"_id": "e1", "org": ORG, "payload": {"id": "a" * 32}})
    found = purge.other_records(db, ORG, gone, kept)
    assert found == {"maintenance_photo_links": {"only": ["l1"], "shared": ["l3", "l4"]},
                     "maintenance_series": {"only": ["s1"], "shared": []}}
