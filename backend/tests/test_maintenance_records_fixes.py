"""Reliafy Maintenance: records that came out wrong in persona walkthroughs (Nov 2026).

- A serial typed on a replacement with no name is kept (the item is named after
  what it replaces).
- A task overdue when it goes into a package stays overdue until it's done.
- An inspection that finds a child (the seal in the pump) failed records it there, and
  the seal's life is interval censored from the last good check to the finding.
- A failure report counts the item as failed on the day it occurred, and a replacement
  for the same failure ends the same life (never a second failure).
- A corrective action raises a work order linked both ways.
- One package's visit can be raised on its own.

Every test that writes compares the rebuilt graph with the live one."""

from datetime import date

import pytest

from backend.maintenance import service
from backend.maintenance.service import PROJECTORS, Invalid, Maintenance
from backend.maintenance.store import GraphStore


@pytest.fixture()
def today(monkeypatch):
    class Clock:
        day = date(2026, 11, 12)

        def set(self, text):
            self.day = date.fromisoformat(text)

    clock = Clock()
    monkeypatch.setattr(service.time_zones, "today", lambda name=None: clock.day)
    return clock


@pytest.fixture()
def m(today):
    return Maintenance(GraphStore(":memory:", PROJECTORS), "user-rf", "tester")


def _rebuilds(m):
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before


def _days(a, b):
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


# ---- 1. a serial typed with no name ------------------------------------------------------

def test_a_serial_with_no_name_is_kept_and_named_after_the_part(m):
    pump = m.create_position("P-202", position_class="Pump mechanical seal 65 mm")["id"]
    part = m.create_part("MS-65-SIC", "Cartridge mechanical seal 65 mm")["id"]
    old = m.create_item("Seal", serial="MS65-0017", part_id=part)["id"]
    m.fit(pump, item_id=old, on="2024-07-02")
    wo = m.open_work_order(pump, "Replace leaking seal")
    m.close_work_order(wo["id"], [{"kind": "replace", "reason": "failure", "new_item": {"name": "", "serial": "MS65-0031"}}])
    fitted = m.position(pump)["fitted"]["item"]
    assert fitted["serial"] == "MS65-0031"
    assert fitted["name"] == "Cartridge mechanical seal 65 mm"
    _rebuilds(m)


def test_a_serial_with_a_part_from_stock_is_kept(m):
    pump = m.create_position("P-202")["id"]
    part = m.create_part("MS-65-SIC", "Cartridge mechanical seal 65 mm")["id"]
    store = m.create_location("Store")["id"]
    m.adjust_stock(part, store, 2)
    m.fit(pump, new_item={"name": "Seal", "serial": "MS65-0017"}, on="2024-07-02")
    wo = m.open_work_order(pump, "Replace leaking seal")
    m.close_work_order(wo["id"], [{"kind": "replace", "reason": "failure", "part_id": part, "from_location_id": store,
                                   "new_item": {"name": "", "serial": "MS65-0031"}}])
    fitted = m.position(pump)["fitted"]["item"]
    assert (fitted["name"], fitted["serial"]) == ("Cartridge mechanical seal 65 mm", "MS65-0031")


def test_a_serial_with_nothing_fitted_before_is_named_after_the_class(m):
    pump = m.create_position("P-203", position_class="Pump mechanical seal 65 mm")["id"]
    wo = m.open_work_order(pump, "Fit the seal")
    m.close_work_order(wo["id"], [{"kind": "replace", "new_item": {"serial": "MS65-0040"}}])
    fitted = m.position(pump)["fitted"]["item"]
    assert (fitted["name"], fitted["serial"]) == ("Pump mechanical seal 65 mm", "MS65-0040")


# ---- 2. overdue tasks put into a package stay overdue ------------------------------------------

def _station(m):
    station = m.create_position("Low-lift pump station")["id"]
    pump = m.create_position("P-101", parent_id=station)["id"]
    seal = m.create_task(pump, "Check the mechanical seal", 1, "months", last_done="2026-10-06")["id"]
    vib = m.create_task(pump, "Measure vibration", 1, "months", last_done="2026-10-20")["id"]
    return station, pump, seal, vib


