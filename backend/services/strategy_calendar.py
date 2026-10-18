"""Replacement over a calendar of shutdowns (Strategy › Replacement, "Shutdown
calendar").

Age replacement assumes a planned replacement costs the same on any day. In a
plant with shuts it doesn't: replacing a part in the annual shut is cheap, in
a quarterly shut dearer, between shuts dearer still, and at a failure dearest.
RePyability (0.15+) works out the long-run best rule for that: at each
opportunity, replace the part if it is at least a threshold age, the threshold
depending on when the next cheaper chance comes
(``NonRepairable.optimal_calendar_policy``, its use case UC-13), and, for the
unit in service, whether to replace it now, at a coming shut or later
(``optimal_next_replacement``, UC-12).

RePyability works in model time from 0; laying the shuts on real dates is the
app's job, and it is done here with one convention: **today is time 0**, at
the start of the day, and a model in hours, days, weeks, months or years
converts at 24 hours, 7 days, 365.25 / 12 days and 365.25 days. A shut "every
6 months from 1 March" is periodic in model time (an average month), and is
shown on its real calendar dates.

Methods: ``dp`` (dynamic programming on a grid, exact for the grid) and
``integration`` (continuous time between shuts, only with no replacement
between them) are exact and free; ``sampling`` (the cost rate sampled over a
cycle too long to sweep, with a standard error) is a Pro calculation that runs
on the compute service. ``auto`` is never used here: RePyability's ``auto``
can turn into sampling on a long cycle, and a free request must never do that.

This module must not import the database layer: the compute service runs
:func:`calendar_replacement` on a self-contained request.
"""

from __future__ import annotations

import calendar as _calendar
import json
import math
import re
import threading
import warnings
from collections import OrderedDict
from datetime import date, timedelta
from typing import Any, Optional

import numpy as np

from backend.services.strategy import StrategyError, _model_from_params, fmt_num
from backend.units import canonical_unit, normalize_unit, unit_in_text
from backend.fitting import surpyval_extras
from repyability import Calendar, NonRepairable, Opportunity

#: Model units a date converts to, per day.
UNITS_PER_DAY = {
    "second": 86_400.0,
    "minute": 1_440.0,
    "hour": 24.0,
    "day": 1.0,
    "week": 1.0 / 7.0,
    "month": 12.0 / 365.25,
    "year": 1.0 / 365.25,
}
#: An opportunity's "every N <unit>" in days (months: an average month).
EVERY_DAYS = {"day": 1.0, "week": 7.0, "month": 365.25 / 12.0, "year": 365.25}

METHODS = ("dp", "integration", "sampling")
FREE_METHODS = ("dp", "integration")
METHOD_LABELS = {
    "dp": "Exact on a fine time grid",
    "integration": "Exact in continuous time",
    "sampling": "Sampled over the calendar's cycle",
}

MAX_OPPORTUNITIES = 8
MAX_DATES = 200
MAX_NAME = 60
MAX_HORIZON_MONTHS = 60
DEFAULT_HORIZON_MONTHS = 12
MC_SAMPLES_DEFAULT = 64
MC_SAMPLES_RANGE = (8, 256)
#: Sampling draws from a fixed seed unless given one: the same inputs give the
#: same answer (and the job cache can reuse it).
DEFAULT_SEED = 20_261_022
MAX_SCHEDULE_ROWS = 400
#: A kind whose long-run chance of a replacement is below this at every one
#: of its times in the window is "not used" in the plain-words rule.
_USED = 1e-3
#: Names RePyability gives kinds of its own.
_RESERVED = ("anytime", "failure")

CONVENTION = ("Today is time 0. Dates become model time at 24 hours, 7 days, 365.25/12 days (a month) or "
              "365.25 days (a year) per unit.")


# ---------------------------------------------------------------------------
# Inputs: dates to model time
# ---------------------------------------------------------------------------


def units_per_day(unit: Optional[str]) -> float:
    """Model time units in a day, for a time unit; StrategyError otherwise."""
    key = normalize_unit(unit)
    if key is None:
        raise StrategyError("Choose the model's time unit (hours, days, weeks, months or years): the shut dates "
                            "are turned into model time with it.")
    if key not in UNITS_PER_DAY:
        raise StrategyError(f"A shutdown calendar needs a model in a unit of time (hours, days, weeks, months or "
                            f"years); this one is in {unit_in_text(unit)}, which dates can't be turned into.")
    return UNITS_PER_DAY[key]


def _parse_date(value, label: str) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except (TypeError, ValueError):
        raise StrategyError(f"{label}: '{value}' isn't a date (use YYYY-MM-DD).") from None


