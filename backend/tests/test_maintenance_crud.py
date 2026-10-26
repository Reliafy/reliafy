"""Every level of the maintenance tree can be taken out of use and brought
back, and the fields that had no edit before can be changed: locations, items,
parts, manufacturers and measurement points retire (with their refusals) and
restore; positions, tasks, failure modes, classes, conditions, groups,
connections and document links restore; connections, documents and photos are
edited; coordinates cleared; a wrong supersession unlinked. Retired things leave
the lists and the matches, keep their history, and a rebuilt graph is the same."""

from datetime import date, timedelta

import pytest

from backend.maintenance.service import PROJECTORS, Invalid, Maintenance
from backend.maintenance.store import GraphStore, new_id

ORG = "user-crud"


@pytest.fixture()
def m():
    return Maintenance(GraphStore(":memory:", PROJECTORS), ORG, "tester")


def _ago(days: int) -> str:
    return (date.today() - timedelta(days=days)).isoformat()


def _same_after_rebuild(m):
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before


# ---- locations ----------------------------------------------------------------------

def test_a_location_retires_only_when_empty_and_comes_back(m):
    site = m.create_location("Site")["id"]
    store = m.create_location("Store A", parent_id=site)["id"]
    pump = m.create_position("Pump", location_id=store)["id"]
    with pytest.raises(Invalid, match="1 position is located at Store A"):
        m.retire_location(store)
    m.update_position(pump, location_id=None)
    spare = m.create_item("Spare motor")["id"]
    m.place_item(spare, store)
    with pytest.raises(Invalid, match="placed at Store A"):
        m.retire_location(store)
    m.place_item(spare, site)
    part = m.create_part("B-1", "Bearing")["id"]
    m.adjust_stock(part, store, 2)
    with pytest.raises(Invalid, match="Stock is on hand"):
        m.retire_location(store)
    m.adjust_stock(part, store, -2)
    wo = m.open_work_order(None, "Walk the store", location_id=store)["id"]
    with pytest.raises(Invalid, match="open work orders"):
        m.retire_location(store)
    m.cancel_work_order(wo, "x")
    with pytest.raises(Invalid, match="Locations inside it are still in use"):
        m.retire_location(site)
    task = m.create_task(None, "Store round", 1, "months", location_id=store)["id"]
    out = m.retire_location(store, "closed")
    assert out["tasks_retired"] == [task]
    assert [x["name"] for x in m.locations()] == ["Site"] and m.location_tree()[0]["children"] == []
    assert m.location(store)["retired"] is True
    with pytest.raises(Invalid, match="has been retired"):
        m.create_position("Fan", location_id=store)
    with pytest.raises(Invalid, match="has been retired"):
        m.adjust_stock(part, store, 1)
    with pytest.raises(Invalid, match="already retired"):
        m.retire_location(store)
    back = m.restore_location(store)
    assert back["retired"] is False and back["tasks_restored"] == [task]
    assert [t["name"] for t in m.location(store)["tasks"]] == ["Store round"]
    with pytest.raises(Invalid, match="isn't retired"):
        m.restore_location(store)
    _same_after_rebuild(m)


def test_a_location_tree_retires_with_cascade_and_restores_top_down(m):
    site = m.create_location("Site")["id"]
    area = m.create_location("Area", parent_id=site)["id"]
    room = m.create_location("Room", parent_id=area)["id"]
    out = m.retire_location(site, cascade=True)
    assert out["also_retired"] == [room, area] and m.locations() == []
    with pytest.raises(Invalid, match="Site \\(what it sits inside\\) is retired"):
        m.restore_location(area)
    m.restore_location(site)
    m.restore_location(area)
    assert m.location(site)["children"][0]["id"] == area
    assert m.location(room)["retired"] is True
    _same_after_rebuild(m)


# ---- positions -------------------------------------------------------------------------

def test_a_position_subtree_retires_with_cascade_all_or_nothing(m):
    plant = m.create_position("Plant")["id"]
    pump = m.create_position("Pump", parent_id=plant)["id"]
    motor = m.create_position("Motor", parent_id=pump)["id"]
    m.fit(motor, new_item={"name": "M1"})
    with pytest.raises(Invalid, match="cascade true"):
        m.retire_position(plant)
    with pytest.raises(Invalid, match="Motor: something is still fitted"):
        m.retire_position(plant, cascade=True)
    assert not m.position(pump)["retired"]
    m.remove(motor)
    out = m.retire_position(plant, "demolished", cascade=True)
    assert out["also_retired"] == [motor, pump]
    assert all(m.position(p)["retired"] for p in (plant, pump, motor))
    with pytest.raises(Invalid, match="Plant \\(what it sits inside\\) is retired: restore that first"):
        m.restore_position(pump)
    assert m.restore_position(plant)["retired"] is False
    assert m.restore_position(pump)["retired"] is False
    assert m.tree()[0]["children"][0]["id"] == pump
    _same_after_rebuild(m)


