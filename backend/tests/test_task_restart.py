"""When the item is replaced, the plan restarts or keeps going (forecast plan step 5, Nov 2026;
forecast-rules 1.8 and 3.3). Restart is the default for a task on its own, keep for a calendar pattern
and for a task in a package. Next due moves when a work order replaces the item. A replacing task is age
replacement when it restarts, block replacement when it keeps; the plan's spark plugs (Weibull 345.8 h,
2.58), 626 h in a year, every 100 h at $49 a change and $900 a failure:

* restart: 5.77 planned changes, 0.243 failures, $501 (worked out);
* keep: 6 changes (certain, on the schedule), 0.241 failures, $511.
"""

from datetime import datetime, timezone

import mongomock
import pytest

from backend.maintenance import forecast_lines as fl
from backend.maintenance import position_models as pm
from backend.maintenance.service import Invalid
from backend.tests.test_maintenance_forecast_engine import _m, _rebuilds_the_same

TODAY = "2026-11-24"
ORG = "org-restart"


@pytest.fixture
def setting(monkeypatch):
    from backend.services import time_zones

    monkeypatch.setattr(time_zones, "_now", lambda: datetime.fromisoformat(TODAY).replace(hour=8, tzinfo=timezone.utc))
    m = _m(ORG)
    m.today = lambda: TODAY
    db = mongomock.MongoClient()["restart"]
    db.models.insert_one({"_id": "plug", "id": "plug", "name": "Spark plug life", "kind": "distribution",
                          "distribution_id": "weibull", "dataset_id": "ds", "spec": {"unit": "hours"},
                          "status": "ready", "owner_id": ORG, "created_at": datetime(2026, 1, 1),
                          "updated_at": datetime(2026, 1, 1),
                          "results": {"distribution_id": "weibull", "unit": "hours",
                                      "params": [{"name": "alpha", "value": 345.8}, {"name": "beta", "value": 2.58}]}})
    return m, db, pm.fetcher(db, [ORG])


def _mower(m, db):
    top = m.create_position("Mower")["id"]
    m.fit(top, new_item={"name": "Mower SN1"}, on=TODAY)
    m.set_operating_plan(top, {"background": {"kind": "rate", "amount": 12, "per": "week"}}, from_=TODAY)
    meter = m.add_point(top, "Hour meter", kind="counter", unit="hours")["id"]
    m.record_reading(meter, 0, on=TODAY)
    plug = m.add_failure_mode(top, "Spark plug electrode worn")["id"]
    m.set_mode_costs(plug, failure_cost=900)
    m.decide_failure_mode(plug, "operational", {"outcome": "fixed_interval", "task": "Replace spark plugs",
                                                "interval": 100, "interval_unit": "hours"})
    pm.link_saved(m, db, [ORG], set(), top, "model", "plug", [plug])
    task = next(t for t in m._tasks_on(top) if t["name"] == "Replace spark plugs")
    m.set_task_cost(task["id"], 49)
    return top, task["id"]


def test_the_defaults_and_the_setting():
    m = _m("org-restart-defaults")
    pos = m.create_position("Pump")["id"]
    alone = m.create_task(pos, "Change the oil", 250, "hours")["id"]
    pattern = m.create_task(pos, "Test the pump", 1, "months",
                            rule={"kind": "monthly", "every": 1, "weekday": "Tuesday", "nth": 1})["id"]
    packaged = m.create_task(pos, "Check the guard", 1, "months")["id"]
    m.create_package("Monthly round", position_id=pos, every=1, unit="months", tasks=[packaged])
    views = {t: m._task_view(m._get(t, "Task"))["on_replace"] for t in (alone, pattern, packaged)}
    assert [views[t]["value"] for t in (alone, pattern, packaged)] == ["restart", "keep", "keep"]
    assert views[alone]["set"] is None and "on its own" in views[alone]["why"]
    out = m.set_task_on_replace(alone, "keep")
    assert out["on_replace"] == {**out["on_replace"], "value": "keep", "set": "keep"}
    assert m.set_task_on_replace(alone, None)["on_replace"]["value"] == "restart"
    with pytest.raises(Invalid, match="restart"):
        m.set_task_on_replace(alone, "sometimes")
    _rebuilds_the_same(m)


