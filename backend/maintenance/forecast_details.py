"""A forecast's details: a task's, a package's or a level's work, failures and costs to come, by
the calendar or by running hours (the Explorer's Maintenance tab: a Forecast row opened, or
Forecast… on a level; ``GET /api/maintenance/positions/{id}/forecast/details``).

Derryn, 23 Nov 2026: "I should be able to set a horizon and see the counts grouped by day, month,
etc etc. and a paginated list of when next. Should also be able to see the forecast costs as well";
"the forecast should be able to work in calendar or operating hours (with or without a duty)".

Two bases:

* **calendar**: from today to a date, grouped by day, week, month, quarter or year
  (``position_forecast`` with ``strict``).
* **hours**: the next N running hours, grouped every B hours.

Hours and the calendar meet through the position's duty (its operating plan, as
``Maintenance.duty_of`` resolves it); with none, it's taken to run all the time, 24 h a day
(Derryn, 21 Nov 2026: "assume continuous use unless there is a duty against that position"),
anchored on the latest hours reading, and the answer says so once, with where to set a duty
(``assumed``). So tasks by use, calendar rules and lives always share one time basis, on both.
The meter's recent rate is not used here.

RePyability does the maths
(``Task.due``, ``UsageForecast.model_time`` and ``moment``, ``NonRepairable.cost_by_window``);
this module picks what to ask, sums the answers into rows and labels them. Nothing is stored.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta

import numpy as np
from dateutil.relativedelta import relativedelta

from backend.maintenance import position_forecast as pf
from backend.maintenance import service as svc
from backend.maintenance.service import Invalid, Maintenance

BASES = ("calendar", "hours")
MAX_HOURS = 200_000
MAX_OCCURRENCES = 5_000  # the When next list, in one read


# ---- what's forecast ----------------------------------------------------------------------------

def _package_tasks(m: Maintenance, package_id: str) -> list[str]:
    """A package's tasks, those of packages layered on it included."""
    pkg = m.s.node(m.org, package_id)
    if pkg is None or pkg.get("label") != "WorkPackage":
        raise svc.NotFound(f"Work package {package_id}")
    out = []
    for tid, entry in m._package_index().items():
        if any(p["id"] == package_id for p in m._package_chain(entry["package"])):
            out.append(tid)
    return out


def _subject(m: Maintenance, pos: dict, task_ids, package_id) -> tuple[dict, list | None]:
    """What the forecast is of ({kind: level|task|package, id, name}) and the task ids it takes
    (None: every task at the level and below)."""
    if package_id:
        pkg = m.s.node(m.org, package_id) or {}
        return {"kind": "package", "id": package_id, "name": pkg.get("name", "")}, _package_tasks(m, package_id)
    if task_ids:
        ids = [t for t in task_ids if t]
        if len(ids) == 1:
            t = m.s.node(m.org, ids[0])
            if t is None or t.get("label") != "Task":
                raise svc.NotFound(f"Task {ids[0]}")
            return {"kind": "task", "id": ids[0], "name": t.get("name", "")}, ids
        return {"kind": "tasks", "id": None, "name": f"{len(ids)} tasks"}, ids
    return {"kind": "level", "id": pos["id"], "name": pos.get("name", "")}, None


def _tasks_in(m: Maintenance, tree, only) -> list[dict]:
    out = []
    for node, _depth in tree:
        for t in m._tasks_on(node["id"]):
            if (only is None or t["id"] in only) and not svc._on_event_only(t):
                out.append(t)
    return out


def _by_use(task: dict) -> bool:
    return not svc._is_calendar(task["unit"]) or bool(task.get("also_unit") and not svc._is_calendar(task["also_unit"]))


def _duty_words(m: Maintenance, position_id: str, root) -> dict | None:
    duty = m.duty_of(position_id, root)
    if duty is None:
        return None
    return {"text": duty["text"], "inherited_from": duty["inherited_from"], "ended": duty["ended"]}


