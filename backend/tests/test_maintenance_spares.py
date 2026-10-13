"""Reliafy Maintenance: a position's parts list (its bill of materials), the
spares it calls for, and the work orders that draw on it."""

from datetime import date

import mongomock
import pytest

from backend.maintenance import service as service_mod
from backend.maintenance.service import PROJECTORS, Invalid, LimitReached, Maintenance, NotFound, summary
from backend.maintenance.store import GraphStore

ORG = "user-spares"


@pytest.fixture()
def m():
    return Maintenance(GraphStore(":memory:", PROJECTORS), ORG, "tester")


@pytest.fixture()
def plant(m):
    """A pump position, a store, and a catalogue: pump A1 superseded by B1, B1
    interchangeable with C1, and a seal kit."""
    store = m.create_location("Store")["id"]
    a = m.create_part("A1", "Pump", "Grundfos")["id"]
    b = m.create_part("B1", "Pump v2", "Grundfos")["id"]
    c = m.create_part("C1", "Pump (other make)")["id"]
    kit = m.create_part("K1", "Seal kit")["id"]
    m.supersede_part(a, b)
    m.mark_interchangeable(b, c)
    pid = m.create_position("Pump A")["id"]
    return {"store": store, "a": a, "b": b, "c": c, "kit": kit, "pid": pid}


def _entry(listing: dict, part_number: str) -> dict:
    return next(x for x in listing["parts_list"] if x["part"]["part_number"] == part_number)


def test_a_parts_list_with_roles_quantities_and_notes(m, plant):
    m.add_position_part(plant["pid"], plant["kit"], "component", quantity=2, notes="")
    out = m.add_position_part(plant["pid"], plant["a"], "replacement", critical=True,
                              notes="needs matching button kit")
    # The replacement comes first.
    assert [x["part"]["part_number"] for x in out["parts_list"]] == ["A1", "K1"]
    pump = out["parts_list"][0]
    assert (pump["role"], pump["quantity"], pump["critical"], pump["min_on_hand"]) == ("replacement", 1, True, 1)
    assert pump["notes"] == "needs matching button kit"
    assert _entry(out, "K1")["min_on_hand"] is None  # not critical: no minimum
    assert m.position(plant["pid"])["parts_list"] == out["parts_list"]

    kit = _entry(out, "K1")["id"]
    out = m.update_position_part(kit, quantity=3, critical=True, min_on_hand=4, notes="Viton, not nitrile")
    assert (_entry(out, "K1")["quantity"], _entry(out, "K1")["min_on_hand"]) == (3, 4)
    out = m.update_position_part(kit, critical=False)
    assert (_entry(out, "K1")["critical"], _entry(out, "K1")["min_on_hand"]) == (False, None)
    out = m.update_position_part(kit, role="consumable")
    assert _entry(out, "K1")["role"] == "consumable" and _entry(out, "K1")["notes"] == "Viton, not nitrile"

    out = m.remove_position_part(kit)
    assert [x["part"]["part_number"] for x in out["parts_list"]] == ["A1"]
    with pytest.raises(Invalid, match="already taken off"):
        m.remove_position_part(kit)
    # It can go back on once it's off.
    m.add_position_part(plant["pid"], plant["kit"], "consumable")

    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before


