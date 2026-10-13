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
        "manufacturer": p.get("manufacturer", ""), "notes": p.get("notes", ""), "created": p["on"],
    })


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
        if task["label"] == "Task" and (not task.get("last_done") or task["last_done"] < p["on"]):
            s.patch_node(org, task["id"], {"last_done": p["on"]})


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
    s.put_node(org, p["id"], "WorkOrder", {
        "number": p["number"], "title": p["title"], "type": p["type"], "status": "open",
        "opened": p["on"], "due": p.get("due"), "closed": None, "notes": p.get("notes", ""),
    })
    s.put_edge(org, "ON", p["id"], p["position_id"])
    if p.get("task_id"):
        s.put_edge(org, "FOR", p["id"], p["task_id"])


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


def _work_order_closed(s: GraphStore, org: str, p: dict) -> None:
    wo = s.node(org, p["id"])
    # Work recorded after the fact: it was opened no later than it was done.
    opened = min(wo["opened"], p["on"])
    s.patch_node(org, p["id"], {"status": "closed", "closed": p["on"], "opened": opened,
                                "notes": p.get("notes", "")})
    for task in s.out(org, p["id"], "FOR"):
        if not task.get("last_done") or task["last_done"] < p["on"]:
            s.patch_node(org, task["id"], {"last_done": p["on"]})


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
            self._get(parent_id, "Position")
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
                self._get(parent, "Position")
                if parent == id or id in self._ancestor_ids(parent):
                    raise Invalid("A position can't sit inside itself.")
            allowed["parent_id"] = parent
        if allowed:
            self._emit("position.updated", {"id": id, "changes": allowed})
        return self._get(id, "Position")

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

    def create_location(self, name, parent_id=None, description="") -> dict:
        name = _text(name, "location's name", required=True)
        if parent_id:
            self._get(parent_id, "Location")
        lid = new_id()
        self._emit("location.created", {"id": lid, "name": name, "parent_id": parent_id or None,
                                        "description": _text(description, "description")})
        return self._get(lid, "Location")

    # ---- items, fitments, placements --------------------------------------------

    def create_item(self, name, serial="", part_number="", manufacturer="", notes="") -> dict:
        iid = new_id()
        self._emit("item.created", {
            "id": iid, "name": _text(name, "item's name", required=True), "serial": _text(serial, "serial"),
            "part_number": _text(part_number, "part number"), "manufacturer": _text(manufacturer, "manufacturer"),
            "notes": _text(notes, "notes"), "on": date.today().isoformat(),
        })
        return self._get(iid, "Item")

    def _item_from(self, item_id=None, new_item=None) -> str:
        if item_id:
            self._get(item_id, "Item")
            if self._current_fitment_of_item(item_id):
                raise Invalid("That item is already fitted somewhere. Remove it there first.")
            return item_id
        if new_item:
            return self.create_item(**{k: new_item.get(k) for k in
                                       ("name", "serial", "part_number", "manufacturer", "notes")})["id"]
        raise Invalid("Say which item: an existing one, or a new one with a name.")

    def place_item(self, item_id: str, location_id: str, on=None) -> dict:
        self._get(item_id, "Item")
        self._get(location_id, "Location")
        self._emit("item.placed", {"item_id": item_id, "location_id": location_id,
                                   "placement_id": new_id(), "on": _day(on)})
        return self.item(item_id)

    def current_fitment(self, position_id: str) -> dict | None:
        for f in self.s.inn(self.org, position_id, "AT"):
            if f["label"] == "Fitment" and f.get("to") is None:
                return f
        return None

    def _current_fitment_of_item(self, item_id: str) -> dict | None:
        for f in self.s.out(self.org, item_id, "IN"):
            if f["label"] == "Fitment" and f.get("to") is None:
                return f
        return None

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

    def _task_view(self, task: dict) -> dict:
        base = task.get("last_done") or task["start"]
        nxt = add_interval(base, task["interval"], task["unit"])
        open_wo = next((w for w in self.s.inn(self.org, task["id"], "FOR") if w.get("status") == "open"), None)
        return {
            "id": task["id"], "name": task["name"], "outcome": task.get("outcome"),
            "interval": task["interval"], "unit": task["unit"], "last_done": task.get("last_done"),
            "next_due": nxt, "by_use": nxt is None,
            "overdue": bool(nxt and nxt < date.today().isoformat()),
            "open_work_order": open_wo and {"id": open_wo["id"], "number": open_wo["number"]},
        }

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

    def close_work_order(self, work_order_id: str, actions=(), on=None, notes="") -> dict:
        """Close a work order with what was done. Replacements end the fitted
        item's fitment and start the new one's."""
        wo = self._get(work_order_id, "WorkOrder")
        if wo["status"] != "open":
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

    # ---- reading -------------------------------------------------------------------

    def _item_brief(self, item: dict | None) -> dict | None:
        if not item:
            return None
        return {k: item.get(k) for k in ("id", "name", "serial", "part_number", "manufacturer")}

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
        positions = self.s.nodes(self.org, "Position")
        children: dict[str | None, list] = {}
        for p in positions:
            parent = self._parent(p["id"])
            children.setdefault(parent["id"] if parent else None, []).append(p)

        def build(p):
            fitted = self.current_fitment(p["id"])
            item = fitted and self.s.inn(self.org, fitted["id"], "IN")
            tasks = [self._task_view(t) for t in self.s.inn(self.org, p["id"], "ON") if t["label"] == "Task"]
            dues = sorted(t["next_due"] for t in tasks if t["next_due"])
            wos = [w for w in self.s.inn(self.org, p["id"], "ON") if w["label"] == "WorkOrder"]
            return {
                "id": p["id"], "name": p["name"], "tag": p.get("tag", ""),
                "position_class": p.get("position_class", ""),
                "item": self._item_brief(item[0] if item else None),
                "tasks": len(tasks), "next_due": dues[0] if dues else None,
                "open_work_orders": sum(1 for w in wos if w["status"] == "open"),
                "children": [build(c) for c in sorted(children.get(p["id"], []), key=lambda c: c["name"].lower())],
            }

        return [build(p) for p in sorted(children.get(None, []), key=lambda c: c["name"].lower())]

    def position(self, id: str) -> dict:
        p = self._get(id, "Position")
        path = [self.s.node(self.org, a) for a in reversed(self._ancestor_ids(id))]
        fitments = [f for f in self.s.inn(self.org, id, "AT") if f["label"] == "Fitment"]
        fitments.sort(key=lambda f: (f["from"], f.get("to") or "9999"), reverse=True)
        current = next((f for f in fitments if f.get("to") is None), None)
        modes = self.s.out(self.org, id, "CAN_FAIL_AS")
        tasks = [self._task_view(t) for t in self.s.inn(self.org, id, "ON") if t["label"] == "Task"]
        wos = [w for w in self.s.inn(self.org, id, "ON") if w["label"] == "WorkOrder"]
        wos.sort(key=lambda w: w["number"], reverse=True)
        kids = sorted(self.s.inn(self.org, id, "PART_OF"), key=lambda c: c["name"].lower())
        return {
            "id": p["id"], "name": p["name"], "tag": p.get("tag", ""),
            "position_class": p.get("position_class", ""), "description": p.get("description", ""),
            "path": [{"id": a["id"], "name": a["name"]} for a in path],
            "children": [{"id": c["id"], "name": c["name"]} for c in kids],
            "fitted": current and self._fitment_view(current),
            "fitments": [self._fitment_view(f) for f in fitments],
            "failure_modes": [{k: m.get(k) for k in ("id", "text", "function", "failure", "consequence", "outcome")}
                              for m in sorted(modes, key=lambda m: m["text"].lower())],
            "tasks": sorted(tasks, key=lambda t: t["next_due"] or "9999"),
            "work_orders": [self._wo_brief(w) for w in wos],
            "life_data": self.life_data(id),
        }

    def _wo_brief(self, w: dict) -> dict:
        position = self.s.out(self.org, w["id"], "ON")
        return {k: w.get(k) for k in ("id", "number", "title", "type", "status", "opened", "due", "closed")} | {
            "position": position and {"id": position[0]["id"], "name": position[0]["name"]},
        }

    def work_orders(self, status: str | None = None) -> list[dict]:
        wos = [w for w in self.s.nodes(self.org, "WorkOrder") if not status or w["status"] == status]
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

    def item(self, id: str) -> dict:
        self._get(id, "Item")
        return next(i for i in self.items() if i["id"] == id)

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
        for f in self.s.inn(self.org, position_id, "AT"):
            if f["label"] != "Fitment":
                continue
            end = f.get("to") or today
            days = (date.fromisoformat(end) - date.fromisoformat(f["from"])).days
            view = self._fitment_view(f)
            rows.append({
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
        "positions": len(m.s.nodes(m.org, "Position")),
        "items": len(m.s.nodes(m.org, "Item")),
        "open_work_orders": sum(1 for w in m.s.nodes(m.org, "WorkOrder") if w["status"] == "open"),
        "tasks": len(m.s.nodes(m.org, "Task")),
    }

