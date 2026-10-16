"""A real Neo4j for the maintenance graph's tests, when one is configured.

``NEO4J_TEST_URI`` (and ``NEO4J_TEST_USERNAME`` / ``NEO4J_TEST_PASSWORD`` /
``NEO4J_TEST_DATABASE``) point the tests at a Neo4j; without them those tests
are skipped, so CI needs none. Every test writes under a namespace of its own
(``test-<random>``) and removes it afterwards: nothing else in the database is
read or touched.

``MAINTENANCE_TEST_GRAPH=neo4j`` runs the maintenance test modules with Neo4j
as the graph (each ``GraphStore(...)`` they make is a ``Neo4jGraphStore`` in a
namespace of its own): the parity run. Slow over a long round trip.
"""

from __future__ import annotations

import os
import threading
import uuid

import pytest

_conn = None
_conn_lock = threading.Lock()


def configured() -> bool:
    return bool(os.environ.get("NEO4J_TEST_URI"))


needs_neo4j = pytest.mark.skipif(not configured(), reason="NEO4J_TEST_URI isn't set (no Neo4j to test against)")


def connection():
    """One connection per test process."""
    global _conn
    with _conn_lock:
        if _conn is None:
            from backend.maintenance.neo4j_store import connect

            _conn = connect(os.environ["NEO4J_TEST_URI"], os.environ.get("NEO4J_TEST_USERNAME") or "neo4j",
                            os.environ.get("NEO4J_TEST_PASSWORD") or "", os.environ.get("NEO4J_TEST_DATABASE") or None)
        return _conn


def namespace() -> str:
    return f"test-{uuid.uuid4().hex[:12]}"


def drop(namespaces) -> None:
    from backend.maintenance.neo4j_store import delete_namespace

    for ns in namespaces:
        delete_namespace(connection(), ns)


def store_factory(created: set):
    """A stand-in for ``GraphStore(path, projectors, log, series, version)`` making a
    Neo4j graph: ":memory:" a new namespace each time; a file path the same
    namespace each time it's given (and the log in that file), as a file would be."""
    from backend.maintenance.neo4j_store import Neo4jGraphStore
    from backend.maintenance.series import SqliteSeries
    from backend.maintenance.store import SqliteEventLog, open_sqlite

    by_path: dict[str, tuple] = {}

    def make(path, projectors, log=None, series=None, version=1):
        if path == ":memory:":
            ns = namespace()
        else:
            if path not in by_path:
                sqlite = open_sqlite(path)
                lock = threading.RLock()
                by_path[path] = (namespace(), SqliteEventLog(sqlite, lock), SqliteSeries(sqlite, lock))
            ns, file_log, file_series = by_path[path]
            log = log if log is not None else file_log
            series = series if series is not None else file_series
        created.add(ns)
        return Neo4jGraphStore(connection(), projectors, log, series=series, version=version, namespace=ns)

    return make


