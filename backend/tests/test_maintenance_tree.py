"""The asset trees: every position once (positions an item carries too), what's on
each row (overdue, open work, alarms) and everything inside it rolled up, read in
bulk rather than a few reads per position."""

import time

import mongomock
import pytest

from backend.maintenance.service import PROJECTORS, Maintenance
from backend.maintenance.store import GraphStore

ORG = "user-t"


@pytest.fixture()
def m():
    return Maintenance(GraphStore(":memory:", PROJECTORS), ORG, "tester")


def _find(nodes, name):
    for n in nodes:
        if n["name"] == name:
            return n
        found = _find(n["children"], name)
        if found:
            return found
    return None


def _plant(m):
    """A truck whose engine carries a turbo position, and a pump station."""
    truck = m.create_position("Truck 14")["id"]
    m.fit(truck, new_item={"name": "Engine", "serial": "E123"})
    engine = m.position(truck)["fitted"]["item"]["id"]
    turbo = m.create_position("Turbo 1", parent_id=engine, position_class="Turbocharger")["id"]
    m.fit(turbo, new_item={"name": "Turbocharger", "serial": "T9"})
    station = m.create_position("Pump station")["id"]
    pump = m.create_position("Pump 1", parent_id=station, position_class="Centrifugal pump")["id"]
    seal = m.create_position("Seal", parent_id=pump, position_class="Mechanical seal")["id"]
    return {"truck": truck, "engine": engine, "turbo": turbo, "station": station, "pump": pump, "seal": seal}


def test_positions_an_item_carries_sit_where_the_item_is_fitted(m):
    ids = _plant(m)
    tree = m.tree()
    assert [t["name"] for t in tree] == ["Pump station", "Truck 14"]  # never a top of their own
    truck = _find(tree, "Truck 14")
    [turbo] = truck["children"]
    assert turbo["name"] == "Turbo 1" and turbo["carried_by"] == {"id": ids["engine"], "name": "Engine"}
    assert turbo["item"]["serial"] == "T9" and turbo["fitted"] is True
    assert truck["inside"]["positions"] == 1

    # The engine moves to another truck: its positions go with it.
    truck22 = m.create_position("Truck 22")["id"]
    m.remove(ids["truck"])
    m.move_item(ids["engine"], truck22)
    tree = m.tree()
    assert _find(tree, "Truck 14")["children"] == []
    assert [c["name"] for c in _find(tree, "Truck 22")["children"]] == ["Turbo 1"]

    # Out on the bench (fitted nowhere): not in the plant's tree, but in the rows,
    # carried by the engine, with no parent.
    m.remove(truck22)
    assert _find(m.tree(), "Turbo 1") is None
    row = next(r for r in m.tree_rows()["positions"] if r["name"] == "Turbo 1")
    assert row["parent_id"] is None and row["carried_by"]["id"] == ids["engine"]
    assert any(i["id"] == ids["engine"] for i in m.tree_rows()["unhomed"])


