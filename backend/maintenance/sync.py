"""Changes from a device that works offline, sent later (routers/maintenance_sync.py).

A device (a phone in a plant room with no signal) keeps what its user did as a
queue of **ops**: a command with its arguments, an id the device made up
(``op_id``), the order it was made in (``device_seq``), the device's clock
when it was made, and what the device saw at the time (``expects``). When it
has signal again it pushes them, up to :data:`MAX_OPS` at a time, and
:func:`push` answers each one:

``applied``
    Recorded now.
``duplicate``
    This op was recorded before (the answer got lost and the device sent it
    again, or two sends crossed). Nothing was recorded twice.
``held``
    An earlier op it depends on (``depends_on``) hasn't been applied, so this
    one waits; ``waiting_on`` names it.
``needs_decision``
    The server said no: what the device saw is no longer so, the command was
    refused, the thing is gone, or the device's clock is ahead. ``reason`` and
    ``message`` say which in plain words; nothing was recorded, and a person
    chooses what to do with it.
``retry``
    Not now (too many changes this minute, or the workspace changed under the
    op twice): send it again later, unchanged.
``refused``
    The op itself is malformed (no id, an unknown command, an argument the
    command doesn't take). Sending it again won't help.

**Once only.** Each op becomes one event in the log, ``op.applied``, holding
the events the command comes to (a close's readings, actions and the close
itself, say). One event is written whole or not at all, so a crash part-way
through a command leaves nothing behind, and the op's id is in the log: the
projector remembers it on a ``SyncOp`` node and ignores a second ``op.applied``
with the same id. "Has this op been applied?" is therefore read from the
graph, which is rebuilt from the log, and holds for as long as the log does.

**How.** A command runs first on a throwaway copy of the workspace
(:func:`store.scratch_copy`), through the same ``Maintenance`` methods as
every other caller, with "today" set to the day the op was made. The events
it wrote there are then appended to the real log as the one ``op.applied``.
A refusal on the copy writes nothing real.

**Time.** The op's ``device_time`` plus the device's own estimate of how far
its clock is from the server's (``clock_offset_ms``, when it has one) is when
the change was made: its day in the workspace's zone is the change's "today",
and an appended note carries the moment. More than ``service.CLOCK_TOLERANCE``
ahead of the server it isn't believed: ``needs_decision``, reason ``clock``.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timedelta, timezone

from backend.errors import client_message
from backend.maintenance.service import (CLOCK_TOLERANCE, OPEN_STATUSES, Invalid, Maintenance, NotFound, RateLimited,
                                         op_node_id)
from backend.maintenance.store import new_id, scratch_copy
from backend.services import time_zones

logger = logging.getLogger(__name__)

#: Ops in one push.
MAX_OPS = 50
_OP_ID = re.compile(r"^[0-9a-fA-F]{8}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{12}$")
_PHOTO_NS = uuid.UUID("6f0c0f5e-3b0a-4d57-9a55-1d1a0a6d7c11")

STATUS_WORDS = {"open": "open", "planned": "planned", "in_progress": "in progress", "waiting": "waiting",
                "closed": "closed", "cancelled": "cancelled"}


class Malformed(ValueError):
    """An op the server can't read: answered ``refused``."""


def photo_id_for(org: str, op_id: str) -> str:
    """The id of the photo an op adds: the same every time the op is sent, so its
    bytes are stored once however often it is uploaded."""
    return uuid.uuid5(_PHOTO_NS, f"{org}:{op_id.lower()}").hex


# ---- the commands ----------------------------------------------------------------
# Each: the arguments it takes (required, optional), and how it runs on a Maintenance.
# The names and arguments are the maintenance tool actions' (work_orders.status and so
# on), so an op reads the same as the one-at-a-time call it replaces.

def _status(m: Maintenance, a: dict, op: dict) -> dict:
    return m.set_work_status(a["work_order_id"], a["status"], a.get("note") or "")


