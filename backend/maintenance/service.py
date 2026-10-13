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

import math
import time
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
END_REASONS = ("failure", "planned", "other")
# Where a task added by hand comes from: the maker's manual, a law or standard,
# the organisation's own practice, or something else. (Tasks from an RCM study
# show as "rcm".)
TASK_SOURCES = ("manual", "oem", "statutory", "other")
# How well a historical date is known (passed through on past fitments).
DATE_PRECISIONS = ("exact", "month", "year", "estimated")


class NotFound(KeyError):
    """No such node in this organisation."""


class Invalid(ValueError):
    """The request can't be done as asked (HTTP 422)."""


class LimitReached(Invalid):
    """An organisation has reached one of its limits (HTTP 422)."""

    status = 422


class RateLimited(LimitReached):
    """Too many changes in the last minute (HTTP 429)."""

    status = 429


# ---- limits --------------------------------------------------------------------
# Generous ceilings, per organisation, so one workspace's use stays within what
# a shared process holds comfortably.

SHORT_TEXT = 200  # names, titles, tags, serials
LONG_TEXT = 4000  # descriptions, notes, instructions, reasons
MAX_NOTES = 5 * LONG_TEXT  # an item's or work order's notes, grown by appended lines
NOTE_HISTORY = 20  # earlier versions of a note kept on the node (the log keeps every one)
_LONG_FIELDS = {"description", "notes", "note", "instructions", "reason"}

MAX_COPY_NODES = 500  # positions, failure modes and tasks made by one copy
MAX_LIST = 100  # ids or entries given in one request
MAX_POSITIONS = 20_000
MAX_ITEMS = 50_000
MAX_TASKS = 100_000
MAX_PHOTOS = 5_000
MAX_PART_LISTINGS = 100_000  # entries on positions' parts lists
MAX_PARTS_EACH = 200  # on one position's parts list
MAX_EVENTS = 1_000_000
MAX_READINGS_PER_DAY = 500_000  # automated readings stored, per organisation per day (UTC)
WRITES_PER_MINUTE = 600  # changes started, per organisation per minute

MAX_AMOUNT = 1e12  # readings, costs, quantities
MAX_CALENDAR_DAYS = 100 * 365.25  # a task interval of at most 100 years
MAX_USE_INTERVAL = 1e7  # hours, cycles, km...
_DAYS_PER = {"days": 1.0, "weeks": 7.0, "months": 30.4375, "years": 365.25}
EARLIEST_DAY, LATEST_DAY = "1900-01-01", "2199-12-31"


# ---- helpers -------------------------------------------------------------------

def _day(value, what: str = "date") -> str:
    """A date as ISO text; today when not given."""
    if value in (None, ""):
        return date.today().isoformat()
    try:
        day = date.fromisoformat(str(value)[:10]).isoformat()
    except ValueError:
        raise Invalid(f"The {what} must be a date like 2026-10-13; got {str(value)[:40]!r}.")
    if not EARLIEST_DAY <= day <= LATEST_DAY:
        raise Invalid(f"The {what} must be between {EARLIEST_DAY[:4]} and {LATEST_DAY[:4]}.")
    return day


def _text(value, what: str, required: bool = False, max_len: int | None = None) -> str:
    """Text from a request: trimmed, and at most ``max_len`` characters (by
    default SHORT_TEXT, or LONG_TEXT for descriptions, notes and the like)."""
    text = str(value or "").strip()
    if required and not text:
        raise Invalid(f"The {what} is required.")
    limit = max_len or (LONG_TEXT if what in _LONG_FIELDS else SHORT_TEXT)
    if len(text) > limit:
        raise Invalid(f"The {what} is at most {limit} characters.")
    return text


def _number(value, what: str, low: float, high: float):
    """A finite number from a request, between ``low`` and ``high``."""
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        raise Invalid(f"The {what} must be a number.")
    if not math.isfinite(value):
        raise Invalid(f"The {what} must be a number.")
    if not low <= value <= high:
        raise Invalid(f"The {what} must be between {low:g} and {high:g}.")
    return value


def _interval(value, unit: str, what: str = "interval") -> float:
    """A task interval: positive, at most 100 years on the calendar, or
    MAX_USE_INTERVAL units of use."""
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        raise Invalid(f"The {what} must be a number.")
    if not math.isfinite(value) or value <= 0:
        raise Invalid(f"The {what} must be positive.")
    unit = _norm_unit(unit) or "days"
    if unit in _DAYS_PER:
        if value * _DAYS_PER[unit] > MAX_CALENDAR_DAYS:
            raise Invalid(f"The {what} is at most 100 years.")
    elif value > MAX_USE_INTERVAL:
        raise Invalid(f"The {what} is at most {MAX_USE_INTERVAL:g} {unit}.")
    return value


def _list(value, what: str, limit: int = MAX_LIST) -> list:
    if value in (None, ""):
        return []
    if not isinstance(value, (list, tuple)):
        raise Invalid(f"The {what} must be a list.")
    if len(value) > limit:
        raise Invalid(f"At most {limit} {what} at a time.")
    return list(value)


def _dicts(value, what: str, limit: int = MAX_LIST) -> list[dict]:
    items = _list(value, what, limit)
    if not all(isinstance(x, dict) for x in items):
        raise Invalid(f"Each of the {what} must be an object.")
    return items


# ---- dates known only roughly, costs, warranties, links ----------------------------
# A date can carry its precision: exact (the day is known), month or year (known to
# the month or year: stored as the period's first day, shown as "Mar 2022" or
# "2022"), or estimated (a best guess, shown as "~Mar 2022", taken as within
# ESTIMATE_MONTHS either side). Life data turns an uncertain fitment into a range.

DATE_PRECISIONS = ("exact", "month", "year", "estimated")
ESTIMATE_MONTHS = 3
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _precision(value, what: str = "date") -> str | None:
    """A date's precision from a request, or None when not given."""
    if value in (None, ""):
        return None
    if value not in DATE_PRECISIONS:
        raise Invalid(f"The {what}'s precision is one of {', '.join(DATE_PRECISIONS)}.")
    return value


def dated(value, precision=None, what: str = "date") -> tuple[str, str]:
    """A date and its precision from a request: (ISO day, precision). The date may
    be "2022" or "2022-03" (precision year or month, unless said otherwise) or a
    full date; today when not given. A month or year is stored as its first day."""
    precision = _precision(precision, what)
    text = str(value or "").strip()
    if not text:
        return _day(None, what), precision or "exact"
    parts = text[:10].split("-")
    if len(text) == 4 and text.isdigit():
        shown = "year"
    elif len(text) == 7 and len(parts) == 2 and all(x.isdigit() for x in parts):
        shown = "month"
    else:
        shown = "exact"
    precision = precision or shown
    if shown != "exact" and precision in ("exact", "estimated"):
        if precision == "exact":
            raise Invalid(f"An exact {what} needs the day, like 2022-03-15; for a month or a year, "
                          "give the precision month or year.")
        if shown == "year":
            raise Invalid(f"For a {what} known only to the year, give the precision year.")
        text += "-15"  # an estimate to the month: its middle
    elif shown == "year":
        text += "-01-01"
    elif shown == "month":
        text += "-01"
    day = _day(text, what)
    if precision == "year":
        day = day[:4] + "-01-01"
    elif precision == "month":
        day = day[:7] + "-01"
    return day, precision


def date_range(day: str, precision: str | None) -> tuple[date, date]:
    """The earliest and latest day a date with this precision can be."""
    d = date.fromisoformat(day)
    if precision == "year":
        return d.replace(month=1, day=1), d.replace(month=12, day=31)
    if precision == "month":
        first = d.replace(day=1)
        return first, first + relativedelta(months=1) - timedelta(days=1)
    if precision == "estimated":
        return d - relativedelta(months=ESTIMATE_MONTHS), d + relativedelta(months=ESTIMATE_MONTHS)
    return d, d


def date_text(day: str | None, precision: str | None) -> str | None:
    """A date as it's known: "2022", "Mar 2022", "~Mar 2022", or the day."""
    if not day:
        return None
    month = _MONTHS[int(day[5:7]) - 1]
    if precision == "year":
        return day[:4]
    if precision == "month":
        return f"{month} {day[:4]}"
    if precision == "estimated":
        return f"~{month} {day[:4]}"
    return f"{int(day[8:10])} {month} {day[:4]}"


def _dated_value(value, what: str) -> dict | None:
    """An item's date (purchase, in service, manufacture): {date, precision, source}
    from a date text or an object with them; None (or {}) clears it."""
    if value in (None, "", {}):
        return None
    if isinstance(value, str):
        value = {"date": value}
    if not isinstance(value, dict):
        raise Invalid(f"The {what} is a date, or {{date, precision, source}}.")
    if not value.get("date"):
        raise Invalid(f"The {what} needs a date (2022, 2022-03 or 2022-03-15).")
    day, precision = dated(value.get("date"), value.get("precision"), what)
    if day > date.today().isoformat():
        raise Invalid(f"The {what} can't be in the future.")
    return {"date": day, "precision": precision, "source": _text(value.get("source"), f"{what}'s source")}


def _check_order(start: str, start_precision, end: str, end_precision) -> None:
    """Refuse an end that can't be after the start, whatever the precisions allow."""
    if date_range(end, end_precision)[1] < date_range(start, start_precision)[0]:
        raise Invalid("It can't come out before it went in.")


def _dated_view(value: dict | None) -> dict | None:
    return value and {**value, "display": date_text(value["date"], value.get("precision"))}


def _currency(value) -> str:
    text = str(value or "").strip().upper()
    if text and not (len(text) == 3 and text.isalpha() and text.isascii()):
        raise Invalid("The currency is a three-letter code, like AUD, USD or EUR.")
    return text


def _cost_value(value, what: str = "replacement cost") -> dict | None:
    """A replacement cost: {amount, currency, source, as_of}; None (or {}) clears it."""
    if value in (None, "", {}):
        return None
    if not isinstance(value, dict):
        raise Invalid(f"The {what} is {{amount, currency, source, as_of}}.")
    if value.get("amount") in (None, ""):
        raise Invalid(f"The {what} needs an amount.")
    as_of = _day(value.get("as_of"), f"{what}'s as-of date")
    if as_of > date.today().isoformat():
        raise Invalid(f"The {what}'s as-of date can't be in the future.")
    return {"amount": _number(value["amount"], what, 0, MAX_AMOUNT), "currency": _currency(value.get("currency")),
            "source": _text(value.get("source"), f"{what}'s source"), "as_of": as_of}


WARRANTY_FIELDS = ("ends_on", "terms", "coverage", "registration_required", "registered", "register_by")


def _flag_value(value, what: str) -> bool:
    if value in (None, ""):
        return False
    if isinstance(value, bool):
        return value
    if str(value).strip().lower() in ("true", "yes", "1"):
        return True
    if str(value).strip().lower() in ("false", "no", "0"):
        return False
    raise Invalid(f"{what} is true or false.")


def _warranty_value(value) -> dict | None:
    """A warranty: when it ends, its terms and what it covers, and whether it must be
    registered (and by when) and has been. None (or {}) clears it."""
    if value in (None, "", {}):
        return None
    if not isinstance(value, dict):
        raise Invalid("The warranty is {ends_on, terms, coverage, registration_required, registered, register_by}.")
    if not value.get("ends_on"):
        raise Invalid("The warranty needs the date it ends on.")
    out = {"ends_on": _day(value["ends_on"], "warranty's end date"),
           "terms": _text(value.get("terms"), "warranty's terms", max_len=LONG_TEXT),
           "coverage": _text(value.get("coverage"), "warranty's coverage", max_len=1000),
           "registration_required": _flag_value(value.get("registration_required"), "registration_required"),
           "registered": _flag_value(value.get("registered"), "registered"),
           "register_by": _day(value["register_by"], "registration date") if value.get("register_by") else None}
    if out["register_by"] and not out["registration_required"]:
        out["registration_required"] = True
    return out


def warranty_view(w: dict | None, on: str | None = None) -> dict | None:
    """A warranty with where it stands on ``on`` (today): in warranty or not, and any
    registration still to do."""
    if not w:
        return None
    on = on or date.today().isoformat()
    due = w["register_by"] if w.get("registration_required") and not w.get("registered") else None
    in_warranty = w["ends_on"] >= on
    words = [f"In warranty until {date_text(w['ends_on'], 'exact')}" if in_warranty
             else f"Warranty ended {date_text(w['ends_on'], 'exact')}"]
    overdue = bool(due and due < on and in_warranty)
    if w.get("registration_required") and not w.get("registered"):
        words.append(f"registration was due by {date_text(due, 'exact')} and isn't recorded: the warranty "
                     "may not apply" if overdue else f"registration due by {date_text(due, 'exact')}" if due
                     else "registration still to do")
    return {**w, "in_warranty": in_warranty, "registration_due": due,
            "registration_overdue": overdue, "summary": "; ".join(words) + "."}


DOCUMENT_KINDS = ("manual", "datasheet", "invoice", "drawing", "certificate", "other")
MAX_DOCUMENTS = 20_000  # per organisation
MAX_DOCUMENTS_EACH = 100  # on one item, position or class
MAX_URL = 2000


def _url(value) -> str:
    """A document link: an http(s) web address, nothing else (no javascript:, data:,
    file: or the like), with no spaces, control characters or user name in it."""
    from urllib.parse import urlsplit

    text = str(value or "").strip()
    if not text:
        raise Invalid("The document's link (URL) is required.")
    if len(text) > MAX_URL:
        raise Invalid(f"The link is at most {MAX_URL} characters.")
    if any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in text):
        raise Invalid("The link can't contain spaces or control characters.")
    try:
        parts = urlsplit(text)
        host = parts.hostname
    except ValueError:
        raise Invalid("That link isn't a web address.")
    if parts.scheme.lower() not in ("http", "https") or not host:
        raise Invalid("A document link is a web address starting http:// or https://, "
                      "like https://example.com/manual.pdf.")
    if "@" in parts.netloc:
        raise Invalid("The link can't carry a user name or password.")
    return text


def add_interval(day: str, interval: float, unit: str) -> str | None:
    """``day`` plus ``interval`` calendar units, or None for a unit of use
    (hours, cycles, km), which needs a meter to schedule. None too when the
    date would fall outside the calendar."""
    unit = _norm_unit(unit) or "days"
    try:
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
    except (OverflowError, ValueError, TypeError):
        return None
    return None


def _same_text(a, b) -> bool:
    """Whether two names say the same thing, case and spacing aside."""
    return " ".join(str(a or "").lower().split()) == " ".join(str(b or "").lower().split())


def _end_reason(reason, mode_ref) -> str:
    """Why a fitment ended. Not given: a failure if a failure mode is named,
    otherwise planned. A planned removal can't name a failure mode (that is
    how failures used to end up counted as planned)."""
    if reason in (None, ""):
        return "failure" if mode_ref else "planned"
    if reason not in END_REASONS:
        raise Invalid("The reason is failure, planned or other.")
    if reason == "planned" and mode_ref:
        raise Invalid("A planned removal has no failure mode. Say the reason is failure, or leave the "
                      "failure mode out.")
    return reason


def _unit(value, default: str) -> str:
    unit = _norm_unit(value) or default
    if len(unit) > 20:
        raise Invalid("The unit is at most 20 characters.")
    return unit