def test_a_parts_list_is_checked_before_anything_is_written(m, plant):
    m.add_position_part(plant["pid"], plant["a"], "replacement")
    before = len(m.s.log.since(0))
    with pytest.raises(Invalid, match="already on this position"):
        m.add_position_part(plant["pid"], plant["a"], "component")
    with pytest.raises(Invalid, match="already this position's replacement"):
        m.add_position_part(plant["pid"], plant["kit"], "replacement")
    with pytest.raises(Invalid, match="role is one of"):
        m.add_position_part(plant["pid"], plant["kit"], "spare")
    with pytest.raises(Invalid, match="more than 0"):
        m.add_position_part(plant["pid"], plant["kit"], quantity=0)
    with pytest.raises(Invalid, match="at most"):
        m.add_position_part(plant["pid"], plant["kit"], notes="x" * (service_mod.LONG_TEXT + 1))
    with pytest.raises(Invalid, match="minimum on hand"):
        m.add_position_part(plant["pid"], plant["kit"], critical=True, min_on_hand=-1)
    with pytest.raises(NotFound):
        m.add_position_part(plant["pid"], "no-such-part")
    with pytest.raises(NotFound):
        m.add_position_part("no-such-position", plant["kit"])
    kit = m.add_position_part(plant["pid"], plant["kit"])["parts_list"][1]["id"]
    with pytest.raises(Invalid, match="already this position's replacement"):
        m.update_position_part(kit, role="replacement")
    after = len(m.s.log.since(0))
    assert after == before + 1  # only the kit went on

    retired = m.create_position("Old pump")["id"]
    m.retire_position(retired)
    with pytest.raises(Invalid, match="retired"):
        m.add_position_part(retired, plant["kit"])


def test_a_parts_list_has_a_limit(m, plant, monkeypatch):
    monkeypatch.setattr(service_mod, "MAX_PARTS_EACH", 1)
    m.add_position_part(plant["pid"], plant["a"])
    with pytest.raises(LimitReached, match="at most 1 parts"):
        m.add_position_part(plant["pid"], plant["kit"])


def test_supersession_and_alternatives_flow_through_with_stock(m, plant):
    m.adjust_stock(plant["c"], plant["store"], 1)
    out = m.add_position_part(plant["pid"], plant["a"], "replacement", critical=True, min_on_hand=2)
    pump = out["parts_list"][0]
    assert pump["superseded_by"]["part_number"] == "B1"
    assert pump["use_instead"]["part_number"] == "B1" and pump["use_instead"]["on_hand"] == 0
    # C1 is interchangeable with B1, which replaced A1: an alternative.
    assert [(x["part_number"], x["on_hand"]) for x in pump["alternatives"]] == [("C1", 1)]
    assert pump["alternatives"][0]["stock"][0]["location"]["name"] == "Store"
    assert pump["usable_on_hand"] == 1 and pump["short"]
    assert pump["summary"] == ("A1 is superseded: use B1 instead. Critical spare: keep 2 on hand; 1 usable in stock, "
                               "short by 1.")

    # A chain (B1 superseded by D1) ends at the part to use; stock anywhere along it counts.
    d = m.create_part("D1", "Pump v3")["id"]
    m.supersede_part(plant["b"], d)
    m.adjust_stock(plant["b"], plant["store"], 1)
    pump = m.position(plant["pid"])["parts_list"][0]
    assert pump["superseded_by"]["part_number"] == "B1" and pump["use_instead"]["part_number"] == "D1"
    assert pump["usable_on_hand"] == 2 and not pump["short"]

    # A loop of supersessions (a mistake) doesn't hang the view.
    m.supersede_part(d, plant["a"])
    assert m.position(plant["pid"])["parts_list"][0]["use_instead"]["part_number"] == "D1"


def test_a_part_lists_where_its_used(m, plant):
    other = m.create_position("Pump B")["id"]
    m.add_position_part(plant["pid"], plant["kit"], quantity=2)
    m.add_position_part(other, plant["kit"], critical=True, min_on_hand=3)
    part = m.part(plant["kit"])
    assert [(u["position"]["name"], u["quantity"], u["critical"]) for u in part["used_at"]] == [
        ("Pump A", 2, False), ("Pump B", 1, True)]
    assert part["critical_min"] == 3 and part["critical_short"]
    m.adjust_stock(plant["kit"], plant["store"], 3)
    assert not m.part(plant["kit"])["critical_short"]
    # A retired position is out of the plant: it uses nothing.
    m.retire_position(other)
    assert [u["position"]["name"] for u in m.part(plant["kit"])["used_at"]] == ["Pump A"]
    assert next(p for p in m.parts() if p["id"] == plant["kit"])["used_at"][0]["quantity"] == 2


