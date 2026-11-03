"""Reliafy Maintenance: work packages. Tasks done together on one visit raise one
work order per visit; layers add lines on some visits (the first Saturday of the
month); a covering task leaves another off; lines not done stay owed; a missed
visit keeps one work order open and gains lines. All synthetic data."""

from datetime import date

import pytest

from backend.maintenance import service
from backend.maintenance.schedule import Cadence
from backend.maintenance.service import PROJECTORS, Invalid, Maintenance
from backend.maintenance.store import GraphStore


@pytest.fixture()
def today(monkeypatch):
    """The workspace's today, set by the test: today.set("2026-11-09")."""
    class Clock:
        day = date(2026, 11, 9)

        def set(self, text):
            self.day = date.fromisoformat(text)

    clock = Clock()
    monkeypatch.setattr(service.time_zones, "today", lambda name=None: clock.day)
    return clock


@pytest.fixture()
def m(today):
    return Maintenance(GraphStore(":memory:", PROJECTORS), "user-pk", "tester")


def _same_after_rebuild(m):
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before


def _events(m, type_):
    return [e for e in m.s.events(m.org, 500) if e["type"] == type_]


# ---- the cadence -----------------------------------------------------------------------

def test_cadence_patterns():
    sat = Cadence(1, "weeks", "2026-11-02", weekday="saturday")
    assert [d.isoformat() for d in sat.dates("2026-11-01", "2026-11-30")] == [
        "2026-11-07", "2026-11-14", "2026-11-21", "2026-11-28"]
    first = Cadence(1, "months", "2026-11-01", weekday="Saturday", nth=1)
    assert [d.isoformat() for d in first.dates("2026-11-01", "2027-02-28")] == [
        "2026-11-07", "2026-12-05", "2027-01-02", "2027-02-06"]
    assert first.includes("2026-12-05") and not first.includes("2026-12-12")
    quarterly = Cadence(3, "months", "2026-12-01", weekday="Saturday", nth=1)
    assert [d.isoformat() for d in quarterly.dates("2026-12-01", "2027-07-31")] == [
        "2026-12-05", "2027-03-06", "2027-06-05"]
    thirtieth = Cadence(1, "months", "2027-01-01", day=30)
    assert [d.isoformat() for d in thirtieth.dates("2027-01-01", "2027-03-31")] == [
        "2027-01-30", "2027-02-28", "2027-03-30"]
    monthly = Cadence(1, "months", "2027-01-31")
    assert monthly.after("2027-01-31").isoformat() == "2027-02-28" and monthly.number("2027-03-31") == 3
    assert Cadence(10, "days", "2026-11-01").after("2026-11-01").isoformat() == "2026-11-11"
    with pytest.raises(ValueError):
        Cadence(1, "months", "2026-11-01", weekday="Saturday")  # which Saturday?
    with pytest.raises(ValueError):
        Cadence(1, "weeks", "2026-11-01", day=3)


# ---- the scenario: a lagoon tree ------------------------------------------------------------

WEEKLY_EACH = 3  # 6 positions × 3 = 18 weekly tasks
MONTHLY = 10


def _plant(m):
    """A lagoon with six positions: 18 weekly tasks, 10 monthly, 3 quarterly extras
    (one of which covers a monthly one)."""
    lagoon = m.create_position("Lagoon")["id"]
    groups = {name: m.create_position(name, parent_id=lagoon)["id"] for name in ("Filtration", "Dosing", "Surrounds")}
    positions = {
        "Sand filter": groups["Filtration"], "Circulation pump": groups["Filtration"],
        "Chlorinator": groups["Dosing"], "Acid doser": groups["Dosing"],
        "Fence": groups["Surrounds"], "Gate": groups["Surrounds"]}
    pids = {name: m.create_position(name, parent_id=parent)["id"] for name, parent in positions.items()}
    weekly = []
    for name, pid in pids.items():
        for k in range(WEEKLY_EACH):
            weekly.append(m.create_task(pid, f"{name} weekly check {k + 1}", 1, "weeks",
                                        checklist=["Look", "Record"] if k == 0 else None)["id"])
    monthly = [m.create_task(pids[list(pids)[k % 6]], f"Monthly test {k + 1}", 1, "months")["id"]
               for k in range(MONTHLY - 1)]
    cell = m.create_task(pids["Chlorinator"], "Clean chlorinator cell", 1, "months")["id"]
    monthly.append(cell)
    quarterly = [m.create_task(pids["Circulation pump"], "Grease pump bearings", 3, "months")["id"],
                 m.create_task(pids["Sand filter"], "Backwash valve service", 3, "months")["id"]]
    overhaul = m.create_task(pids["Chlorinator"], "Chlorinator overhaul", 3, "months")["id"]
    quarterly.append(overhaul)
    return {"lagoon": lagoon, "pids": pids, "weekly": weekly, "monthly": monthly, "quarterly": quarterly,
            "cell": cell, "overhaul": overhaul}


