"""The quick forecast tool as a sentence (Decisions › Forecasts: Spares, Hours and Cost forecast).

"[n] units, running [12 h a week], over the next [12 months]", then two optional clauses, at least
one filled in:

* **work on a schedule:** a task done every so many hours, days, weeks or months, and what it needs
  each time (hours, cost, spares). Its count is certain: it comes from the schedule
  (RePyability's ``Task.due``), assumed just done at the start, so it has no range;
* **a part that fails:** a life model, how old the units are now, and what a failure needs (hours,
  cost). Its failures are a chance, from the saved-fleet engine (``fleet.scratch_forecast``),
  unchanged: seeded runs with a 90% two-sided range.

With both filled in, the work either doesn't change the part's life or replaces the part (the
engine's planned replacement at that age, so its count becomes a chance too).

Every number sits on a line with one owner (the work, or the part's failures), says what kind of
number it is (certain, worked out or simulated) and what it leaves out. A total with a gap is the
"known" total and lists what it leaves out; nothing is filled in (forecast-rules 1.6). Ranges are
90% two-sided; a sum of a certain line and a chance adds the certain part to both ends (1.4). The
time basis is the one typed ("12 h a week"), else running all the time, and the result says which.
Nothing is saved.
"""

from __future__ import annotations

import math
from datetime import date, timedelta

import numpy as np

from backend.services import fleet as fleet_service
from backend.services.fleet import FleetValidationError

PERIOD_DAYS = {"months": 30.4375, "quarters": 91.3125}
HORIZONS = (12, 24, 36, 60)
HOURS = {"h", "hr", "hrs", "hour", "hours", "operating hours", "running hours"}
CALENDAR_DAYS = {"days": 1.0, "day": 1.0, "weeks": 7.0, "week": 7.0, "months": 30.4375, "month": 30.4375,
                 "years": 365.25, "year": 365.25}
WORK_UNITS = ("hours", "days", "weeks", "months", "years")
RANGE_WORDS = "90% two-sided: in nine years out of ten it falls inside"
MAX_UNITS = fleet_service.MAX_SCRATCH_UNITS


def _num(value, label: str, *, positive=False, minimum=None) -> float | None:
    if value in (None, ""):
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise FleetValidationError(f"{label} must be a number.") from None
    if not math.isfinite(v) or v < 0 or (positive and v <= 0):
        raise FleetValidationError(f"{label} must be {'more than 0' if positive else '0 or more'}.")
    if minimum is not None and v < minimum:
        raise FleetValidationError(f"{label} must be at least {minimum:g}.")
    return v


def _sig(v, digits: int = 8):
    if v is None:
        return None
    v = float(v)
    return float(f"{v:.{digits}g}") if math.isfinite(v) else None


def _norm(unit) -> str:
    return str(unit or "").strip().lower()


def _running(raw) -> dict:
    """How the units run: {per_day, text, assumed}. ``raw`` {hours, per: day | week} or
    {all_the_time: true}; none given: all the time, said as assumed."""
    raw = raw or {}
    if raw.get("all_the_time") or raw.get("per") == "all":
        return {"per_day": 24.0, "per": "all", "hours": None, "text": "all the time (24 h a day)", "assumed": False}
    hours = _num(raw.get("hours"), "The hours it runs", positive=True)
    if hours is None:
        return {"per_day": 24.0, "per": "all", "hours": None, "assumed": True,
                "text": "all the time (24 h a day): no running hours given"}
    per = raw.get("per") or "day"
    if per not in ("day", "week"):
        raise FleetValidationError("Running is so many hours a day or a week, or all the time.")
    limit = 24 if per == "day" else 168
    if hours > limit:
        raise FleetValidationError(f"A unit can't run more than {limit} h a {per}.")
    per_day = hours if per == "day" else hours / 7
    return {"per_day": per_day, "per": per, "hours": hours, "text": f"{hours:g} h a {per}", "assumed": False}