def say_date(d) -> str:
    """A date for a sentence: "17 Mar 2027"."""
    d = date.fromisoformat(d) if isinstance(d, str) else d
    return f"{d.day} {d:%b %Y}"


def _number(value, label: str, *, lo: float = 0.0, strict: bool = False) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise StrategyError(f"{label} must be a number.") from None
    if not math.isfinite(v) or v < lo or (strict and v <= lo):
        raise StrategyError(f"{label} must be {'more than' if strict else 'at least'} {lo:g}.")
    return v


def add_months(d: date, months: int) -> date:
    """``d`` moved by whole calendar months, kept to the month's last day."""
    total = d.month - 1 + months
    year, month = d.year + total // 12, total % 12 + 1
    return date(year, month, min(d.day, _calendar.monthrange(year, month)[1]))


def _every_unit(value) -> str:
    key = normalize_unit(value) or ""
    if key not in EVERY_DAYS:
        raise StrategyError(f"'every' takes days, weeks, months or years; got '{value}'.")
    return key


def parse_opportunities(raw: Any, today: date, per_day: float) -> list[dict]:
    """The opportunities as given (name, cost, and either ``every`` +
    ``every_unit`` + ``start`` or ``dates``), checked and laid on model
    time: each with ``period`` / ``offset`` or ``times`` in model units."""
    if raw is None:
        raw = []
    if not isinstance(raw, list):
        raise StrategyError("opportunities must be a list.")
    if len(raw) > MAX_OPPORTUNITIES:
        raise StrategyError(f"At most {MAX_OPPORTUNITIES} kinds of shut; this has {len(raw)}.")
    out, names = [], set()
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise StrategyError("Each opportunity must be an object with a name and a cost.")
        name = str(item.get("name") or "").strip()
        if not name:
            raise StrategyError(f"Opportunity {i + 1} needs a name.")
        if len(name) > MAX_NAME:
            raise StrategyError(f"'{name[:20]}…': names are at most {MAX_NAME} characters.")
        if name.lower() in _RESERVED:
            raise StrategyError(f"'{name}' is a name Reliafy uses itself: call the shut something else.")
        if name.lower() in names:
            raise StrategyError(f"Two shuts are called '{name}': give each its own name.")
        names.add(name.lower())
        if item.get("cost") is None or item.get("cost") == "":
            raise StrategyError(f"Enter what replacing the part at '{name}' costs.")
        cost = _number(item.get("cost"), f"The cost at '{name}'")
        dates = item.get("dates")
        every = item.get("every")
        if dates not in (None, []) and every not in (None, ""):
            raise StrategyError(f"'{name}': give either 'every' with a start date, or a list of dates, not both.")
        if dates not in (None, []):
            if not isinstance(dates, list):
                raise StrategyError(f"'{name}': dates must be a list of YYYY-MM-DD dates.")
            if len(dates) > MAX_DATES:
                raise StrategyError(f"'{name}': at most {MAX_DATES} dates.")
            parsed = sorted({_parse_date(d, f"'{name}'") for d in dates})
            past = [d for d in parsed if d < today]
            kept = [d for d in parsed if d >= today]
            if not kept:
                raise StrategyError(f"'{name}': every date is before today ({today.isoformat()}); "
                                    "give the shuts still to come.")
            out.append({
                "name": name, "cost": cost, "kind": "dates",
                "dates": [d.isoformat() for d in kept], "past_dates_dropped": len(past),
                "times": [(d - today).days * per_day for d in kept],
            })
            continue
        if every in (None, ""):
            raise StrategyError(f"'{name}': say how often it comes ('every' and a unit, from a start date) or "
                                "list its dates.")
        n = _number(every, f"'{name}': every", strict=True)
        unit = _every_unit(item.get("every_unit") or "days")
        start = _parse_date(item.get("start") or today.isoformat(), f"'{name}' start")
        period_days = n * EVERY_DAYS[unit]
        out.append({
            "name": name, "cost": cost, "kind": "every",
            "every": n, "every_unit": unit, "start": start.isoformat(),
            "period": period_days * per_day,
            "offset": (start - today).days * per_day,
        })
    return out


def build_calendar(specs: list[dict], failure_cost: float, anytime_cost: Optional[float]) -> Calendar:
    opportunities = []
    for s in specs:
        if s["kind"] == "dates":
            opportunities.append(Opportunity(s["name"], s["cost"], dates=s["times"]))
        else:
            opportunities.append(Opportunity(s["name"], s["cost"], period=s["period"], offset=s["offset"]))
    try:
        return Calendar(opportunities, failure=failure_cost, anytime=anytime_cost)
    except (TypeError, ValueError) as exc:
        raise StrategyError(str(exc)) from None