def _packages(m, plant):
    weekly = m.create_package("Lagoon weekly check", position_id=plant["lagoon"], every=1, unit="weeks",
                              weekday="Saturday", anchor="2026-11-02", tolerance=1, tasks=plant["weekly"])
    monthly = m.create_package("Lagoon monthly check", parent_id=weekly["id"], every=1, unit="months",
                               weekday="Saturday", nth=1, anchor="2026-11-01", tasks=plant["monthly"])
    quarterly = m.create_package(
        "Lagoon quarterly check", parent_id=monthly["id"], every=3, unit="months", weekday="Saturday", nth=1,
        anchor="2026-12-01",
        tasks=[*plant["quarterly"][:2], {"task_id": plant["overhaul"], "suppresses": [plant["cell"]]}])
    return weekly, monthly, quarterly


def _tick_all(m, wo_id, but=()):
    wo = m.work_order(wo_id)
    for line in wo["lines"]:
        if line["task_id"] not in but:
            m.check_item(wo_id, line["index"])


def _package_wos(result):
    return [w for w in result["work_orders"] if w.get("package")]


def test_old_workspace_generates_as_before(m):
    """No packages: one work order per due task, the result as it always was."""
    plant = _plant(m)
    result = m.generate(14)
    assert set(result) == {"work_orders", "skipped"}
    assert len(result["work_orders"]) == len(plant["weekly"])  # the weekly ones fall due within 14 days
    assert all(w["task"] for w in result["work_orders"])
    assert {e["type"] for e in m.s.events(m.org, 500)} >= {"work_order.opened"}
    assert not _events(m, "work_order.package_opened")
    _same_after_rebuild(m)


