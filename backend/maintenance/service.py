"""The maintenance domain: what can be done to the plant, as events, and what
can be read back from the graph they build.

Positions are the jobs (the functional hierarchy, ``=``); locations are
places (``+``); items are the physical things. An item is *fitted* to a
position (a Fitment: what job it does, from when to when) and *placed* at a
location (a Placement: where it is). Work orders record what was done as
actions, and the fitments follow from the actions: nobody edits a fitment
directly.

Each fitment is one row of life data: it ended in a failure, it was removed
on purpose (a suspension), or it is still fitted (right-censored today).

Dates are whole days, as ISO text (``"2026-10-13"``).
"""

from __future__ import annotations

from datetime import date, timedelta

from dateutil.relativedelta import relativedelta

from backend.maintenance.store import GraphStore, new_id
from backend.services.rcm import _norm_unit

# Outcomes that schedule a task; the others (run to failure, redesign,
# accept) give a failure mode with no task.
SCHEDULED_OUTCOMES = {
    "fixed_interval": "Replace or restore",
    "failure_finding": "Failure-finding check",
    "on_condition": "Condition check",
}
CALENDAR_UNITS = ("days", "weeks", "months", "years")
ACTION_KINDS = ("replace", "repair", "inspect", "other")
FINDINGS = ("ok", "degraded", "found_failed")
WORK_ORDER_TYPES = ("preventive", "corrective", "inspection", "other")
OPEN_STATUSES = ("open", "planned", "in_progress", "waiting")


class NotFound(KeyError):
    """No such node in this organisation."""


class Invalid(ValueError):
    """The request can't be done as asked (HTTP 422)."""


# ---- helpers -------------------------------------------------------------------

def _day(value, what: str = "date") -> str:
    """A date as ISO text; today when not given."""
    if value in (None, ""):
        return date.today().isoformat()
    try:
        return date.fromisoformat(str(value)[:10]).isoformat()
    except ValueError:
        raise Invalid(f"The {what} must be a date like 2026-10-13; got {value!r}.")


def _text(value, what: str, required: bool = False) -> str:
    text = str(value or "").strip()
    if required and not text:
        raise Invalid(f"The {what} is required.")
    return text


def add_interval(day: str, interval: float, unit: str) -> str | None:
    """``day`` plus ``interval`` calendar units, or None for a unit of use
    (hours, cycles, km), which needs a meter to schedule."""
    unit = _norm_unit(unit) or "days"
    start = date.fromisoformat(day)
    if unit == "days":
        return (start + timedelta(days=round(interval))).isoformat()
    if unit == "weeks":
        return (start + timedelta(days=round(interval * 7))).isoformat()
    if unit in ("months", "years"):
        months = interval * (12 if unit == "years" else 1)
        if float(months).is_integer():
            return (start + relativedelta(months=int(months))).isoformat()
        return (start + timedelta(days=round(months * 30.4375))).isoformat()
    return None


# ---- projectors: event payload -> graph ------------------------------------------
# Projectors read only the payload (never the clock), so replaying the log
# gives the same graph.

def _position_created(s: GraphStore, org: str, p: dict) -> None:
    s.put_node(org, p["id"], "Position", {
        "name": p["name"], "tag": p.get("tag", ""), "position_class": p.get("position_class", ""),
        "description": p.get("description", ""), "created": p["on"],
    })
    if p.get("parent_id"):
        s.put_edge(org, "PART_OF", p["id"], p["parent_id"])


def _position_updated(s: GraphStore, org: str, p: dict) -> None:
    changes = {k: v for k, v in p["changes"].items() if k != "parent_id"}
    if changes:
        s.patch_node(org, p["id"], changes)
    if "parent_id" in p["changes"]:
        for parent in s.out(org, p["id"], "PART_OF"):
            s.delete_edge(org, "PART_OF", p["id"], parent["id"])
        if p["changes"]["parent_id"]:
            s.put_edge(org, "PART_OF", p["id"], p["changes"]["parent_id"])


def _location_created(s: GraphStore, org: str, p: dict) -> None:
    s.put_node(org, p["id"], "Location", {"name": p["name"], "description": p.get("description", "")})
    if p.get("parent_id"):
        s.put_edge(org, "PART_OF", p["id"], p["parent_id"])


def _item_created(s: GraphStore, org: str, p: dict) -> None:
    s.put_node(org, p["id"], "Item", {
        "name": p["name"], "serial": p.get("serial", ""), "part_number": p.get("part_number", ""),
        "manufacturer": p.get("manufacturer", ""), "model": p.get("model", ""),
        "nameplate": p.get("nameplate") or {}, "notes": p.get("notes", ""), "created": p["on"],
    })


def _patch(s: GraphStore, org: str, p: dict) -> None:
    """item.updated, task.updated, work_order.updated, location.updated: plain field changes."""
    changes = {k: v for k, v in p["changes"].items() if k != "parent_id"}
    if changes:
        s.patch_node(org, p["id"], changes)
    if "parent_id" in p["changes"]:
        for parent in s.out(org, p["id"], "PART_OF"):
            s.delete_edge(org, "PART_OF", p["id"], parent["id"])
        if p["changes"]["parent_id"]:
            s.put_edge(org, "PART_OF", p["id"], p["changes"]["parent_id"])


def _flag(field: str):
    def project(s: GraphStore, org: str, p: dict) -> None:
        s.patch_node(org, p["id"], {field: True, f"{field}_on": p.get("on"), f"{field}_reason": p.get("reason", "")})
    return project


def _fitment_corrected(s: GraphStore, org: str, p: dict) -> None:
    s.patch_node(org, p["id"], {k: p[k] for k in ("from", "to") if k in p})


def _work_order_cancelled(s: GraphStore, org: str, p: dict) -> None:
    s.patch_node(org, p["id"], {"status": "cancelled", "closed": p["on"], "notes": p.get("reason", "")})


def _item_placed(s: GraphStore, org: str, p: dict) -> None:
    for held in s.out(org, p["item_id"], "IN"):
        if held["label"] == "Placement" and held.get("to") is None:
            s.patch_node(org, held["id"], {"to": p["on"]})
    s.put_node(org, p["placement_id"], "Placement", {"from": p["on"], "to": None})
    s.put_edge(org, "IN", p["item_id"], p["placement_id"])
    s.put_edge(org, "AT", p["placement_id"], p["location_id"])


def _item_fitted(s: GraphStore, org: str, p: dict) -> None:
    s.put_node(org, p["fitment_id"], "Fitment", {"from": p["on"], "to": None, "end_reason": None,
                                                 "failure_mode_id": None})
    s.put_edge(org, "IN", p["item_id"], p["fitment_id"])
    s.put_edge(org, "AT", p["fitment_id"], p["position_id"])
    # A new item is a renewal: the position's tasks count from the day it went in.
    for task in s.inn(org, p["position_id"], "ON"):
        if task["label"] == "Task":
            _renew_task(s, org, task, p["on"])


def _item_removed(s: GraphStore, org: str, p: dict) -> None:
    s.patch_node(org, p["fitment_id"], {"to": p["on"], "end_reason": p["reason"],
                                        "failure_mode_id": p.get("failure_mode_id")})


def _failure_mode_added(s: GraphStore, org: str, p: dict) -> None:
    s.put_node(org, p["id"], "FailureMode", {
        "text": p["text"], "function": p.get("function", ""), "failure": p.get("failure", ""),
        "consequence": p.get("consequence"), "outcome": p.get("outcome"),
        "rcm_mode_id": p.get("rcm_mode_id"), "study_id": p.get("study_id"),
    })
    s.put_edge(org, "CAN_FAIL_AS", p["position_id"], p["id"])


def _task_added(s: GraphStore, org: str, p: dict) -> None:
    s.put_node(org, p["id"], "Task", {
        "name": p["name"], "outcome": p.get("outcome"), "interval": p["interval"], "unit": p["unit"],
        "start": p["start"], "last_done": None, "rcm_mode_id": p.get("rcm_mode_id"),
        "study_id": p.get("study_id"),
    })
    s.put_edge(org, "ON", p["id"], p["position_id"])
    if p.get("failure_mode_id"):
        s.put_edge(org, "MITIGATES", p["id"], p["failure_mode_id"])


def _task_updated(s: GraphStore, org: str, p: dict) -> None:
    s.patch_node(org, p["id"], p["changes"])


def _work_order_opened(s: GraphStore, org: str, p: dict) -> None:
    task = s.node(org, p["task_id"]) if p.get("task_id") else None
    s.put_node(org, p["id"], "WorkOrder", {
        "number": p["number"], "title": p["title"], "type": p["type"], "status": "open",
        "opened": p["on"], "due": p.get("due"), "closed": None, "notes": p.get("notes", ""),
        # A task's instructions and checklist travel with the work it raises.
        "instructions": (task or {}).get("instructions", ""),
        "checklist": [{"text": t, "done": False} for t in (task or {}).get("checklist") or []],
        "status_history": [{"status": "open", "on": p["on"]}],
    })
    s.put_edge(org, "ON", p["id"], p["position_id"])
    if p.get("task_id"):
        s.put_edge(org, "FOR", p["id"], p["task_id"])
    if p.get("alarm_point_id"):
        s.put_edge(org, "ALARM_FOR", p["id"], p["alarm_point_id"])


def _condition_point_added(s: GraphStore, org: str, p: dict) -> None:
    s.put_node(org, p["id"], "ConditionPoint", {k: p.get(k) for k in (
        "name", "unit", "alarm_above", "alarm_below", "source", "tag")} | {"created": p["on"]})
    s.put_edge(org, "ON", p["id"], p["position_id"])


def _condition_read(s: GraphStore, org: str, p: dict) -> None:
    s.put_node(org, p["id"], "ConditionReading", {"on": p["on"], "value": p["value"], "note": p.get("note", "")})
    s.put_edge(org, "OF", p["id"], p["point_id"])


def _work_order_status(s: GraphStore, org: str, p: dict) -> None:
    wo = s.node(org, p["id"])
    history = list(wo.get("status_history") or []) + [{"status": p["status"], "on": p["on"], "note": p.get("note", "")}]
    s.patch_node(org, p["id"], {"status": p["status"], "status_history": history})


def _work_order_entry(label: str):
    def project(s: GraphStore, org: str, p: dict) -> None:
        s.put_node(org, p["id"], label, {k: v for k, v in p.items() if k not in ("id", "work_order_id")}
                   | {"removed": False})
        s.put_edge(org, "OF", p["id"], p["work_order_id"])
    return project


def _work_order_check(s: GraphStore, org: str, p: dict) -> None:
    wo = s.node(org, p["id"])
    checklist = [dict(c) for c in wo.get("checklist") or []]
    if 0 <= p["index"] < len(checklist):
        checklist[p["index"]]["done"] = p["done"]
    s.patch_node(org, p["id"], {"checklist": checklist})


def _action_recorded(s: GraphStore, org: str, p: dict) -> None:
    s.put_node(org, p["id"], "Action", {
        "kind": p["kind"], "finding": p.get("finding"), "notes": p.get("notes", ""), "on": p["on"],
    })
    s.put_edge(org, "INCLUDES", p["work_order_id"], p["id"])
    if p.get("failure_mode_id"):
        s.put_edge(org, "FOUND", p["id"], p["failure_mode_id"])
    if p.get("ends"):
        s.put_edge(org, "ENDS", p["id"], p["ends"])
    if p.get("starts"):
        s.put_edge(org, "STARTS", p["id"], p["starts"])
    if p.get("on_fitment"):
        s.put_edge(org, "ON", p["id"], p["on_fitment"])


# ---- meters and readings (usage: run hours, cycles, km) ---------------------------