def _checklist(value) -> list[str]:
    items = [_text(c, "checklist item")[:200] for c in _list(value, "checklist items")]
    items = [c for c in items if c]
    if len(items) > 50:
        raise Invalid("At most 50 checklist items.")
    return items


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
        "note_history": _note_entry([], p["on"], "set", p.get("notes", "")),
    })


# ---- notes: an item's or a work order's, replaced or added to -------------------
# Each change is kept in the node's note_history (date, how, text), so a note
# replaced by mistake can be read back. Events logged before 13 Oct 2026 carry
# no date on an edit: those versions have "on": None.

def _note_entry(history: list, on, change: str, text: str) -> list:
    if change == "set" and not text and not history:
        return []
    return (list(history) + [{"on": on, "change": change, "text": text}])[-NOTE_HISTORY:]


def _patch_noted(s: GraphStore, org: str, p: dict) -> None:
    """item.updated, work_order.updated: field changes; a new note is kept in the history."""
    _patch(s, org, p)
    if "notes" in p["changes"]:
        node = s.node(org, p["id"])
        s.patch_node(org, p["id"], {"note_history": _note_entry(node.get("note_history") or [], p.get("on"), "set",
                                                                p["changes"]["notes"])})


def _note_appended(s: GraphStore, org: str, p: dict) -> None:
    """note.appended: a dated line added to the end of an item's or work order's notes."""
    node = s.node(org, p["id"])
    line = f"{p['on']}: {p['text']}"
    notes = node.get("notes") or ""
    s.patch_node(org, p["id"], {"notes": f"{notes}\n{line}" if notes else line,
                                "note_history": _note_entry(node.get("note_history") or [], p["on"], "appended",
                                                            p["text"])})


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
    s.patch_node(org, p["id"], {k: p[k] for k in ("from", "to", "from_precision", "to_precision") if k in p})


def _work_order_cancelled(s: GraphStore, org: str, p: dict) -> None:
    # The reason is its own field: the notes (the diagnosis so far) stay as they were.
    wo = s.node(org, p["id"])
    history = list(wo.get("status_history") or []) + [{"status": "cancelled", "on": p["on"],
                                                       "note": p.get("reason", "")}]
    s.patch_node(org, p["id"], {"status": "cancelled", "closed": p["on"], "cancel_reason": p.get("reason", ""),
                                "status_history": history})


def _item_placed(s: GraphStore, org: str, p: dict) -> None:
    for held in s.out(org, p["item_id"], "IN"):
        if held["label"] == "Placement" and held.get("to") is None:
            s.patch_node(org, held["id"], {"to": p["on"]})
    s.put_node(org, p["placement_id"], "Placement", {"from": p["on"], "to": None})
    s.put_edge(org, "IN", p["item_id"], p["placement_id"])
    s.put_edge(org, "AT", p["placement_id"], p["location_id"])


def _item_fitted(s: GraphStore, org: str, p: dict) -> None:
    # from_precision only when the start isn't an exact day (older events have none).
    s.put_node(org, p["fitment_id"], "Fitment", {"from": p["on"], "to": None, "end_reason": None,
                                                 "failure_mode_id": None}
               | ({"from_precision": p["from_precision"]} if p.get("from_precision") else {}))
    s.put_edge(org, "IN", p["item_id"], p["fitment_id"])
    s.put_edge(org, "AT", p["fitment_id"], p["position_id"])
    # A new item is a renewal: the position's tasks count from the day it went in.
    for task in s.inn(org, p["position_id"], "ON"):
        if task["label"] == "Task":
            _renew_task(s, org, task, p["on"], (p.get("task_readings") or {}).get(task["id"]))


def _item_removed(s: GraphStore, org: str, p: dict) -> None:
    s.patch_node(org, p["fitment_id"], {"to": p["on"], "end_reason": p["reason"],
                                        "failure_mode_id": p.get("failure_mode_id")}
                 | ({"to_precision": p["to_precision"]} if p.get("to_precision") else {}))


def _fitment_added(s: GraphStore, org: str, p: dict) -> None:
    """A past fitment put into a position's history: in and out again, with no
    work order, and no effect on the tasks (they count from the current item)."""
    s.put_node(org, p["fitment_id"], "Fitment", {
        "from": p["from"], "to": p["to"], "end_reason": p["reason"], "failure_mode_id": p.get("failure_mode_id"),
        "past": True, "note": p.get("note", ""),
    } | {k: p[k] for k in ("from_precision", "to_precision") if p.get(k)})
    s.put_edge(org, "IN", p["item_id"], p["fitment_id"])
    s.put_edge(org, "AT", p["fitment_id"], p["position_id"])


def _failure_mode_added(s: GraphStore, org: str, p: dict) -> None:
    s.put_node(org, p["id"], "FailureMode", {
        "text": p["text"], "function": p.get("function", ""), "failure": p.get("failure", ""),
        "consequence": p.get("consequence"), "outcome": p.get("outcome"),
        "rcm_mode_id": p.get("rcm_mode_id"), "study_id": p.get("study_id"),
    } | ({"ad_hoc": True} if p.get("ad_hoc") else {}))
    s.put_edge(org, "CAN_FAIL_AS", p["position_id"], p["id"])


def _failure_mode_merged(s: GraphStore, org: str, p: dict) -> None:
    """A mode folded into another on the same position: the failures recorded
    against it, the findings and the tasks that mitigate it all move across."""
    old, into = p["id"], p["into_id"]
    for position in s.inn(org, old, "CAN_FAIL_AS"):
        for f in s.inn(org, position["id"], "AT"):
            if f["label"] == "Fitment" and f.get("failure_mode_id") == old:
                s.patch_node(org, f["id"], {"failure_mode_id": into})
    for edge in ("FOUND", "MITIGATES"):
        for src in s.inn(org, old, edge):
            s.delete_edge(org, edge, src["id"], old)
            s.put_edge(org, edge, src["id"], into)
    s.patch_node(org, old, {"merged_into": into, "merged_on": p.get("on")})


# Task fields that only tasks added by hand (or edited since) carry: projected
# only when the payload has them, so older events give the same tasks.
_TASK_EXTRAS = ("source", "reference", "also_interval", "also_unit", "point_id", "instructions", "checklist",
               "trade")


def _task_added(s: GraphStore, org: str, p: dict) -> None:
    s.put_node(org, p["id"], "Task", {
        "name": p["name"], "outcome": p.get("outcome"), "interval": p["interval"], "unit": p["unit"],
        "start": p["start"], "last_done": None, "rcm_mode_id": p.get("rcm_mode_id"),
        "study_id": p.get("study_id"),
    } | {k: p[k] for k in _TASK_EXTRAS if k in p})
    s.put_edge(org, "ON", p["id"], p["position_id"])
    if p.get("failure_mode_id"):
        s.put_edge(org, "MITIGATES", p["id"], p["failure_mode_id"])


def _task_updated(s: GraphStore, org: str, p: dict) -> None:
    changes = dict(p["changes"])
    if "failure_mode_id" in changes:
        # Linked to a failure mode (or unlinked: None), not a field.
        mode = changes.pop("failure_mode_id")
        for old in s.out(org, p["id"], "MITIGATES"):
            s.delete_edge(org, "MITIGATES", p["id"], old["id"])
        if mode:
            s.put_edge(org, "MITIGATES", p["id"], mode)
    s.patch_node(org, p["id"], changes)


def _work_order_opened(s: GraphStore, org: str, p: dict) -> None:
    task = s.node(org, p["task_id"]) if p.get("task_id") else None
    s.put_node(org, p["id"], "WorkOrder", {
        "number": p["number"], "title": p["title"], "type": p["type"], "status": "open",
        "opened": p["on"], "due": p.get("due"), "closed": None, "notes": p.get("notes", ""),
        "note_history": _note_entry([], p["on"], "set", p.get("notes", "")),
        # A task's instructions and checklist travel with the work it raises.
        "instructions": (task or {}).get("instructions", ""),
        "checklist": [{"text": t, "done": False} for t in (task or {}).get("checklist") or []],
        "status_history": [{"status": "open", "on": p["on"]}],
    })
    # So does the trade the work needs, unless the work order names its own.
    trade = p.get("trade") or (task or {}).get("trade")
    if trade:
        s.patch_node(org, p["id"], {"trade": trade})
    s.put_edge(org, "ON", p["id"], p["position_id"])
    if p.get("task_id"):
        s.put_edge(org, "FOR", p["id"], p["task_id"])
    if p.get("alarm_point_id"):
        s.put_edge(org, "ALARM_FOR", p["id"], p["alarm_point_id"])


def _point_added(s: GraphStore, org: str, p: dict) -> None:
    """point.added, and the older meter.added / condition_point.added (replayed into
    the same shape: a meter counted use, a condition point showed condition)."""
    kind = p.get("kind") or ("condition" if "alarm_above" in p or "alarm_below" in p else "counter")
    s.put_node(org, p["id"], "MeasurementPoint", {
        "name": p["name"], "kind": kind, "unit": p.get("unit", ""), "source": p.get("source") or "manual",
        "tag": p.get("tag", ""), "alarm_above": p.get("alarm_above"), "alarm_below": p.get("alarm_below"),
        "created": p["on"]})
    s.put_edge(org, "ON", p["id"], p["position_id"])


def _reading_added(s: GraphStore, org: str, p: dict) -> None:
    """reading.added, and the older meter.read / condition.read: a manual reading."""
    point_id = p.get("point_id") or p.get("meter_id")
    s.put_node(org, p["id"], "Reading", {"on": p["on"], "value": p["value"], "note": p.get("note", "")})
    s.put_edge(org, "OF", p["id"], point_id)
    point = s.node(org, point_id)
    # Up to now readings came in date order. One dated on or before the latest
    # (backdated) can change the reading a task by use was last done at.
    if point.get("latest_on") and p["on"] <= point["latest_on"]:
        _reread_tasks(s, org, point_id, p["on"])
    else:
        s.patch_node(org, point_id, {"latest_on": p["on"]})


def _reading_voided(s: GraphStore, org: str, p: dict) -> None:
    _flag("voided")(s, org, p)
    point = s.out(org, p["id"], "OF")[0]
    _reread_tasks(s, org, point["id"], s.node(org, p["id"])["on"])


def _reading_corrected(s: GraphStore, org: str, p: dict) -> None:
    """A reading struck out and replaced by one with the right value or date,
    each pointing at the other."""
    old = s.node(org, p["id"])
    point_id = s.out(org, p["id"], "OF")[0]["id"]
    s.patch_node(org, p["id"], {"voided": True, "voided_on": p["corrected_on"], "voided_reason": p["reason"],
                                "replaced_by": p["new_id"]})
    s.put_node(org, p["new_id"], "Reading", {"on": p["on"], "value": p["value"], "note": old.get("note", ""),
                                             "replaces": p["id"], "reason": p["reason"],
                                             "corrected_on": p["corrected_on"]})
    s.put_edge(org, "OF", p["new_id"], point_id)
    point = s.node(org, point_id)
    if p["on"] > (point.get("latest_on") or ""):
        s.patch_node(org, point_id, {"latest_on": p["on"]})
    _reread_tasks(s, org, point_id, min(old["on"], p["on"]))


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


# ---- measurements: use counters and condition, manual or automated -------------
# A measurement point counts use (run hours, cycles, km: only goes up, drives tasks
# by use) or shows condition (vibration, temperature: alarms and trends). Its
# readings are manual (entered by someone: events, in the log) or automated (a
# feed: in the time-series store, series.py).

USAGE_UNITS = ("hours", "cycles", "km", "miles", "starts", "tonnes", "litres")
POINT_KINDS = ("counter", "condition")
POINT_SOURCES = ("manual", "automated")


def _is_calendar(unit: str) -> bool:
    return (_norm_unit(unit) or "days") in CALENDAR_UNITS


def _manual_readings(s: GraphStore, org: str, point_id: str) -> list[dict]:
    rows = [r for r in s.inn(org, point_id, "OF") if r["label"] == "Reading" and not r.get("voided")]
    return sorted(rows, key=lambda r: (r["on"], r["value"]))


def _readings(s: GraphStore, org: str, point: dict) -> list[dict]:
    """A point's readings, oldest first, one per day for a feed (its last that day)."""
    if point.get("source") == "automated":
        return s.series.daily(org, point["id"])
    return _manual_readings(s, org, point["id"])


def _reading_at(readings: list[dict], day: str) -> float | None:
    """The counter on ``day``: interpolated between the readings either side, the
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


def _reread_tasks(s: GraphStore, org: str, point_id: str, day: str) -> None:
    """A manual counter's readings changed on or before ``day`` (one backdated, struck
    out or corrected): each task by use that goes by it and was last done since then
    takes its last-done reading again, from the readings as they are now."""
    point = s.node(org, point_id)
    if point.get("source") == "automated" or point.get("kind") != "counter":
        return
    readings = None
    for task in s.nodes(org, "Task"):
        if not task.get("last_done") or task["last_done"] < day:
            continue
        if (_task_point(s, org, task) or {}).get("id") != point_id:
            continue
        if readings is None:
            readings = _manual_readings(s, org, point_id)
        value = _reading_at(readings, task["last_done"])
        if value != task.get("last_done_reading"):
            s.patch_node(org, task["id"], {"last_done_reading": value})


def _task_point(s: GraphStore, org: str, task: dict) -> dict | None:
    """The use counter a task by use goes by: the one chosen, else the position's
    counter in the task's unit."""
    chosen = task.get("point_id") or task.get("meter_id")
    if chosen:
        return s.node(org, chosen)
    for unit in (task.get("unit"), task.get("also_unit")):
        if unit and not _is_calendar(unit):
            position = s.out(org, task["id"], "ON")
            points = [mp for mp in (s.inn(org, position[0]["id"], "ON") if position else [])
                      if mp["label"] == "MeasurementPoint" and mp.get("kind") == "counter"
                      and _norm_unit(mp["unit"]) == _norm_unit(unit)]
            if points:
                return sorted(points, key=lambda mp: mp["name"].lower())[0]
    return None


def _renew_task(s: GraphStore, org: str, task: dict, day: str, reading=None) -> None:
    """The task was done (or its item renewed) on ``day``: record the date, and the
    counter reading then if it goes by use. A feed's reading comes in the event (the
    projector can't read the time-series store); a manual one is read here."""
    if task.get("last_done") and task["last_done"] >= day:
        return
    changes = {"last_done": day}
    if reading is not None:
        changes["last_done_reading"] = reading
    else:
        point = _task_point(s, org, task)
        if point and point.get("source") != "automated":
            changes["last_done_reading"] = _reading_at(_manual_readings(s, org, point["id"]), day)
    s.patch_node(org, task["id"], changes)


def _work_order_closed(s: GraphStore, org: str, p: dict) -> None:
    wo = s.node(org, p["id"])
    # Work recorded after the fact: it was opened no later than it was done.
    opened = min(wo["opened"], p["on"])
    # Closing notes are their own field: the notes from before stay.
    s.patch_node(org, p["id"], {"status": "closed", "closed": p["on"], "opened": opened,
                                "close_notes": p.get("notes", "")})
    for task in s.out(org, p["id"], "FOR"):
        _renew_task(s, org, task, p["on"], (p.get("task_readings") or {}).get(task["id"]))


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


def class_id(org: str, name: str) -> str:
    """A position class's node id: one per organisation and class name (case
    and spacing aside)."""
    import hashlib

    key = org + "\n" + " ".join(name.lower().split())
    return "class-" + hashlib.sha1(key.encode()).hexdigest()[:16]