def _horizon(body: dict) -> dict:
    try:
        months = int(body.get("months") or 12)
    except (TypeError, ValueError):
        raise FleetValidationError("The horizon is 12, 24, 36 or 60 months.") from None
    if months not in HORIZONS:
        raise FleetValidationError("The horizon is 12, 24, 36 or 60 months.")
    try:
        start = date.fromisoformat(str(body.get("start"))[:10]) if body.get("start") else date.today()
    except ValueError:
        raise FleetValidationError("start is a date, such as 2026-11-24.") from None
    # Group by month up to two years, by quarter beyond (forecast-rules 5.5: chosen for you).
    label = "months" if months <= 24 else "quarters"
    periods = months if label == "months" else months // 3
    days = PERIOD_DAYS[label] * periods
    end = start + timedelta(days=round(days) - 1)
    return {"months": months, "start": start, "end": end, "period_label": label, "periods": periods,
            "period_days": PERIOD_DAYS[label]}


def _ages(body: dict, part: dict) -> tuple[list[float], int]:
    src = part["raw"]
    raw = src.get("ages", src.get("age", body.get("ages")))
    if raw in (None, "", []):
        raise FleetValidationError("Say how old the part is now: one age for them all, or one per unit.")
    ages = raw if isinstance(raw, list) else [raw]
    try:
        ages = [float(a) for a in ages]
    except (TypeError, ValueError):
        raise FleetValidationError("Each age must be a number, in the model's unit.") from None
    if any(not math.isfinite(a) or a < 0 for a in ages):
        raise FleetValidationError("An age can't be negative.")
    return ages, len(ages)


def _units(body: dict) -> int:
    raw = body.get("units")
    try:
        n = 1 if raw in (None, "") else int(raw)
    except (TypeError, ValueError):
        raise FleetValidationError("The number of units must be a whole number.") from None
    if n < 1:
        raise FleetValidationError("The number of units must be at least 1.")
    if n > MAX_UNITS:
        raise FleetValidationError(f"A quick forecast takes up to {MAX_UNITS:,} units: save a fleet for more.")
    return n


# ---- work on a schedule: certain counts ---------------------------------------------------------

def _work(raw: dict | None) -> dict | None:
    if not raw:
        return None
    every = _num(raw.get("every"), "How often the work is done", positive=True)
    if every is None:
        raise FleetValidationError("Say how often the work is done: every so many hours, days, weeks or months.")
    unit = _norm(raw.get("unit") or "hours")
    unit = "hours" if unit in HOURS else unit
    if unit not in WORK_UNITS:
        raise FleetValidationError("The work is done every so many hours, days, weeks, months or years.")
    effect = raw.get("effect") or "none"
    if effect not in ("none", "replaces", "supports"):
        raise FleetValidationError("The work doesn't change the part's life (none), replaces the part, or keeps it on "
                                   "its life (supports).")
    k = _num(raw.get("impact_k"), "The impact (failure rate × k if it isn't done)")
    if k is not None and not 1 <= k <= 100:
        raise FleetValidationError("The impact is from × 1 (no change) to × 100: the failure rate while it isn't done.")
    grace = _num(raw.get("grace"), "The grace (% of its interval)")
    if grace is not None and grace > 100:
        raise FleetValidationError("The grace is 0% to 100% of its interval.")
    name = str(raw.get("name") or "").strip()[:120] or "The work"
    on_replace = raw.get("on_replace") or "restart"
    if on_replace not in ("restart", "keep"):
        raise FleetValidationError("When the part is replaced, the work restarts (restart) or keeps its schedule (keep).")
    whatif = raw.get("whatif") or None
    if whatif is not None and not (whatif.get("drop") or _num(whatif.get("interval"), "The what-if interval",
                                                                  positive=True)):
        raise FleetValidationError("A what-if drops the work, or stretches it to another interval.")
    return {"name": name, "every": every, "unit": unit, "effect": effect, "on_replace": on_replace,
            "impact_k": k, "grace": grace or 0.0, "whatif": whatif,
            "resets": on_replace == "restart",
            "hours_each": _num(raw.get("hours_each"), "The hours each time"),
            "cost_each": _num(raw.get("cost_each"), "The cost each time"),
            "spares_each": _num(raw.get("spares_each"), "The spares each time"),
            "spare_name": str(raw.get("spare_name") or "").strip()[:120] or None}