def test_restoring_a_position_wants_its_location_live(m):
    loc = m.create_location("Yard")["id"]
    p = m.create_position("Crane", location_id=loc)["id"]
    m.update_position(p, location_id=None)
    m.retire_position(p)
    m.retire_location(loc)
    m.restore_position(p)  # no location set on it: fine
    q = m.create_position("Hoist")["id"]
    m.restore_location(loc)
    m.update_position(q, location_id=loc)
    m.retire_position(q)
    m.update_position(p, location_id=None)
    m.retire_location(loc)
    with pytest.raises(Invalid, match="Its location Yard is retired"):
        m.restore_position(q)


# ---- items ------------------------------------------------------------------------------

def test_an_item_retires_when_out_of_service_and_comes_back_with_its_tasks(m):
    pump = m.create_position("Pump")["id"]
    item = m.fit(pump, new_item={"name": "Pump N1", "serial": "N1"}, on=_ago(100))["fitted"]["item"]["id"]
    with pytest.raises(Invalid, match="is fitted to Pump: remove it first"):
        m.retire_item(item)
    m.remove(pump, on=_ago(1), reason="planned")
    wo = m.open_work_order(None, "Strip for parts", item_id=item)["id"]
    with pytest.raises(Invalid, match="open work orders"):
        m.retire_item(item)
    m.cancel_work_order(wo, "no")
    task = m.create_task(None, "Rotate shaft", 1, "months", item_id=item)["id"]
    out = m.retire_item(item, "scrapped")
    assert out["tasks_retired"] == [task]
    assert m.item(item)["retired"] is True and m.items() == []
    assert [f["item"]["id"] for f in m.position(pump)["fitments"]] == [item]  # the history keeps it
    with pytest.raises(Invalid, match="retired \\(disposed of\\)"):
        m.fit(pump, item_id=item)
    with pytest.raises(Invalid, match="has been retired"):
        m.create_task(None, "x", 1, item_id=item)
    back = m.restore_item(item)
    assert back["retired"] is False and back["tasks_restored"] == [task]
    assert [i["id"] for i in m.items()] == [item]
    m.fit(pump, item_id=item)
    _same_after_rebuild(m)


def test_an_item_with_positions_inside_it_in_use_stays(m):
    engine = m.create_item("Engine E1")["id"]
    turbo = m.create_position("Turbo", parent_id=engine)["id"]
    with pytest.raises(Invalid, match="Positions inside it are still in use"):
        m.retire_item(engine)
    m.retire_position(turbo)
    m.retire_item(engine)
    with pytest.raises(Invalid, match="retired \\(disposed of\\)"):
        m.create_position("Turbo 2", parent_id=engine)


# ---- tasks and failure modes ----------------------------------------------------------------

def test_a_task_restores_as_it_was(m):
    pump = m.create_position("Pump")["id"]
    task = m.create_task(pump, "Grease", 6, "months", last_done=_ago(30))["id"]
    m.retire_task(task, "dup")
    assert m.position(pump)["tasks"] == []
    with pytest.raises(Invalid, match="isn't retired"):
        m.restore_task(m.create_task(pump, "Other", 1)["id"])
    back = m.restore_task(task)
    assert back["last_done"] == _ago(30) and back["interval"] == 6
    m.retire_task(task)
    m.retire_position(pump)
    with pytest.raises(Invalid, match="Pump \\(what the task is on\\) is retired"):
        m.restore_task(task)


