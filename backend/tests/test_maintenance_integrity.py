"""Reliafy Maintenance: data integrity. Cancelling or closing a work order keeps
its notes; notes can be added to and every version is kept; meter readings can
be struck out or corrected (value or date) with a reason, leaving an audit trail
that rates, due dates and alarms see past."""

from datetime import date, timedelta

import mongomock
import pytest

from backend.maintenance.service import (MAX_NOTES, PROJECTION_VERSION, PROJECTORS, Invalid, Maintenance)
from backend.maintenance.store import GraphStore
from backend.tests.rcm_tree import position_with_rcm

ORG = "org-i"
TODAY = date.today().isoformat()


def _ago(days: int) -> str:
    return (date.today() - timedelta(days=days)).isoformat()


def _ahead(days: int) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


@pytest.fixture()
def m():
    return Maintenance(GraphStore(":memory:", PROJECTORS), ORG, "tester")


class _Rcm:
    name = "Pump"
    functions = [{"id": "f", "text": "Pump", "failures": [{"id": "ff", "text": "No flow", "modes": [
        {"id": "m1", "text": "Seal worn", "consequence": "operational",
         "decision": {"outcome": "fixed_interval", "interval": 500, "interval_unit": "hours",
                      "task": "Replace the seal"}}]}]}]


# ---- 1.1 cancelling and closing keep the notes ------------------------------------

def test_cancelling_keeps_the_notes_and_records_the_reason(m):
    pid = m.create_position("Pump")["id"]
    wo = m.open_work_order(pid, "Pump screaming", notes="Bearing noise at the drive end; suspect the bearing.")
    out = m.cancel_work_order(wo["id"], "duplicate of #3")
    assert out["status"] == "cancelled" and out["closed"] == TODAY
    assert out["notes"] == "Bearing noise at the drive end; suspect the bearing."
    assert out["cancel_reason"] == "duplicate of #3"
    assert out["status_history"][-1] == {"status": "cancelled", "on": TODAY, "note": "duplicate of #3"}


def test_closing_keeps_the_notes_beside_the_closing_notes(m):
    pid = m.create_position("Pump")["id"]
    wo = m.open_work_order(pid, "Noisy", notes="Diagnosis: worn bearing")
    out = m.close_work_order(wo["id"], [{"kind": "repair"}], notes="Bearing replaced, runs quiet")
    assert out["notes"] == "Diagnosis: worn bearing" and out["close_notes"] == "Bearing replaced, runs quiet"
    quiet = m.close_work_order(m.open_work_order(pid, "Check", notes="Look at the seal")["id"], [{"kind": "repair"}])
    assert quiet["notes"] == "Look at the seal" and quiet["close_notes"] == ""


def _old_cancelled(s, org, p):
    """The projector before version 4: the reason replaced the notes."""
    s.patch_node(org, p["id"], {"status": "cancelled", "closed": p["on"], "notes": p.get("reason", "")})


def _old_closed(s, org, p):
    wo = s.node(org, p["id"])
    s.patch_node(org, p["id"], {"status": "closed", "closed": p["on"], "opened": min(wo["opened"], p["on"]),
                                "notes": p.get("notes", "")})


def test_work_orders_cancelled_under_the_old_projector_get_their_notes_back(tmp_path):
    path = str(tmp_path / "maintenance.db")
    old = {**PROJECTORS, "work_order.cancelled": _old_cancelled, "work_order.closed": _old_closed}
    before = Maintenance(GraphStore(path, old, version=3), ORG)
    pid = before.create_position("Pump")["id"]
    cancelled = before.open_work_order(pid, "Pump screaming", notes="Diagnosis: cavitation at low tank level")
    before.cancel_work_order(cancelled["id"], "raised twice")
    closed = before.open_work_order(pid, "Seal", notes="Seal weeping")
    before.close_work_order(closed["id"], [{"kind": "repair"}], notes="")
    assert before.work_order(cancelled["id"])["notes"] == "raised twice"  # the diagnosis was lost
    assert before.work_order(closed["id"])["notes"] == ""

    # Opened by this version, the graph is rebuilt from the log, which kept the notes.
    after = Maintenance(GraphStore(path, PROJECTORS, version=PROJECTION_VERSION), ORG)
    assert PROJECTION_VERSION >= 4
    wo = after.work_order(cancelled["id"])
    assert wo["notes"] == "Diagnosis: cavitation at low tank level" and wo["cancel_reason"] == "raised twice"
    assert after.work_order(closed["id"])["notes"] == "Seal weeping"


# ---- 1.2 notes: append and history ----------------------------------------------------