def _work_dates(work: dict, run: dict, hz: dict) -> list[date]:
    """The dates the work falls due from the start to the horizon's end, assumed just done at the
    start: RePyability's Task.due, on the calendar or through the running hours."""
    from backend.maintenance import schedule

    start, end = hz["start"], hz["end"]
    if work["unit"] == "hours":
        plan = (schedule.DutyPlan(schedule.Continuous()) if run["per"] == "all"
                else schedule.DutyPlan(schedule.Rate(run["hours"], run["per"])))
        usage = plan.forecast(start, end + timedelta(days=1))
        task = schedule.LibraryTask(work["name"], every=schedule.Usage(work["every"], "hours"), last_done=start,
                                    last_done_reading=0.0)
        return list(task.due(start, end, usage=usage).done)
    every = work["every"]
    if float(every).is_integer():
        rule = schedule.Recurrence.every(int(every), work["unit"], start)
    else:
        rule = schedule.Recurrence.every(max(1, round(every * CALENDAR_DAYS[work["unit"]])), "days", start)
    task = schedule.LibraryTask(work["name"], every=rule, last_done=start)
    return list(task.due(start, end).done)


def _in_life_unit(work: dict, life_unit: str, run: dict, use_per_day: float | None) -> float | None:
    """The work's interval in the life's unit (for a replacement at that age), or None."""
    w, life = work["unit"], _norm(life_unit)
    if w == "hours" and life in HOURS:
        return work["every"]
    if w != "hours" and life in CALENDAR_DAYS:
        return work["every"] * CALENDAR_DAYS[w] / CALENDAR_DAYS[life]
    if w == "hours" and life in CALENDAR_DAYS:
        return work["every"] / run["per_day"] / CALENDAR_DAYS[life]
    if w != "hours" and life in HOURS:
        return work["every"] * CALENDAR_DAYS[w] * run["per_day"]
    if use_per_day and w != "hours":
        return work["every"] * CALENDAR_DAYS[w] * use_per_day
    return None


# ---- a part that fails: the existing engine ------------------------------------------------------

def _part(raw: dict | None) -> dict | None:
    if not raw:
        return None
    if not raw.get("distribution_id") or not raw.get("params"):
        raise FleetValidationError("Pick a saved model, or choose a distribution and type its parameters.")
    unit = str(raw.get("unit") or "").strip()
    if not unit:
        raise FleetValidationError("Say the unit of the model's times (hours, days, cycles…).")
    return {"distribution_id": raw["distribution_id"], "params": raw["params"], "extras": raw.get("extras") or None,
            "unit": unit, "name": str(raw.get("name") or "Typed parameters")[:120], "raw": raw,
            "hours_if_fails": _num(raw.get("hours_if_fails"), "The hours a failure takes"),
            "cost_if_fails": _num(raw.get("cost_if_fails"), "The cost of a failure"),
            "spare_cost": _num(raw.get("spare_cost"), "The cost of a spare"),
            "use_per_day": _num(raw.get("use_per_day"), "The use a unit adds a day", positive=True)}


def _rate(part: dict, run: dict, hz: dict) -> float:
    """The use a unit adds in one period, in the life's unit."""
    unit = _norm(part["unit"])
    if unit in HOURS:
        return run["per_day"] * hz["period_days"]
    if unit in CALENDAR_DAYS:
        return hz["period_days"] / CALENDAR_DAYS[unit]
    if part["use_per_day"]:
        return part["use_per_day"] * hz["period_days"]
    raise FleetValidationError(f"This life is in {part['unit']}: say how many {part['unit']} a unit adds a day "
                               "(More options).")


def _restart_note(lines: list, work: dict, part: dict, run: dict) -> None:
    """Work that restarts when the part is replaced (forecast-rules 1.8): each replacement drops half an
    interval, so about interval ÷ (2 × the mean life) fewer. Said on the work's line; the count stays
    the scheduled one."""
    from backend.maintenance import restart as rs
    from backend.services.strategy import StrategyError, _model_from_params

    try:
        dist, _ = _model_from_params(part["distribution_id"], part["params"], part["extras"])
        mean = float(np.atleast_1d(dist.mean())[0])
    except (StrategyError, ValueError, TypeError):
        return
    every = _in_life_unit(work, part["unit"], run, part["use_per_day"])
    share = rs.shortfall(every, mean) if every is not None and math.isfinite(mean) else None
    line = next((x for x in lines if x["id"] == "work"), None)
    if share is None or line is None:
        return
    line["restart_share"] = _sig(share, 3)
    line["note"] = (f"Restarts when the part is replaced: about one fewer for each replacement, half the time "
                    f"(about {share:.1%} fewer); shown as scheduled." if share < rs.NOTE_BELOW else
                    f"Restarts when the part is replaced: about {share:.0%} fewer than scheduled; shown as "
                    "scheduled, as its exact range isn't worked out yet.")


