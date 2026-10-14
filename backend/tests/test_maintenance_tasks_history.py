"""Reliafy Maintenance without an RCM study: tasks added by hand, failure modes
added or typed in at a failure (and merged later), placement dates that follow
the fitment, and past fitments put into a position's history."""

from datetime import date, timedelta

import mongomock
import pytest

from backend.maintenance import loop
from backend.maintenance.service import PROJECTORS, Invalid, Maintenance
from backend.maintenance.store import GraphStore

ORG = "user-t"


@pytest.fixture()
def m():
    return Maintenance(GraphStore(":memory:", PROJECTORS), ORG, "tester")


def _ago(days: int) -> str:
    return (date.today() - timedelta(days=days)).isoformat()


class _Study:
    id, name, system = "s1", "Pump RCM", "Pump"
    functions = [{"id": "f", "text": "Pump water", "failures": [{"id": "ff", "text": "No flow", "modes": [
        {"id": "m1", "text": "Bearing worn", "consequence": "operational",
         "decision": {"outcome": "fixed_interval", "interval": 24, "interval_unit": "months",
                      "task": "Replace bearings"}}]}]}]


# ---- tasks added by hand ---------------------------------------------------------------

def test_a_task_by_hand_is_scheduled_and_raises_work_orders_like_an_rcm_task(m):
    pid = m.create_position("Hot water system")["id"]
    m.fit(pid, new_item={"name": "Rheem 315"}, on=_ago(400))
    task = m.create_task(pid, "Replace sacrificial anode", 12, "months", outcome="fixed_interval",
                         source="oem", reference="Owner's guide §7", instructions="Isolate first.",
                         checklist=["Isolate power", "", "Drain 10 L"], last_done=_ago(370))
    assert (task["source"], task["reference"], task["outcome"]) == ("oem", "Owner's guide §7", "fixed_interval")
    assert task["checklist"] == ["Isolate power", "Drain 10 L"] and task["overdue"]
    assert [t["name"] for t in m.due_tasks(0)] == ["Replace sacrificial anode"]
    [wo] = m.generate_work_orders(0)
    detail = m.work_order(wo["id"])
    assert detail["instructions"] == "Isolate first." and [c["text"] for c in detail["checklist"]] == \
        ["Isolate power", "Drain 10 L"]
    m.close_work_order(wo["id"], [{"kind": "repair"}])
    assert m.position(pid)["tasks"][0]["last_done"] == date.today().isoformat()
    # A new item renews it, as it would an RCM task.
    wo = m.open_work_order(pid, "Leaking")
    m.close_work_order(wo["id"], [{"kind": "replace", "new_item": {"name": "Rheem 315"}}], on=date.today().isoformat())
    assert m.position(pid)["tasks"][0]["last_done"] == date.today().isoformat()


def test_a_task_by_use_with_a_second_limit_and_its_counter(m):
    pid = m.create_position("Generator")["id"]
    other = m.create_position("Other")["id"]
    hours = m.add_point(pid, "Hour meter", kind="counter", unit="hours")["id"]
    elsewhere = m.add_point(other, "Hour meter", kind="counter", unit="hours")["id"]
    cycles = m.add_point(pid, "Starts", kind="counter", unit="cycles")["id"]
    with pytest.raises(Invalid, match="same position"):
        m.create_task(pid, "Oil change", 250, "hours", point_id=elsewhere)
    with pytest.raises(Invalid, match="counts cycles"):
        m.create_task(pid, "Oil change", 250, "hours", point_id=cycles)
    task = m.create_task(pid, "Oil change", 250, "h", also_interval=6, also_unit="months", point_id=hours)
    assert (task["unit"], task["also_interval"], task["also_unit"], task["by_use"]) == ("hours", 6, "months", True)
    assert task["source"] == "manual" and task["outcome"] is None
    m.record_reading(hours, 1000, _ago(20))
    m.record_reading(hours, 1100, _ago(10))
    task = m.position(pid)["tasks"][0]
    assert task["limits"][0]["counter"]["id"] == hours and task["next_due"]