def _plan_link(position_id: str, root) -> str:
    """Where a duty is set: the position's operating plan, on the Operations tab (?plan=)."""
    return pf._explorer_link(position_id, root, "operations", plan=position_id)


# ---- When next ------------------------------------------------------------------------------------

def _occurrences(m: Maintenance, tasks_out: list[dict], subject_kind: str, hours_of=None) -> tuple[list, bool]:
    """Each time something is done, soonest first: a task, or a package's visit with the tasks on it
    (a level's or a package's forecast: the tasks of one package due at the same moment, or on the
    same day on the calendar, are one visit). [{date, moment, hours, kind, name, package, tasks,
    position, overdue}], and whether the list was cut short."""
    index = m._package_index()
    groups: dict = {}
    for t in tasks_out:
        entry = index.get(t["id"])
        pkg = entry["package"] if entry else None
        moments = t.get("moments") or []
        slots = t["dates"] or [None] * len(t.get("hours") or [])
        for k, day in enumerate(slots):
            moment = moments[k] if k < len(moments) else None
            hours = hours_of(t, k) if hours_of else None
            visit = pkg is not None and subject_kind != "task"
            key = ("visit", pkg["id"], hours if hours is not None else moment or day) if visit else ("task", t["id"], k)
            g = groups.get(key)
            if g is None:
                g = groups[key] = {
                    "date": day, "moment": moment, "hours": hours, "kind": "visit" if visit else "task",
                    "name": pkg["name"] if visit else t["name"],
                    "package": {"id": pkg["id"], "name": pkg.get("name", "")} if pkg else None,
                    "position": t["position"], "tasks": [], "overdue": False}
            g["tasks"].append({"id": t["id"], "name": t["name"], "position": t["position"]["name"]})
            g["overdue"] = g["overdue"] or bool(t.get("overdue") and k == 0)
    out = sorted(groups.values(), key=lambda g: (g["hours"] if g["hours"] is not None else 0.0,
                                                 g["moment"] or g["date"] or "", g["name"]))
    for g in out:
        g["tasks"].sort(key=lambda x: x["name"])
    return out[:MAX_OCCURRENCES], len(out) > MAX_OCCURRENCES


def _not_placed(fc_not_on_dates: list[dict], m: Maintenance, root, basis: str) -> list[dict]:
    """The tasks left out, each with why and (for a missing duty) where to set one."""
    out = []
    for x in fc_not_on_dates:
        task = m.s.node(m.org, x["task"]["id"]) or {}
        reason, link = x["reason"], None
        if "no operating plan" in reason or "no hours reading" in reason:
            link = _plan_link(x["position"]["id"], root)
        out.append({"task": x["task"], "position": x["position"], "reason": reason, "link": link})
    return out


# ---- by the calendar --------------------------------------------------------------------------------

def _calendar(m: Maintenance, position_id: str, root, period, end, only, subject, fetch) -> dict:
    fc = pf.position_forecast(m, position_id, root, period or "month", 12, fetch,
                              end=end or None, task_ids=only, strict=True)
    rows = [{k: v for k, v in r.items() if k != "due"} for r in fc["rows"]]
    occ, cut = _occurrences(m, fc["tasks"], subject["kind"])
    return {
        **{k: fc[k] for k in ("position", "root", "today", "period", "start", "end", "covers", "answer", "range",
                              "range_level", "hours_basis", "totals", "tasks", "models", "not_forecast",
                              "by_position", "states", "notes", "prompts", "cost_basis", "truncated")},
        "rows": rows, "occurrences": occ, "occurrences_cut": cut,
        "not_placed": _not_placed(fc["not_on_dates"], m, root, "calendar"),
        "_hours_kind": fc.get("hours_source"), "_rate_per_day": fc.get("hours_rate_per_day"),
    }


# ---- by running hours ------------------------------------------------------------------------------

def _num_or_none(v):
    return None if v is None else pf._num(v)


def _hours_rows(horizon: float, every: float) -> list[tuple[float, float]]:
    n = int(math.ceil(horizon / every - 1e-9))
    return [(k * every, min(horizon, (k + 1) * every)) for k in range(n)]