def _class_upsert(s: GraphStore, org: str, p: dict, changes: dict) -> None:
    # The id comes from the organisation and the name, not the payload: events
    # logged before the id took in the organisation carry the older form.
    cid = class_id(org, p["name"])
    if s.node(org, cid) is None:
        s.put_node(org, cid, "PositionClass", {"name": p["name"]})
    s.patch_node(org, cid, changes)


def _class_costs_set(s: GraphStore, org: str, p: dict) -> None:
    _class_upsert(s, org, p, {k: p.get(k) for k in ("planned_cost", "failure_cost", "availability_target")})


def _class_updated(s: GraphStore, org: str, p: dict) -> None:
    """class.updated: plain field changes on a class (its default replacement cost)."""
    _class_upsert(s, org, p, p["changes"])


def _document_added(s: GraphStore, org: str, p: dict) -> None:
    """A link to a document (a manual, a datasheet, an invoice) on an item, a
    position, or a position class (named, like the class's other events)."""
    target = p.get("target_id")
    if p.get("class_name"):
        _class_upsert(s, org, {"name": p["class_name"]}, {})
        target = class_id(org, p["class_name"])
    s.put_node(org, p["id"], "Document", {"title": p["title"], "url": p["url"], "kind": p["kind"],
                                          "added_on": p["on"], "removed": False})
    s.put_edge(org, "OF", p["id"], target)


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


def stock_id(part_id: str, location_id: str) -> str:
    return f"stock-{part_id[:12]}-{location_id[:12]}"


def _part_created(s: GraphStore, org: str, p: dict) -> None:
    s.put_node(org, p["id"], "Part", {k: p.get(k, "") for k in ("part_number", "name", "manufacturer", "unit", "notes")}
               | {"unit_cost": p.get("unit_cost"), "created": p["on"], "superseded_by": None})


def _part_superseded(s: GraphStore, org: str, p: dict) -> None:
    s.patch_node(org, p["id"], {"superseded_by": p["by_id"]})
    s.put_edge(org, "SUPERSEDED_BY", p["id"], p["by_id"])


def _parts_interchangeable(s: GraphStore, org: str, p: dict) -> None:
    s.put_edge(org, "INTERCHANGEABLE", p["a"], p["b"])
    s.put_edge(org, "INTERCHANGEABLE", p["b"], p["a"])


def _stock_adjusted(s: GraphStore, org: str, p: dict) -> None:
    sid = stock_id(p["part_id"], p["location_id"])
    node = s.node(org, sid)
    if node is None:
        s.put_node(org, sid, "Stock", {"quantity": 0.0, "reorder_point": None, "moves": []})
        s.put_edge(org, "OF", sid, p["part_id"])
        s.put_edge(org, "AT", sid, p["location_id"])
        node = s.node(org, sid)
    moves = (list(node.get("moves") or []) + [{"on": p["on"], "delta": p["delta"], "reason": p.get("reason", ""),
                                                "work_order_id": p.get("work_order_id")}])[-200:]
    s.patch_node(org, sid, {"quantity": round(node["quantity"] + p["delta"], 6), "moves": moves})


def _stock_reorder_set(s: GraphStore, org: str, p: dict) -> None:
    sid = stock_id(p["part_id"], p["location_id"])
    if s.node(org, sid) is None:
        _stock_adjusted(s, org, {**p, "delta": 0, "reason": "reorder point set"})
    s.patch_node(org, sid, {"reorder_point": p["reorder_point"]})


def _position_part_listed(s: GraphStore, org: str, p: dict) -> None:
    """A catalogue part on a position's parts list: the part that replaces what's
    fitted, or a component or consumable its maintenance uses."""
    s.put_node(org, p["id"], "PartListing", {
        "role": p["role"], "quantity": p["quantity"], "critical": p.get("critical", False),
        "min_on_hand": p.get("min_on_hand"), "notes": p.get("notes", ""), "listed": p["on"], "removed": False})
    s.put_edge(org, "LISTED_AT", p["id"], p["position_id"])
    s.put_edge(org, "LISTS", p["id"], p["part_id"])


