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

PERIODS = ("day", "week", "month", "quarter", "year")
MAX_MONTHS = 120
CONTINUOUS_NOTE = svc.CONTINUOUS_TEXT
MAX_ROWS = 400  # periods in one read (a year by day; ten years by week is too many)
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
    if period == "day":
        return start, start + timedelta(days=periods - 1)
    if period == "week":
        # Monday to Sunday: a week begun counts, then ``periods`` whole weeks (none begun: just those).
        monday = start - timedelta(days=start.weekday())
        weeks = periods if monday == start else periods + 1
        return start, monday + timedelta(days=7 * weeks - 1)
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
    days = {"day": 1, "week": 7}.get(period)
    too_far = periods * days > MAX_MONTHS * 366 // 12 if days else periods * _MONTHS_OF[period] > MAX_MONTHS
    if not 1 <= periods or too_far or periods > MAX_ROWS:
        raise Invalid("Forecast 1 period or more, at most 10 years ahead.")
    return period, periods


def _until(start: date, end) -> date:
    """A horizon's last day, given (``end``, an ISO date): from today, at most 10 years on."""
    try:
        last = date.fromisoformat(str(end)[:10])
    except ValueError:
        raise Invalid("end is a date, such as 2027-11-30.") from None
    if last < start:
        raise Invalid(f"The horizon ends before it starts: end on {_short(start)} or later.")
    if last > start + relativedelta(months=MAX_MONTHS):
        raise Invalid("Forecast at most 10 years ahead.")
    return last


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

def _hours_map(m: Maintenance, pos: dict, root, start: date, end_excl: date, strict: bool = False) -> dict | None:
    """The position's map from dates to operating hours over the horizon: from its operating
    plan (anchored on its hours counter's latest reading, when it has one), else the hours
    counter's recent rate; {usage, basis {kind, text}, counter, reading}. None with neither.
    ``strict`` (the forecast details): with neither, running all the time, 24 h a day (Derryn,
    21 and 23 Nov 2026: duty, then the readings' rate, then 24 h a day), anchored on the latest
    hours reading, else 0 h today; basis kind "continuous" says it's assumed. The same maps as a
    task's next due (service.meter_usage), so the two agree."""
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
    # No duty: the readings' rate, else (strict) running all the time, on the maps next due uses.
    last = readings[-1] if readings else None
    rate = svc._rate(readings) if counter and len(readings) >= 2 else None
    if rate and rate > 0:
        per_day = min(rate, 24.0)
        usage = svc.meter_usage(start, end_excl, last, per_day)
        text = f"{svc.rate_text(per_day)}, anchored on {float(last['value']):,.6g} h on {_short(last['on'])}"
        return {"usage": usage, "counter": counter, "readings": readings,
                "basis": {"kind": "rate", "text": text, "rate_per_day": _num(per_day),
                          "reading": {"value": last["value"], "on": last["on"][:10]}}}
    if strict:
        usage = svc.meter_usage(start, end_excl, last)
        value = float(last["value"]) if last else 0.0
        anchor = (f", from {value:,.6g} h on {_short(last['on'])}" if last else ", counted from 0 h today (no hours reading)")
        return {"usage": usage, "counter": counter, "readings": readings,
                "basis": {"kind": "continuous", "reading": {"value": value, "on": last["on"][:10] if last else start.isoformat()},
                          "text": f"{CONTINUOUS_NOTE}{anchor}"}}
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
        if rule and rule["kind"] == "shutdowns":
            # Due its interval after it was last done; done at the next shutdown (visits, _lib_task).
            return schedule.Recurrence.every(int(rule["every"]), rule["unit"], task["start"]), None
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


def _lib_task(m: Maintenance, task: dict, hours_map, end: date, name: str | None = None, hours_only: bool = False):
    """One task as the library's Task: ((lib, view, basis, first, by_use), None), or (None, why it
    can't be put on dates). ``hours_only`` (by operating hours with no duty): a calendar limit
    beside a limit by use is left out, as nothing turns it into hours."""
    from backend.maintenance import schedule

    view = m._task_view(task)
    every, why = _limit(m, task, task["interval"], task["unit"], task.get("rule"), hours_map)
    also = None
    if hours_only and task.get("also_unit") and svc._is_calendar(task["also_unit"]):
        pass
    elif why is None and task.get("also_interval") and task.get("also_unit"):
        also, why = _limit(m, task, task["also_interval"], task["also_unit"], None, hours_map)
    if why:
        return None, why
    visits = None
    if (task.get("rule") or {}).get("kind") == "shutdowns":
        from backend.maintenance.shutdowns import shutdown_dates

        subject = svc._subject(m.s, m.org, task)
        shuts = shutdown_dates(m, subject["id"], m.today(), end.isoformat()) if subject else []
        if not shuts:
            return None, "at shutdowns: no planned shutdown here in the forecast"
        visits = schedule.Recurrence.on([x["on"] for x in shuts])
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
    on_pattern = bool(task.get("rule")) and task["rule"]["kind"] != "shutdowns"
    last_done = first or task.get("last_done") or (None if on_pattern else task["start"])
    if last_done and last_done > end.isoformat():
        last_done = None
    cost = (view.get("cost") or {}).get("amount")
    lib = schedule.LibraryTask(name or task["name"], every=every, also=also, last_done=last_done, cost=cost,
                               duration=_labour_hours(view), last_done_reading=last_reading, visits=visits)
    basis = hours_map["basis"]["text"] if by_use else "At planned shutdowns" if visits else "On the calendar"
    return (lib, view, basis, first if first and first <= end.isoformat() else None, by_use), None


def _task_rows(m: Maintenance, pos: dict, hours_map, start: date, end: date,
               only: set | None = None, hours_only: bool = False) -> tuple[list, list, list]:
    """The position's tasks as the library's Tasks: (rows [(library Task, view, task, basis)],
    not on dates [{task, reason}], the library Tasks). ``only``: just these task ids."""
    rows, skipped = [], []
    names: set = set()
    for task in sorted(m._tasks_on(pos["id"]), key=lambda t: (t.get("name") or "", t["id"])):
        if only is not None and task["id"] not in only:
            continue
        if (task.get("trigger") or {}).get("kind") in ("failure", "found"):
            continue  # a failure mode's response: counted on its failure lines (forecast_lines.py)
        if svc._on_event_only(task):
            skipped.append({"task": {"id": task["id"], "name": task["name"]}, "reason": "waits for its trigger"})
            continue
        name = task["name"] if task["name"] not in names else f"{task['name']} ({task['id'][:6]})"
        found, why = _lib_task(m, task, hours_map, end, name, hours_only=hours_only)
        if why:
            skipped.append({"task": {"id": task["id"], "name": task["name"]}, "reason": why})
            continue
        names.add(name)
        lib, view, basis, first, by_use = found
        rows.append((lib, view, task, basis, first, by_use))
    return rows, skipped, [r[0] for r in rows]