def test_task_input_is_checked(m):
    pid = m.create_position("Pump")["id"]
    for kwargs in ({"name": ""}, {"interval": 0}, {"interval": 101, "unit": "years"}, {"outcome": "rtf"},
                   {"source": "insurer"}, {"unit": "x" * 30}, {"last_done": _ago(-5)},
                   {"checklist": ["step"] * 51}, {"failure_mode_id": "nope"}):
        args = {"name": "Grease", "interval": 3, "unit": "months"} | kwargs
        with pytest.raises(Invalid):
            m.create_task(pid, **args)
    assert m.position(pid)["tasks"] == []
    m.retire_position(pid)
    with pytest.raises(Invalid, match="retired"):
        m.create_task(pid, "Grease", 3)


def test_linking_a_task_to_an_rcm_mode_makes_it_that_decisions_task(m):
    pid = m.create_position("Pump")["id"]
    task = m.create_task(pid, "Bearing change (OEM)", 30, "months", source="oem")
    m.apply_rcm(pid, _Study())
    tasks = m.position(pid)["tasks"]
    rcm_task = next(t for t in tasks if t["source"] == "rcm")
    with pytest.raises(Invalid, match="RCM study"):
        m.update_task(rcm_task["id"], failure_mode_id="")
    m.retire_task(rcm_task["id"])

    # A second position: the hand-made task is linked before the study comes.
    pid2 = m.create_position("Pump 2")["id"]
    own = m.create_task(pid2, "Bearing change (OEM)", 30, "months", source="oem")
    m.apply_rcm(pid2, type("S", (), {"id": "s1", "functions": [{"text": "Pump water", "failures": [
        {"text": "No flow", "modes": [{"id": "m1", "text": "Bearing worn", "decision": {}}]}]}]})())
    mode = m.position(pid2)["failure_modes"][0]
    linked = m.update_task(own["id"], failure_mode_id=mode["id"])
    assert linked["failure_mode"] == {"id": mode["id"], "text": "Bearing worn"} and linked["source"] == "oem"
    result = m.apply_rcm(pid2, _Study())
    assert (result["tasks_added"], result["tasks_updated"]) == (0, 1)
    [only] = m.position(pid2)["tasks"]
    assert (only["id"], only["interval"], only["unit"]) == (own["id"], 24, "months")
    unlinked = m.update_task(own["id"], failure_mode_id="")
    assert unlinked["failure_mode"] is None
    assert task["id"] in {t["id"] for t in m.position(pid)["tasks"]}


def test_a_hand_made_task_goes_into_the_class_proposals_and_economics():
    db = mongomock.MongoClient()["tasks"]
    m = Maintenance(GraphStore(":memory:", PROJECTORS), ORG, "tester")
    lives = [[700, 760, 820], [690, 840, 780], [730, 800]]
    for i, history in enumerate(lives):
        pid = m.create_position(f"Pump {i + 1}", position_class="Centrifugal pump")["id"]
        m.create_task(pid, "Replace bearings", 36, "months", outcome="fixed_interval", source="oem")
        day = 3000
        m.fit(pid, new_item={"name": f"Pump {i + 1}.0"}, on=_ago(day))
        for n, life in enumerate(history):
            day -= life
            wo = m.open_work_order(pid, "Seized")
            m.close_work_order(wo["id"], [{"kind": "replace", "failure_mode_text": "Bearing seized",
                                           "new_item": {"name": f"Pump {i + 1}.{n + 1}"}}], on=_ago(day))
    data = m.class_life_data("Centrifugal pump")
    assert data["failures"] == 8 and data["suspensions"] == 3
    m.set_class_costs("Centrifugal pump", planned_cost=400, failure_cost=4000)
    out = loop.fit_class_model(m, db, "Centrifugal pump")
    assert {p["task"]["name"] for p in out["proposals"]} == {"Replace bearings"} and len(out["proposals"]) == 3
    plans = {o["plan"] for o in loop.economics(m, "Centrifugal pump")["options"]}
    assert "current plan" in plans


