"""Reliafy Maintenance: work order statuses, assignment, labour, parts, costs and
checklists."""

import pytest

from backend.maintenance.service import PROJECTORS, Invalid, Maintenance
from backend.maintenance.store import GraphStore


@pytest.fixture()
def m():
    return Maintenance(GraphStore(":memory:", PROJECTORS), "user-w", "tester")


class _Study:
    id, name, system = "s", "HWS RCM", "Hot water"
    functions = [{"id": "f", "text": "Hot water", "failures": [{"id": "ff", "text": "None", "modes": [
        {"id": "m1", "text": "Anode depleted", "consequence": "operational",
         "decision": {"outcome": "fixed_interval", "interval": 1, "interval_unit": "days",
                      "task": "Replace anode"}}]}]}]


def test_task_checklist_travels_to_its_work_order(m):
    pos = m.position_from_rcm(_Study())["position"]
    task = pos["tasks"][0]
    m.update_task(task["id"], instructions="Isolate power and water first.",
                  checklist=["Isolate power", "Drain 10 L", "Fit anode", "Refill and bleed"])
    [wo] = m.generate_work_orders(30)
    detail = m.work_order(wo["id"])
    assert detail["instructions"].startswith("Isolate") and len(detail["checklist"]) == 4
    m.check_item(wo["id"], 0)
    m.check_item(wo["id"], 1)
    assert [c["done"] for c in m.work_order(wo["id"])["checklist"]] == [True, True, False, False]
    with pytest.raises(Invalid):
        m.check_item(wo["id"], 9)


def test_statuses_assignment_and_costs(m):
    pid = m.create_position("Pool pump")["id"]
    wo = m.open_work_order(pid, "Noisy bearing")
    m.update_work_order(wo["id"], assignee="Derryn", planned_for="2026-10-20")
    m.set_work_status(wo["id"], "waiting", "bearings on order")
    m.add_part_used(wo["id"], "6203 bearing", quantity=2, unit_cost=12.5)
    m.add_cost(wo["id"], "Courier", 15)
    m.set_work_status(wo["id"], "in_progress")
    detail = m.log_labour(wo["id"], 1.5, who="Derryn", rate=80)
    assert detail["status"] == "in_progress" and detail["assignee"] == "Derryn"
    assert [h["status"] for h in detail["status_history"]] == ["open", "waiting", "in_progress"]
    assert detail["totals"] == {"hours": 1.5, "labour": 120.0, "parts": 25.0, "other": 15.0, "total": 160.0}
    assert m.work_orders("open")[0]["id"] == wo["id"]  # in progress still counts as open
    courier = detail["other_costs"][0]["id"]
    assert m.remove_entry(courier)["totals"]["total"] == 145.0
    m.close_work_order(wo["id"], [{"kind": "repair"}])
    assert m.log_labour(wo["id"], 0.5)["totals"]["hours"] == 2.0  # timesheets come late
    with pytest.raises(Invalid):
        m.set_work_status(wo["id"], "planned")  # closed
    with pytest.raises(Invalid):
        m.log_labour(wo["id"], 0)


def test_rebuild_matches_with_work_entries(m):
    test_statuses_assignment_and_costs(m)
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before