def test_an_overdue_task_put_into_a_package_stays_overdue_until_done(m, today):
    station, pump, seal, vib = _station(m)
    before = m._task_view(m._get(seal, "Task"))
    assert (before["next_due"], before["overdue"]) == ("2026-11-06", True)
    pkg = m.create_package("Low-lift monthly round", position_id=station, every=1, unit="months", weekday="monday",
                           nth=3, anchor="2026-11-01", tasks=[seal, vib])
    view = m._task_view(m._get(seal, "Task"))
    # Still overdue from its own date, not moved to the visit on 16 Nov.
    assert (view["next_due"], view["overdue"]) == ("2026-11-06", True)
    assert view["overdue_before_package"] == {"due": "2026-11-06", "since": "2026-11-12"}
    # The one that wasn't late goes by the package's visit as before.
    other = m._task_view(m._get(vib, "Task"))
    assert (other["next_due"], other["overdue"]) == ("2026-11-16", False)
    assert "overdue_before_package" not in other
    rows = {t["id"]: t for t in m.due_tasks(30)}
    assert rows[seal]["overdue"] and rows[seal]["next_due"] == "2026-11-06"
    page = {t["task_id"]: t for t in m.package(pkg["id"])["tasks"]}
    assert page[seal]["overdue"] and page[seal]["overdue_before_package"]["due"] == "2026-11-06"
    _rebuilds(m)
    # Done on the package's visit: it's on time again and goes by the package.
    raised = m.raise_package_visit(pkg["id"])
    wo = raised["work_order"]
    for t in (seal, vib):
        m.mark_line(wo["id"], t, "done")
    m.close_work_order(wo["id"], [{"kind": "inspect", "finding": "ok"}])
    view = m._task_view(m._get(seal, "Task"))
    assert not view["overdue"] and "overdue_before_package" not in view
    _rebuilds(m)


def test_an_overdue_task_added_to_a_package_stays_overdue(m):
    station, pump, seal, vib = _station(m)
    pkg = m.create_package("Low-lift monthly round", position_id=station, every=1, unit="months", weekday="monday",
                           nth=3, anchor="2026-11-01", tasks=[vib])
    m.add_package_task(pkg["id"], seal)
    view = m._task_view(m._get(seal, "Task"))
    assert (view["next_due"], view["overdue"]) == ("2026-11-06", True)
    events = [e["type"] for e in m.s.events(m.org, 100)]
    assert events.count("task.overdue_carried") == 1
    _rebuilds(m)


# ---- 3. found failed on the seal inside the pump: interval censored ----------------------------

def _pump_with_seal(m, today):
    pump = m.create_position("Treated water pump P-202", position_class="Split-case pump")["id"]
    seal = m.create_position("Mechanical seal", parent_id=pump, position_class="Pump mechanical seal 65 mm")["id"]
    m.fit(pump, new_item={"name": "Split-case pump 150x125-400", "serial": "P-0202"}, on="2020-05-01")
    m.fit(seal, new_item={"name": "Seal", "serial": "MS65-0017"}, on="2024-07-02")
    check = m.create_task(pump, "Check the mechanical seal for leakage", 1, "months", outcome="on_condition")["id"]
    # The last check, done and found good on 21 Oct.
    today.set("2026-10-21")
    first = m.open_work_order(None, None, type="preventive", task_id=check)
    m.close_work_order(first["id"], [{"kind": "inspect", "finding": "ok"}])
    today.set("2026-11-12")
    return pump, seal, check