def _occurrences(spec: dict, today: date, until: date) -> list[date]:
    """A spec's own calendar dates from today up to ``until`` (a month-based
    shut on its real dates, not the average month the model uses)."""
    if spec["kind"] == "dates":
        return [d for d in (date.fromisoformat(x) for x in spec["dates"]) if d < until]
    start = date.fromisoformat(spec["start"])
    n, unit = spec["every"], spec["every_unit"]
    out: list[date] = []
    if unit in ("month", "year") and float(n).is_integer():
        step = int(n) * (12 if unit == "year" else 1)
        # The first occurrence on or after today, counting from the start both ways.
        k = math.floor(((today.year - start.year) * 12 + today.month - start.month) / step) - 1
        while len(out) < 5000:
            d = add_months(start, k * step)
            if d >= until:
                break
            if d >= today:
                out.append(d)
            k += 1
        return out
    period = n * EVERY_DAYS[unit]
    k = math.ceil(((today - start).days) / period)
    while len(out) < 5000:
        d = start + timedelta(days=round(k * period))
        if d >= until:
            break
        if d >= today:
            out.append(d)
        k += 1
    return out


# ---------------------------------------------------------------------------
# The policy
# ---------------------------------------------------------------------------


_CACHE: "OrderedDict[str, Any]" = OrderedDict()
_CACHE_SIZE = 8
_CACHE_LOCK = threading.Lock()


def _max_age(extras: Optional[dict], max_age: Optional[float]) -> Optional[float]:
    """The oldest age on the grid, if given. A limited failure population
    (some units never fail) is refused: RePyability sizes the calendar's
    settling span from the age a unit outlives with a small chance, which
    such a life never falls to."""
    if surpyval_extras(extras).get("lfp_p", 1.0) < 1.0:
        raise StrategyError("This model has a limited failure population (some units never fail), which the "
                            "shutdown calendar can't take yet. Plain age replacement handles it.")
    if max_age not in (None, ""):
        return _number(max_age, "The oldest age", strict=True)
    return None


def _solve(part: NonRepairable, cal: Calendar, *, method: str, max_age, mc_samples: int, seed: int):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            policy = part.optimal_calendar_policy(cal, max_age=max_age, method=method,
                                                  mc_samples=mc_samples, seed=seed)
        except (ValueError, TypeError, NotImplementedError) as exc:
            raise StrategyError(_library_message(str(exc))) from None
    notes, moved = [], []
    for w in caught:
        text = str(w.message)
        if not text or issubclass(w.category, DeprecationWarning):
            continue
        if "not on the grid" in text:
            # A date laid on the calculation's grid: say it once, plainly.
            found = re.search(r"moved by up to ([0-9.eE+-]+)", text)
            if found:
                moved.append(float(found.group(1)))
            continue
        if text not in notes:
            notes.append(text)
    if moved:
        notes.append(f"Shut times are placed on the calculation's time grid, each within {fmt_num(max(moved))} "
                     "model time units of its date.")
    return policy, notes


def _library_message(text: str) -> str:
    """RePyability's refusals in the app's words, where they name its API."""
    if "give max_age" in text:
        return ("Some units of this model never fail, so the calculation needs the oldest age to consider: "
                "enter a maximum age.")
    if "integration" in text.lower() and "any day" in text.lower():
        return ("The continuous-time method works only with no replacement between shuts: clear the 'any day' "
                "cost, or use the grid method.")
    if "sampling" in text.lower() and "date" in text.lower():
        return "Sampling is for repeating shuts with a very long cycle; shuts on given dates use the grid method."
    return text


def _policy_key(distribution_id, params, extras, cal_specs, failure_cost, anytime_cost, max_age, method) -> str:
    return json.dumps([distribution_id, params, extras or {}, cal_specs, failure_cost, anytime_cost, max_age,
                       method], sort_keys=True, default=str)


def cached_policy(key: str, build):
    """An exact policy, kept for a few requests: "one unit now" asks again
    about the calendar just worked out."""
    with _CACHE_LOCK:
        if key in _CACHE:
            _CACHE.move_to_end(key)
            return _CACHE[key]
    found = build()
    with _CACHE_LOCK:
        _CACHE[key] = found
        while len(_CACHE) > _CACHE_SIZE:
            _CACHE.popitem(last=False)
    return found