def _map_for(m: Maintenance, node: dict, root, today: date, far: date, reading):
    """The position's map between dates and running hours for the hours basis: (map, duty?).
    The duty's, else the readings' rate, else running all the time, 24 h a day; anchored on the
    hours reading given, else the latest recorded (``_hours_map`` with ``strict``)."""
    duty = m.duty_of(node["id"], root)
    end_excl = far + timedelta(days=1)
    if reading is None:
        hm = pf._hours_map(m, node, root, today, end_excl, strict=True)
        if hm is not None:
            if hm["basis"].get("reading") is None:  # a duty, no reading: count from 0 h today
                hm = {**hm, "basis": {**hm["basis"], "reading": {"value": 0.0, "on": today.isoformat()}}}
            return hm, duty is not None
    counter = svc._counter_on(m.s, m.org, node["id"], "hours")
    readings = svc._readings(m.s, m.org, counter, m.tz) if counter else []
    value = float(reading or 0.0)
    rate = svc._rate(readings) if len(readings) >= 2 else None
    per_day = min(rate, 24.0) if rate and rate > 0 else None
    now = {"value": value, "on": today.isoformat()}
    if duty is not None:
        usage = duty["plan"].forecast(today, end_excl, readings={"hours": value}, read_at=today)
        text = f"Hours from the operating plan ({duty['text']}), from {value:,.6g} h now"
        kind = "plan"
    else:
        usage = svc.meter_usage(datetime(today.year, today.month, today.day), end_excl, now, per_day)
        text = f"{svc.rate_text(per_day) if per_day else pf.CONTINUOUS_NOTE}, from {value:,.6g} h now"
        kind = "rate" if per_day else "continuous"
    basis = {"kind": kind, "text": text, "reading": now, "rate_per_day": per_day}
    return {"usage": usage, "counter": counter, "readings": readings, "basis": basis}, duty is not None