# ---- failures from the life models on positions -----------------------------------------------

def _cost_per_failure(m: Maintenance, pos: dict, mode_ids=None) -> tuple[float | None, str, dict]:
    """What a failure here costs, all in (repair plus downtime at its cost an hour), by the one rule
    (failure_costs.py: each figure the failure mode's own, else the position class's; a life for
    several modes the costliest): (per failure or None, where it comes from in words, the figures)."""
    c = m.failure_consequence(pos, mode_ids)
    return c["per_failure"], c["text"], c


def _lives_on(m: Maintenance, pos: dict) -> tuple[list[tuple[dict, list | None]], list[dict]]:
    """The lives forecast on a position: [(link view, the failure-mode ids it's for, or None for
    every failure of the position)], and the links left out ({link brief, reason}).

    A position's links that name failure modes of their own (a life for each mode) are
    forecast, one each, the modes failing independently; the position's whole-life model in
    use is then left out, so no failure is counted twice. Otherwise the model in use is."""
    views = m.position_models(pos["id"])
    own, covered, skipped = [], set(), []
    for v in reversed(views):  # the latest first
        # A degradation model on a failure mode: its time to the limit is that mode's life.
        if v.get("model_type") not in ("model", "degradation_model"):
            continue
        ids = [x["id"] for x in v.get("failure_modes") or [] if not x.get("gone")]
        if not ids:
            continue
        fresh = [i for i in ids if i not in covered]
        if not fresh:
            skipped.append({"link_id": v["id"], "name": v.get("name") or "", "model_type": v["model_type"],
                            "reason": "a later life on this position covers the same failure modes"})
            continue
        covered.update(fresh)
        own.append((v, fresh))
    if own:
        used = next((v for v in views if v.get("in_use")), None)
        if used and not any(v["id"] == used["id"] for v, _ in own) and used.get("model_type") == "model":
            skipped.append({"link_id": used["id"], "name": used.get("name") or "", "model_type": used["model_type"],
                            "reason": "left out: this position's failure modes have lives of their own, "
                                      "forecast instead (so no failure is counted twice)"})
        return list(reversed(own)), skipped
    link = m.in_use_link(pos["id"])
    return ([(link, None)] if link else []), skipped


def _lives_served(m: Maintenance, pos: dict, lives, served: set):
    """The lives a task's (or package's) forecast counts: a life for failure modes, those the tasks
    serve (just those modes); the position's whole life, when they serve any mode on it."""
    out = []
    for link, mode_ids in lives:
        if mode_ids is None:
            mine = [fm["id"] for fm in m._modes_on(pos["id"]) if fm["id"] in served]
            if mine:
                out.append((link, None))
        else:
            mine = [i for i in mode_ids if i in served]
            if mine:
                out.append((link, mine))
    return out


def _mode_tasks(m: Maintenance, pos: dict, mode_ids) -> list[dict]:
    """The live tasks serving the failure modes (``mode_ids``, None: every mode on the
    position), each with its outcome in the mode's decision and the evidence behind it:
    [{task, outcome, evidence, mode}]."""
    modes = m._modes_on(pos["id"]) if mode_ids is None else [
        fm for fm in (m.s.node(m.org, i) for i in mode_ids)
        if fm and not fm.get("retired") and not fm.get("merged_into")]
    out = []
    for fm in modes:
        members = {o.get("task_id"): o for o in fm.get("outcomes") or [] if o.get("task_id")}
        for task in m.s.inn(m.org, fm["id"], "MITIGATES"):
            if task.get("label") != "Task" or task.get("retired"):
                continue
            member = members.get(task["id"]) or {}
            outcome = member.get("outcome") or fm.get("outcome") or task.get("outcome")
            evidence = member.get("evidence") or fm.get("evidence")
            out.append({"task": task, "outcome": outcome, "evidence": evidence, "mode": fm})
    return sorted(out, key=lambda x: (x["task"].get("name") or "", x["task"]["id"], x["mode"]["id"]))


def _in_life_unit(value, unit, life_unit: str):
    """``value`` ``unit`` in the life's unit, when both are operating hours or both calendar
    time; None otherwise (they meet only through a duty, not counted here yet)."""
    task_unit = svc._norm_unit(unit) or "days"
    if task_unit == "hours" and life_unit == "hours":
        return float(value)
    if task_unit in svc.CALENDAR_UNITS and life_unit in svc.CALENDAR_UNITS:
        return float(value) * svc._DAYS_PER[task_unit] / svc._DAYS_PER[life_unit]
    return None


def _pf_of(fetch, evidence) -> tuple[float, str, float] | None:
    """The P-F interval an on-condition task's evidence gives (a saved P-F calculation):
    (P-F, its unit, the chance a check finds the warning), or None."""
    if not evidence or evidence.get("type") != "strategy_analysis" or fetch is None:
        return None
    doc = fetch("strategy_analysis", evidence.get("id"))
    if doc is None or getattr(doc, "kind", "") != "on_condition_interval":
        return None
    inputs = dict(getattr(doc, "inputs", None) or {})
    try:
        pf = float(inputs.get("pf_interval"))
    except (TypeError, ValueError):
        return None
    try:
        p = float(inputs.get("detection_probability") or 1.0)
    except (TypeError, ValueError):
        p = 1.0
    if not pf > 0 or not 0 < p <= 1:
        return None
    return pf, svc._norm_unit(inputs.get("pf_unit")) or "days", p


