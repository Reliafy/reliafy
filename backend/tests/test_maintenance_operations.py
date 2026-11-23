"""Reliafy Maintenance: the Operations read (the Explorer's Operations tab). Each position's duty,
its own or the one it takes from above, other use, shutdown and outage windows (inherited) and
time zone, in one read. All synthetic data."""

from datetime import date, datetime, time, timezone

import pytest

from backend.maintenance import service
from backend.maintenance.service import PROJECTORS, Maintenance
from backend.maintenance.store import GraphStore


@pytest.fixture()
def today(monkeypatch):
    class Clock:
        day = date(2026, 11, 23)

    clock = Clock()
    monkeypatch.setattr(service.time_zones, "today", lambda name=None: clock.day)
    monkeypatch.setattr(service.time_zones, "now", lambda: datetime.combine(clock.day, time(12), tzinfo=timezone.utc))
    return clock


@pytest.fixture()
def m(today):
    return Maintenance(GraphStore(":memory:", PROJECTORS), "user-ops", "tester")


def _site(m):
    site = m.create_position("Site A")["id"]
    line = m.create_position("Line 1", parent_id=site)["id"]
    pump = m.create_position("Pump 1", parent_id=line)["id"]
    return site, line, pump


def _rows(m, **kw):
    return {r["name"]: r for r in m.operations(**kw)["positions"]}


def test_a_duty_at_the_site_is_inherited_below_and_overridable(m):
    site, line, pump = _site(m)
    rows = _rows(m, root=site)
    assert {r["duty"]["source"] for r in rows.values()} == {"none"}
    m.set_operating_plan(site, {"background": {"kind": "shifts", "shifts": [
        {"days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"], "start": "06:00", "stop": "22:00"}]},
        "meters": [{"meter": "km", "amount": 400, "per": "day"}]}, time_zone="Australia/Perth")
    rows = _rows(m, root=site)
    assert rows["Site A"]["duty"]["source"] == "own"
    assert rows["Site A"]["parent_duty"] == {"source": "none", "from": None, "text": "All the time"}
    for name in ("Line 1", "Pump 1"):
        assert rows[name]["duty"]["source"] == "inherited"
        assert rows[name]["duty"]["from"] == {"id": site, "name": "Site A"}
        assert rows[name]["duty"]["plan"]["hours_per_week"] == 80
        assert rows[name]["other_use"][0]["text"] == "400 km a day"
        assert rows[name]["time_zone"] == {"zone": "Australia/Perth", "source": "plan"}
    # An override on the line; the pump now takes the line's.
    m.set_operating_plan(line, {"background": {"kind": "continuous"}})
    rows = _rows(m, root=site)
    assert rows["Line 1"]["duty"]["source"] == "own"
    assert rows["Line 1"]["parent_duty"]["from"]["name"] == "Site A"
    assert rows["Pump 1"]["duty"]["from"]["name"] == "Line 1"
    # Clear (use Site A's): the line ends its own plan and takes the site's again.
    m.end_operating_plan(line)
    rows = _rows(m, root=site)
    assert rows["Line 1"]["duty"]["source"] == "inherited" and rows["Pump 1"]["duty"]["from"]["name"] == "Site A"
    # The same as what every calculation reads (duty_of).
    assert m.duty_of(pump)["inherited_from"]["id"] == site


def test_the_asset_opened_bounds_inheritance(m):
    site, line, pump = _site(m)
    m.set_operating_plan(site, {"background": {"kind": "rate", "amount": 8, "per": "day"}})
    rows = _rows(m, root=line)
    assert set(rows) == {"Line 1", "Pump 1"}
    assert rows["Line 1"]["duty"]["source"] == "none" and rows["Pump 1"]["duty"]["source"] == "none"
    one = m.operations(root=site, position_id=pump)["positions"]
    assert len(one) == 1 and one[0]["duty"]["from"]["name"] == "Site A"


def test_shutdown_and_outage_windows_are_inherited(m):
    site, line, pump = _site(m)
    task = m.create_task(line, "Inspect the conveyor", 6, "months")["id"]
    pkg = m.create_package("Annual shut", position_id=line, every=12, unit="months", timing="fixed",
                           anchor="2027-03-01", tasks=[task])
    m.set_package_shutdown(pkg["id"], {"duration_hours": 72, "cost": 15000})
    m.take_out_of_service(site, "Cyclone season", until="2027-01-10", start="2027-01-03")
    rows = _rows(m, root=site)
    assert [w["kind"] for w in rows["Site A"]["windows"]] == ["outage"]
    pump_w = rows["Pump 1"]["windows"]
    assert [(w["kind"], w["start"][:10], w["own"]) for w in pump_w] == [
        ("outage", "2027-01-03", False), ("shutdown", "2027-03-01", False)]
    shut = pump_w[1]
    assert shut["hours"] == 72 and shut["cost"] == 15000 and shut["source"]["name"] == "Line 1"
    assert shut["end"] == "2027-03-04T00:00"
    assert rows["Line 1"]["windows"][1]["own"] is True
    # The small API other features read.
    assert m.operation_windows(pump, "2027-02-01", "2027-12-31") == [shut]


def test_a_duty_at_the_site_dates_an_hour_package_below_with_no_duty_of_its_own(m):
    site = m.create_position("Site A")["id"]
    mower = m.create_position("Mower", parent_id=site)["id"]
    meter = m.add_point(mower, "Hour meter", kind="counter", unit="hours")
    m.record_reading(meter["id"], 0, on="2026-11-23")
    air = m.create_task(mower, "Service the air cleaner", 50, "hours")["id"]
    pkg = m.create_package("50 h service", position_id=mower, every=50, unit="hours", tasks=[air])
    assert pkg["next_visits"] == [] or pkg["cadence"]["by_hours"]["basis"] is None or \
        pkg["cadence"]["by_hours"]["basis"]["kind"] != "plan"
    m.set_operating_plan(site, {"background": {"kind": "rate", "amount": 12, "per": "week"}}, from_="2026-11-23")
    slow = m.package(pkg["id"])
    assert slow["cadence"]["by_hours"]["basis"]["kind"] == "plan"
    assert slow["next_visits"][0]["on"] == "2026-12-22"  # 50 h at 12 h a week
    m.set_operating_plan(site, {"background": {"kind": "rate", "amount": 24, "per": "week"}}, from_="2026-11-23")
    fast = m.package(pkg["id"])
    assert fast["next_visits"][0]["on"] < slow["next_visits"][0]["on"]
    assert _rows(m, root=site)["Mower"]["duty"]["from"]["name"] == "Site A"