def test_next_due_moves_when_the_item_is_replaced(monkeypatch):
    from backend.services import time_zones

    monkeypatch.setattr(time_zones, "_now", lambda: datetime(2026, 11, 24, 8, tzinfo=timezone.utc))
    m = _m("org-restart-next-due")
    m.today = lambda: "2026-11-24"
    pump = m.create_position("Pump")["id"]
    m.fit(pump, new_item={"name": "Pump SN1"}, on="2026-01-01")
    task = m.create_task(pump, "Clean the strainer", 30, "days", last_done="2026-11-01")["id"]
    assert m._task_view(m._get(task, "Task"))["next_due"] == "2026-12-01"
    # A new pump fitted on 20 Nov: the schedule restarts from it.
    m.remove(pump, on="2026-11-20", reason="planned")
    m.fit(pump, new_item={"name": "Pump SN2"}, on="2026-11-20")
    view = m._task_view(m._get(task, "Task"))
    assert view["next_due"] == "2026-12-20" and view["on_replace"]["restarted_on"] == "2026-11-20"
    # Kept: the schedule runs on regardless.
    m.set_task_on_replace(task, "keep")
    assert m._task_view(m._get(task, "Task"))["next_due"] == "2026-12-01"
    # One below it doesn't count (replacing one spindle doesn't restart the deck's greasing)...
    m.set_task_on_replace(task, None)
    child = m.create_position("Seal", parent_id=pump)["id"]
    m.fit(child, new_item={"name": "Seal 1"}, on="2026-11-22")
    assert m._task_view(m._get(task, "Task"))["next_due"] == "2026-12-20"
    # ... and a new item above it does: the seal's own task restarts when a new pump goes in.
    seal_task = m.create_task(child, "Check the seal", 30, "days", last_done="2026-11-22")["id"]
    assert m._task_view(m._get(seal_task, "Task"))["next_due"] == "2026-12-22"
    m.remove(pump, on="2026-11-24", reason="planned")
    m.fit(pump, new_item={"name": "Pump SN3"}, on="2026-11-24")
    view = m._task_view(m._get(seal_task, "Task"))
    assert view["next_due"] == "2026-12-24" and view["on_replace"]["restarted_on"] == "2026-11-24"


def test_keep_reads_its_last_real_doing_back_without_changing_the_projection(monkeypatch):
    """No projection changes shape (PROJECTION_VERSION stays 5): a fitting notes each task's last real doing
    in a new event first (task.done_before_fit). A fitting logged before that event existed: the latest
    closed work order for the task stands in."""
    from backend.maintenance.service import PROJECTION_VERSION
    from backend.services import time_zones

    assert PROJECTION_VERSION == 5
    monkeypatch.setattr(time_zones, "_now", lambda: datetime(2026, 11, 24, 8, tzinfo=timezone.utc))
    m = _m("org-restart-keep-log")
    m.today = lambda: "2026-11-24"
    pump = m.create_position("Pump")["id"]
    m.fit(pump, new_item={"name": "Pump SN1"}, on="2026-01-01")
    task = m.create_task(pump, "Clean the strainer", 30, "days", last_done="2026-11-01")["id"]
    m.set_task_on_replace(task, "keep")
    m.remove(pump, on="2026-11-20", reason="planned")
    m.fit(pump, new_item={"name": "Pump SN2"}, on="2026-11-20")
    types = [e["type"] for e in m.s.log.events(m.org)] if hasattr(m.s.log, "events") else []
    if types:
        assert types.index("task.done_before_fit") < len(types) - 1
    assert m._task_view(m._get(task, "Task"))["next_due"] == "2026-12-01"
    _rebuilds_the_same(m)
    # As an older log would leave it (no note): the latest closed work order, else not placed.
    m.s.patch_node(m.org, task, {"done_before_fit": None})
    node = m._get(task, "Task")
    assert m.restarted(node)["last_done"] is None


