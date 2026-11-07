"""Deleting a branch of the tree (retire with cascade) never refuses, takes
everything below it, keeps the history, and comes back as a unit (restore with
cascade). A rebuilt graph is the same as the live one at every step."""

import pytest

from backend.maintenance.service import PROJECTORS, Invalid, Maintenance
from backend.maintenance.store import GraphStore

ORG = "user-tree-delete"


@pytest.fixture()
def m():
    return Maintenance(GraphStore(":memory:", PROJECTORS), ORG, "tester")


def _same_after_rebuild(m):
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before


def _plant(m):
    """Propulsion › Motor 1 › Bearing, Propulsion › Motor 2; an item fitted to Motor 1
    (carrying a position of its own), a task, an open work order, a package, RCM."""
    site = m.create_location("Site")["id"]
    hall = m.create_location("Hall", parent_id=site)["id"]
    top = m.create_position("Airframe")["id"]
    prop = m.create_position("Propulsion", parent_id=top, location_id=hall)["id"]
    m1 = m.create_position("Motor 1", parent_id=prop)["id"]
    m2 = m.create_position("Motor 2", parent_id=prop)["id"]
    brg = m.create_position("Bearing", parent_id=m1)["id"]
    m.fit(m1, new_item={"name": "Motor SN1"})
    item = m.current_fitment(m1)
    item_id = m.s.inn(m.org, item["id"], "IN")[0]["id"]
    m.create_position("Brush slot", parent_id=item_id)
    task = m.create_task(m1, "Grease", 3, "months")["id"]
    wo = m.open_work_order(m2, "Noisy")["id"]
    pkg = m.create_package("Weekly", position_id=prop)["id"]
    m.add_failure_mode(brg, "Bearing wears")
    # A functional failure on Motor 1 explains one on the Airframe (above what goes).
    fn_top = m.add_function(top, "Fly")["id"]
    ff_top = m.add_functional_failure(fn_top, "Can't fly")["id"]
    fn_m1 = m.add_function(m1, "Turn the prop")["id"]
    ff_m1 = m.add_functional_failure(fn_m1, "Doesn't turn")["id"]
    m.link_cause(ff_top, ff_m1)
    return dict(site=site, hall=hall, top=top, prop=prop, m1=m1, m2=m2, brg=brg, item=item_id, task=task,
                wo=wo, pkg=pkg, ff_top=ff_top, ff_m1=ff_m1)


def test_the_preview_counts_what_goes_and_writes_nothing(m):
    p = _plant(m)
    events = m.s.event_count(m.org)
    out = m.retire_position(p["prop"], cascade=True, dry_run=True)
    assert m.s.event_count(m.org) == events
    assert out["dry_run"] is True and out["name"] == "Propulsion"
    assert (out["positions"], out["positions_inside"]) == (4, 3)
    assert out["items_unfitted"] == 1 and out["positions_on_unfitted_items"] == 1
    assert out["tasks"] == 1 and out["open_work_orders"] == 1 and out["work_packages"] == 1
    assert out["functions"] == 1 and out["failure_modes"] == 1 and out["links"] == 1
    assert out["summary"] == ("Delete Propulsion and everything inside it? 3 positions, 1 fitted item (kept, "
                              "unfitted), 1 task, 1 open work order (cancelled). Its history stays in the log.")
    # A leaf with nothing on it says so plainly.
    assert m.retire_position(p["brg"], cascade=True, dry_run=True)["summary"] == (
        "Delete Bearing? Its history stays in the log.")


def test_a_position_delete_never_refuses_and_takes_everything_below(m):
    p = _plant(m)
    out = m.retire_position(p["prop"], "scrapped", cascade=True)
    assert out["deleted"] == out["retired"] == p["prop"] and out["deletion_id"]
    assert set(out["also_retired"]) == {p["m1"], p["m2"], p["brg"]}
    assert all(m.position(x)["retired"] for x in (p["prop"], p["m1"], p["m2"], p["brg"]))
    assert not m.position(p["top"])["retired"]
    # The item is kept, unfitted, with its own position still on it.
    assert m.current_fitment(p["m1"]) is None and not m.item(p["item"])["retired"]
    assert out["items_unfitted"] == [p["item"]]
    assert [c["name"] for c in m._live_children(p["item"], "Position")] == ["Brush slot"]
    wo = m.work_order(p["wo"])
    assert wo["status"] == "cancelled" and wo["cancel_reason"] == "scrapped"
    assert m.s.node(m.org, p["task"])["retired"] and m.s.node(m.org, p["pkg"])["retired"]
    assert m.s.out(m.org, p["ff_top"], "RESULTS_FROM") == []
    _same_after_rebuild(m)
    with pytest.raises(Invalid, match="already deleted"):
        m.retire_position(p["prop"], cascade=True)


def test_undo_brings_the_whole_branch_back_as_it_was(m):
    p = _plant(m)
    fit_before = m.current_fitment(p["m1"])
    m.retire_position(p["prop"], cascade=True)
    back = m.restore_position(p["prop"], cascade=True)
    assert back["positions_restored"] == 4 and back["items_refitted"] == 1 and back["tasks_restored"] == 1
    assert back["work_orders_reopened"] == 1 and back["work_packages_restored"] == 1
    assert back["links_restored"] == 1 and back["skipped"] == []
    assert not any(m.position(x)["retired"] for x in (p["prop"], p["m1"], p["m2"], p["brg"]))
    again = m.current_fitment(p["m1"])
    assert again["id"] == fit_before["id"] and again["to"] is None and again["from"] == fit_before["from"]
    assert m.work_order(p["wo"])["status"] == "open"
    assert not m.s.node(m.org, p["task"])["retired"] and not m.s.node(m.org, p["pkg"])["retired"]
    assert [c["id"] for c in m.s.out(m.org, p["ff_top"], "RESULTS_FROM")] == [p["ff_m1"]]
    _same_after_rebuild(m)
    with pytest.raises(Invalid, match="Nothing deleted there"):
        m.restore_position(p["prop"], cascade=True)
    # Deleted again, the latest delete is the one undone.
    m.retire_position(p["prop"], cascade=True)
    assert m.restore_position(p["prop"], cascade=True)["positions_restored"] == 4
    _same_after_rebuild(m)