def _task_effects(m: Maintenance, fetch, pos: dict, mode_ids, life_unit: str, usage, hours_map, start: date,
                  end: date) -> dict:
    """What the maintenance tasks do to a life (the RCM decisions of the modes it's for):
    {every, since_renewal, miss, credited [{task, effect}], not_credited [{task, reason}]}.

    * a fixed-interval task that leaves the item as new (the default) is a planned
      replacement at its interval (block replacement: done on its dates, failures or not);
      one that restores nothing (restores 0%) leaves the failures as they are; a partial
      restoration isn't counted yet;
    * an on-condition check with a P-F interval (its saved P-F calculation) finds the warning
      with RePyability's ``on_condition`` detection probability; the failures left are those
      it misses. With no P-F interval linked the check isn't counted;
    * failure-finding tests, redesigns and run to failure leave the failures as they are."""
    from repyability import on_condition

    credited, not_credited = [], []
    renew: list[tuple[float, dict]] = []
    miss = 1.0
    seen = set()
    for x in _mode_tasks(m, pos, mode_ids):
        task, outcome = x["task"], x["outcome"]
        key = (task["id"], outcome)
        if key in seen:
            continue
        seen.add(key)
        brief = {"id": task["id"], "name": task.get("name") or ""}
        if svc._on_event_only(task) or not task.get("interval"):
            continue
        if task.get("support"):
            # A supporting task keeps the item on its life (supporting.py): the life model already
            # assumes it, so it changes no failure while done as planned (forecast-rules 4.1).
            from backend.maintenance import supporting

            not_credited.append({"task": brief, "support": True,
                                 "reason": "it supports this life (keeps it on its life): the life model already "
                                           "assumes it, so the failures are as the model gives ("
                                           + supporting.impact_words(task["support"].get("impact")) + ")"})
            continue
        if outcome == "fixed_interval":
            from backend.maintenance import restoration as rs

            r = (task.get("restorations") or {}).get(x["mode"]["id"]) or task.get("restoration")
            assumed = False
            if r is None:
                r = rs.default_for(task)
                assumed = r is not None
            if r and r.get("kind") != "as_new":
                q = float(r.get("q") or 0.0)
                if q >= 1 - 1e-9:
                    why = ("it restores none of the item's age" + (" (assumed from its name: say what it leaves the "
                                                                    "item as if it does more)" if assumed else "")
                           + ", so the failures are as they would be without it")
                    not_credited.append({"task": brief, "reason": why, "fix": "effect"})
                else:
                    not_credited.append({"task": brief, "reason": "a partial restoration isn't counted in the "
                                                                  "forecast yet: its failures are as without it",
                                         "fix": "effect"})
                continue
            every = _in_life_unit(task["interval"], task["unit"], life_unit)
            if every is None:
                not_credited.append({"task": brief, "reason": f"its interval is in {task['unit']} and the life in "
                                                              f"{life_unit}: not counted in the forecast yet"})
                continue
            renew.append((every, task))
        elif outcome == "on_condition":
            pf = _pf_of(fetch, x["evidence"])
            if pf is None:
                not_credited.append({"task": brief, "reason": "no P-F interval linked (a saved P-F calculation as "
                                                              "its evidence), so the check isn't counted",
                                     "fix": "pf", "mode": {"id": x["mode"]["id"], "text": x["mode"].get("text") or ""}})
                continue
            tau = _in_life_unit(task["interval"], task["unit"], life_unit)
            pf_life = _in_life_unit(pf[0], pf[1], life_unit)
            if tau is None or pf_life is None:
                not_credited.append({"task": brief, "reason": f"its interval or P-F interval isn't in {life_unit}, "
                                                              "the life's unit: not counted in the forecast yet"})
                continue
            found = float(on_condition(pf_life, tau, onset_rate=1.0, detection_probability=pf[2])
                          .detection_probability)
            miss *= 1.0 - found
            credited.append({"task": brief, "effect": (
                f"a check every {_num(tau, 4):g} {life_unit} against a P-F interval of {_num(pf_life, 4):g} "
                f"{life_unit} finds {found:.0%} of warnings in time")})
        elif outcome == "failure_finding":
            not_credited.append({"task": brief, "reason": "a failure-finding test: it finds hidden failures, which "
                                                          "this forecast doesn't count yet"})
        else:
            not_credited.append({"task": brief, "reason": "it has no modelled effect on failures (not a replacement "
                                                          "or a check in its RCM decision)", "fix": "effect"})
    every = since = None
    if renew:
        every, task = min(renew, key=lambda r: r[0])
        for other_every, other in renew:
            if other is not task:
                not_credited.append({"task": {"id": other["id"], "name": other.get("name") or ""},
                                     "reason": "another replacement on these failure modes comes sooner"})
        # How far into its interval it is now: from the first date it falls due.
        found, why = _lib_task(m, task, hours_map, end)
        first_at = None
        if found is not None:
            lib, _view, _basis, first, by_use = found
            due = lib.due(start, end, usage=usage if by_use else None)
            if first:
                first_at = datetime.combine(max(date.fromisoformat(first), start), datetime.min.time())
            elif by_use and due.moments and due.moments[0] is not None:
                first_at = due.moments[0]
            elif due.done:
                first_at = datetime.combine(due.done[0], datetime.min.time())
        if first_at is None:
            # Not due before the horizon's end: no replacement inside it.
            not_credited.append({"task": {"id": task["id"], "name": task.get("name") or ""},
                                 "reason": "not due before the forecast ends"})
            every = None
        else:
            to_first = float(np.atleast_1d(usage.model_time([first_at], unit=_LIB_UNITS[life_unit]))[0])
            since = min(max(0.0, every - max(0.0, to_first)), every * (1 - 1e-9))
            credited.insert(0, {"task": {"id": task["id"], "name": task.get("name") or ""},
                                "effect": f"a planned replacement every {_num(every, 4):g} {life_unit}"})
    return {"every": every, "since_renewal": since, "miss": miss, "credited": credited,
            "not_credited": not_credited}


class _Credited:
    """A forecast with on-condition checks counted: the library's failures thinned by the share
    of warnings the checks miss (expected values only; no ranges or chances, which the library
    doesn't give for checks yet)."""

    def __init__(self, fc, miss: float):
        self.base = fc  # the failures if nothing found them (forecast_lines splits found and missed)
        self.miss = miss
        self.method = fc.method
        self.notes = fc.notes
        self.expected_failures = np.asarray(fc.expected_failures, dtype=float) * miss
        self.expected_cost = None if fc.expected_cost is None else np.asarray(fc.expected_cost, dtype=float) * miss
        self.failures_low = self.failures_high = self.cost_low = self.cost_high = None
        cost = fc.total.get("expected_cost")
        self.total = {"expected_failures": float(fc.total["expected_failures"]) * miss,
                      "expected_cost": None if cost is None else float(cost) * miss,
                      "probability": None}