class _Inputs:
    """A request's inputs, checked and laid on model time."""

    def __init__(self, distribution_id, params, *, unit, opportunities=None, failure_cost=None, anytime_cost=None,
                 max_age=None, method="dp", mc_samples=None, seed=None, today=None, extras=None,
                 horizon_months=None):
        if failure_cost is None or failure_cost == "":
            raise StrategyError("Enter what a failure (an unplanned replacement) costs.")
        self.failure_cost = _number(failure_cost, "The failure cost", strict=True)
        self.anytime_cost = None if anytime_cost in (None, "") else _number(anytime_cost, "The any-day cost")
        self.method = str(method or "dp").strip().lower()
        if self.method == "auto":
            self.method = "dp"
        if self.method not in METHODS:
            raise StrategyError(f"method must be one of {', '.join(METHODS)}.")
        self.unit = canonical_unit(unit)
        self.per_day = units_per_day(unit)
        self.today = _parse_date(today, "today") if today else date.today()
        self.specs = parse_opportunities(opportunities, self.today, self.per_day)
        if not self.specs and self.anytime_cost is None:
            raise StrategyError("Add at least one shut, or a cost for replacing on any day.")
        self.distribution_id = distribution_id
        self.params = params or []
        self.extras = extras or None
        self.model, self.distribution = _model_from_params(distribution_id, self.params, extras)
        self.max_age = _max_age(extras, max_age)
        if self.method == "sampling":
            n = int(_number(mc_samples if mc_samples not in (None, "") else MC_SAMPLES_DEFAULT, "mc_samples"))
            lo, hi = MC_SAMPLES_RANGE
            if not lo <= n <= hi:
                raise StrategyError(f"mc_samples must be between {lo} and {hi}.")
            self.mc_samples = n
            self.seed = int(_number(seed, "seed")) if seed not in (None, "") else DEFAULT_SEED
        else:
            self.mc_samples, self.seed = MC_SAMPLES_DEFAULT, None
        months = DEFAULT_HORIZON_MONTHS if horizon_months in (None, "") else int(
            _number(horizon_months, "horizon_months", strict=True))
        self.horizon_months = min(months, MAX_HORIZON_MONTHS)
        self.calendar = build_calendar(self.specs, self.failure_cost, self.anytime_cost)

    def model_time(self, d: date) -> float:
        return (d - self.today).days * self.per_day

    def to_date(self, t: float) -> date:
        return self.today + timedelta(days=int(round(t / self.per_day)))

    def per_year(self, rate: Optional[float]) -> Optional[float]:
        return None if rate is None else rate * self.per_day * 365.25

    def policy(self):
        """The policy (cached when exact) and the notes the library gave."""
        part = NonRepairable(self.model)

        def build():
            return _solve(part, self.calendar, method=self.method, max_age=self.max_age,
                          mc_samples=self.mc_samples, seed=self.seed or 0)

        if self.method == "sampling":
            return build()
        cal_specs = [{k: v for k, v in s.items() if k in ("name", "cost", "period", "offset", "times")}
                     for s in self.specs]
        key = _policy_key(self.distribution_id, self.params, self.extras, cal_specs, self.failure_cost,
                          self.anytime_cost, self.max_age, self.method)
        return cached_policy(key, build)


# ---------------------------------------------------------------------------
# The answer
# ---------------------------------------------------------------------------


def _finite(v) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _comparisons(inp: _Inputs, policy) -> list[dict]:
    """What simpler rules cost: running to failure, age replacement ignoring
    the shuts (with an any-day price), and replacing at every shut of a kind."""
    model, cal = inp.model, inp.calendar
    out = []
    mean = None
    if surpyval_extras(inp.extras).get("lfp_p", 1.0) >= 1.0:
        try:
            mean = _finite(np.atleast_1d(model.mean())[0])
        except Exception:  # noqa: BLE001
            mean = None
    part = NonRepairable(model)
    if mean and mean > 0:
        rtf = inp.failure_cost / mean
    else:
        rtf = _rule_cost(part, cal, {}, inp.max_age)
    out.append({"policy": "run_to_failure", "label": "Run to failure", "cost_rate": rtf})
    if inp.anytime_cost is not None and inp.anytime_cost < inp.failure_cost:
        age_part = NonRepairable(model, planned_cost=inp.anytime_cost, unplanned_cost=inp.failure_cost)
        try:
            found = age_part.optimal_replacement_policy()
            interval, rate = _finite(found.interval), _finite(found.cost_rate)
        except Exception:  # noqa: BLE001 - no optimum (no wear-out): it is running to failure
            interval, rate = None, None
        if interval is not None and rate is not None:
            out.append({"policy": "age", "label": f"Age replacement at {fmt_num(interval)} "
                        f"{unit_in_text(inp.unit)}, ignoring the shuts", "age": interval, "cost_rate": rate})
    for s in inp.specs:
        rate = _rule_cost(part, cal, {s["name"]: 0.0}, inp.max_age)
        out.append({"policy": "every", "kind": s["name"], "label": f"Replace at every {s['name']}",
                    "cost_rate": rate})
    for row in out:
        row["cost_per_year"] = inp.per_year(row["cost_rate"])
        row["vs_optimal"] = (None if not row["cost_rate"] or not policy.cost_rate
                             else row["cost_rate"] / policy.cost_rate - 1.0)
    return out