def test_a_failure_mode_restores_with_its_decision_and_task(m):
    pump = m.create_position("Pump")["id"]
    fn = m.add_function(pump, "Pump water")["id"]
    ff = m.add_functional_failure(fn, "No flow")["id"]
    mode = m.add_failure_mode(pump, "Bearing worn", functional_failure_id=ff)["id"]
    m.decide_failure_mode(mode, "operational", {"outcome": "fixed_interval", "task": "Replace bearings",
                                                "interval": 12, "interval_unit": "months"})
    gone = m.retire_failure_mode(mode)
    task = gone["task_retired"]
    assert m.position(pump)["failure_modes"] == [] and m.position(pump)["tasks"] == []
    twin = m.add_failure_mode(pump, "bearing worn")["id"]
    with pytest.raises(Invalid, match="is a failure mode on Pump now"):
        m.restore_failure_mode(mode)
    m.retire_failure_mode(twin)
    back = m.restore_failure_mode(mode)
    assert back["decision"]["outcome"] == "fixed_interval" and back["tasks_restored"] == [task]
    assert [t["id"] for t in m.position(pump)["tasks"]] == [task]
    sheet = m.rcm_worksheet(pump, "this")["positions"][0]
    assert sheet["functions"][0]["failures"][0]["modes"][0]["id"] == mode
    # Its functional failure deleted meanwhile: it comes back unassigned.
    m.retire_failure_mode(mode)
    m.remove_functional_failure(ff)
    m.restore_failure_mode(mode)
    assert [x["id"] for x in m.rcm_worksheet(pump, "this")["positions"][0]["unassigned"]] == [mode]
    with pytest.raises(Invalid, match="was deleted"):
        m.restore_task(m.retire_failure_mode(mode)["task_retired"])
    _same_after_rebuild(m)


# ---- parts ------------------------------------------------------------------------------------

def test_a_part_retires_when_nothing_uses_it_and_a_wrong_link_unlinks(m):
    store = m.create_location("Store")["id"]
    pump = m.create_position("Pump")["id"]
    old = m.create_part("SEAL-1", "Seal")["id"]
    new = m.create_part("SEAL-2", "Seal, new")["id"]
    kit = m.create_part("KIT-1", "Seal kit")["id"]
    m.adjust_stock(old, store, 3)
    m.add_position_part(pump, old)
    m.add_component(kit, old)
    with pytest.raises(Invalid, match="in stock \\(3 at Store\\).*parts list of Pump.*structure of KIT-1") as err:
        m.retire_part(old)
    assert "remove_from_position" in str(err.value) and "remove_component" in str(err.value)
    m.adjust_stock(old, store, -3)
    for entry in m.position_parts(pump)["parts_list"]:
        if entry["part"]["id"] == old:
            m.remove_position_part(entry["id"])
    m.remove_component(kit, old)
    m.supersede_part(old, new)
    m.mark_interchangeable(old, kit)
    m.retire_part(old, "obsolete")
    assert m.part(old)["retired"] is True and [p["part_number"] for p in m.parts()] == ["KIT-1", "SEAL-2"]
    with pytest.raises(Invalid, match="retired from the catalogue"):
        m.add_position_part(pump, old)
    with pytest.raises(Invalid, match="retired from the catalogue"):
        m.create_item("x", part_id=old)
    with pytest.raises(Invalid, match="retired from the catalogue"):
        m.adjust_stock(old, store, 1)
    m.restore_part(old)
    assert m.part(old)["superseded_by"]["id"] == new
    with pytest.raises(Invalid, match="isn't superseded by KIT-1"):
        m.unlink_parts(old, kit, "superseded_by")
    assert m.unlink_parts(old, new, "superseded_by")["superseded_by"] is None
    assert [a["id"] for a in m.part(old)["interchangeable"]] == [kit]
    assert m.unlink_parts(old, kit)["interchangeable"] == []
    with pytest.raises(Invalid, match="aren't marked interchangeable"):
        m.unlink_parts(old, kit)
    assert m.part(kit)["interchangeable"] == []
    _same_after_rebuild(m)


def test_a_parts_numbers_clear_and_a_reorder_point_clears(m):
    store = m.create_location("Store")["id"]
    part = m.create_part("B-1", "Bearing", unit_cost=12.5)["id"]
    m.update_part(part, lead_time_days=30, service_level=0.95)
    cleared = m.update_part(part, unit_cost=None, lead_time_days=None)
    assert cleared["unit_cost"] is None and cleared["lead_time_days"] is None and cleared["service_level"] == 0.95
    m.set_reorder_point(part, store, 2)
    m.adjust_stock(part, store, 1)
    assert m.part(part)["stock"][0]["reorder_point"] == 2
    assert m.set_reorder_point(part, store, None)["stock"][0]["reorder_point"] is None


# ---- measurement points ----------------------------------------------------------------------