def test_copying_a_position_keeps_a_hand_made_tasks_details(m):
    pid = m.create_position("Pump")["id"]
    m.create_task(pid, "Grease", 3, "months", source="oem", instructions="Two shots.", checklist=["Wipe nipple"])
    copy = m.copy_position(pid, "Pump 2")
    [task] = copy["tasks"]
    assert (task["source"], task["instructions"], task["checklist"]) == ("oem", "Two shots.", ["Wipe nipple"])


# ---- failure modes without RCM -------------------------------------------------------------

def test_a_failure_in_words_adds_an_ad_hoc_mode_and_counts_as_a_failure(m):
    pid = m.create_position("Pump A", position_class="Pool pump")["id"]
    m.fit(pid, new_item={"name": "P1"}, on=_ago(300))
    with pytest.raises(Invalid, match="planned removal"):
        m.remove(pid, on=_ago(200), reason="planned", failure_mode_text="Seal leaking")
    with pytest.raises(Invalid, match="not both"):
        m.remove(pid, on=_ago(200), failure_mode_id="x", failure_mode_text="Seal leaking")
    position = m.remove(pid, on=_ago(200), failure_mode_text="Seal leaking")
    [mode] = position["failure_modes"]
    assert (mode["text"], mode["ad_hoc"], mode["from_rcm"]) == ("Seal leaking", True, False)
    assert position["fitments"][0]["end_reason"] == "failure"
    # The same words (case and spacing aside) reuse the mode.
    m.fit(pid, new_item={"name": "P2"}, on=_ago(200))
    position = m.remove(pid, on=_ago(100), reason="failure", failure_mode_text="  seal   LEAKING ")
    assert len(position["failure_modes"]) == 1
    assert [(r["c"], r["failure_mode"]) for r in m.class_life_data("Pool pump")["rows"]] == \
        [(0, "Seal leaking"), (0, "Seal leaking")]
    assert m.position_classes()[0]["failures"] == 2


def test_closing_a_work_order_with_a_failure_in_words(m):
    pid = m.create_position("Pump B", position_class="Pool pump")["id"]
    m.fit(pid, new_item={"name": "P1"}, on=_ago(300))
    wo = m.open_work_order(pid, "Dead")
    bad = [{"kind": "replace", "failure_mode_text": "Motor burnt out", "new_item": {"name": "P2"}},
           {"kind": "inspect"}]
    with pytest.raises(Invalid):
        m.close_work_order(wo["id"], bad)
    assert m.position(pid)["failure_modes"] == []  # nothing written
    closed = m.close_work_order(wo["id"], [
        {"kind": "replace", "failure_mode_text": "Motor burnt out", "new_item": {"name": "P2"}},
        {"kind": "inspect", "finding": "degraded", "failure_mode_text": "motor burnt out"}])
    assert [a["failure_mode"]["text"] for a in closed["actions"]] == ["Motor burnt out", "Motor burnt out"]
    assert len(m.position(pid)["failure_modes"]) == 1
    assert m.life_data(pid)[0]["c"] == 0


def test_quick_pick_offers_modes_from_the_same_class(m):
    a = m.create_position("Pump A", position_class="Pool pump")["id"]
    b = m.create_position("Pump B", position_class=" pool PUMP")["id"]
    c = m.create_position("Fan", position_class="Fan")["id"]
    m.add_failure_mode(a, "Seal leaking")
    m.add_failure_mode(a, "Bearing worn")
    m.add_failure_mode(b, "bearing worn")
    m.add_failure_mode(c, "Belt slipping")
    assert m.position(b)["class_failure_modes"] == ["Seal leaking"]
    assert m.class_failure_modes(c) == []
    m.update_position(c, position_class="")
    assert m.position(c)["class_failure_modes"] == []


