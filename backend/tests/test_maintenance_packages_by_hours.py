"""Reliafy Maintenance: work packages by operating hours. A "50 h service" visits every 50 h
on its position's hours counter, its dates put on the calendar through the operating plan
(or the readings that reached them); a 100 h task rides on every second visit. All synthetic
data."""

from datetime import date, datetime, time, timezone

import pytest

from backend.maintenance import service
from backend.maintenance.service import PROJECTORS, Invalid, Maintenance
from backend.maintenance.store import GraphStore


@pytest.fixture()
def today(monkeypatch):
    class Clock:
        day = date(2026, 11, 22)

        def set(self, text):
            self.day = date.fromisoformat(text)

    clock = Clock()
    monkeypatch.setattr(service.time_zones, "today", lambda name=None: clock.day)
    monkeypatch.setattr(service.time_zones, "now", lambda: datetime.combine(clock.day, time(12), tzinfo=timezone.utc))
    return clock


@pytest.fixture()
def m(today):
    return Maintenance(GraphStore(":memory:", PROJECTORS), "user-hp", "tester")


def _mower(m, plan=True):
    """A mower at 0 h today, running about 12 h a week, with a 50 h and two 100 h tasks."""
    top = m.create_position("Mower")["id"]
    engine = m.create_position("Engine", parent_id=top)["id"]
    meter = m.add_point(top, "Hour meter", kind="counter", unit="hours")
    m.record_reading(meter["id"], 0, on="2026-11-22")
    if plan:
        m.set_operating_plan(top, {"background": {"kind": "rate", "amount": 12, "per": "week"}},
                             name="Contract mowing", from_="2026-11-22")
    air = m.create_task(top, "Service the air cleaner", 50, "hours")["id"]
    oil = m.create_task(engine, "Change engine oil and filter", 100, "hours")["id"]
    plugs = m.create_task(top, "Replace spark plugs", 100, "hours")["id"]
    return {"top": top, "engine": engine, "meter": meter["id"], "air": air, "oil": oil, "plugs": plugs}


def _service(m, x, **kw):
    return m.create_package("50 h service", position_id=x["top"], every=50, unit="hours", tasks=[
        x["air"], {"task_id": x["oil"], "visit_rule": "nth", "every_nth": 2},
        {"task_id": x["plugs"], "visit_rule": "nth", "every_nth": 2}], **kw)


def _same_after_rebuild(m):
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before


def test_a_50_h_service_visits_every_50_h_and_100_h_tasks_every_second_visit(m):
    x = _mower(m)
    pkg = _service(m, x)
    assert pkg["cadence"]["unit"] == "hours" and pkg["cadence"]["text"] == "every 50 operating hours"
    hours = pkg["cadence"]["by_hours"]
    assert hours["anchor_reading"] == 0 and hours["counter"]["name"] == "Hour meter"
    assert hours["basis"]["kind"] == "plan"  # dates through the operating plan
    visits = pkg["next_visits"]
    assert [v["hours"] for v in visits] == [50, 100, 150, 200, 250, 300]
    # 12 h a week: 50 h is 29 days on, 100 h 58 (the same dates a task by use gets).
    assert [v["on"] for v in visits[:3]] == ["2026-12-21", "2027-01-19", "2027-02-17"]
    assert [v["tasks"] for v in visits] == [1, 3, 1, 3, 1, 3]
    assert set(visits[1]["task_ids"]) == {x["air"], x["oil"], x["plugs"]}
    assert pkg["next_visit"] == "2026-12-21" and pkg["next_visit_hours"] == 50
    # Each task is due on the visit it's on, not its own interval.
    assert m._task_view(m.s.node(m.org, x["oil"]))["next_due"] == "2027-01-19"
    assert m._task_view(m.s.node(m.org, x["air"]))["next_due"] == "2026-12-21"
    _same_after_rebuild(m)


def test_generate_raises_the_visit_with_its_hours(m, today):
    x = _mower(m)
    _service(m, x)
    today.set("2026-12-20")
    result = m.generate(14)
    [wo] = [w for w in result["work_orders"] if w.get("package")]
    assert wo["visit_on"] == "2026-12-21" and len(wo["lines"]) == 1
    assert m.s.node(m.org, wo["id"])["visit_hours"] == 50
    _same_after_rebuild(m)


