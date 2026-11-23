"""When a task or a work package is next due, only when that's actually known (Derryn, 23 Nov 2026:
"Next due" is blank when we don't know).

The schedule keeps counting from a task's start (the day it was made) so the plan always has
something to work with, and an hours counter with no duty or readings is assumed to run all day.
Neither is something to show as a fact. These functions read the schedule's own answer (the task
view's limits, a package's next visit) and say what is known:

    {on, at_reading, unit, basis, why, overdue}

``on`` a date (ISO day) or None; ``at_reading`` the counter reading it falls due at (a task or
package by use), with its ``unit``; ``basis`` what the date rests on, in words; ``why`` why it's
blank (or why there's no date beside a reading). Nothing here works out a date of its own.

A date is known when the task has a last-done record, a date it was set to fall due (its start),
or a calendar rule (the first Saturday of every month), or something owed on a date (an open work
order, a return from out of service). A task by use is known at a reading when it has a last-done
record (a date or a reading); the reading gets a date only from a duty or measured readings,
never from running 24 hours a day.
"""

from __future__ import annotations

from backend.maintenance.rcm_decisions import norm_unit

CALENDAR = {"days", "weeks", "months", "years"}
# What a date by use may rest on: the position's operating plan, the meter's measured rate, or
# the readings having reached it already. "continuous" (24 h a day, no duty) is an assumption.
DATED_BASES = {"plan", "rate", "readings"}

NO_RECORD = "No record of when this was last done"
NO_RECORD_USE = "No record of when this was last done, or at what reading"


def _blank(why: str) -> dict:
    return {"on": None, "at_reading": None, "unit": None, "basis": None, "why": why, "overdue": False}


def _calendar(unit) -> bool:
    return norm_unit(unit) in CALENDAR


def _limit_next(task: dict, lim: dict, unit) -> dict:
    """One limit of a task (its interval, or its second interval), known or blank."""
    done = task.get("last_done")
    rule = task.get("rule") if lim is not None and unit == task.get("unit") else None
    if lim.get("note") and not lim.get("next_due") and lim.get("due_at_reading") is None:
        return _blank(lim["note"][0].upper() + lim["note"][1:])
    if _calendar(unit):
        first = lim.get("first_due") or task.get("first_due")
        pattern = rule and rule.get("kind") not in (None, "every", "shutdowns")
        if not (done or first or pattern):
            return _blank(NO_RECORD)
        if not lim.get("next_due"):
            return _blank(NO_RECORD)
        basis = ("Set to fall due on this date" if first and not done
                 else f"On its pattern: {lim['limit']}" if pattern and not done
                 else f"{lim['limit']} after it was last done")
        return {"on": lim["next_due"], "at_reading": None, "unit": None, "basis": basis, "why": None, "overdue": False}
    # By use: from the reading it was last done at.
    if not done and task.get("last_done_reading") is None:
        return _blank(NO_RECORD_USE)
    target = lim.get("due_at_reading")
    if target is None:
        return _blank(NO_RECORD_USE)
    counter_unit = (lim.get("counter") or {}).get("unit") or unit
    basis = lim.get("basis") or {}
    if lim.get("next_due") and basis.get("kind") in DATED_BASES:
        return {"on": lim["next_due"], "at_reading": target, "unit": counter_unit, "basis": basis.get("text"),
                "why": None, "overdue": False}
    why = ("No duty or measured readings on the position to put a date on it"
           if basis.get("kind") == "continuous" else (lim.get("note") or "No date: it goes by its counter"))
    return {"on": None, "at_reading": target, "unit": counter_unit, "basis": None, "why": why[0].upper() + why[1:],
            "overdue": False}


