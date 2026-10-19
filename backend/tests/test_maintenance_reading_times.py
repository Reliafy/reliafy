"""Readings with a time of day and how precisely it's known (#264)."""

from datetime import date, datetime, timedelta, timezone

import pytest

from backend.maintenance.service import PROJECTORS, Invalid, Maintenance
from backend.maintenance.store import GraphStore


@pytest.fixture()
def m():
    return Maintenance(GraphStore(":memory:", PROJECTORS), "user-u", "tester")


def _mins_ago(n: int) -> str:
    """A minute ``n`` minutes ago, UTC (the test workspace has no time zone)."""
    return (datetime.now(timezone.utc) - timedelta(minutes=n)).strftime("%Y-%m-%dT%H:%MZ")


def test_two_readings_minutes_apart_are_ordered_and_rated_by_the_hour(m):
    pos = m.create_position("Pool")
    lvl = m.add_point(pos["id"], "Water level", kind="condition", unit="mm")
    a, b = _mins_ago(60), _mins_ago(40)
    m.record_reading(lvl["id"], 47, at=b)          # entered out of order
    p = m.record_reading(lvl["id"], -31.5, at=a)
    p = m.record_reading(lvl["id"], 40, at=_mins_ago(20))
    assert [r["value"] for r in p["readings"]] == [40, 47, -31.5]   # newest first, by time of day
    assert p["readings"][1]["precision"] == "minute" and p["readings"][1]["when"].endswith(b[-6:-1])
    assert p["read_precision"] == "minute" and p["reading"] == 40
    # Twenty minutes apart: the trend is per hour, not a meaningless per day.
    assert p["trend_per_hour"] is not None and abs(p["trend_per_hour"]) > 1


def test_precision_is_kept_and_never_exceeds_what_was_given(m):
    pos = m.create_position("Pool")
    pt = m.add_point(pos["id"], "Salinity", kind="condition", unit="ppm")
    last_year = str(date.today().year - 1)
    p = m.record_reading(pt["id"], 4200, at=last_year)
    r = p["readings"][0]
    assert r["precision"] == "year" and r["when"] == last_year and r["on"] == f"{last_year}-01-01"
    p = m.record_reading(pt["id"], 4300, at=f"{last_year}-06", precision="month")
    assert p["readings"][0]["when"] == f"{last_year}-06"
    with pytest.raises(Invalid, match="only given to the day"):
        m.record_reading(pt["id"], 4400, at=date.today().isoformat(), precision="minute")
    with pytest.raises(Invalid, match="future"):
        m.record_reading(pt["id"], 4400, at=(datetime.now(timezone.utc) + timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M"))
    with pytest.raises(Invalid, match="isn't a time"):
        m.record_reading(pt["id"], 4400, at="yesterday at ten")


def test_nanoseconds_and_offsets(m):
    pos = m.create_position("Rig")
    pt = m.add_point(pos["id"], "Vibration", kind="condition", unit="mm/s")
    p = m.record_reading(pt["id"], 2.5, at="2026-01-05T10:14:03.123456789+10:00")
    r = p["readings"][0]
    assert r["precision"] == "ns" and r["at"] == "2026-01-05T00:14:03.123456789Z"
    assert r["when"] == "2026-01-05 00:14:03.123456789"   # shown in the workspace zone (UTC here)


def test_correct_changes_the_time_and_the_note(m):
    pos = m.create_position("Pool")
    lvl = m.add_point(pos["id"], "Water level", kind="condition", unit="mm")
    p = m.record_reading(lvl["id"], 47, note="10:34 drained")
    rid = p["readings"][0]["id"]
    p = m.correct_reading(rid, at=_mins_ago(30), reason="time was in the note", note="drained")
    r = p["readings"][0]
    assert r["status"] == "correction" and r["precision"] == "minute" and r["note"] == "drained"
    with pytest.raises(Invalid, match="as it is"):
        m.correct_reading(r["id"], reason="same again")


def test_old_readings_replay_the_same(m):
    """A reading with no time (every reading before #264) is known to the day, and
    the graph rebuilt from the log is the same as the live one."""
    pos = m.create_position("Pump")
    meter = m.add_point(pos["id"], "Run hours", kind="counter", unit="hours")
    m.record_reading(meter["id"], 100, (date.today() - timedelta(days=2)).isoformat())
    p = m.record_reading(meter["id"], 110, at=_mins_ago(30))
    assert p["readings"][1]["precision"] == "day" and p["readings"][1]["when"] == p["readings"][1]["on"]
    with pytest.raises(Invalid):
        m.record_reading(meter["id"], 105, at=_mins_ago(10))   # a counter only goes up, by time of day too
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before