def _rule_cost(part, cal, rule: dict, max_age) -> Optional[float]:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return _finite(part.calendar_policy_cost(cal, rule, max_age=max_age))
    except (ValueError, TypeError, NotImplementedError):
        return None


def _schedule(inp: _Inputs, policy, until_date: date) -> tuple[list[dict], dict]:
    """The opportunities from today to ``until_date`` with their thresholds,
    chances and dates, and each kind's thresholds and total chance."""
    until = inp.model_time(until_date)
    if until <= 0 or not inp.specs:
        return [], {}
    rows = policy.schedule(kinds=tuple(s["name"] for s in inp.specs), until=until)
    occurrences = {s["name"]: _occurrences(s, inp.today, until_date + timedelta(days=2)) for s in inp.specs}
    prices = {s["name"]: s["cost"] for s in inp.specs}
    # How far a shut's own date may be from its model time: the grid's half
    # step for dates; an average month's drift from the calendar's (up to a
    # few days a year) for a shut every N months.
    slack = {s["name"]: (2.0 if s["kind"] == "dates" else max(2.0, 0.4 * s["period"] / inp.per_day))
             for s in inp.specs}
    out, by_kind = [], {}
    for t, kind, threshold, chance in rows:
        days = t / inp.per_day
        near = occurrences.get(kind) or []
        on = min(near, key=lambda d: abs((d - inp.today).days - days)) if near else None
        if on is None or abs((on - inp.today).days - days) > slack.get(kind, 2.0):
            on = inp.to_date(t)
        thr = _finite(threshold)
        if thr is not None and inp.max_age is not None and thr >= inp.max_age:
            thr = None
        row = {"time": t, "date": on.isoformat(), "kind": kind, "price": prices.get(kind),
               "threshold": thr, "chance": _finite(chance)}
        out.append(row)
        k = by_kind.setdefault(kind, {"thresholds": [], "chance": 0.0, "count": 0, "max_chance": 0.0})
        k["count"] += 1
        if thr is not None:
            k["thresholds"].append(thr)
        c = row["chance"] or 0.0
        k["chance"] += c
        k["max_chance"] = max(k["max_chance"], c)
    return out[:MAX_SCHEDULE_ROWS], by_kind


def _anytime_threshold(inp: _Inputs, policy) -> Optional[tuple[float, float]]:
    """The youngest and oldest age at which the policy replaces on a day with
    no shut, over a year (None where it never does)."""
    if inp.anytime_cost is None:
        return None
    until = 365.25 * inp.per_day
    if policy.step is not None and until / policy.step > 50_000:
        return None
    try:
        rows = policy.schedule(kinds=("anytime",), until=until)
    except ValueError:
        return None
    ages = [_finite(r[2]) for r in rows if r[1] == "anytime"]
    ages = [a for a in ages if a is not None and (inp.max_age is None or a < inp.max_age)]
    return (min(ages), max(ages)) if ages else None


def _age_text(lo: float, hi: float, unit: str) -> str:
    u = unit_in_text(unit)
    if hi - lo <= max(1e-9, 0.02 * hi):
        return f"{fmt_num(lo)} {u}".strip()
    return f"{fmt_num(lo)}–{fmt_num(hi)} {u}".strip()