USAGE_UNITS = ("hours", "cycles", "km", "miles", "starts", "tonnes", "litres")


def _is_calendar(unit: str) -> bool:
    return (_norm_unit(unit) or "days") in CALENDAR_UNITS


def _readings(s: GraphStore, org: str, meter_id: str) -> list[dict]:
    rows = [r for r in s.inn(org, meter_id, "OF") if r["label"] == "Reading" and not r.get("voided")]
    return sorted(rows, key=lambda r: (r["on"], r["value"]))


def _reading_at(readings: list[dict], day: str) -> float | None:
    """The meter on ``day``: interpolated between the readings either side, the
    last one before it, or None if every reading is later."""
    before = [r for r in readings if r["on"] <= day]
    after = [r for r in readings if r["on"] > day]
    if not before:
        return None
    a = before[-1]
    if not after:
        return a["value"]
    b = after[0]
    span = (date.fromisoformat(b["on"]) - date.fromisoformat(a["on"])).days
    frac = (date.fromisoformat(day) - date.fromisoformat(a["on"])).days / span if span else 0
    return a["value"] + frac * (b["value"] - a["value"])


def _rate(readings: list[dict]) -> float | None:
    """Units per day over the last year of readings (None with fewer than two)."""
    if len(readings) < 2:
        return None
    last = readings[-1]
    cutoff = (date.fromisoformat(last["on"]) - timedelta(days=365)).isoformat()
    window = [r for r in readings if r["on"] >= cutoff]
    first = window[0] if len(window) > 1 else readings[-2]
    days = (date.fromisoformat(last["on"]) - date.fromisoformat(first["on"])).days
    return (last["value"] - first["value"]) / days if days > 0 else None


def _task_meter(s: GraphStore, org: str, task: dict) -> dict | None:
    if task.get("meter_id"):
        return s.node(org, task["meter_id"])
    for unit in (task.get("unit"), task.get("also_unit")):
        if unit and not _is_calendar(unit):
            position = s.out(org, task["id"], "ON")
            meters = [mt for mt in (s.inn(org, position[0]["id"], "ON") if position else [])
                      if mt["label"] == "Meter" and _norm_unit(mt["unit"]) == _norm_unit(unit)]
            if meters:
                return sorted(meters, key=lambda mt: mt["name"].lower())[0]
    return None


def _renew_task(s: GraphStore, org: str, task: dict, day: str) -> None:
    """The task was done (or its item renewed) on ``day``: record the date, and the
    meter reading then if it goes by use."""
    if task.get("last_done") and task["last_done"] >= day:
        return
    changes = {"last_done": day}
    meter = _task_meter(s, org, task)
    if meter:
        changes["last_done_reading"] = _reading_at(_readings(s, org, meter["id"]), day)
    s.patch_node(org, task["id"], changes)


def _meter_added(s: GraphStore, org: str, p: dict) -> None:
    s.put_node(org, p["id"], "Meter", {"name": p["name"], "unit": p["unit"], "created": p["on"]})
    s.put_edge(org, "ON", p["id"], p["position_id"])


def _meter_read(s: GraphStore, org: str, p: dict) -> None:
    s.put_node(org, p["id"], "Reading", {"on": p["on"], "value": p["value"], "note": p.get("note", "")})
    s.put_edge(org, "OF", p["id"], p["meter_id"])


def _work_order_closed(s: GraphStore, org: str, p: dict) -> None:
    wo = s.node(org, p["id"])
    # Work recorded after the fact: it was opened no later than it was done.
    opened = min(wo["opened"], p["on"])
    s.patch_node(org, p["id"], {"status": "closed", "closed": p["on"], "opened": opened,
                                "notes": p.get("notes", "")})
    for task in s.out(org, p["id"], "FOR"):
        _renew_task(s, org, task, p["on"])


def _photo_added(s: GraphStore, org: str, p: dict) -> None:
    s.put_node(org, p["id"], "Photo", {
        "caption": p.get("caption", ""), "taken_on": p.get("taken_on"), "uploaded_on": p["on"],
        "width": p.get("width"), "height": p.get("height"), "via": p.get("via", "app"), "removed": False,
    })
    s.put_edge(org, "OF", p["id"], p["target_id"])


def _photo_removed(s: GraphStore, org: str, p: dict) -> None:
    s.patch_node(org, p["id"], {"removed": True})


def _coordinates_set(s: GraphStore, org: str, p: dict) -> None:
    s.patch_node(org, p["node_id"], {"coordinates": {"lat": p["lat"], "lon": p["lon"],
                                                     "source": p.get("source", "manual"), "on": p["on"]}})


def class_id(name: str) -> str:
    """A position class's node id: one per class name (case and spacing aside)."""
    import hashlib

    return "class-" + hashlib.sha1(" ".join(name.lower().split()).encode()).hexdigest()[:16]


def _class_upsert(s: GraphStore, org: str, p: dict, changes: dict) -> None:
    if s.node(org, p["id"]) is None:
        s.put_node(org, p["id"], "PositionClass", {"name": p["name"]})
    s.patch_node(org, p["id"], changes)


def _class_costs_set(s: GraphStore, org: str, p: dict) -> None:
    _class_upsert(s, org, p, {k: p.get(k) for k in ("planned_cost", "failure_cost", "availability_target")})


def _class_model_fitted(s: GraphStore, org: str, p: dict) -> None:
    _class_upsert(s, org, p, {"model": {k: p.get(k) for k in (
        "model_id", "distribution", "params", "extras", "unit", "fitted_on", "failures", "suspensions")}})


def _proposal_made(s: GraphStore, org: str, p: dict) -> None:
    for old in s.inn(org, p["task_id"], "ABOUT"):
        if old["label"] == "Proposal" and old.get("status") == "pending":
            s.patch_node(org, old["id"], {"status": "superseded"})
    s.put_node(org, p["id"], "Proposal", {k: p.get(k) for k in (
        "kind", "current", "proposed", "reason", "made_on", "class_name")} | {"status": "pending"})
    s.put_edge(org, "ABOUT", p["id"], p["task_id"])


def _proposal_decided(s: GraphStore, org: str, p: dict) -> None:
    s.patch_node(org, p["id"], {"status": p["decision"], "decided_on": p["on"], "note": p.get("note", "")})


def _interface_added(s: GraphStore, org: str, p: dict) -> None:
    s.put_node(org, p["id"], "Interface", {k: p.get(k, "") for k in ("name", "kind", "medium", "rating")}
               | {"created": p["on"]})
    s.put_edge(org, "FROM", p["id"], p["from_id"])
    s.put_edge(org, "TO", p["id"], p["to_id"])
    if p.get("realised_by"):
        s.put_edge(org, "REALISED_BY", p["id"], p["realised_by"])


def _group_created(s: GraphStore, org: str, p: dict) -> None:
    s.put_node(org, p["id"], "RedundancyGroup", {k: p.get(k) for k in ("name", "k", "mode", "standby")}
               | {"duty": None, "created": p["on"]})


def _group_member(add: bool):
    def project(s: GraphStore, org: str, p: dict) -> None:
        if add:
            s.put_edge(org, "IN_GROUP", p["position_id"], p["group_id"])
        else:
            s.delete_edge(org, "IN_GROUP", p["position_id"], p["group_id"])
    return project


def _duty_changed(s: GraphStore, org: str, p: dict) -> None:
    s.patch_node(org, p["group_id"], {"duty": p["position_id"], "duty_since": p["on"]})


PROJECTORS = {
    "position.created": _position_created,
    "position.updated": _position_updated,
    "location.created": _location_created,
    "item.created": _item_created,
    "item.placed": _item_placed,
    "item.fitted": _item_fitted,
    "item.removed": _item_removed,
    "failure_mode.added": _failure_mode_added,
    "task.added": _task_added,
    "task.updated": _task_updated,
    "work_order.opened": _work_order_opened,
    "action.recorded": _action_recorded,
    "work_order.closed": _work_order_closed,
    "item.updated": _patch,
    "task.retired": _flag("retired"),
    "position.retired": _flag("retired"),
    "fitment.voided": _flag("voided"),
    "fitment.corrected": _fitment_corrected,
    "work_order.updated": _patch,
    "work_order.cancelled": _work_order_cancelled,
    "location.updated": _patch,
    "meter.added": _meter_added,
    "meter.read": _meter_read,
    "reading.voided": _flag("voided"),
    "class.costs_set": _class_costs_set,
    "class.model_fitted": _class_model_fitted,
    "proposal.made": _proposal_made,
    "proposal.decided": _proposal_decided,
    "interface.added": _interface_added,
    "interface.removed": _flag("retired"),
    "group.created": _group_created,
    "group.updated": _patch,
    "group.member_added": _group_member(True),
    "group.member_removed": _group_member(False),
    "group.retired": _flag("retired"),
    "duty.changed": _duty_changed,
    "position.rbd_linked": _patch,
    "condition_point.added": _condition_point_added,
    "condition_point.updated": _patch,
    "condition.read": _condition_read,
    "work_order.status": _work_order_status,
    "work_order.labour": _work_order_entry("Labour"),
    "work_order.part_used": _work_order_entry("PartUse"),
    "work_order.cost": _work_order_entry("Cost"),
    "work_order.entry_removed": _flag("removed"),
    "work_order.check": _work_order_check,
    "photo.added": _photo_added,
    "photo.removed": _photo_removed,
    "coordinates.set": _coordinates_set,
}


# ---- the domain ------------------------------------------------------------------