def test_failure_modes_are_added_edited_and_merged(m):
    pid = m.create_position("Pump", position_class="Pool pump")["id"]
    other = m.create_position("Other")["id"]
    formal = m.add_failure_mode(pid, "Bearing worn", failure="No flow", consequence="operational")
    assert (formal["ad_hoc"], formal["failure"]) == (False, "No flow")
    with pytest.raises(Invalid, match="already"):
        m.add_failure_mode(pid, "bearing  worn")
    m.fit(pid, new_item={"name": "P1"}, on=_ago(300))
    m.remove(pid, on=_ago(200), failure_mode_text="Bearing noisy")
    ad_hoc = next(f for f in m.position(pid)["failure_modes"] if f["ad_hoc"])
    m.create_task(pid, "Listen to bearings", 1, "months", failure_mode_id=ad_hoc["id"])
    with pytest.raises(Invalid, match="merge"):
        m.update_failure_mode(ad_hoc["id"], text="Bearing worn")
    with pytest.raises(Invalid, match="same position"):
        m.merge_failure_mode(ad_hoc["id"], m.add_failure_mode(other, "x")["id"])

    position = m.merge_failure_mode(ad_hoc["id"], formal["id"])
    assert [f["text"] for f in position["failure_modes"]] == ["Bearing worn"]
    assert position["life_data"][0]["failure_mode"] == "Bearing worn" and position["life_data"][0]["c"] == 0
    assert m.position(pid)["tasks"][0]["failure_mode"]["id"] == formal["id"]
    with pytest.raises(Invalid, match="merged"):
        m.merge_failure_mode(ad_hoc["id"], formal["id"])
    # An old id still finds where it went.
    m.fit(pid, new_item={"name": "P2"}, on=_ago(200))
    assert m.remove(pid, on=_ago(100), failure_mode_id=ad_hoc["id"])["fitments"][0]["failure_mode"]["text"] == \
        "Bearing worn"

    m.fit(pid, new_item={"name": "P3"}, on=_ago(100))
    typed = m.remove(pid, on=_ago(50), failure_mode_text="Impeller cracked")["failure_modes"]
    cracked = next(f for f in typed if f["ad_hoc"])
    promoted = m.update_failure_mode(cracked["id"], text="Impeller cracked (cavitation)")
    assert (promoted["ad_hoc"], promoted["text"]) == (False, "Impeller cracked (cavitation)")


def test_rcm_modes_are_changed_in_the_study_and_never_merged_away(m):
    pid = m.position_from_rcm(_Study())["position"]["id"]
    rcm = m.position(pid)["failure_modes"][0]
    assert rcm["from_rcm"]
    with pytest.raises(Invalid, match="RCM study"):
        m.update_failure_mode(rcm["id"], text="Bearings")
    m.fit(pid, new_item={"name": "P1"}, on=_ago(300))
    m.remove(pid, on=_ago(200), failure_mode_text="Bearing collapsed")
    ad_hoc = next(f for f in m.position(pid)["failure_modes"] if f["ad_hoc"])
    with pytest.raises(Invalid, match="stays"):
        m.merge_failure_mode(rcm["id"], ad_hoc["id"])
    m.merge_failure_mode(ad_hoc["id"], rcm["id"])
    assert m.life_data(pid)[0]["failure_mode"] == "Bearing worn"
    # Applying the study again still adds nothing.
    assert m.apply_rcm(pid, _Study())["failure_modes_added"] == 0


# ---- placements are for items that aren't fitted ---------------------------------------------

def test_a_fitted_item_is_where_its_position_is_and_cant_be_placed(m):
    pid = m.create_position("Hot water system")["id"]
    plant_room = m.create_location("Plant room")["id"]
    store = m.create_location("Store")["id"]
    m.fit(pid, new_item={"name": "Rheem 315"}, on="2019-03-01")
    item = m.position(pid)["fitted"]["item"]["id"]
    with pytest.raises(Invalid, match="fitted to Hot water system.*no location set.*position's location"):
        m.place_item(item, plant_room)
    m.update_position(pid, location_id=plant_room)
    with pytest.raises(Invalid, match=r"\(Plant room\)"):
        m.place_item(item, store)
    spare = m.create_item("Spare anode")["id"]
    assert m.place_item(spare, store)["placements"][0]["from"] == date.today().isoformat()
    # Never before where it is now.
    m.place_item(spare, plant_room, on=_ago(0))
    with pytest.raises(Invalid, match="since"):
        m.place_item(spare, store, on=_ago(10))