def test_found_failed_on_the_seal_inside_the_pump_is_interval_censored(m, today):
    pump, seal, check = _pump_with_seal(m, today)
    wo = m.open_work_order(None, None, type="preventive", task_id=check)
    view = m.work_order(wo["id"])
    assert [p["id"] for p in view["inside_positions"]] == [seal]
    assert view["inside_positions"][0]["fitted"]["item"]["serial"] == "MS65-0017"
    pump_rows_before = m.life_data(pump)
    m.close_work_order(wo["id"], [
        {"kind": "inspect", "finding": "found_failed", "position_id": seal,
         "failure_mode_text": "Mechanical seal leaking past the limit"},
        {"kind": "replace", "reason": "failure", "position_id": seal, "new_item": {"serial": "MS65-0031"}},
    ])
    rows = m.life_data(seal)
    old, new = rows
    lo, hi = _days("2024-07-02", "2026-10-21"), _days("2024-07-02", "2026-11-12")
    assert (old["c"], old["xl"], old["xr"], old["x"]) == (2, lo, hi, round((lo + hi) / 2))
    assert old["found_failed"] == {"on": "2026-11-12", "last_good": "2026-10-21", "work_order_id": wo["id"]}
    assert old["failure_mode"] == "Mechanical seal leaking past the limit"
    assert (new["c"], new["status"]) == (1, "still fitted")
    # The new seal kept its serial; the pump's own life and failure modes are untouched.
    assert m.position(seal)["fitted"]["item"]["serial"] == "MS65-0031"
    assert m.life_data(pump) == pump_rows_before
    assert not m.position(pump)["failure_modes"]
    assert [fm["text"] for fm in m.position(seal)["failure_modes"]] == ["Mechanical seal leaking past the limit"]
    # The closed work order says where each action was recorded.
    acts = m.work_order(wo["id"])["actions"]
    assert [a["position"]["id"] for a in acts] == [seal, seal]
    # Pooled for the class: one failure, interval censored, one still running.
    pooled = m.class_life_data("Pump mechanical seal 65 mm")
    assert (pooled["failures"], pooled["suspensions"]) == (1, 1)
    assert [r["c"] for r in pooled["rows"]] == [2, 1]
    _rebuilds(m)


def test_found_failed_then_replaced_on_its_own_work_order_keeps_the_interval(m, today):
    """W07: the check (#73) found it failed; the replacement went on a work order of its
    own (#76). The seal's life is still interval censored, not exact at the replacement."""
    pump, seal, check = _pump_with_seal(m, today)
    wo = m.open_work_order(None, None, type="preventive", task_id=check)
    m.close_work_order(wo["id"], [{"kind": "inspect", "finding": "found_failed", "position_id": seal}])
    rows = m.life_data(seal)
    assert rows[0]["c"] == 2 and rows[0]["to"] is None and rows[0]["status"] == "failed"
    today.set("2026-11-14")
    fix = m.open_work_order(seal, "Replace leaking mechanical seal")
    m.close_work_order(fix["id"], [{"kind": "replace", "reason": "failure", "new_item": {"name": "Seal", "serial": "S2"}}])
    old = m.life_data(seal)[0]
    assert (old["c"], old["xl"], old["xr"], old["to"]) == (
        2, _days("2024-07-02", "2026-10-21"), _days("2024-07-02", "2026-11-12"), "2026-11-14")
    assert m.class_life_data("Pump mechanical seal 65 mm")["failures"] == 1
    _rebuilds(m)


def test_found_failed_with_no_good_check_known_is_censored_from_when_it_went_in(m, today):
    seal = m.create_position("Seal")["id"]
    m.fit(seal, new_item={"name": "Seal"}, on="2026-01-01")
    wo = m.open_work_order(seal, "Look at the seal", type="inspection")
    m.close_work_order(wo["id"], [{"kind": "inspect", "finding": "found_failed"}])
    row = m.life_data(seal)[0]
    assert (row["c"], row["xl"], row["xr"]) == (2, 0, _days("2026-01-01", "2026-11-12"))
    assert row["found_failed"]["last_good"] is None
    _rebuilds(m)


def test_an_action_on_a_position_outside_the_work_order_is_refused(m, today):
    pump, seal, check = _pump_with_seal(m, today)
    other = m.create_position("Somewhere else")["id"]
    wo = m.open_work_order(pump, "Look at it")
    with pytest.raises(Invalid, match="inside it"):
        m.close_work_order(wo["id"], [{"kind": "inspect", "finding": "found_failed", "position_id": other}])


def test_found_failed_twice_keeps_the_first_finding(m, today):
    seal = m.create_position("Seal")["id"]
    m.fit(seal, new_item={"name": "Seal"}, on="2026-01-01")
    for day in ("2026-11-01", "2026-11-12"):
        today.set(day)
        wo = m.open_work_order(seal, "Look at the seal", type="inspection")
        m.close_work_order(wo["id"], [{"kind": "inspect", "finding": "found_failed"}])
    assert m.life_data(seal)[0]["found_failed"]["on"] == "2026-11-01"
    _rebuilds(m)