def _life_bound(part: dict, ages: list[float], counts: list[int], rate_per_day: float) -> dict | None:
    """90% one-sided: the time with a 90% chance of no failure among the units, from now (each unit
    at its age; independent). {in_life_unit, days}, or None."""
    from scipy.optimize import brentq

    from backend.services.strategy import StrategyError, _model_from_params

    try:
        dist, _ = _model_from_params(part["distribution_id"], part["params"], part["extras"])
    except StrategyError:
        return None
    a = np.repeat(np.asarray(ages, dtype=float), counts)

    def log_none(t):
        with np.errstate(all="ignore"):
            s0 = np.asarray(dist.sf(a), dtype=float)
            s1 = np.asarray(dist.sf(a + t), dtype=float)
        if np.any(s0 <= 0):
            return -np.inf
        return float(np.sum(np.log(np.clip(s1, 1e-300, None)) - np.log(s0)))

    target = math.log(0.9)
    hi = 1.0
    while log_none(hi) > target and hi < 1e12:
        hi *= 4
    if hi >= 1e12:
        return None
    try:
        t = brentq(lambda x: log_none(x) - target, 0.0, hi, xtol=1e-9 * hi)
    except ValueError:
        return None
    return {"in_life_unit": _sig(t), "days": _sig(t / rate_per_day) if rate_per_day > 0 else None}


def _block(v) -> dict:
    v = v or {}
    iv = v.get("interval")
    return {"expected": _sig(v.get("expected")), "interval": [_sig(iv[0]), _sig(iv[1])] if iv else None}


def _scaled(b: dict, k: float | None) -> dict | None:
    if k is None or b is None:
        return None
    iv = b.get("interval")
    return {"expected": _sig((b.get("expected") or 0) * k), "interval": [_sig(iv[0] * k), _sig(iv[1] * k)] if iv else None}


def _plus(b: dict | None, certain: float) -> dict | None:
    """A chance plus a certain amount: the certain part added to both ends (forecast-rules 1.4)."""
    if b is None:
        return {"expected": _sig(certain), "interval": [_sig(certain), _sig(certain)]}
    iv = b.get("interval")
    return {"expected": _sig((b.get("expected") or 0) + certain),
            "interval": [_sig(iv[0] + certain), _sig(iv[1] + certain)] if iv else None}