def test_undo_skips_what_changed_since(m):
    p = _plant(m)
    m.retire_position(p["prop"], cascade=True)
    spare = m.create_position("Spare bay")["id"]
    m.fit(spare, item_id=p["item"])
    back = m.restore_position(p["prop"], cascade=True)
    assert back["items_refitted"] == 0 and "Motor SN1 wasn't refitted" in back["skipped"][0]
    assert m.current_fitment(spare) is not None and m.current_fitment(p["m1"]) is None
    _same_after_rebuild(m)


def test_a_location_delete_takes_the_places_inside_and_the_positions_there(m):
    p = _plant(m)
    store = m.create_location("Store", parent_id=p["hall"])["id"]
    loose = m.create_item("Spare motor")["id"]
    m.place_item(loose, store)
    part = m.create_part("B-1", "Bearing")["id"]
    m.adjust_stock(part, store, 2)
    round_ = m.create_task(None, "Hall round", 1, "months", location_id=p["hall"])["id"]
    preview = m.retire_location(p["site"], cascade=True, dry_run=True)
    assert preview["locations"] == 3 and preview["locations_inside"] == 2 and preview["positions"] == 4
    assert preview["items_placed"] == 1 and preview["stock_lines"] == 1 and preview["tasks"] == 2
    out = m.retire_location(p["site"], cascade=True)
    assert set(out["also_retired"]) == {p["hall"], store}
    assert m.locations() == [] and m.position(p["prop"])["retired"] and m.position(p["brg"])["retired"]
    assert not m.position(p["top"])["retired"] and m.s.node(m.org, round_)["retired"]
    _same_after_rebuild(m)
    back = m.restore_location(p["site"], cascade=True)
    assert back["locations_restored"] == 3 and back["positions_restored"] == 4 and back["items_refitted"] == 1
    assert not m.position(p["prop"])["retired"] and not m.s.node(m.org, round_)["retired"]
    _same_after_rebuild(m)


def test_an_item_delete_takes_it_out_with_the_positions_inside(m):
    p = _plant(m)
    preview = m.retire_item(p["item"], cascade=True, dry_run=True)
    assert preview["positions"] == 1 and preview["items_unfitted"] == 0
    out = m.retire_item(p["item"], cascade=True)
    assert m.item(p["item"])["retired"] and m.current_fitment(p["m1"]) is None
    assert out["positions"] == 1
    _same_after_rebuild(m)
    back = m.restore_item(p["item"], cascade=True)
    assert back["items_restored"] == 1 and back["items_refitted"] == 1 and back["positions_restored"] == 1
    assert m.current_fitment(p["m1"]) is not None
    _same_after_rebuild(m)


def test_plain_retire_and_restore_keep_their_rules(m):
    p = _plant(m)
    with pytest.raises(Invalid, match="Positions inside it are still in use"):
        m.retire_position(p["prop"])
    with pytest.raises(Invalid, match="open work orders"):
        m.retire_position(p["m2"])
    with pytest.raises(Invalid, match="Locations inside it are still in use"):
        m.retire_location(p["site"])
    with pytest.raises(Invalid, match="is fitted to"):
        m.retire_item(p["item"])


def test_delete_and_undo_over_rest(env_client):
    client, prop, motor = env_client
    preview = client.post(f"/api/maintenance/positions/{prop}/retire", json={"cascade": True, "dry_run": True})
    assert preview.status_code == 200 and preview.json()["positions_inside"] == 1
    done = client.post(f"/api/maintenance/positions/{prop}/retire", json={"cascade": True})
    assert done.status_code == 200 and done.json()["positions"] == 2
    back = client.post(f"/api/maintenance/positions/{prop}/restore", json={"cascade": True})
    assert back.status_code == 200 and back.json()["positions_restored"] == 2


@pytest.fixture()
def env_client(monkeypatch):
    import mongomock
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app
    from backend.routers import maintenance as router

    monkeypatch.setattr(db, "_db", mongomock.MongoClient()["reliafy_test"])
    monkeypatch.setattr(db, "_simulated", True)
    monkeypatch.setattr(router, "_store", GraphStore(":memory:", PROJECTORS))
    monkeypatch.setattr(config, "MAINTENANCE_ENABLED", True)
    monkeypatch.setattr(config, "MAINTENANCE_EMAILS", {"a@x.com"})
    app.dependency_overrides[get_current_user] = lambda: {
        "uid": ORG, "email": "a@x.com", "name": "A", "email_verified": True}
    client = TestClient(app)
    prop = client.post("/api/maintenance/positions", json={"name": "Propulsion"}).json()["id"]
    motor = client.post("/api/maintenance/positions", json={"name": "Motor", "parent_id": prop}).json()["id"]
    yield client, prop, motor
    app.dependency_overrides.pop(get_current_user, None)