def task_next(task: dict, view: dict, today: str, overdue_shown: bool = True) -> dict:
    """A task's next due, known or blank (``view``: the task view, its limits and next_due worked
    out). ``overdue_shown``: False when work management is off (a plan is never late)."""
    if view.get("on_event") and not view.get("open_work_order"):
        return _blank("Raised by an event, not on a date")
    wo = view.get("open_work_order")
    if wo and wo.get("due"):
        out = {"on": wo["due"], "at_reading": None, "unit": None,
               "basis": f"Owed on work order #{wo['number']}", "why": None}
        return {**out, "overdue": bool(view.get("overdue")) and overdue_shown}
    held = view.get("out_of_service")
    if held:
        if held.get("until"):
            return {"on": held["until"], "at_reading": None, "unit": None,
                    "basis": f"Out of service until then{': ' + held['reason'] if held.get('reason') else ''}",
                    "why": None, "overdue": False}
        return _blank("Out of service, with no return date")
    if view.get("overdue_before_package"):
        carried = view["overdue_before_package"]
        return {"on": carried["due"], "at_reading": None, "unit": None,
                "basis": "Overdue from before it joined its package", "why": None, "overdue": overdue_shown}
    if view.get("due_by") == "package" and view.get("package"):
        pkg = view["package"]
        name = pkg.get("name") or "its package"
        if view.get("held") and not view.get("next_due"):
            return _blank(f"{name} is paused, with no return date")
        if view.get("next_due") is None and view.get("due_at_reading") is None:
            return _blank(f"{name} has no visit to come")
        on = view.get("next_due") if pkg.get("dated", True) else None
        out = {"on": on, "at_reading": view.get("due_at_reading"), "unit": "hours" if view.get("due_at_reading") is not None else None,
               "basis": f"On a visit of {name}" if on else None,
               "why": None if on else f"On a visit of {name}: no duty or measured readings to put a date on it"}
        return {**out, "overdue": bool(on and view.get("overdue")) and overdue_shown}
    units = [task.get("unit"), task.get("also_unit")]
    found = [_limit_next(task, lim, units[i] if i < len(units) else None) for i, lim in enumerate(view.get("limits") or [])]
    dated = [x for x in found if x["on"]]
    if dated:
        best = min(dated, key=lambda x: x["on"])
    else:
        best = next((x for x in found if x["at_reading"] is not None), None) or (found[0] if found else _blank(NO_RECORD))
    return {**best, "overdue": bool(best["on"] and best["on"] < today) and overdue_shown}


def package_next(pkg_out: dict, basis_kind: str | None = None) -> dict:
    """A package's next visit, known or blank (``pkg_out``: the package as listed, its next_visit
    worked out; ``basis_kind``: what a package by hours dates its visits from). A package's visits
    run from the date it was set to start, so a calendar package's next visit is known."""
    status = pkg_out.get("status")
    if status == "retired":
        return _blank("Retired")
    wo = pkg_out.get("open_work_order")
    if wo and wo.get("visit_on"):
        return {"on": wo["visit_on"], "at_reading": None, "unit": None,
                "basis": f"The visit on work order #{wo['number']}", "why": None, "overdue": bool(wo.get("late"))}
    if status == "paused":
        pause = pkg_out.get("pause") or {}
        return _blank(f"Paused{' until ' + pause['until'] if pause.get('until') else ', with no return date'}")
    nxt = pkg_out.get("next_visit")
    hours = (pkg_out.get("cadence") or {}).get("unit") == "hours"
    if hours:
        reading = pkg_out.get("next_visit_hours")
        if reading is None:
            return _blank("No visit to come")
        if nxt and basis_kind in DATED_BASES:
            return {"on": nxt, "at_reading": reading, "unit": "hours", "basis": "Its next visit", "why": None, "overdue": False}
        return {"on": None, "at_reading": reading, "unit": "hours", "basis": None,
                "why": "No duty or measured readings on the position to put a date on it", "overdue": False}
    if not nxt:
        return _blank("No visit to come")
    return {"on": nxt, "at_reading": None, "unit": None, "basis": "Its next visit", "why": None, "overdue": False}