def _note(m: Maintenance, a: dict, op: dict) -> dict:
    return m.update_work_order(a["work_order_id"], append_note=a["append_note"], note_at=a.get("at") or op["at"])


def _check(m: Maintenance, a: dict, op: dict) -> dict:
    index = a["index"]
    if isinstance(index, bool) or not isinstance(index, int):
        raise Invalid("index is the checklist line's number, from 0.")
    return m.check_item(a["work_order_id"], index, bool(a.get("done", True)))


def _mark(m: Maintenance, a: dict, op: dict) -> dict:
    return m.mark_line(a["work_order_id"], a["task_id"], a["state"], a.get("reason"), a.get("finding"))


def _labour(m: Maintenance, a: dict, op: dict) -> dict:
    return m.log_labour(a["work_order_id"], a["hours"], a.get("who") or "", None, a.get("on"), a.get("note") or "")


def _part_used(m: Maintenance, a: dict, op: dict) -> dict:
    return m.add_part_used(a["work_order_id"], part=a.get("part"), quantity=a.get("quantity") or 1,
                           note=a.get("note") or "", part_id=a.get("part_id") or None,
                           from_location_id=a.get("from_location_id") or None)


def _close(m: Maintenance, a: dict, op: dict) -> dict:
    return m.close_work_order(a["work_order_id"], a.get("actions") or (), a.get("on"), a.get("notes") or "",
                              a.get("readings") or (), a.get("not_done") or ())


def _reading(m: Maintenance, a: dict, op: dict) -> dict:
    # Taken at a work order: linked to it, unless it has been cancelled since (the
    # reading is the point's, and is still true).
    link = a.get("work_order_id") or None
    if link:
        wo = m.s.node(m.org, str(link), "WorkOrder")
        if wo is None or wo["status"] == "cancelled":
            link = None
    return m.record_reading(a["point_id"], a["value"], a.get("on"), a.get("note") or "", a.get("at"),
                            a.get("precision"), work_order_id=link, task_id=a.get("task_id") if link else None)


def _photo(m: Maintenance, a: dict, op: dict) -> dict:
    return m.add_photo(op["photo_id"], a["target_id"], op["cleaned"], a.get("caption") or "", "app")


COMMANDS: dict[str, tuple[tuple[str, ...], tuple[str, ...], object]] = {
    "work_orders.status": (("work_order_id", "status"), ("note",), _status),
    "work_orders.update": (("work_order_id", "append_note"), ("at",), _note),
    "work_orders.check": (("work_order_id", "index"), ("done",), _check),
    "work_orders.mark": (("work_order_id", "task_id", "state"), ("reason", "finding"), _mark),
    "work_orders.labour": (("work_order_id", "hours"), ("who", "on", "note"), _labour),
    "work_orders.part_used": (("work_order_id",), ("part", "part_id", "quantity", "note", "from_location_id"),
                              _part_used),
    "work_orders.close": (("work_order_id",), ("actions", "on", "notes", "readings", "not_done"), _close),
    "measurements.record": (("point_id", "value"), ("work_order_id", "task_id", "on", "at", "precision", "note"),
                            _reading),
    # Only through the photo route: the image is the request's body.
    "photos.add": (("target_id",), ("caption", "work_order_id"), _photo),
}
#: What ``expects`` may hold.
EXPECTS = ("work_order_status", "fitment_id", "checklist_length", "last_reading")


def _parse_time(value) -> datetime:
    """An op's device_time: ISO with Z or an offset."""
    try:
        t = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        raise Malformed("device_time is the device's clock when the change was made, like 2026-11-04T00:14:05Z.") \
            from None
    if t.tzinfo is None:
        raise Malformed("device_time needs Z or an offset, like 2026-11-04T00:14:05Z.")
    return t.astimezone(timezone.utc)