def test_item_notes_append_a_dated_line_and_keep_every_version(m):
    item = m.create_item("Pump", notes="Bought 2019, second-hand")
    out = m.update_item(item["id"], append_note="Bearing noise at the drive end")
    assert out["notes"] == f"Bought 2019, second-hand\n{TODAY}: Bearing noise at the drive end"
    out = m.update_item(item["id"], notes="Rebuilt 2026")
    assert out["notes"] == "Rebuilt 2026"
    assert out["note_history"] == [
        {"on": TODAY, "change": "set", "text": "Bought 2019, second-hand"},
        {"on": TODAY, "change": "appended", "text": "Bearing noise at the drive end"},
        {"on": TODAY, "change": "set", "text": "Rebuilt 2026"},
    ]
    # A form sending the note back unchanged doesn't make a new version.
    events = m.s.event_count(ORG)
    m.update_item(item["id"], notes="Rebuilt 2026", name="Pump")
    assert m.s.event_count(ORG) == events + 1  # the item.updated for the name only
    assert len(m.item(item["id"])["note_history"]) == 3

    blank = m.create_item("Motor")
    assert m.item(blank["id"])["note_history"] == []
    assert m.update_item(blank["id"], append_note="Fan cover cracked")["notes"] == f"{TODAY}: Fan cover cracked"
    with pytest.raises(Invalid):
        m.update_item(blank["id"], append_note="x" * 4001)


def test_appending_past_the_notes_limit_writes_nothing(m):
    item = m.create_item("Pump", notes="n" * 4000)
    for _ in range(4):
        m.update_item(item["id"], append_note="a" * 3900)
    with pytest.raises(Invalid):
        m.update_item(item["id"], name="Renamed", append_note="a" * 4000)
    after = m.item(item["id"])
    assert after["name"] == "Pump" and len(after["notes"]) < MAX_NOTES


def test_an_edit_logged_without_a_date_keeps_its_version_undated(m):
    item = m.create_item("Pump")
    m.s.apply(ORG, "item.updated", {"id": item["id"], "changes": {"notes": "older note"}})
    assert m.item(item["id"])["note_history"] == [{"on": None, "change": "set", "text": "older note"}]


def test_work_order_notes_append_even_once_closed_or_cancelled(m):
    pid = m.create_position("Pump")["id"]
    wo = m.open_work_order(pid, "Noisy", notes="Grinding noise")
    out = m.update_work_order(wo["id"], append_note="Isolated; waiting for a bearing")
    assert out["notes"] == f"Grinding noise\n{TODAY}: Isolated; waiting for a bearing"
    m.cancel_work_order(wo["id"], "replaced by a project")
    out = m.update_work_order(wo["id"], append_note="See project P-12")
    assert out["notes"].endswith(f"{TODAY}: See project P-12") and out["cancel_reason"] == "replaced by a project"
    assert [h["change"] for h in out["note_history"]] == ["set", "appended", "appended"]
    with pytest.raises(Invalid):
        m.update_work_order(wo["id"], title="Renamed")  # only an open one can be edited
    m.update_work_order(wo["id"], notes=out["notes"])  # unchanged: fine, nothing written


# ---- 1.3 readings: void, correct, the audit trail -----------------------------------------

def _counter(m):
    pos = position_with_rcm(m, _Rcm.functions, _Rcm.name)["position"]
    meter = m.add_point(pos["id"], "Run hours", kind="counter", unit="hours")
    return pos["id"], pos["tasks"][0]["id"], meter["id"]


def _readings(m, point_id):
    return m.point(point_id)["readings"]


def _the(point, status):
    """The one reading in a point's trail with this status."""
    [r] = [r for r in point["readings"] if r["status"] == status]
    return r


def test_a_stale_reading_entered_as_today_moves_to_its_true_date(m):
    pid, task_id, meter = _counter(m)
    m.record_reading(meter, 3000, _ago(400))
    stale = m.record_reading(meter, 3774)["readings"][0]
    assert stale["value"] == 3774 and stale["at"] == TODAY and stale["status"] == "ok"
    with pytest.raises(Invalid):
        m.record_reading(meter, 4774, _ago(1))  # higher than today's (stale) reading

    point = m.correct_reading(stale["id"], on=_ago(200), reason="an old reading, entered as today")
    # Newest first by the date read: the original (today), then its correction.
    original, corrected = point["readings"][0], point["readings"][1]
    assert (corrected["status"], corrected["at"], corrected["value"]) == ("correction", _ago(200), 3774)
    assert corrected["replaces"] == {"id": stale["id"], "at": TODAY, "when": TODAY, "value": 3774}
    assert corrected["reason"] == "an old reading, entered as today" and corrected["corrected_on"] == TODAY
    assert (original["status"], original["id"], original["voided_on"]) == ("replaced", stale["id"], TODAY)
    assert original["replaced_by"] == {"id": corrected["id"], "at": _ago(200), "when": _ago(200), "value": 3774}
    assert point["reading"] == 3774 and point["read_at"] == _ago(200)

    point = m.record_reading(meter, 4774)
    assert point["reading"] == 4774 and point["rate_per_day"] == 5  # 1000 h in 200 days
    assert [r["status"] for r in point["readings"]] == ["ok", "replaced", "correction", "ok"]