def _model_forecast(m: Maintenance, fetch, pos: dict, hours_map, start: date, end_excl: date, period: str,
                    link: dict | None = ..., mode_ids=None, windows=None):
    """A life on the position (``link``; by default the model in use), forecast by period with
    the tasks of the failure modes it's for (``mode_ids``; None: all the position's) counted:
    (found, None) or (None, reason). ``windows(life_unit, usage)``: forecast in these windows
    instead of calendar periods (the forecast details by operating hours): their ends in the
    life's unit from now, or a reason they can't be had."""
    from repyability import NonRepairable

    from backend.maintenance import forecast as class_fc
    from backend.maintenance import schedule
    from backend.services.strategy import StrategyError, _model_from_params

    if link is ...:
        link = m.in_use_link(pos["id"])
    if link is None:
        return None, None
    brief = {"link_id": link["id"], "name": link.get("name") or "", "model_type": link["model_type"]}
    if mode_ids:
        brief["failure_modes"] = [{"id": i, "text": (m.s.node(m.org, i) or {}).get("text", "")} for i in mode_ids]
    if link["model_type"] == "rbd":
        return None, {**brief, "reason": "a system diagram (RBD): its blocks' positions are forecast instead"}
    limit = link["model_type"] == "degradation_model"
    if link["model_type"] != "model" and not (limit and mode_ids):
        return None, {**brief, "reason": "not a non-repairable life model: not laid on dates yet" if not limit else
                      "a degradation model counts for the failure modes it's linked for: link it to a failure mode"}
    doc = fetch(link["model_type"], link["model_id"])
    if doc is None:
        return None, {**brief, "reason": "the model can't be opened (deleted, or not shared with you)"}
    r = dict(getattr(doc, "results", None) or {})
    if limit:
        # Its time to the limit (the fitted distribution of when each path crosses it): a crossing is
        # the mode's failure, charged its failure cost (task_optimise.life_of reads the same).
        life = r.get("life_model") or {}
        if not life.get("distribution_id"):
            return None, {**brief, "reason": "this degradation model has no time-to-limit distribution yet: refit it"}
        r = {**r, "distribution_id": life["distribution_id"], "params": life.get("params") or [], "extras": None}
    kind = "distribution" if limit else getattr(doc, "kind", "distribution")
    if kind != "distribution" or (r.get("extras") or {}).get("p") is not None:
        return None, {**brief, "reason": "a covariate, joint or limited-failure model: not laid on dates yet"}
    dist_id = r.get("distribution_id") or getattr(doc, "distribution_id", "")
    try:
        dist, label = _model_from_params(dist_id, r.get("params") or [], r.get("extras"))
    except StrategyError as exc:
        return None, {**brief, "reason": f"the model can't be evaluated: {exc}"}
    if limit:
        thr = r.get("threshold")
        mu = f" {r['measurement_unit']}" if r.get("measurement_unit") else ""
        label = f"time to the limit ({_num(thr, 4):g}{mu}), {label}" if thr is not None else f"time to the limit, {label}"
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
            # No plan and no counter rate: it runs all the time, 24 h a day (running_clock; Derryn, 21 Nov 2026).
            hours_map = {"usage": schedule.DutyPlan(schedule.Continuous()).forecast(start, end_excl), "counter": None,
                         "readings": [],
                         "basis": {"kind": "continuous", "reading": None,
                                   "text": "Hours assuming it runs all the time (no duty set for this position)"}}
        use = class_fc._use_age(m, pos["id"], fitment, "hours")
        age = use.get("age")
        if age is None:
            counter_value = None
            readings = hours_map["readings"]
            if not readings:
                # No counter here: the one above it (a deck spindle's hours are its mower's).
                above = m._use_counter(pos["id"], "hours")
                readings = svc._readings(m.s, m.org, above, m.tz) if above else []
            if readings:
                fitted_at = svc._reading_at(readings, fitment["from"])
                counter_value = (float(readings[-1]["value"]) - fitted_at) if fitted_at is not None else None
            if counter_value is None:
                return None, {**brief, "reason": "its age in operating hours isn't known: record the hours counter "
                                                 "(a reading since the item was fitted)"}
            age = max(0.0, counter_value)
        usage, hours_text = hours_map["usage"], hours_map["basis"]["text"]
        age_text = f"{age:,.0f} h since it was fitted on {_short(fitment['from'])}"
        lib_unit = "hours"
    else:
        from backend.services import running_clock

        if unit and running_clock.is_use(unit):
            why = running_clock.refusal(unit, "days", running_clock.for_position(m, pos["id"]))
            if why:
                return None, {**brief, "reason": why}
            # The duty gives a rate in it, but RePyability lays lives on dates in operating time only.
            return None, {**brief, "reason": (f"this life is in {unit}: its duty gives {unit} a day, but lives are "
                                              "laid on dates in operating hours or calendar time only for now")}
        counter = svc._counter_on(m.s, m.org, pos["id"], unit) if unit else None
        what = unit or "a unit not given"
        return None, {**brief, "reason": (f"this life is in {what}: only lives in operating hours or calendar time "
                                          "are laid on dates for now" if counter else
                                          f"this life is in {what}: no {what} counter here, and only lives in "
                                          "operating hours or calendar time are laid on dates for now")}
    cost, cost_basis, consequence = _cost_per_failure(m, pos, mode_ids)
    end = end_excl - timedelta(days=1)
    effects = _task_effects(m, fetch, pos, mode_ids, unit, usage, hours_map, start, end)
    policy = {}
    if effects["every"] is not None:
        # A planned replacement's own cost is the task's, counted with the tasks: none here.
        # With no failure cost set, a nominal one (the library needs it; the costs are dropped after).
        part = NonRepairable(dist, unplanned_cost=cost if cost else 1.0, planned_cost=0.0)
        policy = {"every": effects["every"], "resets": False, "since_renewal": effects["since_renewal"]}
    else:
        # With no failure cost set, a nominal one, so the count still comes with its distribution and
        # range (the costs are dropped after, _NoCost): a gap in the cost never loses the failures' range.
        part = NonRepairable(dist, unplanned_cost=cost if cost is not None else 1.0)
    try:
        if windows is not None:
            ends = windows(lib_unit, usage)
            if isinstance(ends, str):
                return None, {**brief, "reason": ends}
            fc = by_windows(part, ends, float(age), policy)
        else:
            fc = schedule.failures_by_period(part, usage, period, age=float(age), unit=lib_unit, **policy)
    except (ValueError, TypeError, NotImplementedError) as exc:
        return None, {**brief, "reason": f"couldn't be forecast: {exc}"}
    if cost is None:
        fc = _NoCost(fc)
    if effects["miss"] < 1.0:
        fc = _Credited(fc, effects["miss"])
    quality = "typed in, not fitted from data" if placeholder else "fitted from data"
    total = fc.total
    tasks_words = "; ".join(f"{c['task']['name']}: {c['effect']}" for c in effects["credited"])
    row = {
        **brief, "position": {"id": pos["id"], "name": pos.get("name", "")},
        "distribution": label, "unit": unit, "age": _num(age), "placeholder": placeholder,
        "cost_per_failure": cost, "cost_basis": cost_basis,
        "failure_cost_each": consequence["failure_cost"], "downtime_hours_each": consequence["downtime_hours"],
        "downtime_rate": consequence["downtime_rate"], "response": consequence.get("response"),
        "response_mode": (consequence.get("mode") or {}).get("id"),
        "expected_downtime_hours": _num(total["expected_failures"] * consequence["downtime_hours"])
        if consequence["downtime_hours"] else None,
        "expected_failures": _num(total["expected_failures"]),
        "probability": _num(total["probability"], 3) if total.get("probability") is not None else None,
        "failures_range": [total.get("failures_low"), total.get("failures_high")],
        "expected_cost": _money(total.get("expected_cost")),
        "cost_range": [_money(total.get("cost_low")), _money(total.get("cost_high"))],
        "rests_on": f"{label} life ({quality}), {age_text}; {hours_text[0].lower() + hours_text[1:]}"
                    + (f"; each failure costs {cost_basis}" if cost is not None else f"; {cost_basis}")
                    + (f"; with the maintenance: {tasks_words}" if tasks_words else "; run to failure")
                    + "".join(f"; not counted: {x['task']['name']} ({x['reason']})" for x in effects["not_credited"]),
        "tasks_counted": effects["credited"], "tasks_not_counted": effects["not_credited"],
        "found_share": _num(1.0 - effects["miss"], 6) if effects["miss"] < 1.0 else None,
        "method": fc.method, "notes": list(fc.notes) + (
            ["The checks' share of warnings missed is applied to the expected failures and cost; no range is "
             "given for them yet."] if effects["miss"] < 1.0 else []),
    }
    return {"row": row, "fc": fc}, None