def test_weekly_package_raises_one_work_order_and_layers_join_it(m, today):
    plant = _plant(m)
    weekly, monthly, quarterly = _packages(m, plant)
    assert weekly["cadence"]["text"] == "every Saturday"
    assert monthly["cadence"]["text"] == "the first Saturday of every month"
    assert quarterly["cadence"]["text"] == "the first Saturday of every 3 months"
    _same_after_rebuild(m)

    # Mon 9 Nov: the next visit is Sat 14 Nov: one work order with the 18 weekly lines.
    result = m.generate(14)
    [wo] = _package_wos(result)
    assert len(result["work_orders"]) == 1  # not 18, and no member raised on its own
    assert result["packages"][0]["visit_on"] == "2026-11-14"
    assert len(wo["lines"]) == 18 and wo["visit_on"] == "2026-11-14" and wo["package"]["id"] == weekly["id"]
    assert wo["task"] is None and len(wo["tasks"]) == 18
    # The checklist is one flat list: a line per task, then its steps.
    first = wo["lines"][0]
    assert wo["checklist"][first["index"]]["task_id"] == first["task_id"]
    assert [wo["checklist"][i]["text"] for i in first["steps"]] == ["Look", "Record"]
    assert m.generate(14)["work_orders"] == []  # one open per package
    _same_after_rebuild(m)

    for visit in ("2026-11-14", "2026-11-21", "2026-11-28"):
        today.set(visit)
        wo = m.work_orders("open")[0]
        assert wo["visit_on"] == visit
        _tick_all(m, wo["id"])
        closed = m.close_work_order(wo["id"])
        assert closed["status"] == "closed"
        made = m.generate(14)["work_orders"]
        assert len(made) == 1

    # Sat 5 Dec is the first Saturday, and the first quarterly one: the same work order
    # carries the monthly and quarterly lines, without the cell clean the overhaul covers.
    [wo] = m.work_orders("open")
    detail = m.work_order(wo["id"])
    assert detail["visit_on"] == "2026-12-05"
    on = {line["task_id"] for line in detail["lines"]}
    assert set(plant["weekly"]) <= on
    assert set(plant["monthly"]) - on == {plant["cell"]}
    assert set(plant["quarterly"]) <= on
    assert len(detail["lines"]) == 18 + 9 + 3
    assert {line["package"]["id"] for line in detail["lines"]} == {weekly["id"], monthly["id"], quarterly["id"]}
    _same_after_rebuild(m)

    today.set("2026-12-05")
    _tick_all(m, wo["id"])
    m.close_work_order(wo["id"])
    cell = m._task_view(m.s.node(m.org, plant["cell"]))
    assert cell["last_done"] is None  # covered, not done
    assert cell["next_due"] == "2027-01-02" and not cell["overdue"]
    today.set("2026-12-07")
    assert not m._task_view(m.s.node(m.org, plant["cell"]))["overdue"]
    grease = m._task_view(m.s.node(m.org, plant["quarterly"][0]))
    assert grease["last_done"] == "2026-12-05" and grease["next_due"] == "2027-03-06"
    assert grease["package"]["id"] == quarterly["id"] and grease["due_by"] == "package"
    _same_after_rebuild(m)


def test_missed_visit_keeps_one_work_order_and_adds_lines(m, today):
    plant = _plant(m)
    weekly, monthly, _ = _packages(m, plant)
    today.set("2026-12-14")  # Monday after the first Saturday
    [wo] = _package_wos(m.generate(14))
    assert wo["visit_on"] == "2026-12-19"
    today.set("2026-12-19")
    _tick_all(m, wo["id"])
    m.close_work_order(wo["id"])
    today.set("2026-12-21")
    [wo] = _package_wos(m.generate(14))
    assert wo["visit_on"] == "2026-12-26" and len(wo["lines"]) == 18

    # On Sunday it's still on time; on Mon 28 Dec it's late (Saturday, with Sunday still fine).
    today.set("2026-12-27")
    assert m.tree()[0]["inside"]["overdue"] == 0
    assert not m.work_orders("open")[0]["late"]
    today.set("2026-12-28")
    assert m.tree()[0]["inside"]["overdue"] == 18
    listed = m.packages()
    top = next(p for p in listed["packages"] if p["id"] == weekly["id"])
    assert top["open_work_order"]["late"] and top["open_work_order"]["days_late"] == 1
    assert top["open_work_order"]["visits_missed"] == 1 and listed["late"] == 1
    assert m.work_orders("open")[0]["late"]
    overdue = m._task_view(m.s.node(m.org, plant["weekly"][0]))
    assert overdue["overdue"] and overdue["next_due"] == "2026-12-26"
    assert m.generate(14)["work_orders"] == []

    # Sat 2 Jan (the first Saturday) comes and it's still open: the monthly lines join it.
    today.set("2027-01-02")
    result = m.generate(14)
    assert result["work_orders"] == [] and len(m.work_orders("open")) == 1
    [added] = result["lines_added"]
    assert added["work_order"]["id"] == wo["id"] and added["lines"] == MONTHLY and added["through"] == "2027-01-02"
    detail = m.work_order(wo["id"])
    assert len(detail["lines"]) == 18 + MONTHLY and detail["covers_to"] == "2027-01-02"
    assert m.generate(14)["lines_added"] == []  # once
    _same_after_rebuild(m)

    # Closed on Sunday 3 Jan with two lines not done: they stay due and go on the next one.
    today.set("2027-01-03")
    skipped_weekly, skipped_monthly = plant["weekly"][4], plant["monthly"][2]
    _tick_all(m, wo["id"], but=(skipped_weekly, skipped_monthly))
    with pytest.raises(Invalid, match="Say whether each line"):
        m.close_work_order(wo["id"])
    with pytest.raises(Invalid, match="reason"):
        m.close_work_order(wo["id"], not_done=[{"task_id": skipped_weekly}, {"task_id": skipped_monthly}])
    m.close_work_order(wo["id"], not_done=[{"task_id": skipped_weekly, "reason": "no access"},
                                           {"task_id": skipped_monthly, "reason": "reagent out"}])
    detail = m.work_order(wo["id"])
    assert {r["task_id"] for r in detail["released"]} == {skipped_weekly, skipped_monthly}
    assert skipped_monthly not in {t["id"] for t in detail["tasks"]}
    done = m._task_view(m.s.node(m.org, plant["monthly"][0]))
    assert done["last_done"] == "2027-01-03"
    owed = m._task_view(m.s.node(m.org, skipped_monthly))
    assert owed["last_done"] is None and owed["next_due"] == "2027-01-09"
    _same_after_rebuild(m)

    # The next visit is the next Saturday after the close (the missed one isn't made up).
    [nxt] = _package_wos(m.generate(14))
    assert nxt["visit_on"] == "2027-01-09"
    on = {line["task_id"] for line in nxt["lines"]}
    assert skipped_monthly in on and skipped_weekly in on and plant["monthly"][0] not in on
    assert len(on) == 18 + 1
    today.set("2027-01-09")
    _tick_all(m, nxt["id"])
    m.close_work_order(nxt["id"])
    assert not m.s.node(m.org, skipped_monthly)["last_done"] < "2027-01-09"
    assert not m._owed(m.s.node(m.org, skipped_monthly))
    _same_after_rebuild(m)