def test_status_on_each_row_and_rolled_up_inside(m):
    ids = _plant(m)
    task = m.create_task(ids["seal"], "Inspect the seal", 1, "months")
    m.set_last_done(task["id"], "2020-01-01")  # long overdue
    m.create_task(ids["pump"], "Grease", 3, "months")  # due later
    m.open_work_order(ids["pump"], "Noisy bearing")
    point = m.add_point(ids["pump"], "Vibration", kind="condition", unit="mm/s", alarm_above=7.1)
    m.record_reading(point["id"], 9.4)
    m.open_work_order(None, "Turbo overhaul", item_id=m.position(ids["turbo"])["fitted"]["item"]["id"])
    ok = m.add_point(ids["seal"], "Leak", kind="condition", unit="ml/h", alarm_above=50)
    m.record_reading(ok["id"], 3)

    tree = m.tree()
    seal, pump, station = _find(tree, "Seal"), _find(tree, "Pump 1"), _find(tree, "Pump station")
    assert seal["status"]["overdue"] == 1 and seal["status"]["alarms"] == 0
    assert pump["status"]["overdue"] == 0 and pump["status"]["alarms"] >= 1
    # The alarm raised a work order on its own, so open work counts it too.
    assert pump["status"]["open_work"] == pump["open_work_orders"] >= 1
    assert pump["inside"] == {"positions": 1, "empty": 1, "overdue": 1, "open_work": 0, "alarms": 0,
                              "next_due": seal["status"]["next_due"]}
    assert station["inside"]["overdue"] == 1 and station["inside"]["positions"] == 2
    assert station["inside"]["open_work"] == pump["status"]["open_work"]
    assert station["inside"]["alarms"] == pump["status"]["alarms"]
    assert station["inside"]["empty"] == 2  # the pump and the seal: a class, nothing fitted
    # The turbo's work order is on its item: it shows on the turbo position, and on the truck.
    turbo, truck = _find(tree, "Turbo 1"), _find(tree, "Truck 14")
    assert turbo["status"]["open_work"] == 1 and turbo["open_work_orders"] == 0
    assert truck["inside"]["open_work"] == 1


def test_the_tree_agrees_with_each_position_page(m):
    ids = _plant(m)
    m.create_task(ids["pump"], "Grease", 3, "months")
    m.create_task(ids["pump"], "Overhaul", 2, "years")
    m.open_work_order(ids["station"], "Paint")
    flat = []

    def walk(nodes):
        for n in nodes:
            flat.append(n)
            walk(n["children"])

    walk(m.tree())
    assert len(flat) == 5  # every position, the carried turbo included
    for node in flat:
        page = m.position(node["id"])
        assert node["tasks"] == len(page["tasks"])
        assert node["next_due"] == min((t["next_due"] for t in page["tasks"] if t["next_due"]), default=None)
        assert node["open_work_orders"] == sum(1 for w in page["work_orders"] if w["status"] in ("open", "planned"))
        assert node["item"] == (page["fitted"] and page["fitted"]["item"])
        assert [c["id"] for c in node["children"]] == [c["id"] for c in sorted(
            node["children"], key=lambda c: c["name"].lower())]


def test_where_each_position_is_set_or_inherited(m):
    ids = _plant(m)
    site = m.create_location("Site")["id"]
    m.update_position(ids["station"], location_id=site)
    rows = {r["name"]: r for r in m.tree_rows()["positions"]}
    assert rows["Pump station"]["location"] == {"id": site, "name": "Site", "inherited": False}
    assert rows["Pump station"]["location_id"] == site
    assert rows["Seal"]["location"] == {"id": site, "name": "Site", "inherited": True}
    assert "location_id" not in rows["Seal"] and "location" not in rows["Truck 14"]
    # The same as each position's page says.
    for name in ("Pump station", "Seal"):
        assert m.position(rows[name]["id"])["location"]["id"] == site


def test_rows_for_the_pane_are_lean_and_list_spares(m):
    ids = _plant(m)
    store = m.create_location("Store A")["id"]
    spare = m.create_item("Spare seal", serial="S-1")
    m.place_item(spare["id"], store)
    out = m.tree_rows()
    assert len(out["positions"]) == 5
    seal = next(r for r in out["positions"] if r["id"] == ids["seal"])
    assert set(seal) == {"id", "name", "parent_id", "position_class", "inside"} or set(seal) == {
        "id", "name", "parent_id", "position_class"}  # nothing empty is sent
    assert out["spares"] == [{"id": spare["id"], "name": "Spare seal", "serial": "S-1", "location_id": store}]
    assert out["locations"] == [{"id": store, "name": "Store A", "parent_id": None}]


def test_reading_the_tree_writes_nothing(m):
    _plant(m)
    before, events = m.s.snapshot(), m.s.event_count(ORG)
    m.tree()
    m.tree_rows()
    assert m.s.snapshot() == before and m.s.event_count(ORG) == events