def _count_at(counts, probabilities, q: float) -> float:
    """The smallest count whose chance of that many or fewer reaches ``q`` (a percentile of a count)."""
    cum = np.cumsum(np.asarray(probabilities, dtype=float))
    at = int(np.searchsorted(cum, q / 100.0 - 1e-12))
    return float(counts[min(at, len(counts) - 1)])


class _Windows:
    """A life forecast over windows in operating time (not calendar periods), the shape the rows
    read from ``failures_by_period``."""

    def __init__(self, **kw):
        self.__dict__.update(kw)


def by_windows(part, ends, age: float, policy: dict) -> _Windows:
    """A part's expected failures, cost and their 90% range (the 5th to 95th percentile) in each of
    a run of windows from now, ``ends`` in the life's unit: RePyability's
    ``NonRepairable.cost_by_window`` (or, run to failure with no cost, its exact ``failures``).
    What ``schedule.failures_by_period`` does for calendar periods, for windows of running hours."""
    ends = np.maximum.accumulate(np.asarray(ends, dtype=float))
    n = len(ends)
    has_cost = getattr(part, "cu", None) is not None
    found = None
    try:
        found = part.cost_by_window(ends, policy.get("every"), resets=policy.get("resets"), age=age,
                                    since_renewal=policy.get("since_renewal"), levels=(5.0, 95.0))
    except (ValueError, NotImplementedError):
        if policy.get("every") is not None:
            raise
    if found is not None:
        ws = list(found.windows)
        expected = np.array([float(w.expected_failures) for w in ws])
        cost = np.array([float(w.mean) for w in ws])
        low = np.array([float(w.percentiles[0]) for w in ws])
        high = np.array([float(w.percentiles[1]) for w in ws])
        f_low = np.array([_count_at(np.arange(len(w.failure_probabilities)), w.failure_probabilities, 5.0) for w in ws])
        f_high = np.array([_count_at(np.arange(len(w.failure_probabilities)), w.failure_probabilities, 95.0) for w in ws])
        whole = found.total
        probs = [float(p) for p in whole.failure_probabilities]
        counts = np.arange(len(probs))
        total = {"expected_failures": float(whole.expected_failures), "expected_cost": float(whole.mean),
                 "cost_low": float(whole.percentiles[0]), "cost_high": float(whole.percentiles[1]),
                 "failures_low": _count_at(counts, probs, 5.0), "failures_high": _count_at(counts, probs, 95.0),
                 "failure_probabilities": probs, "probability": 1.0 - probs[0] if probs else 0.0}
        return _Windows(method="numerical", notes=(), expected_failures=expected,
                        expected_cost=cost if has_cost else None, cost_low=low if has_cost else None,
                        cost_high=high if has_cost else None, failures_low=f_low, failures_high=f_high, total=total)
    got = part.failures(ends, age=age)
    cumulative = np.asarray(got.expected_failures, dtype=float)
    expected = np.diff(cumulative, prepend=0.0)
    total = {"expected_failures": float(cumulative[-1]) if n else 0.0,
             "expected_cost": float(cumulative[-1] * part.cu) if has_cost and n else None,
             "probability": float(np.asarray(got.probability, dtype=float)[-1]) if n else 0.0}
    return _Windows(method="exact", notes=("No ranges: the part has no cost the windows can be worked out with.",),
                    expected_failures=expected, expected_cost=expected * part.cu if has_cost else None,
                    cost_low=None, cost_high=None, failures_low=None, failures_high=None, total=total)


class _NoCost:
    """A forecast run with a policy at no failure cost (the library needs one): its costs dropped."""

    def __init__(self, fc):
        self.method, self.notes = fc.method, fc.notes
        self.expected_failures = fc.expected_failures
        self.expected_cost = None
        self.failures_low, self.failures_high = fc.failures_low, fc.failures_high
        self.cost_low = self.cost_high = None
        self.total = {k: v for k, v in fc.total.items() if k not in ("expected_cost", "cost_low", "cost_high")}


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


# ---- planned cost by kind, and what's missing --------------------------------------------------

def _split_each(view: dict) -> tuple[float, float]:
    """One doing of a task, its cost by kind: (labour, parts and consumables), from its LSA lines
    (labour at the trade rates; spares at their unit cost; consumables). A typed cost is what's
    charged: the LSA's parts are taken from it first, then its labour; what the LSA doesn't price is
    the rest of the planned cost ("other")."""
    cost = view.get("cost") or {}
    lsa = cost.get("lsa") or {}
    lab = float(lsa.get("labour_cost") or 0.0)
    mat = float(lsa.get("materials_cost") or 0.0)
    amount = cost.get("amount")
    if amount is None:
        return 0.0, 0.0
    if cost.get("source") == "typed":
        mat = min(mat, float(amount))
        lab = min(lab, float(amount) - mat)
    return lab, mat