def test_a_point_retires_unless_a_task_or_alarm_depends_on_it(m):
    pump = m.create_position("Pump")["id"]
    hours = m.add_point(pump, "Run hours", "counter", "hours")["id"]
    task = m.create_task(pump, "Grease", 500, "hours", point_id=hours)["id"]
    with pytest.raises(Invalid, match="Grease goes by Run hours"):
        m.retire_point(hours)
    m.update_task(task, point_id="")
    vib = m.add_point(pump, "Vibration", "condition", "mm/s", alarm_above=10, tag="VT-1", source="automated")["id"]
    raised = m.ingest([{"tag": "VT-1", "value": 12}])
    assert raised["work_orders_raised"]
    with pytest.raises(Invalid, match="open alarm work order"):
        m.retire_point(vib)
    m.cancel_work_order(raised["work_orders_raised"][0]["id"], "test")
    m.record_reading(hours, 100)
    m.retire_point(hours, "meter removed")
    m.retire_point(vib)
    assert m.position(pump)["measurements"] == [] and m.point(hours)["retired"] is True
    assert m.point(hours)["readings"]  # kept
    with pytest.raises(Invalid, match="has been retired"):
        m.record_reading(hours, 200)
    assert m.ingest([{"tag": "VT-1", "value": 1}])["unknown_tags"] == {"VT-1": 1}  # the tag is freed
    other = m.add_point(pump, "Vibration 2", "condition", "mm/s", tag="VT-1", source="automated")["id"]
    with pytest.raises(Invalid, match="Tag VT-1 is used by another point now"):
        m.restore_point(vib)
    m.retire_point(other)
    assert m.restore_point(vib)["retired"] is False
    assert m.restore_point(hours)["reading"] == 100
    with pytest.raises(Invalid, match="A task by use goes by a counter"):
        m.update_task(task, point_id=vib)
    m.update_task(task, point_id=hours)
    _same_after_rebuild(m)


# ---- classes, conditions, manufacturers, groups, connections ----------------------------------

def test_classes_and_conditions_restore_under_a_live_parent(m):
    top = m.create_item_class("Rotating")["id"]
    pump = m.create_item_class("Pump", parent_id=top)["id"]
    m.retire_item_class(pump)
    m.retire_item_class(top)
    with pytest.raises(Invalid, match="Rotating \\(the class it sits inside\\) is retired"):
        m.restore_item_class(pump)
    m.restore_item_class(top)
    m.create_item_class("Pump", parent_id=top)
    with pytest.raises(Invalid, match="already an item class called Pump there"):
        m.restore_item_class(pump)
    zone = m.create_condition("Hazardous area")["id"]
    z1 = m.create_condition("Zone 1", parent_id=zone)["id"]
    p = m.create_position("Pump")["id"]
    m.apply_condition(p, z1)
    m.retire_condition(z1)
    assert m.conditions_of(p)["conditions"] == []
    assert m.restore_condition(z1)["name"] == "Zone 1"
    assert [c["condition"]["name"] for c in m.conditions_of(p)["conditions"]] == ["Zone 1"]
    _same_after_rebuild(m)


def test_a_manufacturer_retires_when_unlinked_and_leaves_the_matches(m):
    ksb = m.create_manufacturer("KSB", ["K.S.B."])["id"]
    part = m.create_part("P-1", "Pump", manufacturer_id=ksb)["id"]
    with pytest.raises(Invalid, match="0 item\\(s\\) and 1 part\\(s\\) are linked to KSB"):
        m.retire_manufacturer(ksb)
    m.link_manufacturer(part, None)
    m.retire_manufacturer(ksb, "duplicate")
    assert m.manufacturers() == [] and m.manufacturer(ksb)["retired"] is True
    assert m.match_manufacturer("K.S.B.")["match"] is None
    with pytest.raises(Invalid, match="retired from the register"):
        m.link_manufacturer(part, ksb)
    again = m.create_manufacturer("KSB")["id"]  # the name is free while it's retired
    with pytest.raises(Invalid, match="KSB is already in the register"):
        m.restore_manufacturer(ksb)
    m.retire_manufacturer(again)
    assert m.restore_manufacturer(ksb)["retired"] is False
    _same_after_rebuild(m)