# ---- past fitments ------------------------------------------------------------------------------

def test_a_past_fitment_goes_in_before_the_current_one(m):
    pid = m.create_position("Pump", position_class="Pool pump")["id"]
    m.fit(pid, new_item={"name": "Astral CTX", "serial": "P3"}, on="2023-01-01")
    current = m.position(pid)["fitted"]
    task = m.create_task(pid, "Clean basket", 1, "months")
    before = m.position(pid)["tasks"][0]["last_done"]

    position = m.add_past_fitment(pid, "2019-06-01", "2022-12-31", new_item={"name": "Astral CTX", "serial": "P2"},
                                  failure_mode_text="Seal leaking", from_precision="month", to_precision="exact",
                                  note="from the old CMMS")
    assert position["fitted"] == current
    assert [(f["from"], f["to"], f["end_reason"]) for f in position["fitments"]] == \
        [("2023-01-01", None, None), ("2019-06-01", "2022-12-31", "failure")]
    assert position["fitments"][1]["failure_mode"]["text"] == "Seal leaking"
    assert position["tasks"][0]["last_done"] == before and task["id"] == position["tasks"][0]["id"]
    # The start is known to the month, so the failure lies in a range (c = 2).
    assert [r["c"] for r in position["life_data"]] == [2, 1]
    event = next(e for e in m.s.events(ORG, 50) if e["type"] == "fitment.added")
    # Like the other fitment events, only a date that isn't exact carries its precision.
    assert event["payload"]["from_precision"] == "month" and "to_precision" not in event["payload"]

    # Meeting the next one on the day is fine; overlapping isn't, and the error names the clash.
    m.add_past_fitment(pid, "2017-01-01", "2019-06-01", reason="planned", new_item={"name": "Old pump"})
    with pytest.raises(Invalid, match=r"Astral CTX \(serial P2\), fitted here from 2019-06-01 to 2022-12-31"):
        m.add_past_fitment(pid, "2020-01-01", "2020-06-01", new_item={"name": "Ghost"})
    with pytest.raises(Invalid, match="since 2023-01-01, still fitted"):
        m.add_past_fitment(pid, "2022-12-31", "2023-02-01", new_item={"name": "Ghost"})
    assert not any(i["name"] == "Ghost" for i in m.items())


def test_a_past_fitment_of_an_existing_item_and_the_checks(m):
    a = m.create_position("Pump A")["id"]
    b = m.create_position("Pump B")["id"]
    m.fit(a, new_item={"name": "Rotable"}, on="2022-01-01")
    rotable = m.position(a)["fitted"]["item"]["id"]
    with pytest.raises(Invalid, match="fitted elsewhere then: Rotable, fitted at Pump A since 2022-01-01"):
        m.add_past_fitment(b, "2021-06-01", "2022-06-01", item_id=rotable)
    position = m.add_past_fitment(b, "2020-01-01", "2021-12-31", item_id=rotable, reason="other")
    assert position["fitments"][0]["item"]["id"] == rotable
    assert [h["position"]["name"] for h in m.item(rotable)["history"]] == ["Pump A", "Pump B"]
    new = {"new_item": {"name": "X"}}
    for args in (new | {"start": "", "end": "2020-01-01"}, new | {"start": "2020-02-01", "end": "2020-01-01"},
                 new | {"start": "2020-01-01", "end": _ago(-3)}, {"start": "2010-01-01", "end": "2011-01-01"},
                 new | {"start": "2010-01-01", "end": "2011-01-01", "from_precision": "decade"},
                 new | {"start": "2010-01-01", "end": "2011-01-01", "reason": "planned", "failure_mode_text": "x"}):
        with pytest.raises(Invalid):
            m.add_past_fitment(b, **args)
    assert len(m.position(b)["fitments"]) == 1