def _planned_split(planned, lab, mat, visits=0.0) -> dict:
    planned, lab, mat, visits = float(planned), float(lab), float(mat), float(visits)
    return {"labour_cost": _money(lab), "materials_cost": _money(mat), "visits_cost": _money(visits),
            "other_planned_cost": _money(max(0.0, planned - lab - mat - visits))}


def _visits(m: Maintenance, tasks_out: list[dict], starts: list, n: int) -> tuple[np.ndarray, np.ndarray]:
    """Each visit's cost besides its tasks (visit_costs.py), by period: (cost, count). A package's
    visit_cost at each time one of its tasks falls due; a task in no package with a visit_cost, each
    time it does. Tasks due on the same position at the same time (or the same day, on the
    calendar) are one visit, charged the largest visit cost among them once."""
    visits = visit_list(m, tasks_out)
    cost_arr, count_arr = np.zeros(n), np.zeros(n)
    day_starts = np.array(starts)
    for cost, day in visits.values():
        idx = max(0, min(n - 1, int(np.searchsorted(day_starts, date.fromisoformat(day), side="right")) - 1))
        cost_arr[idx] += cost
        count_arr[idx] += 1
    return cost_arr, count_arr


def visit_list(m: Maintenance, tasks_out: list[dict]) -> dict:
    """The visits with a cost of their own: {(position id, moment or day): (cost, day)} (see _visits)."""
    index = m._package_index()
    visits: dict = {}
    for t in tasks_out:
        entry = index.get(t["id"])
        if entry:
            cost = 0.0 if not entry["active"] else max(float(entry["root"].get("visit_cost") or 0),
                                                       float(entry["package"].get("visit_cost") or 0))
        else:
            cost = float((m.s.node(m.org, t["id"]) or {}).get("visit_cost") or 0)
        if not cost:
            continue
        keys = t["moments"] if len(t["moments"]) == len(t["dates"]) else t["dates"]
        for key, day in zip(keys, t["dates"]):
            k = (t["position"]["id"], key or day)
            visits[k] = (max(cost, visits.get(k, (0.0, day))[0]), day)
    return visits


def _cost_basis_words(t: dict, unpriced: list[dict]) -> dict:
    """What each cost rests on, in words, for the screen and the tool."""
    planned = ("Planned: each task's cost each time × the times it falls due. Labour is its LSA's labour at the "
               "trade rates, parts and consumables its LSA's lines; each visit's call-out and setup (the package's visit "
               "cost, once a visit); a typed cost the LSA doesn't explain is \"other\".")
    unplanned = ("Unplanned: expected failures × what a failure costs (its repair, plus its downtime × the cost of "
                 "an hour down), each figure the failure mode's own, else its position class's.")
    if unpriced:
        names = ", ".join(sorted({f"{r['position']['name']}: {r['name']}" for r in unpriced}))
        unplanned += f" Not costed (no failure cost set): {names}."
    return {"planned": planned, "unplanned": unplanned}


def _explorer_link(position_id: str, root, tab: str, sel: str | None = None, **extra) -> str:
    from urllib.parse import urlencode

    q = {"arrange": "positions", **({"root": root} if root else {}), "sel": sel or position_id, "tab": tab, **extra}
    return "/asset-register/explorer?" + urlencode(q)


def _prompts(m: Maintenance, fetch, tree, tasks_out: list[dict], models: list[dict], root) -> dict:
    """What to enter for the forecast to count more (plan step 1, Nov 2026), each with a link to
    where it's entered: tasks with no modelled effect on failures, failure modes with no failure
    cost, and on-condition checks with no P-F interval."""
    counted_ids: set = set()
    why: dict = {}
    for r in models:
        for c in r.get("tasks_counted") or []:
            counted_ids.add(c["task"]["id"])
        for c in r.get("tasks_not_counted") or []:
            why.setdefault(c["task"]["id"], c)
    lives_for: set = set()
    for r in models:
        if r.get("failure_modes"):
            lives_for.update(x["id"] for x in r["failure_modes"])
        else:
            lives_for.update(fm["id"] for fm in m._modes_on(r["position"]["id"]))
    no_effect, seen = [], set()
    for t in tasks_out:
        if t["id"] in counted_ids or t["id"] in seen or why.get(t["id"], {}).get("support"):
            continue
        seen.add(t["id"])
        serves = [fm for fm in m.s.out(m.org, t["id"], "MITIGATES") if not fm.get("retired")]
        if t["id"] in why:
            reason = why[t["id"]]["reason"]
        elif not serves:
            reason = "it serves no failure mode, so no failure here changes with it"
        elif not any(fm["id"] in lives_for for fm in serves):
            reason = "its failure modes have no life model in this forecast"
        else:
            reason = "it has no modelled effect on failures"
        link_tab, extra = ("models", {}) if reason.startswith("its failure modes have no life") else (
            "maintenance", {"mtask": t["id"]})
        no_effect.append({"task": {"id": t["id"], "name": t["name"]}, "position": t["position"], "reason": reason,
                          "link": _explorer_link(t["position"]["id"], root, link_tab, **extra)})
    no_cost, no_pf, pf_seen = [], [], set()
    for node, _depth in tree:
        here = {"id": node["id"], "name": node.get("name", "")}
        for fm in m._modes_on(node["id"]):
            c = m.failure_consequence(node, [fm["id"]])
            if c["per_failure"] is None:
                no_cost.append({"mode": {"id": fm["id"], "text": fm.get("text") or ""}, "position": here,
                                "counted": fm["id"] in lives_for,
                                "link": _explorer_link(node["id"], root, "rcm", sel=fm["id"], fm=fm["id"],
                                                       respond="failure")})
        if fetch is None:
            continue
        for x in _mode_tasks(m, node, None):
            task = x["task"]
            if x["outcome"] != "on_condition" or task["id"] in pf_seen or svc._on_event_only(task):
                continue
            if _pf_of(fetch, x["evidence"]) is None:
                pf_seen.add(task["id"])
                no_pf.append({"task": {"id": task["id"], "name": task.get("name") or ""},
                              "mode": {"id": x["mode"]["id"], "text": x["mode"].get("text") or ""}, "position": here,
                              "link": _explorer_link(node["id"], root, "rcm", sel=x["mode"]["id"], fm=x["mode"]["id"])})
    for r in models:
        if r["cost_per_failure"] is None and not r.get("failure_modes") and not m._modes_on(r["position"]["id"]):
            # A life for every failure of a position with no failure modes: its class's cost, or a mode of its own.
            no_cost.append({"mode": None, "life": r["name"], "position": r["position"], "counted": True,
                            "reason": "a life for every failure here, with no failure mode and no class failure cost: "
                                      "add the failure mode it's for and enter its cost, or set the class's",
                            "link": _explorer_link(r["position"]["id"], root, "rcm")})
    no_cost.sort(key=lambda x: (not x["counted"], x["position"]["name"].lower()))
    return {"no_effect": no_effect, "no_failure_cost": no_cost, "no_pf": no_pf}