def _worked_out(part: dict, ages, counts, rate: float, hz: dict, replace_at, work, body) -> dict | None:
    """The part's answer worked out (worked_part.py), in the shape of the saved-fleet engine's (strategy,
    views, per_item), or None with too many different ages to work out one by one."""
    from collections import Counter

    from backend.services import worked_part
    from backend.services.strategy import StrategyError, _model_from_params

    groups = Counter()
    for a, c in zip(ages, counts):
        groups[float(a)] += int(c)
    if len(groups) > worked_part.MAX_GROUPS:
        return None
    try:
        dist, _ = _model_from_params(part["distribution_id"], part["params"], part["extras"])
    except StrategyError as exc:
        return {"status": "error", "reason": str(exc)}
    n = hz["periods"]
    ends = rate * np.arange(1, n + 1)
    resets = True if work is None else work.get("resets", True)
    try:
        got = worked_part.forecast(dist, sorted(groups.items()), ends, replace_at, resets)
    except (ValueError, NotImplementedError) as exc:
        return {"status": "error", "reason": f"This model can't be worked out here: {exc}"}
    blk = worked_part.block
    sc = part["spare_cost"] or 0.0
    planned = replace_at is not None

    def row(j, k):
        return {"period": k + 1, "failures": blk(j, 1), "planned": blk(j, 0, 1), "parts": blk(j, 1, 1)}

    st = {"kind": "age" if planned else "run_to_failure", "replace_at": replace_at,
          "total": {"failures": blk(got["total"], 1), "planned": blk(got["total"], 0, 1),
                    "parts": blk(got["total"], 1, 1)},
          "per_period": [row(j, k) for k, j in enumerate(got["windows"])]}
    views: dict = {}
    hf, hp = part["hours_if_fails"], (work or {}).get("hours_each") if planned else None
    if hf is not None or hp is not None:
        a, b = hf or 0.0, hp or 0.0
        views["hours"] = {"total": blk(got["total"], a, b),
                          "per_period": [{"period": k + 1, "hours": blk(j, a, b)} for k, j in enumerate(got["windows"])]}
    cf, cp = part["cost_if_fails"], (work or {}).get("cost_each") if planned else None
    if cf is not None or sc or cp is not None:
        a, b = (cf or 0.0) + sc, ((cp or 0.0) + sc) if planned else 0.0
        views["costs"] = {"total": blk(got["total"], a, b),
                          "per_period": [{"period": k + 1, "cost": blk(j, a, b)} for k, j in enumerate(got["windows"])]}
    return {"status": "ok", "interval_method": "exact", "strategy": st, "views": views,
            "per_item": [{"prob_any": worked_part.chance_any(got["total"]), "count": 1}],
            "period_label": hz["period_label"], "periods": n, "model_name": part["name"], "unit": part["unit"],
            "settings": {"period_label": hz["period_label"], "periods": n}, "items": []}


def quick_forecast(body: dict) -> dict:
    """See ``_one``. Work that keeps the part on its life (effect supports) with an impact also gets its
    worth (the part's failures with the work dropped, against as planned) and, with a what-if (dropped
    or stretched), the answer with that change beside it (support_whatif.py: the averaged hazard ratio,
    "approximate" past 20% of the mean life). Nothing is saved."""
    from backend.maintenance import support_whatif

    out = _one(body)
    raw = (body or {}).get("work") or {}
    if out.get("status") != "ok" or raw.get("effect") != "supports" or not (body or {}).get("part"):
        return out
    k = _num(raw.get("impact_k"), "The impact")
    support = {"impact": {"k": k} if k else None, "reference": {"value": raw.get("every")},
               "grace": raw.get("grace") or 0}

    def scenario(plan):
        got = support_whatif.multiplier(support, float(raw["every"]), plan)
        part = dict(body["part"])
        part["extras"] = {**(part.get("extras") or {}), "hr": float((part.get("extras") or {}).get("hr") or 1.0)
                          * got["mult"]}
        work = None if plan.get("drop") else {**raw, "every": plan.get("interval") or raw["every"], "whatif": None}
        alt = _one({**body, "part": part, "work": work})
        approx = False
        if got["interval"] is not None and got["overdue_share"] < 1.0:
            mean = _part_mean(part)
            every = _in_life_unit({"every": got["interval"], "unit": _norm(raw.get("unit") or "hours")},
                                  part.get("unit"), _running(body.get("running")), part.get("use_per_day"))
            approx = bool(mean and every is not None and every / mean > support_whatif.APPROX_SHARE)
        return alt, {**got, "approximate": approx}

    if k:
        dropped, _ = scenario({"drop": True})
        out["worth"] = _quick_worth(out, dropped)
    plan = support_whatif.plan_of({"w": raw.get("whatif")}, "w") if raw.get("whatif") else None
    if plan:
        alt, ratio = scenario(plan)
        out["whatif"] = {"plan": plan, "lines": alt.get("lines"), "totals": alt.get("totals"), "rows": alt.get("rows"),
                         "ratio": ratio, "approximate": ratio["approximate"]}
    return out


def _part_mean(part: dict) -> float | None:
    from backend.services.strategy import StrategyError, _model_from_params

    try:
        dist, _ = _model_from_params(part["distribution_id"], part["params"], part.get("extras"))
        mean = float(np.atleast_1d(dist.mean())[0])
    except (StrategyError, ValueError, TypeError, KeyError):
        return None
    return mean if math.isfinite(mean) and mean > 0 else None