def read_op(raw, photo: bool = False) -> dict:
    """An op as sent, checked for shape (not for sense: that's the command's job).
    Raises :class:`Malformed`."""
    if not isinstance(raw, dict):
        raise Malformed("An op is an object: {op_id, device_seq, command, args, device_time, …}.")
    op_id = raw.get("op_id")
    if not isinstance(op_id, str) or not _OP_ID.match(op_id):
        raise Malformed("op_id is a UUID the device makes for each change.")
    command = raw.get("command")
    if command not in COMMANDS or (command == "photos.add") != photo:
        known = ", ".join(c for c in COMMANDS if c != "photos.add")
        raise Malformed("A photo goes to the photo route, with the image as the body." if command == "photos.add"
                        else f"command is one of: {known}.")
    required, optional, _run = COMMANDS[command]
    args = raw.get("args") or {}
    if not isinstance(args, dict):
        raise Malformed("args is an object of the command's arguments.")
    extra = sorted(set(args) - set(required) - set(optional))
    if extra:
        raise Malformed(f"{command} doesn't take {', '.join(extra)}.")
    missing = [k for k in required if args.get(k) in (None, "")]
    if missing:
        raise Malformed(f"{command} needs {', '.join(missing)}.")
    expects = raw.get("expects") or {}
    if not isinstance(expects, dict) or set(expects) - set(EXPECTS):
        raise Malformed(f"expects may hold: {', '.join(EXPECTS)}.")
    seq = raw.get("device_seq")
    if isinstance(seq, bool) or not isinstance(seq, int) or seq < 0:
        raise Malformed("device_seq is the op's number on the device: 1, 2, 3, …")
    depends = raw.get("depends_on") or []
    if not isinstance(depends, list) or any(not isinstance(d, str) or not _OP_ID.match(d) for d in depends):
        raise Malformed("depends_on is a list of earlier op ids.")
    offset = raw.get("clock_offset_ms")
    if offset is not None and (isinstance(offset, bool) or not isinstance(offset, (int, float))
                               or offset != offset or abs(offset) > 366 * 86400 * 1000):
        raise Malformed("clock_offset_ms is the server's clock minus the device's, in milliseconds, or null.")
    made = _parse_time(raw.get("device_time"))
    effective = made + timedelta(milliseconds=offset or 0)
    return {"op_id": op_id.lower(), "command": command, "args": args, "expects": expects, "device_seq": seq,
            "depends_on": [d.lower() for d in depends], "clock_offset_ms": offset,
            "device_time": made.strftime("%Y-%m-%dT%H:%M:%SZ"), "effective": effective,
            "at": effective.strftime("%Y-%m-%dT%H:%M:%SZ")}


def _number(value) -> str:
    return f"{value:g}" if isinstance(value, (int, float)) and not isinstance(value, bool) else str(value)