def test_critical_spares_short_and_positions_with_no_spare(m, plant):
    bare = m.create_position("Valve")["id"]
    m.add_position_part(plant["pid"], plant["a"], "replacement", critical=True)
    m.add_position_part(plant["pid"], plant["kit"], critical=True, min_on_hand=2)
    m.adjust_stock(plant["kit"], plant["store"], 1)
    assert summary(m)["critical_short"] == 2
    cover = m.spares_cover()
    assert [x["part"]["part_number"] for x in cover["short"]] == ["A1", "K1"]
    assert [x["position"]["name"] for x in cover["no_spare"]] == ["Pump A"]
    assert "without_parts_list" not in cover
    assert [p["id"] for p in m.spares_cover(include_unlisted=True)["without_parts_list"]] == [bare]

    m.adjust_stock(plant["c"], plant["store"], 1)  # an alternative on the shelf
    cover = m.spares_cover()
    assert cover["no_spare"] == [] and [x["part"]["part_number"] for x in cover["short"]] == ["K1"]
    m.adjust_stock(plant["kit"], plant["store"], 1)
    assert m.critical_spares_short() == [] and summary(m)["critical_short"] == 0


def test_the_daily_digest_mentions_spares_short(monkeypatch):
    from backend import config
    from backend.maintenance import daily
    from backend.services import email as email_service

    sent = []
    monkeypatch.setattr(email_service, "send", lambda to, subject, body, **k: sent.append(body))
    monkeypatch.setattr(config, "MAINTENANCE_ENABLED", True)
    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "MAINTENANCE_EMAILS", {"me@example.org"})
    db = mongomock.MongoClient()["daily_spares"]
    db.users.insert_one({"_id": ORG, "email": "me@example.org", "email_verified": True})
    store = GraphStore(":memory:", PROJECTORS)
    m = Maintenance(store, ORG)
    pid = m.create_position("Smoke alarm")["id"]
    m.create_task(pid, "Press test", 1, "weeks")
    battery = m.create_part("9V", "Battery")["id"]
    m.add_position_part(pid, battery, "replacement", critical=True, min_on_hand=2)
    assert daily.run(db, store)["emails"] == 1
    assert "Critical spares below the minimum" in sent[0] and "9V Battery for Smoke alarm: 0 usable, keep 2" in sent[0]


def test_work_orders_suggest_the_parts_list_and_draw_stock(m, plant):
    m.adjust_stock(plant["b"], plant["store"], 2)
    m.adjust_stock(plant["kit"], plant["store"], 5)
    m.add_position_part(plant["pid"], plant["kit"], "component", quantity=2)
    m.add_position_part(plant["pid"], plant["b"], "replacement")
    m.fit(plant["pid"], new_item={"name": "Old pump"}, on="2024-01-01")
    wo = m.open_work_order(plant["pid"], "Pump seized")
    assert [x["part"]["part_number"] for x in wo["suggested_parts"]] == ["B1", "K1"]
    assert wo["suggested_parts"][0]["part"]["stock"][0]["quantity"] == 2

    before = len(m.s.log.since(0))
    with pytest.raises(Invalid, match="only 2 of B1"):
        m.close_work_order(wo["id"], [{"kind": "replace", "part_id": plant["b"], "from_location_id": plant["store"],
                                       "quantity": 3}])
    with pytest.raises(Invalid, match="give the part_id"):
        m.close_work_order(wo["id"], [{"kind": "repair", "from_location_id": plant["store"]}])
    with pytest.raises(Invalid, match="only 5 of K1"):  # two actions drawing on one shelf
        m.close_work_order(wo["id"], [
            {"kind": "repair", "part_id": plant["kit"], "from_location_id": plant["store"], "quantity": 3},
            {"kind": "repair", "part_id": plant["kit"], "from_location_id": plant["store"], "quantity": 3}])
    assert len(m.s.log.since(0)) == before

    done = m.close_work_order(wo["id"], [
        {"kind": "replace", "part_id": plant["b"], "from_location_id": plant["store"]},
        {"kind": "repair", "part_id": plant["kit"], "from_location_id": plant["store"]},
    ], on=date.today().isoformat())
    # The new item is made from the part; the kit's quantity comes from the parts list.
    # An action with no failure mode, or nothing fitted, says so plainly (null, not []).
    assert done["actions"][0]["failure_mode"] is None and done["actions"][1]["fitted"] is None
    fitted = done["actions"][0]["fitted"]
    assert (fitted["name"], fitted["part_number"], fitted["manufacturer"]) == ("Pump v2", "B1", "Grundfos")
    assert [(p["part_number"], p["quantity"]) for p in done["parts"]] == [("B1", 1), ("K1", 2)]
    assert m.part(plant["b"])["on_hand"] == 1 and m.part(plant["kit"])["on_hand"] == 3

    # A part named on a replace with its own new item keeps the item, and fills its part number.
    wo = m.open_work_order(plant["pid"], "Again")
    done = m.close_work_order(wo["id"], [{"kind": "replace", "part_id": plant["b"],
                                          "new_item": {"name": "Pump v2", "serial": "S9"}}])
    assert (done["actions"][0]["fitted"]["serial"], done["actions"][0]["fitted"]["part_number"]) == ("S9", "B1")
    assert m.part(plant["b"])["on_hand"] == 1  # no store named: stock unchanged