def test_rebuild_matches_with_the_new_events(m):
    pid = m.create_position("Pump", position_class="Pool pump")["id"]
    m.fit(pid, new_item={"name": "P1"}, on=_ago(300))
    m.create_task(pid, "Grease", 3, "months", source="statutory", checklist=["a"])
    m.remove(pid, on=_ago(200), failure_mode_text="Seal leaking")
    formal = m.add_failure_mode(pid, "Seal worn")
    ad_hoc = next(f for f in m.position(pid)["failure_modes"] if f["ad_hoc"])
    m.merge_failure_mode(ad_hoc["id"], formal["id"])
    m.update_failure_mode(formal["id"], failure="Leaks")
    m.add_past_fitment(pid, _ago(900), _ago(400), new_item={"name": "P0"}, from_precision="year")
    m.update_task(m.position(pid)["tasks"][0]["id"], failure_mode_id=formal["id"])
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before


def test_the_rest_routes(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app
    from backend.routers import maintenance as router

    monkeypatch.setattr(db, "_db", mongomock.MongoClient()["reliafy_tasks"])
    monkeypatch.setattr(db, "_simulated", True)
    monkeypatch.setattr(router, "_store", GraphStore(":memory:", PROJECTORS))
    monkeypatch.setattr(config, "MAINTENANCE_ENABLED", True)
    monkeypatch.setattr(config, "MAINTENANCE_EMAILS", {"t@x.com"})
    client = TestClient(app)
    app.dependency_overrides[get_current_user] = lambda: {
        "uid": ORG, "email": "t@x.com", "name": "T", "email_verified": True}
    api = "/api/maintenance"
    try:
        pid = client.post(f"{api}/positions", json={"name": "Pump", "position_class": "Pool pump"}).json()["id"]
        task = client.post(f"{api}/positions/{pid}/tasks", json={"name": "Grease", "interval": 3, "source": "statutory"})
        assert task.status_code == 200, task.text
        assert client.post(f"{api}/positions/{pid}/tasks", json={"name": "Grease"}).status_code == 422
        mode = client.post(f"{api}/positions/{pid}/failure-modes", json={"text": "Bearing worn"}).json()
        patched = client.patch(f"{api}/tasks/{task.json()['id']}", json={"failure_mode_id": mode["id"],
                                                                         "outcome": "fixed_interval"}).json()
        assert patched["failure_mode"]["id"] == mode["id"] and patched["outcome"] == "fixed_interval"
        patched = client.patch(f"{api}/tasks/{task.json()['id']}", json={"failure_mode_id": None}).json()
        assert patched["failure_mode"] is None

        client.post(f"{api}/positions/{pid}/fit", json={"new_item": {"name": "P1"}, "on": "2024-01-01"})
        out = client.post(f"{api}/positions/{pid}/remove", json={"on": "2025-01-01", "failure_mode_text": "Seal gone"})
        assert out.status_code == 200 and out.json()["fitments"][0]["end_reason"] == "failure"
        ad_hoc = next(f for f in out.json()["failure_modes"] if f["ad_hoc"])
        assert client.patch(f"{api}/failure-modes/{ad_hoc['id']}", json={"text": "Seal failed"}).json()["ad_hoc"] is False
        merged = client.post(f"{api}/failure-modes/{ad_hoc['id']}/merge", json={"into_id": mode["id"]})
        assert merged.status_code == 200 and len(merged.json()["failure_modes"]) == 1
        past = client.post(f"{api}/positions/{pid}/past-fitments", json={
            "start": "2020-01-01", "end": "2023-06-01", "reason": "planned", "new_item": {"name": "P0"}})
        assert past.status_code == 200 and len(past.json()["fitments"]) == 2
        clash = client.post(f"{api}/positions/{pid}/past-fitments", json={
            "start": "2023-01-01", "end": "2024-06-01", "new_item": {"name": "P9"}})
        assert clash.status_code == 422 and "P0" in clash.json()["detail"]
    finally:
        app.dependency_overrides.pop(get_current_user, None)
