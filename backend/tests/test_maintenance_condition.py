"""Reliafy Maintenance: condition monitoring points, alarms that raise work, and
the trend to an alarm."""

from datetime import date, timedelta

import pytest

from backend.maintenance.service import PROJECTORS, Invalid, Maintenance
from backend.maintenance.store import GraphStore


def _ago(days: int) -> str:
    return (date.today() - timedelta(days=days)).isoformat()


def test_trend_projects_the_alarm_and_a_breach_raises_one_work_order():
    m = Maintenance(GraphStore(":memory:", PROJECTORS), "user-c")
    pid = m.create_position("Pool pump")["id"]
    with pytest.raises(Invalid):
        m.add_point(pid, "Vibration", unit="mm/s", alarm_above=2, alarm_below=5)
    point = m.add_point(pid, "Vibration", unit="mm/s", alarm_above=7.1)
    for days, v in ((40, 3.0), (30, 3.5), (20, 4.0), (10, 4.5)):
        m.record_reading(point["id"], v, _ago(days))
    view = m.point(point["id"])
    assert view["status"] == "ok" and view["trend_per_day"] == pytest.approx(0.05)
    assert view["projected_alarm"] == (date.today() + timedelta(days=42)).isoformat()  # 2.6 more at 0.05 a day
    high = m.record_reading(point["id"], 7.4)
    assert high["status"] == "high" and high["alarm_work_order"]
    wo = m.work_order(high["alarm_work_order"]["id"])
    assert wo["type"] == "inspection" and "above the 7.1 alarm limit" in wo["title"]
    again = m.record_reading(point["id"], 7.6)
    assert again["alarm_work_order"]["id"] == wo["id"]  # one at a time
    assert len(m.work_orders("open")) == 1
    m.close_work_order(wo["id"], [{"kind": "repair", "notes": "rebalanced"}])
    assert m.record_reading(point["id"], 7.2)["alarm_work_order"]["id"] != wo["id"]  # a new one now
    assert m.position(pid)["measurements"][0]["name"] == "Vibration"
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before