# ---- 4. a failure report counts in the life data, once ---------------------------------------------

def _diaphragm(m):
    head = m.create_position("AD40-0103 pump head")["id"]
    d = m.create_position("Diaphragm", parent_id=head, position_class="D40 dosing pump diaphragm")["id"]
    m.fit(d, new_item={"name": "D40 PTFE/EPDM diaphragm", "serial": "AD40-0103-D2"}, on="2025-08-18")
    other = m.create_position("Diaphragm (other unit)", position_class="D40 dosing pump diaphragm")["id"]
    m.fit(other, new_item={"name": "D40 PTFE/EPDM diaphragm", "serial": "AD40-0104-D1"}, on="2025-09-01")
    return d


def test_a_failure_report_counts_the_item_as_failed_on_the_day_it_occurred(m):
    d = _diaphragm(m)
    assert m.class_life_data("D40 dosing pump diaphragm")["failures"] == 0
    r = m.file_failure_report(d, "Diaphragm ruptured", occurred_on="2026-11-09",
                              failure_mode_text="Diaphragm ruptured")
    [row] = m.life_data(d)
    assert (row["c"], row["x"], row["status"], row["to"]) == (0, 448, "failed", None)
    assert row["report"] == {"id": r["id"], "label": r["label"]} and row["failed_on"] == "2026-11-09"
    assert row["failure_mode"] == "Diaphragm ruptured"
    pooled = m.class_life_data("D40 dosing pump diaphragm")
    assert (pooled["failures"], pooled["suspensions"]) == (1, 1)
    assert m.failure_report(r["id"])["life_data"]["counts"] is True
    _rebuilds(m)


def test_a_replacement_for_the_reported_failure_is_not_a_second_failure(m, today):
    d = _diaphragm(m)
    m.file_failure_report(d, "Diaphragm ruptured", occurred_on="2026-11-09")
    wo = m.open_work_order(d, "Replace ruptured diaphragm (FR-1)")
    m.close_work_order(wo["id"], [{"kind": "replace", "reason": "failure", "failure_mode_text": "Diaphragm ruptured",
                                   "new_item": {"name": "D40 diaphragm", "serial": "AD40-0103-D3"}}], on="2026-11-09")
    old, new = m.life_data(d)
    assert (old["c"], old["x"], old["to"]) == (0, 448, "2026-11-09")
    assert (new["c"], new["from"]) == (1, "2026-11-09")
    pooled = m.class_life_data("D40 dosing pump diaphragm")
    assert (pooled["failures"], pooled["suspensions"]) == (1, 2)
    _rebuilds(m)


def test_a_reported_failure_replaced_later_as_planned_still_fails_on_the_report_day(m, today):
    d = _diaphragm(m)
    m.file_failure_report(d, "Diaphragm ruptured", occurred_on="2026-11-09")
    wo = m.open_work_order(d, "Swap the diaphragm")
    m.close_work_order(wo["id"], [{"kind": "replace", "reason": "planned", "new_item": {"name": "D40 diaphragm"}}])
    old = m.life_data(d)[0]
    assert (old["c"], old["x"], old["to"]) == (0, 448, "2026-11-12")


def test_a_rejected_report_does_not_count(m):
    d = _diaphragm(m)
    r = m.file_failure_report(d, "Thought it leaked", occurred_on="2026-11-09")
    m.set_failure_report_status(r["id"], "rejected", note="Not a failure: a loose fitting")
    [row] = m.life_data(d)
    assert (row["c"], row["status"]) == (1, "still fitted")
    assert m.failure_report(r["id"])["life_data"]["counts"] is False


def test_two_reports_on_the_same_item_count_one_failure(m):
    d = _diaphragm(m)
    m.file_failure_report(d, "Weeping", occurred_on="2026-10-01")
    second = m.file_failure_report(d, "Ruptured", occurred_on="2026-11-09")
    [row] = m.life_data(d)
    assert (row["c"], row["x"]) == (0, _days("2025-08-18", "2026-10-01"))
    assert m.failure_report(second["id"])["life_data"]["counts"] is False