# ---- the forecast ----------------------------------------------------------------------------

def served_modes(m: Maintenance, task_ids) -> set:
    """The failure modes the tasks serve (MITIGATES): a task's or a package's forecast counts the
    failures of these only."""
    out = set()
    for tid in task_ids or ():
        for fm in m.s.out(m.org, tid, "MITIGATES"):
            if fm.get("label") == "FailureMode" and not fm.get("retired"):
                out.add(fm["id"])
    return out


def position_forecast(m: Maintenance, position_id: str, root: str | None = None, period="month", periods=12,
                      fetch=None, end=None, task_ids=None, strict: bool = False) -> dict:
    """The forecast for a position and everything under it: see the module docstring.
    ``fetch(model_type, model_id)`` opens a saved model (position_models.fetcher); without
    it, no failures are forecast. ``end`` (an ISO date): the horizon's last day instead of
    ``periods``. ``task_ids``: only these tasks, and the failures of the modes they serve (a
    task's or a package's forecast). ``strict``: hours by a duty only (``_hours_map``)."""
    from backend.maintenance import schedule

    period, periods = _check(period, periods)
    only = set(task_ids) if task_ids is not None else None
    served = served_modes(m, only) if only is not None else None
    pos = m._get(position_id, "Position")
    if root:
        scope = m.s.node(m.org, root)
        if scope is None:
            raise svc.NotFound(f"Position {root}")
        if root != position_id and root not in m._ancestor_ids(position_id):
            raise Invalid("That position isn't inside the asset opened.")
    today = m.today()
    if end not in (None, ""):
        start = date.fromisoformat(today)
        end = _until(start, end)
        periods = None
    else:
        start, end = horizon(today, period, periods)
    end_excl = end + timedelta(days=1)
    calendar = schedule.UsageForecast.calendar(start, end_excl).by_period(period)
    starts = [d.date() if isinstance(d, datetime) else d for d in calendar.starts]
    n = len(starts)
    if n > MAX_ROWS:
        raise Invalid(f"That's {n:,} {period}s: group by a longer period, or forecast a shorter time "
                      f"(at most {MAX_ROWS} rows).")
    periods = periods or n
    zeros = lambda: np.zeros(n)  # noqa: E731
    count, labour, planned = zeros(), zeros(), zeros()
    labour_cost, materials_cost = zeros(), zeros()
    fail_exp, fail_cost = zeros(), zeros()
    down_hours, down_cost = zeros(), zeros()
    tasks_out, not_on_dates, models, not_forecast, by_position, states = [], [], [], [], [], []
    due_in: list[list[dict]] = [[] for _ in range(n)]
    no_cost_tasks, no_hours_tasks = set(), set()
    model_rows = []
    tree = _subtree(m, position_id)
    own_map = None
    n_tasks = 0
    for node, depth in tree:
        hours_map = _hours_map(m, node, root, start, end_excl, strict=strict)
        if node["id"] == position_id:
            own_map = hours_map
        rows, skipped, lib_tasks = _task_rows(m, node, hours_map, start, end, only)
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
                lab_each, mat_each = _split_each(view)
                for k, d in enumerate(done):
                    idx = max(0, min(n - 1, int(np.searchsorted(np.array(starts), d, side="right")) - 1))
                    labour_cost[idx] += lab_each
                    materials_cost[idx] += mat_each
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
                    "labour_cost_each": _money(lab_each), "materials_cost_each": _money(mat_each),
                    "next_due": view.get("next_due"), "rests_on": basis, "notes": list(due.notes)})
        if fetch is not None:
            here = {"id": node["id"], "name": node.get("name", "")}
            lives, left_out = _lives_on(m, node)
            not_forecast.extend({**x, "position": here} for x in left_out)
            if served is not None:
                lives = _lives_served(m, node, lives, served)
            for link, mode_ids in lives:
                # A life in hours with no duty runs all the time (running_clock), strict or not.
                found, why = _model_forecast(m, fetch, node, hours_map, start, end_excl, period, link, mode_ids)
                if why:
                    not_forecast.append({**why, "position": here})
                if found:
                    fc = found["fc"]
                    expected = np.asarray(fc.expected_failures, dtype=float)[:n]
                    fail_exp += expected
                    if fc.expected_cost is not None:
                        fail_cost += np.asarray(fc.expected_cost, dtype=float)[:n]
                    row_ = found["row"]
                    if row_["downtime_hours_each"]:
                        down_hours += expected * row_["downtime_hours_each"]
                        if row_["cost_per_failure"] is not None and row_["downtime_rate"]:
                            down_cost += expected * row_["downtime_hours_each"] * row_["downtime_rate"]
                    model_rows.append(found)
                    models.append(found["row"])
                    mine["failures"] += float(found["row"]["expected_failures"] or 0)
                    mine["failure_cost"] += float(found["row"]["expected_cost"] or 0)
        by_position.append({"position": {"id": node["id"], "name": node.get("name", "")}, "depth": depth,
                            "tasks": mine["count"], "labour_hours": _num(mine["labour"]),
                            "planned_cost": _money(mine["planned"]), "failures": _num(mine["failures"]),
                            "failure_cost": _money(mine["failure_cost"]),
                            "hours_basis": hours_map["basis"]["text"] if hours_map else None})

    # The range: one model, its own (exact) per period; several, the total assuming independence.
    single = model_rows[0]["fc"] if len(model_rows) == 1 else None
    # A life with checks counted has no range yet (the library gives none for checks): the total has none either.
    ranged = all(r["fc"].total.get("failure_probabilities") for r in model_rows)
    if model_rows and (single is not None or ranged):
        if single is not None:
            f_lo, f_hi = single.total.get("failures_low"), single.total.get("failures_high")
            c_lo, c_hi = single.total.get("cost_low"), single.total.get("cost_high")
        else:
            f_lo, f_hi, c_lo, c_hi = _sum_range(model_rows)
    else:
        f_lo = f_hi = c_lo = c_hi = None
    prob_any = None
    if model_rows and all(r["fc"].total.get("probability") is not None for r in model_rows):
        none = 1.0
        for r in model_rows:
            none *= 1.0 - float(r["fc"].total["probability"])
        prob_any = 1.0 - none
    hours = None
    if own_map is not None:
        got = own_map["usage"].by_period(period).usage.get("hours")
        hours = [float(x) for x in got][:n] if got is not None else None
    visit_cost, visit_count = _visits(m, tasks_out, starts, n)
    planned = planned + visit_cost
    priced = bool(model_rows) and any(r["row"]["cost_per_failure"] for r in model_rows)
    any_downtime = any(r["row"]["downtime_hours_each"] for r in model_rows)
    rows = []
    for k in range(n):
        p_end = (starts[k + 1] - timedelta(days=1)) if k + 1 < n else end
        unplanned = _money(fail_cost[k]) if priced else None
        row = {"start": starts[k].isoformat(), "end": p_end.isoformat(),
               "hours": _num(hours[k]) if hours and k < len(hours) else None,
               "tasks": int(count[k]), "labour_hours": _num(labour[k]), "planned_cost": _money(planned[k]),
               **_planned_split(planned[k], labour_cost[k], materials_cost[k], visit_cost[k]),
               "visits": int(visit_count[k]),
               "failures": _num(fail_exp[k]) if model_rows else None,
               "failure_cost": unplanned, "unplanned_cost": unplanned,
               "downtime_hours": _num(down_hours[k]) if any_downtime else None,
               "downtime_cost": _money(down_cost[k]) if any_downtime and priced else None,
               "total_cost": _money(planned[k] + (fail_cost[k] if priced else 0.0)),
               "due": sorted(due_in[k], key=lambda d: (d["date"], d["name"]))}
        if single is not None:
            row["failures_range"] = [_num(single.failures_low[k]) if single.failures_low is not None else None,
                                     _num(single.failures_high[k]) if single.failures_high is not None else None]
            row["cost_range"] = [_money(single.cost_low[k]) if single.cost_low is not None else None,
                                 _money(single.cost_high[k]) if single.cost_high is not None else None]
        rows.append(row)

    total_cost = float(fail_cost.sum()) if model_rows else None
    unpriced = [r["row"] for r in model_rows if r["row"]["cost_per_failure"] is None]
    totals = {"tasks": int(count.sum()), "labour_hours": _num(labour.sum()), "planned_cost": _money(planned.sum()),
              **_planned_split(planned.sum(), labour_cost.sum(), materials_cost.sum(), visit_cost.sum()),
              "visits": int(visit_count.sum()),
              "failures": _num(fail_exp.sum()) if model_rows else None,
              "failures_range": [f_lo, f_hi] if model_rows else None,
              "failure_cost": _money(total_cost) if priced else None,
              "unplanned_cost": _money(total_cost) if priced else None,
              "cost_range": [_money(c_lo), _money(c_hi)] if model_rows and c_lo is not None else None,
              "downtime_hours": _num(down_hours.sum()) if any_downtime else None,
              "downtime_cost": _money(down_cost.sum()) if any_downtime and priced else None,
              "total_cost": _money(planned.sum() + (total_cost if priced else 0.0)),
              # Every failure forecast has a cost: the total is planned plus unplanned in full.
              "total_complete": not unpriced,
              "probability": _num(prob_any, 3)}
    cost_basis = _cost_basis_words(totals, unpriced)

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
        if x["reason"].startswith(("this life is in", "This model is in")):
            states.append({"kind": "unit_not_measured",
                           "text": f"{x['position']['name']}: {x['reason'].rstrip('.')}."})
    for r in models:
        if r["placeholder"]:
            states.append({"kind": "placeholder",
                           "text": f"{r['position']['name']}: its life model, {r['name']}, was typed in, not fitted "
                                   "from data. Treat its failures as a placeholder until it's fitted."})

    prompts = _prompts(m, fetch, tree, tasks_out, models, root)
    if prompts["no_failure_cost"]:
        counted = sum(1 for x in prompts["no_failure_cost"] if x["counted"])
        if counted:
            states.append({"kind": "no_failure_cost",
                           "text": f"{counted} failure mode{'s' if counted != 1 else ''} forecast here "
                                   f"{'have' if counted != 1 else 'has'} no failure cost: the unplanned cost leaves "
                                   "their failures out. Enter what a failure costs (listed under What to enter)."})
    answer = _answer(end, totals, len(not_on_dates))
    words = (f"{len(tree)} position{'s' if len(tree) != 1 else ''} ({pos.get('name', '')} and everything inside "
             "it)" if len(tree) > 1 else pos.get("name", ""))
    notes = ["Each task is assumed done on its due date: an interval counts again from then; a pattern keeps its "
             "own dates.",
             "A failed item is assumed replaced at once with a like one.",
             "Expected failures count the maintenance on the failure modes each life is for: a replacement at "
             "its interval, and an on-condition check against its P-F interval (the warnings it misses fail)."]
    if len(model_rows) > 1:
        notes.append("Expected failures and costs add up over positions; the total's range assumes the positions "
                     "fail independently. Ranges by period are per position.")
    if no_cost_tasks:
        notes.append(f"{len(no_cost_tasks)} task{'s have' if len(no_cost_tasks) != 1 else ' has'} no cost: the "
                     "planned cost leaves them out.")
    if no_hours_tasks:
        notes.append(f"{len(no_hours_tasks)} task{'s have' if len(no_hours_tasks) != 1 else ' has'} no labour in "
                     "its LSA: the labour hours leave them out.")
    out = {
        "position": {"id": pos["id"], "name": pos.get("name", "")}, "root": root, "today": today,
        "period": period, "periods": periods, "start": start.isoformat(), "end": end.isoformat(),
        "covers": words, "answer": answer, "range": RANGE_WORDS, "range_level": RANGE_LEVEL,
        "hours_basis": own_map["basis"]["text"] if own_map else None,
        "hours_source": own_map["basis"]["kind"] if own_map else None,
        "hours_rate_per_day": own_map["basis"].get("rate_per_day") if own_map else None,
        "rows": rows, "totals": totals, "tasks": tasks_out, "not_on_dates": not_on_dates,
        "models": models, "not_forecast": not_forecast, "by_position": by_position,
        "states": states, "notes": notes, "prompts": prompts, "cost_basis": cost_basis,
        "truncated": len(tree) >= MAX_POSITIONS,
    }
    from backend.maintenance import forecast_lines

    out["lines"] = forecast_lines.build(m, out, model_rows, tree, root)
    return out


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
    if t.get("failure_cost") is not None:
        text += (f"; about ${t['total_cost']:,.0f} in all (${t['planned_cost'] or 0:,.0f} planned, "
                 f"${t['failure_cost']:,.0f} unplanned)")
    if left_out:
        text += f". {left_out} task{'s' if left_out != 1 else ''} can't be put on dates yet (see Left out)"
    return text + "."
