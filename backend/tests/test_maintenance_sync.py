"""A device that works offline: its queued changes pushed in a batch
(maintenance/sync.py). Each is recorded once however often it is sent, whole or
not at all, in the order the device made them, dated when they were made."""

import random
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from backend.maintenance import sync
from backend.maintenance.service import PROJECTORS, Invalid, Maintenance
from backend.maintenance.store import GraphStore
from backend.services import time_zones

BNE = "Australia/Brisbane"


@pytest.fixture()
def m():
    return Maintenance(GraphStore(":memory:", PROJECTORS), "user-u", "tester", time_zone=BNE)


def _iso(minutes: float = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")


class Device:
    """A phone's outbox, as far as the server sees it."""

    def __init__(self, name="phone-1"):
        self.name, self.seq = name, 0

    def op(self, command, args, expects=None, minutes=-5, depends_on=(), op_id=None):
        self.seq += 1
        return {"op_id": op_id or str(uuid.uuid4()), "device_seq": self.seq, "command": command, "args": args,
                "expects": expects or {}, "device_time": _iso(minutes), "clock_offset_ms": 0,
                "depends_on": list(depends_on)}

    def push(self, m, *ops):
        return sync.push(m, {"device_id": self.name, "device_tz": BNE, "ops": list(ops)})


def _job(m, checklist=("Isolate power", "Check the seal")):
    """A pump with a seal fitted, a counter, and an open work order with a checklist."""
    pos = m.create_position("Pump P-101")
    m.fit(pos["id"], new_item={"name": "Seal"}, on="2026-01-10")
    hours = m.add_point(pos["id"], "Run hours", kind="counter", unit="hours")
    task = m.create_task(pos["id"], "Inspect the seal", 6, "months", checklist=list(checklist))
    wo = m.open_work_order(pos["id"], "Inspect the seal", type="preventive", task_id=task["id"])
    return pos, hours, wo


def _same_after_rebuild(m):
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before


def _statuses(out):
    return [o["status"] for o in out["ops"]]


# ---- once only ---------------------------------------------------------------------

def test_a_batch_is_applied_in_device_order_and_answers_with_the_fresh_views(m):
    pos, hours, wo = _job(m)
    d = Device()
    ops = [
        d.op("work_orders.status", {"work_order_id": wo["id"], "status": "in_progress"},
             {"work_order_status": ["open", "planned", "in_progress", "waiting"]}),
        d.op("work_orders.check", {"work_order_id": wo["id"], "index": 0, "done": True}, {"checklist_length": 2}),
        d.op("measurements.record", {"point_id": hours["id"], "value": 1200, "at": _iso(-4),
                                     "work_order_id": wo["id"]}, {"last_reading": {"point_id": hours["id"],
                                                                                   "value": None}}),
        d.op("work_orders.update", {"work_order_id": wo["id"], "append_note": "Seal weeping at the gland"}),
        d.op("work_orders.labour", {"work_order_id": wo["id"], "hours": 1.5, "who": "Sam"}),
        d.op("work_orders.part_used", {"work_order_id": wo["id"], "part": "Gland packing", "quantity": 2}),
    ]
    out = d.push(m, *reversed(ops))                  # sent out of order: device_seq decides
    assert _statuses(out) == ["applied"] * 6
    view = out["work_orders"][wo["id"]]
    assert view["status"] == "in_progress" and view["checklist"][0]["done"] is True
    assert view["notes"].endswith("Seal weeping at the gland")
    assert view["totals"]["hours"] == 1.5 and view["parts"][0]["part"] == "Gland packing"
    assert out["points"][hours["id"]]["reading"] == 1200
    assert out["time_zone"] == BNE and out["today"] == m.today() and out["server_time"].endswith("Z")
    _same_after_rebuild(m)


def test_sending_everything_again_records_nothing_twice(m):
    pos, hours, wo = _job(m)
    d = Device()
    ops = [
        d.op("work_orders.update", {"work_order_id": wo["id"], "append_note": "First look"}),
        d.op("work_orders.labour", {"work_order_id": wo["id"], "hours": 2}),
        d.op("work_orders.part_used", {"work_order_id": wo["id"], "part": "O-ring"}),
        d.op("measurements.record", {"point_id": hours["id"], "value": 900, "at": _iso(-3)}),
        d.op("work_orders.close", {"work_order_id": wo["id"], "actions": [{"kind": "repair", "notes": "Repacked"}]}),
    ]
    assert _statuses(d.push(m, *ops)) == ["applied"] * 5
    events = m.s.event_count(m.org)
    snapshot = m.s.snapshot()
    for _ in range(3):
        again = d.push(m, *ops)
        assert _statuses(again) == ["duplicate"] * 5
        assert again["work_orders"][wo["id"]]["status"] == "closed"   # the fresh view all the same
    assert m.s.event_count(m.org) == events and m.s.snapshot() == snapshot
    view = m.work_order(wo["id"])
    assert len(view["labour"]) == 1 and len(view["parts"]) == 1 and view["notes"].count("First look") == 1
    assert len(m.point(hours["id"])["readings"]) == 1 and len(view["actions"]) == 1
    _same_after_rebuild(m)


def test_the_same_op_twice_in_one_batch_is_applied_once(m):
    _pos, _hours, wo = _job(m)
    d = Device()
    op = d.op("work_orders.labour", {"work_order_id": wo["id"], "hours": 1})
    out = d.push(m, op, dict(op))
    assert sorted(_statuses(out)) == ["applied", "duplicate"]
    assert len(m.work_order(wo["id"])["labour"]) == 1


def test_two_sends_that_cross_are_recorded_once_by_the_log_itself(m):
    """Two servers each check "not applied yet" and both append: the second event in
    the log changes nothing, on this graph and on any rebuilt from the log."""
    _pos, _hours, wo = _job(m)
    op_id = str(uuid.uuid4())
    inner = [{"type": "work_order.labour", "payload": {"id": "l-one", "work_order_id": wo["id"], "hours": 1.0,
                                                        "who": "", "rate": None, "on": "2026-11-02", "note": ""}}]
    base = {"op_id": op_id, "device_id": "phone-1", "device_seq": 1, "command": "work_orders.labour",
            "on": "2026-11-02", "ref": {"work_order_id": wo["id"]}}
    m.s.apply(m.org, "op.applied", {**base, "apply_id": "first", "events": inner}, "tester")
    second = [{"type": "work_order.labour", "payload": {**inner[0]["payload"], "id": "l-two"}}]
    m.s.apply(m.org, "op.applied", {**base, "apply_id": "second", "events": second}, "tester")
    assert [e["id"] for e in m.work_order(wo["id"])["labour"]] == ["l-one"]
    assert sync.applied(m, op_id)["apply_id"] == "first"
    _same_after_rebuild(m)
    # And a push that finds it there says so.
    d = Device()
    out = d.push(m, d.op("work_orders.labour", {"work_order_id": wo["id"], "hours": 1}, op_id=op_id))
    assert _statuses(out) == ["duplicate"] and len(m.work_order(wo["id"])["labour"]) == 1


# ---- whole or not at all: the close --------------------------------------------------

def test_a_close_is_one_event_holding_everything_it_did(m):
    pos, hours, wo = _job(m)
    d = Device()
    before = m.s.event_count(m.org)
    out = d.push(m, d.op("work_orders.close", {
        "work_order_id": wo["id"], "on": m.today(), "notes": "Seal replaced",
        "actions": [{"kind": "replace", "new_item": {"name": "Seal Mk2"}, "failure_mode_text": "Leaking"}],
        "readings": [{"point_id": hours["id"], "value": 1300}],
    }, {"work_order_status": ["open", "in_progress"], "fitment_id": m.work_order(wo["id"])["fitted"]["id"]}))
    assert _statuses(out) == ["applied"]
    assert m.s.event_count(m.org) == before + 1
    event = m.s.events(m.org, 1)[0]
    kinds = [e["type"] for e in event["payload"]["events"]]
    assert event["type"] == "op.applied" and kinds[-1] == "work_order.closed"
    assert {"reading.added", "item.removed", "item.fitted", "action.recorded"} <= set(kinds)
    view = m.work_order(wo["id"])
    assert view["status"] == "closed" and view["fitted"]["item"]["name"] == "Seal Mk2"
    assert m.point(hours["id"])["reading"] == 1300
    _same_after_rebuild(m)


def test_a_close_that_fails_part_way_leaves_nothing_and_goes_through_when_sent_again(m, monkeypatch):
    """A crash in the middle of a close: the reading and the removal had been written
    on the copy, nothing on the workspace. The device sends the op again and it is
    applied, once."""
    pos, hours, wo = _job(m)
    d = Device()
    op = d.op("work_orders.close", {
        "work_order_id": wo["id"], "actions": [{"kind": "replace", "new_item": {"name": "Seal Mk2"}}],
        "readings": [{"point_id": hours["id"], "value": 1300}]})
    real_emit, seen = Maintenance._emit, []

    def crashing(self, type, payload):
        seen.append(type)
        if type == "item.fitted":
            raise RuntimeError("the process died here")
        return real_emit(self, type, payload)

    snapshot, events = m.s.snapshot(), m.s.event_count(m.org)
    monkeypatch.setattr(Maintenance, "_emit", crashing)
    with pytest.raises(RuntimeError):
        d.push(m, op)
    assert seen[:2] == ["reading.added", "item.removed"]          # it really was half way
    assert m.s.snapshot() == snapshot and m.s.event_count(m.org) == events
    assert sync.applied(m, op["op_id"]) is None
    monkeypatch.setattr(Maintenance, "_emit", real_emit)
    assert _statuses(d.push(m, op)) == ["applied"]
    assert _statuses(d.push(m, op)) == ["duplicate"]
    assert len(m.point(hours["id"])["readings"]) == 1 and m.work_order(wo["id"])["status"] == "closed"
    _same_after_rebuild(m)


def test_a_crash_after_the_log_took_the_close_is_a_duplicate_on_the_resend(m, monkeypatch):
    """The other side of the same crash: the event reached the log and the answer never
    left. The resend finds the op there."""
    pos, hours, wo = _job(m)
    d = Device()
    op = d.op("work_orders.close", {"work_order_id": wo["id"], "actions": [{"kind": "repair"}]})
    monkeypatch.setattr(sync.Push, "views", lambda self: (_ for _ in ()).throw(RuntimeError("died answering")))
    with pytest.raises(RuntimeError):
        d.push(m, op)
    monkeypatch.undo()
    events = m.s.event_count(m.org)
    assert _statuses(d.push(m, op)) == ["duplicate"]
    assert m.s.event_count(m.org) == events and len(m.work_order(wo["id"])["actions"]) == 1


def test_a_refused_close_writes_nothing_even_when_it_was_refused_late(m):
    pos, hours, wo = _job(m)
    d = Device()
    # Both readings timed, the counter's 2000 before the device's 1500: undated, the
    # 2000 is "today" and the close's reading the op's day, which in the first
    # minutes after the workspace's midnight is yesterday (and so rightly earlier).
    m.record_reading(hours["id"], 2000, at=_iso(-10))
    snapshot = m.s.snapshot()
    out = d.push(m, d.op("work_orders.close", {
        "work_order_id": wo["id"], "actions": [{"kind": "repair"}],
        "readings": [{"point_id": hours["id"], "value": 1500, "at": _iso(-5)}]}))  # lower than the counter's last
    answer = out["ops"][0]
    assert answer["status"] == "needs_decision" and answer["reason"] == "refused" and "lower" in answer["message"]
    assert m.s.snapshot() == snapshot and out["work_orders"][wo["id"]]["status"] == "open"


# ---- what the device saw ---------------------------------------------------------------

def test_closed_by_someone_else_first_holds_back_only_what_cannot_apply(m):
    pos, hours, wo = _job(m)
    d = Device()
    open_only = {"work_order_status": ["open", "planned", "in_progress", "waiting"]}
    tick = d.op("work_orders.check", {"work_order_id": wo["id"], "index": 1, "done": True},
                {**open_only, "checklist_length": 2})
    note = d.op("work_orders.update", {"work_order_id": wo["id"], "append_note": "Found it dry"})
    labour = d.op("work_orders.labour", {"work_order_id": wo["id"], "hours": 1},
                  {"work_order_status": [*open_only["work_order_status"], "closed"]})
    close = d.op("work_orders.close", {"work_order_id": wo["id"], "actions": [{"kind": "inspect", "finding": "ok"}]},
                 {**open_only, "fitment_id": m.work_order(wo["id"])["fitted"]["id"]}, depends_on=[tick["op_id"]])
    m.close_work_order(wo["id"], [{"kind": "repair"}])                  # the planner, meanwhile
    out = d.push(m, tick, note, labour, close)
    assert _statuses(out) == ["needs_decision", "applied", "applied", "held"]
    assert out["ops"][0]["reason"] == "closed_elsewhere" and "was closed" in out["ops"][0]["message"]
    assert out["ops"][3]["waiting_on"] == tick["op_id"]
    view = out["work_orders"][wo["id"]]
    assert view["notes"].endswith("Found it dry") and view["totals"]["hours"] == 1 and len(view["actions"]) == 1
    # The user drops the tick; the close no longer waits on it and is refused in its own right.
    out = d.push(m, {**close, "depends_on": []})
    assert out["ops"][0]["reason"] == "closed_elsewhere"


def test_a_cancelled_job_a_different_fitment_and_a_changed_reading_each_say_so(m):
    pos, hours, wo = _job(m)
    d = Device()
    saw = m.work_order(wo["id"])["fitted"]["id"]
    m.close_work_order(m.open_work_order(pos["id"], "Swap the seal")["id"],
                       [{"kind": "replace", "new_item": {"name": "Seal Mk2"}}])
    out = d.push(m, d.op("work_orders.close", {"work_order_id": wo["id"], "actions": [{"kind": "repair"}]},
                         {"work_order_status": ["open"], "fitment_id": saw}))
    assert out["ops"][0]["expectation"] == "fitment_id" and "Seal Mk2" in out["ops"][0]["message"]
    m.record_reading(hours["id"], 50, at=_iso(-10))   # timed, so it stays before the readings below at midnight
    out = d.push(m, d.op("measurements.record", {"point_id": hours["id"], "value": 60, "at": _iso(-1)},
                         {"last_reading": {"point_id": hours["id"], "value": None}}))
    assert out["ops"][0]["expectation"] == "last_reading" and "50 hours" in out["ops"][0]["message"]
    m.cancel_work_order(wo["id"], "Duplicate of #7")
    out = d.push(m, d.op("work_orders.status", {"work_order_id": wo["id"], "status": "in_progress"},
                         {"work_order_status": ["open"]}),
                 d.op("measurements.record", {"point_id": hours["id"], "value": 70, "at": _iso(-1),
                                              "work_order_id": wo["id"]}))
    assert out["ops"][0]["reason"] == "cancelled" and "Duplicate of #7" in out["ops"][0]["message"]
    assert out["ops"][1]["status"] == "applied"        # the reading is the point's: kept, not linked
    assert "work_order_id" not in m.point(hours["id"])["readings"][0]
    gone = d.push(m, d.op("work_orders.update", {"work_order_id": "no-such-job", "append_note": "Hello"}))
    assert gone["ops"][0]["reason"] == "not_found" and gone["work_orders"]["no-such-job"] is None


def test_an_op_waits_for_the_one_it_follows_and_others_carry_on(m):
    pos, hours, wo = _job(m)
    other = m.open_work_order(pos["id"], "Grease the bearing")
    d = Device()
    bad = d.op("work_orders.check", {"work_order_id": wo["id"], "index": 7})
    follows = d.op("work_orders.update", {"work_order_id": wo["id"], "append_note": "Ticked line 8"},
                   depends_on=[bad["op_id"]])
    elsewhere = d.op("work_orders.update", {"work_order_id": other["id"], "append_note": "Greased"})
    out = d.push(m, bad, follows, elsewhere)
    assert _statuses(out) == ["needs_decision", "held", "applied"]
    # An op that follows one from an earlier push: applied if that one was, held if it never arrived.
    after = d.op("work_orders.update", {"work_order_id": other["id"], "append_note": "And wiped down"},
                 depends_on=[elsewhere["op_id"]])
    lost = d.op("work_orders.update", {"work_order_id": other["id"], "append_note": "x"},
                depends_on=[str(uuid.uuid4())])
    assert _statuses(d.push(m, after, lost)) == ["applied", "held"]


# ---- time ----------------------------------------------------------------------------

def test_work_done_on_monday_and_sent_on_wednesday_is_dated_monday(m, monkeypatch):
    monkeypatch.setattr(time_zones, "_now", lambda: datetime(2026, 11, 4, 3, 0, tzinfo=timezone.utc))
    pos, hours, wo = _job(m)
    d = Device()

    def op(command, args, when, **kw):
        return {**d.op(command, args, **kw), "device_time": when}

    monday = "2026-11-02T05:20:05Z"      # 15:20 on Monday in Brisbane
    out = d.push(
        m, op("work_orders.status", {"work_order_id": wo["id"], "status": "in_progress"}, monday),
        op("work_orders.update", {"work_order_id": wo["id"], "append_note": "Gland weeping"}, monday),
        op("work_orders.labour", {"work_order_id": wo["id"], "hours": 2}, monday),
        op("work_orders.close", {"work_order_id": wo["id"], "actions": [{"kind": "repair"}]}, "2026-11-02T20:30:00Z"))
    assert _statuses(out) == ["applied"] * 4
    view = out["work_orders"][wo["id"]]
    assert view["note_history"][-1] == {"on": "2026-11-02", "change": "appended", "text": "Gland weeping",
                                        "at": monday}
    assert view["labour"][0]["on"] == "2026-11-02"
    assert view["status_history"][-1]["on"] == "2026-11-02"
    assert view["closed"] == "2026-11-03"        # 06:30 on Tuesday in Brisbane, not Monday in UTC
    assert sync.applied(m, out["ops"][0]["op_id"])["on"] == "2026-11-02"


def test_a_clock_ahead_is_tolerated_for_ten_minutes_then_needs_a_decision(m):
    _pos, _hours, wo = _job(m)
    d = Device()
    fast = d.op("work_orders.update", {"work_order_id": wo["id"], "append_note": "A little fast"}, minutes=8)
    wrong = d.op("work_orders.update", {"work_order_id": wo["id"], "append_note": "Next week"}, minutes=60 * 24 * 7)
    out = d.push(m, fast, wrong)
    assert _statuses(out) == ["applied", "needs_decision"]
    assert out["ops"][1]["reason"] == "clock" and "Check the clock" in out["ops"][1]["message"]
    # The device knows its clock is a week fast: with its offset the same op is believed.
    week = 7 * 24 * 3600 * 1000
    assert _statuses(d.push(m, {**wrong, "clock_offset_ms": -week})) == ["applied"]
    assert m.work_order(wo["id"])["note_history"][-1]["on"] == m.today()


# ---- shape, limits ---------------------------------------------------------------------

def test_malformed_ops_are_refused_one_by_one_and_the_rest_go_through(m):
    _pos, _hours, wo = _job(m)
    d = Device()
    good = d.op("work_orders.update", {"work_order_id": wo["id"], "append_note": "Fine"})
    out = d.push(
        m, {**d.op("work_orders.update", {"work_order_id": wo["id"], "append_note": "x"}), "op_id": "17"},
        d.op("positions.delete", {"id": "anything"}),
        d.op("work_orders.update", {"work_order_id": wo["id"], "append_note": "x", "title": "Renamed"}),
        d.op("work_orders.update", {"work_order_id": wo["id"]}),
        {**d.op("work_orders.update", {"work_order_id": wo["id"], "append_note": "x"}), "device_time": "noon"},
        d.op("photos.add", {"target_id": wo["id"]}), good, "not an op")
    assert _statuses(out) == ["refused"] * 6 + ["applied", "refused"]
    assert "doesn't take title" in out["ops"][2]["message"] and "photo route" in out["ops"][5]["message"]
    assert m.work_order(wo["id"])["title"] == "Inspect the seal"


def test_a_push_is_at_most_fifty_ops(m):
    _pos, _hours, wo = _job(m)
    d = Device()
    ops = [d.op("work_orders.update", {"work_order_id": wo["id"], "append_note": f"n{i}"}) for i in range(51)]
    with pytest.raises(Invalid, match="At most 50"):
        d.push(m, *ops)
    assert _statuses(d.push(m, *ops[:50])) == ["applied"] * 50
    with pytest.raises(Invalid):
        sync.push(m, {"ops": "all of them"})


def test_too_many_changes_this_minute_says_retry_and_keeps_the_op(m, monkeypatch):
    from backend.maintenance import service

    _pos, _hours, wo = _job(m)
    d = Device()
    ops = [d.op("work_orders.update", {"work_order_id": wo["id"], "append_note": f"n{i}"}) for i in range(3)]
    m.s.write_windows.clear()
    monkeypatch.setattr(service, "WRITES_PER_MINUTE", 2)
    out = d.push(Maintenance(m.s, m.org, "tester", time_zone=BNE), *ops)
    assert _statuses(out) == ["applied", "applied", "retry"]
    m.s.write_windows.clear()
    assert _statuses(d.push(Maintenance(m.s, m.org, "tester", time_zone=BNE), *ops)) == ["duplicate"] * 2 + ["applied"]


def test_someone_else_writing_between_ops_is_seen_by_the_next_op(m):
    """The copy a batch runs on is made again when the workspace has moved."""
    _pos, _hours, wo = _job(m)
    d = Device()
    run = sync.Push(m, "phone-1", BNE)
    assert run.run(d.op("work_orders.status", {"work_order_id": wo["id"], "status": "in_progress"}))["status"] == \
        "applied"
    m.close_work_order(wo["id"], [{"kind": "repair"}])                  # between two ops of one push
    answer = run.run(d.op("work_orders.check", {"work_order_id": wo["id"], "index": 0},
                          {"work_order_status": ["in_progress"]}))
    assert answer["reason"] == "closed_elsewhere"


def test_histories_read_a_devices_change_as_the_events_inside_it(m):
    from backend.maintenance.service import _flat_events

    pos, hours, wo = _job(m)
    d = Device()
    d.push(m, d.op("work_orders.close", {"work_order_id": wo["id"], "actions": [{"kind": "repair"}],
                                         "readings": [{"point_id": hours["id"], "value": 5}]}))
    flat = _flat_events(m.s.events(m.org, 3))
    assert [e["type"] for e in flat[:3]] == ["work_order.closed", "action.recorded", "reading.added"]  # newest first
    assert flat[0]["actor"] == "tester" and flat[0]["payload"]["id"] == wo["id"]
    assert m.explain_task(m.s.out(m.org, wo["id"], "FOR")[0]["id"])["history"]   # still reads


# ---- many devices, lost answers, any order ---------------------------------------------

@pytest.mark.parametrize("seed", range(6))
def test_random_devices_retries_and_reordering_never_double_and_always_settle(seed):
    rng = random.Random(seed)
    m = Maintenance(GraphStore(":memory:", PROJECTORS), "user-u", "tester", time_zone=BNE)
    pos, hours, _wo = _job(m)
    jobs = [m.open_work_order(pos["id"], f"Job {i}")["id"] for i in range(4)]
    devices = [Device(f"phone-{i}") for i in range(3)]
    made: list[tuple[Device, dict]] = []
    counter = 100
    for _ in range(60):
        d = rng.choice(devices)
        job = rng.choice(jobs)
        kind = rng.choice(["note", "labour", "part", "status", "reading", "close"])
        if kind == "note":
            op = d.op("work_orders.update", {"work_order_id": job, "append_note": f"note {len(made)}"})
        elif kind == "labour":
            op = d.op("work_orders.labour", {"work_order_id": job, "hours": 1})
        elif kind == "part":
            op = d.op("work_orders.part_used", {"work_order_id": job, "part": f"part {len(made)}"})
        elif kind == "status":
            op = d.op("work_orders.status", {"work_order_id": job, "status": rng.choice(["in_progress", "waiting"])},
                      {"work_order_status": ["open", "planned", "in_progress", "waiting"]})
        elif kind == "reading":
            counter += 1
            op = d.op("measurements.record", {"point_id": hours["id"], "value": counter, "at": _iso(-60 + len(made))})
        else:
            op = d.op("work_orders.close", {"work_order_id": job, "actions": [{"kind": "repair"}]},
                      {"work_order_status": ["open", "planned", "in_progress", "waiting"]})
        made.append((d, op))
    final: dict[str, str] = {}
    pending = list(made)
    rounds = 0
    while pending and rounds < 200:
        rounds += 1
        batch = rng.sample(pending, min(len(pending), rng.randint(1, 12)))     # any order, any mix
        by_device: dict[str, list] = {}
        for d, op in batch:
            by_device.setdefault(d.name, []).append(op)
        for name, ops in by_device.items():
            out = sync.push(m, {"device_id": name, "device_tz": BNE, "ops": ops})
            for answer in out["ops"]:
                status = answer["status"]
                assert status in ("applied", "duplicate", "needs_decision"), answer
                if status == "duplicate":
                    assert sync.applied(m, answer["op_id"])              # only ever said of one that is there
                    assert final.get(answer["op_id"]) == "applied"       # and that this test saw applied
                elif status == "applied":
                    assert final.get(answer["op_id"]) != "applied"       # never applied twice
                    final[answer["op_id"]] = "applied"
                else:
                    assert final.get(answer["op_id"]) != "applied"
                    final[answer["op_id"]] = status
        # The answer to an op is "lost" three times in ten: it stays in the outbox and goes again.
        sent = {op["op_id"] for _d, op in batch}
        pending = [(d, op) for d, op in pending if op["op_id"] not in sent or rng.random() < 0.3]
    # Every op was answered; each applied op is in the graph exactly once.
    assert set(final) == {op["op_id"] for _d, op in made}
    applied = [op for _d, op in made if sync.applied(m, op["op_id"])]
    notes = "\n".join(m.work_order(j)["notes"] for j in jobs)
    for op in applied:
        if op["command"] == "work_orders.update":
            assert notes.count(op["args"]["append_note"] + "\n") + notes.endswith(op["args"]["append_note"]) >= 1
    for op in (o for _d, o in made if o["command"] == "work_orders.update"):
        text = op["args"]["append_note"]
        hits = sum(1 for j in jobs for h in m.work_order(j)["note_history"] if h["text"] == text)
        assert hits == (1 if sync.applied(m, op["op_id"]) else 0)
    labour_ops = sum(1 for o in applied if o["command"] == "work_orders.labour")
    assert sum(len(m.work_order(j)["labour"]) for j in jobs) == labour_ops
    reading_ops = sum(1 for o in applied if o["command"] == "measurements.record")
    assert len([r for r in m.point(hours["id"])["readings"] if not r.get("struck")]) == reading_ops
    closes = sum(1 for o in applied if o["command"] == "work_orders.close")
    assert closes == sum(1 for j in jobs if m.work_order(j)["status"] == "closed")
    _same_after_rebuild(m)


# ---- the asset trees in the pack (a phone browses them with no signal) ----------------


def _plant(m):
    """A site with a pump station: a pump with a motor fitted, a spare in the store,
    an item with no home, and a point read three times."""
    site = m.create_location("North site")
    store = m.create_location("Store", parent_id=site["id"])
    pump = m.create_position("Pump station 1", tag="PS-1", location_id=site["id"])
    motor = m.create_position("Drive motor", tag="M-01", parent_id=pump["id"], position_class="Motor")
    m.fit(motor["id"], new_item={"name": "WEG 30 kW", "serial": "SN-77"})
    spare = m.create_item("Spare motor", serial="SN-99")
    m.place_item(spare["id"], store["id"])
    loose = m.create_item("Old gearbox")
    point = m.add_point(motor["id"], "Bearing temperature", kind="condition", unit="°C")
    for i, value in enumerate((61, 64, 70)):
        m.record_reading(point["id"], value, at=f"2026-11-0{i + 1}T08:00:00+10:00")
    wo = m.open_work_order(motor["id"], "Bearing running hot")
    return {"site": site, "store": store, "pump": pump, "motor": motor, "spare": spare, "loose": loose,
            "point": point, "wo": wo}


def test_the_tree_is_every_position_once_flat_and_lean(m):
    p = _plant(m)
    tree = sync.device_tree(m)
    rows = {r["id"]: r for r in tree["positions"]}
    assert set(rows) == {p["pump"]["id"], p["motor"]["id"]}
    motor = rows[p["motor"]["id"]]
    assert motor["parent_id"] == p["pump"]["id"] and motor["tag"] == "M-01" and motor["position_class"] == "Motor"
    assert motor["item"]["name"] == "WEG 30 kW" and motor["item"]["serial"] == "SN-77"
    assert motor["open_work"] == 1
    pump = rows[p["pump"]["id"]]
    assert pump["parent_id"] is None and pump["location_id"] == p["site"]["id"]
    assert "item" not in pump and "open_work" not in pump and "position_class" not in pump   # empty: left out
    assert {(x["name"], x["parent_id"]) for x in tree["locations"]} == {("North site", None),
                                                                        ("Store", p["site"]["id"])}
    assert tree["spares"] == [{"id": p["spare"]["id"], "name": "Spare motor", "location_id": p["store"]["id"],
                               "serial": "SN-99"}]
    assert [x["name"] for x in tree["unhomed"]] == ["Old gearbox"]


def test_a_pack_with_the_tree_carries_where_the_work_is_and_what_is_kept(m):
    p = _plant(m)
    plain = sync.pack(m, {})
    assert "tree" not in plain and "assets" not in plain           # an older phone's pack is as it was
    out = sync.pack(m, {"tree": True, "keep": [p["spare"]["id"], p["site"]["id"], "gone-id"]})
    assert len(out["tree"]["positions"]) == 2
    assets = out["assets"]
    assert set(assets) == {p["spare"]["id"], p["site"]["id"], p["motor"]["id"]}   # kept, then the work's
    motor = assets[p["motor"]["id"]]
    assert motor["kind"] == "position" and [x["name"] for x in motor["path"]] == ["Pump station 1"]
    assert motor["item"]["serial"] == "SN-77" and motor["location"]["name"] == "North site"
    temp = motor["readings"][0]
    assert temp["name"] == "Bearing temperature" and temp["reading"] == 70
    assert [r["value"] for r in temp["recent"]] == [70, 64, 61]                    # newest first
    spare = assets[p["spare"]["id"]]
    assert spare["kind"] == "item" and spare["serial"] == "SN-99" and spare["location"]["name"] == "Store"
    assert assets[p["site"]["id"]]["kind"] == "location"
    with pytest.raises(Invalid):
        sync.pack(m, {"tree": True, "keep": ["x"] * (sync.MAX_DETAILS + 1)})
    with pytest.raises(Invalid):
        sync.pack(m, {"tree": True, "keep": "all"})


def test_the_tree_stays_a_sensible_size(m):
    """At the workspace's cap of positions (20,000) the tree must still be a download a
    phone can take: measured here on 1,500 positions, a few hundred with items fitted."""
    import gzip
    import json

    from backend.maintenance.service import MAX_POSITIONS

    site = m.create_location("Mine site")
    lines = [m.create_position(f"Conveyor CV-{i:02d}", tag=f"CV-{i:02d}", location_id=site["id"]) for i in range(30)]
    for i in range(1470):
        pos = m.create_position(f"Idler set {i:04d}", tag=f"ID-{i:04d}", parent_id=lines[i % 30]["id"],
                                position_class="Idler set")
        if i % 5 == 0:
            m.fit(pos["id"], new_item={"name": "Idler 152 mm", "serial": f"IS-{i:05d}"})
    tree = sync.device_tree(m)
    assert len(tree["positions"]) == 1500
    raw = json.dumps(tree, separators=(",", ":")).encode()
    per_position = len(raw) / 1500
    assert per_position < 200, per_position                      # about 3 to 4 MB at the cap
    assert per_position * MAX_POSITIONS < 4_000_000
    assert len(gzip.compress(raw, 6)) < len(raw) / 4               # and well under 1 MB over the wire