def test_correcting_a_value_rereads_the_task_done_at_it(m):
    pid, task_id, meter = _counter(m)
    m.record_reading(meter, 3000, _ago(100))
    wo = m.open_work_order(pid, "Seal", type="preventive", task_id=task_id)
    m.close_work_order(wo["id"], [{"kind": "repair"}], readings=[{"point_id": meter, "value": 3774}])
    task = m.position(pid)["tasks"][0]
    assert task["last_done_reading"] == 3774 and task["limits"][0]["due_at_reading"] == 4274

    typo = _readings(m, meter)[0]
    point = m.correct_reading(typo["id"], value=4774, reason="typo: 3 for 4")
    assert point["reading"] == 4774 and point["rate_per_day"] == pytest.approx(17.74)
    task = m.position(pid)["tasks"][0]
    assert task["last_done_reading"] == 4774 and task["limits"][0]["due_at_reading"] == 5274

    # Struck out instead, the task goes back to the reading before.
    m.void_reading(point["readings"][0]["id"], "wrong meter")
    task = m.position(pid)["tasks"][0]
    assert task["last_done_reading"] == 3000 and task["limits"][0]["due_at_reading"] == 3500


def test_a_backdated_reading_recomputes_the_rate_and_the_due_date(m):
    pid, task_id, meter = _counter(m)
    m.record_reading(meter, 1000, _ago(300))
    m.fit(pid, new_item={"name": "Seal"}, on=_ago(100))  # renewal: the counter read 1000 then
    m.record_reading(meter, 3000)
    task = m.position(pid)["tasks"][0]
    assert task["last_done_reading"] == 1000 and task["next_due"] == TODAY  # 1500 h passed long ago

    # The reading actually taken when the seal went in, entered late.
    m.record_reading(meter, 2800, _ago(100))
    task = m.position(pid)["tasks"][0]
    assert task["last_done_reading"] == 2800 and task["limits"][0]["due_at_reading"] == 3300
    assert task["limits"][0]["counter"]["rate_per_day"] == pytest.approx(6.667, abs=1e-3)
    assert task["next_due"] == _ahead(45)  # 300 h at 6.67 h a day

    # One earlier still, inside the last year: the rate is taken from it now.
    point = m.record_reading(meter, 500, _ago(350))
    assert point["rate_per_day"] == pytest.approx(2500 / 350, abs=1e-3)
    assert [r["at"] for r in point["readings"]] == [TODAY, _ago(100), _ago(300), _ago(350)]


def test_struck_out_readings_leave_rates_and_alarms(m):
    pid, task_id, meter = _counter(m)
    m.record_reading(meter, 1000, _ago(20))
    m.record_reading(meter, 1200, _ago(10))
    bad = m.record_reading(meter, 9000)["readings"][0]
    assert m.point(meter)["rate_per_day"] == 400
    point = m.void_reading(bad["id"], "fat finger")
    assert point["reading"] == 1200 and point["rate_per_day"] == 20
    assert (point["readings"][0]["status"], point["readings"][0]["void_reason"]) == ("voided", "fat finger")
    m.record_reading(meter, 1300)  # in order again once the bad one is out

    vib = m.add_point(pid, "Vibration", kind="condition", unit="mm/s", alarm_above=7)["id"]
    m.record_reading(vib, 3, _ago(10))
    spike = m.record_reading(vib, 9)
    assert spike["status"] == "high" and spike["alarm_work_order"]
    point = m.void_reading(spike["readings"][0]["id"], "sensor knocked")
    assert point["status"] == "ok" and point["reading"] == 3


def test_correcting_a_condition_reading_checks_the_alarm_only_when_it_is_the_latest(m):
    pid = m.create_position("Fan")["id"]
    vib = m.add_point(pid, "Vibration", kind="condition", unit="mm/s", alarm_above=7)["id"]
    m.record_reading(vib, 3, _ago(10))
    m.record_reading(vib, 4, _ago(5))
    older = _readings(m, vib)[1]
    assert m.correct_reading(older["id"], value=8, reason="misread")["alarm_work_order"] is None
    latest = _readings(m, vib)[0]
    point = m.correct_reading(latest["id"], value=7.5, reason="misread")
    assert point["status"] == "high" and point["alarm_work_order"]