def _rule_lines(inp: _Inputs, policy, by_kind: dict, anytime: Optional[tuple]) -> list[dict]:
    """The rule in plain words, a line per kind of opportunity."""
    lines = []
    rates = policy.replacement_rates or {}
    for s in inp.specs:
        name = s["name"]
        k = by_kind.get(name) or {}
        thresholds = k.get("thresholds") or []
        used = (rates.get(name) or 0.0) * inp.per_day * 365.25 >= _USED or k.get("max_chance", 0.0) >= _USED
        if not thresholds:
            text = f"At the {name}: don't replace (it never pays at this price)."
            used = False
        elif not used:
            text = (f"At the {name}: replace only a unit older than {_age_text(min(thresholds), max(thresholds), inp.unit)}"
                    " — in the long run, almost no unit gets that old there.")
        else:
            text = (f"At the {name}: replace the part if it is older than "
                    f"{_age_text(min(thresholds), max(thresholds), inp.unit)}.")
            if max(thresholds) - min(thresholds) > 0.02 * max(thresholds):
                text += " The age depends on how soon the next cheaper chance comes."
        lines.append({"kind": name, "text": text, "used": bool(used),
                      "threshold_min": min(thresholds) if thresholds else None,
                      "threshold_max": max(thresholds) if thresholds else None})
    if inp.anytime_cost is not None:
        used = (rates.get("anytime") or 0.0) * inp.per_day * 365.25 >= _USED
        if anytime and used:
            text = (f"Between shuts: replace the part once it is older than "
                    f"{_age_text(anytime[0], anytime[1], inp.unit)}.")
        else:
            text = "Between shuts: don't replace it; wait for a shut (or a failure)."
        lines.append({"kind": "anytime", "text": text, "used": bool(anytime and used),
                      "threshold_min": anytime[0] if anytime else None,
                      "threshold_max": anytime[1] if anytime else None})
    return lines


def _kind_rows(inp: _Inputs, policy) -> list[dict]:
    rates, costs = policy.replacement_rates or {}, policy.cost_rates or {}
    prices = {s["name"]: s["cost"] for s in inp.specs}
    if inp.anytime_cost is not None:
        prices["anytime"] = inp.anytime_cost
    prices["failure"] = inp.failure_cost
    total = policy.cost_rate or 0.0
    rows = []
    for kind in [*(s["name"] for s in inp.specs), "anytime", "failure"]:
        if kind not in rates:
            continue
        rate, cost = _finite(rates.get(kind)) or 0.0, _finite(costs.get(kind)) or 0.0
        rows.append({
            "kind": kind,
            "label": {"anytime": "Between shuts (any day)", "failure": "Failures"}.get(kind, kind),
            "price": prices.get(kind),
            "replacements_per_year": inp.per_year(rate),
            "cost_per_year": inp.per_year(cost),
            "share": (cost / total) if total else None,
        })
    return rows


def _opportunities_out(inp: _Inputs) -> list[dict]:
    """The shuts as given and as model time (the "today = 0" conversion)."""
    out = []
    for s in inp.specs:
        row = {k: s[k] for k in ("name", "cost", "kind")}
        if s["kind"] == "dates":
            row.update(dates=s["dates"], times=s["times"], past_dates_dropped=s["past_dates_dropped"])
        else:
            row.update(every=s["every"], every_unit=s["every_unit"], start=s["start"],
                       period=s["period"], offset=s["offset"])
        out.append(row)
    return out


def _headline(inp: _Inputs, policy, comparisons: list[dict], lines: list[dict]) -> str:
    per_year = inp.per_year(policy.cost_rate)
    used = [ln for ln in lines if ln["used"]]
    if not used:
        how = "Run the part to failure: no planned replacement pays at these prices."
    else:
        how = " ".join(ln["text"] for ln in used)
    rtf = next((c for c in comparisons if c["policy"] == "run_to_failure"), None)
    age = next((c for c in comparisons if c["policy"] == "age"), None)
    bits = [f"Long-run cost about {fmt_num(per_year)} a year"]
    if rtf and rtf["cost_rate"] and policy.cost_rate < rtf["cost_rate"] * 0.995:
        bits.append(f"{1 - policy.cost_rate / rtf['cost_rate']:.0%} less than running to failure")
    if age and age["cost_rate"] and policy.cost_rate < age["cost_rate"] * 0.995:
        bits.append(f"{1 - policy.cost_rate / age['cost_rate']:.0%} less than plain age replacement")
    return f"{how} {', '.join(bits)}."


def check_inputs(distribution_id: str, params: list, **kwargs) -> None:
    """Check a request's inputs without solving it (StrategyError if bad):
    a sampled request is checked before it is queued."""
    _Inputs(distribution_id, params, **kwargs)