def plant(m) -> dict:
    """A workspace with every shape the graph queries walk: nested locations;
    positions located, inheriting, retired, and inside items (fitted, placed,
    neither, and one whose fitment was struck out); spares placed and moved;
    connections with two ways round, a loop and a removed one; an item class
    tree with a retired branch, items classed directly and by their part; and a product
    structure (parts made of parts, a shared one, indenture levels)."""
    loc = lambda name, parent=None: m.create_location(name, parent_id=parent)["id"]  # noqa: E731
    site = loc("Site")
    area, gallery, store, yard = loc("Area X", site), loc("Gallery", site), loc("Store", site), loc("Yard")
    sub = loc("Substation 2", area)
    pos = lambda name, **kw: m.create_position(name, **kw)["id"]  # noqa: E731
    elec = pos("Electrical")
    mcc = pos("MCC-3", parent_id=elec, location_id=sub)
    f12 = pos("Feeder 12", parent_id=mcc, location_id=gallery)
    f13 = pos("Feeder 13", parent_id=mcc)
    old = pos("Old feeder", parent_id=mcc)
    m.retire_position(pos("Old feeder's relay", parent_id=old))
    m.retire_position(old)

    def fitted(position, name):
        m.fit(position, new_item={"name": name})
        return m.position(position)["fitted"]["item"]["id"]

    truck = pos("Truck 14", location_id=yard)
    engine = fitted(truck, "Engine E1")
    pos("Turbo 1", parent_id=engine)
    truck2 = pos("Truck 15", location_id=yard)
    engine2 = fitted(truck2, "Engine E2")
    pos("Turbo 2", parent_id=engine2)
    m.remove(truck2)
    m.place_item(engine2, store)
    truck3 = pos("Truck 16", location_id=yard)
    engine3 = fitted(truck3, "Engine E3")
    pos("Turbo 3", parent_id=engine3)
    m.remove(truck3)  # out, and not placed anywhere
    breaker = fitted(f13, "Breaker")
    pos("Trip unit", parent_id=breaker)
    m.void_fitment(m.position(f13)["fitted"]["id"])
    spare = m.create_item("Spare pump")["id"]
    m.place_item(spare, store)
    moved = m.create_item("Spare motor")["id"]
    m.place_item(moved, store)
    m.place_item(moved, gallery)

    tank, pump_a, pump_b = pos("Tank"), pos("Pump A"), pos("Pump B")
    filt, header, outlet = pos("Filter"), pos("Header"), pos("Outlet")
    for a, b in ((tank, pump_a), (tank, pump_b), (pump_b, filt), (pump_a, filt), (filt, outlet), (filt, tank)):
        m.connect(a, b)
    m.connect(pump_a, outlet, kind="signal")
    m.disconnect(m.connect(pump_a, header)["id"])
    m.create_group("Pumps", [pump_a, pump_b])

    cls = lambda name, parent=None: m.create_item_class(name, parent_id=parent)["id"]  # noqa: E731
    rotating = cls("Rotating equipment")
    pump = cls("Pump", rotating)
    centrifugal = cls("Centrifugal", pump)
    retired = cls("Old pumps", pump)
    retired_child = cls("Older pumps", retired)
    m.retire_item_class(retired_child)
    m.retire_item_class(retired)
    part = m.create_part("P-100", "Pump P-100", item_class_id=pump)["id"]
    by_part = m.create_item("Pump by part", part_id=part)["id"]
    own_class = m.create_item("Pump, own class", part_id=part)["id"]
    m.assign_item_class(own_class, rotating)
    m.assign_item_class(engine, centrifugal)
    m.assign_item_class(spare, centrifugal)

    # Product structure (#435): the pump part contains a motor and bearings, the motor
    # bearings too (one bearing part, shared); a line changed, one taken out; indenture
    # levels set, and the list changed with a level renamed.
    motor = m.create_part("M-200", "Motor M-200")["id"]
    bearing = m.create_part("B-6205", "Bearing 6205")["id"]
    seal = m.create_part("S-10", "Seal kit")["id"]
    for pid, level in ((part, "Assembly"), (motor, "LRU"), (bearing, "Component")):
        m.set_part_level(pid, level)
    m.add_component(part, motor, 1, "M1")
    m.add_component(part, bearing, 2, "B1, B2")
    m.add_component(motor, bearing, 2)
    m.add_component(part, seal, 1)
    m.update_component(part, seal, 2, "S1")
    m.remove_component(part, seal)
    m.add_component(motor, seal, 1)
    m.set_part_levels(["System", "Assembly", "Line-replaceable unit", "Component"], {"LRU": "Line-replaceable unit"})

    # Conditions: nested, with and without values, excluded lower down, on an item and a
    # connection, and one retired after it was applied.
    cond = lambda name, **kw: m.create_condition(name, **kw)["id"]  # noqa: E731
    outdoor, hazard, temp, gone = cond("Outdoor"), cond("Hazardous area"), cond("Ambient temperature", unit="°C"), \
        cond("Old condition")
    zone1 = cond("Zone 1", parent_id=hazard)
    m.apply_condition(site, outdoor)
    m.exclude_condition(sub, outdoor, "indoors")
    m.apply_condition(site, temp, 40)
    m.apply_condition(area, temp, 55, "sun all day")
    m.apply_condition(mcc, zone1)
    m.apply_condition(engine, temp, 90)
    m.apply_condition(m.connections(tank)["downstream"][0]["id"], outdoor)
    m.apply_condition(yard, gone)
    m.retire_condition(gone)
    return {"site": site, "area": area, "sub": sub, "gallery": gallery, "store": store, "yard": yard,
            "elec": elec, "mcc": mcc, "f12": f12, "f13": f13, "truck": truck, "engine": engine,
            "engine2": engine2, "engine3": engine3, "breaker": breaker, "spare": spare, "moved": moved,
            "tank": tank, "pump_a": pump_a, "pump_b": pump_b, "filter": filt, "header": header, "outlet": outlet,
            "rotating": rotating, "pump": pump, "centrifugal": centrifugal, "retired_class": retired,
            "part": part, "by_part": by_part, "own_class": own_class, "motor": motor, "bearing": bearing,
            "seal": seal}


def query_cases(p: dict) -> list[tuple[str, str]]:
    """(query, id) pairs that cover the plant."""
    return ([("downstream", p[k]) for k in ("tank", "pump_a", "pump_b", "filter", "outlet", "header")] +
            [("location_rollup", p[k]) for k in ("site", "area", "sub", "gallery", "store", "yard")] +
            [("class_members", p[k]) for k in ("rotating", "pump", "centrifugal", "retired_class")])