# ---- 5. a corrective action's work order, linked both ways ----------------------------------------

def test_a_corrective_action_raises_its_work_order_linked_both_ways(m):
    d = _diaphragm(m)
    r = m.file_failure_report(d, "Diaphragm ruptured", occurred_on="2026-11-09")
    r = m.add_corrective_action(r["id"], "Replace the diaphragm and the clamp ring", owner="Mei Chen")
    aid = r["actions"][0]["id"]
    assert r["actions"][0]["work_order"] is None
    r = m.raise_action_work_order(r["id"], aid)
    linked = r["actions"][0]["work_order"]
    assert linked["number"] and linked["status"] == "open"
    wo = m.work_order(linked["id"])
    assert wo["type"] == "corrective" and wo["title"].startswith("FR-1: Replace the diaphragm")
    assert wo["failure_reports"] == [{"id": r["id"], "label": "FR-1", "title": "Diaphragm ruptured", "status": "reported",
                                      "action": {"id": aid, "what": "Replace the diaphragm and the clamp ring"},
                                      "position_id": d}]
    with pytest.raises(Invalid, match="has a work order already"):
        m.raise_action_work_order(r["id"], aid)
    # Or an existing one picked for a new action.
    r = m.add_corrective_action(r["id"], "Check the other units", work_order_id=linked["id"])
    assert r["actions"][1]["work_order"]["id"] == linked["id"]
    _rebuilds(m)


# ---- 6. one package's visit on its own ----------------------------------------------------------

def test_one_packages_visit_is_raised_on_its_own(m, today):
    station, pump, seal, vib = _station(m)
    other = m.create_position("Somebody else's pump")["id"]
    late = m.create_task(other, "Their overdue check", 1, "weeks", last_done="2026-10-01")["id"]
    pkg = m.create_package("Low-lift monthly round", position_id=station, every=1, unit="months", weekday="monday",
                           nth=3, anchor="2026-11-01", tasks=[seal, vib])
    out = m.raise_package_visit(pkg["id"])
    assert out["raised"] is True and out["work_order"]["visit_on"] == "2026-11-16"
    assert {t["id"] for t in out["work_order"]["tasks"]} == {seal, vib}
    # Nothing else was raised: the other team's overdue task has no work order.
    assert m._task_view(m._get(late, "Task"))["open_work_order"] is None
    assert len(m.work_orders("open")) == 1
    # Asked again: the open one comes back, not a second.
    again = m.raise_package_visit(pkg["id"])
    assert again["raised"] is False and again["work_order"]["id"] == out["work_order"]["id"]
    assert len(m.work_orders("open")) == 1
    _rebuilds(m)


def test_a_paused_package_raises_nothing(m):
    station, pump, seal, vib = _station(m)
    pkg = m.create_package("Low-lift monthly round", position_id=station, every=1, unit="months", tasks=[vib])
    m.pause_package(pkg["id"], "Plant shut down", None)
    with pytest.raises(Invalid, match="paused"):
        m.raise_package_visit(pkg["id"])


def test_a_report_filed_on_the_day_of_a_swap_is_the_outgoing_items_failure(m):
    """Filed with no item on the day the motor was swapped, a report names the item fitted
    that evening; the failure is the one that came out that day, not the new one on day 0."""
    motor = m.create_position("Motor 1", position_class="Motor 2210")["id"]
    m.add_past_fitment(motor, "2026-01-01", "2026-07-15", reason="failure", failure_mode_text="Bearing seizure",
                       new_item={"name": "Motor", "serial": "M-a"})
    m.fit(motor, new_item={"name": "Motor", "serial": "M-b"}, on="2026-07-15")
    r = m.file_failure_report(motor, "Motor 1 seized in hover", occurred_on="2026-07-15")
    assert r["item"]["serial"] == "M-b"  # the snapshot as filed, unchanged
    old, new = m.life_data(motor)
    assert (old["c"], old["x"]) == (0, _days("2026-01-01", "2026-07-15"))
    assert (new["c"], new["status"]) == (1, "still fitted")
    assert m.class_life_data("Motor 2210")["failures"] == 1