def calendar_replacement(distribution_id: str, params: list, **kwargs) -> dict:
    """The long-run best replacement rule over a calendar of shuts, with
    what simpler rules cost and the next months' schedule (see the module
    docstring for the inputs and the "today = 0" convention)."""
    inp = _Inputs(distribution_id, params, **kwargs)
    policy, notes = inp.policy()
    until_date = add_months(inp.today, inp.horizon_months)
    schedule, by_kind = _schedule(inp, policy, until_date)
    anytime = _anytime_threshold(inp, policy)
    lines = _rule_lines(inp, policy, by_kind, anytime)
    comparisons = _comparisons(inp, policy)
    for s in inp.specs:
        if s.get("past_dates_dropped"):
            notes.append(f"'{s['name']}': {s['past_dates_dropped']} date(s) before today were left out.")
    if not policy.threshold_only:
        notes.append("This life's failure rate falls at some ages, so at some times an older unit is kept where "
                     "a younger one is replaced; the ages shown are the youngest that are replaced.")
    if policy.basis != "exact":
        notes.append("The cost split by kind and the schedule's chances are estimates from a unit run in over "
                     "the calendar" + (" (only the total cost rate has a standard error)." if
                                       policy.method == "sampling" else "."))
    if any(s["kind"] == "dates" for s in inp.specs):
        notes.append("Shuts on given dates are taken to repeat after the last one (the plan from its first date "
                     "to its last, then again), so there is a long run to optimise; the chances in the schedule "
                     "are for a unit fitted today.")
    determined = _finite(policy.determined_until)
    rtf = next(c for c in comparisons if c["policy"] == "run_to_failure")
    age = next((c for c in comparisons if c["policy"] == "age"), None)
    return {
        "kind": "calendar_replacement",
        "distribution": inp.distribution,
        "unit": inp.unit,
        "today": inp.today.isoformat(),
        "convention": CONVENTION,
        "units_per_day": inp.per_day,
        "failure_cost": inp.failure_cost,
        "anytime_cost": inp.anytime_cost,
        "max_age": inp.max_age,
        "method": policy.method,
        "method_label": ("On a fine time grid, over a long horizon (the shuts' pattern takes too long to "
                         "repeat for an exact cycle)" if policy.basis == "differenced"
                         else METHOD_LABELS.get(policy.method, policy.method)),
        "basis": policy.basis,
        "cost_rate": _finite(policy.cost_rate),
        "cost_rate_se": _finite(policy.cost_rate_se),
        "cost_per_year": inp.per_year(_finite(policy.cost_rate)),
        "cost_per_year_se": inp.per_year(_finite(policy.cost_rate_se)),
        "run_to_failure_cost_rate": rtf["cost_rate"],
        "age_rule": age,
        "savings_vs_run_to_failure": (None if not rtf["cost_rate"] else 1 - policy.cost_rate / rtf["cost_rate"]),
        "savings_vs_age_rule": (None if not age or not age["cost_rate"] else 1 - policy.cost_rate / age["cost_rate"]),
        "comparisons": comparisons,
        "by_kind": _kind_rows(inp, policy),
        "rule": lines,
        "recommendation": _headline(inp, policy, comparisons, lines),
        "schedule": schedule,
        "schedule_until": until_date.isoformat(),
        "horizon_months": inp.horizon_months,
        "opportunities": _opportunities_out(inp),
        "step": _finite(policy.step),
        "period": _finite(policy.period),
        "determined_until": determined,
        "determined_until_date": inp.to_date(determined).isoformat() if determined is not None else None,
        "threshold_only": bool(policy.threshold_only),
        "mc_samples": inp.mc_samples if policy.method == "sampling" else None,
        "notes": notes,
    }


# ---------------------------------------------------------------------------
# One unit now
# ---------------------------------------------------------------------------


def _next_outages(inp: _Inputs) -> tuple[list[tuple[float, float]], list[dict], Optional[dict]]:
    """The next shut of each kind from today, as (time from now, price), with
    its name and date; and a shut falling today, if one does."""
    horizon = add_months(inp.today, 12 * 25)
    outages, labels, today_shut = [], [], None
    seen = set()
    for s in inp.specs:
        dates = _occurrences(s, inp.today, horizon)
        if dates and dates[0] == inp.today:
            if today_shut is None or s["cost"] < today_shut["price"]:
                today_shut = {"kind": s["name"], "price": s["cost"], "date": dates[0].isoformat()}
            dates = dates[1:]
        if not dates:
            continue
        d = dates[0]
        t = inp.model_time(d)
        if t <= 0 or (t, s["cost"]) in seen:
            continue
        seen.add((t, s["cost"]))
        outages.append((t, s["cost"]))
        labels.append({"kind": s["name"], "date": d.isoformat(), "time": t, "price": s["cost"]})
    return outages, labels, today_shut


