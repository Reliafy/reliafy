"""The forecast on a position: the position and everything under it, by calendar period.

The Explorer's Maintenance tab (its Forecast view), ``maintenance get.forecast`` and
``GET /api/maintenance/positions/{id}/forecast`` all read this. In plain words, for
the position and every position inside it (inside the asset opened, ``root``):

* **tasks on dates:** each task's due dates from today to the horizon. Calendar
  tasks by their interval or pattern; tasks by use through the position's
  operating plan (its own or the nearest above, inside the asset) anchored on the
  counter's latest reading, else the counter's recent rate. Each says which.
* **work per period:** how many tasks, their labour hours (the LSA's labour) and
  their planned cost (each task's cost each time).
* **expected failures and their cost per period, with a 90% range** (the 5th to
  95th percentile of outcomes), from the life model in use on each position with
  an item fitted. A life in operating hours is laid on the calendar through the
  same map as the tasks by use; a life in calendar time runs on the calendar.

RePyability computes every number (``repyability.schedule``: ``Task.due``,
``work_by_period``, ``DutyPlan.forecast``, ``failures_by_period``); this module
gathers the records it needs and labels the answers. It assumes each task is done
on its due date (an interval counts again from then; a pattern keeps its dates)
and a failed item is replaced at once with a like one. Expected values add up over
positions; the range of a sum assumes the positions fail independently, and says
so. Nothing is stored, nothing is written as a reading.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import numpy as np
from dateutil.relativedelta import relativedelta

from backend.maintenance import service as svc
from backend.maintenance.service import Invalid, Maintenance

PERIODS = ("month", "quarter", "year")
MAX_MONTHS = 120
MAX_POSITIONS = 500  # positions under the one opened, forecast in one read
MAX_TASKS = 2000
RANGE_LEVEL = 0.90
RANGE_WORDS = "90% range: the 5th to 95th percentile of outcomes"
SAMPLES = 20_000  # draws for the range of a sum over positions (independent positions)
_MONTHS_OF = {"month": 1, "quarter": 3, "year": 12}
_LIB_UNITS = {"hours": "hours", "days": "days", "weeks": "weeks", "years": "years"}


def horizon(today: str, period: str, periods: int) -> tuple[date, date]:
    """From today to the end of the period ``periods`` periods on: the last date included.
    A partial first period (today is the 16th) is counted and the last is whole."""
    start = date.fromisoformat(today)
    months = _MONTHS_OF[period]
    first = start.replace(day=1)
    if period == "quarter":
        first = first.replace(month=(first.month - 1) // 3 * 3 + 1)
    elif period == "year":
        first = first.replace(month=1)
    whole = first + relativedelta(months=months * periods)
    if first == start:
        return start, whole - timedelta(days=1)
    return start, whole + relativedelta(months=months) - timedelta(days=1)


def _check(period, periods) -> tuple[str, int]:
    period = (period or "month").strip().lower()
    if period not in PERIODS:
        raise Invalid(f"The period is one of {', '.join(PERIODS)}.")
    try:
        periods = int(periods if periods not in (None, "") else 12)
    except (TypeError, ValueError):
        raise Invalid("periods must be a whole number.") from None
    if not 1 <= periods or periods * _MONTHS_OF[period] > MAX_MONTHS:
        raise Invalid("Forecast 1 period or more, at most 10 years ahead.")
    return period, periods


def _subtree(m: Maintenance, position_id: str) -> list[tuple[dict, int]]:
    """The position and the live positions inside it, depth first, with their depth."""
    out, stack, seen = [], [(m._get(position_id, "Position"), 0)], set()
    while stack and len(out) < MAX_POSITIONS:
        node, depth = stack.pop()
        if node["id"] in seen:
            continue
        seen.add(node["id"])
        out.append((node, depth))
        kids = [c for c in m.s.inn(m.org, node["id"], "PART_OF") if c["label"] == "Position" and not c.get("retired")]
        stack.extend((c, depth + 1) for c in sorted(kids, key=lambda c: c.get("name", "").lower(), reverse=True))
    return out


def _num(v, digits: int = 4):
    """A number to 4 significant figures (no 15-digit floats on screen)."""
    if v is None:
        return None
    v = float(v)
    if not np.isfinite(v):
        return None
    return float(f"{v:.{digits}g}")


def _money(v):
    return None if v is None else round(float(v), 2)


def _short(day) -> str:
    d = day if isinstance(day, date) else date.fromisoformat(str(day)[:10])
    return f"{d.day} {d.strftime('%b')} {d.year}"


# ---- the map between dates and operating hours, for one position ------------------------------

def _hours_map(m: Maintenance, pos: dict, root, start: date, end_excl: date) -> dict | None:
    """The position's map from dates to operating hours over the horizon: from its operating
    plan (anchored on its hours counter's latest reading, when it has one), else the hours
    counter's recent rate; {usage, basis {kind, text}, counter, reading}. None with neither."""
    from backend.maintenance import schedule

    counter = svc._counter_on(m.s, m.org, pos["id"], "hours")
    readings = svc._readings(m.s, m.org, counter, m.tz) if counter else []
    if counter and readings:
        mapped = m._usage_map(pos["id"], counter, readings, root, start=start.isoformat(),
                              end=end_excl.isoformat())
        if mapped is not None:
            return {"usage": mapped["usage"], "basis": mapped["basis"], "counter": counter, "readings": readings}
    duty = m.duty_of(pos["id"], root)
    if duty is not None:
        usage = duty["plan"].forecast(start, end_excl)
        where = f", from {duty['inherited_from']['name']}" if duty["inherited_from"] else ""
        text = f"Hours from the operating plan ({duty['text']}{where}); no hours counter reading here to anchor it"
        if duty["ended"]:
            text += f"; the plan ended on {_short(duty['ended'])}: nothing runs after it"
        return {"usage": usage, "counter": counter, "readings": readings,
                "basis": {"kind": "plan", "text": text, "plan": duty["text"], "inherited_from": duty["inherited_from"],
                          "ended": duty["ended"], "reading": None}}
    if counter and len(readings) >= 2:
        rate = svc._rate(readings)
        if rate and rate > 0:
            per_day = min(rate, 24.0)
            last = readings[-1]
            usage = schedule.DutyPlan(schedule.Rate(per_day, per="day")).forecast(
                start, end_excl, readings={"hours": float(last["value"])}, read_at=last["on"][:10])
            text = (f"Hours from the recent meter rate ({_num(per_day, 3):g} h a day, from {counter['name']}'s "
                    f"readings; no operating plan here), anchored on {float(last['value']):,.6g} h on "
                    f"{_short(last['on'])}")
            return {"usage": usage, "counter": counter, "readings": readings,
                    "basis": {"kind": "rate", "text": text, "rate_per_day": _num(per_day),
                              "reading": {"value": last["value"], "on": last["on"][:10]}}}
    return None


# ---- tasks on dates ------------------------------------------------------------------------

def _labour_hours(view: dict) -> float | None:
    lines = (view.get("resources") or {}).get("labour") or []
    total = 0.0
    for line in lines:
        try:
            total += float(line.get("people") or 1) * float(line.get("hours") or 0)
        except (TypeError, ValueError):
            continue
    return total or None


def _limit(m: Maintenance, task: dict, interval, unit, rule, hours_map) -> tuple[object | None, str | None]:
    """One limit of a task as the library's: a Recurrence on the calendar, or Usage by the
    position's hours map. (limit, None), or (None, why it can't be put on dates)."""
    from backend.maintenance import how_often, schedule

    norm = svc._norm_unit(unit) or "days"
    if norm in svc.CALENDAR_UNITS:
        if rule:
            return how_often.recurrence(rule, task["start"]), None
        if float(interval).is_integer() and interval >= 1:
            return schedule.Recurrence.every(int(interval), norm, task["start"]), None
        days = round(float(interval) * svc._DAYS_PER[norm])
        return schedule.Recurrence.every(max(1, days), "days", task["start"]), None
    if norm != "hours":
        return None, f"by use in {unit}: only operating hours are put on dates for now"
    if hours_map is None:
        return None, "by use: no operating plan and no hours readings to put it on dates"
    if hours_map["basis"].get("reading") is None:
        return None, "by use: no hours reading here to count from (record the hours counter)"
    return schedule.Usage(float(interval), "hours"), None


def _task_rows(m: Maintenance, pos: dict, hours_map, start: date, end: date) -> tuple[list, list, list]:
    """The position's tasks as the library's Tasks: (rows [(library Task, view, task, basis)],
    not on dates [{task, reason}], the library Tasks)."""
    from backend.maintenance import schedule

    rows, skipped = [], []
    names: set = set()
    for task in sorted(m._tasks_on(pos["id"]), key=lambda t: (t.get("name") or "", t["id"])):
        if svc._on_event_only(task):
            skipped.append({"task": {"id": task["id"], "name": task["name"]}, "reason": "waits for its trigger"})
            continue
        view = m._task_view(task)
        every, why = _limit(m, task, task["interval"], task["unit"], task.get("rule"), hours_map)
        also = None
        if why is None and task.get("also_interval") and task.get("also_unit"):
            also, why = _limit(m, task, task["also_interval"], task["also_unit"], None, hours_map)
        if why:
            skipped.append({"task": {"id": task["id"], "name": task["name"]}, "reason": why})
            continue
        by_use = not svc._is_calendar(task["unit"]) or bool(task.get("also_unit")
                                                           and not svc._is_calendar(task["also_unit"]))
        last_reading = None
        if by_use:
            last_reading = task.get("last_done_reading")
            readings = hours_map["readings"]
            if last_reading is None and readings:
                last_reading = svc._reading_at(readings, task.get("last_done") or task["start"])
            if last_reading is None:
                last_reading = float(readings[0]["value"]) if readings else 0.0
        # As the task view counts it: an interval from when it was last done, else from when it was made;
        # a date it was set to fall due (its start, or rescheduled) comes first, then its limits from there.
        first = svc._first_due(task)
        last_done = first or task.get("last_done") or (None if task.get("rule") else task["start"])
        if last_done and last_done > end.isoformat():
            last_done = None
        cost = (view.get("cost") or {}).get("amount")
        name = task["name"] if task["name"] not in names else f"{task['name']} ({task['id'][:6]})"
        names.add(name)
        lib = schedule.LibraryTask(name, every=every, also=also, last_done=last_done, cost=cost,
                                   duration=_labour_hours(view), last_done_reading=last_reading)
        basis = hours_map["basis"]["text"] if by_use else "On the calendar"
        rows.append((lib, view, task, basis, first if first and first <= end.isoformat() else None, by_use))
    return rows, skipped, [r[0] for r in rows]


# ---- failures from the life models on positions -----------------------------------------------

def _cost_per_failure(m: Maintenance, pos: dict) -> tuple[float | None, str]:
    """What a failure here costs: the position class's failure cost, else its replacement cost."""
    name = (pos.get("position_class") or "").strip()
    if not name:
        return None, "no failure cost set (give the position a class with a failure cost)"
    node = m.s.node(m.org, svc.class_id(m.org, name)) or {}
    if node.get("failure_cost") is not None:
        return float(node["failure_cost"]), f"the {node.get('name') or name} class's failure cost"
    rc = (node.get("replacement_cost") or {}).get("amount")
    if rc is not None:
        return float(rc), f"the {node.get('name') or name} class's replacement cost"
    return None, f"no failure cost set on the {name} class"


def _model_forecast(m: Maintenance, fetch, pos: dict, hours_map, start: date, end_excl: date, period: str):
    """The position's life model in use, forecast by period: (row, None) or (None, reason)."""
    from repyability import NonRepairable

    from backend.maintenance import forecast as class_fc
    from backend.maintenance import schedule
    from backend.services.strategy import StrategyError, _model_from_params

    link = m.in_use_link(pos["id"])
    if link is None:
        return None, None
    brief = {"link_id": link["id"], "name": link.get("name") or "", "model_type": link["model_type"]}
    if link["model_type"] == "rbd":
        return None, {**brief, "reason": "a system diagram (RBD): its blocks' positions are forecast instead"}
    if link["model_type"] != "model":
        return None, {**brief, "reason": "not a non-repairable life model: not laid on dates yet"}
    doc = fetch(link["model_type"], link["model_id"])
    if doc is None:
        return None, {**brief, "reason": "the model can't be opened (deleted, or not shared with you)"}
    r = dict(getattr(doc, "results", None) or {})
    kind = getattr(doc, "kind", "distribution")
    if kind != "distribution" or (r.get("extras") or {}).get("p") is not None:
        return None, {**brief, "reason": "a covariate, joint or limited-failure model: not laid on dates yet"}
    dist_id = r.get("distribution_id") or getattr(doc, "distribution_id", "")
    try:
        dist, label = _model_from_params(dist_id, r.get("params") or [], r.get("extras"))
    except StrategyError as exc:
        return None, {**brief, "reason": f"the model can't be evaluated: {exc}"}
    unit = svc._norm_unit(r.get("unit") or (getattr(doc, "spec", None) or {}).get("unit")) or ""
    fitment = m.current_fitment(pos["id"])
    if fitment is None:
        return None, {**brief, "reason": "nothing fitted here"}
    placeholder = not getattr(doc, "dataset_id", "")
    lib_unit = _LIB_UNITS.get(unit)
    if unit in svc.CALENDAR_UNITS and lib_unit:
        usage = schedule.UsageForecast.calendar(start, end_excl)
        age = class_fc._calendar_age(m, pos["id"], fitment) / svc._DAYS_PER[unit]
        hours_text = "on the calendar (a life in calendar time)"
        age_text = f"{_num(age, 3):g} {unit} since it was fitted on {_short(fitment['from'])}"
    elif unit == "hours":
        if hours_map is None:
            return None, {**brief, "reason": "this life is in operating hours: give the position an operating plan "
                                             "or record its hours counter"}
        use = class_fc._use_age(m, pos["id"], fitment, "hours")
        age = use.get("age")
        if age is None:
            counter_value = None
            if hours_map["readings"]:
                fitted_at = svc._reading_at(hours_map["readings"], fitment["from"])
                counter_value = (float(hours_map["readings"][-1]["value"]) - fitted_at) if fitted_at is not None \
                    else None
            if counter_value is None:
                return None, {**brief, "reason": "its age in operating hours isn't known: record the hours counter "
                                                 "(a reading since the item was fitted)"}
            age = max(0.0, counter_value)
        usage, hours_text = hours_map["usage"], hours_map["basis"]["text"]
        age_text = f"{age:,.0f} h since it was fitted on {_short(fitment['from'])}"
        lib_unit = "hours"
    else:
        counter = svc._counter_on(m.s, m.org, pos["id"], unit) if unit else None
        what = unit or "a unit not given"
        return None, {**brief, "reason": (f"this life is in {what}: only lives in operating hours or calendar time "
                                          "are laid on dates for now" if counter else
                                          f"this life is in {what}: no {what} counter here, and only lives in "
                                          "operating hours or calendar time are laid on dates for now")}
    cost, cost_basis = _cost_per_failure(m, pos)
    part = NonRepairable(dist, unplanned_cost=cost) if cost is not None else NonRepairable(dist)
    try:
        fc = schedule.failures_by_period(part, usage, period, age=float(age), unit=lib_unit)
    except (ValueError, TypeError) as exc:
        return None, {**brief, "reason": f"couldn't be forecast: {exc}"}
    quality = "typed in, not fitted from data" if placeholder else "fitted from data"
    row = {
        **brief, "position": {"id": pos["id"], "name": pos.get("name", "")},
        "distribution": label, "unit": unit, "age": _num(age), "placeholder": placeholder,
        "cost_per_failure": cost, "cost_basis": cost_basis,
        "expected_failures": _num(fc.total["expected_failures"]),
        "probability": _num(fc.total["probability"], 3),
        "failures_range": [fc.total.get("failures_low"), fc.total.get("failures_high")],
        "expected_cost": _money(fc.total.get("expected_cost")),
        "cost_range": [_money(fc.total.get("cost_low")), _money(fc.total.get("cost_high"))],
        "rests_on": f"{label} life ({quality}), {age_text}; {hours_text[0].lower() + hours_text[1:]}"
                    + (f"; each failure at {cost_basis}" if cost is not None else f"; {cost_basis}"),
        "method": fc.method, "notes": list(fc.notes),
    }
    return {"row": row, "fc": fc}, None


def _sum_range(rows: list[dict]) -> tuple[float, float, float, float]:
    """P5 and P95 of the total failures and their cost over positions, assuming the
    positions fail independently: each position's count of failures drawn from its own
    distribution (``failure_probabilities``), at its cost."""
    rng = np.random.default_rng(20261114)
    failures, cost = np.zeros(SAMPLES), np.zeros(SAMPLES)
    for r in rows:
        probs = np.asarray(r["fc"].total.get("failure_probabilities") or [], dtype=float)
        if probs.size == 0:
            continue
        probs = np.clip(probs, 0, None)
        probs = probs / probs.sum()
        draws = rng.choice(probs.size, size=SAMPLES, p=probs)
        failures += draws
        cost += draws * (r["row"]["cost_per_failure"] or 0.0)
    return (float(np.quantile(failures, 0.05, method="inverted_cdf")),
            float(np.quantile(failures, 0.95, method="inverted_cdf")),
            float(np.quantile(cost, 0.05, method="inverted_cdf")), float(np.quantile(cost, 0.95, method="inverted_cdf")))


# ---- the forecast ----------------------------------------------------------------------------

def position_forecast(m: Maintenance, position_id: str, root: str | None = None, period="month", periods=12,
                      fetch=None) -> dict:
    """The forecast for a position and everything under it: see the module docstring.
    ``fetch(model_type, model_id)`` opens a saved model (position_models.fetcher); without
    it, no failures are forecast."""
    from backend.maintenance import schedule

    period, periods = _check(period, periods)
    pos = m._get(position_id, "Position")
    if root:
        scope = m.s.node(m.org, root)
        if scope is None:
            raise svc.NotFound(f"Position {root}")
        if root != position_id and root not in m._ancestor_ids(position_id):
            raise Invalid("That position isn't inside the asset opened.")
    today = m.today()
    start, end = horizon(today, period, periods)
    end_excl = end + timedelta(days=1)
    calendar = schedule.UsageForecast.calendar(start, end_excl).by_period(period)
    starts = [d.date() if isinstance(d, datetime) else d for d in calendar.starts]
    n = len(starts)
    zeros = lambda: np.zeros(n)  # noqa: E731
    count, labour, planned = zeros(), zeros(), zeros()
    fail_exp, fail_cost = zeros(), zeros()
    tasks_out, not_on_dates, models, not_forecast, by_position, states = [], [], [], [], [], []
    due_in: list[list[dict]] = [[] for _ in range(n)]
    no_cost_tasks, no_hours_tasks = set(), set()
    model_rows = []
    tree = _subtree(m, position_id)
    own_map = None
    n_tasks = 0
    for node, depth in tree:
        hours_map = _hours_map(m, node, root, start, end_excl)
        if node["id"] == position_id:
            own_map = hours_map
        rows, skipped, lib_tasks = _task_rows(m, node, hours_map, start, end)
        n_tasks += len(rows)
        if n_tasks > MAX_TASKS:
            raise Invalid(f"More than {MAX_TASKS} tasks under this position: open a smaller branch.")
        for s in skipped:
            not_on_dates.append({**s, "position": {"id": node["id"], "name": node.get("name", "")}})
        mine = {"count": 0, "labour": 0.0, "planned": 0.0, "failures": 0.0, "failure_cost": 0.0}
        if lib_tasks:
            usage = hours_map["usage"] if hours_map else None
            work = schedule.work_by_period(lib_tasks, period, start, end, usage=usage)
            count += np.asarray(work.count, dtype=float)
            labour += np.asarray(work.hours, dtype=float)
            planned += np.asarray(work.cost, dtype=float)
            no_cost_tasks.update((node["id"], t) for t in work.no_cost)
            no_hours_tasks.update((node["id"], t) for t in work.no_hours)
            mine.update(count=int(sum(work.count)), labour=float(sum(work.hours)), planned=float(sum(work.cost)))
            for lib, view, task, basis, first, by_use in rows:
                due = lib.due(start, end, usage=usage)
                done = list(due.done)
                overdue = bool(due.overdue)
                if first:
                    # The date set by hand: done then (at the start, when it's already past), counted here.
                    day = max(date.fromisoformat(first), start)
                    overdue = date.fromisoformat(first) < start
                    done.insert(0, day)
                    idx = max(0, min(n - 1, int(np.searchsorted(np.array(starts), day, side="right")) - 1))
                    count[idx] += 1
                    labour[idx] += lib.duration or 0.0
                    planned[idx] += lib.cost or 0.0
                    mine.update(count=mine["count"] + 1, labour=mine["labour"] + (lib.duration or 0.0),
                                planned=mine["planned"] + (lib.cost or 0.0))
                dates = [d.isoformat() for d in done]
                for k, d in enumerate(done):
                    idx = max(0, min(n - 1, int(np.searchsorted(np.array(starts), d, side="right")) - 1))
                    due_in[idx].append({"task_id": task["id"], "name": task["name"], "date": d.isoformat(),
                                        "position": {"id": node["id"], "name": node.get("name", "")},
                                        "overdue": bool(overdue and k == 0)})
                # The moment the meter reaches each one (by use only: a calendar date has no time).
                moments = [x.strftime("%Y-%m-%dT%H:%M") if x else None for x in (due.moments or ())] if by_use else []
                tasks_out.append({
                    "id": task["id"], "name": task["name"],
                    "position": {"id": node["id"], "name": node.get("name", "")},
                    "how_often": view["limits"][0]["limit"] if view.get("limits") else "",
                    "by_use": by_use, "dates": dates, "moments": moments if any(moments) else [],
                    "limits": list(due.limits),
                    "overdue": overdue, "count": len(done),
                    "cost_each": (view.get("cost") or {}).get("amount"), "labour_each": lib.duration,
                    "next_due": view.get("next_due"), "rests_on": basis, "notes": list(due.notes)})
        if fetch is not None:
            found, why = _model_forecast(m, fetch, node, hours_map, start, end_excl, period)
            if why:
                not_forecast.append({**why, "position": {"id": node["id"], "name": node.get("name", "")}})
            if found:
                fc = found["fc"]
                fail_exp += np.asarray(fc.expected_failures, dtype=float)[:n]
                if fc.expected_cost is not None:
                    fail_cost += np.asarray(fc.expected_cost, dtype=float)[:n]
                model_rows.append(found)
                models.append(found["row"])
                mine["failures"] = float(found["row"]["expected_failures"] or 0)
                mine["failure_cost"] = float(found["row"]["expected_cost"] or 0)
        by_position.append({"position": {"id": node["id"], "name": node.get("name", "")}, "depth": depth,
                            "tasks": mine["count"], "labour_hours": _num(mine["labour"]),
                            "planned_cost": _money(mine["planned"]), "failures": _num(mine["failures"]),
                            "failure_cost": _money(mine["failure_cost"]),
                            "hours_basis": hours_map["basis"]["text"] if hours_map else None})

    # The range: one model, its own (exact) per period; several, the total assuming independence.
    single = model_rows[0]["fc"] if len(model_rows) == 1 else None
    if model_rows:
        if single is not None:
            f_lo, f_hi = single.total.get("failures_low"), single.total.get("failures_high")
            c_lo, c_hi = single.total.get("cost_low"), single.total.get("cost_high")
        else:
            f_lo, f_hi, c_lo, c_hi = _sum_range(model_rows)
    else:
        f_lo = f_hi = c_lo = c_hi = None
    prob_any = None
    if model_rows:
        none = 1.0
        for r in model_rows:
            none *= 1.0 - float(r["fc"].total["probability"])
        prob_any = 1.0 - none
    hours = None
    if own_map is not None:
        got = own_map["usage"].by_period(period).usage.get("hours")
        hours = [float(x) for x in got][:n] if got is not None else None
    rows = []
    for k in range(n):
        p_end = (starts[k + 1] - timedelta(days=1)) if k + 1 < n else end
        row = {"start": starts[k].isoformat(), "end": p_end.isoformat(),
               "hours": _num(hours[k]) if hours and k < len(hours) else None,
               "tasks": int(count[k]), "labour_hours": _num(labour[k]), "planned_cost": _money(planned[k]),
               "failures": _num(fail_exp[k]) if model_rows else None,
               "failure_cost": _money(fail_cost[k]) if model_rows and any(r["row"]["cost_per_failure"] for r in model_rows)
               else None,
               "due": sorted(due_in[k], key=lambda d: (d["date"], d["name"]))}
        if single is not None:
            row["failures_range"] = [_num(single.failures_low[k]) if single.failures_low is not None else None,
                                     _num(single.failures_high[k]) if single.failures_high is not None else None]
            row["cost_range"] = [_money(single.cost_low[k]) if single.cost_low is not None else None,
                                 _money(single.cost_high[k]) if single.cost_high is not None else None]
        rows.append(row)

    total_cost = float(fail_cost.sum()) if model_rows else None
    totals = {"tasks": int(count.sum()), "labour_hours": _num(labour.sum()), "planned_cost": _money(planned.sum()),
              "failures": _num(fail_exp.sum()) if model_rows else None,
              "failures_range": [f_lo, f_hi] if model_rows else None,
              "failure_cost": _money(total_cost) if model_rows and any(r["row"]["cost_per_failure"] for r in model_rows)
              else None,
              "cost_range": [_money(c_lo), _money(c_hi)] if model_rows and c_lo is not None else None,
              "probability": _num(prob_any, 3)}

    # States (plan 4.3): what's missing, said plainly with what to do.
    if not_on_dates and any("no operating plan and no hours readings" in x["reason"] for x in not_on_dates):
        states.append({"kind": "no_plan_no_readings",
                       "text": "Say how this runs (an operating plan), or record an hours reading, to put the tasks "
                               "by use on dates."})
    if own_map and own_map["basis"].get("ended"):
        states.append({"kind": "plan_ended",
                       "text": f"The operating plan ended on {_short(own_map['basis']['ended'])}: nothing runs after "
                               "it, so no hours are added. Give it a new plan if it still runs."})
    for x in not_forecast:
        if x["reason"].startswith("this life is in"):
            states.append({"kind": "unit_not_measured", "text": f"{x['position']['name']}: {x['reason']}."})
    for r in models:
        if r["placeholder"]:
            states.append({"kind": "placeholder",
                           "text": f"{r['position']['name']}: its life model, {r['name']}, was typed in, not fitted "
                                   "from data. Treat its failures as a placeholder until it's fitted."})

    answer = _answer(end, totals, len(not_on_dates))
    words = (f"{len(tree)} position{'s' if len(tree) != 1 else ''} ({pos.get('name', '')} and everything inside "
             "it)" if len(tree) > 1 else pos.get("name", ""))
    notes = ["Each task is assumed done on its due date: an interval counts again from then; a pattern keeps its "
             "own dates.",
             "A failed item is assumed replaced at once with a like one."]
    if len(model_rows) > 1:
        notes.append("Expected failures and costs add up over positions; the total's range assumes the positions "
                     "fail independently. Ranges by period are per position.")
    if no_cost_tasks:
        notes.append(f"{len(no_cost_tasks)} task{'s have' if len(no_cost_tasks) != 1 else ' has'} no cost: the "
                     "planned cost leaves them out.")
    if no_hours_tasks:
        notes.append(f"{len(no_hours_tasks)} task{'s have' if len(no_hours_tasks) != 1 else ' has'} no labour in "
                     "its LSA: the labour hours leave them out.")
    return {
        "position": {"id": pos["id"], "name": pos.get("name", "")}, "root": root, "today": today,
        "period": period, "periods": periods, "start": start.isoformat(), "end": end.isoformat(),
        "covers": words, "answer": answer, "range": RANGE_WORDS, "range_level": RANGE_LEVEL,
        "hours_basis": own_map["basis"]["text"] if own_map else None,
        "hours_source": own_map["basis"]["kind"] if own_map else None,
        "rows": rows, "totals": totals, "tasks": tasks_out, "not_on_dates": not_on_dates,
        "models": models, "not_forecast": not_forecast, "by_position": by_position,
        "states": states, "notes": notes,
        "truncated": len(tree) >= MAX_POSITIONS,
    }


def _answer(end: date, t: dict, left_out: int = 0) -> str:
    """The answer first: "To 30 Nov 2027: 58 tasks, about 46 labour hours, $2,800 planned;
    0.62 failures expected (0 to 1), about $2,990." """
    parts = [f"{t['tasks']} task{'s' if t['tasks'] != 1 else ''}"]
    if t["labour_hours"]:
        parts.append(f"about {t['labour_hours']:,.0f} labour hours")
    if t["planned_cost"]:
        parts.append(f"${t['planned_cost']:,.0f} planned")
    text = f"To {_short(end)}: " + ", ".join(parts)
    if t["failures"] is not None:
        lo, hi = t["failures_range"] or (None, None)
        rng = f" ({lo:g} to {hi:g}, 90% range)" if lo is not None and hi is not None else ""
        text += f"; {t['failures']:.2g} failures expected{rng}"
        if t["failure_cost"] is not None:
            text += f", about ${t['failure_cost']:,.0f}"
    if left_out:
        text += f". {left_out} task{'s' if left_out != 1 else ''} can't be put on dates yet (see Left out)"
    return text + "."
