"""Reliafy Maintenance: names longer than names may be.

A task's name became a 397-character paragraph (an RCM decision's task text,
brought onto a position by an earlier import, which didn't check its length). Its work
order's title, made from the name, was then refused every morning, and that one
refusal stopped the whole workspace's daily run. Now:

* a title made from a longer name is shortened at a word with a trailing "…",
  and the full name goes at the top of the work order's notes;
* each task stands alone in a run: one that can't have its work order is
  skipped and reported, and the rest still get theirs;
* every way in that sets a name refuses one that's too long, saying the limit,
  its length and what to do; where a name is made from something longer (an
  RCM decision, a copy), it's shortened instead.
"""

import logging

import mongomock
import pytest

from backend.maintenance import daily, importer
from backend.maintenance.service import (
    LONG_TEXT, PROJECTORS, SHORT_TEXT, Invalid, Maintenance, derived_title, shortened,
)
from backend.maintenance.store import GraphStore
from backend.tests.rcm_tree import apply_tree

ORG = "user-long"


def _long(n: int) -> str:
    """A paragraph of real words, exactly ``n`` characters long."""
    words = ("Fortnightly filter check: read filter pressure (gauge — note the clean reading after each backwash), "
             "inspect the pump basket and the skimmer baskets, empty them, check the lid O-ring for cracks, and "
             "backwash when the pressure is 50 kPa above the clean reading; rinse for 30 seconds, then return the "
             "valve to filter and record the readings in the notes. ")
    text = (words * (n // len(words) + 1))[:n]
    while text[-1] == " ":  # never ends in a space (a name is trimmed)
        text = text[:-1] + "x"
    assert len(text) == n
    return text


LONG_NAME = _long(397)


@pytest.fixture()
def store():
    return GraphStore(":memory:", PROJECTORS)


@pytest.fixture()
def m(store):
    return Maintenance(store, ORG, "tester")


def _decision(task_text):
    return {"outcome": "on_condition", "interval": 2, "interval_unit": "weeks", "task": task_text}


def _rcm(task_text):
    return [{"id": "fn1", "text": "Keep the water clear", "failures": [{
        "id": "ff1", "text": "Water cloudy", "modes": [
            {"id": "m-filter", "text": "Filter blocked", "consequence": "operational",
             "decision": _decision(task_text)}]}]}]


def _due_task(m: Maintenance, position_id: str, name: str) -> str:
    return m.create_task(position_id, name, 1, "months", last_done="2020-01-01")["id"]


def _snapshot_holds(m: Maintenance) -> None:
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before


# ---- the shortening rule ----------------------------------------------------------------------

def test_a_name_that_fits_is_unchanged_and_gets_no_note():
    for text in ("Grease bearings", "x" * SHORT_TEXT, ("word " * 40).strip()):
        assert shortened(text) == (text.strip(), False)
        assert derived_title(text) == (text.strip(), "")


def test_a_long_name_is_cut_at_a_word_with_an_ellipsis():
    title, note = derived_title(LONG_NAME)
    assert len(title) <= SHORT_TEXT and title.endswith("…")
    head = title[:-1]
    assert LONG_NAME.startswith(head)
    assert LONG_NAME[len(head)].isspace() or LONG_NAME[len(head)] in ",;:-–—(/"  # cut at a word boundary
    assert not head.endswith((" ", ",", ";", ":"))  # no dangling space or punctuation before the "…"
    assert note == LONG_NAME  # the full name, for the notes


def test_one_over_cuts_back_to_the_last_word():
    text = "a" * 150 + " " + "b" * 50  # 201 characters
    assert shortened(text) == ("a" * 150 + "…", True)
    # A word ending exactly where the "…" goes is kept whole.
    text = "a" * 199 + " tail"
    assert shortened(text) == ("a" * 199 + "…", True)


def test_one_long_word_is_cut_hard():
    assert shortened("x" * 397) == ("x" * 199 + "…", True)
    # A space only early on (before half the limit) would leave too little: a hard cut.
    text = "Pump " + "y" * 300
    title, cut = shortened(text)
    assert cut and len(title) == SHORT_TEXT and title.startswith("Pump yyy")


def test_multibyte_text_is_cut_by_character_and_never_inside_one():
    cjk = "过滤器检查" * 60  # no spaces at all
    title, cut = shortened(cjk)
    assert cut and len(title) == SHORT_TEXT and cjk.startswith(title[:-1])
    accented = "é" * 150  # é as e + a combining accent: 300 code points
    title, _ = shortened(accented)
    assert len(title) <= SHORT_TEXT and title[-2] == "́"  # the accent stays with its letter
    family = "👨‍👩‍👧" * 60  # emoji joined by zero-width joiners
    title, _ = shortened(family)
    assert len(title) <= SHORT_TEXT and title[-2] != "‍" and not title[:-1].endswith("‍")
    words = "Prüfung des Überdruckventils " * 20
    title, _ = shortened(words)
    assert title.endswith("…") and len(title) <= SHORT_TEXT and words.startswith(title[:-1])


def test_the_full_name_is_bounded_too():
    huge = _long(LONG_TEXT + 500)
    title, note = derived_title(huge)
    assert len(title) <= SHORT_TEXT and len(note) <= LONG_TEXT and note.endswith("…")


# ---- the 397-character task, end to end --------------------------------------------------------

def test_a_397_character_task_name_from_before_gets_its_work_order(m, caplog):
    """As the real data did: the long name arrived by an event nothing checked (a
    name-only task.updated, as an earlier import wrote), not through create_task."""
    pool = m.create_position("Pool")
    filt = m.create_position("Filter", parent_id=pool["id"])
    long_task = _due_task(m, filt["id"], "Fortnightly filter check")
    m.s.apply(ORG, "task.updated", {"id": long_task, "changes": {"name": LONG_NAME}})
    assert len(m._get(long_task, "Task")["name"]) == 397
    other = _due_task(m, pool["id"], "Test the water")

    with caplog.at_level(logging.WARNING):
        result = m.generate(30)
    assert result["skipped"] == []
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]  # nothing to alert on
    by_task = {wo["task"]["id"]: wo for wo in result["work_orders"]}
    assert set(by_task) == {long_task, other}
    wo = m.work_order(by_task[long_task]["id"])
    assert len(wo["title"]) <= SHORT_TEXT and wo["title"].endswith("…")
    assert LONG_NAME.startswith(wo["title"][:-1])
    assert wo["notes"].split("\n")[0] == LONG_NAME  # the whole name, first in the notes
    assert m.work_order(by_task[other]["id"])["title"] == "Test the water"
    assert m.work_order(by_task[other]["id"])["notes"] == ""  # a name that fits gets no extra note
    _snapshot_holds(m)


def test_the_daily_run_carries_on_with_the_397_character_task(store, caplog):
    m = Maintenance(store, ORG, "tester")
    pos = m.create_position("Filter")
    tid = _due_task(m, pos["id"], "Fortnightly filter check")
    m.s.apply(ORG, "task.updated", {"id": tid, "changes": {"name": LONG_NAME}})
    _due_task(m, pos["id"], "Backwash")
    with caplog.at_level(logging.WARNING):
        result = daily.run(mongomock.MongoClient()["daily_long"], store)
    assert result["work_orders"] == 2 and "failed" not in result and "skipped_tasks" not in result
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


def test_a_task_raised_by_hand_with_its_long_name_as_title(m):
    """The app sends no title; an older client (or agent) sends the task's own name:
    either way the title is made from it."""
    pos = m.create_position("Filter")
    tid = _due_task(m, pos["id"], "Check")
    m.s.apply(ORG, "task.updated", {"id": tid, "changes": {"name": LONG_NAME}})
    for title in (None, "", LONG_NAME):
        wo = m.open_work_order(None, title, type="preventive", task_id=tid, notes="Bring the gauge")
        assert len(wo["title"]) <= SHORT_TEXT and wo["title"].endswith("…")
        assert wo["notes"] == f"{LONG_NAME}\n\nBring the gauge"
        m.cancel_work_order(wo["id"], "test")
    # A title of your own is yours, and is checked.
    assert m.open_work_order(None, "Filter check", task_id=tid)["title"] == "Filter check"
    with pytest.raises(Invalid, match="at most 200 characters; this one is 397. Shorten it and put the detail "
                                      "in the notes."):
        m.open_work_order(None, "y" * 397, task_id=tid)


def test_an_alarm_title_from_a_long_point_name_is_shortened(m):
    pos = m.create_position("Pump")
    point = m.add_point(pos["id"], "v" * SHORT_TEXT, kind="condition", unit="mm/s", alarm_above=7)
    m.record_reading(point["id"], 9.5)
    [wo] = m.work_orders("open")
    full = m.work_order(wo["id"])
    assert len(full["title"]) <= SHORT_TEXT and full["title"].endswith("…")
    assert full["notes"].startswith("v" * SHORT_TEXT + " 9.5 mm/s: above the 7 alarm limit\n\n")
    assert full["notes"].endswith("Raised by a reading past an alarm limit.")


# ---- one task's trouble doesn't stop the others -----------------------------------------------

def test_each_task_stands_alone_and_the_result_says_which_were_skipped(m, monkeypatch, caplog):
    pos = m.create_position("Pump")
    good = _due_task(m, pos["id"], "Grease")
    refused = _due_task(m, pos["id"], "Refused")
    broken = _due_task(m, pos["id"], "Broken")
    real = Maintenance.open_work_order

    def open_work_order(self, position_id, title, *args, task_id=None, **kwargs):
        if task_id == refused:
            raise Invalid("That position has been retired.")
        if task_id == broken:
            raise RuntimeError("boom")
        return real(self, position_id, title, *args, task_id=task_id, **kwargs)

    monkeypatch.setattr(Maintenance, "open_work_order", open_work_order)
    with caplog.at_level(logging.WARNING):
        result = m.generate(30)
    assert [wo["task"]["id"] for wo in result["work_orders"]] == [good]
    skipped = {s["task"]["id"]: s for s in result["skipped"]}
    assert set(skipped) == {refused, broken}
    assert skipped[refused] == {"task": {"id": refused, "name": "Refused"}, "why": "That position has been retired."}
    assert skipped[broken]["task"]["name"] == "Broken" and "went wrong" in skipped[broken]["why"]
    assert "boom" not in skipped[broken]["why"]  # no internals in what users see
    # A refusal is a warning; the unexpected is logged as an error (it alerts us).
    levels = {r.levelno for r in caplog.records if "work order for task" in r.getMessage()}
    assert levels == {logging.WARNING, logging.ERROR}
    assert m.generate_work_orders(30) == []  # the list form: what was opened (none left to open)


def test_the_daily_run_reports_skipped_tasks_in_its_result_and_digest(store, monkeypatch):
    m = Maintenance(store, ORG, "tester")
    pos = m.create_position("Pump")
    _due_task(m, pos["id"], "Grease")
    bad = _due_task(m, pos["id"], "Refused")
    real = Maintenance.open_work_order

    def open_work_order(self, position_id, title, *args, task_id=None, **kwargs):
        if task_id == bad:
            raise Invalid("That position has been retired.")
        return real(self, position_id, title, *args, task_id=task_id, **kwargs)

    monkeypatch.setattr(Maintenance, "open_work_order", open_work_order)
    result = daily.run(mongomock.MongoClient()["daily_skipped"], store)
    assert result["work_orders"] == 1 and result["skipped_tasks"] == 1 and "failed" not in result
    _, body = daily._digest([], [], skipped=[{"task": {"id": bad, "name": "Refused"},
                                              "why": "That position has been retired."}])
    assert "Tasks that couldn't get a work order (the others did):" in body
    assert "  Refused: That position has been retired." in body


# ---- the hole: RCM decisions, and other names made from longer text ----------------------------

def test_an_rcm_decisions_long_task_text_becomes_a_short_name_and_full_instructions(m):
    pos = m.create_position("Filter")
    apply_tree(m, pos["id"], _rcm(LONG_NAME))
    [task] = m.position(pos["id"])["tasks"]
    assert len(task["name"]) <= SHORT_TEXT and task["name"].endswith("…")
    assert task["instructions"] == LONG_NAME
    m.set_last_done(task["id"], "2020-01-01")
    [wo] = m.generate(30)["work_orders"]
    assert m.work_order(wo["id"])["instructions"] == LONG_NAME  # it travels with the work
    # Deciding the same again changes nothing.
    [mode] = m.position(pos["id"])["failure_modes"]
    events = m.s.event_count(ORG)
    m.decide_failure_mode(mode["id"], decision=_decision(LONG_NAME))
    assert m.s.event_count(ORG) == events
    # A short decision text stays the name, as it always was, with no instructions added.
    other = m.create_position("Skimmer")
    apply_tree(m, other["id"], _rcm("Empty the skimmer basket"))
    [short] = m.position(other["id"])["tasks"]
    assert short["name"] == "Empty the skimmer basket" and not short.get("instructions")
    _snapshot_holds(m)


def test_deciding_again_fixes_a_long_name_from_before(m):
    """The workspace's existing long names: deciding the mode again shortens its
    task's name, and the full text moves to the instructions."""
    pos = m.create_position("Filter")
    apply_tree(m, pos["id"], _rcm("Check"))
    [task] = m.position(pos["id"])["tasks"]
    m.s.apply(ORG, "task.updated", {"id": task["id"], "changes": {"name": LONG_NAME}})  # as before the fix
    [mode] = m.position(pos["id"])["failure_modes"]
    m.decide_failure_mode(mode["id"], decision=_decision(LONG_NAME))
    [task] = m.position(pos["id"])["tasks"]
    assert len(task["name"]) <= SHORT_TEXT and task["instructions"] == LONG_NAME
    _snapshot_holds(m)


def test_a_copy_shortens_a_long_name_from_before(m):
    pos = m.create_position("Filter")
    tid = m.create_task(pos["id"], "Check", 1, "months", instructions="Wear gloves")["id"]
    m.s.apply(ORG, "task.updated", {"id": tid, "changes": {"name": LONG_NAME}})
    copy = m.copy_position(pos["id"], "Filter 2")
    [task] = m.position(copy["id"])["tasks"]
    assert len(task["name"]) <= SHORT_TEXT and task["name"].endswith("…")
    assert task["instructions"] == f"{LONG_NAME}\n\nWear gloves"
    _snapshot_holds(m)


# ---- every way in refuses a name that's too long, saying what to do ----------------------------

def _refuses(fn, what, hint, length=397):
    with pytest.raises(Invalid) as err:
        fn()
    assert str(err.value) == f"The {what} is at most 200 characters; this one is {length}. {hint}"


def test_every_entry_path_refuses_an_over_long_name_with_a_clear_message(m):
    pos = m.create_position("Pump")
    tid = m.create_task(pos["id"], "Grease", 1)["id"]
    loc = m.create_location("Plant room")
    item = m.create_item("Motor")
    wo = m.open_work_order(pos["id"], "Fix")
    cls = m.create_item_class("Pumps")
    cond = m.create_condition("Outdoor")
    point = m.add_point(pos["id"], "Vibration", kind="condition", unit="mm/s")
    task_hint = "Shorten it and put the detail in the task's instructions."
    description = "Shorten it and put the detail in the description."
    notes = "Shorten it and put the detail in the notes."
    _refuses(lambda: m.create_task(pos["id"], LONG_NAME, 1), "task's name", task_hint)
    _refuses(lambda: m.create_task(None, LONG_NAME, 1, location_id=loc["id"]), "task's name", task_hint)
    _refuses(lambda: m.update_task(tid, name=LONG_NAME), "task's name", task_hint)
    _refuses(lambda: m.open_work_order(pos["id"], LONG_NAME), "title", notes)
    _refuses(lambda: m.update_work_order(wo["id"], title=LONG_NAME), "title", notes)
    _refuses(lambda: m.create_position(LONG_NAME), "position's name", description)
    _refuses(lambda: m.update_position(pos["id"], name=LONG_NAME), "position's name", description)
    _refuses(lambda: m.copy_position(pos["id"], LONG_NAME), "copy's name", description)
    _refuses(lambda: m.create_location(LONG_NAME), "location's name", description)
    _refuses(lambda: m.update_location(loc["id"], name=LONG_NAME), "location's name", description)
    _refuses(lambda: m.create_item(LONG_NAME), "item's name", "Shorten it and put the detail in the item's notes.")
    _refuses(lambda: m.update_item(item["id"], name=LONG_NAME), "item's name",
             "Shorten it and put the detail in the item's notes.")
    _refuses(lambda: m.create_item_class(LONG_NAME), "item class's name", description)
    _refuses(lambda: m.update_item_class(cls["id"], name=LONG_NAME), "item class's name", description)
    _refuses(lambda: m.create_condition(LONG_NAME), "condition's name", description)
    _refuses(lambda: m.update_condition(cond["id"], name=LONG_NAME), "condition's name", description)
    _refuses(lambda: m.add_point(pos["id"], LONG_NAME), "point's name", "Shorten it.")
    _refuses(lambda: m.update_point(point["id"], name=LONG_NAME), "point's name", "Shorten it.")
    # 200 exactly is fine.
    assert m.update_task(tid, name="n" * 200)["name"] == "n" * 200


def test_an_import_checks_every_name_before_writing_anything(m):
    rows = [{"position": "Plant > Pump", "item": "Motor", "fitted": "2024-01-01"},
            {"position": f"Plant > {LONG_NAME}", "item": "Motor", "fitted": "2024-01-01"},
            {"position": "Plant > Fan", "item": LONG_NAME[:250], "fitted": "2024-01-01"}]
    before = len(m.s.log.since(0))
    with pytest.raises(Invalid) as err:
        importer.run(m, rows)
    message = str(err.value)
    assert "Row 3: The position's name is at most 200 characters; this one is 397." in message
    assert "Row 4: The item's name is at most 200 characters; this one is 250." in message
    assert len(m.s.log.since(0)) == before  # all or nothing


# ---- the app's API and the tools say the same ---------------------------------------------------

@pytest.fixture()
def api(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app
    from backend.maintenance import photos
    from backend.routers import maintenance as router

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    monkeypatch.setattr(config, "MAINTENANCE_ENABLED", True)
    monkeypatch.setattr(config, "MAINTENANCE_EMAILS", {"long@example.org"})
    test_db = mongomock.MongoClient()["maint_long_api"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    store = GraphStore(":memory:", PROJECTORS)
    monkeypatch.setattr(router, "_store", store)
    monkeypatch.setattr(router, "_photo_store", photos.FilePhotoStore(str(tmp_path)))
    user = {"uid": ORG, "email": "long@example.org", "name": "L", "email_verified": True}
    test_db.users.insert_one({"_id": ORG, "email": "long@example.org", "name": "L", "email_verified": True})
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        yield TestClient(app), store
    finally:
        app.dependency_overrides.clear()


def test_the_app_api_refuses_with_the_message_and_generate_lists_skipped(api):
    client, store = api
    pid = client.post("/api/maintenance/positions", json={"name": "Filter"}).json()["id"]
    r = client.post(f"/api/maintenance/positions/{pid}/tasks", json={"name": LONG_NAME, "interval": 1})
    assert r.status_code == 422
    assert r.json()["detail"] == ("The task's name is at most 200 characters; this one is 397. Shorten it and put "
                                  "the detail in the task's instructions.")
    r = client.post("/api/maintenance/work-orders", json={"position_id": pid, "title": LONG_NAME})
    assert r.status_code == 422 and "this one is 397" in r.json()["detail"]
    task = client.post(f"/api/maintenance/positions/{pid}/tasks",
                       json={"name": "Check", "interval": 1, "last_done": "2020-01-01"}).json()
    Maintenance(store, ORG).s.apply(ORG, "task.updated", {"id": task["id"], "changes": {"name": LONG_NAME}})
    # What the app's Raise button sends: no title.
    wo = client.post("/api/maintenance/work-orders", json={"task_id": task["id"], "type": "preventive"}).json()
    assert wo["title"].endswith("…") and wo["notes"].startswith(LONG_NAME)
    client.post(f"/api/maintenance/work-orders/{wo['id']}/cancel", json={"reason": "again"})
    r = client.post("/api/maintenance/work-orders/generate", json={"horizon_days": 30})
    assert r.status_code == 200 and r.json()["skipped"] == [] and len(r.json()["work_orders"]) == 1


def test_a_cut_title_is_one_line():
    text = "Monthly cell check, two parts.\n(1) ELECTRICAL, pump running:\n\n" + _long(300)
    title, cut = shortened(text)
    assert cut and "\n" not in title and title.startswith("Monthly cell check, two parts. (1) ELECTRICAL")