def test_marks_passed_before_the_package_are_not_made_up(m, today):
    x = _mower(m)
    today.set("2026-12-10")
    m.record_reading(x["meter"], 104, on="2026-12-10")  # it ran harder than planned
    pkg = _service(m, x, anchor_reading=0)
    # 50 h was passed before the package was made: like a calendar package's missed dates,
    # it isn't made up. Today's reading reached 100 h, so that visit (every task) is due today.
    first, second = pkg["next_visits"][:2]
    assert (first["hours"], first["on"], first["tasks"]) == (100, "2026-12-10", 3)
    assert (second["hours"], second["tasks"]) == (150, 1)


def test_an_anchor_reading_counts_the_marks_from_it(m):
    x = _mower(m)
    m.record_reading(x["meter"], 37, on="2026-11-22")
    pkg = _service(m, x)
    assert pkg["cadence"]["by_hours"]["anchor_reading"] == 37
    assert pkg["next_visits"][0]["hours"] == 87
    later = m.update_package(pkg["id"], anchor_reading=0)
    assert later["next_visits"][0]["hours"] == 50
    assert later["next_visits"][1]["tasks"] == 3  # 100 h: every second visit from the anchor
    _same_after_rebuild(m)


def test_from_the_last_visit_counts_the_hours_from_the_close(m, today):
    x = _mower(m)
    pkg = m.create_package("50 h service", position_id=x["top"], every=50, unit="hours",
                           timing="from_last_visit", tasks=[x["air"]])
    assert pkg["cadence"]["text"] == "every 50 operating hours after the last visit"
    assert pkg["next_visit"] == "2026-12-21"


def test_what_an_hours_package_refuses(m):
    x = _mower(m)
    cal = m.create_task(x["top"], "Wash down", 1, "weeks")["id"]
    with pytest.raises(Invalid, match="holds tasks by operating hours"):
        m.create_package("50 h service", position_id=x["top"], every=50, unit="hours", tasks=[cal])
    pkg = _service(m, x)
    with pytest.raises(Invalid, match="holds tasks by operating hours"):
        m.add_package_task(pkg["id"], cal)
    with pytest.raises(Invalid, match="every Nth visit"):
        m.create_package("100 h layer", parent_id=pkg["id"], every=100, unit="hours")
    with pytest.raises(Invalid, match="no weekday"):
        m.create_package("Odd", position_id=x["top"], every=50, unit="hours", weekday="saturday")
    with pytest.raises(Invalid, match="for good"):
        m.update_package(pkg["id"], unit="weeks")
    with pytest.raises(Invalid, match="no season"):
        m.update_package(pkg["id"], season={"months": [10, 11]})
    with pytest.raises(Invalid, match="can't be one"):
        m.set_package_shutdown(pkg["id"], {"duration_hours": 4})
    bare = m.create_position("Trailer")["id"]
    with pytest.raises(Invalid, match="no hours counter"):
        m.create_package("50 h service", position_id=bare, every=50, unit="hours")
    weekly = m.create_package("Weekly", position_id=x["top"], every=1, unit="weeks", tasks=[cal])
    spare = m.create_task(x["top"], "Grease the deck", 50, "hours")["id"]
    with pytest.raises(Invalid, match="by operating hours"):
        m.add_package_task(weekly["id"], spare)
    with pytest.raises(Invalid, match="anchor_reading goes with"):
        m.create_package("Monthly", position_id=x["top"], every=1, unit="months", anchor_reading=10)


def test_without_an_operating_plan_the_counter_rate_dates_the_visits(m, today):
    x = _mower(m, plan=False)
    today.set("2026-11-27")
    m.record_reading(x["meter"], 10, on="2026-11-27")  # 2 h a day
    pkg = _service(m, x)
    hours = pkg["cadence"]["by_hours"]
    assert hours["basis"]["kind"] == "rate"
    # From today's reading (10 h), at 2 h a day: 60 h in 25 days.
    assert pkg["next_visits"][0]["hours"] == 60 and pkg["next_visits"][0]["on"] == "2026-12-22"