def _quick_worth(base: dict, dropped: dict) -> dict:
    """The work's worth: the part's failures (and their cost) it avoids for its own cost. A comparison."""
    def side(out):
        line = next((x for x in out.get("lines") or [] if x["owner_kind"] == "failure"), None) or {}
        return (float((line.get("times") or {}).get("expected") or 0.0),
                (line.get("cost") or {}).get("expected"))

    n0, c0 = side(base)
    n1, c1 = side(dropped)
    work = next((x for x in base.get("lines") or [] if x["owner_kind"] == "task"), None) or {}
    own = (work.get("cost") or {}).get("expected")
    out = {"avoids_failures": _sig(n1 - n0, 4), "avoids_cost": _sig(c1 - c0) if c0 is not None and c1 is not None else None,
           "costs": own}
    if out["avoids_cost"] is not None and own is not None:
        out["words"] = f"Worth: avoids about ${c1 - c0:,.0f} of failures for ${own:,.0f}"
    elif out["avoids_cost"] is not None:
        out["words"] = f"Worth: avoids about ${c1 - c0:,.0f} of failures"
    else:
        out["words"] = f"Worth: avoids about {n1 - n0:.2g} failures (no cost if it fails, so not in money)"
    return out


def _one(body: dict) -> dict:
    """See the module docstring. {units?, running? {hours, per: day | week} | {all_the_time}, months
    (12, 24, 36 or 60), start? (a date; default today), work? {name, every, unit, effect (none |
    replaces), hours_each?, cost_each?, spares_each?, spare_name?}, part? {distribution_id, params,
    extras?, unit, name?, age or ages, hours_if_fails?, cost_if_fails?, spare_cost?, use_per_day?},
    spares? (stock to hold: as the scratch forecast)}: lines, totals per view and rows by period."""
    body = body or {}
    work, part = _work(body.get("work")), _part(body.get("part"))
    if work is None and part is None:
        raise FleetValidationError("Fill in at least one: work on a schedule, or a part that fails.")
    run = _running(body.get("running"))
    hz = _horizon(body)
    units = _units(body)
    ages = counts = None
    if part is not None:
        ages, n_ages = _ages(body, part)
        if n_ages > 1:
            units = n_ages
            counts = [1] * n_ages
        else:
            counts = [units]
    n = hz["periods"]
    notes = []
    lines: list[dict] = []
    per_period = [{"period": k + 1, "work": 0.0, "failures": 0.0, "planned": 0.0, "hours": 0.0, "cost": 0.0}
                  for k in range(n)]
    certain = {"hours": 0.0, "cost": 0.0}
    gaps = {"hours": [], "cost": [], "spares": []}
    spares = []
    engine = None

    # A replacement at the work's interval goes through the engine; any other work is certain.
    replace_at = None
    if work is not None and work["effect"] == "replaces":
        if part is None:
            raise FleetValidationError("Work that replaces the part needs a part that fails: add one, or say the work "
                                       "doesn't change the part's life.")
        replace_at = _in_life_unit(work, part["unit"], run, part["use_per_day"])
        if replace_at is None:
            raise FleetValidationError(f"The work goes by {work['unit']} and the life by {part['unit']}: give the work "
                                       "in the life's unit to replace the part at that age.")

    if work is not None and replace_at is None:
        dates = _work_dates(work, run, hz)
        each = len(dates)
        times = each * units
        for d in dates:
            k = min(n - 1, int((d - hz["start"]).days // hz["period_days"]))
            per_period[k]["work"] += units
        line = {"id": "work", "owner": work["name"], "owner_kind": "task", "kind": "planned", "number": "certain",
                "times": {"expected": times, "interval": None, "each_unit": each},
                "every": {"value": work["every"], "unit": work["unit"]},
                "first": dates[0].isoformat() if dates else None, "last": dates[-1].isoformat() if dates else None,
                "hours": None, "cost": None, "spares": None, "gaps": []}
        for key, view, word in (("hours_each", "hours", "no hours each time"), ("cost_each", "cost", "no cost each time"),
                                ("spares_each", "spares", "no spares each time")):
            if work[key] is None:
                line["gaps"].append({"view": view, "text": word})
                gaps[view].append(f"{work['name']} ({word})")
            else:
                amount = times * work[key]
                line[view] = {"expected": _sig(amount), "interval": None}
                if view in certain:
                    certain[view] += amount
                    for k, row in enumerate(per_period):
                        row[view] += row["work"] * work[key]
        if work["spares_each"] is not None:
            spares.append({"name": work["spare_name"] or f"spares for {work['name']}", "owner": work["name"],
                           "expected": _sig(times * work["spares_each"]), "interval": None, "number": "certain"})
        lines.append(line)
        notes.append(f"{work['name']}: assumed just done at the start, then every {work['every']:g} {work['unit']}"
                     + (f", through the running hours ({run['text']})" if work["unit"] == "hours" else
                        " on the calendar") + ".")

    if part is not None:
        rate = _rate(part, run, hz)
        scratch = {"distribution_id": part["distribution_id"], "params": part["params"], "extras": part["extras"],
                   "unit": part["unit"], "name": part["name"],
                   "ages": ages[0] if len(ages) == 1 else ages, "units": units if len(ages) == 1 else len(ages),
                   "rate": rate, "periods": n, "period_label": hz["period_label"],
                   "strategy": "age" if replace_at is not None else "run_to_failure", "replace_at": replace_at,
                   "failure_cost": part["cost_if_fails"], "corrective_hours": part["hours_if_fails"],
                   "planned_cost": work["cost_each"] if replace_at is not None else None,
                   "planned_hours": work["hours_each"] if replace_at is not None else None,
                   "spare_cost": part["spare_cost"], "spares": body.get("spares")}
        engine = _worked_out(part, ages, counts, rate, hz, replace_at, work, body)
        if engine is None:
            # Too many different ages to work out one by one: the saved-fleet engine's seeded runs.
            engine = fleet_service.scratch_forecast(scratch)
        elif body.get("spares"):
            # Stock to hold keeps its own statement (the service level), from the engine's runs.
            got = fleet_service.scratch_forecast(scratch)
            engine["spares"], engine["settings"] = got.get("spares"), got.get("settings")
        if engine.get("status") != "ok":
            return {"status": "error", "reason": engine.get("reason") or "This model can't be forecast here."}
        st = engine.get("strategy") or {}
        exact = engine.get("interval_method") == "exact"
        number = "worked out" if exact else "simulated"
        sims = engine.get("sims")
        method = ("Worked out exactly, not simulated" if exact else
                  f"Simulated: {sims:,} seeded runs, the same every time" if sims else "Simulated")
        failures = _block((st.get("total") or {}).get("failures"))
        per_item = engine.get("per_item") or []
        none = 1.0
        weights = [1] * len(per_item) if exact and len(per_item) == 1 else (
            counts if len(per_item) == len(counts) else [1] * len(per_item))
        for row, c in zip(per_item, weights):
            p = row.get("prob_any")
            if p is None:
                none = None
                break
            none *= (1.0 - float(p)) ** c
        prob_any = _sig(1.0 - none, 3) if none is not None else None
        spare_each = part["spare_cost"] or 0.0
        for r, row in zip(st.get("per_period") or [], per_period):
            row["failures"] = float(r["failures"]["expected"])
            row["planned"] = float((r.get("planned") or {}).get("expected") or 0.0)
        views = engine.get("views") or {}
        hours_view, cost_view = views.get("hours"), views.get("costs")
        fail_line = {"id": "failures", "owner": part["name"], "owner_kind": "failure", "kind": "corrective",
                     "number": number, "method": method, "times": {**failures, "probability": prob_any},
                     "hours": _scaled(failures, part["hours_if_fails"]),
                     "cost": _scaled(failures, (part["cost_if_fails"] + spare_each) if part["cost_if_fails"] is not None
                                     else (spare_each or None)),
                     "spares": dict(failures), "gaps": []}
        if part["hours_if_fails"] is None:
            fail_line["gaps"].append({"view": "hours", "text": "no hours if it fails, so the hours to put failures "
                                                              "right are unknown"})
            gaps["hours"].append(f"{part['name']} failures (no hours if it fails)")
        if part["cost_if_fails"] is None:
            text = ("no cost if it fails, so the failure cost is unknown" + (" (only the spares are counted)"
                                                                            if part["spare_cost"] else ""))
            fail_line["gaps"].append({"view": "cost", "text": text})
            gaps["cost"].append(f"{part['name']} failures (no cost if it fails)")
        if replace_at is not None:
            planned = _block((st.get("total") or {}).get("planned"))
            plan_line = {"id": "work", "owner": work["name"], "owner_kind": "task", "kind": "planned",
                         "number": number, "method": method, "times": planned,
                         "every": {"value": work["every"], "unit": work["unit"]}, "replaces": True,
                         "replace_at": {"value": _sig(replace_at), "unit": part["unit"]},
                         "hours": _scaled(planned, work["hours_each"]),
                         "cost": _scaled(planned, (work["cost_each"] or 0.0) + spare_each
                                         if work["cost_each"] is not None else (spare_each or None)),
                         "spares": dict(planned), "gaps": []}
            for key, view, word in (("hours_each", "hours", "no hours each time"),
                                    ("cost_each", "cost", "no cost each time")):
                if work[key] is None:
                    plan_line["gaps"].append({"view": view, "text": word})
                    gaps[view].append(f"{work['name']} ({word})")
            lines.append(plan_line)
            notes.append(f"{work['name']} replaces the part at {_sig(replace_at):g} {part['unit']} of age, and its "
                         "clock starts again after a failure (age replacement): how many times it's done is a chance."
                         if work["resets"] else
                         f"{work['name']} replaces the part every {_sig(replace_at):g} {part['unit']} on its schedule, "
                         "failures or not (block replacement).")
        lines.append(fail_line)
        parts_total = _block((st.get("total") or {}).get("parts"))
        spares.append({"name": f"replacement part ({part['name']})", "owner": part["name"], **parts_total,
                       "number": number})
        # The view totals from the engine's runs (one set of runs, so its range is joint).
        chance = {"hours": _block(hours_view.get("total")) if hours_view else None,
                  "cost": _block(cost_view.get("total")) if cost_view else None}
        for view, v in (("hours", hours_view), ("cost", cost_view)):
            for r, row in zip((v or {}).get("per_period") or [], per_period):
                row[view] += float(((r.get(view if view == "hours" else "cost")) or {}).get("expected") or 0.0)
        bound = None
        if replace_at is None:
            per_day = rate / hz["period_days"]
            bound = _life_bound(part, ages, counts, per_day)
            if work is not None and work["resets"]:
                _restart_note(lines, work, part, run)
        notes.append("A failed unit is replaced at once with a like one, which can fail again inside the horizon.")
    else:
        chance = {"hours": None, "cost": None}
        method, prob_any, bound = None, None, None

    def total(view: str) -> dict | None:
        has_any = any(line.get(view) is not None for line in lines)
        if not has_any:
            return {"expected": None, "interval": None, "known": False, "leaves_out": gaps[view]} if gaps[view] else None
        block = _plus(chance[view], certain[view]) if chance[view] is not None or certain[view] else None
        if block is None:
            block = {"expected": 0.0, "interval": [0.0, 0.0]}
        return {**block, "known": not gaps[view], "leaves_out": gaps[view]}

    totals = {"hours": total("hours"), "cost": total("cost"),
              "spares": {"items": spares, "known": not gaps["spares"], "leaves_out": gaps["spares"]}}
    rows = [{**r, "hours": _sig(r["hours"]), "cost": _sig(r["cost"]), "failures": _sig(r["failures"]),
             "planned": _sig(r["planned"]), "work": _sig(r["work"])} for r in per_period]
    by_period = engine.get("views") if engine else None
    return {
        "status": "ok", "saved": False, "units": units,
        "start": hz["start"].isoformat(), "end": hz["end"].isoformat(), "months": hz["months"],
        "period_label": hz["period_label"], "periods": n,
        "running": {"text": run["text"], "assumed": run["assumed"], "per_day": _sig(run["per_day"])},
        "range": RANGE_WORDS, "range_level": 0.9,
        "lines": lines, "totals": totals, "rows": rows,
        "probability_any": prob_any, "no_failure_before": bound,
        "notes": notes,
        # The part's engine answer as it was (stock to hold, when next, ranges by period).
        "part": ({k: v for k, v in engine.items() if k != "views"} | {"views": by_period}) if engine else None,
    }
