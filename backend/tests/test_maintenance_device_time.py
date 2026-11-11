"""Times that come from another clock (a phone's): a few minutes ahead of the
server isn't "the future", in the workspace's zone; a note carries the time it
was written."""

from datetime import datetime, timedelta, timezone

import pytest

from backend.maintenance import service
from backend.maintenance.service import PROJECTORS, Invalid, Maintenance
from backend.maintenance.store import GraphStore
from backend.services import time_zones


@pytest.fixture()
def m():
    return Maintenance(GraphStore(":memory:", PROJECTORS), "user-u", "tester")


def _at(minutes: float) -> str:
    """A moment ``minutes`` from now (UTC, to the second)."""
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _freeze(monkeypatch, moment: datetime) -> None:
    monkeypatch.setattr(time_zones, "_now", lambda: moment)


def test_a_reading_a_few_minutes_ahead_is_taken_and_far_ahead_says_check_the_clock(m):
    pos = m.create_position("Pool")
    pt = m.add_point(pos["id"], "Water level", kind="condition", unit="mm")
    p = m.record_reading(pt["id"], 41, at=_at(8))            # a phone eight minutes fast
    assert p["reading"] == 41
    with pytest.raises(Invalid, match="can't be in the future"):
        m.record_reading(pt["id"], 42, at=_at(12))
    assert m.point(pt["id"])["reading"] == 41                # nothing was written


def test_just_before_midnight_a_fast_clock_gives_tomorrow_and_is_still_taken(monkeypatch):
    m = Maintenance(GraphStore(":memory:", PROJECTORS), "user-u", "tester", time_zone="Australia/Brisbane")
    # 23:55 on 14 Oct in Brisbane; the phone is six minutes fast, so it says 00:01 on the 15th.
    _freeze(monkeypatch, datetime(2026, 10, 14, 13, 55, tzinfo=timezone.utc))
    assert m.today() == "2026-10-14" and m.latest_day() == "2026-10-15"
    pos = m.create_position("Bore 3")
    hours = m.add_point(pos["id"], "Run hours", kind="counter", unit="hours")
    p = m.record_reading(hours["id"], 100, at="2026-10-15T00:01:00+10:00")     # a time of day: read now
    assert p["readings"][0]["at"] == "2026-10-14T13:55:00Z"
    p = m.record_reading(hours["id"], 101, "2026-10-15")                       # a day alone: taken as given
    assert p["readings"][0]["on"] == "2026-10-15"
    with pytest.raises(Invalid, match="future"):
        m.record_reading(hours["id"], 102, "2026-10-16")
    with pytest.raises(Invalid, match="future"):
        m.record_reading(hours["id"], 102, at="2026-10-15T00:30:00+10:00")
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before


def test_the_tolerance_follows_the_workspaces_zone_not_the_servers(monkeypatch):
    # 09:00 UTC on the 14th: already the 15th nowhere, but a UTC server and a Brisbane
    # workspace (19:00 on the 14th) agree that the 15th is the future.
    _freeze(monkeypatch, datetime(2026, 10, 14, 9, 0, tzinfo=timezone.utc))
    m = Maintenance(GraphStore(":memory:", PROJECTORS), "user-u", "tester", time_zone="Australia/Brisbane")
    assert m.latest_day() == "2026-10-14"
    # 14:05 UTC: 00:05 on the 15th in Brisbane, still the 14th on the server.
    _freeze(monkeypatch, datetime(2026, 10, 14, 14, 5, tzinfo=timezone.utc))
    assert m.latest_day() == "2026-10-15"


def test_an_appended_note_carries_the_time_it_was_written(monkeypatch):
    m = Maintenance(GraphStore(":memory:", PROJECTORS), "user-u", "tester", time_zone="Australia/Brisbane")
    _freeze(monkeypatch, datetime(2026, 11, 4, 3, 0, tzinfo=timezone.utc))     # Wednesday 13:00 in Brisbane
    pos = m.create_position("Bore 3")
    wo = m.open_work_order(pos["id"], "Check the bore", type="corrective")
    # Written on Monday afternoon with no signal, sent on Wednesday.
    out = m.update_work_order(wo["id"], append_note="Gland packing weeping", note_at="2026-11-02T15:20:05+10:00")
    assert out["notes"] == "2026-11-02: Gland packing weeping"
    entry = out["note_history"][-1]
    assert entry == {"on": "2026-11-02", "change": "appended", "text": "Gland packing weeping",
                     "at": "2026-11-02T05:20:05Z"}
    # One written just after midnight UTC falls on the workspace's day, not the server's.
    out = m.update_work_order(wo["id"], append_note="Back on", note_at="2026-11-02T20:30:00Z")
    assert out["note_history"][-1]["on"] == "2026-11-03"
    # With no time it is dated today, as before, and has no "at".
    out = m.update_work_order(wo["id"], append_note="Closed out")
    assert out["note_history"][-1] == {"on": "2026-11-04", "change": "appended", "text": "Closed out"}
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before


def test_a_notes_time_is_checked_before_anything_is_written(m):
    pos = m.create_position("Bore 3")
    wo = m.open_work_order(pos["id"], "Check the bore", type="corrective")
    events = m.s.event_count(m.org)
    out = m.update_work_order(wo["id"], append_note="A little fast", note_at=_at(8))
    assert out["notes"].endswith("A little fast")
    with pytest.raises(Invalid, match="A note can't be in the future"):
        m.update_work_order(wo["id"], append_note="Tomorrow's note", note_at=_at(30))
    with pytest.raises(Invalid, match="needs its time of day"):
        m.update_work_order(wo["id"], append_note="When?", note_at="2026-11-02")
    with pytest.raises(Invalid, match="isn't a time"):
        m.update_work_order(wo["id"], append_note="When?", note_at="Monday arvo")
    with pytest.raises(Invalid, match="note_at goes with append_note"):
        m.update_work_order(wo["id"], title="New title", note_at=_at(-5))
    assert m.s.event_count(m.org) == events + 1
    assert m.work_order(wo["id"])["title"] == "Check the bore"


def test_the_tolerance_is_ten_minutes():
    assert service.CLOCK_TOLERANCE == timedelta(minutes=10)