class Push:
    """One push: ops applied in the order the device made them."""

    def __init__(self, m: Maintenance, device_id: str | None = None, device_tz: str | None = None):
        self.m = m
        self.device_id = str(device_id)[:64] if device_id else None
        self.device_tz = device_tz if isinstance(device_tz, str) and time_zones.zone(device_tz) else None
        self._copy = None      # the throwaway copy the next command runs on
        self._mark = 0         # the copy's log, read up to here
        self._events = -1      # the workspace's event count the copy matches
        self.outcome: dict[str, str] = {}   # op_id -> status, this push
        self.work_orders: set[str] = set()
        self.points: set[str] = set()

    # -- the copy --------------------------------------------------------------------

    def _fresh_copy(self):
        """The throwaway copy, in step with the workspace: made again when anything
        else has written to the workspace since, or a refused command left it dirty."""
        self.m.s.sync()
        count = self.m.s.event_count(self.m.org)
        if self._copy is None or count != self._events:
            self._copy = scratch_copy(self.m.s, self.m.org)
            # Readings from feeds aren't in the graph: the copy reads the real ones.
            for shared in ("series", "snapshots"):
                if hasattr(self.m.s, shared):
                    setattr(self._copy, shared, getattr(self.m.s, shared))
            self._mark, self._events = 0, count
        return self._copy

    def _drop_copy(self) -> None:
        self._copy = None

    # -- answers ---------------------------------------------------------------------

    def _answer(self, op: dict | None, status: str, raw=None, **more) -> dict:
        op_id = op["op_id"] if op else (raw.get("op_id") if isinstance(raw, dict) else None)
        if isinstance(op_id, str):
            self.outcome[op_id.lower()] = status
        out = {"op_id": op_id, "status": status, **{k: v for k, v in more.items() if v is not None}}
        if op:
            wo = op["args"].get("work_order_id")
            if op["command"] == "photos.add" and not wo:
                wo = self._work_order_id_of(op["args"].get("target_id"))
            if wo:
                out["work_order_id"] = str(wo)
                self.work_orders.add(str(wo))
            if op["command"] == "measurements.record":
                out["point_id"] = str(op["args"]["point_id"])
                self.points.add(out["point_id"])
        return out

    def _work_order_id_of(self, node_id) -> str | None:
        node = self.m.s.node(self.m.org, node_id) if isinstance(node_id, str) else None
        return node["id"] if node and node["label"] == "WorkOrder" else None

    def _applied_node(self, op_id: str) -> dict | None:
        return self.m.s.node(self.m.org, op_node_id(op_id), "SyncOp")

    # -- one op ------------------------------------------------------------------------

    def run(self, raw, photo: dict | None = None) -> dict:
        """Apply one op and answer it. ``photo``: for photos.add, ``{"cleaned": …,
        "photo_id": …}`` (the bytes are already stored under that id)."""
        try:
            op = read_op(raw, photo=photo is not None)
        except Malformed as err:
            return self._answer(None, "refused", raw, message=str(err))
        if photo:
            op.update(photo)
        self.m.s.sync()
        if self._applied_node(op["op_id"]) is not None:
            return self._duplicate(op)
        for dep in op["depends_on"]:
            done = self.outcome.get(dep)
            if done is None:
                done = "applied" if self._applied_node(dep) is not None else "missing"
            if done not in ("applied", "duplicate"):
                return self._answer(op, "held", waiting_on=dep,
                                    message="An earlier change this one follows hasn't been applied yet.")
        ahead = op["effective"] - time_zones.now()
        if ahead > CLOCK_TOLERANCE:
            return self._answer(op, "needs_decision", reason="clock", message=(
                f"This change is stamped {round(ahead.total_seconds() / 60)} minutes ahead of the server's time. "
                "Check the clock on the device, then send it again."))
        for attempt in (1, 2):
            answer = self._attempt(op)
            if answer is not None:
                return answer
        return self._answer(op, "retry", message="The workspace changed while this was being applied. Send it "
                                                 "again.")

    def _duplicate(self, op: dict) -> dict:
        node = self._applied_node(op["op_id"]) or {}
        return self._answer(op, "duplicate", ref=node.get("ref") or None, applied_on=node.get("on"))

    def _attempt(self, op: dict) -> dict | None:
        """Run the op's command on the copy, then record it. None: the workspace moved
        under it (try once more on a fresh copy)."""
        try:
            self.m.check_limits()
        except RateLimited as err:
            return self._answer(op, "retry", message=client_message(err))
        except Invalid as err:
            return self._answer(op, "needs_decision", reason="refused", message=client_message(err))
        copy = self._fresh_copy()
        day = time_zones.day_of(op["effective"], self.m.tz)
        on_copy = Maintenance(copy, self.m.org, self.m.actor, limited=self.m.limited, time_zone=self.m.time_zone,
                              as_of=day)
        on_copy._checked = True  # counted once, on the workspace itself (above)
        run = COMMANDS[op["command"]][2]
        try:
            failed = self._check_expects(on_copy, op)
            if failed:
                return self._answer(op, "needs_decision", **failed)
            run(on_copy, op["args"], op)
        except NotFound:
            self._drop_copy()
            return self._answer(op, "needs_decision", reason="not_found",
                                message="The server no longer has what this change is for.")
        except RateLimited as err:
            self._drop_copy()
            return self._answer(op, "retry", message=client_message(err))
        except Invalid as err:
            self._drop_copy()
            text = client_message(err)
            reason = "refused"
            wo = self._node_status(op)
            if wo == "closed" and re.search(r"already closed|closed or cancelled|only an open", text, re.I):
                reason = "closed_elsewhere"
            elif wo == "cancelled":
                reason = "cancelled"
            return self._answer(op, "needs_decision", reason=reason, message=text)
        events = [{"type": e["type"], "payload": e["payload"]} for e in copy.log.since(self._mark)]
        self._mark += len(events)
        apply_id = new_id()
        ref = {k: str(op["args"][k]) for k in ("work_order_id", "point_id", "target_id") if op["args"].get(k)}
        if op.get("photo_id"):
            ref["photo_id"] = op["photo_id"]
        payload = {"op_id": op["op_id"], "apply_id": apply_id, "device_id": self.device_id,
                   "device_seq": op["device_seq"], "command": op["command"], "device_time": op["device_time"],
                   "device_tz": self.device_tz, "clock_offset_ms": op["clock_offset_ms"], "on": day, "ref": ref,
                   "events": events}
        try:
            self.m._emit("op.applied", payload)
        except Exception:  # noqa: BLE001 - the workspace isn't as the copy had it: nothing was written
            logger.info("sync op %s didn't apply to the workspace as it did to the copy; trying again",
                        op["op_id"], exc_info=True)
            self._drop_copy()
            return None
        self._events += 1
        node = self._applied_node(op["op_id"])
        if node is None or node.get("apply_id") != apply_id:
            # The same op, sent twice at once: the other send was first in the log.
            self._drop_copy()
            return self._duplicate(op)
        return self._answer(op, "applied", ref=ref or None, applied_on=day)

    def _node_status(self, op: dict) -> str | None:
        wo = op["args"].get("work_order_id")
        node = self.m.s.node(self.m.org, str(wo), "WorkOrder") if wo else None
        return node["status"] if node else None

    def _check_expects(self, m: Maintenance, op: dict) -> dict | None:
        """What the device saw against what is so now: None when it still holds, else
        the answer's reason, expectation and message."""
        expects = op["expects"]
        if not expects:
            return None
        wo_id = op["args"].get("work_order_id")
        view = m.work_order(str(wo_id)) if wo_id else None
        want = expects.get("work_order_status")
        if want is not None and view is not None:
            if not isinstance(want, list):
                raise Invalid("expects.work_order_status is a list of statuses.")
            if view["status"] not in want:
                number = f"Work order #{view['number']}"
                if view["status"] == "closed":
                    when = f" on {view['closed']}" if view.get("closed") else ""
                    return {"reason": "closed_elsewhere", "expectation": "work_order_status",
                            "message": f"{number} was closed{when} before this change reached the server."}
                if view["status"] == "cancelled":
                    why = f" ({view['cancel_reason']})" if view.get("cancel_reason") else ""
                    return {"reason": "cancelled", "expectation": "work_order_status",
                            "message": f"{number} was cancelled{why} before this change reached the server."}
                was = " or ".join(STATUS_WORDS.get(s, str(s)) for s in want)
                return {"reason": "precondition", "expectation": "work_order_status",
                        "message": f"{number} is now {STATUS_WORDS.get(view['status'], view['status'])}, not "
                                   f"{was} as the device saw it."}
        if "fitment_id" in expects and view is not None:
            fitted = view.get("fitted") or None
            current = fitted["id"] if fitted else None
            if current != expects["fitment_id"]:
                name = ((fitted or {}).get("item") or {}).get("name")
                return {"reason": "precondition", "expectation": "fitment_id", "message": (
                    "The item the device saw fitted has been removed since. A planner will need to sort this out."
                    if current is None else
                    f"A different item{f' ({name})' if name else ''} is fitted now. Someone has replaced it since "
                    "the device looked.")}
        if expects.get("checklist_length") is not None and view is not None \
                and len(view.get("checklist") or []) != expects["checklist_length"]:
            return {"reason": "precondition", "expectation": "checklist_length", "message": (
                "The checklist has changed since the device saw it, so the line numbers no longer match. Open the "
                "work order and tick the right line.")}
        last = expects.get("last_reading")
        if last:
            if not isinstance(last, dict) or not last.get("point_id"):
                raise Invalid("expects.last_reading is {point_id, value}.")
            point = m.point(str(last["point_id"]))
            if point.get("reading") != last.get("value"):
                unit = f" {point['unit']}" if point.get("unit") else ""
                return {"reason": "precondition", "expectation": "last_reading", "message": (
                    f"Someone recorded a reading on {point['name']} since the device looked (now "
                    f"{_number(point.get('reading'))}{unit}). Check the value before sending.")}
        return None

    # -- the whole push ------------------------------------------------------------------

    def views(self) -> dict:
        """What the ops touched, as it is now: the device replaces its copies with these."""
        out: dict = {"work_orders": {}, "points": {}}
        for wo in sorted(self.work_orders):
            try:
                out["work_orders"][wo] = self.m.work_order(wo)
            except NotFound:
                out["work_orders"][wo] = None
        for point in sorted(self.points):
            try:
                out["points"][point] = self.m.point(point)
            except NotFound:
                out["points"][point] = None
        return out

    def stamp(self) -> dict:
        return {"server_time": time_zones.now().strftime("%Y-%m-%dT%H:%M:%SZ"), "today": self.m.today(),
                "time_zone": self.m.time_zone}