def _hours(m: Maintenance, position_id: str, root, horizon, every, reading, only, subject, fetch) -> dict:
    try:
        horizon = float(horizon if horizon not in (None, "") else 1000)
        every = float(every if every not in (None, "") else max(1.0, horizon / 10))
        reading = None if reading in (None, "") else float(reading)
    except (TypeError, ValueError):
        raise Invalid("hours, every and reading are numbers of running hours.") from None
    if not 0 < horizon <= MAX_HOURS:
        raise Invalid(f"Forecast more than 0 and at most {MAX_HOURS:,} running hours.")
    if not 0 < every <= horizon:
        raise Invalid("Group every so many hours: more than 0, and no more than the horizon.")
    if reading is not None and reading < 0:
        raise Invalid("The starting reading is 0 h or more.")
    bins = _hours_rows(horizon, every)
    if len(bins) > pf.MAX_ROWS:
        raise Invalid(f"That's {len(bins):,} rows: group by more hours (at most {pf.MAX_ROWS} rows).")
    edges = np.array([b for _, b in bins])
    n = len(bins)
    pos = m._get(position_id, "Position")
    today = date.fromisoformat(m.today())
    far = today + relativedelta(months=pf.MAX_MONTHS)
    z = lambda: np.zeros(n)  # noqa: E731
    count, labour, planned, lab_cost, mat_cost = z(), z(), z(), z(), z()
    fail_exp, fail_cost = z(), z()
    f_rows = []
    tasks_out, not_on, models, not_forecast = [], [], [], []
    hours_at: dict = {}
    served = pf.served_modes(m, only) if only is not None else None
    tree = pf._subtree(m, position_id, m.forecast_within(pos["id"], root))
    own_basis = None
    origin = datetime(today.year, today.month, today.day)
    for node, _depth in tree:
        hm, _has_duty = _map_for(m, node, root, today, far, reading)
        usage = hm["usage"]
        if node["id"] == position_id:
            own_basis = hm["basis"]
        until = usage.moment(horizon)
        last_day = until.date() if until is not None else far
        rows, skipped, _lib = pf._task_rows(m, node, hm, today, last_day, only)
        here = {"id": node["id"], "name": node.get("name", "")}
        for s in skipped:
            not_on.append({**s, "position": here})
        for lib, view, task, basis, first, by_use in rows:
            due = lib.due(today, last_day, usage=usage)
            done = list(due.done)
            moments = list(due.moments or ()) if by_use else []
            overdue = bool(due.overdue)
            if first:
                day = max(date.fromisoformat(first), today)
                overdue = date.fromisoformat(first) < today
                done.insert(0, day)
                if moments:
                    moments.insert(0, None)
            at = []
            for k, d in enumerate(done):
                mo = moments[k] if k < len(moments) and moments[k] else datetime(d.year, d.month, d.day)
                h = 0.0 if mo <= origin else max(0.0, float(usage.model_time(mo)))  # overdue: done now
                at.append(h)
            keep = [k for k, h in enumerate(at) if h <= horizon + 1e-9]
            lab_each, mat_each = pf._split_each(view)
            cost_each = (view.get("cost") or {}).get("amount")
            for k in keep:
                i = min(n - 1, int(np.searchsorted(edges, at[k] - 1e-9, side="left")))
                count[i] += 1
                labour[i] += lib.duration or 0.0
                planned[i] += float(cost_each or 0.0)
                lab_cost[i] += lab_each
                mat_cost[i] += mat_each
            dates = [done[k].isoformat() for k in keep]
            mos = [moments[k].strftime("%Y-%m-%dT%H:%M") if k < len(moments) and moments[k] else None for k in keep]
            hours_at[task["id"]] = [pf._num(at[k], 6) for k in keep]
            tasks_out.append({
                "id": task["id"], "name": task["name"], "position": here,
                "how_often": view["limits"][0]["limit"] if view.get("limits") else "",
                "by_use": by_use, "dates": dates, "moments": mos if any(mos) else [],
                "hours": hours_at[task["id"]], "overdue": overdue and bool(keep) and keep[0] == 0, "count": len(keep),
                "cost_each": cost_each, "labour_each": lib.duration, "labour_cost_each": pf._money(lab_each),
                "materials_cost_each": pf._money(mat_each), "rests_on": basis, "notes": list(due.notes),
                "_keys": [mos[j] or dates[j] for j in range(len(keep))]})
        if fetch is not None:
            lives, left_out = pf._lives_on(m, node)
            not_forecast.extend({**x, "position": here} for x in left_out)
            if served is not None:
                lives = pf._lives_served(m, node, lives, served)

            def windows(life_unit, use, _usage=usage):
                if life_unit == "hours":
                    return edges
                per = svc._DAYS_PER.get(life_unit, 1.0)
                out = []
                for e in edges:
                    mo = _usage.moment(float(e))
                    out.append(((mo or datetime(far.year, far.month, far.day)) - origin).total_seconds() / 86_400 / per)
                return np.array(out)

            for link, mode_ids in lives:
                found, why = pf._model_forecast(m, fetch, node, hm, today, far + timedelta(days=1), "month", link,
                                                mode_ids, windows=windows)
                if why:
                    not_forecast.append({**why, "position": here})
                if found:
                    f = found["fc"]
                    fail_exp += np.asarray(f.expected_failures, dtype=float)[:n]
                    if f.expected_cost is not None:
                        fail_cost += np.asarray(f.expected_cost, dtype=float)[:n]
                    f_rows.append(found)
                    models.append(found["row"])

    # Visits: a package's visit cost once each time its tasks are done together.
    keyed = [{**t, "dates": t["_keys"], "moments": []} for t in tasks_out]
    visit_cost, visit_count = z(), z()
    by_key = {(t["position"]["id"], key): h for t in tasks_out for key, h in zip(t["_keys"], t["hours"])}
    for (pid, key), (cost, _day) in pf.visit_list(m, keyed).items():
        h = by_key.get((pid, key), 0.0)
        i = min(n - 1, int(np.searchsorted(edges, h - 1e-9, side="left")))
        visit_cost[i] += cost
        visit_count[i] += 1
    planned = planned + visit_cost
    single = f_rows[0]["fc"] if len(f_rows) == 1 else None
    priced = any(r["row"]["cost_per_failure"] for r in f_rows)
    start_h = float(own_basis["reading"]["value"]) if own_basis and own_basis.get("reading") else 0.0
    rows = []
    for k, (lo, hi) in enumerate(bins):
        unplanned = pf._money(fail_cost[k]) if priced else None
        row = {"from_hours": pf._num(lo, 6), "to_hours": pf._num(hi, 6),
               "reading_from": pf._num(start_h + lo, 6), "reading_to": pf._num(start_h + hi, 6),
               "tasks": int(count[k]), "visits": int(visit_count[k]), "labour_hours": pf._num(labour[k]),
               "planned_cost": pf._money(planned[k]),
               **pf._planned_split(planned[k], lab_cost[k], mat_cost[k], visit_cost[k]),
               "failures": pf._num(fail_exp[k]) if f_rows else None, "failure_cost": unplanned,
               "total_cost": pf._money(planned[k] + (fail_cost[k] if priced else 0.0))}
        if single is not None and single.failures_low is not None:
            row["failures_range"] = [pf._num(single.failures_low[k]), pf._num(single.failures_high[k])]
            if single.cost_low is not None:
                row["cost_range"] = [pf._money(single.cost_low[k]), pf._money(single.cost_high[k])]
        rows.append(row)
    if single is not None:
        f_lo, f_hi = single.total.get("failures_low"), single.total.get("failures_high")
        c_lo, c_hi = single.total.get("cost_low"), single.total.get("cost_high")
    elif f_rows and all(r["fc"].total.get("failure_probabilities") for r in f_rows):
        f_lo, f_hi, c_lo, c_hi = pf._sum_range(f_rows)
    else:
        f_lo = f_hi = c_lo = c_hi = None
    total_fail_cost = float(fail_cost.sum())
    totals = {"tasks": int(count.sum()), "visits": int(visit_count.sum()), "labour_hours": pf._num(labour.sum()),
              "planned_cost": pf._money(planned.sum()),
              **pf._planned_split(planned.sum(), lab_cost.sum(), mat_cost.sum(), visit_cost.sum()),
              "failures": pf._num(fail_exp.sum()) if f_rows else None,
              "failures_range": [_num_or_none(f_lo), _num_or_none(f_hi)] if f_rows and f_lo is not None else None,
              "failure_cost": pf._money(total_fail_cost) if priced else None,
              "cost_range": [pf._money(c_lo), pf._money(c_hi)] if priced and c_lo is not None else None,
              "total_cost": pf._money(planned.sum() + (total_fail_cost if priced else 0.0)),
              "total_complete": all(r["row"]["cost_per_failure"] is not None for r in f_rows)}

    def hours_of(t, k):
        return t["hours"][k]

    for t in tasks_out:
        t.pop("_keys", None)
    occ, cut = _occurrences(m, tasks_out, subject["kind"], hours_of=hours_of)
    words = (f"{len(tree)} positions ({pos.get('name', '')} and everything inside it)" if len(tree) > 1
             else pos.get("name", ""))
    answer = (f"The next {horizon:,.6g} running hours: {totals['tasks']} task{'s' if totals['tasks'] != 1 else ''}"
              + (f", about {totals['labour_hours']:,.3g} labour hours" if totals["labour_hours"] else "")
              + (f", ${totals['planned_cost']:,.0f} planned" if totals["planned_cost"] else "")
              + (f"; {totals['failures']:.2g} failures expected" if totals["failures"] is not None else "") + ".")
    notes = ["Each task is assumed done when it falls due; a failed item is assumed replaced at once with a like one.",
             "Running hours are each position's own from now: positions inside this one count theirs."]
    if f_rows and served is not None:
        notes.append("Failures are those of the failure modes these tasks serve (a position's whole life when "
                     "they serve any of its modes).")
    return {
        "position": {"id": pos["id"], "name": pos.get("name", "")}, "root": root, "today": today.isoformat(),
        "hours": pf._num(horizon, 6), "every": pf._num(every, 6), "reading": pf._num(start_h, 6),
        "covers": words, "answer": answer, "range": pf.RANGE_WORDS, "range_level": pf.RANGE_LEVEL,
        "hours_basis": own_basis["text"] if own_basis else None, "rows": rows, "totals": totals,
        "_hours_kind": own_basis["kind"] if own_basis else None,
        "_rate_per_day": own_basis.get("rate_per_day") if own_basis else None,
        "tasks": tasks_out, "models": models, "not_forecast": not_forecast, "states": [], "notes": notes,
        "prompts": None, "cost_basis": None, "by_position": [], "truncated": len(tree) >= pf.MAX_POSITIONS,
        "occurrences": occ, "occurrences_cut": cut, "not_placed": _not_placed(not_on, m, root, "hours"),
    }