class Maintenance:
    """One organisation's maintenance graph, acted on by one person."""

    def __init__(self, store: GraphStore, org: str, actor: str | None = None):
        self.s = store
        self.org = org
        self.actor = actor

    def _emit(self, type: str, payload: dict) -> None:
        self.s.apply(self.org, type, payload, self.actor)

    def _get(self, id: str, label: str) -> dict:
        node = self.s.node(self.org, id, label)
        if node is None:
            raise NotFound(f"{label} {id}")
        return node

    # ---- positions and locations -------------------------------------------------

    def create_position(self, name, tag="", parent_id=None, position_class="", description="") -> dict:
        name = _text(name, "position's name", required=True)
        if parent_id:
            self._parent_node(parent_id)
        pid = new_id()
        self._emit("position.created", {
            "id": pid, "name": name, "tag": _text(tag, "tag"), "parent_id": parent_id or None,
            "position_class": _text(position_class, "class"), "description": _text(description, "description"),
            "on": date.today().isoformat(),
        })
        return self._get(pid, "Position")

    def update_position(self, id: str, **changes) -> dict:
        self._get(id, "Position")
        allowed = {k: _text(v, k) for k, v in changes.items()
                   if k in ("name", "tag", "position_class", "description") and v is not None}
        if "name" in allowed and not allowed["name"]:
            raise Invalid("The position's name is required.")
        if "parent_id" in changes:
            parent = changes["parent_id"] or None
            if parent:
                self._parent_node(parent)
                if parent == id or id in self._ancestor_ids(parent):
                    raise Invalid("A position can't sit inside itself.")
            allowed["parent_id"] = parent
        if allowed:
            self._emit("position.updated", {"id": id, "changes": allowed})
        return self._get(id, "Position")

    def _parent_node(self, id: str) -> dict:
        """What a position can sit inside: another position, or an item (an item
        position: it moves with the item, like an engine's turbo positions)."""
        node = self.s.node(self.org, id)
        if node is None or node["label"] not in ("Position", "Item"):
            raise NotFound(id)
        if node.get("retired"):
            raise Invalid("That position has been retired.")
        return node

    def _parent(self, id: str) -> dict | None:
        parents = self.s.out(self.org, id, "PART_OF")
        return parents[0] if parents else None

    def _ancestor_ids(self, id: str) -> list[str]:
        out, seen = [], set()
        parent = self._parent(id)
        while parent and parent["id"] not in seen:
            seen.add(parent["id"])
            out.append(parent["id"])
            parent = self._parent(parent["id"])
        return out

    def copy_position(self, position_id: str, name, parent_id=None) -> dict:
        """Copy a position and everything inside it: the positions, their
        failure modes and their tasks (not items or work orders). For a
        second pump station like the first, or a template."""
        source = self._get(position_id, "Position")
        if parent_id:
            self._get(parent_id, "Position")
        today = date.today().isoformat()

        def copy(src: dict, new_name: str, parent: str | None) -> str:
            pid = new_id()
            self._emit("position.created", {
                "id": pid, "name": new_name, "tag": "", "parent_id": parent,
                "position_class": src.get("position_class", ""), "description": src.get("description", ""),
                "on": today,
            })
            mode_ids = {}
            for fm in self.s.out(self.org, src["id"], "CAN_FAIL_AS"):
                mode_ids[fm["id"]] = new_id()
                self._emit("failure_mode.added", {
                    "id": mode_ids[fm["id"]], "position_id": pid,
                    **{k: fm.get(k) for k in ("text", "function", "failure", "consequence", "outcome",
                                              "rcm_mode_id", "study_id")},
                })
            for task in self.s.inn(self.org, src["id"], "ON"):
                if task["label"] != "Task":
                    continue
                mitigates = self.s.out(self.org, task["id"], "MITIGATES")
                self._emit("task.added", {
                    "id": new_id(), "position_id": pid,
                    "failure_mode_id": mitigates and mode_ids.get(mitigates[0]["id"]),
                    "start": today,
                    **{k: task.get(k) for k in ("name", "outcome", "interval", "unit", "rcm_mode_id", "study_id")},
                })
            for child in sorted(self.s.inn(self.org, src["id"], "PART_OF"), key=lambda c: c["name"].lower()):
                copy(child, child["name"], pid)
            return pid

        new = copy(source, _text(name, "copy's name", required=True), parent_id or None)
        return self.position(new)

    def create_location(self, name, parent_id=None, description="") -> dict:
        name = _text(name, "location's name", required=True)
        if parent_id:
            self._get(parent_id, "Location")
        lid = new_id()
        self._emit("location.created", {"id": lid, "name": name, "parent_id": parent_id or None,
                                        "description": _text(description, "description")})
        return self._get(lid, "Location")

    # ---- items, fitments, placements --------------------------------------------

    def create_item(self, name, serial="", part_number="", manufacturer="", notes="", model="",
                    nameplate=None) -> dict:
        iid = new_id()
        self._emit("item.created", {
            "id": iid, "name": _text(name, "item's name", required=True), "serial": _text(serial, "serial"),
            "part_number": _text(part_number, "part number"), "manufacturer": _text(manufacturer, "manufacturer"),
            "model": _text(model, "model"), "notes": _text(notes, "notes"), "on": date.today().isoformat(),
        })
        if nameplate:
            self.update_item(iid, nameplate=nameplate)
        return self._get(iid, "Item")

    def _item_from(self, item_id=None, new_item=None) -> str:
        if item_id:
            self._get(item_id, "Item")
            if self._current_fitment_of_item(item_id):
                raise Invalid("That item is already fitted somewhere. Remove it there first.")
            return item_id
        if new_item:
            return self.create_item(**{k: new_item.get(k) for k in
                                       ("name", "serial", "part_number", "manufacturer", "notes", "model",
                                        "nameplate")})["id"]
        raise Invalid("Say which item: an existing one, or a new one with a name.")

    def place_item(self, item_id: str, location_id: str, on=None) -> dict:
        self._get(item_id, "Item")
        self._get(location_id, "Location")
        self._emit("item.placed", {"item_id": item_id, "location_id": location_id,
                                   "placement_id": new_id(), "on": _day(on)})
        return self.item(item_id)

    def _fitments_at(self, position_id: str) -> list[dict]:
        return [f for f in self.s.inn(self.org, position_id, "AT") if f["label"] == "Fitment" and not f.get("voided")]

    def _fitments_of(self, item_id: str) -> list[dict]:
        return [f for f in self.s.out(self.org, item_id, "IN") if f["label"] == "Fitment" and not f.get("voided")]

    def current_fitment(self, position_id: str) -> dict | None:
        return next((f for f in self._fitments_at(position_id) if f.get("to") is None), None)

    def _current_fitment_of_item(self, item_id: str) -> dict | None:
        return next((f for f in self._fitments_of(item_id) if f.get("to") is None), None)

    def fit(self, position_id: str, item_id=None, new_item=None, on=None) -> dict:
        """Fit an item to an empty position (a first install, or after a removal)."""
        self._get(position_id, "Position")
        if self.current_fitment(position_id):
            raise Invalid("Something is already fitted here. Replace it through a work order, "
                          "or remove it first.")
        iid = self._item_from(item_id, new_item)
        self._emit("item.fitted", {"fitment_id": new_id(), "item_id": iid,
                                   "position_id": position_id, "on": _day(on)})
        return self.position(position_id)

    def remove(self, position_id: str, on=None, reason="planned", failure_mode_id=None) -> dict:
        """Take the fitted item out, with no work order (a correction, or an item
        moved elsewhere)."""
        current = self.current_fitment(position_id)
        if current is None:
            raise Invalid("Nothing is fitted here.")
        day = _day(on)
        if day < current["from"]:
            raise Invalid("It can't come out before it went in.")
        if reason not in ("failure", "planned", "other"):
            raise Invalid("The reason is failure, planned or other.")
        if failure_mode_id:
            self._get(failure_mode_id, "FailureMode")
        self._emit("item.removed", {"fitment_id": current["id"], "on": day, "reason": reason,
                                    "failure_mode_id": failure_mode_id or None})
        return self.position(position_id)

    # ---- RCM -> failure modes and tasks ---------------------------------------------

    def apply_rcm(self, position_id: str, study) -> dict:
        """Bring an RCM study's failure modes and scheduled tasks onto a position.

        Applying again adds what's new and updates changed tasks; nothing is
        removed (work orders may already point at it)."""
        self._get(position_id, "Position")
        today = date.today().isoformat()
        modes = {m.get("rcm_mode_id"): m for m in self.s.out(self.org, position_id, "CAN_FAIL_AS")}
        tasks = {t.get("rcm_mode_id"): t for t in self.s.inn(self.org, position_id, "ON")
                 if t["label"] == "Task"}
        added_modes = added_tasks = updated_tasks = 0
        for fn in study.functions or []:
            for failure in fn.get("failures") or []:
                for mode in failure.get("modes") or []:
                    decision = mode.get("decision") or {}
                    fm = modes.get(mode["id"])
                    if fm is None:
                        fm_id = new_id()
                        self._emit("failure_mode.added", {
                            "id": fm_id, "position_id": position_id, "text": mode.get("text", ""),
                            "function": fn.get("text", ""), "failure": failure.get("text", ""),
                            "consequence": mode.get("consequence"), "outcome": decision.get("outcome"),
                            "rcm_mode_id": mode["id"], "study_id": study.id,
                        })
                        added_modes += 1
                    else:
                        fm_id = fm["id"]
                    outcome = decision.get("outcome")
                    if outcome not in SCHEDULED_OUTCOMES or not decision.get("interval"):
                        continue
                    name = decision.get("task") or f"{SCHEDULED_OUTCOMES[outcome]}: {mode.get('text', '')}"
                    unit = _norm_unit(decision.get("interval_unit")) or "days"
                    interval = float(decision["interval"])
                    existing = tasks.get(mode["id"])
                    if existing is None:
                        self._emit("task.added", {
                            "id": new_id(), "position_id": position_id, "failure_mode_id": fm_id,
                            "name": name, "outcome": outcome, "interval": interval, "unit": unit,
                            "start": today, "rcm_mode_id": mode["id"], "study_id": study.id,
                        })
                        added_tasks += 1
                    else:
                        changes = {k: v for k, v in (("name", name), ("interval", interval), ("unit", unit),
                                                     ("outcome", outcome)) if existing.get(k) != v}
                        if changes:
                            self._emit("task.updated", {"id": existing["id"], "changes": changes})
                            updated_tasks += 1
        return {"position_id": position_id, "failure_modes_added": added_modes,
                "tasks_added": added_tasks, "tasks_updated": updated_tasks}

    def position_from_rcm(self, study, parent_id=None) -> dict:
        """A new position named for the study's system, with its tasks."""
        name = (study.system or "").strip() or study.name
        position = self.create_position(name, parent_id=parent_id,
                                        description=f"From the RCM study “{study.name}”.")
        result = self.apply_rcm(position["id"], study)
        return {**result, "position": self.position(position["id"])}

    # ---- tasks and when they're due ------------------------------------------------

    def _tasks_on(self, position_id: str) -> list[dict]:
        return [t for t in self.s.inn(self.org, position_id, "ON") if t["label"] == "Task" and not t.get("retired")]

    def _due_by(self, task: dict, interval: float, unit: str) -> dict:
        """When one limit of a task falls due: on the calendar, or by use from its
        meter (projected from the meter's recent rate)."""
        base = task.get("last_done") or task["start"]
        if _is_calendar(unit):
            return {"limit": f"{interval:g} {unit}", "next_due": add_interval(base, interval, unit)}
        meter = _task_meter(self.s, self.org, task)
        if meter is None:
            return {"limit": f"{interval:g} {unit}", "next_due": None,
                    "note": f"needs a {unit} meter on the position"}
        readings = _readings(self.s, self.org, meter["id"])
        if not readings:
            return {"limit": f"{interval:g} {unit}", "next_due": None, "note": "needs meter readings"}
        start = task.get("last_done_reading")
        if start is None:
            start = _reading_at(readings, base)
        if start is None:
            start = readings[0]["value"]
        target = start + interval
        last, rate = readings[-1], _rate(readings)
        out = {"limit": f"{interval:g} {unit}", "due_at_reading": round(target, 2),
               "meter": {"id": meter["id"], "name": meter["name"], "unit": meter["unit"],
                         "reading": last["value"], "read_on": last["on"],
                         "rate_per_day": rate and round(rate, 3)}}
        if last["value"] >= target:
            crossed = next((r["on"] for r in readings if r["value"] >= target), last["on"])
            return {**out, "next_due": crossed}
        if not rate or rate <= 0:
            return {**out, "next_due": None, "note": "needs two readings to project a date"}
        days = (target - last["value"]) / rate
        return {**out, "next_due": (date.fromisoformat(last["on"]) + timedelta(days=round(days))).isoformat()}

    def _task_view(self, task: dict) -> dict:
        limits = [self._due_by(task, task["interval"], task["unit"])]
        if task.get("also_interval") and task.get("also_unit"):
            limits.append(self._due_by(task, task["also_interval"], task["also_unit"]))
        dues = [lim["next_due"] for lim in limits if lim["next_due"]]
        nxt = min(dues) if dues else None
        open_wo = next((w for w in self.s.inn(self.org, task["id"], "FOR") if w.get("status") in OPEN_STATUSES), None)
        return {
            "id": task["id"], "name": task["name"], "outcome": task.get("outcome"),
            "interval": task["interval"], "unit": task["unit"],
            "also_interval": task.get("also_interval"), "also_unit": task.get("also_unit"),
            "instructions": task.get("instructions", ""), "checklist": task.get("checklist") or [],
            "last_done": task.get("last_done"), "last_done_reading": task.get("last_done_reading"),
            "limits": limits, "next_due": nxt, "by_use": not _is_calendar(task["unit"]),
            "overdue": bool(nxt and nxt < date.today().isoformat()),
            "open_work_order": open_wo and {"id": open_wo["id"], "number": open_wo["number"]},
            "proposal": next(({"id": p["id"], "proposed": p.get("proposed"), "kind": p.get("kind")}
                              for p in self.s.inn(self.org, task["id"], "ABOUT")
                              if p["label"] == "Proposal" and p.get("status") == "pending"), None),
        }

    # ---- condition monitoring -----------------------------------------------------

    def add_condition_point(self, position_id: str, name, unit="", alarm_above=None, alarm_below=None,
                            source="manual", tag="") -> dict:
        """Something measured on a position to see its condition (vibration, temperature,
        pressure, wear), with alarm limits. A reading past a limit raises an inspection
        work order. source and tag say where readings come from (a historian tag) for later
        links; readings are entered here for now."""
        self._get(position_id, "Position")
        above, below = self._amount_or_none(alarm_above), self._amount_or_none(alarm_below)
        if above is not None and below is not None and below >= above:
            raise Invalid("The low alarm must be below the high alarm.")
        pid = new_id()
        self._emit("condition_point.added", {
            "id": pid, "position_id": position_id, "name": _text(name, "point's name", required=True),
            "unit": _text(unit, "unit")[:20], "alarm_above": above, "alarm_below": below,
            "source": _text(source, "source")[:60] or "manual", "tag": _text(tag, "tag")[:200],
            "on": date.today().isoformat()})
        return self.condition_point(pid)

    def update_condition_point(self, point_id: str, name=None, alarm_above=..., alarm_below=..., tag=None) -> dict:
        point = self._get(point_id, "ConditionPoint")
        changes = {}
        if name is not None:
            changes["name"] = _text(name, "point's name", required=True)
        if alarm_above is not ...:
            changes["alarm_above"] = self._amount_or_none(alarm_above)
        if alarm_below is not ...:
            changes["alarm_below"] = self._amount_or_none(alarm_below)
        if tag is not None:
            changes["tag"] = _text(tag, "tag")[:200]
        above = changes.get("alarm_above", point.get("alarm_above"))
        below = changes.get("alarm_below", point.get("alarm_below"))
        if above is not None and below is not None and below >= above:
            raise Invalid("The low alarm must be below the high alarm.")
        if changes:
            self._emit("condition_point.updated", {"id": point_id, "changes": changes})
        return self.condition_point(point_id)

    @staticmethod
    def _amount_or_none(value):
        if value in (None, ""):
            return None
        try:
            value = float(value)
        except (TypeError, ValueError):
            raise Invalid("An alarm limit must be a number.")
        if value != value:
            raise Invalid("An alarm limit must be a number.")
        return value

    def record_condition(self, point_id: str, value, on=None, note="") -> dict:
        """A condition reading. Past an alarm limit, an inspection work order is opened
        (one at a time per point)."""
        point = self._get(point_id, "ConditionPoint")
        try:
            value = float(value)
        except (TypeError, ValueError):
            raise Invalid("A reading is a number.")
        if value != value:
            raise Invalid("A reading is a number.")
        day = _day(on)
        if day > date.today().isoformat():
            raise Invalid("A reading can't be in the future.")
        self._emit("condition.read", {"id": new_id(), "point_id": point_id, "on": day, "value": value,
                                      "note": _text(note, "note")})
        view = self.condition_point(point_id)
        if view["status"] != "ok" and not view["alarm_work_order"]:
            position = self.s.out(self.org, point_id, "ON")[0]
            limit = point["alarm_above"] if view["status"] == "high" else point["alarm_below"]
            wid = new_id()
            self._emit("work_order.opened", {
                "id": wid, "number": self._next_number(), "type": "inspection", "position_id": position["id"],
                "title": f"{point['name']} {value:g}{(' ' + point['unit']) if point.get('unit') else ''}: "
                         f"{'above' if view['status'] == 'high' else 'below'} the {limit:g} alarm limit",
                "task_id": None, "due": day, "notes": "Raised by a condition reading.", "on": day,
                "alarm_point_id": point_id})
            view = self.condition_point(point_id)
        return view

    def condition_point(self, point_id: str) -> dict:
        point = self._get(point_id, "ConditionPoint")
        readings = sorted([r for r in self.s.inn(self.org, point_id, "OF") if r["label"] == "ConditionReading"],
                          key=lambda r: (r["on"], r["id"]))
        last = readings[-1] if readings else None
        above, below = point.get("alarm_above"), point.get("alarm_below")
        status = "ok"
        if last and above is not None and last["value"] >= above:
            status = "high"
        elif last and below is not None and last["value"] <= below:
            status = "low"
        trend = projection = None
        recent = readings[-6:]
        if len(recent) >= 3:
            xs = [(date.fromisoformat(r["on"]) - date.fromisoformat(recent[0]["on"])).days for r in recent]
            ys = [r["value"] for r in recent]
            n = len(xs)
            mx, my = sum(xs) / n, sum(ys) / n
            sxx = sum((x - mx) ** 2 for x in xs)
            if sxx > 0:
                slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
                trend = round(slope, 4)
                target = above if slope > 0 and above is not None else below if slope < 0 and below is not None else None
                if status == "ok" and target is not None:
                    days = (target - last["value"]) / slope
                    if 0 < days < 3650:
                        projection = (date.fromisoformat(last["on"]) + timedelta(days=round(days))).isoformat()
        alarm_wo = next((w for w in self.s.inn(self.org, point_id, "ALARM_FOR")
                         if w["label"] == "WorkOrder" and w["status"] in OPEN_STATUSES), None)
        position = self.s.out(self.org, point_id, "ON")
        return {
            "id": point_id, "name": point["name"], "unit": point.get("unit", ""), "source": point.get("source"),
            "tag": point.get("tag", ""), "alarm_above": above, "alarm_below": below,
            "position": position and {"id": position[0]["id"], "name": position[0]["name"]},
            "reading": last and last["value"], "read_on": last and last["on"], "status": status,
            "trend_per_day": trend, "projected_alarm": projection,
            "alarm_work_order": alarm_wo and {"id": alarm_wo["id"], "number": alarm_wo["number"]},
            "readings": [{"id": r["id"], "on": r["on"], "value": r["value"]} for r in reversed(readings[-50:])],
        }

    # ---- meters ------------------------------------------------------------------

    def add_meter(self, position_id: str, name, unit) -> dict:
        """A usage meter on a position: run hours, cycles, km. Tasks on the position
        that go by that unit use it."""
        self._get(position_id, "Position")
        unit = _norm_unit(unit)
        if not unit or _is_calendar(unit):
            raise Invalid(f"A meter counts use, e.g. {', '.join(USAGE_UNITS[:4])}.")
        mid = new_id()
        self._emit("meter.added", {"id": mid, "position_id": position_id,
                                   "name": _text(name, "meter's name") or f"{unit.capitalize()} meter",
                                   "unit": unit, "on": date.today().isoformat()})
        return self.meter(mid)

    def record_reading(self, meter_id: str, value, on=None, note="") -> dict:
        self._get(meter_id, "Meter")
        try:
            value = float(value)
        except (TypeError, ValueError):
            raise Invalid("A reading is a number.")
        if value < 0 or value != value:
            raise Invalid("A reading can't be negative.")
        day = _day(on)
        if day > date.today().isoformat():
            raise Invalid("A reading can't be in the future.")
        readings = _readings(self.s, self.org, meter_id)
        before = [r for r in readings if r["on"] <= day]
        after = [r for r in readings if r["on"] > day]
        if before and value < before[-1]["value"]:
            raise Invalid(f"It's lower than the reading of {before[-1]['value']:g} on {before[-1]['on']}. "
                          "If the meter was replaced, add a new meter.")
        if after and value > after[0]["value"]:
            raise Invalid(f"It's higher than the later reading of {after[0]['value']:g} on {after[0]['on']}.")
        self._emit("meter.read", {"id": new_id(), "meter_id": meter_id, "on": day, "value": value,
                                  "note": _text(note, "note")})
        return self.meter(meter_id)

    def void_reading(self, reading_id: str) -> None:
        if self._get(reading_id, "Reading").get("voided"):
            raise Invalid("That reading was already struck out.")
        self._emit("reading.voided", {"id": reading_id, "on": date.today().isoformat()})

    def meter(self, meter_id: str) -> dict:
        mt = self._get(meter_id, "Meter")
        readings = _readings(self.s, self.org, meter_id)
        rate = _rate(readings)
        position = self.s.out(self.org, meter_id, "ON")
        return {"id": meter_id, "name": mt["name"], "unit": mt["unit"],
                "position": position and {"id": position[0]["id"], "name": position[0]["name"]},
                "reading": readings[-1]["value"] if readings else None,
                "read_on": readings[-1]["on"] if readings else None,
                "rate_per_day": rate and round(rate, 3),
                "readings": [{"id": r["id"], "on": r["on"], "value": r["value"], "note": r.get("note", "")}
                             for r in reversed(readings[-50:])]}

    def set_last_done(self, task_id: str, on) -> dict:
        """Record when a task was last done (before it was tracked here), so
        its next due date counts from then."""
        self._get(task_id, "Task")
        day = _day(on)
        if day > date.today().isoformat():
            raise Invalid("Last done can't be in the future.")
        self._emit("task.updated", {"id": task_id, "changes": {"last_done": day}})
        return self._task_view(self._get(task_id, "Task"))

    def due_tasks(self, horizon_days: int = 30) -> list[dict]:
        until = (date.today() + timedelta(days=horizon_days)).isoformat()
        out = []
        for task in self.s.nodes(self.org, "Task"):
            if task.get("retired"):
                continue
            position = self.s.out(self.org, task["id"], "ON")
            if not position or position[0].get("retired"):
                continue
            view = self._task_view(task)
            if view["next_due"] and view["next_due"] <= until:
                position = self.s.out(self.org, task["id"], "ON")
                view["position"] = position and {"id": position[0]["id"], "name": position[0]["name"]}
                out.append(view)
        return sorted(out, key=lambda t: t["next_due"])

    # ---- work orders ------------------------------------------------------------------

    def _next_number(self) -> int:
        return 1 + max((w.get("number", 0) for w in self.s.nodes(self.org, "WorkOrder")), default=0)

    def open_work_order(self, position_id: str, title, type="corrective", task_id=None, due=None,
                        notes="") -> dict:
        self._get(position_id, "Position")
        if type not in WORK_ORDER_TYPES:
            raise Invalid(f"The type is one of {', '.join(WORK_ORDER_TYPES)}.")
        if task_id:
            self._get(task_id, "Task")
        wid = new_id()
        self._emit("work_order.opened", {
            "id": wid, "number": self._next_number(), "title": _text(title, "title", required=True),
            "type": type, "position_id": position_id, "task_id": task_id or None,
            "due": _day(due, "due date") if due else None, "notes": _text(notes, "notes"),
            "on": date.today().isoformat(),
        })
        return self.work_order(wid)

    def generate_work_orders(self, horizon_days: int = 30) -> list[dict]:
        """A work order for every task due within the horizon that has none open."""
        made = []
        for task in self.due_tasks(horizon_days):
            if task["open_work_order"] or not task.get("position"):
                continue
            made.append(self.open_work_order(task["position"]["id"], task["name"], type="preventive",
                                             task_id=task["id"], due=task["next_due"]))
        return made

    def close_work_order(self, work_order_id: str, actions=(), on=None, notes="", readings=()) -> dict:
        """Close a work order with what was done. Replacements end the fitted
        item's fitment and start the new one's."""
        wo = self._get(work_order_id, "WorkOrder")
        if wo["status"] not in OPEN_STATUSES:
            raise Invalid("This work order is already closed.")
        day = _day(on)
        position_id = self.s.out(self.org, work_order_id, "ON")[0]["id"]
        modes = {m["id"] for m in self.s.out(self.org, position_id, "CAN_FAIL_AS")}
        # Check everything before writing anything.
        plans = []
        for a in actions or []:
            kind = a.get("kind")
            if kind not in ACTION_KINDS:
                raise Invalid(f"An action is one of {', '.join(ACTION_KINDS)}.")
            fm = a.get("failure_mode_id") or None
            if fm and fm not in modes:
                raise Invalid("That failure mode isn't on this position.")
            finding = a.get("finding") or None
            if kind == "inspect" and finding not in FINDINGS:
                raise Invalid("An inspection's finding is ok, degraded or found_failed.")
            if kind == "replace" and not (a.get("item_id") or (a.get("new_item") or {}).get("name")) \
                    and not self.current_fitment(position_id):
                raise Invalid("A replacement needs the item that went in.")
            plans.append((kind, fm, finding, a))
        current = self.current_fitment(position_id)
        if current and day < current["from"]:
            raise Invalid("The work can't be done before the fitted item went in.")
        # Meter readings taken during the work go in first, so a task by use
        # records the reading it was done at.
        for r in readings or []:
            self.record_reading(r.get("meter_id"), r.get("value"), day, "read at the work order")

        for kind, fm, finding, a in plans:
            ends = starts = on_fitment = None
            if kind == "replace":
                current = self.current_fitment(position_id)
                if current:
                    self._emit("item.removed", {"fitment_id": current["id"], "on": day,
                                                "reason": "failure" if fm else "planned",
                                                "failure_mode_id": fm})
                    ends = current["id"]
                if a.get("item_id") or (a.get("new_item") or {}).get("name"):
                    iid = self._item_from(a.get("item_id"), a.get("new_item"))
                    starts = new_id()
                    self._emit("item.fitted", {"fitment_id": starts, "item_id": iid,
                                               "position_id": position_id, "on": day})
            else:
                fitted = self.current_fitment(position_id)
                on_fitment = fitted and fitted["id"]
            self._emit("action.recorded", {
                "id": new_id(), "work_order_id": work_order_id, "kind": kind, "finding": finding,
                "failure_mode_id": fm, "notes": _text(a.get("notes"), "notes"), "on": day,
                "ends": ends, "starts": starts, "on_fitment": on_fitment,
            })
        self._emit("work_order.closed", {"id": work_order_id, "on": day, "notes": _text(notes, "notes")})
        return self.work_order(work_order_id)

    # ---- corrections and edits ------------------------------------------------------
    # Mistakes are fixed with events too, so the history shows what changed.

    ITEM_FIELDS = ("name", "serial", "part_number", "manufacturer", "model", "notes")

    def update_item(self, item_id: str, nameplate: dict | None = None, **changes) -> dict:
        """Change an item's details: name, serial, part number, manufacturer, model,
        notes, and nameplate fields (ratings, year, anything on the plate: merged in;
        a field set to "" is removed)."""
        item = self._get(item_id, "Item")
        out = {k: _text(v, k) for k, v in changes.items() if k in self.ITEM_FIELDS and v is not None}
        if "name" in out and not out["name"]:
            raise Invalid("The item's name is required.")
        if nameplate:
            if not isinstance(nameplate, dict):
                raise Invalid("Nameplate fields are name: value pairs.")
            plate = dict(item.get("nameplate") or {})
            for k, v in nameplate.items():
                key = _text(k, "nameplate field")[:60]
                value = _text(v, "nameplate value")[:200]
                if key and value:
                    plate[key] = value
                elif key:
                    plate.pop(key, None)
            if len(plate) > 60:
                raise Invalid("At most 60 nameplate fields.")
            out["nameplate"] = plate
        if out:
            self._emit("item.updated", {"id": item_id, "changes": out})
        return self.item(item_id)

    def move_item(self, item_id: str, to_position_id: str, on=None) -> dict:
        """Move an item from wherever it's fitted to an empty position (a planned
        removal there, a fit here): a rotable going round."""
        self._get(item_id, "Item")
        self._get(to_position_id, "Position")
        if self.current_fitment(to_position_id):
            raise Invalid("Something is already fitted there. Move or remove it first.")
        day = _day(on)
        current = self._current_fitment_of_item(item_id)
        if current:
            if current["id"] and self.s.out(self.org, current["id"], "AT")[0]["id"] == to_position_id:
                raise Invalid("It's already fitted there.")
            if day < current["from"]:
                raise Invalid("It can't move before it was fitted where it is.")
            self._emit("item.removed", {"fitment_id": current["id"], "on": day, "reason": "planned",
                                        "failure_mode_id": None})
        self._emit("item.fitted", {"fitment_id": new_id(), "item_id": item_id,
                                   "position_id": to_position_id, "on": day})
        return self.item(item_id)

    def void_fitment(self, fitment_id: str, reason="") -> None:
        """Strike out a fitment recorded by mistake: it leaves the life data and the
        position's history (the event log keeps it)."""
        f = self._get(fitment_id, "Fitment")
        if f.get("voided"):
            raise Invalid("That fitment was already struck out.")
        self._emit("fitment.voided", {"id": fitment_id, "on": date.today().isoformat(),
                                      "reason": _text(reason, "reason")})

    def correct_fitment(self, fitment_id: str, start=None, end=None) -> dict:
        """Correct the dates an item went in (start) or came out (end)."""
        f = self._get(fitment_id, "Fitment")
        changes = {}
        if start:
            changes["from"] = _day(start, "start date")
        if end:
            if f.get("to") is None:
                raise Invalid("It's still fitted: remove it, or close a work order, to end it.")
            changes["to"] = _day(end, "end date")
        new_from, new_to = changes.get("from", f["from"]), changes.get("to", f.get("to"))
        if new_to and new_to < new_from:
            raise Invalid("It can't come out before it went in.")
        if changes:
            self._emit("fitment.corrected", {"id": fitment_id, **changes})
        return self._fitment_view(self._get(fitment_id, "Fitment"))

    def update_work_order(self, work_order_id: str, title=None, due=None, notes=None, type=None,
                          assignee=None, planned_for=None) -> dict:
        wo = self._get(work_order_id, "WorkOrder")
        if wo["status"] not in OPEN_STATUSES:
            raise Invalid("Only an open work order can be changed.")
        changes = {}
        if title is not None:
            changes["title"] = _text(title, "title", required=True)
        if due is not None:
            changes["due"] = _day(due, "due date") if due else None
        if notes is not None:
            changes["notes"] = _text(notes, "notes")
        if type is not None:
            if type not in WORK_ORDER_TYPES:
                raise Invalid(f"The type is one of {', '.join(WORK_ORDER_TYPES)}.")
            changes["type"] = type
        if assignee is not None:
            changes["assignee"] = _text(assignee, "assignee")[:120]
        if planned_for is not None:
            changes["planned_for"] = _day(planned_for, "planned date") if planned_for else None
        if changes:
            self._emit("work_order.updated", {"id": work_order_id, "changes": changes})
        return self.work_order(work_order_id)

    WORK_STATUSES = {"open": "Open", "planned": "Planned", "in_progress": "In progress",
                     "waiting": "Waiting (parts or access)"}

    def _open_wo(self, work_order_id: str) -> dict:
        wo = self._get(work_order_id, "WorkOrder")
        if wo["status"] not in OPEN_STATUSES:
            raise Invalid("This work order is already closed or cancelled.")
        return wo

    def set_work_status(self, work_order_id: str, status: str, note="") -> dict:
        """Move an open work order along: open, planned, in_progress, waiting. (Close it
        with close_work_order, or cancel it.)"""
        wo = self._open_wo(work_order_id)
        if status not in self.WORK_STATUSES:
            raise Invalid(f"The status is one of {', '.join(self.WORK_STATUSES)}.")
        if status != wo["status"]:
            self._emit("work_order.status", {"id": work_order_id, "status": status,
                                             "on": date.today().isoformat(), "note": _text(note, "note")})
        return self.work_order(work_order_id)

    @staticmethod
    def _amount(value, what: str, allow_none=True):
        if value in (None, ""):
            if allow_none:
                return None
            raise Invalid(f"The {what} is required.")
        try:
            value = float(value)
        except (TypeError, ValueError):
            raise Invalid(f"The {what} must be a number.")
        if value < 0 or value != value:
            raise Invalid(f"The {what} can't be negative.")
        return value

    def log_labour(self, work_order_id: str, hours, who="", rate=None, on=None, note="") -> dict:
        self._open_or_closed(work_order_id)
        hours = self._amount(hours, "hours", allow_none=False)
        if hours <= 0 or hours > 1000:
            raise Invalid("Hours must be more than 0 (and at most 1000).")
        self._emit("work_order.labour", {"id": new_id(), "work_order_id": work_order_id, "hours": hours,
                                         "who": _text(who, "who")[:120], "rate": self._amount(rate, "rate"),
                                         "on": _day(on), "note": _text(note, "note")})
        return self.work_order(work_order_id)

    def add_part_used(self, work_order_id: str, part, quantity=1, unit_cost=None, part_number="", note="") -> dict:
        self._open_or_closed(work_order_id)
        qty = self._amount(quantity, "quantity", allow_none=False)
        if qty <= 0:
            raise Invalid("The quantity must be more than 0.")
        self._emit("work_order.part_used", {"id": new_id(), "work_order_id": work_order_id,
                                             "part": _text(part, "part", required=True)[:200],
                                             "part_number": _text(part_number, "part number")[:120],
                                             "quantity": qty, "unit_cost": self._amount(unit_cost, "unit cost"),
                                             "note": _text(note, "note")})
        return self.work_order(work_order_id)

    def add_cost(self, work_order_id: str, description, amount) -> dict:
        self._open_or_closed(work_order_id)
        self._emit("work_order.cost", {"id": new_id(), "work_order_id": work_order_id,
                                       "description": _text(description, "description", required=True)[:200],
                                       "amount": self._amount(amount, "amount", allow_none=False)})
        return self.work_order(work_order_id)

    def remove_entry(self, entry_id: str) -> dict:
        node = self.s.node(self.org, entry_id)
        if node is None or node["label"] not in ("Labour", "PartUse", "Cost"):
            raise NotFound(entry_id)
        if node.get("removed"):
            raise Invalid("That entry was already removed.")
        wo = self.s.out(self.org, entry_id, "OF")[0]
        self._emit("work_order.entry_removed", {"id": entry_id, "on": date.today().isoformat()})
        return self.work_order(wo["id"])

    def check_item(self, work_order_id: str, index: int, done: bool = True) -> dict:
        wo = self._open_wo(work_order_id)
        if not 0 <= int(index) < len(wo.get("checklist") or []):
            raise Invalid("There's no checklist item with that number.")
        self._emit("work_order.check", {"id": work_order_id, "index": int(index), "done": bool(done)})
        return self.work_order(work_order_id)

    def _open_or_closed(self, work_order_id: str) -> dict:
        """Labour, parts and costs can be added after closing (timesheets come late),
        but not to a cancelled work order."""
        wo = self._get(work_order_id, "WorkOrder")
        if wo["status"] == "cancelled":
            raise Invalid("This work order was cancelled.")
        return wo

    def _wo_costs(self, work_order_id: str) -> dict:
        entries = [e for e in self.s.inn(self.org, work_order_id, "OF")
                   if e["label"] in ("Labour", "PartUse", "Cost") and not e.get("removed")]
        labour = [e for e in entries if e["label"] == "Labour"]
        parts = [e for e in entries if e["label"] == "PartUse"]
        other = [e for e in entries if e["label"] == "Cost"]
        labour_cost = sum((e.get("rate") or 0) * e["hours"] for e in labour)
        parts_cost = sum((e.get("unit_cost") or 0) * e["quantity"] for e in parts)
        other_cost = sum(e["amount"] for e in other)
        strip = lambda e: {k: v for k, v in e.items() if k not in ("label", "removed")}
        return {
            "labour": [strip(e) for e in sorted(labour, key=lambda e: e["on"])],
            "parts": [strip(e) for e in parts], "other_costs": [strip(e) for e in other],
            "totals": {"hours": round(sum(e["hours"] for e in labour), 2), "labour": round(labour_cost, 2),
                       "parts": round(parts_cost, 2), "other": round(other_cost, 2),
                       "total": round(labour_cost + parts_cost + other_cost, 2)},
        }

    def cancel_work_order(self, work_order_id: str, reason="") -> dict:
        wo = self._get(work_order_id, "WorkOrder")
        if wo["status"] not in OPEN_STATUSES:
            raise Invalid("Only an open work order can be cancelled.")
        self._emit("work_order.cancelled", {"id": work_order_id, "on": date.today().isoformat(),
                                            "reason": _text(reason, "reason")})
        return self.work_order(work_order_id)

    def update_task(self, task_id: str, name=None, interval=None, unit=None, also_interval=None,
                    also_unit=None, meter_id=None, instructions=None, checklist=None) -> dict:
        """Change a task. also_interval / also_unit add a second limit, whichever comes
        first (500 hours or 6 months); also_interval 0 removes it. meter_id picks the
        meter a task by use goes by (otherwise the position's meter in its unit)."""
        task = self._get(task_id, "Task")
        if task.get("retired"):
            raise Invalid("That task has been retired.")
        changes = {}
        if also_interval is not None:
            try:
                also_interval = float(also_interval)
            except (TypeError, ValueError):
                raise Invalid("The second limit must be a number.")
            if also_interval <= 0:
                changes["also_interval"], changes["also_unit"] = None, None
            else:
                changes["also_interval"] = also_interval
                changes["also_unit"] = _norm_unit(also_unit or task.get("also_unit")) or "months"
        if meter_id is not None:
            if meter_id:
                self._get(meter_id, "Meter")
            changes["meter_id"] = meter_id or None
        if instructions is not None:
            changes["instructions"] = _text(instructions, "instructions")[:4000]
        if checklist is not None:
            items = [_text(c, "checklist item")[:200] for c in (checklist or [])]
            items = [c for c in items if c]
            if len(items) > 50:
                raise Invalid("At most 50 checklist items.")
            changes["checklist"] = items
        if name is not None:
            changes["name"] = _text(name, "task's name", required=True)
        if interval is not None:
            try:
                interval = float(interval)
            except (TypeError, ValueError):
                raise Invalid("The interval must be a number.")
            if interval <= 0:
                raise Invalid("The interval must be positive.")
            changes["interval"] = interval
        if unit is not None:
            changes["unit"] = _norm_unit(unit) or "days"
        if changes:
            self._emit("task.updated", {"id": task_id, "changes": changes})
        return self._task_view(self._get(task_id, "Task"))

    def retire_task(self, task_id: str, reason="") -> None:
        task = self._get(task_id, "Task")
        if task.get("retired"):
            raise Invalid("That task was already retired.")
        self._emit("task.retired", {"id": task_id, "on": date.today().isoformat(), "reason": _text(reason, "reason")})

    def retire_position(self, position_id: str, reason="") -> None:
        """Take a position out of the plant (it stays in the history). Nothing may be
        fitted to it, and no position inside it still in use."""
        p = self._get(position_id, "Position")
        if p.get("retired"):
            raise Invalid("That position was already retired.")
        if self.current_fitment(position_id):
            raise Invalid("Something is still fitted. Remove or move it first.")
        if any(not c.get("retired") for c in self.s.inn(self.org, position_id, "PART_OF") if c["label"] == "Position"):
            raise Invalid("Positions inside it are still in use. Retire or move them first.")
        if any(w["label"] == "WorkOrder" and w["status"] in OPEN_STATUSES for w in self.s.inn(self.org, position_id, "ON")):
            raise Invalid("It has open work orders. Close or cancel them first.")
        self._emit("position.retired", {"id": position_id, "on": date.today().isoformat(),
                                        "reason": _text(reason, "reason")})

    def update_location(self, location_id: str, name=None, description=None, parent_id=...) -> dict:
        self._get(location_id, "Location")
        changes = {}
        if name is not None:
            changes["name"] = _text(name, "location's name", required=True)
        if description is not None:
            changes["description"] = _text(description, "description")
        if parent_id is not ...:
            if parent_id:
                self._get(parent_id, "Location")
                if parent_id == location_id or location_id in self._ancestor_ids(parent_id):
                    raise Invalid("A location can't sit inside itself.")
            changes["parent_id"] = parent_id or None
        if changes:
            self._emit("location.updated", {"id": location_id, "changes": changes})
        return self.location(location_id)

    # ---- items, locations and classes: reading ---------------------------------------

    def item(self, id: str) -> dict:
        """An item: its details and nameplate, where it's fitted and placed now, every
        position it has been fitted to, its own positions (an engine's turbos) and photos."""
        item = self._get(id, "Item")
        fitments = sorted(self._fitments_of(id), key=lambda f: f["from"], reverse=True)
        current = next((f for f in fitments if f.get("to") is None), None)
        placements = sorted([p for p in self.s.out(self.org, id, "IN") if p["label"] == "Placement"],
                            key=lambda p: p["from"], reverse=True)
        here = next((p for p in placements if p.get("to") is None), None)
        location = here and self.s.out(self.org, here["id"], "AT")
        own = [c for c in self.s.inn(self.org, id, "PART_OF") if c["label"] == "Position" and not c.get("retired")]
        return {
            **{k: item.get(k, "") for k in self.ITEM_FIELDS}, "id": id, "nameplate": item.get("nameplate") or {},
            "created": item.get("created"), "coordinates": item.get("coordinates"),
            "fitted_to": current and self._fitment_view(current)["position"],
            "location": location and {"id": location[0]["id"], "name": location[0]["name"]},
            "history": [self._fitment_view(f) for f in fitments],
            "placements": [{"from": p["from"], "to": p.get("to"),
                            "location": (lambda l: l and {"id": l[0]["id"], "name": l[0]["name"]})(
                                self.s.out(self.org, p["id"], "AT"))} for p in placements],
            "positions": [{"id": c["id"], "name": c["name"],
                           "item": (lambda f: f and self._fitment_view(f)["item"])(self.current_fitment(c["id"]))}
                          for c in sorted(own, key=lambda c: c["name"].lower())],
            "photos": self.photos_of(id),
        }

    def location(self, id: str) -> dict:
        loc = self._get(id, "Location")
        path = [self.s.node(self.org, a) for a in reversed(self._ancestor_ids(id))]
        here = []
        for placement in self.s.inn(self.org, id, "AT"):
            if placement["label"] == "Placement" and placement.get("to") is None:
                item = self.s.inn(self.org, placement["id"], "IN")
                if item:
                    here.append({**self._item_brief(item[0]), "since": placement["from"]})
        kids = [c for c in self.s.inn(self.org, id, "PART_OF") if c["label"] == "Location"]
        return {
            "id": id, "name": loc["name"], "description": loc.get("description", ""),
            "coordinates": loc.get("coordinates"),
            "path": [{"id": a["id"], "name": a["name"]} for a in path],
            "children": [{"id": c["id"], "name": c["name"]} for c in sorted(kids, key=lambda c: c["name"].lower())],
            "items": sorted(here, key=lambda i: i["name"].lower()),
            "photos": self.photos_of(id),
        }

    def location_tree(self) -> list[dict]:
        locs = self.s.nodes(self.org, "Location")
        children: dict[str | None, list] = {}
        for loc in locs:
            parent = self._parent(loc["id"])
            children.setdefault(parent["id"] if parent else None, []).append(loc)

        def build(loc):
            items = sum(1 for p in self.s.inn(self.org, loc["id"], "AT")
                        if p["label"] == "Placement" and p.get("to") is None)
            return {"id": loc["id"], "name": loc["name"], "items": items,
                    "children": [build(c) for c in sorted(children.get(loc["id"], []), key=lambda c: c["name"].lower())]}

        return [build(loc) for loc in sorted(children.get(None, []), key=lambda c: c["name"].lower())]

    def position_classes(self) -> list[dict]:
        """Each class of position ('Centrifugal pump'), with how many positions and
        how much life data it pools."""
        classes: dict[str, dict] = {}
        for p in self.s.nodes(self.org, "Position"):
            name = (p.get("position_class") or "").strip()
            if not name or p.get("retired"):
                continue
            entry = classes.setdefault(name, {"position_class": name, "positions": 0, "fitments": 0, "failures": 0})
            if "costs" not in entry:
                node = self.s.node(self.org, class_id(name)) or {}
                entry["costs"] = {k: node.get(k) for k in ("planned_cost", "failure_cost", "availability_target")}
                entry["model"] = node.get("model")
            entry["positions"] += 1
            for f in self._fitments_at(p["id"]):
                entry["fitments"] += 1
                entry["failures"] += f.get("end_reason") == "failure"
        return sorted(classes.values(), key=lambda c: c["position_class"].lower())

    # ---- closing the loop: costs, proposals -------------------------------------------

    def set_class_costs(self, position_class: str, planned_cost=None, failure_cost=None,
                        availability_target=None) -> dict:
        """What a planned replacement and a failure cost for this class of position,
        and the availability a hidden (protective) function must reach: what the
        proposed intervals are optimised against."""
        name = _text(position_class, "class", required=True)
        if not any((p.get("position_class") or "").strip().lower() == name.lower()
                   for p in self.s.nodes(self.org, "Position")):
            raise NotFound(name)
        node = self.s.node(self.org, class_id(name)) or {}
        out = {}
        for key, value in (("planned_cost", planned_cost), ("failure_cost", failure_cost),
                           ("availability_target", availability_target)):
            if value is None or value == "":
                out[key] = node.get(key)
                continue
            try:
                out[key] = float(value)
            except (TypeError, ValueError):
                raise Invalid(f"{key.replace('_', ' ').capitalize()} must be a number.")
        if out["planned_cost"] is not None and out["failure_cost"] is not None:
            if out["planned_cost"] < 0 or out["failure_cost"] <= out["planned_cost"]:
                raise Invalid("A failure must cost more than a planned replacement (and neither below 0).")
        if out["availability_target"] is not None and not (0 < out["availability_target"] < 1):
            raise Invalid("The availability target is between 0 and 1, e.g. 0.99.")
        self._emit("class.costs_set", {"id": class_id(name), "name": name, **out})
        return self.position_class(name)

    def position_class(self, position_class: str) -> dict:
        found = next((c for c in self.position_classes()
                      if c["position_class"].lower() == (position_class or "").strip().lower()), None)
        if found is None:
            raise NotFound(position_class)
        return {**found, "proposals": [p for p in self.proposals("pending")
                                       if (p.get("class_name") or "").lower() == found["position_class"].lower()]}

    def proposals(self, status: str | None = "pending") -> list[dict]:
        out = []
        for pr in self.s.nodes(self.org, "Proposal"):
            if status and pr.get("status") != status:
                continue
            task = self.s.out(self.org, pr["id"], "ABOUT")
            position = task and self.s.out(self.org, task[0]["id"], "ON")
            out.append({k: pr.get(k) for k in ("id", "kind", "current", "proposed", "reason", "status",
                                                "made_on", "decided_on", "class_name")} | {
                "task": task and {"id": task[0]["id"], "name": task[0]["name"]},
                "position": position and {"id": position[0]["id"], "name": position[0]["name"]},
            })
        return sorted(out, key=lambda p: p["made_on"] or "", reverse=True)

    def decide_proposal(self, proposal_id: str, accept: bool, note="") -> dict:
        pr = self._get(proposal_id, "Proposal")
        if pr.get("status") != "pending":
            raise Invalid("That proposal has already been decided or superseded.")
        task = self.s.out(self.org, proposal_id, "ABOUT")[0]
        if accept:
            if pr["kind"] == "interval":
                self.update_task(task["id"], interval=pr["proposed"]["interval"], unit=pr["proposed"]["unit"])
            elif pr["kind"] == "retire":
                self.retire_task(task["id"], "accepted proposal: " + (pr.get("reason") or "")[:200])
        self._emit("proposal.decided", {"id": proposal_id, "decision": "accepted" if accept else "rejected",
                                        "on": date.today().isoformat(), "note": _text(note, "note")})
        return next(p for p in self.proposals(None) if p["id"] == proposal_id)

    def explain_task(self, task_id: str) -> dict:
        """Why a task is what it is now: where it came from, every change to it and the
        proposals behind them, newest first."""
        task = self._get(task_id, "Task")
        mine = []
        for e in self.s.events(self.org, 5000):
            pl = e["payload"]
            if pl.get("id") == task_id or pl.get("task_id") == task_id:
                mine.append({"on": e["at"][:10], "type": e["type"], "by": e.get("actor"),
                             "detail": {k: v for k, v in pl.items() if k not in ("id", "task_id", "position_id")}})
        decided = [p for p in self.proposals(None) if p["task"] and p["task"]["id"] == task_id]
        return {"task": self._task_view(task), "history": mine, "proposals": decided}

    def class_life_data(self, position_class: str) -> dict:
        """Every fitment at every position of a class, pooled: the data for one life
        model of that kind of position."""
        wanted = (position_class or "").strip().lower()
        rows = []
        for p in self.s.nodes(self.org, "Position"):
            if (p.get("position_class") or "").strip().lower() == wanted and not p.get("retired"):
                rows += [{**r, "position": p["name"], "position_id": p["id"]} for r in self.life_data(p["id"])]
        if not rows and not any((p.get("position_class") or "").strip().lower() == wanted
                                for p in self.s.nodes(self.org, "Position")):
            raise NotFound(position_class)
        return {"position_class": position_class, "rows": sorted(rows, key=lambda r: r["from"]),
                "failures": sum(1 for r in rows if r["c"] == 0), "suspensions": sum(1 for r in rows if r["c"] == 1)}

    # ---- interfaces and redundancy ----------------------------------------------------

    INTERFACE_KINDS = ("flow", "electrical", "mechanical", "signal", "data", "other")

    def connect(self, from_id: str, to_id: str, kind="flow", medium="", name="", rating="",
                realised_by=None) -> dict:
        """A connection from one position to another: what flows or passes from A to B
        (water, 240 V, a 4-20 mA signal, torque through a coupling)."""
        a, b = self._get(from_id, "Position"), self._get(to_id, "Position")
        if from_id == to_id:
            raise Invalid("A position can't connect to itself.")
        if kind not in self.INTERFACE_KINDS:
            raise Invalid(f"The kind is one of {', '.join(self.INTERFACE_KINDS)}.")
        if realised_by:
            self._get(realised_by, "Position")
        for existing in self._interfaces(from_id, "FROM"):
            if existing["to"]["id"] == to_id and existing["kind"] == kind:
                raise Invalid(f"{a['name']} already connects to {b['name']} ({kind}).")
        iid = new_id()
        self._emit("interface.added", {"id": iid, "from_id": from_id, "to_id": to_id, "kind": kind,
                                       "medium": _text(medium, "medium"), "name": _text(name, "name"),
                                       "rating": _text(rating, "rating"), "realised_by": realised_by or None,
                                       "on": date.today().isoformat()})
        return self._interface_view(self._get(iid, "Interface"))

    def disconnect(self, interface_id: str) -> None:
        if self._get(interface_id, "Interface").get("retired"):
            raise Invalid("That connection was already removed.")
        self._emit("interface.removed", {"id": interface_id, "on": date.today().isoformat()})

    def _interface_view(self, i: dict) -> dict:
        src = self.s.out(self.org, i["id"], "FROM")[0]
        dst = self.s.out(self.org, i["id"], "TO")[0]
        via = self.s.out(self.org, i["id"], "REALISED_BY")
        return {"id": i["id"], "kind": i.get("kind"), "medium": i.get("medium", ""), "name": i.get("name", ""),
                "rating": i.get("rating", ""), "from": {"id": src["id"], "name": src["name"]},
                "to": {"id": dst["id"], "name": dst["name"]},
                "realised_by": via and {"id": via[0]["id"], "name": via[0]["name"]}}

    def _interfaces(self, position_id: str, end: str) -> list[dict]:
        """Live interfaces with ``position_id`` at their FROM end (outgoing) or TO end (incoming)."""
        return [self._interface_view(i) for i in self.s.inn(self.org, position_id, end)
                if i["label"] == "Interface" and not i.get("retired")]

    def connections(self, position_id: str) -> dict:
        self._get(position_id, "Position")
        return {"downstream": self._interfaces(position_id, "FROM"), "upstream": self._interfaces(position_id, "TO")}

    def create_group(self, name, member_ids, k=1, mode="active", standby="cold") -> dict:
        """A redundancy group: positions doing the same job where k of them are enough
        (two pumps, either will do: k = 1). mode 'standby': the others wait to take over
        (standby cold, warm or hot)."""
        members = [self._get(pid, "Position") for pid in dict.fromkeys(member_ids or [])]
        if len(members) < 2:
            raise Invalid("A redundancy group needs at least two positions.")
        try:
            k = int(k)
        except (TypeError, ValueError):
            raise Invalid("k (how many are needed) is a whole number.")
        if not 1 <= k < len(members):
            raise Invalid(f"k (how many are needed) is 1 to {len(members) - 1} for {len(members)} positions.")
        if mode not in ("active", "standby") or standby not in ("cold", "warm", "hot"):
            raise Invalid("mode is active or standby; standby is cold, warm or hot.")
        gid = new_id()
        self._emit("group.created", {"id": gid, "name": _text(name, "group's name") or
                                     " / ".join(m["name"] for m in members), "k": k, "mode": mode,
                                     "standby": standby, "on": date.today().isoformat()})
        for m in members:
            self._emit("group.member_added", {"group_id": gid, "position_id": m["id"]})
        return self.group(gid)

    def update_group(self, group_id: str, name=None, k=None, mode=None, standby=None, add=(), remove=()) -> dict:
        g = self._get(group_id, "RedundancyGroup")
        members = {m["id"] for m in self._members(group_id)}
        for pid in add or []:
            self._get(pid, "Position")
            if pid not in members:
                self._emit("group.member_added", {"group_id": group_id, "position_id": pid})
                members.add(pid)
        for pid in remove or []:
            if pid in members:
                self._emit("group.member_removed", {"group_id": group_id, "position_id": pid})
                members.discard(pid)
        changes = {}
        if name is not None:
            changes["name"] = _text(name, "group's name", required=True)
        if mode is not None:
            if mode not in ("active", "standby"):
                raise Invalid("mode is active or standby.")
            changes["mode"] = mode
        if standby is not None:
            if standby not in ("cold", "warm", "hot"):
                raise Invalid("standby is cold, warm or hot.")
            changes["standby"] = standby
        new_k = int(k) if k is not None else g["k"]
        if not 1 <= new_k < max(len(members), 2):
            raise Invalid(f"k (how many are needed) must be 1 to {len(members) - 1}.")
        if k is not None:
            changes["k"] = new_k
        if changes:
            self._emit("group.updated", {"id": group_id, "changes": changes})
        return self.group(group_id)

    def set_duty(self, group_id: str, position_id: str) -> dict:
        """Which member of a standby group is running now (the others wait)."""
        self._get(group_id, "RedundancyGroup")
        if position_id not in {m["id"] for m in self._members(group_id)}:
            raise Invalid("That position isn't in the group.")
        self._emit("duty.changed", {"group_id": group_id, "position_id": position_id,
                                    "on": date.today().isoformat()})
        return self.group(group_id)

    def retire_group(self, group_id: str) -> None:
        self._get(group_id, "RedundancyGroup")
        self._emit("group.retired", {"id": group_id, "on": date.today().isoformat()})

    def _members(self, group_id: str) -> list[dict]:
        return [m for m in self.s.inn(self.org, group_id, "IN_GROUP") if m["label"] == "Position"]

    def group(self, group_id: str) -> dict:
        g = self._get(group_id, "RedundancyGroup")
        members = sorted(self._members(group_id), key=lambda m: m["name"].lower())
        return {"id": group_id, "name": g["name"], "k": g["k"], "n": len(members), "mode": g["mode"],
                "standby": g["standby"], "duty": g.get("duty"), "retired": bool(g.get("retired")),
                "members": [{"id": m["id"], "name": m["name"]} for m in members]}

    def groups_of(self, position_id: str) -> list[dict]:
        return [self.group(g["id"]) for g in self.s.out(self.org, position_id, "IN_GROUP")
                if g["label"] == "RedundancyGroup" and not g.get("retired")]

    def impact(self, position_id: str) -> dict:
        """What depends on a position: everything downstream of it through its
        connections, and whether redundancy covers it (k of n still available)."""
        start = self._get(position_id, "Position")
        downstream, queue, seen = [], [position_id], {position_id}
        while queue:
            current = queue.pop(0)
            for i in self._interfaces(current, "FROM"):
                nxt = i["to"]["id"]
                if nxt not in seen:
                    seen.add(nxt)
                    queue.append(nxt)
                    downstream.append({"id": nxt, "name": i["to"]["name"], "via": i["kind"],
                                       "from": i["from"]["name"]})
        covered = []
        for g in self.groups_of(position_id):
            others = [m["name"] for m in g["members"] if m["id"] != position_id]
            if g["n"] - 1 >= g["k"]:
                covered.append(f"{g['name']}: {g['k']} of {g['n']} needed, so {', '.join(others)} can carry it")
        path = self._position_path(position_id)
        return {"position": {"id": position_id, "name": start["name"]}, "part_of": path,
                "downstream": downstream, "redundancy": covered,
                "summary": (f"If {start['name']} fails, " + (
                    "redundancy covers it: " + "; ".join(covered) if covered else
                    f"{len(downstream)} position{'s' if len(downstream) != 1 else ''} downstream lose their supply"
                    if downstream else "nothing downstream is connected to it") + ".")}

    # ---- photos and coordinates ------------------------------------------------------

    def photo_target(self, node_id: str) -> dict:
        """A node photos can show: a position, location, item or work order."""
        node = self.s.node(self.org, node_id)
        if node is None or node["label"] not in ("Position", "Location", "Item", "WorkOrder"):
            raise NotFound(node_id)
        return node

    def add_photo(self, photo_id: str, target_id: str, cleaned: dict, caption="", via="app") -> dict:
        """Record a photo whose bytes are already stored (see photos.py)."""
        self.photo_target(target_id)
        self._emit("photo.added", {
            "id": photo_id, "target_id": target_id, "caption": _text(caption, "caption"),
            "taken_on": cleaned.get("taken_on"), "width": cleaned.get("width"),
            "height": cleaned.get("height"), "via": via, "on": date.today().isoformat(),
        })
        return self.photo(photo_id)

    def photo(self, photo_id: str) -> dict:
        p = self._get(photo_id, "Photo")
        of = self.s.out(self.org, photo_id, "OF")
        return {k: p.get(k) for k in ("id", "caption", "taken_on", "uploaded_on", "width", "height", "removed")} | {
            "of": of and {"id": of[0]["id"], "kind": of[0]["label"],
                          "name": of[0].get("name") or of[0].get("title")},
        }

    def photos_of(self, node_id: str) -> list[dict]:
        found = [p for p in self.s.inn(self.org, node_id, "OF") if p["label"] == "Photo" and not p.get("removed")]
        found.sort(key=lambda p: (p.get("taken_on") or p["uploaded_on"], p["id"]))
        return [{k: p.get(k) for k in ("id", "caption", "taken_on", "uploaded_on", "width", "height")}
                for p in found]

    def remove_photo(self, photo_id: str) -> None:
        if self._get(photo_id, "Photo").get("removed"):
            raise Invalid("That photo was already removed.")
        self._emit("photo.removed", {"id": photo_id})

    def set_coordinates(self, node_id: str, lat, lon, source="manual") -> dict:
        """Where a position, item or location is, as latitude and longitude. For a
        work order, the coordinates go on its position."""
        node = self.photo_target(node_id)
        if node["label"] == "WorkOrder":
            node = self.s.out(self.org, node_id, "ON")[0]
        try:
            lat, lon = float(lat), float(lon)
        except (TypeError, ValueError):
            raise Invalid("Latitude and longitude must be numbers.")
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise Invalid("Latitude is -90 to 90 and longitude -180 to 180.")
        self._emit("coordinates.set", {"node_id": node["id"], "lat": round(lat, 6), "lon": round(lon, 6),
                                       "source": source, "on": date.today().isoformat()})
        node = self.s.node(self.org, node["id"])
        return {"id": node["id"], "kind": node["label"], "name": node.get("name") or node.get("title"),
                "coordinates": node["coordinates"]}

    # ---- reading -------------------------------------------------------------------

    def _item_brief(self, item: dict | None) -> dict | None:
        if not item:
            return None
        return {k: item.get(k) for k in ("id", "name", "serial", "part_number", "manufacturer", "model")}

    def _fitment_view(self, f: dict) -> dict:
        item = self.s.inn(self.org, f["id"], "IN")
        position = self.s.out(self.org, f["id"], "AT")
        fm = f.get("failure_mode_id") and self.s.node(self.org, f["failure_mode_id"])
        return {
            "id": f["id"], "from": f["from"], "to": f.get("to"), "end_reason": f.get("end_reason"),
            "failure_mode": fm and {"id": fm["id"], "text": fm["text"]},
            "item": self._item_brief(item[0] if item else None),
            "position": position and {"id": position[0]["id"], "name": position[0]["name"]},
        }

    def tree(self) -> list[dict]:
        positions = [p for p in self.s.nodes(self.org, "Position") if not p.get("retired")]
        children: dict[str | None, list] = {}
        for p in positions:
            parent = self._parent(p["id"])
            children.setdefault(parent["id"] if parent else None, []).append(p)

        def build(p):
            fitted = self.current_fitment(p["id"])
            item = fitted and self.s.inn(self.org, fitted["id"], "IN")
            tasks = [self._task_view(t) for t in self._tasks_on(p["id"])]
            dues = sorted(t["next_due"] for t in tasks if t["next_due"])
            wos = [w for w in self.s.inn(self.org, p["id"], "ON") if w["label"] == "WorkOrder"]
            return {
                "id": p["id"], "name": p["name"], "tag": p.get("tag", ""),
                "position_class": p.get("position_class", ""),
                "item": self._item_brief(item[0] if item else None),
                "tasks": len(tasks), "next_due": dues[0] if dues else None,
                "open_work_orders": sum(1 for w in wos if w["status"] in OPEN_STATUSES),
                "children": [build(c) for c in sorted(children.get(p["id"], []), key=lambda c: c["name"].lower())],
            }

        return [build(p) for p in sorted(children.get(None, []), key=lambda c: c["name"].lower())]

    def position(self, id: str) -> dict:
        p = self._get(id, "Position")
        path = self._position_path(id)
        fitments = self._fitments_at(id)
        fitments.sort(key=lambda f: (f["from"], f.get("to") or "9999"), reverse=True)
        current = next((f for f in fitments if f.get("to") is None), None)
        fitted = current and self._fitment_view(current)
        modes = self.s.out(self.org, id, "CAN_FAIL_AS")
        tasks = [self._task_view(t) for t in self._tasks_on(id)]
        wos = [w for w in self.s.inn(self.org, id, "ON") if w["label"] == "WorkOrder"]
        wos.sort(key=lambda w: w["number"], reverse=True)
        kids = sorted(self.s.inn(self.org, id, "PART_OF"), key=lambda c: c["name"].lower())
        return {
            "id": p["id"], "name": p["name"], "tag": p.get("tag", ""),
            "position_class": p.get("position_class", ""), "description": p.get("description", ""),
            "path": path, "retired": bool(p.get("retired")),
            "children": [{"id": c["id"], "name": c["name"]} for c in kids if not c.get("retired")],
            "fitted": fitted,
            "fitments": [self._fitment_view(f) for f in fitments],
            "failure_modes": [{k: m.get(k) for k in ("id", "text", "function", "failure", "consequence", "outcome")}
                              for m in sorted(modes, key=lambda m: m["text"].lower())],
            "tasks": sorted(tasks, key=lambda t: t["next_due"] or "9999"),
            "work_orders": [self._wo_brief(w) for w in wos],
            "life_data": self.life_data(id),
            "coordinates": p.get("coordinates"),
            "meters": [self.meter(mt["id"]) for mt in self.s.inn(self.org, id, "ON") if mt["label"] == "Meter"],
            "condition": [self.condition_point(c["id"]) for c in self.s.inn(self.org, id, "ON")
                          if c["label"] == "ConditionPoint"],
            "connections": self.connections(id),
            "groups": self.groups_of(id),
            "rbd_id": p.get("rbd_id"),
            "photos": self.photos_of(id),
            "item_photos": self.photos_of(fitted["item"]["id"]) if fitted and fitted["item"] else [],
        }

    def _position_path(self, id: str) -> list[dict]:
        """The way down to a position, top first. An item position's path runs
        through its item and on up from wherever the item is fitted (Truck 14 >
        Engine E123 > Turbo 1)."""
        out, seen, node = [], {id}, self._parent(id)
        while node and node["id"] not in seen:
            seen.add(node["id"])
            out.append({"id": node["id"], "name": node["name"], "kind": node["label"]})
            if node["label"] == "Item":
                fitment = self._current_fitment_of_item(node["id"])
                node = fitment and self.s.out(self.org, fitment["id"], "AT")[0]
                if node and node["id"] not in seen:
                    seen.add(node["id"])
                    out.append({"id": node["id"], "name": node["name"], "kind": node["label"]})
                    node = self._parent(node["id"])
                continue
            node = self._parent(node["id"])
        return list(reversed(out))

    def _wo_brief(self, w: dict) -> dict:
        position = self.s.out(self.org, w["id"], "ON")
        return {k: w.get(k) for k in ("id", "number", "title", "type", "status", "opened", "due", "closed",
                                      "assignee", "planned_for")} | {
            "position": position and {"id": position[0]["id"], "name": position[0]["name"]},
        }

    def work_orders(self, status: str | None = None) -> list[dict]:
        """Work orders, newest first. status 'open' means every not-yet-done status."""
        def keep(w):
            if not status:
                return True
            return w["status"] in OPEN_STATUSES if status == "open" else w["status"] == status
        wos = [w for w in self.s.nodes(self.org, "WorkOrder") if keep(w)]
        return [self._wo_brief(w) for w in sorted(wos, key=lambda w: w["number"], reverse=True)]

    def work_order(self, id: str) -> dict:
        w = self._get(id, "WorkOrder")
        position_id = self.s.out(self.org, id, "ON")[0]["id"]
        actions = []
        for a in sorted(self.s.out(self.org, id, "INCLUDES"), key=lambda a: a["on"]):
            fm = self.s.out(self.org, a["id"], "FOUND")
            ended = self.s.out(self.org, a["id"], "ENDS")
            started = self.s.out(self.org, a["id"], "STARTS")
            actions.append({
                "id": a["id"], "kind": a["kind"], "finding": a.get("finding"), "notes": a.get("notes", ""),
                "failure_mode": fm and {"id": fm[0]["id"], "text": fm[0]["text"]},
                "removed": ended and self._fitment_view(ended[0])["item"],
                "fitted": started and self._fitment_view(started[0])["item"],
            })
        task = self.s.out(self.org, id, "FOR")
        position = self.position(position_id)
        return {
            **self._wo_brief(w), "notes": w.get("notes", ""), "actions": actions,
            "task": task and {"id": task[0]["id"], "name": task[0]["name"]},
            "fitted": position["fitted"], "failure_modes": position["failure_modes"],
            "meters": [{k: mt[k] for k in ("id", "name", "unit", "reading")} for mt in position["meters"]],
            "photos": self.photos_of(id),
            "assignee": w.get("assignee", ""), "planned_for": w.get("planned_for"),
            "instructions": w.get("instructions", ""), "checklist": w.get("checklist") or [],
            "status_history": w.get("status_history") or [],
            **self._wo_costs(id),
        }

    def items(self) -> list[dict]:
        out = []
        for item in sorted(self.s.nodes(self.org, "Item"), key=lambda i: i["name"].lower()):
            fitment = self._current_fitment_of_item(item["id"])
            placement = next((p for p in self.s.out(self.org, item["id"], "IN")
                              if p["label"] == "Placement" and p.get("to") is None), None)
            location = placement and self.s.out(self.org, placement["id"], "AT")
            out.append({
                **self._item_brief(item),
                "fitted_to": fitment and self._fitment_view(fitment)["position"],
                "location": location and {"id": location[0]["id"], "name": location[0]["name"]},
            })
        return out

    def locations(self) -> list[dict]:
        out = []
        for loc in sorted(self.s.nodes(self.org, "Location"), key=lambda n: n["name"].lower()):
            parent = self._parent(loc["id"])
            out.append({"id": loc["id"], "name": loc["name"], "description": loc.get("description", ""),
                        "parent": parent and {"id": parent["id"], "name": parent["name"]}})
        return out

    def life_data(self, position_id: str) -> list[dict]:
        """One row per fitment at this position: its life in days, and whether it
        ended in a failure (``c`` = 0) or not (``c`` = 1: removed on purpose, or
        still fitted, censored today). Reliafy's censoring convention."""
        today = date.today().isoformat()
        rows = []
        for f in self._fitments_at(position_id):
            end = f.get("to") or today
            days = (date.fromisoformat(end) - date.fromisoformat(f["from"])).days
            view = self._fitment_view(f)
            rows.append({
                "fitment_id": f["id"],
                "item": view["item"] and view["item"]["name"], "from": f["from"], "to": f.get("to"),
                "x": days, "c": 0 if f.get("end_reason") == "failure" else 1,
                "failure_mode": view["failure_mode"] and view["failure_mode"]["text"],
                "status": "failed" if f.get("end_reason") == "failure"
                else "still fitted" if f.get("to") is None else "removed",
            })
        return sorted(rows, key=lambda r: r["from"])


def summary(m: Maintenance) -> dict:
    """Counts for the home page."""
    return {
        "positions": sum(1 for p in m.s.nodes(m.org, "Position") if not p.get("retired")),
        "locations": len(m.s.nodes(m.org, "Location")),
        "items": len(m.s.nodes(m.org, "Item")),
        "open_work_orders": sum(1 for w in m.s.nodes(m.org, "WorkOrder") if w["status"] in OPEN_STATUSES),
        "tasks": len(m.s.nodes(m.org, "Task")),
    }

