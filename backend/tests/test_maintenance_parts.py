"""Reliafy Maintenance: the parts catalogue, stock by location, and parts issued
to work orders."""

import pytest

from backend.maintenance.service import PROJECTORS, Invalid, Maintenance
from backend.maintenance.store import GraphStore


def test_stock_received_issued_to_work_and_low():
    m = Maintenance(GraphStore(":memory:", PROJECTORS), "user-p")
    shed = m.create_location("Shed")["id"]
    anode = m.create_part("RH-AN-315", "Magnesium anode 315 L", "Rheem", unit_cost=65)
    with pytest.raises(Invalid):
        m.create_part("rh-an-315", "Duplicate")
    m.adjust_stock(anode["id"], shed, 3, "bought 3")
    m.set_reorder_point(anode["id"], shed, 1)
    pid = m.create_position("Hot water system")["id"]
    wo = m.open_work_order(pid, "Replace anode")
    detail = m.add_part_used(wo["id"], part_id=anode["id"], from_location_id=shed, quantity=2)
    used = detail["parts"][0]
    assert (used["part"], used["part_number"], used["unit_cost"]) == ("Magnesium anode 315 L", "RH-AN-315", 65)
    assert detail["totals"]["parts"] == 130
    part = m.part(anode["id"])
    assert part["on_hand"] == 1 and part["low"] and part["used_last_year"] == 2 and part["months_of_cover"] == 6
    with pytest.raises(Invalid):
        m.add_part_used(wo["id"], part_id=anode["id"], from_location_id=shed, quantity=5)  # only 1 left
    new = m.create_part("RH-AN-315B", "Anode (new design)", "Rheem")
    assert m.supersede_part(anode["id"], new["id"])["superseded_by"]["part_number"] == "RH-AN-315B"
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before