def push(m: Maintenance, body: dict) -> dict:
    """Apply a batch of ops in the order the device made them. ``body``:
    ``{device_id, device_tz, ops: [{op_id, device_seq, command, args, expects?,
    device_time, clock_offset_ms?, depends_on?}]}``. Returns ``{ops: [{op_id,
    status, …}], work_orders: {id: view}, points: {id: view}, server_time, today,
    time_zone}``. Raises Invalid for a body that isn't a batch at all."""
    if not isinstance(body, dict) or not isinstance(body.get("ops"), list):
        raise Invalid("Send {device_id, device_tz, ops: [...]}.")
    ops = body["ops"]
    if len(ops) > MAX_OPS:
        raise Invalid(f"At most {MAX_OPS} ops in one push; send the rest in the next.")
    run = Push(m, body.get("device_id"), body.get("device_tz"))
    order = sorted(range(len(ops)), key=lambda i: (
        ops[i].get("device_seq") if isinstance(ops[i], dict) and isinstance(ops[i].get("device_seq"), int)
        and not isinstance(ops[i].get("device_seq"), bool) else 0, i))
    answers: list = [None] * len(ops)
    seen: dict[str, dict] = {}
    for i in order:
        raw = ops[i]
        op_id = raw.get("op_id").lower() if isinstance(raw, dict) and isinstance(raw.get("op_id"), str) else None
        if op_id and op_id in seen:
            # The same op twice in one push: the first one's answer (a duplicate, if that applied it).
            first = seen[op_id]
            answers[i] = {**first, "status": "duplicate"} if first["status"] == "applied" else dict(first)
            continue
        answers[i] = run.run(raw)
        if op_id:
            seen[op_id] = answers[i]
    return {"ops": answers, **run.views(), **run.stamp()}