# ---- the read -------------------------------------------------------------------------------------

def forecast_details(m: Maintenance, position_id: str, root: str | None = None, basis: str | None = None,
                     period: str = "month", end: str | None = None, hours=None, every=None, reading=None,
                     task_ids=None, package_id: str | None = None, fetch=None, months=None) -> dict:
    """The forecast details for a position and everything inside it (inside ``root``), or for
    one task (``task_ids``) or a package (``package_id``) there: see the module docstring.
    ``basis``: "calendar" (``period``, ``end``: the last day, default a year from today less a
    day; or ``months``: this month and the next months - 1, to the end of a month, so 12 months
    by month is 12 rows) or "hours" (``hours`` ahead, grouped ``every`` hours, from ``reading``); left out, the
    calendar when the position has a duty, running hours when it has none and its tasks are
    mostly by use."""
    pos = m._get(position_id, "Position")
    within = m.forecast_within(pos["id"], root)
    subject, ids = _subject(m, pos, task_ids, package_id)
    only = set(ids) if ids is not None else None
    tree = pf._subtree(m, position_id, within)
    tasks = _tasks_in(m, tree, only)
    duty = _duty_words(m, position_id, root)
    by_use = sum(1 for t in tasks if _by_use(t))
    default = "calendar" if duty or by_use * 2 <= len(tasks) else "hours"
    basis = (basis or default).strip().lower()
    if basis not in BASES:
        raise Invalid("The basis is calendar or hours.")
    if basis == "calendar":
        today = date.fromisoformat(m.today())
        if not end and months not in (None, ""):
            try:
                months = int(months)
            except (TypeError, ValueError):
                raise Invalid("months is a whole number.") from None
            if not 1 <= months <= pf.MAX_MONTHS:
                raise Invalid(f"Forecast 1 to {pf.MAX_MONTHS} months.")
            end = (today.replace(day=1) + relativedelta(months=months) - timedelta(days=1)).isoformat()
        if not end:
            end = (today + relativedelta(years=1) - timedelta(days=1)).isoformat()
        out = _calendar(m, position_id, root, period, end, only, subject, fetch)
    else:
        out = _hours(m, position_id, root, hours, every, reading, only, subject, fetch)
    # With no duty, hours meet the calendar at the readings' rate, else 24 h a day: said once, with
    # where to set a duty.
    assumed = None
    kind, per_day = out.pop("_hours_kind", None), out.pop("_rate_per_day", None)
    if duty is None and (by_use or (basis == "hours" and len(tasks) > by_use) or out.get("models")):
        words = svc.rate_text(per_day) if kind == "rate" and per_day else pf.CONTINUOUS_NOTE
        assumed = {"text": f"{words}. Set a duty in Operations.", "link": _plan_link(position_id, root),
                   "kind": "rate" if kind == "rate" else "continuous"}
    return {**out, "basis": basis, "default_basis": default, "duty": duty, "assumed": assumed,
            "duty_link": _plan_link(position_id, root), "subject": subject,
            "by_use_tasks": by_use, "calendar_tasks": len(tasks) - by_use}