PROJECTORS = {
    "position.created": _position_created,
    "position.updated": _position_updated,
    "location.created": _location_created,
    "item.created": _item_created,
    "item.placed": _item_placed,
    "item.fitted": _item_fitted,
    "item.removed": _item_removed,
    "fitment.added": _fitment_added,
    "failure_mode.added": _failure_mode_added,
    "failure_mode.updated": _patch,
    "failure_mode.merged": _failure_mode_merged,
    "task.added": _task_added,
    "task.updated": _task_updated,
    "work_order.opened": _work_order_opened,
    "action.recorded": _action_recorded,
    "work_order.closed": _work_order_closed,
    "item.updated": _patch_noted,
    "task.retired": _flag("retired"),
    "position.retired": _flag("retired"),
    "fitment.voided": _flag("voided"),
    "fitment.corrected": _fitment_corrected,
    "work_order.updated": _patch_noted,
    "work_order.cancelled": _work_order_cancelled,
    "location.updated": _patch,
    "point.added": _point_added,
    "point.updated": _patch,
    "reading.added": _reading_added,
    "meter.added": _point_added,
    "meter.read": _reading_added,
    "reading.voided": _reading_voided,
    "reading.corrected": _reading_corrected,
    "note.appended": _note_appended,
    "class.costs_set": _class_costs_set,
    "class.model_fitted": _class_model_fitted,
    "class.updated": _class_updated,
    "document.added": _document_added,
    "document.removed": _flag("removed"),
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
    "condition_point.added": _point_added,
    "condition_point.updated": _patch,
    "condition.read": _reading_added,
    "part.created": _part_created,
    "part.updated": _patch,
    "part.superseded": _part_superseded,
    "parts.interchangeable": _parts_interchangeable,
    "stock.adjusted": _stock_adjusted,
    "stock.reorder_set": _stock_reorder_set,
    "position_part.listed": _position_part_listed,
    "position_part.updated": _patch,
    "position_part.removed": _flag("removed"),
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

    def __init__(self, store: GraphStore, org: str, actor: str | None = None, limited: bool = True):
        self.s = store
        self.org = org
        self.actor = actor
        # The daily run isn't limited: it writes for every organisation.
        self.limited = limited
        self._checked = False

    def check_limits(self) -> None:
        """Before a change: refuse when the organisation has started too many
        changes this minute, or holds MAX_EVENTS events. Counted per change
        (one request, one tool call), not per event, so a large import is one."""
        self._checked = True
        if not self.limited:
            return
        now = time.monotonic()
        window = self.s.write_windows.get(self.org)
        if window is None or now - window[0] >= 60:
            window = self.s.write_windows[self.org] = [now, 0]
        if window[1] >= WRITES_PER_MINUTE:
            raise RateLimited(f"Too many changes in the last minute (at most {WRITES_PER_MINUTE}). "
                              "Wait a moment and try again.")
        window[1] += 1
        if self.s.event_count(self.org) >= MAX_EVENTS:
            raise LimitReached(f"This maintenance workspace has reached its limit of {MAX_EVENTS:,} recorded changes.")

    def _quota(self, label: str, limit: int, adding: int = 1, what: str = "") -> None:
        if self.limited and self.s.count(self.org, label) + adding > limit:
            raise LimitReached(f"This maintenance workspace can hold at most {limit:,} {what or label.lower() + 's'}.")

    def _emit(self, type: str, payload: dict) -> None:
        if not self._checked:
            self.check_limits()
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
        self._quota("Position", MAX_POSITIONS)
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
        failure modes, their tasks and their parts lists (not items, stock or work
        orders). For a second pump station like the first, or a template."""
        source = self._get(position_id, "Position")
        new_name = _text(name, "copy's name", required=True)
        if parent_id:
            self._get(parent_id, "Position")
            if parent_id == position_id or position_id in self._ancestor_ids(parent_id):
                raise Invalid("A position can't be copied into itself.")
        today = date.today().isoformat()

        # Read the whole subtree first, then write: what's copied is the tree as
        # it was, never the copy being made.
        plan, seen, size = [], set(), 0

        def read(src: dict, new_pid: str, label: str, parent: str | None) -> None:
            nonlocal size
            if src["id"] in seen:
                return
            seen.add(src["id"])
            modes = self._modes_on(src["id"])
            tasks = [t for t in self.s.inn(self.org, src["id"], "ON") if t["label"] == "Task"]
            listings = self._listings_at(src["id"])
            size += 1 + len(modes) + len(tasks) + len(listings)
            if size > MAX_COPY_NODES:
                raise Invalid(f"That's more than {MAX_COPY_NODES} positions, failure modes, tasks and parts-list "
                              "entries to copy at once. Copy a smaller part of it.")
            plan.append((src, new_pid, label, parent, modes, tasks, listings))
            for child in sorted(self.s.inn(self.org, src["id"], "PART_OF"), key=lambda c: c["name"].lower()):
                if child["label"] == "Position":
                    read(child, new_id(), child["name"], new_pid)

        new = new_id()
        read(source, new, new_name, parent_id or None)
        self._quota("Position", MAX_POSITIONS, adding=len(plan))
        self._quota("PartListing", MAX_PART_LISTINGS, adding=sum(len(x[-1]) for x in plan), what="parts-list entries")
        for src, pid, label, parent, modes, tasks, listings in plan:
            self._emit("position.created", {
                "id": pid, "name": label, "tag": "", "parent_id": parent,
                "position_class": src.get("position_class", ""), "description": src.get("description", ""),
                "on": today,
            })
            mode_ids = {}
            for fm in modes:
                mode_ids[fm["id"]] = new_id()
                self._emit("failure_mode.added", {
                    "id": mode_ids[fm["id"]], "position_id": pid,
                    **{k: fm.get(k) for k in ("text", "function", "failure", "consequence", "outcome",
                                              "rcm_mode_id", "study_id")},
                    **({"ad_hoc": True} if fm.get("ad_hoc") else {}),
                })
            for task in tasks:
                mitigates = self.s.out(self.org, task["id"], "MITIGATES")
                self._emit("task.added", {
                    "id": new_id(), "position_id": pid,
                    "failure_mode_id": mitigates and mode_ids.get(mitigates[0]["id"]),
                    "start": today,
                    **{k: task.get(k) for k in ("name", "outcome", "interval", "unit", "rcm_mode_id", "study_id")},
                    # Not point_id: the copy has no measurement points yet.
                    **{k: task[k] for k in _TASK_EXTRAS if k in task and k != "point_id"},
                })
            for listing in listings:
                self._emit("position_part.listed", {
                    "id": new_id(), "position_id": pid, "part_id": self.s.out(self.org, listing["id"], "LISTS")[0]["id"],
                    **{k: listing.get(k) for k in ("role", "quantity", "critical", "min_on_hand", "notes")},
                    "on": today})
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
                    nameplate=None, **details) -> dict:
        """A new item. ``details``: any of ITEM_DETAILS (dates, replacement cost,
        warranty), as update_item takes them."""
        details = {k: v for k, v in details.items() if k in self.ITEM_DETAILS and v not in (None, "", {})}
        for key, value in details.items():
            self.ITEM_DETAILS[key](value)  # checked before anything is written
        self._quota("Item", MAX_ITEMS)
        iid = new_id()
        self._emit("item.created", {
            "id": iid, "name": _text(name, "item's name", required=True), "serial": _text(serial, "serial"),
            "part_number": _text(part_number, "part number"), "manufacturer": _text(manufacturer, "manufacturer"),
            "model": _text(model, "model"), "notes": _text(notes, "notes"), "on": date.today().isoformat(),
        })
        if nameplate or details:
            self.update_item(iid, nameplate=nameplate, **details)
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
                                        "nameplate", *self.ITEM_DETAILS)})["id"]
        raise Invalid("Say which item: an existing one, or a new one with a name.")

    def place_item(self, item_id: str, location_id: str, on=None) -> dict:
        """Record where an item is from ``on``. With no date: since it was fitted
        to its position, if it is (it has been there all along), otherwise today;
        never before it got where it is now."""
        self._get(item_id, "Item")
        self._get(location_id, "Location")
        here = next((p for p in self.s.out(self.org, item_id, "IN")
                     if p["label"] == "Placement" and p.get("to") is None), None)
        if on in (None, ""):
            fitted = self._current_fitment_of_item(item_id)
            day = fitted["from"] if fitted else date.today().isoformat()
            if here and here["from"] > day:
                day = here["from"]
        else:
            day = _day(on)
            if here and day < here["from"]:
                where = self.s.out(self.org, here["id"], "AT")
                raise Invalid(f"It has been at {where[0]['name'] if where else 'its location'} since {here['from']}; "
                              "a move can't be dated before that.")
        self._emit("item.placed", {"item_id": item_id, "location_id": location_id,
                                   "placement_id": new_id(), "on": day})
        return self.item(item_id)

    def _fitments_at(self, position_id: str) -> list[dict]:
        return [f for f in self.s.inn(self.org, position_id, "AT") if f["label"] == "Fitment" and not f.get("voided")]

    def _fitments_of(self, item_id: str) -> list[dict]:
        return [f for f in self.s.out(self.org, item_id, "IN") if f["label"] == "Fitment" and not f.get("voided")]

    def current_fitment(self, position_id: str) -> dict | None:
        return next((f for f in self._fitments_at(position_id) if f.get("to") is None), None)

    def _current_fitment_of_item(self, item_id: str) -> dict | None:
        return next((f for f in self._fitments_of(item_id) if f.get("to") is None), None)

    def fit(self, position_id: str, item_id=None, new_item=None, on=None, from_precision=None) -> dict:
        """Fit an item to an empty position (a first install, or after a removal).
        ``on`` may be known only roughly: "2022", "2022-03", or a day with
        from_precision estimated."""
        self._get(position_id, "Position")
        if self.current_fitment(position_id):
            raise Invalid("Something is already fitted here. Replace it through a work order, "
                          "or remove it first.")
        day, precision = dated(on, from_precision, "fitted date")
        iid = self._item_from(item_id, new_item)
        self._emit("item.fitted", {"fitment_id": new_id(), "item_id": iid, "position_id": position_id, "on": day,
                                   "task_readings": self._renewal_readings(position_id, day)}
                   | ({"from_precision": precision} if precision != "exact" else {}))
        return self.position(position_id)

    def remove(self, position_id: str, on=None, reason=None, failure_mode_id=None, failure_mode_text=None,
               to_precision=None) -> dict:
        """Take the fitted item out, with no work order (a correction, or an item
        moved elsewhere). A failure names its mode by id, or in words
        (failure_mode_text: the position's mode of that name, or a new ad-hoc one)."""
        current = self.current_fitment(position_id)
        if current is None:
            raise Invalid("Nothing is fitted here.")
        day, precision = dated(on, to_precision, "removal date")
        _check_order(current["from"], current.get("from_precision"), day, precision)
        ref = self._mode_ref(position_id, failure_mode_id, failure_mode_text)
        reason = _end_reason(reason, ref)
        self._emit("item.removed", {"fitment_id": current["id"], "on": day, "reason": reason,
                                    "failure_mode_id": self._mode_id(position_id, ref)}
                   | ({"to_precision": precision} if precision != "exact" else {}))
        return self.position(position_id)

    # ---- failure modes: from RCM, added by hand, or typed in at a failure ----------

    def _modes_on(self, position_id: str) -> list[dict]:
        """A position's failure modes, less those merged into another."""
        return [fm for fm in self.s.out(self.org, position_id, "CAN_FAIL_AS") if not fm.get("merged_into")]

    def _mode_ref(self, position_id: str, failure_mode_id=None, failure_mode_text=None) -> tuple | None:
        """Check the failure mode a failure names (nothing is written): ("id", id)
        for one of the position's modes, ("text", text) for one in words, or None."""
        text = _text(failure_mode_text, "failure mode")
        if failure_mode_id and text:
            raise Invalid("Name the failure mode by its id or in words, not both.")
        if failure_mode_id:
            fm = next((m for m in self.s.out(self.org, position_id, "CAN_FAIL_AS") if m["id"] == failure_mode_id), None)
            if fm is None:
                raise Invalid("That failure mode isn't on this position.")
            return ("id", fm.get("merged_into") or fm["id"])
        return ("text", text) if text else None

    def _mode_id(self, position_id: str, ref: tuple | None) -> str | None:
        """The id for a checked reference: a mode named in words is the position's
        mode of that name (case and spacing aside), or a new one marked ad hoc."""
        if ref is None:
            return None
        kind, value = ref
        if kind == "id":
            return value
        found = next((fm for fm in self._modes_on(position_id) if _same_text(fm["text"], value)), None)
        if found:
            return found["id"]
        fid = new_id()
        self._emit("failure_mode.added", {"id": fid, "position_id": position_id, "text": value, "function": "",
                                          "failure": "", "consequence": None, "outcome": None,
                                          "rcm_mode_id": None, "study_id": None, "ad_hoc": True})
        return fid

    def _mode_view(self, fm: dict) -> dict:
        return {k: fm.get(k) for k in ("id", "text", "function", "failure", "consequence", "outcome")} | {
            "ad_hoc": bool(fm.get("ad_hoc")), "from_rcm": bool(fm.get("rcm_mode_id")),
        }

    def class_failure_modes(self, position_id: str) -> list[str]:
        """Failure modes recorded at other positions of the same class and not
        on this one: what to offer when something here fails."""
        position = self._get(position_id, "Position")
        cls = (position.get("position_class") or "").strip().lower()
        if not cls:
            return []
        here = {" ".join(fm["text"].lower().split()) for fm in self._modes_on(position_id)}
        found: dict[str, str] = {}
        for p in self.s.nodes(self.org, "Position"):
            if p["id"] == position_id or (p.get("position_class") or "").strip().lower() != cls:
                continue
            for fm in self._modes_on(p["id"]):
                key = " ".join(fm["text"].lower().split())
                if key and key not in here:
                    found.setdefault(key, fm["text"])
        return sorted(found.values(), key=str.lower)[:MAX_LIST]

    def add_failure_mode(self, position_id: str, text, function="", failure="", consequence="") -> dict:
        """A failure mode on a position without an RCM study (how it fails: 'Bearing
        worn', 'Seal leaking'). Failures and tasks can then name it."""
        position = self._get(position_id, "Position")
        if position.get("retired"):
            raise Invalid("That position has been retired.")
        text = _text(text, "failure mode", required=True)
        same = next((fm for fm in self._modes_on(position_id) if _same_text(fm["text"], text)), None)
        if same:
            raise Invalid(f"{same['text']} is already a failure mode here (id {same['id']}).")
        fid = new_id()
        self._emit("failure_mode.added", {
            "id": fid, "position_id": position_id, "text": text, "function": _text(function, "function"),
            "failure": _text(failure, "functional failure"), "consequence": _text(consequence, "consequence") or None,
            "outcome": None, "rcm_mode_id": None, "study_id": None,
        })
        return self._mode_view(self._get(fid, "FailureMode"))

    def _live_mode(self, mode_id: str) -> tuple[dict, dict]:
        fm = self._get(mode_id, "FailureMode")
        if fm.get("merged_into"):
            raise Invalid("That failure mode was merged into another.")
        return fm, self.s.inn(self.org, mode_id, "CAN_FAIL_AS")[0]

    def update_failure_mode(self, mode_id: str, text=None, function=None, failure=None, consequence=None) -> dict:
        """Change a failure mode added by hand or typed in at a failure. Editing an
        ad-hoc mode confirms it as a formal one. (A mode from an RCM study is
        changed in the study.)"""
        fm, position = self._live_mode(mode_id)
        if fm.get("rcm_mode_id"):
            raise Invalid("That failure mode comes from an RCM study: change it in the study, and apply it again.")
        changes = {}
        if text is not None:
            changes["text"] = _text(text, "failure mode", required=True)
            same = next((m for m in self._modes_on(position["id"])
                         if m["id"] != mode_id and _same_text(m["text"], changes["text"])), None)
            if same:
                raise Invalid(f"{same['text']} is already a failure mode here: merge the two instead.")
        if function is not None:
            changes["function"] = _text(function, "function")
        if failure is not None:
            changes["failure"] = _text(failure, "functional failure")
        if consequence is not None:
            changes["consequence"] = _text(consequence, "consequence") or None
        if fm.get("ad_hoc"):
            changes["ad_hoc"] = False
        if changes:
            self._emit("failure_mode.updated", {"id": mode_id, "changes": changes})
        return self._mode_view(self._get(mode_id, "FailureMode"))

    def merge_failure_mode(self, mode_id: str, into_mode_id: str) -> dict:
        """Fold one failure mode into another on the same position: the failures
        recorded against it, findings and tasks move to the other, and it leaves
        the list. To link a mode typed in at a failure to one from an RCM study,
        merge it into the study's mode (apply the study to the position first)."""
        fm, position = self._live_mode(mode_id)
        into, into_position = self._live_mode(into_mode_id)
        if mode_id == into_mode_id:
            raise Invalid("Pick two different failure modes.")
        if position["id"] != into_position["id"]:
            raise Invalid("Both failure modes must be on the same position.")
        if fm.get("rcm_mode_id"):
            raise Invalid(f"{fm['text']} comes from an RCM study, so it stays: merge {into['text']} into it instead.")
        self._emit("failure_mode.merged", {"id": mode_id, "into_id": into_mode_id, "on": date.today().isoformat()})
        return self.position(position["id"])

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
                    if not isinstance(mode, dict) or not mode.get("id"):
                        continue  # a mode not yet saved with an id can't be tracked
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
                    interval = _interval(decision["interval"], unit, f"interval for {str(name)[:80]}")
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
        meter = _task_point(self.s, self.org, task)
        if meter is None:
            return {"limit": f"{interval:g} {unit}", "next_due": None,
                    "note": f"needs a {unit} counter on the position"}
        readings = _readings(self.s, self.org, meter)
        if not readings:
            return {"limit": f"{interval:g} {unit}", "next_due": None, "note": "needs counter readings"}
        start = task.get("last_done_reading")
        if start is None:
            start = _reading_at(readings, base)
        if start is None:
            start = readings[0]["value"]
        target = start + interval
        last, rate = readings[-1], _rate(readings)
        out = {"limit": f"{interval:g} {unit}", "due_at_reading": round(target, 2),
               "counter": {"id": meter["id"], "name": meter["name"], "unit": meter["unit"],
                         "reading": last["value"], "read_on": last["on"],
                         "rate_per_day": rate and round(rate, 3)}}
        if last["value"] >= target:
            crossed = next((r["on"] for r in readings if r["value"] >= target), last["on"])
            return {**out, "next_due": crossed}
        if not rate or rate <= 0:
            return {**out, "next_due": None, "note": "needs two readings to project a date"}
        days = (target - last["value"]) / rate
        try:
            next_due = (date.fromisoformat(last["on"]) + timedelta(days=round(days))).isoformat()
        except (OverflowError, ValueError):
            return {**out, "next_due": None, "note": "too far ahead to put a date on"}
        return {**out, "next_due": next_due}

    def _task_view(self, task: dict) -> dict:
        limits = [self._due_by(task, task["interval"], task["unit"])]
        if task.get("also_interval") and task.get("also_unit"):
            limits.append(self._due_by(task, task["also_interval"], task["also_unit"]))
        dues = [lim["next_due"] for lim in limits if lim["next_due"]]
        nxt = min(dues) if dues else None
        open_wo = next((w for w in self.s.inn(self.org, task["id"], "FOR") if w.get("status") in OPEN_STATUSES), None)
        mode = self.s.out(self.org, task["id"], "MITIGATES")
        return {
            "id": task["id"], "name": task["name"], "outcome": task.get("outcome"),
            "source": task.get("source") or ("rcm" if task.get("rcm_mode_id") else "manual"),
            "reference": task.get("reference", ""), "point_id": task.get("point_id"),
            "failure_mode": {"id": mode[0]["id"], "text": mode[0]["text"]} if mode else None,
            "interval": task["interval"], "unit": task["unit"],
            "also_interval": task.get("also_interval"), "also_unit": task.get("also_unit"),
            "instructions": task.get("instructions", ""), "checklist": task.get("checklist") or [],
            "trade": task.get("trade", ""), "last_done": task.get("last_done"), "last_done_reading": task.get("last_done_reading"),
            "limits": limits, "next_due": nxt, "by_use": not _is_calendar(task["unit"]),
            "overdue": bool(nxt and nxt < date.today().isoformat()),
            "open_work_order": open_wo and {"id": open_wo["id"], "number": open_wo["number"]},
            "proposal": next(({"id": p["id"], "proposed": p.get("proposed"), "kind": p.get("kind")}
                              for p in self.s.inn(self.org, task["id"], "ABOUT")
                              if p["label"] == "Proposal" and p.get("status") == "pending"), None),
        }

    # ---- parts and stock ----------------------------------------------------------

    def create_part(self, part_number, name, manufacturer="", unit="each", unit_cost=None, notes="") -> dict:
        """A part in the catalogue (a bearing, a seal kit, an anode), by part number."""
        number = _text(part_number, "part number", required=True)[:120]
        if any(pt["part_number"].lower() == number.lower() for pt in self.s.nodes(self.org, "Part")):
            raise Invalid(f"Part number {number} is already in the catalogue.")
        pid = new_id()
        self._emit("part.created", {"id": pid, "part_number": number, "name": _text(name, "part's name", required=True)[:200],
                                    "manufacturer": _text(manufacturer, "manufacturer")[:120],
                                    "unit": _text(unit, "unit")[:20] or "each",
                                    "unit_cost": self._amount(unit_cost, "unit cost"), "notes": _text(notes, "notes"),
                                    "on": date.today().isoformat()})
        return self.part(pid)

    def update_part(self, part_id: str, **changes) -> dict:
        self._get(part_id, "Part")
        out = {k: _text(v, k)[:200] for k, v in changes.items()
               if k in ("name", "manufacturer", "unit", "notes") and v is not None}
        if "unit_cost" in changes:
            out["unit_cost"] = self._amount(changes["unit_cost"], "unit cost")
        if out:
            self._emit("part.updated", {"id": part_id, "changes": out})
        return self.part(part_id)

    def supersede_part(self, part_id: str, by_part_id: str) -> dict:
        """The part is replaced by another (a new part number for the same job)."""
        self._get(part_id, "Part")
        self._get(by_part_id, "Part")
        if part_id == by_part_id:
            raise Invalid("A part can't supersede itself.")
        self._emit("part.superseded", {"id": part_id, "by_id": by_part_id})
        return self.part(part_id)

    def mark_interchangeable(self, part_id: str, other_part_id: str) -> dict:
        self._get(part_id, "Part")
        self._get(other_part_id, "Part")
        if part_id == other_part_id:
            raise Invalid("Pick two different parts.")
        self._emit("parts.interchangeable", {"a": part_id, "b": other_part_id})
        return self.part(part_id)

    def adjust_stock(self, part_id: str, location_id: str, delta, reason="", on=None, work_order_id=None) -> dict:
        """Receive (positive) or issue (negative) stock of a part at a location."""
        self._get(part_id, "Part")
        self._get(location_id, "Location")
        delta = _number(delta, "quantity", -MAX_AMOUNT, MAX_AMOUNT)
        if delta == 0:
            raise Invalid("The quantity can't be 0.")
        stock = self.s.node(self.org, stock_id(part_id, location_id))
        if (stock or {}).get("quantity", 0) + delta < 0:
            raise Invalid(f"There are only {(stock or {}).get('quantity', 0):g} in stock there.")
        self._emit("stock.adjusted", {"part_id": part_id, "location_id": location_id, "delta": delta,
                                      "reason": _text(reason, "reason")[:200], "on": _day(on),
                                      "work_order_id": work_order_id})
        return self.part(part_id)

    def set_reorder_point(self, part_id: str, location_id: str, reorder_point) -> dict:
        self._get(part_id, "Part")
        self._get(location_id, "Location")
        self._emit("stock.reorder_set", {"part_id": part_id, "location_id": location_id,
                                         "reorder_point": self._amount(reorder_point, "reorder point"),
                                         "on": date.today().isoformat()})
        return self.part(part_id)

    def _stocks(self, part_id: str) -> list[dict]:
        return [st for st in self.s.inn(self.org, part_id, "OF") if st["label"] == "Stock"]

    def _stock_rows(self, stocks: list[dict]) -> list[dict]:
        """A part's stock by location, by location name."""
        locs = []
        for st in stocks:
            loc = self.s.out(self.org, st["id"], "AT")[0]
            locs.append({"location": {"id": loc["id"], "name": loc["name"]}, "quantity": st["quantity"],
                         "reorder_point": st.get("reorder_point"),
                         "low": st.get("reorder_point") is not None and st["quantity"] <= st["reorder_point"]})
        return sorted(locs, key=lambda x: x["location"]["name"].lower())

    def part(self, part_id: str) -> dict:
        """A catalogue part: its stock by location, use over the last year, what
        supersedes it and what it's interchangeable with, and the positions whose
        parts lists name it (used_at), with critical_short when it's a critical
        spare at one of them and fewer are usable than that position keeps."""
        pt = self._get(part_id, "Part")
        stocks = self._stocks(part_id)
        today = date.fromisoformat(date.today().isoformat())
        year_ago = (today - timedelta(days=365)).isoformat()
        used = sum(-mv["delta"] for st in stocks for mv in st.get("moves") or []
                   if mv["delta"] < 0 and mv["on"] >= year_ago)
        on_hand = sum(st["quantity"] for st in stocks)
        monthly = used / 12 if used else 0
        by = pt.get("superseded_by") and self.s.node(self.org, pt["superseded_by"])
        alike = self.s.out(self.org, part_id, "INTERCHANGEABLE")
        locs = self._stock_rows(stocks)
        used_at, critical_min, critical_short = [], None, False
        for listing in self._listings_of(part_id):
            position = self.s.out(self.org, listing["id"], "LISTED_AT")[0]
            used_at.append({"listing_id": listing["id"], "position": {"id": position["id"], "name": position["name"]},
                            **{k: listing.get(k) for k in ("role", "quantity", "critical", "min_on_hand")}})
            if listing.get("critical"):
                critical_min = max(critical_min or 0, listing.get("min_on_hand") or 0)
                critical_short = critical_short or self._listing_view(listing)["short"]
        return {
            "id": part_id, **{k: pt.get(k) for k in ("part_number", "name", "manufacturer", "unit", "unit_cost", "notes")},
            "superseded_by": by and {"id": by["id"], "part_number": by["part_number"], "name": by["name"]},
            "interchangeable": [{"id": a["id"], "part_number": a["part_number"], "name": a["name"]} for a in alike],
            "stock": locs, "on_hand": on_hand,
            "used_last_year": used, "months_of_cover": round(on_hand / monthly, 1) if monthly else None,
            "low": any(x["low"] for x in locs),
            "used_at": sorted(used_at, key=lambda u: u["position"]["name"].lower()),
            "critical_min": critical_min, "critical_short": critical_short,
        }

    def parts(self) -> list[dict]:
        return [self.part(pt["id"]) for pt in sorted(self.s.nodes(self.org, "Part"),
                                                     key=lambda pt: pt["part_number"].lower())]

    # ---- a position's parts list ------------------------------------------------------
    # Catalogue parts linked to a position (a PartListing: LISTED_AT the position,
    # LISTS the part): the part that replaces what's fitted (role "replacement"),
    # or a component or consumable its maintenance uses (a seal kit, a filter);
    # how many a job takes; whether it's a critical spare, with the least to keep on
    # hand; and compatibility notes. Stock stays the catalogue's. Per position only.

    PART_ROLES = ("replacement", "component", "consumable")

    def _listings_at(self, position_id: str) -> list[dict]:
        return [x for x in self.s.inn(self.org, position_id, "LISTED_AT")
                if x["label"] == "PartListing" and not x.get("removed")]

    def _listings_of(self, part_id: str) -> list[dict]:
        """The live parts-list entries naming a part, at positions still in the plant."""
        out = []
        for x in self.s.inn(self.org, part_id, "LISTS"):
            if x["label"] != "PartListing" or x.get("removed"):
                continue
            position = self.s.out(self.org, x["id"], "LISTED_AT")
            if position and not position[0].get("retired"):
                out.append(x)
        return out

    def _listing(self, listing_id: str) -> dict:
        node = self._get(listing_id, "PartListing")
        if node.get("removed"):
            raise Invalid("That entry was already taken off the parts list.")
        return node

    def _part_role(self, role) -> str:
        role = role or "component"
        if role not in self.PART_ROLES:
            raise Invalid(f"A part's role is one of {', '.join(self.PART_ROLES)}.")
        return role

    @staticmethod
    def _per_job(quantity) -> float:
        qty = _number(1 if quantity in (None, "") else quantity, "quantity per job", 0, MAX_AMOUNT)
        if qty <= 0:
            raise Invalid("The quantity per job must be more than 0.")
        return qty

    def _keep_on_hand(self, critical: bool, min_on_hand, quantity: float):
        """The least to keep on hand: only for a critical spare, enough for one job
        unless said otherwise."""
        if not critical:
            return None
        if min_on_hand in (None, ""):
            return quantity
        return _number(min_on_hand, "minimum on hand", 0, MAX_AMOUNT)

    def _part_brief(self, pt: dict) -> dict:
        rows = self._stock_rows(self._stocks(pt["id"]))
        return {**{k: pt.get(k) for k in ("id", "part_number", "name", "manufacturer", "unit", "unit_cost")},
                "on_hand": sum(r["quantity"] for r in rows),
                "stock": [{"location": r["location"], "quantity": r["quantity"]} for r in rows]}

    def _successors(self, pt: dict) -> list[dict]:
        """What supersedes a part, in order (B supersedes A, then C supersedes B)."""
        out, seen, nxt = [], {pt["id"]}, pt.get("superseded_by")
        while nxt and nxt not in seen:
            node = self.s.node(self.org, nxt, "Part")
            if node is None:
                break
            seen.add(nxt)
            out.append(node)
            nxt = node.get("superseded_by")
        return out

    def _listing_view(self, listing: dict) -> dict:
        """A parts-list entry with its part's stock, what to use instead if the part
        has been superseded, and its interchangeable alternatives. usable_on_hand
        counts the part, its successors and its alternatives in every store; a
        critical spare is short when that's below its minimum."""
        pt = self.s.out(self.org, listing["id"], "LISTS")[0]
        position = self.s.out(self.org, listing["id"], "LISTED_AT")[0]
        chain = self._successors(pt)
        skip = {pt["id"]} | {c["id"] for c in chain}
        alts = {}
        for src in [pt] + chain:
            for a in self.s.out(self.org, src["id"], "INTERCHANGEABLE"):
                if a["id"] not in skip:
                    alts[a["id"]] = a
        brief = self._part_brief(pt)
        successors = [self._part_brief(c) for c in chain]
        alternatives = [self._part_brief(a) for a in sorted(alts.values(), key=lambda a: a["part_number"].lower())]
        usable = brief["on_hand"] + sum(x["on_hand"] for x in successors + alternatives)
        critical = bool(listing.get("critical"))
        minimum = listing.get("min_on_hand") if critical else None
        short = critical and usable < (minimum or 0)
        words = []
        if successors:
            words.append(f"{pt['part_number']} is superseded: use {successors[-1]['part_number']} instead.")
        if critical:
            words.append(f"Critical spare: keep {minimum or 0:g} on hand; {usable:g} usable in stock"
                         + (f", short by {(minimum or 0) - usable:g}." if short else "."))
        return {
            "id": listing["id"], "role": listing["role"], "quantity": listing["quantity"], "critical": critical,
            "min_on_hand": minimum, "notes": listing.get("notes", ""),
            "position": {"id": position["id"], "name": position["name"]},
            "part": brief,
            "superseded_by": successors and {k: successors[0][k] for k in ("id", "part_number", "name")} or None,
            "use_instead": successors[-1] if successors else None, "alternatives": alternatives,
            "usable_on_hand": usable, "short": short, "summary": " ".join(words),
        }

    def _parts_list(self, position_id: str) -> list[dict]:
        """A position's parts list: the replacement first, then components and
        consumables, each by part number."""
        views = [self._listing_view(x) for x in self._listings_at(position_id)]
        return sorted(views, key=lambda v: (self.PART_ROLES.index(v["role"]), v["part"]["part_number"].lower()))

    def position_parts(self, position_id: str) -> dict:
        p = self._get(position_id, "Position")
        return {"position": {"id": p["id"], "name": p["name"]}, "parts_list": self._parts_list(position_id)}

    def add_position_part(self, position_id: str, part_id: str, role="component", quantity=1, critical=False,
                          min_on_hand=None, notes="") -> dict:
        """Put a catalogue part on a position's parts list. role: replacement (the
        part that replaces what's fitted: one per position), component or
        consumable (used in its maintenance)."""
        position = self._get(position_id, "Position")
        if position.get("retired"):
            raise Invalid("That position has been retired.")
        pt = self._get(part_id, "Part")
        role = self._part_role(role)
        listings = self._listings_at(position_id)
        if any(self.s.out(self.org, x["id"], "LISTS")[0]["id"] == part_id for x in listings):
            raise Invalid(f"{pt['part_number']} is already on this position's parts list: change that entry instead.")
        if role == "replacement":
            self._one_replacement(listings)
        if len(listings) >= MAX_PARTS_EACH:
            raise LimitReached(f"A position's parts list holds at most {MAX_PARTS_EACH} parts.")
        self._quota("PartListing", MAX_PART_LISTINGS, what="parts-list entries")
        qty = self._per_job(quantity)
        critical = _flag_value(critical, "critical")
        self._emit("position_part.listed", {
            "id": new_id(), "position_id": position_id, "part_id": part_id, "role": role, "quantity": qty,
            "critical": critical, "min_on_hand": self._keep_on_hand(critical, min_on_hand, qty),
            "notes": _text(notes, "notes"), "on": date.today().isoformat()})
        return self.position_parts(position_id)

    def _one_replacement(self, listings: list[dict], but: str | None = None) -> None:
        for x in listings:
            if x["role"] == "replacement" and x["id"] != but:
                pt = self.s.out(self.org, x["id"], "LISTS")[0]
                raise Invalid(f"{pt['part_number']} is already this position's replacement part. Make it a "
                              "component, or take it off the list, first.")

    def update_position_part(self, listing_id: str, role=None, quantity=None, critical=None, min_on_hand=...,
                             notes=None) -> dict:
        """Change a parts-list entry. min_on_hand: ... leaves it; None goes back to
        one job's worth. Taking the critical flag off drops the minimum."""
        listing = self._listing(listing_id)
        position_id = self.s.out(self.org, listing_id, "LISTED_AT")[0]["id"]
        changes = {}
        if role is not None:
            changes["role"] = self._part_role(role)
            if changes["role"] == "replacement":
                self._one_replacement(self._listings_at(position_id), but=listing_id)
        if quantity is not None:
            changes["quantity"] = self._per_job(quantity)
        if critical is not None:
            changes["critical"] = _flag_value(critical, "critical")
        if notes is not None:
            changes["notes"] = _text(notes, "notes")
        is_critical = changes.get("critical", listing.get("critical", False))
        if not is_critical:
            if listing.get("min_on_hand") is not None:
                changes["min_on_hand"] = None
        elif min_on_hand is not ... or not listing.get("critical"):
            given = None if min_on_hand is ... else min_on_hand
            changes["min_on_hand"] = self._keep_on_hand(True, given, changes.get("quantity", listing["quantity"]))
        changes = {k: v for k, v in changes.items() if v != listing.get(k)}
        if changes:
            self._emit("position_part.updated", {"id": listing_id, "changes": changes})
        return self.position_parts(position_id)

    def remove_position_part(self, listing_id: str) -> dict:
        """Take a part off a position's parts list (the catalogue keeps it)."""
        self._listing(listing_id)
        position_id = self.s.out(self.org, listing_id, "LISTED_AT")[0]["id"]
        self._emit("position_part.removed", {"id": listing_id, "on": date.today().isoformat()})
        return self.position_parts(position_id)

    def _critical_views(self) -> list[dict]:
        """Every critical spare on a parts list at a position still in the plant."""
        out = []
        for listing in self.s.nodes(self.org, "PartListing"):
            if listing.get("removed") or not listing.get("critical"):
                continue
            if self.s.out(self.org, listing["id"], "LISTED_AT")[0].get("retired"):
                continue
            out.append(self._listing_view(listing))
        return sorted(out, key=lambda v: (v["position"]["name"].lower(), v["part"]["part_number"].lower()))

    def critical_spares_short(self) -> list[dict]:
        """Critical spares with fewer usable in stock than their position keeps."""
        return [v for v in self._critical_views() if v["short"]]

    def spares_cover(self, include_unlisted: bool = False) -> dict:
        """Where the spares don't cover the plant: critical spares below their
        minimum (short), positions whose critical replacement part has none usable
        in stock at all (no_spare), and with include_unlisted, positions with no
        parts list (without_parts_list)."""
        views = self._critical_views()
        out = {"short": [v for v in views if v["short"]],
               "no_spare": [v for v in views if v["role"] == "replacement" and v["usable_on_hand"] <= 0]}
        if include_unlisted:
            out["without_parts_list"] = [
                {"id": p["id"], "name": p["name"], "path": [a["name"] for a in self._position_path(p["id"])]}
                for p in sorted(self.s.nodes(self.org, "Position"), key=lambda p: p["name"].lower())
                if not p.get("retired") and not self._listings_at(p["id"])]
        return out

    # ---- measurement points ---------------------------------------------------------

    def add_point(self, position_id: str, name, kind="condition", unit="", source="manual", tag="",
                  alarm_above=None, alarm_below=None) -> dict:
        """Something measured on a position. kind 'counter' counts use (run hours,
        cycles, km: tasks by use go by it); 'condition' shows condition (vibration,
        temperature, wear: alarm limits raise inspections). source 'manual' (someone
        reads it) or 'automated' (a feed sends it, matched by tag)."""
        self._get(position_id, "Position")
        if kind not in POINT_KINDS or source not in POINT_SOURCES:
            raise Invalid("kind is counter or condition; source is manual or automated.")
        tag = _text(tag, "tag")[:200]
        if source == "automated" and not tag:
            raise Invalid("An automated point needs the tag its feed sends readings under.")
        if tag and any(mp.get("tag") == tag for mp in self.s.nodes(self.org, "MeasurementPoint")):
            raise Invalid(f"Tag {tag} is already used by another point.")
        unit = _text(unit, "unit")[:20]
        if kind == "counter":
            unit = _norm_unit(unit)
            if not unit or _is_calendar(unit):
                raise Invalid(f"A counter counts use, e.g. {', '.join(USAGE_UNITS[:4])}.")
        above, below = self._amount_or_none(alarm_above), self._amount_or_none(alarm_below)
        if above is not None and below is not None and below >= above:
            raise Invalid("The low alarm must be below the high alarm.")
        pid = new_id()
        self._emit("point.added", {
            "id": pid, "position_id": position_id, "kind": kind, "source": source, "tag": tag, "unit": unit,
            "name": _text(name, "name") or (f"{unit.capitalize()} counter" if kind == "counter" else "Condition"),
            "alarm_above": above, "alarm_below": below, "on": date.today().isoformat()})
        return self.point(pid)

    def update_point(self, point_id: str, name=None, alarm_above=..., alarm_below=..., tag=None) -> dict:
        point = self._get(point_id, "MeasurementPoint")
        changes = {}
        if name is not None:
            changes["name"] = _text(name, "name", required=True)
        if alarm_above is not ...:
            changes["alarm_above"] = self._amount_or_none(alarm_above)
        if alarm_below is not ...:
            changes["alarm_below"] = self._amount_or_none(alarm_below)
        if tag is not None:
            tag = _text(tag, "tag")[:200]
            if point.get("source") == "automated" and not tag:
                raise Invalid("An automated point needs a tag.")
            if tag and any(mp.get("tag") == tag and mp["id"] != point_id
                           for mp in self.s.nodes(self.org, "MeasurementPoint")):
                raise Invalid(f"Tag {tag} is already used by another point.")
            changes["tag"] = tag
        above = changes.get("alarm_above", point.get("alarm_above"))
        below = changes.get("alarm_below", point.get("alarm_below"))
        if above is not None and below is not None and below >= above:
            raise Invalid("The low alarm must be below the high alarm.")
        if changes:
            self._emit("point.updated", {"id": point_id, "changes": changes})
        return self.point(point_id)

    @staticmethod
    def _amount_or_none(value):
        if value in (None, ""):
            return None
        return _number(value, "alarm limit", -MAX_AMOUNT, MAX_AMOUNT)

    def record_reading(self, point_id: str, value, on=None, note="") -> dict:
        """A manual reading. A counter's only go up. A condition reading past an alarm
        limit opens an inspection (one at a time per point)."""
        point = self._get(point_id, "MeasurementPoint")
        if point.get("source") == "automated":
            raise Invalid(f"{point['name']} is fed automatically (tag {point.get('tag')}); its readings come in "
                          "through the feed.")
        value, day = self._checked_reading(point, value, on)
        self._emit("reading.added", {"id": new_id(), "point_id": point_id, "on": day, "value": value,
                                     "note": _text(note, "note")})
        if point.get("kind") == "condition":
            self._check_alarm(point_id, value, day)
        return self.point(point_id)

    def _checked_reading(self, point: dict, value, on, instead_of: str | None = None) -> tuple[float, str]:
        """A manual reading's value and date, checked: not in the future, and a
        counter's in order with its other readings (leaving out ``instead_of``, the
        reading it would replace)."""
        value = _number(value, "reading", -MAX_AMOUNT, MAX_AMOUNT)
        day = _day(on)
        if day > date.today().isoformat():
            raise Invalid("A reading can't be in the future.")
        if point.get("kind") == "counter":
            if value < 0:
                raise Invalid("A counter can't be negative.")
            readings = [r for r in _manual_readings(self.s, self.org, point["id"]) if r["id"] != instead_of]
            before = [r for r in readings if r["on"] <= day]
            after = [r for r in readings if r["on"] > day]
            if before and value < before[-1]["value"]:
                raise Invalid(f"It's lower than the reading of {before[-1]['value']:g} on {before[-1]['on']}. "
                              "If the counter was replaced, add a new one.")
            if after and value > after[0]["value"]:
                raise Invalid(f"It's higher than the later reading of {after[0]['value']:g} on {after[0]['on']}.")
        return value, day

    def ingest(self, rows) -> dict:
        """Automated readings from a feed: rows of {tag, value, time?}. Each lands in the
        time-series store under its point; a condition point whose latest reading is past
        an alarm limit opens an inspection. Unknown tags are reported, not stored."""
        from backend.maintenance.series import MAX_BATCH, parse_time

        rows = _list(rows, "readings", MAX_BATCH)
        by_tag = {mp["tag"]: mp for mp in self.s.nodes(self.org, "MeasurementPoint")
                  if mp.get("source") == "automated" and mp.get("tag")}
        grouped: dict[str, list] = {}
        unknown: dict[str, int] = {}
        for i, r in enumerate(rows):
            if not isinstance(r, dict):
                raise Invalid(f"Reading {i + 1}: each reading is an object with a tag, a value and a time.")
            tag = str(r.get("tag") or "").strip()[:SHORT_TEXT]
            point = by_tag.get(tag)
            if point is None:
                if len(unknown) < 100 or tag in unknown:
                    unknown[tag] = unknown.get(tag, 0) + 1
                continue
            try:
                value = _number(r.get("value"), "value", -MAX_AMOUNT, MAX_AMOUNT)
                when = parse_time(r.get("time") or r.get("t") or r.get("timestamp"))
            except (TypeError, ValueError) as err:
                raise Invalid(f"Reading {i + 1} ({tag}): {err}") from None
            grouped.setdefault(point["id"], []).append((when, value))
        total = sum(len(pts) for pts in grouped.values())
        if total and self.limited:
            day = date.today().isoformat()
            used = self.s.series_days.get((self.org, day), 0)
            if used + total > MAX_READINGS_PER_DAY:
                raise RateLimited(f"This workspace has stored {used:,} automated readings today; the limit is "
                                  f"{MAX_READINGS_PER_DAY:,} a day.")
            self.s.series_days = {k: v for k, v in self.s.series_days.items() if k[1] == day}
            self.s.series_days[(self.org, day)] = used + total
        stored, alarms = 0, []
        for pid, pts in grouped.items():
            stored += self.s.series.append(self.org, pid, sorted(pts))
            point = self.s.node(self.org, pid)
            if point.get("kind") == "condition":
                latest = self.s.series.latest(self.org, pid)
                wo = self._check_alarm(pid, latest["value"], latest["t"][:10])
                if wo:
                    alarms.append(wo)
        return {"stored": stored, "points": len(grouped), "unknown_tags": unknown, "work_orders_raised": alarms}

    def _check_alarm(self, point_id: str, value: float, day: str) -> dict | None:
        """Past a limit with no alarm work order open: open one. Returns it, if opened."""
        point = self._get(point_id, "MeasurementPoint")
        above, below = point.get("alarm_above"), point.get("alarm_below")
        status = "high" if above is not None and value >= above else "low" if below is not None and value <= below \
            else "ok"
        if status == "ok":
            return None
        if any(w["label"] == "WorkOrder" and w["status"] in OPEN_STATUSES
               for w in self.s.inn(self.org, point_id, "ALARM_FOR")):
            return None
        position = self.s.out(self.org, point_id, "ON")[0]
        limit = above if status == "high" else below
        wid = new_id()
        self._emit("work_order.opened", {
            "id": wid, "number": self._next_number(), "type": "inspection", "position_id": position["id"],
            "title": f"{point['name']} {value:g}{(' ' + point['unit']) if point.get('unit') else ''}: "
                     f"{'above' if status == 'high' else 'below'} the {limit:g} alarm limit",
            "task_id": None, "due": day, "notes": "Raised by a reading past an alarm limit.", "on": day,
            "alarm_point_id": point_id})
        return {"id": wid, "point": point["name"], "position": position["name"]}

    def void_reading(self, reading_id: str, reason) -> dict:
        """Strike out a manual reading entered by mistake, saying why. It stays in the
        point's readings, marked voided; rates, due dates and alarms leave it out."""
        if self._get(reading_id, "Reading").get("voided"):
            raise Invalid("That reading was already struck out.")
        self._emit("reading.voided", {"id": reading_id, "on": date.today().isoformat(),
                                      "reason": _text(reason, "reason", required=True)})
        return self.point(self.s.out(self.org, reading_id, "OF")[0]["id"])

    def correct_reading(self, reading_id: str, value=None, on=None, reason="") -> dict:
        """Correct a manual reading's value, or move it to the date it was really
        read: the original is struck out and the corrected one recorded in its place,
        each linked to the other, with the reason."""
        old = self._get(reading_id, "Reading")
        if old.get("voided"):
            raise Invalid("That reading was struck out; correct the one that replaced it.")
        reason = _text(reason, "reason", required=True)
        point = self._get(self.s.out(self.org, reading_id, "OF")[0]["id"], "MeasurementPoint")
        new_value, day = self._checked_reading(point, old["value"] if value in (None, "") else value,
                                               on or old["on"], instead_of=reading_id)
        if new_value == old["value"] and day == old["on"]:
            raise Invalid("That's the reading as it is: give the right value, the right date, or both.")
        new = new_id()
        self._emit("reading.corrected", {"id": reading_id, "new_id": new, "on": day, "value": new_value,
                                         "reason": reason, "corrected_on": date.today().isoformat()})
        if point.get("kind") == "condition":
            latest = _manual_readings(self.s, self.org, point["id"])[-1]
            if latest["id"] == new:
                self._check_alarm(point["id"], new_value, day)
        return self.point(point["id"])

    def _reading_trail(self, point_id: str, limit: int = 50) -> list[dict]:
        """A manual point's latest readings, newest first, struck-out ones included and
        marked: status 'ok', 'correction' (it replaces another: replaces, reason),
        'voided' (void_reason, voided_on) or 'replaced' (by a correction: replaced_by)."""
        rows = sorted((r for r in self.s.inn(self.org, point_id, "OF") if r["label"] == "Reading"),
                      key=lambda r: (r["on"], r["value"]))[-limit:]
        by_id = {r["id"]: r for r in rows}

        def brief(rid):
            r = by_id.get(rid) or self.s.node(self.org, rid) or {}
            return {"id": rid, "at": r.get("on"), "value": r.get("value")}

        out = []
        for r in reversed(rows):
            entry = {"id": r["id"], "at": r["on"], "value": r["value"], "note": r.get("note", "")}
            if r.get("voided"):
                entry |= {"status": "replaced" if r.get("replaced_by") else "voided",
                          "voided_on": r.get("voided_on"), "void_reason": r.get("voided_reason", "")}
                if r.get("replaced_by"):
                    entry["replaced_by"] = brief(r["replaced_by"])
            elif r.get("replaces"):
                entry |= {"status": "correction", "replaces": brief(r["replaces"]), "reason": r.get("reason", ""),
                          "corrected_on": r.get("corrected_on")}
            else:
                entry["status"] = "ok"
            out.append(entry)
        return out

    def point(self, point_id: str) -> dict:
        """A measurement point: its latest reading and when, the rate (a counter) or the
        trend and projected alarm date (condition), status against its limits, and its
        recent readings (a manual point's with the struck-out and corrected ones, marked)."""
        mp = self._get(point_id, "MeasurementPoint")
        readings = _readings(self.s, self.org, mp)
        last = readings[-1] if readings else None
        if mp.get("source") == "automated":
            latest = self.s.series.latest(self.org, point_id)
            current = latest and {"value": latest["value"], "at": latest["t"]}
            recent = [{"at": r["t"], "value": r["value"]} for r in self.s.series.recent(self.org, point_id, 50)]
        else:
            current = last and {"value": last["value"], "at": last["on"]}
            recent = self._reading_trail(point_id)
        above, below = mp.get("alarm_above"), mp.get("alarm_below")
        status = "ok"
        if current and above is not None and current["value"] >= above:
            status = "high"
        elif current and below is not None and current["value"] <= below:
            status = "low"
        out = {"id": point_id, "name": mp["name"], "kind": mp.get("kind", "counter"), "unit": mp.get("unit", ""),
               "source": mp.get("source", "manual"), "tag": mp.get("tag", ""), "alarm_above": above,
               "alarm_below": below, "reading": current and current["value"], "read_at": current and current["at"],
               "status": status, "readings": recent}
        position = self.s.out(self.org, point_id, "ON")
        out["position"] = position and {"id": position[0]["id"], "name": position[0]["name"]}
        if out["kind"] == "counter":
            rate = _rate(readings)
            out["rate_per_day"] = rate and round(rate, 3)
        else:
            trend = projection = None
            recent_days = readings[-6:]
            if len(recent_days) >= 3:
                xs = [(date.fromisoformat(r["on"]) - date.fromisoformat(recent_days[0]["on"])).days for r in recent_days]
                ys = [r["value"] for r in recent_days]
                n = len(xs)
                mx, my = sum(xs) / n, sum(ys) / n
                sxx = sum((x - mx) ** 2 for x in xs)
                if sxx > 0:
                    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
                    trend = round(slope, 4)
                    target = above if slope > 0 and above is not None else \
                        below if slope < 0 and below is not None else None
                    if status == "ok" and target is not None:
                        days = (target - last["value"]) / slope
                        if 0 < days < 3650:
                            try:
                                projection = (date.fromisoformat(last["on"]) + timedelta(days=round(days))).isoformat()
                            except (OverflowError, ValueError):
                                projection = None
            alarm_wo = next((w for w in self.s.inn(self.org, point_id, "ALARM_FOR")
                             if w["label"] == "WorkOrder" and w["status"] in OPEN_STATUSES), None)
            out |= {"trend_per_day": trend, "projected_alarm": projection,
                    "alarm_work_order": alarm_wo and {"id": alarm_wo["id"], "number": alarm_wo["number"]}}
        return out

    def _renewal_readings(self, position_id: str, day: str) -> dict:
        """Each use-counted task on a position: its counter's reading on ``day``, to record
        with a renewal (a feed's reading can't be read when the event is replayed)."""
        out = {}
        for task in self._tasks_on(position_id):
            point = _task_point(self.s, self.org, task)
            if point and point.get("source") == "automated":
                value = _reading_at(_readings(self.s, self.org, point), day)
                if value is not None:
                    out[task["id"]] = value
        return out

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
                        notes="", trade=None) -> dict:
        """Open a work order. trade: who may do the work ("licensed electrician"); from a
        task, the task's trade unless one is given."""
        self._get(position_id, "Position")
        if type not in WORK_ORDER_TYPES:
            raise Invalid(f"The type is one of {', '.join(WORK_ORDER_TYPES)}.")
        if task_id:
            self._get(task_id, "Task")
        trade = _text(trade, "trade")
        wid = new_id()
        self._emit("work_order.opened", {
            "id": wid, "number": self._next_number(), "title": _text(title, "title", required=True),
            "type": type, "position_id": position_id, "task_id": task_id or None,
            "due": _day(due, "due date") if due else None, "notes": _text(notes, "notes"),
            "on": date.today().isoformat(),
        } | ({"trade": trade} if trade else {}))
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
        item's fitment and start the new one's. An action may name a catalogue
        part used doing it (part_id, quantity, from_location_id: issued from stock
        there): for a replacement with no other item given, the new item is made
        from the part."""
        wo = self._get(work_order_id, "WorkOrder")
        if wo["status"] not in OPEN_STATUSES:
            raise Invalid("This work order is already closed.")
        day = _day(on)
        position_id = self.s.out(self.org, work_order_id, "ON")[0]["id"]
        actions, readings = _dicts(actions, "actions"), _dicts(readings, "readings")
        # Check everything before writing anything.
        plans, issues = [], {}
        per_job = {self.s.out(self.org, x["id"], "LISTS")[0]["id"]: x["quantity"] for x in self._listings_at(position_id)}
        for a in actions:
            kind = a.get("kind")
            if kind not in ACTION_KINDS:
                raise Invalid(f"An action is one of {', '.join(ACTION_KINDS)}.")
            fm = self._mode_ref(position_id, a.get("failure_mode_id") or None, a.get("failure_mode_text"))
            finding = a.get("finding") or None
            if kind == "inspect" and finding not in FINDINGS:
                raise Invalid("An inspection's finding is ok, degraded or found_failed.")
            used = None
            if a.get("part_id"):
                pt = self._get(a["part_id"], "Part")
                qty = self._amount(a.get("quantity") or per_job.get(pt["id"], 1), "quantity", allow_none=False)
                if qty <= 0:
                    raise Invalid("The quantity must be more than 0.")
                if a.get("from_location_id"):
                    self._get(a["from_location_id"], "Location")
                    key = (pt["id"], a["from_location_id"])
                    issues[key] = issues.get(key, 0) + qty
                    held = (self.s.node(self.org, stock_id(*key)) or {}).get("quantity", 0)
                    if issues[key] > held:
                        raise Invalid(f"There are only {held:g} of {pt['part_number']} in stock there.")
                used = (pt, qty, a.get("from_location_id") or None)
                if kind == "replace" and not a.get("item_id"):
                    new_item = a.get("new_item") or {}
                    a = {**a, "new_item": {**new_item, "name": new_item.get("name") or pt["name"],
                                           "part_number": new_item.get("part_number") or pt["part_number"],
                                           "manufacturer": new_item.get("manufacturer") or pt.get("manufacturer", "")}}
            elif a.get("from_location_id"):
                raise Invalid("Stock is issued from the catalogue: give the part_id.")
            if kind == "replace" and not (a.get("item_id") or (a.get("new_item") or {}).get("name")) \
                    and not self.current_fitment(position_id):
                raise Invalid("A replacement needs the item that went in.")
            plans.append((kind, fm, finding, a, used))
        current = self.current_fitment(position_id)
        if current and day < current["from"]:
            raise Invalid("The work can't be done before the fitted item went in.")
        # Meter readings taken during the work go in first, so a task by use
        # records the reading it was done at.
        for r in readings or []:
            self.record_reading(r.get("point_id") or r.get("meter_id"), r.get("value"), day, "read at the work order")

        for kind, ref, finding, a, used in plans:
            # A mode named in words is found, or added, as the action is recorded.
            fm = self._mode_id(position_id, ref)
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
                                               "position_id": position_id, "on": day,
                                               "task_readings": self._renewal_readings(position_id, day)})
            else:
                fitted = self.current_fitment(position_id)
                on_fitment = fitted and fitted["id"]
            self._emit("action.recorded", {
                "id": new_id(), "work_order_id": work_order_id, "kind": kind, "finding": finding,
                "failure_mode_id": fm, "notes": _text(a.get("notes"), "notes"), "on": day,
                "ends": ends, "starts": starts, "on_fitment": on_fitment,
            })
            if used:
                pt, qty, from_location_id = used
                self.add_part_used(work_order_id, part_id=pt["id"], quantity=qty, from_location_id=from_location_id,
                                   note="fitted as the replacement" if kind == "replace" else "")
        self._emit("work_order.closed", {"id": work_order_id, "on": day, "notes": _text(notes, "notes"),
                                         "task_readings": self._renewal_readings(position_id, day)})
        return self.work_order(work_order_id)

    # ---- corrections and edits ------------------------------------------------------
    # Mistakes are fixed with events too, so the history shows what changed.

    ITEM_FIELDS = ("name", "serial", "part_number", "manufacturer", "model", "notes")
    # Structured details, each checked by its function; None (or {}) clears one.
    ITEM_DETAILS = {
        "purchase_date": lambda v: _dated_value(v, "purchase date"),
        "in_service_date": lambda v: _dated_value(v, "in-service date"),
        "manufacture_date": lambda v: _dated_value(v, "manufacture date"),
        "replacement_cost": _cost_value,
        "warranty": _warranty_value,
    }

    def update_item(self, item_id: str, nameplate: dict | None = None, append_note=None, **changes) -> dict:
        """Change an item's details: name, serial, part number, manufacturer, model,
        notes, and nameplate fields (ratings, year, anything on the plate: merged in;
        a field set to "" is removed). ``notes`` replaces the whole note; ``append_note``
        adds a dated line to the end of it. Every version is kept in note_history.
        And its structured details (ITEM_DETAILS): purchase, in-service and manufacture
        dates with their precision and source, replacement cost, warranty; given as
        None, each is cleared."""
        item = self._get(item_id, "Item")
        if changes.get("notes") is not None and str(changes["notes"]).strip() == (item.get("notes") or ""):
            changes.pop("notes")  # unchanged (a form sending everything back)
        out = {k: _text(v, k) for k, v in changes.items() if k in self.ITEM_FIELDS and v is not None}
        for key, check in self.ITEM_DETAILS.items():
            if key in changes:
                value = check(changes[key])
                if value != item.get(key):
                    out[key] = value
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
        appended = self._note_to_append(item if "notes" not in out else {**item, **out}, append_note)
        if out:
            self._emit("item.updated", {"id": item_id, "changes": out, "on": date.today().isoformat()})
        if appended:
            self._emit("note.appended", appended)
        return self.item(item_id)

    def _note_to_append(self, node: dict, text) -> dict | None:
        """The note.appended payload for adding ``text`` as a dated line to a node's
        notes (checked before anything is written), or None with no text."""
        if text is None or not str(text).strip():
            return None
        text = _text(text, "note")
        on = date.today().isoformat()
        if len(node.get("notes") or "") + len(on) + len(text) + 3 > MAX_NOTES:
            raise Invalid(f"The notes would be over {MAX_NOTES:,} characters. Replace them with a shorter "
                          "summary first.")
        return {"id": node["id"], "on": on, "text": text}

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
                                   "position_id": to_position_id, "on": day,
                                   "task_readings": self._renewal_readings(to_position_id, day)})
        return self.item(item_id)

    def void_fitment(self, fitment_id: str, reason="") -> None:
        """Strike out a fitment recorded by mistake: it leaves the life data and the
        position's history (the event log keeps it)."""
        f = self._get(fitment_id, "Fitment")
        if f.get("voided"):
            raise Invalid("That fitment was already struck out.")
        self._emit("fitment.voided", {"id": fitment_id, "on": date.today().isoformat(),
                                      "reason": _text(reason, "reason")})

    def correct_fitment(self, fitment_id: str, start=None, end=None, from_precision=None, to_precision=None) -> dict:
        """Correct the dates an item went in (start) or came out (end), and how well
        each is known (from_precision, to_precision: exact, month, year, estimated).
        A precision on its own re-reads the date already there at that precision."""
        f = self._get(fitment_id, "Fitment")
        changes = {}
        if start or from_precision:
            changes["from"], changes["from_precision"] = dated(start or f["from"], from_precision, "start date")
        if end or to_precision:
            if f.get("to") is None:
                raise Invalid("It's still fitted: remove it, or close a work order, to end it.")
            changes["to"], changes["to_precision"] = dated(end or f["to"], to_precision, "end date")
        new_from, new_to = changes.get("from", f["from"]), changes.get("to", f.get("to"))
        if new_to:
            _check_order(new_from, changes.get("from_precision", f.get("from_precision")),
                         new_to, changes.get("to_precision", f.get("to_precision")))
        if changes:
            self._emit("fitment.corrected", {"id": fitment_id, **changes})
        return self._fitment_view(self._get(fitment_id, "Fitment"))

    def add_past_fitment(self, position_id: str, start, end, reason=None, item_id=None, new_item=None,
                         failure_mode_id=None, failure_mode_text=None, from_precision=None, to_precision=None,
                         note="") -> dict:
        """Put a past fitment into a position's history (migrating an old CMMS's
        records): an item that went in on ``start`` and came out on ``end``, for a
        reason (failure, with its mode by id or in words; planned; other). An
        existing item (item_id) or a new one (new_item). It can sit before the
        current fitment, never across another one, and changes nothing else: the
        current item and the tasks stay as they are. from_precision / to_precision
        say how well each date is known (exact, month, year, estimated)."""
        self._get(position_id, "Position")
        if start in (None, "") or end in (None, ""):
            raise Invalid("A past fitment needs the date it went in (start) and the date it came out (end).")
        start, from_precision = dated(start, from_precision, "start date")
        end, to_precision = dated(end, to_precision, "end date")
        _check_order(start, from_precision, end, to_precision)
        if end > date.today().isoformat():
            raise Invalid("A past fitment has ended: the end date can't be in the future.")
        precisions = {k: v for k, v in (("from_precision", from_precision), ("to_precision", to_precision))
                      if v != "exact"}
        ref = self._mode_ref(position_id, failure_mode_id, failure_mode_text)
        reason = _end_reason(reason, ref)
        clash = self._overlapping(self._fitments_at(position_id), start, end)
        if clash:
            raise Invalid(f"It overlaps {self._fitment_text(clash, 'here')}. Correct or strike out that "
                          "fitment first, or change these dates.")
        if item_id:
            self._get(item_id, "Item")
            clash = self._overlapping(self._fitments_of(item_id), start, end)
            if clash:
                where = self._fitment_view(clash)["position"]
                raise Invalid(f"That item was fitted elsewhere then: "
                              f"{self._fitment_text(clash, 'at ' + (where['name'] if where else 'another position'))}.")
        elif not (new_item or {}).get("name"):
            raise Invalid("Say which item: an existing one (item_id), or a new one with a name.")
        note = _text(note, "note")
        iid = item_id or self.create_item(**{k: new_item.get(k) for k in
                                             ("name", "serial", "part_number", "manufacturer", "notes", "model",
                                              "nameplate")})["id"]
        self._emit("fitment.added", {
            "fitment_id": new_id(), "item_id": iid, "position_id": position_id, "from": start, "to": end,
            "reason": reason, "failure_mode_id": self._mode_id(position_id, ref), "note": note, **precisions,
        })
        return self.position(position_id)

    @staticmethod
    def _overlapping(fitments: list[dict], start: str, end: str) -> dict | None:
        """The first fitment sharing time with start..end (meeting at a day is fine:
        one came out and the next went in that day)."""
        for f in sorted(fitments, key=lambda f: f["from"]):
            if start < (f.get("to") or "9999-12-31") and f["from"] < end:
                return f
        return None

    def _fitment_text(self, f: dict, where: str) -> str:
        item = self._fitment_view(f)["item"] or {}
        name = item.get("name") or "an item"
        serial = f" (serial {item['serial']})" if item.get("serial") else ""
        when = f"from {f['from']} to {f['to']}" if f.get("to") else f"since {f['from']}, still fitted"
        return f"{name}{serial}, fitted {where} {when}"

    def update_work_order(self, work_order_id: str, title=None, due=None, notes=None, type=None,
                          assignee=None, planned_for=None, append_note=None, trade=None) -> dict:
        """Change an open work order. ``notes`` replaces the whole note; ``append_note``
        adds a dated line to the end of it (on any work order, closed or cancelled too).
        Every version is kept in note_history. trade: who may do the work."""
        wo = self._get(work_order_id, "WorkOrder")
        if notes is not None and str(notes).strip() == (wo.get("notes") or ""):
            notes = None  # unchanged (a form sending everything back)
        editing = any(v is not None for v in (title, due, notes, type, assignee, planned_for))
        if editing and wo["status"] not in OPEN_STATUSES:
            raise Invalid("Only an open work order can be changed. A closed or cancelled one can still "
                          "take an appended note.")
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
        if trade is not None:
            changes["trade"] = _text(trade, "trade")
        appended = self._note_to_append({**wo, **changes}, append_note)
        if changes:
            self._emit("work_order.updated", {"id": work_order_id, "changes": changes,
                                              "on": date.today().isoformat()})
        if appended:
            self._emit("note.appended", appended)
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
        except (TypeError, ValueError, OverflowError):
            raise Invalid(f"The {what} must be a number.")
        if value != value:
            raise Invalid(f"The {what} must be a number.")
        if value < 0:
            raise Invalid(f"The {what} can't be negative.")
        if value > MAX_AMOUNT:
            raise Invalid(f"The {what} is at most {MAX_AMOUNT:g}.")
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

    def add_part_used(self, work_order_id: str, part=None, quantity=1, unit_cost=None, part_number="", note="",
                      part_id=None, from_location_id=None) -> dict:
        """A part used on a work order: free text, or a catalogue part (part_id), issued from
        stock at a location (from_location_id) if given."""
        self._open_or_closed(work_order_id)
        qty = self._amount(quantity, "quantity", allow_none=False)
        if qty <= 0:
            raise Invalid("The quantity must be more than 0.")
        if part_id:
            catalogue = self._get(part_id, "Part")
            part = part or catalogue["name"]
            part_number = part_number or catalogue["part_number"]
            if unit_cost in (None, ""):
                unit_cost = catalogue.get("unit_cost")
            if from_location_id:
                self.adjust_stock(part_id, from_location_id, -qty, "used on a work order",
                                  work_order_id=work_order_id)
        elif from_location_id:
            raise Invalid("Stock is issued from the catalogue: give the part_id.")
        self._emit("work_order.part_used", {"id": new_id(), "work_order_id": work_order_id,
                                             "part": _text(part, "part", required=True)[:200],
                                             "part_number": _text(part_number, "part number")[:120],
                                             "quantity": qty, "unit_cost": self._amount(unit_cost, "unit cost"),
                                             "note": _text(note, "note"), "part_id": part_id or None})
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

    def _also_limit(self, also_interval, also_unit, current_unit=None) -> dict:
        """A task's second limit, whichever comes first: {} with none given, both
        None to remove it (0 or less)."""
        if also_interval is None:
            return {}
        try:
            also_number = float(also_interval)
        except (TypeError, ValueError, OverflowError):
            raise Invalid("The second limit must be a number.")
        if also_number <= 0:
            return {"also_interval": None, "also_unit": None}
        unit = _unit(also_unit or current_unit, "months")
        return {"also_unit": unit, "also_interval": _interval(also_number, unit, "second limit")}

    def _counter(self, point_id: str) -> dict:
        point = self._get(point_id, "MeasurementPoint")
        if point.get("kind") != "counter":
            raise Invalid("A task by use goes by a counter, not a condition point.")
        return point

    def _task_link(self, position_id: str, failure_mode_id, task: dict | None = None) -> dict:
        """The changes that link a task to one of its position's failure modes (or
        unlink it: ''). Linked to a mode from an RCM study, the task becomes that
        decision's task, so applying the study again updates it instead of adding
        a second one (unless the decision already has a task here)."""
        if task and task.get("rcm_mode_id") and not task.get("source"):
            raise Invalid("This task comes from an RCM study and stays linked to its decision.")
        out = {"failure_mode_id": None, "rcm_mode_id": None, "study_id": None}
        if not failure_mode_id:
            return out
        ref = self._mode_ref(position_id, failure_mode_id)
        fm = self._get(ref[1], "FailureMode")
        out["failure_mode_id"] = fm["id"]
        if fm.get("rcm_mode_id"):
            taken = any(t.get("rcm_mode_id") == fm["rcm_mode_id"] and t["id"] != (task or {}).get("id")
                        for t in self.s.inn(self.org, position_id, "ON") if t["label"] == "Task")
            if not taken:
                out |= {"rcm_mode_id": fm["rcm_mode_id"], "study_id": fm.get("study_id")}
        return out

    def create_task(self, position_id: str, name, interval, unit="months", outcome=None, also_interval=None,
                    also_unit=None, point_id=None, instructions="", checklist=None, source="manual", reference="",
                    failure_mode_id=None, last_done=None, trade="") -> dict:
        """A scheduled task on a position without an RCM study: from the maker's
        manual (source 'oem'), a law or standard ('statutory'), your own practice
        ('manual') or elsewhere ('other'). It's scheduled, raises work orders and
        renews like a task from RCM. outcome says what kind of task it is (as an RCM
        decision would): fixed_interval (replace or restore: the class's life model
        proposes its interval and plan_economics costs it), failure_finding,
        on_condition, or None for other routine work."""
        position = self._get(position_id, "Position")
        if position.get("retired"):
            raise Invalid("That position has been retired.")
        name = _text(name, "task's name", required=True)
        unit = _unit(unit, "months")
        interval = _interval(interval, unit)
        if outcome in ("", None):
            outcome = None
        elif outcome not in SCHEDULED_OUTCOMES:
            raise Invalid(f"The outcome is one of {', '.join(SCHEDULED_OUTCOMES)}, or none.")
        if source not in TASK_SOURCES:
            raise Invalid(f"The source is one of {', '.join(TASK_SOURCES)}.")
        payload = {"id": new_id(), "position_id": position_id, "name": name, "outcome": outcome,
                   "interval": interval, "unit": unit, "start": date.today().isoformat(),
                   "source": source, "reference": _text(reference, "reference"),
                   "instructions": _text(instructions, "instructions"), "checklist": _checklist(checklist),
                   "trade": _text(trade, "trade")}
        payload |= {k: v for k, v in self._also_limit(also_interval, also_unit).items() if v is not None}
        if point_id:
            point = self._counter(point_id)
            on = self.s.out(self.org, point_id, "ON")
            if not on or on[0]["id"] != position_id:
                raise Invalid("The counter must be on the same position as the task.")
            if _norm_unit(point.get("unit")) not in (unit, payload.get("also_unit")):
                raise Invalid(f"{point['name']} counts {point.get('unit')}, but the task is every "
                              f"{interval:g} {unit}.")
            payload["point_id"] = point_id
        payload |= self._task_link(position_id, failure_mode_id)
        done = None
        if last_done not in (None, ""):
            done = _day(last_done, "last done date")
            if done > date.today().isoformat():
                raise Invalid("Last done can't be in the future.")
        self._quota("Task", MAX_TASKS)
        self._emit("task.added", payload)
        if done:
            self._emit("task.updated", {"id": payload["id"], "changes": {"last_done": done}})
        return self._task_view(self._get(payload["id"], "Task"))

    def update_task(self, task_id: str, name=None, interval=None, unit=None, also_interval=None,
                    also_unit=None, point_id=None, instructions=None, checklist=None, failure_mode_id=None,
                    source=None, reference=None, outcome=..., trade=None) -> dict:
        """Change a task. also_interval / also_unit add a second limit, whichever comes
        first (500 hours or 6 months); also_interval 0 removes it. point_id picks the
        meter a task by use goes by (otherwise the position's meter in its unit).
        failure_mode_id links it to a failure mode on its position ('' unlinks).
        trade: who may do it ("licensed electrician"); its work orders carry it."""
        task = self._get(task_id, "Task")
        if task.get("retired"):
            raise Invalid("That task has been retired.")
        changes = self._also_limit(also_interval, also_unit, task.get("also_unit"))
        if point_id is not None:
            if point_id:
                self._counter(point_id)
            changes["point_id"] = point_id or None
        if instructions is not None:
            changes["instructions"] = _text(instructions, "instructions")[:4000]
        if checklist is not None:
            changes["checklist"] = _checklist(checklist)
        if trade is not None:
            changes["trade"] = _text(trade, "trade")
        if name is not None:
            changes["name"] = _text(name, "task's name", required=True)
        if unit is not None:
            changes["unit"] = _unit(unit, "days")
        if interval is not None:
            changes["interval"] = _interval(interval, changes.get("unit", task["unit"]))
        elif "unit" in changes:
            _interval(task["interval"], changes["unit"])  # the interval must still make sense in the new unit
        if source is not None:
            if source not in TASK_SOURCES:
                raise Invalid(f"The source is one of {', '.join(TASK_SOURCES)}.")
            if task.get("rcm_mode_id") and not task.get("source"):
                raise Invalid("This task comes from an RCM study.")
            changes["source"] = source
        if reference is not None:
            changes["reference"] = _text(reference, "reference")
        if outcome is not ...:
            if outcome not in (None, "") and outcome not in SCHEDULED_OUTCOMES:
                raise Invalid(f"The outcome is one of {', '.join(SCHEDULED_OUTCOMES)}, or none.")
            if task.get("rcm_mode_id"):
                raise Invalid("This task's outcome is its RCM decision's.")
            changes["outcome"] = outcome or None
        if failure_mode_id is not None:
            position = self.s.out(self.org, task_id, "ON")[0]
            linked = self.s.out(self.org, task_id, "MITIGATES")
            if (linked[0]["id"] if linked else "") != (failure_mode_id or ""):
                changes |= self._task_link(position["id"], failure_mode_id, task)
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
        fitted_to = current and self._fitment_view(current)["position"]
        position = fitted_to and self.s.node(self.org, fitted_to["id"])
        cls = (position or {}).get("position_class", "").strip()
        class_cost = cls and (self.s.node(self.org, class_id(self.org, cls)) or {}).get("replacement_cost")
        return {
            **{k: item.get(k, "") for k in self.ITEM_FIELDS}, "id": id, "nameplate": item.get("nameplate") or {},
            "note_history": item.get("note_history") or [],
            "created": item.get("created"), "coordinates": item.get("coordinates"),
            **{k: _dated_view(item.get(k)) for k in ("purchase_date", "in_service_date", "manufacture_date")},
            "replacement_cost": item.get("replacement_cost"),
            "class_replacement_cost": class_cost and {**class_cost, "position_class": cls},
            "warranty": warranty_view(item.get("warranty")),
            "documents": self.documents_of(id),
            "fitted_to": fitted_to,
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
                node = self.s.node(self.org, class_id(self.org, name)) or {}
                entry["costs"] = {k: node.get(k) for k in ("planned_cost", "failure_cost", "availability_target")}
                entry["model"] = node.get("model")
                entry["replacement_cost"] = node.get("replacement_cost")
                entry["documents"] = self.documents_of(class_id(self.org, name))
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
        name = self._class_name(position_class)
        node = self.s.node(self.org, class_id(self.org, name)) or {}
        out = {}
        for key, value in (("planned_cost", planned_cost), ("failure_cost", failure_cost),
                           ("availability_target", availability_target)):
            if value is None or value == "":
                out[key] = node.get(key)
                continue
            out[key] = _number(value, key.replace("_", " "), -MAX_AMOUNT, MAX_AMOUNT)
        if out["planned_cost"] is not None and out["failure_cost"] is not None:
            if out["planned_cost"] < 0 or out["failure_cost"] <= out["planned_cost"]:
                raise Invalid("A failure must cost more than a planned replacement (and neither below 0).")
        if out["availability_target"] is not None and not (0 < out["availability_target"] < 1):
            raise Invalid("The availability target is between 0 and 1, e.g. 0.99.")
        self._emit("class.costs_set", {"id": class_id(self.org, name), "name": name, **out})
        return self.position_class(name)

    def _class_name(self, position_class) -> str:
        """A class some position has (case and spacing aside), or NotFound."""
        name = _text(position_class, "class", required=True)
        if not any((p.get("position_class") or "").strip().lower() == name.lower()
                   for p in self.s.nodes(self.org, "Position")):
            raise NotFound(name)
        return name

    def set_class_replacement_cost(self, position_class: str, replacement_cost) -> dict:
        """What an item doing this class's job costs to replace ({amount, currency,
        source, as_of}): the default for items with no replacement cost of their own.
        None clears it."""
        name = self._class_name(position_class)
        self._emit("class.updated", {"id": class_id(self.org, name), "name": name,
                                     "changes": {"replacement_cost": _cost_value(replacement_cost)}})
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
                "task": {"id": task[0]["id"], "name": task[0]["name"]} if task else None,
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
                "failures": sum(1 for r in rows if r["c"] != 1), "suspensions": sum(1 for r in rows if r["c"] == 1),
                "uncertain": sum(1 for r in rows if "xl" in r)}

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
        members = [self._get(pid, "Position") for pid in dict.fromkeys(_list(member_ids, "positions"))]
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
        add, remove = _list(add, "positions to add"), _list(remove, "positions to remove")
        try:
            new_k = int(k) if k is not None else g["k"]
        except (TypeError, ValueError):
            raise Invalid("k (how many are needed) is a whole number.")
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

    # ---- documents: links to manuals, datasheets, invoices -----------------------------

    def _document_target(self, target_id=None, position_class=None) -> tuple[dict, str]:
        """What a document is for, as the event names it, and its node's id."""
        if bool(target_id) == bool(position_class):
            raise Invalid("Say what the document is for: an item or position (target_id), or a class of "
                          "position (position_class).")
        if position_class:
            name = self._class_name(position_class)
            return {"class_name": name}, class_id(self.org, name)
        node = self.s.node(self.org, str(target_id))
        if node is None or node["label"] not in ("Item", "Position"):
            raise NotFound(target_id)
        return {"target_id": node["id"]}, node["id"]

    def add_document(self, url, title="", kind="other", target_id=None, position_class=None) -> dict:
        """A link to a document (a manual, datasheet, invoice, drawing, certificate) on an
        item, a position, or a class of position. Only http(s) links."""
        from urllib.parse import urlsplit

        ref, node_id = self._document_target(target_id, position_class)
        url = _url(url)
        if kind not in DOCUMENT_KINDS:
            raise Invalid(f"The kind is one of {', '.join(DOCUMENT_KINDS)}.")
        parts = urlsplit(url)
        title = _text(title, "title") or (parts.path.rstrip("/").rsplit("/", 1)[-1] or parts.hostname)[:SHORT_TEXT]
        if len(self.documents_of(node_id)) >= MAX_DOCUMENTS_EACH:
            raise LimitReached(f"At most {MAX_DOCUMENTS_EACH} documents on one item, position or class.")
        if self.limited and sum(1 for d in self.s.nodes(self.org, "Document") if not d.get("removed")) >= MAX_DOCUMENTS:
            raise LimitReached(f"This maintenance workspace can hold at most {MAX_DOCUMENTS:,} documents.")
        did = new_id()
        self._emit("document.added", {"id": did, **ref, "title": title, "url": url, "kind": kind,
                                      "on": date.today().isoformat()})
        return self.document(did)

    def remove_document(self, document_id: str) -> dict:
        if self._get(document_id, "Document").get("removed"):
            raise Invalid("That document was already removed.")
        self._emit("document.removed", {"id": document_id, "on": date.today().isoformat()})
        return {"removed": document_id}

    def document(self, document_id: str) -> dict:
        d = self._get(document_id, "Document")
        of = self.s.out(self.org, document_id, "OF")
        return {k: d.get(k) for k in ("id", "title", "url", "kind", "added_on", "removed")} | {
            "of": of and {"id": of[0]["id"], "kind": of[0]["label"], "name": of[0].get("name")},
        }

    def documents_of(self, node_id: str) -> list[dict]:
        found = [d for d in self.s.inn(self.org, node_id, "OF") if d["label"] == "Document" and not d.get("removed")]
        found.sort(key=lambda d: (DOCUMENT_KINDS.index(d["kind"]), d["title"].lower(), d["id"]))
        return [{k: d.get(k) for k in ("id", "title", "url", "kind", "added_on")} for d in found]

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
        self.check_photo_quota()
        self._emit("photo.added", {
            "id": photo_id, "target_id": target_id, "caption": _text(caption, "caption"),
            "taken_on": cleaned.get("taken_on"), "width": cleaned.get("width"),
            "height": cleaned.get("height"), "via": via, "on": date.today().isoformat(),
        })
        return self.photo(photo_id)

    def check_photo_quota(self) -> None:
        """Refuse another photo when the workspace already holds MAX_PHOTOS."""
        if self.limited:
            kept = sum(1 for p in self.s.nodes(self.org, "Photo") if not p.get("removed"))
            if kept >= MAX_PHOTOS:
                raise LimitReached(f"This maintenance workspace can hold at most {MAX_PHOTOS:,} photos. "
                                   "Remove some first.")

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
        if source not in ("manual", "photo"):
            raise Invalid("The source is manual or photo.")
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
            "from_precision": f.get("from_precision") or "exact",
            "to_precision": (f.get("to_precision") or "exact") if f.get("to") else None,
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
        modes = self._modes_on(id)
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
            "failure_modes": [self._mode_view(m) for m in sorted(modes, key=lambda m: m["text"].lower())],
            "class_failure_modes": self.class_failure_modes(id),
            "tasks": sorted(tasks, key=lambda t: t["next_due"] or "9999"),
            "work_orders": [self._wo_brief(w) for w in wos],
            "life_data": self.life_data(id),
            "coordinates": p.get("coordinates"),
            "measurements": [self.point(mp["id"]) for mp in sorted(
                (x for x in self.s.inn(self.org, id, "ON") if x["label"] == "MeasurementPoint"),
                key=lambda x: (x.get("kind") != "counter", x["name"].lower()))],
            "connections": self.connections(id),
            "groups": self.groups_of(id),
            "rbd_id": p.get("rbd_id"),
            "photos": self.photos_of(id),
            "documents": self.documents_of(id),
            "parts_list": self._parts_list(id),
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

    def _warranty_for(self, position_id: str, on: str) -> dict | None:
        """The warranty of the item fitted to a position on ``on``, if it was in
        warranty then: the item, and the warranty as it stood that day."""
        fitments = sorted(self._fitments_at(position_id), key=lambda f: f["from"])
        for f in fitments:
            if f["from"] <= on and (f.get("to") is None or f["to"] >= on):
                item = self.s.inn(self.org, f["id"], "IN")
                w = item and item[0].get("warranty")
                if w and w["ends_on"] >= on:
                    return {"item": self._item_brief(item[0]), **warranty_view(w, on)}
                return None
        return None

    def _wo_brief(self, w: dict) -> dict:
        position = self.s.out(self.org, w["id"], "ON")
        return {k: w.get(k) for k in ("id", "number", "title", "type", "status", "opened", "due", "closed",
                                      "assignee", "planned_for")} | {
            "trade": w.get("trade", ""),
            "under_warranty": bool(position and self._warranty_for(position[0]["id"], w["opened"])),
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
                "failure_mode": {"id": fm[0]["id"], "text": fm[0]["text"]} if fm else None,
                "removed": self._fitment_view(ended[0])["item"] if ended else None,
                "fitted": self._fitment_view(started[0])["item"] if started else None,
            })
        task = self.s.out(self.org, id, "FOR")
        position = self.position(position_id)
        return {
            **self._wo_brief(w), "notes": w.get("notes", ""), "note_history": w.get("note_history") or [],
            "close_notes": w.get("close_notes", ""), "cancel_reason": w.get("cancel_reason", ""),
            "actions": actions,
            "task": {"id": task[0]["id"], "name": task[0]["name"]} if task else None,
            "fitted": position["fitted"], "failure_modes": position["failure_modes"],
            "class_failure_modes": position["class_failure_modes"],
            "measurements": [{k: mp[k] for k in ("id", "name", "kind", "unit", "reading")}
                             for mp in position["measurements"] if mp["source"] == "manual"],
            "photos": self.photos_of(id),
            "assignee": w.get("assignee", ""), "planned_for": w.get("planned_for"),
            "instructions": w.get("instructions", ""), "checklist": w.get("checklist") or [],
            "status_history": w.get("status_history") or [],
            # The item fitted when it was raised, if under warranty then: a claim may cover it.
            "warranty": self._warranty_for(position_id, w["opened"]),
            # The position's parts list, replacement first: what a replacement or a part used
            # is picked from.
            "suggested_parts": position["parts_list"],
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
        still fitted, censored today). Reliafy's censoring convention.

        A fitment whose start or end is known only roughly (a month, a year, an
        estimate) has a life between ``xl`` and ``xr`` days, the shortest and longest
        the dates allow. A failure then is interval censored (``c`` = 2, ``x`` the
        middle); anything else is censored at the shortest (``x`` = ``xl``), the life
        it surely reached. Exact rows are as they always were."""
        today = date.today().isoformat()
        rows = []
        for f in self._fitments_at(position_id):
            end = f.get("to") or today
            failed = f.get("end_reason") == "failure"
            days = (date.fromisoformat(end) - date.fromisoformat(f["from"])).days
            c, extra = 0 if failed else 1, {}
            from_p, to_p = f.get("from_precision"), f.get("to") and f.get("to_precision")
            if from_p not in (None, "exact") or to_p not in (None, "exact"):
                s_lo, s_hi = date_range(f["from"], from_p)
                e_lo, e_hi = date_range(end, to_p)
                s_hi, e_lo = min(s_hi, e_hi), max(e_lo, s_lo)
                lo = max(0, (e_lo - s_hi).days)
                hi = max(lo, (e_hi - s_lo).days)
                if failed and hi > lo:
                    c, days = 2, round((lo + hi) / 2)
                else:
                    days = lo
                extra = {"xl": lo, "xr": hi, "from_precision": from_p or "exact", "to_precision": to_p or None}
            view = self._fitment_view(f)
            rows.append({
                "fitment_id": f["id"],
                "item": view["item"] and view["item"]["name"], "from": f["from"], "to": f.get("to"),
                "x": days, "c": c,
                "failure_mode": view["failure_mode"] and view["failure_mode"]["text"],
                "status": "failed" if failed else "still fitted" if f.get("to") is None else "removed",
                **extra,
            })
        return sorted(rows, key=lambda r: r["from"])


def summary(m: Maintenance) -> dict:
    """Counts for the home page."""
    return {
        "positions": sum(1 for p in m.s.nodes(m.org, "Position") if not p.get("retired")),
        "locations": len(m.s.nodes(m.org, "Location")),
        "items": len(m.s.nodes(m.org, "Item")),
        "open_work_orders": sum(1 for w in m.s.nodes(m.org, "WorkOrder") if w["status"] in OPEN_STATUSES),
        "low_stock": sum(1 for st in m.s.nodes(m.org, "Stock")
                         if st.get("reorder_point") is not None and st["quantity"] <= st["reorder_point"]),
        "critical_short": len(m.critical_spares_short()),
        "tasks": len(m.s.nodes(m.org, "Task")),
    }



# 2: meters and condition points became measurement points
# 3: nodes and edges keyed by (org, id); position class ids include the org
# 4: cancelling or closing a work order no longer replaces its notes (the reason and
#    closing notes are their own fields); note history; tasks re-read a corrected counter
PROJECTION_VERSION = 4