def test_a_copy_takes_the_parts_list(m, plant):
    m.add_position_part(plant["pid"], plant["a"], "replacement", critical=True, min_on_hand=2, notes="button kit")
    copy = m.copy_position(plant["pid"], "Pump C")
    [entry] = copy["parts_list"]
    assert (entry["part"]["part_number"], entry["role"], entry["min_on_hand"], entry["notes"]) == (
        "A1", "replacement", 2, "button kit")
    assert len(m.part(plant["a"])["used_at"]) == 2


def test_rest_routes(monkeypatch, plant, m):
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app
    from backend.routers import maintenance as router

    monkeypatch.setattr(db, "_db", mongomock.MongoClient()["reliafy_spares"])
    monkeypatch.setattr(db, "_simulated", True)
    monkeypatch.setattr(router, "_store", m.s)
    monkeypatch.setattr(config, "MAINTENANCE_ENABLED", True)
    monkeypatch.setattr(config, "MAINTENANCE_EMAILS", {"a@x.com"})
    client = TestClient(app)
    app.dependency_overrides[get_current_user] = lambda: {
        "uid": ORG, "email": "a@x.com", "name": "A", "email_verified": True}
    try:
        api = "/api/maintenance"
        out = client.post(f"{api}/positions/{plant['pid']}/parts", json={
            "part_id": plant["a"], "role": "replacement", "critical": True, "notes": "button kit"})
        assert out.status_code == 200, out.text
        lid = out.json()["parts_list"][0]["id"]
        bad = client.post(f"{api}/positions/{plant['pid']}/parts", json={"part_id": plant["kit"], "role": "nope"})
        assert bad.status_code == 422
        out = client.patch(f"{api}/position-parts/{lid}", json={"min_on_hand": 3}).json()
        assert out["parts_list"][0]["min_on_hand"] == 3
        assert client.get(f"{api}/positions/{plant['pid']}/parts").json()["parts_list"][0]["notes"] == "button kit"
        assert client.get(f"{api}/parts/{plant['a']}").json()["used_at"][0]["listing_id"] == lid
        overview = client.get(f"{api}/overview").json()
        assert overview["summary"]["critical_short"] == 1 and overview["critical_spares"][0]["id"] == lid
        cover = client.get(f"{api}/spares", params={"include_unlisted": True}).json()
        assert cover["no_spare"][0]["id"] == lid and cover["without_parts_list"] == []
        assert client.delete(f"{api}/position-parts/{lid}").json()["parts_list"] == []
        assert client.delete(f"{api}/position-parts/nope").status_code == 404
    finally:
        app.dependency_overrides.clear()
