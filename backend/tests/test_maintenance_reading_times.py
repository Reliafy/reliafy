"""Readings with a time of day and how precisely it's known (#264)."""

from datetime import date, datetime, timedelta, timezone

import pytest

from backend.maintenance.service import PROJECTORS, Invalid, Maintenance
from backend.maintenance.store import GraphStore
from backend.services import time_zones
from backend.tests.test_maintenance_rcm_api import api  # noqa: F401
from backend.tests.test_maintenance_time_zones import server_in_utc  # noqa: F401


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
    # By status, not position: just after midnight "30 minutes ago" is yesterday and sorts first.
    r = next(x for x in p["readings"] if x["status"] == "correction")
    assert r["precision"] == "minute" and r["note"] == "drained"
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


# ---- whose clock: a device in another zone, or a few minutes fast ------------------------------

def _at(monkeypatch, iso: str) -> None:
    """Pretend it's this UTC moment."""
    moment = datetime.fromisoformat(iso).replace(tzinfo=timezone.utc)
    monkeypatch.setattr(time_zones, "_now", lambda: moment)


def _point(m):
    return m.add_point(m.create_position("Gearbox")["id"], "Vibration", kind="condition", unit="mm/s")["id"]


def test_a_devices_own_clock_time_is_refused_with_what_to_do(m, monkeypatch, server_in_utc):  # noqa: F811
    """A phone in Brisbane (20:01) on a UTC workspace (10:01): its clock time, read as the
    workspace's, is ten hours ahead."""
    _at(monkeypatch, "2026-11-11T10:01:00")
    pt = _point(m)
    with pytest.raises(Invalid) as err:
        m.record_reading(pt, 7.4, "2026-11-11", at="2026-11-11T20:01")
    text = str(err.value)
    assert "can't be in the future" in text
    assert "20:01 is later than the time in this workspace, 10:01 on 11 Nov 2026 (UTC)" in text
    assert "workspace's clock" in text and "leave the time out" in text and "Settings" in text
    # Each of the things it says to do works: the workspace's time, the day alone, the device's offset.
    m.record_reading(pt, 7.4, at="2026-11-11T10:01")
    m.record_reading(pt, 7.5, "2026-11-11")
    p = m.record_reading(pt, 7.6, at="2026-11-11T20:01+10:00")
    assert p["readings"][0]["at"] == "2026-11-11T10:01:00Z"
    with pytest.raises(Invalid, match=r"it's 11 Nov 2026 in this workspace \(UTC\)"):
        m.record_reading(pt, 7.7, "2026-11-12")


def test_the_same_clock_time_is_fine_where_the_workspace_is(monkeypatch):
    _at(monkeypatch, "2026-11-11T10:01:00")
    m = Maintenance(GraphStore(":memory:", PROJECTORS), "user-u", "tester", time_zone="Australia/Brisbane")
    pt = _point(m)
    p = m.record_reading(pt, 7.4, "2026-11-11", at="2026-11-11T20:01")
    assert p["readings"][0]["at"] == "2026-11-11T10:01:00Z" and p["readings"][0]["when"] == "2026-11-11 20:01"
    with pytest.raises(Invalid, match=r"23:30 is later than the time in this workspace, 20:01 on 11 Nov 2026 "
                                      r"\(Australia/Brisbane\)"):
        m.record_reading(pt, 7.4, at="2026-11-11T23:30")


def test_a_clock_a_few_minutes_fast_still_records_as_now(m, monkeypatch, server_in_utc):  # noqa: F811
    _at(monkeypatch, "2026-11-11T10:01:30")
    pt = _point(m)
    p = m.record_reading(pt, 7.4, at="2026-11-11T10:09")     # eight minutes fast
    r = p["readings"][0]
    assert r["at"] == "2026-11-11T10:01:00Z" and r["on"] == "2026-11-11" and r["precision"] == "minute"
    with pytest.raises(Invalid, match="later than the time in this workspace"):
        m.record_reading(pt, 7.4, at="2026-11-11T10:20")     # past the tolerance
    # Just before midnight a fast clock says tomorrow: still today's reading.
    _at(monkeypatch, "2026-11-11T23:57:10")
    p = m.record_reading(pt, 7.5, at="2026-11-12T00:02:00Z")
    assert p["readings"][0]["on"] == "2026-11-11" and p["readings"][0]["at"] == "2026-11-11T23:57:10Z"
    with pytest.raises(Invalid, match="00:30 on 12 Nov 2026 is later"):
        m.record_reading(pt, 7.5, at="2026-11-12T00:30")
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before


def test_the_reading_route_says_what_to_do(api, monkeypatch, server_in_utc):  # noqa: F811
    M = "/api/maintenance"
    _at(monkeypatch, "2026-11-11T10:01:00")
    pos = api.post(f"{M}/positions", json={"name": "Gearbox"}).json()
    made = api.post(f"{M}/positions/{pos['id']}/points", json={"name": "Vibration", "kind": "condition", "unit": "mm/s"})
    assert made.status_code == 200, made.text
    pt = made.json()["id"]
    refused = api.post(f"{M}/points/{pt}/readings", json={"value": 7.4, "at": "2026-11-11T20:01"})
    assert refused.status_code == 422
    assert "10:01 on 11 Nov 2026 (UTC)" in refused.json()["detail"]
    # What the form sends on a workspace with no time zone: the workspace's (UTC) clock, marked Z.
    ok = api.post(f"{M}/points/{pt}/readings", json={"value": 7.4, "at": "2026-11-11T10:01Z"})
    assert ok.status_code == 200, ok.text
    assert ok.json()["reading"] == 7.4