def test_a_connection_is_edited_reconnected_and_a_group_restored(m):
    tank = m.create_position("Tank")["id"]
    pump = m.create_position("Pump")["id"]
    hose = m.create_position("Hose")["id"]
    link = m.connect(tank, pump, "flow", "water")["id"]
    out = m.update_interface(link, kind="mechanical", name="Suction", rating="DN80", realised_by=hose)
    assert (out["kind"], out["name"], out["rating"], out["realised_by"]["id"]) == ("mechanical", "Suction", "DN80", hose)
    assert not m.update_interface(link, realised_by=None, rating="")["realised_by"]
    m.connect(tank, pump, "flow")
    with pytest.raises(Invalid, match="already connects to Pump \\(flow\\)"):
        m.update_interface(link, kind="flow")
    m.disconnect(link)
    with pytest.raises(Invalid, match="was removed: reconnect it first"):
        m.update_interface(link, name="x")
    assert m.reconnect(link)["kind"] == "mechanical"
    assert len(m.connections(tank)["downstream"]) == 2
    a, b = m.create_position("Pump A")["id"], m.create_position("Pump B")["id"]
    group = m.create_group("Pumps", [a, b])["id"]
    m.retire_group(group, "rebuilt")
    assert m.groups_of(a) == [] and m.group(group)["retired"]
    with pytest.raises(Invalid, match="restore it first"):
        m.update_group(group, name="x")
    m.retire_position(b)
    with pytest.raises(Invalid, match="Pump B \\(in the group\\) is retired"):
        m.restore_group(group)
    m.restore_position(b)
    assert m.restore_group(group)["retired"] is False and [g["id"] for g in m.groups_of(a)] == [group]
    _same_after_rebuild(m)


def test_documents_photos_and_coordinates_are_edited(m):
    pump = m.create_position("Pump")["id"]
    doc = m.add_document("https://example.com/manual.pdf", "Manual", "other", target_id=pump)["id"]
    out = m.update_document(doc, title="Pump manual", kind="manual")
    assert (out["title"], out["kind"]) == ("Pump manual", "manual")
    with pytest.raises(Invalid, match="kind is one of"):
        m.update_document(doc, kind="poem")
    m.remove_document(doc)
    assert m.position(pump)["documents"] == []
    assert m.restore_document(doc)["removed"] is False
    assert [d["title"] for d in m.position(pump)["documents"]] == ["Pump manual"]
    photo = new_id()
    m.add_photo(photo, pump, {"width": 10, "height": 10}, "Front")
    assert m.update_photo(photo, "Nameplate")["caption"] == "Nameplate"
    assert m.update_photo(photo, "")["caption"] == ""
    m.set_coordinates(pump, -27.5, 153.0)
    assert m.clear_coordinates(pump)["coordinates"] is None
    assert m.clear_coordinates(pump)["coordinates"] is None  # nothing to clear: no event
    assert m.position(pump).get("coordinates") is None
    _same_after_rebuild(m)


def test_events_read_newest_first_with_seq_and_forward_from_a_seq(m):
    p = m.create_position("Pump")["id"]
    m.update_position(p, name="Pump A")
    m.retire_position(p)
    events = m.s.events(ORG, 10)
    assert [e["type"] for e in events] == ["position.retired", "position.updated", "position.created"]
    assert [e["seq"] for e in events] == [3, 2, 1] and events[0]["actor"] == "tester"
    assert [e["seq"] for e in m.s.events(ORG, 10, since=1)] == [2, 3]
    assert [e["type"] for e in m.s.events(ORG, 10, type="position.updated")] == ["position.updated"]


def test_the_code_before_the_new_events_replays_them_harmlessly(m):
    """An older process passes over event types it doesn't know (logged, skipped):
    the rest of the log still projects, so a rolling deploy never breaks a graph."""
    loc = m.create_location("Store")["id"]
    item = m.create_item("Spare")["id"]
    m.retire_location(loc)
    m.retire_item(item)
    m.restore_item(item)
    old_types = {k: v for k, v in PROJECTORS.items() if not k.endswith((".restored",)) and k not in (
        "location.retired", "item.retired", "part.retired", "manufacturer.retired", "point.retired",
        "interface.updated", "document.updated", "photo.updated", "coordinates.cleared",
        "part.supersession_cleared", "parts.not_interchangeable")}
    old = GraphStore(":memory:", old_types)
    for e in m.s.log.since(0, 10_000):
        old.log.append({"id": new_id(), "org": e["org"], "type": e["type"], "at": "", "actor": None,
                        "payload": e["payload"]})
    old.sync()
    assert old.node(ORG, loc)["name"] == "Store" and "retired" not in old.node(ORG, loc)
    assert {s["why"] for s in old.skipped()} == {"UnknownEvent in location.retired", "UnknownEvent in item.retired",
                                                "UnknownEvent in item.restored"}