def test_findings_at_a_line_position_build_the_life_data(m, today):
    plant = _plant(m)
    pump = plant["pids"]["Circulation pump"]
    m.fit(pump, new_item={"name": "Pump", "serial": "P1"}, on="2026-01-01")
    weekly, _, _ = _packages(m, plant)
    [wo] = _package_wos(m.generate(14))
    assert {"id": pump, "name": "Circulation pump"} in [
        {k: p[k] for k in ("id", "name")} for p in m.work_order(wo["id"])["line_positions"]]
    today.set("2026-11-14")
    _tick_all(m, wo["id"])
    with pytest.raises(Invalid, match="line"):
        m.close_work_order(wo["id"], [{"kind": "inspect", "finding": "ok", "position_id": plant["lagoon"] + "x"}])
    m.close_work_order(wo["id"], [{"kind": "replace", "position_id": pump, "failure_mode_text": "Seal leak",
                                   "new_item": {"name": "Pump", "serial": "P2"}}])
    rows = m.life_data(pump)
    assert [r["c"] for r in rows] == [0, 1] and rows[0]["failure_mode"] == "Seal leak"
    _same_after_rebuild(m)


def test_one_home_package_and_what_can_join(m):
    plant = _plant(m)
    weekly, _, _ = _packages(m, plant)
    other = m.create_position("Shed")["id"]
    with pytest.raises(Invalid, match="already in Lagoon weekly check"):
        m.create_package("Again", position_id=plant["lagoon"], tasks=[plant["weekly"][0]])
    shed_task = m.create_task(other, "Sweep shed", 1, "weeks")["id"]
    with pytest.raises(Invalid, match="isn't Lagoon or inside it"):
        m.add_package_task(weekly["id"], shed_task)
    counter = m.add_point(plant["pids"]["Circulation pump"], "Run hours", kind="counter", unit="hours")
    by_use = m.create_task(plant["pids"]["Circulation pump"], "Pump service", 500, "hours",
                           point_id=counter["id"])["id"]
    with pytest.raises(Invalid, match="by use"):
        m.add_package_task(weekly["id"], by_use)
    with pytest.raises(Invalid, match="isn't one of"):
        m.create_package("Odd layer", parent_id=weekly["id"], every=1, unit="months", day=15)
    with pytest.raises(Invalid):
        m.update_package(weekly["id"], timing="from_last_visit")  # it has layers