def test_3_3_restart_is_age_replacement_and_keep_is_block_replacement(setting):
    m, db, fetch = setting
    top, task = _mower(m, db)
    out = fl.node_forecast(m, fetch, "position", top, top, 12)
    line = next(x for x in out["lines"]["lines"] if x.get("task_id") == task)
    fail = next(x for x in out["lines"]["lines"] if x["kind"] == "corrective")
    assert line["on_replace"] == "restart" and line["number"] == "worked out"
    assert line["times"]["expected"] == pytest.approx(5.77, abs=0.01)
    assert fail["times"]["expected"] == pytest.approx(0.243, abs=0.002)
    assert out["lines"]["totals"]["cost"]["expected"] == pytest.approx(501, abs=2)
    assert "age replacement" in line["note"]

    m.set_task_on_replace(task, "keep")
    out = fl.node_forecast(m, fetch, "position", top, top, 12)
    line = next(x for x in out["lines"]["lines"] if x.get("task_id") == task)
    fail = next(x for x in out["lines"]["lines"] if x["kind"] == "corrective")
    assert line["number"] == "certain" and line["times"]["expected"] == 6
    assert fail["times"]["expected"] == pytest.approx(0.241, abs=0.002)
    assert out["lines"]["totals"]["cost"]["expected"] == pytest.approx(511, abs=2)


def test_a_servicing_task_shows_its_count_with_a_note(setting):
    """Greasing every 50 h on a plug run to failure (mean life about 307 h): 50 ÷ (2 × 307) ≈ 8% lost to
    replacements, so the note says the count may be about 8% lower; every 10 h, about 1.6%: one fewer for
    each replacement, half the time."""
    m, db, fetch = setting
    top, task = _mower(m, db)
    m.retire_task(task)
    grease = m.create_task(top, "Clean the plug", 10, "hours")["id"]
    out = fl.node_forecast(m, fetch, "position", top, top, 12)
    line = next(x for x in out["lines"]["lines"] if x.get("task_id") == grease)
    assert line["number"] == "certain" and line["restart_share"] == pytest.approx(10 / (2 * 307.1), rel=0.01)
    assert "about one fewer for each replacement, half the time" in line["note"]
    m.update_task(grease, interval=50)
    line = next(x for x in fl.node_forecast(m, fetch, "position", top, top, 12)["lines"]["lines"]
                if x.get("task_id") == grease)
    assert line["restart_share"] >= 0.05 and "about 8% fewer than scheduled" in line["note"]


def test_the_route(api):  # noqa: F811
    M = "/api/maintenance"
    pump = api.post(f"{M}/positions", json={"name": "Pump"}).json()
    task = api.post(f"{M}/positions/{pump['id']}/tasks", json={"name": "Change the oil", "interval": 250,
                                                               "unit": "hours"}).json()
    assert task["on_replace"]["value"] == "restart"
    r = api.patch(f"{M}/tasks/{task['id']}", json={"on_replace": "keep"})
    assert r.status_code == 200, r.text
    assert r.json()["on_replace"]["value"] == "keep"
    assert api.patch(f"{M}/tasks/{task['id']}", json={"on_replace": "maybe"}).status_code >= 400
    # The MCP and CLI twin: maintenance tasks.update on_replace.
    from backend.maintenance import mcp_tools

    assert "on_replace" in mcp_tools.TABLES["maintenance_tasks"][1]["update"][1].split()


from backend.tests.test_maintenance_rcm_api import api  # noqa: E402,F401,F811