def _count_reads(store):
    counts = {"n": 0}
    for name in ("node", "nodes", "out", "inn", "edge", "pairs"):
        real = getattr(store, name)

        def wrapped(*a, _real=real, **kw):
            counts["n"] += 1
            return _real(*a, **kw)

        setattr(store, name, wrapped)
    return counts


def _grow(m, systems, per):
    tops = []
    for i in range(systems):
        top = m.create_position(f"System {i}")["id"]
        tops.append(top)
        for j in range(per):
            p = m.create_position(f"Unit {i}.{j}", parent_id=top, position_class="Pump")["id"]
            if j % 2:
                m.fit(p, new_item={"name": f"Pump {i}.{j}"})
            m.create_task(p, "Inspect", 6, "months")
            if j % 3 == 0:
                m.open_work_order(p, "Check")
    return tops


def test_the_tree_is_read_in_bulk_not_per_position():
    small = Maintenance(GraphStore(":memory:", PROJECTORS), ORG, "tester")
    big = Maintenance(GraphStore(":memory:", PROJECTORS), ORG, "tester")
    _grow(small, 2, 3)
    _grow(big, 6, 20)
    reads = []
    for mm in (small, big):
        counts = _count_reads(mm.s)
        mm.tree()
        mm.tree_rows()
        reads.append(counts["n"])
    assert reads[0] == reads[1], reads  # the same reads, whatever the size


def test_a_big_register_reads_quickly():
    """About 8,000 positions (written straight into the graph: the events would
    take minutes) read in well under the time a page load allows."""
    s = GraphStore(":memory:", PROJECTORS)
    rows, edges = [], []
    n = 0
    for a in range(20):
        top = f"top{a}"
        rows.append((top, f"Area {a}"))
        for b in range(20):
            mid = f"{top}-{b}"
            rows.append((mid, f"System {a}.{b}"))
            edges.append((mid, top))
            for c in range(19):
                leaf = f"{mid}-{c}"
                rows.append((leaf, f"Unit {a}.{b}.{c}"))
                edges.append((leaf, mid))
    for pid, name in rows:
        s.put_node(ORG, pid, "Position", {"name": name, "tag": "", "position_class": "", "description": ""})
        n += 1
    for src, dst in edges:
        s.put_edge(ORG, "PART_OF", src, dst)
    m = Maintenance(s, ORG, "tester")
    t0 = time.perf_counter()
    out = m.tree_rows()
    took = time.perf_counter() - t0
    assert len(out["positions"]) == n == 8020
    tree = m.tree()
    assert len(tree) == 20 and tree[0]["inside"]["positions"] == 20 * 20
    assert took < 5, took


def test_the_tree_through_the_api(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app
    from backend.routers import maintenance as router

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    monkeypatch.setattr(config, "MAINTENANCE_ENABLED", True)
    monkeypatch.setattr(config, "MAINTENANCE_EMAILS", {"t@example.org"})
    test_db = mongomock.MongoClient()["maint_tree_api"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    monkeypatch.setattr(router, "_store", GraphStore(":memory:", PROJECTORS))
    user = {"uid": "user-t", "email": "t@example.org", "name": "T", "email_verified": True}
    test_db.users.insert_one({"_id": "user-t", "email": "t@example.org", "name": "T", "email_verified": True})
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        api = TestClient(app)
        base = "/api/maintenance"
        top = api.post(f"{base}/positions", json={"name": "House"}).json()["id"]
        api.post(f"{base}/positions", json={"name": "Pool pump", "parent_id": top})
        out = api.get(f"{base}/tree").json()
        assert {r["name"] for r in out["positions"]} == {"House", "Pool pump"}
        assert out["summary"]["positions"] == 2 and out["today"]
        pool = next(r for r in out["positions"] if r["name"] == "Pool pump")
        assert pool["parent_id"] == top
        overview = api.get(f"{base}/overview").json()
        assert overview["tree"][0]["inside"]["positions"] == 1
    finally:
        app.dependency_overrides.clear()