def calendar_next(distribution_id: str, params: list, *, age, now_cost=None, **kwargs) -> dict:
    """For the unit in service, ``age`` old today: replace it now, at the
    next shut (of each kind), at a planned time between, or run it to
    failure — each choice's cost and break-even age, valued at the calendar
    policy's long-run cost rate. Always exact (the grid method)."""
    kwargs = {**kwargs, "method": "dp", "mc_samples": None, "seed": None}
    inp = _Inputs(distribution_id, params, **kwargs)
    a = _number(age, "The unit's age")
    policy, notes = inp.policy()
    outages, labels, today_shut = _next_outages(inp)
    if now_cost in (None, ""):
        if today_shut is not None:
            now = today_shut["price"]
        elif inp.anytime_cost is not None:
            now = inp.anytime_cost
        else:
            raise StrategyError("No shut falls today and the calendar has no any-day replacement: enter what "
                                "replacing it now would cost.")
    else:
        now = _number(now_cost, "The cost of replacing it now")
    planned = inp.anytime_cost if inp.anytime_cost is not None else now
    if planned >= inp.failure_cost or now >= inp.failure_cost:
        planned = min(planned, inp.failure_cost * (1 - 1e-9))
    part = NonRepairable(inp.model, planned_cost=planned, unplanned_cost=inp.failure_cost)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            found = part.optimal_next_replacement(a, now_cost=now, scheduled_outages=outages, policy=policy)
    except (ValueError, TypeError, NotImplementedError) as exc:
        raise StrategyError(str(exc)) from None
    choices = []
    for c in found.choices:
        if c.kind == "planned" and inp.anytime_cost is None:
            continue  # no replacement between shuts on this calendar
        row = {"kind": c.kind, "time": _finite(c.time), "price": _finite(c.price), "cost": _finite(c.cost),
               "break_even_age": _finite(c.break_even_age)}
        if c.kind == "outage":
            match = next((lb for lb in labels if abs(lb["time"] - c.time) < 1e-9 and lb["price"] == c.price), None)
            if match:
                row.update(label=f"At the {match['kind']} on {say_date(match['date'])}", shut=match["kind"],
                           date=match["date"])
        elif c.kind == "now":
            row.update(label="Replace now", date=inp.today.isoformat())
        elif c.kind == "planned":
            if row["time"] is None:
                row["label"] = "A planned replacement between shuts (none beats running to failure)"
            else:
                d = inp.to_date(row["time"])
                row.update(label=f"A planned replacement between shuts, in {fmt_num(row['time'])} "
                           f"{unit_in_text(inp.unit)} ({say_date(d)})", date=d.isoformat())
        elif c.kind == "failure":
            row["label"] = "Run it to failure"
        if row["break_even_age"] is not None and row["break_even_age"] >= 1e300:
            row["break_even_age"] = None
        choices.append(row)
    best = min(choices, key=lambda r: (r["cost"] if r["cost"] is not None else math.inf))
    later = [r["break_even_age"] for r in choices if r["kind"] != "now"]
    replace_from = None if any(v is None for v in later) or not later else max(later)
    nxt = policy.next_replacement(a, now=0.0)
    plan = None
    if math.isfinite(nxt.time):
        d = inp.to_date(nxt.time)
        spec = next((sp for sp in inp.specs if sp["name"] == nxt.kind), None)
        if spec is not None:  # the shut's own date (a month-based shut's real one)
            near = _occurrences(spec, inp.today, d + timedelta(days=40))
            if near:
                d = min(near, key=lambda x: abs((x - d).days))
        kind = nxt.kind or ""
        plan = {"time": nxt.time, "kind": kind, "price": nxt.price, "date": d.isoformat(),
                "text": ("Replace it now." if nxt.time <= 1e-9 else
                         f"On the long-run rule it is replaced {'between shuts' if kind == 'anytime' else 'at the ' + kind} "
                         f"on {say_date(d)}, if it hasn't failed by then.")}
    u = unit_in_text(inp.unit)
    if best["kind"] == "now":
        sentence = f"Replace it now ({fmt_num(now)})."
    elif best["kind"] == "outage":
        sentence = f"Keep it: replace it at the {best.get('shut', 'next shut')} on {say_date(best['date'])}."
    elif best["kind"] == "planned":
        sentence = f"Keep it for now: replace it between shuts in about {fmt_num(best['time'])} {u}."
    else:
        sentence = "Keep it running: no planned replacement beats running it to failure."
    if replace_from is not None:
        sentence += f" Replacing now becomes the best choice from an age of {fmt_num(replace_from)} {u}."
    return {
        "kind": "calendar_next",
        "unit": inp.unit,
        "today": inp.today.isoformat(),
        "age": a,
        "now_cost": now,
        "best": best,
        "now": best["kind"] == "now",
        "choices": choices,
        "replace_from_age": replace_from,
        "cost_rate": _finite(found.cost_rate),
        "cost_per_year": inp.per_year(_finite(found.cost_rate)),
        "policy_next": plan,
        "outages": labels,
        "recommendation": sentence,
        "notes": notes,
    }