def test_package_events_project_and_replay(m, today):
    plant = _plant(m)
    pkg = m.create_package("Fence walk", position_id=plant["pids"]["Fence"], every=2, unit="weeks",
                           weekday="Saturday", tasks=plant["weekly"][12:14])
    _same_after_rebuild(m)
    m.add_package_task(pkg["id"], plant["weekly"][14], visit_rule="nth", every_nth=2)
    node = m.s.node(m.org, pkg["id"])
    assert node["members"][-1] == {"task_id": plant["weekly"][14], "visit_rule": "nth", "every_nth": 2}
    _same_after_rebuild(m)
    m.update_package(pkg["id"], name="Fence and gate walk", tolerance=2,
                     tasks=[{"task_id": plant["weekly"][12], "suppresses": [plant["weekly"][13]]}])
    node = m.s.node(m.org, pkg["id"])
    assert node["name"] == "Fence and gate walk" and node["tolerance"] == {"amount": 2, "unit": "days"}
    _same_after_rebuild(m)
    removed = m.remove_package_task(pkg["id"], plant["weekly"][14])
    assert removed["removed"]["task_id"] == plant["weekly"][14]
    assert plant["weekly"][14] not in {t["task_id"] for t in removed["tasks"]}
    assert m._task_view(m.s.node(m.org, plant["weekly"][14])).get("package") is None
    _same_after_rebuild(m)
    paused = m.pause_package(pkg["id"], "fence contractor on site")
    assert paused["status"] == "paused"
    # Paused: its tasks go back to their own intervals and are raised one by one.
    made = m.generate(14)["work_orders"]
    assert {w["task"]["id"] for w in made if w.get("task")} >= set(plant["weekly"][12:14])
    _same_after_rebuild(m)
    for w in made:
        m.cancel_work_order(w["id"])
    assert m.resume_package(pkg["id"])["status"] == "active"
    _same_after_rebuild(m)
    m.retire_package(pkg["id"])
    assert m.package(pkg["id"])["status"] == "retired"
    assert m.create_package("Fence again", position_id=plant["pids"]["Fence"], tasks=[plant["weekly"][12]])
    with pytest.raises(Invalid, match="joined Fence again"):
        m.restore_package(pkg["id"])
    _same_after_rebuild(m)
    m.remove_package_task(m.packages()["packages"][0]["id"], plant["weekly"][12])
    restored = m.restore_package(pkg["id"])
    assert restored["status"] == "active" and restored["task_count"] == 2
    assert m._task_view(m.s.node(m.org, plant["weekly"][12]))["package"]["id"] == pkg["id"]
    _same_after_rebuild(m)


def test_from_last_visit_counts_from_the_close(m, today):
    plant = _plant(m)
    pkg = m.create_package("Gate check", position_id=plant["pids"]["Gate"], timing="from_last_visit", every=10,
                           unit="days", tasks=plant["weekly"][15:18])
    [wo] = _package_wos(m.generate(14))
    assert wo["visit_on"] == "2026-11-09"
    today.set("2026-11-12")
    _tick_all(m, wo["id"])
    m.close_work_order(wo["id"])
    assert m.package(pkg["id"])["next_visit"] == "2026-11-22"
    _same_after_rebuild(m)


def test_propose_groups_by_cadence_area_and_trade_and_saves_nothing(m):
    plant = _plant(m)
    sixth = m.create_task(plant["pids"]["Acid doser"], "Calibrate probe", 4, "weeks")
    count = m.s.event_count(m.org)
    out = m.propose_packages(position_id=plant["lagoon"])
    assert m.s.event_count(m.org) == count and out["saved"] is False
    by = {d["cadence"]: d for d in out["drafts"]}
    assert len(by["weekly"]["tasks"]) == 18 and by["weekly"]["name"] == "Lagoon weekly check"
    assert by["weekly"]["create"]["position_id"] == plant["lagoon"]
    assert len(by["monthly"]["tasks"]) == MONTHLY + 1
    assert any("Mixes 1 months, 4 weeks" in w for w in by["monthly"]["warnings"])
    assert len(by["quarterly"]["tasks"]) == 3
    assert sixth["id"] in by["monthly"]["create"]["tasks"]
    # A ready create makes it.
    made = m.create_package(**by["weekly"]["create"])
    assert made["task_count"] == 18
    again = m.propose_packages(position_id=plant["lagoon"])
    assert "weekly" not in {d["cadence"] for d in again["drafts"]} and again["already_in_packages"] == 18