def push_photo(m: Maintenance, raw_op: dict, cleaned: dict, device_id=None, device_tz=None) -> dict:
    """One photos.add op, its image already cleaned and stored under
    :func:`photo_id_for`. Returns ``{op: {op_id, status, …}, photo, server_time, …}``."""
    run = Push(m, device_id, device_tz)
    op_id = raw_op.get("op_id") if isinstance(raw_op, dict) else None
    photo_id = photo_id_for(m.org, op_id) if isinstance(op_id, str) and _OP_ID.match(op_id) else ""
    answer = run.run(raw_op, photo={"cleaned": cleaned, "photo_id": photo_id})
    photo = None
    if answer["status"] in ("applied", "duplicate"):
        try:
            photo = m.photo((answer.get("ref") or {}).get("photo_id") or photo_id)
        except NotFound:
            photo = None
    return {"op": answer, "photo": photo, **run.views(), **run.stamp()}


#: Work orders in one pack: more than a phone's day, short of a slow answer.
MAX_PACK = 200


def pack(m: Maintenance, body: dict | None = None) -> dict:
    """What a device needs to do its work with no signal, in one answer: every open
    work order in full (its position and location, tasks, checklist, instructions,
    the points to read with their last readings, failure modes, suggested parts),
    the list rows they are shown from, and the parts catalogue for "part used".
    The views are the ones the app's pages read: the device keeps them as they
    come and never works anything out itself.

    ``body``: ``{work_order_ids?: [...]}`` for just those (open or not: a job closed
    since is still wanted, to show that it was), else every open one, the most
    overdue first, up to :data:`MAX_PACK` (``more`` says some were left out).
    ``if_mark``: the ``mark`` of the pack the device has; when nothing in the
    workspace has changed since, the answer is ``{unchanged: true}``."""
    body = body or {}
    if not isinstance(body, dict):
        raise Invalid("Send {work_order_ids?: [...], if_mark?: N}.")
    m.s.sync()
    mark = m.s.event_count(m.org)
    stamp = {"mark": mark, "server_time": time_zones.now().strftime("%Y-%m-%dT%H:%M:%SZ"), "today": m.today(),
             "time_zone": m.time_zone}
    if body.get("if_mark") is not None and body.get("if_mark") == mark:
        return {"unchanged": True, **stamp}
    wanted = body.get("work_order_ids")
    briefs = m.work_orders("open")
    more = False
    if wanted is not None:
        if not isinstance(wanted, list) or len(wanted) > MAX_PACK or any(not isinstance(w, str) for w in wanted):
            raise Invalid(f"work_order_ids is a list of at most {MAX_PACK} ids.")
        ids = list(dict.fromkeys(wanted))
    else:
        more = len(briefs) > MAX_PACK
        briefs = briefs[:MAX_PACK]
        ids = [b["id"] for b in briefs]
    full, gone = [], []
    for wo_id in ids:
        try:
            full.append(m.work_order(wo_id))
        except NotFound:
            gone.append(wo_id)
    if wanted is not None:
        open_rows = {b["id"]: b for b in briefs}
        briefs = [open_rows[i] for i in ids if i in open_rows]
    parts = [{k: p.get(k) for k in ("id", "part_number", "name", "unit", "manufacturer")}
             for p in m.s.nodes(m.org, "Part") if not p.get("retired")]
    parts.sort(key=lambda p: str(p.get("part_number") or "").lower())
    return {"unchanged": False, "briefs": briefs, "work_orders": full, "gone": gone, "more": more, "parts": parts,
            **stamp}


def applied(m: Maintenance, op_id: str) -> dict | None:
    """The record of an op that has been applied, or None."""
    m.s.sync()
    return m.s.node(m.org, op_node_id(str(op_id).lower()), "SyncOp")


__all__ = ["COMMANDS", "MAX_OPS", "OPEN_STATUSES", "Malformed", "Push", "applied", "pack", "photo_id_for", "push",
           "push_photo", "read_op"]