def test_voids_and_corrections_are_checked(m):
    pid, task_id, meter = _counter(m)
    m.record_reading(meter, 1000, _ago(60))
    r = m.record_reading(meter, 1400, _ago(10))["readings"][0]
    with pytest.raises(Invalid):
        m.void_reading(r["id"], "")  # a reason is required
    with pytest.raises(Invalid):
        m.correct_reading(r["id"], value=1300)  # here too
    with pytest.raises(Invalid):
        m.correct_reading(r["id"], value=1400, on=_ago(10), reason="no change")
    with pytest.raises(Invalid):
        m.correct_reading(r["id"], value=900, reason="lower than the reading before")
    with pytest.raises(Invalid):
        m.correct_reading(r["id"], on=_ahead(1), reason="the future")
    # Lower than itself is fine: the reading being replaced doesn't count.
    fixed = _the(m.correct_reading(r["id"], value=1300, reason="misread"), "correction")
    with pytest.raises(Invalid):
        m.correct_reading(r["id"], value=1350, reason="again")  # struck out: correct the new one
    with pytest.raises(Invalid):
        m.void_reading(r["id"], "again")
    m.correct_reading(fixed["id"], value=1350, reason="misread twice")
    assert [(x["status"], x["value"]) for x in _readings(m, meter)] == [
        ("replaced", 1400), ("correction", 1350), ("replaced", 1300), ("ok", 1000)]


def test_a_rebuild_gives_the_same_graph(m):
    pid, task_id, meter = _counter(m)
    m.record_reading(meter, 1000, _ago(60))
    m.fit(pid, new_item={"name": "Seal", "notes": "spare"}, on=_ago(30))
    r = m.record_reading(meter, 1400)["readings"][0]
    m.correct_reading(r["id"], on=_ago(10), reason="date")
    m.record_reading(meter, 1200, _ago(30))
    item = m.position(pid)["fitted"]["item"]["id"]
    m.update_item(item, append_note="leaking")
    wo = m.open_work_order(pid, "x", notes="diag")
    m.cancel_work_order(wo["id"], "dup")
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before


# ---- REST and MCP -------------------------------------------------------------------------

def test_rest_routes(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app
    from backend.routers import maintenance as router

    monkeypatch.setattr(db, "_db", mongomock.MongoClient()["reliafy_integrity"])
    monkeypatch.setattr(db, "_simulated", True)
    monkeypatch.setattr(router, "_store", GraphStore(":memory:", PROJECTORS))
    monkeypatch.setattr(config, "MAINTENANCE_ENABLED", True)
    monkeypatch.setattr(config, "MAINTENANCE_EMAILS", {"a@x.com"})
    client = TestClient(app)
    app.dependency_overrides[get_current_user] = lambda: {
        "uid": ORG, "email": "a@x.com", "name": "A", "email_verified": True}
    try:
        api = "/api/maintenance"
        pid = client.post(f"{api}/positions", json={"name": "Pump"}).json()["id"]
        item = client.post(f"{api}/items", json={"name": "Pump", "notes": "first"}).json()
        out = client.patch(f"{api}/items/{item['id']}", json={"append_note": "second"}).json()
        assert out["notes"] == f"first\n{TODAY}: second" and len(out["note_history"]) == 2

        wo = client.post(f"{api}/work-orders", json={"position_id": pid, "title": "Noisy", "notes": "diag"}).json()
        out = client.patch(f"{api}/work-orders/{wo['id']}", json={"append_note": "more"}).json()
        assert out["notes"] == f"diag\n{TODAY}: more"
        out = client.post(f"{api}/work-orders/{wo['id']}/cancel", json={"reason": "dup"}).json()
        assert out["notes"] == f"diag\n{TODAY}: more" and out["cancel_reason"] == "dup"

        meter = client.post(f"{api}/positions/{pid}/points",
                            json={"name": "Hours", "kind": "counter", "unit": "hours"}).json()["id"]
        client.post(f"{api}/points/{meter}/readings", json={"value": 100, "on": _ago(10)})
        rid = client.post(f"{api}/points/{meter}/readings", json={"value": 300}).json()["readings"][0]["id"]
        assert client.post(f"{api}/readings/{rid}/void").status_code == 422  # no reason
        bad = client.post(f"{api}/readings/{rid}/correct", json={"value": 50, "reason": "x"})
        assert bad.status_code == 422 and "lower" in bad.json()["detail"]
        point = client.post(f"{api}/readings/{rid}/correct", json={"value": 200, "on": _ago(5), "reason": "misread"})
        assert point.status_code == 200, point.text
        new = _the(point.json(), "correction")
        assert (new["status"], new["value"], new["at"]) == ("correction", 200, _ago(5))
        point = client.post(f"{api}/readings/{new['id']}/void", json={"reason": "wrong meter"}).json()
        assert point["reading"] == 100 and _the(point, "voided")["void_reason"] == "wrong meter"
        assert client.post(f"{api}/readings/nope/void", json={"reason": "x"}).status_code == 404
    finally:
        app.dependency_overrides.clear()