def test_lines_marked_during_the_visit_are_saved_and_used_at_close(m, today):
    plant = _plant(m)
    pump = plant["pids"]["Circulation pump"]
    m.fit(pump, new_item={"name": "Pump", "serial": "P1"}, on="2026-01-01")
    _packages(m, plant)
    [wo] = _package_wos(m.generate(14))
    today.set("2026-11-14")
    lines = {line["task_id"]: line for line in wo["lines"]}
    skipped, problem = plant["weekly"][0], next(t for t, line in lines.items() if line.get("position_id") == pump)
    marks = len(_events(m, "work_order.line_marked"))
    out = m.mark_line(wo["id"], skipped, "not_done", reason="gate locked")
    assert out["marked"]["state"] == "not_done" and out["previous"] == {"state": "todo"}
    _same_after_rebuild(m)
    m.mark_line(wo["id"], skipped, "not_done", reason="gate locked")  # the same mark again: nothing new
    assert len(_events(m, "work_order.line_marked")) == marks + 1
    m.mark_line(wo["id"], skipped, "not_done", reason="gate locked, no key")  # overwrites
    finding = {"kind": "replace", "failure_mode_text": "Seal leak", "new_item": {"name": "Pump", "serial": "P2"}}
    m.mark_line(wo["id"], problem, "problem", finding=finding)
    with pytest.raises(Invalid, match="finding"):
        m.mark_line(wo["id"], problem, "problem")
    with pytest.raises(Invalid, match="reason"):
        m.mark_line(wo["id"], skipped, "not_done")
    other = plant["weekly"][6]
    m.mark_line(wo["id"], other, "done")
    m.mark_line(wo["id"], other, "todo")  # cleared
    detail = m.work_order(wo["id"])
    states = {line["task_id"]: line for line in detail["lines"]}
    assert states[skipped]["state"] == "not_done" and states[skipped]["reason"] == "gate locked, no key"
    assert states[problem]["state"] == "problem" and states[problem]["done"]
    assert states[other]["state"] == "todo" and not states[other]["done"]
    _same_after_rebuild(m)

    # Another device (or the same one after a refresh) closes it: the saved marks count.
    phone = Maintenance(m.s, m.org, "field")
    for line in phone.work_order(wo["id"])["lines"]:
        if line["state"] == "todo" and line["task_id"] != skipped:
            phone.check_item(wo["id"], line["index"])
    closed = phone.close_work_order(wo["id"])
    assert [r["task_id"] for r in closed["released"]] == [skipped]
    assert closed["released"][0]["reason"] == "gate locked, no key"
    assert [a["kind"] for a in closed["actions"]] == ["replace"]
    rows = phone.life_data(pump)
    assert [r["c"] for r in rows] == [0, 1] and rows[0]["failure_mode"] == "Seal leak"
    assert phone.s.node(m.org, problem)["last_done"] == "2026-11-14"
    assert phone.s.node(m.org, skipped)["last_done"] is None
    _same_after_rebuild(m)


def test_a_saved_mark_still_needs_the_other_lines_answered(m, today):
    plant = _plant(m)
    _packages(m, plant)
    [wo] = _package_wos(m.generate(14))
    m.mark_line(wo["id"], plant["weekly"][0], "not_done", reason="rain")
    with pytest.raises(Invalid, match="Say whether each line"):
        m.close_work_order(wo["id"])
    m.mark_line(wo["id"], plant["weekly"][0], "todo")
    assert m.work_order(wo["id"])["lines"][0]["state"] == "todo"
    with pytest.raises(Invalid, match="work package"):
        plain = m.open_work_order(plant["lagoon"], "Leak")
        m.mark_line(plain["id"], plant["weekly"][0], "done")
