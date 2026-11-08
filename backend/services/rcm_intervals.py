"""How often to do an RCM task: the interval calculators on a failure mode's task card.

Two exact calculators, each a thin wrapper around RePyability's
``repyability.maintenance`` decision functions:

* ``on_condition_interval`` — how often to check for a warning sign (the P-F
  calculator): ``optimal_on_condition_interval`` for the cheapest interval and
  ``on_condition`` for the numbers at the interval the task will use.
* ``failure_finding_interval`` — how often to test a protective device whose
  failure is hidden: ``optimal_failure_finding_interval`` (the longest interval
  that keeps its unavailability within a target, or the cheapest) and
  ``failure_finding`` for the interval the task has now.

The third (a fixed-interval task) is the Strategy replacement calculator
(``backend.services.strategy.optimal_replacement``), reused as it is.

Times go in with their unit and come back in a unit people schedule in
(hours, days, weeks, months or years), rounded down so a check is never
later than the calculation says. Rates (onset, demand) are per year.

RePyability added these functions after 0.16, the version the app pins. Until
the pin moves, the same formulas (ported from RePyability's
``maintenance/_decisions.py``, its notes say why each holds) run here when the
installed RePyability lacks them; ``backend/tests/test_rcm_intervals.py``
checks both give the same numbers wherever the new RePyability is installed.
Drop the port when the pin reaches the release that has them.
"""

from __future__ import annotations

import math
from typing import Optional

import numpy as np
from scipy.optimize import brentq, minimize_scalar

from backend.services.strategy import StrategyError, _model_from_params, fmt_num
from backend.units import normalize_unit, unit_in_text

try:  # RePyability after 0.16
    from repyability import maintenance as _repy_maintenance
except ImportError:  # pragma: no cover - RePyability is always installed
    _repy_maintenance = None

# Days in one of each time unit (a month and a year on average, leap years included).
DAYS_IN = {"hour": 1 / 24, "day": 1.0, "week": 7.0, "month": 365.25 / 12, "year": 365.25}
# The units a task is scheduled in, as the task card's unit picker spells them.
TASK_UNIT = {"hour": "hours", "day": "days", "week": "weeks", "month": "months", "year": "years"}
DAYS_A_YEAR = 365.25


class IntervalError(StrategyError):
    """Inputs an interval calculator can't use; the message says what to change."""


def _repy(name: str):
    """RePyability's function ``name`` when the installed release has it, else None."""
    return getattr(_repy_maintenance, name, None) if _repy_maintenance is not None else None


# ---- inputs -------------------------------------------------------------------------

def _number(value, label: str, *, positive: bool = False, allow_none: bool = False) -> Optional[float]:
    if value is None or value == "":
        if allow_none:
            return None
        raise IntervalError(f"Enter the {label}.")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise IntervalError(f"The {label} must be a number.") from None
    if not math.isfinite(number):
        raise IntervalError(f"The {label} must be a finite number.")
    if positive and number <= 0:
        raise IntervalError(f"The {label} must be more than 0.")
    if number < 0:
        raise IntervalError(f"The {label} can't be negative.")
    return number


def _time_unit(unit, label: str) -> str:
    """A time unit's key in DAYS_IN ("hour", ..., "year"), or a plain refusal."""
    key = normalize_unit(unit)
    if key not in DAYS_IN:
        shown = f" “{unit}”" if unit else ""
        raise IntervalError(
            f"The {label} needs a time unit (hours, days, weeks, months or years), not{shown or ' a blank one'}: "
            "the rates are per year, so the calculator needs to know how long the unit is."
        )
    return key


def nice_interval(days: float) -> Optional[dict]:
    """An interval in days as people schedule it, rounded down: whole years (half
    years under 5), then whole months, weeks, days or hours, the largest unit that
    still gives at least 2 of it. Rounded down, so the task is never later than
    the calculation; never below 1 hour."""
    if days is None or not math.isfinite(days) or days <= 0:
        return None
    for key, least in (("year", 2), ("month", 2), ("week", 2), ("day", 2)):
        amount = days / DAYS_IN[key]
        if amount >= least:
            step = 0.5 if key == "year" and amount < 5 else 1.0
            value = math.floor(amount / step + 1e-9) * step
            return {"value": int(value) if value == int(value) else value, "unit": TASK_UNIT[key],
                    "days": value * DAYS_IN[key]}
    hours = max(1, math.floor(days * 24 + 1e-9))
    return {"value": hours, "unit": "hours", "days": hours / 24}


def _in_unit(days: float, unit: str) -> float:
    return days / DAYS_IN[normalize_unit(unit)]


def _with_unit(value, unit) -> str:
    text = fmt_num(value)
    word = unit_in_text(unit)
    if normalize_unit(unit) in DAYS_IN and float(value) == 1:
        word = word[:-1] if word.endswith("s") else word
    return f"{text} {word}".strip()


def _result_unit(unit, fallback_days: float) -> dict:
    """The unit asked for (a time unit), else the nice one for ``fallback_days``."""
    if unit:
        key = _time_unit(unit, "result")
        return {"unit": TASK_UNIT[key], "days": DAYS_IN[key]}
    nice = nice_interval(fallback_days)
    return {"unit": nice["unit"] if nice else "days", "days": DAYS_IN[normalize_unit(nice["unit"]) if nice else "day"]}


# ---- on condition (the P-F calculator) -------------------------------------------------

def _miss_fixed(pf: float, tau: float, p: float) -> float:
    """The chance a fixed warning of length ``pf`` is missed by checks every ``tau``
    that each find it with probability ``p`` (random phase): RePyability's notes."""
    whole = math.floor(pf / tau)
    return (1.0 - p) ** whole * (1.0 - p * (pf / tau - whole))


def _on_condition_numbers(pf, tau, p, onset, inspection, found, failed) -> dict:
    fn = _repy("on_condition")
    if fn is not None:
        r = fn(pf, tau, onset_rate=onset, detection_probability=p, inspection_cost=inspection,
               found_cost=found, failure_cost=failed)
        detect, cost = float(r.detection_probability), r.cost_rate
    else:
        detect = 1.0 - _miss_fixed(pf, tau, p)
        priced = inspection > 0 or found > 0 or failed > 0
        cost = inspection / tau + onset * (detect * found + (1 - detect) * failed) if priced else None
    return {"interval": tau, "detection_probability": detect, "failure_rate": onset * (1 - detect),
            "cost_rate": None if cost is None else float(cost)}


def _optimal_on_condition(pf, onset, inspection, found, failed, p) -> float:
    """The cheapest interval between checks, in the P-F interval's unit (inf: checking never pays)."""
    fn = _repy("optimal_on_condition_interval")
    if fn is not None:
        return float(fn(pf, onset_rate=onset, inspection_cost=inspection, found_cost=found,
                        failure_cost=failed, detection_probability=p).interval)

    def rate(log_tau: float) -> float:
        return _on_condition_numbers(pf, math.exp(log_tau), p, onset, inspection, found, failed)["cost_rate"]

    grid = np.linspace(math.log(1e-3 * pf), math.log(30.0 * pf), 240)
    values = np.array([rate(g) for g in grid])
    i = int(np.argmin(values))
    if i == len(grid) - 1:
        return math.inf
    refined = minimize_scalar(rate, bounds=(grid[max(i - 1, 0)], grid[i + 1]), method="bounded",
                              options={"xatol": 1e-12})
    best = refined.x if refined.fun <= values[i] else grid[i]
    # A fixed warning makes the cost rate step at fractions of it: try those too.
    candidates = [pf / n for n in range(1, 21)] + [math.exp(best)]
    return min(candidates, key=lambda tau: rate(math.log(tau)))


def on_condition_interval(pf_interval=None, pf_unit=None, onset_rate=None, inspection_cost=None, found_cost=None,
                          failure_cost=None, detection_probability=1.0, unit: Optional[str] = None,
                          current_interval=None, current_unit: Optional[str] = None) -> dict:
    """The cheapest interval between checks for a warning sign that comes a P-F
    interval before the failure. ``onset_rate``: warnings (failures, if nothing is
    done) per year; the costs: one check, acting on a warning found (the planned
    fix), and a failure (the unplanned one). ``unit``: the unit to answer in (by
    default the one that reads best). ``current_interval`` (in ``current_unit``):
    the task's interval now, to compare."""
    pf = _number(pf_interval, "P-F interval", positive=True)
    pf_key = _time_unit(pf_unit, "P-F interval")
    onset = _number(onset_rate, "onset rate (failures a year)", positive=True)
    inspection = _number(inspection_cost, "cost of a check", positive=True)
    found = _number(found_cost, "cost when a warning is found")
    failed = _number(failure_cost, "cost of a failure")
    p = _number(detection_probability if detection_probability is not None else 1.0,
                "chance a check finds the warning", positive=True)
    if p > 1:
        raise IntervalError("The chance a check finds the warning is at most 1 (100%).")
    if failed <= found:
        raise IntervalError("The cost of a failure must be more than the cost of fixing a warning found in time: "
                            "otherwise checking can't pay.")

    pf_days = pf * DAYS_IN[pf_key]
    per_day = onset / DAYS_A_YEAR
    best_days = _optimal_on_condition(pf_days, per_day, inspection, found, failed, p)
    rtf = onset * failed
    rule = pf_days / 2
    out = {
        "kind": "on_condition_interval",
        "pf_interval": pf, "pf_unit": TASK_UNIT[pf_key], "onset_rate": onset, "inspection_cost": inspection,
        "found_cost": found, "failure_cost": failed, "detection_probability": p,
        "run_to_failure_cost_rate": rtf,
        "explanation": ("A failure gives a warning a while before it happens (the P-F interval). Check too often and "
                        "the checks cost more than they save; too rarely and warnings are missed and become failures. "
                        "This finds the interval with the lowest cost a year, checks, planned fixes and failures together."),
    }
    if not math.isfinite(best_days):
        out |= {"worth_it": False, "interval": None, "unit": unit or TASK_UNIT[pf_key], "recommended": None,
                "cost_rate": rtf,
                "summary": (f"Checking never pays at these prices: failures cost about ${fmt_num(rtf)} a year, "
                            "less than any schedule of checks.")}
        return out
    shown = _result_unit(unit, best_days)
    nice = nice_interval(best_days) if not unit else {
        "value": _floor_value(best_days / shown["days"]), "unit": shown["unit"]}
    nice["days"] = nice["value"] * DAYS_IN[normalize_unit(nice["unit"])]
    best = _on_condition_numbers(pf_days, best_days, p, per_day, inspection, found, failed)
    at = _on_condition_numbers(pf_days, nice["days"], p, per_day, inspection, found, failed)
    rule_nice = nice_interval(rule)
    out |= {
        "worth_it": best["cost_rate"] * DAYS_A_YEAR < rtf,
        "unit": nice["unit"],
        "interval": best_days / DAYS_IN[normalize_unit(nice["unit"])],
        "recommended": {"value": nice["value"], "unit": nice["unit"]},
        "detection_probability_at_best": best["detection_probability"],
        "cost_rate": best["cost_rate"] * DAYS_A_YEAR,
        "at_recommended": {"detection_probability": at["detection_probability"],
                           "failures_per_year": at["failure_rate"] * DAYS_A_YEAR,
                           "cost_rate": at["cost_rate"] * DAYS_A_YEAR},
        "rule_of_thumb": {"value": rule / DAYS_IN[normalize_unit(nice["unit"])], "unit": nice["unit"],
                          "nice": rule_nice and {"value": rule_nice["value"], "unit": rule_nice["unit"]},
                          "text": f"Rule of thumb: check at least every half P-F interval, {_with_unit(pf / 2, TASK_UNIT[pf_key])}."},
    }
    if current_interval not in (None, ""):
        cur = _number(current_interval, "task's interval now", positive=True)
        cur_days = cur * DAYS_IN[_time_unit(current_unit, "task's interval now")]
        now = _on_condition_numbers(pf_days, cur_days, p, per_day, inspection, found, failed)
        out["current"] = {"value": cur, "unit": current_unit, "detection_probability": now["detection_probability"],
                          "cost_rate": now["cost_rate"] * DAYS_A_YEAR}
    out["summary"] = (f"Check every {_with_unit(nice['value'], nice['unit'])}: about ${fmt_num(out['at_recommended']['cost_rate'])} "
                      f"a year, against ${fmt_num(rtf)} a year letting it fail. "
                      f"It finds {at['detection_probability']:.0%} of warnings in time.")
    return out


def _floor_value(amount: float):
    """A value in a unit someone chose: rounded down to a whole number from 2, else to 0.1."""
    value = math.floor(amount + 1e-9) if amount >= 2 else max(0.1, math.floor(amount * 10 + 1e-9) / 10)
    return int(value) if value == int(value) else value


# ---- failure finding -----------------------------------------------------------------

def _device(failure_rate, distribution_id, params, model_unit, extras):
    """(life model, days in its unit, words) for the protective device: a constant
    failure rate a year, or a model in a time unit."""
    if distribution_id:
        key = _time_unit(model_unit, "device's model")
        model, name = _model_from_params(distribution_id, params or [], extras)
        mean = float(np.ravel(model.mean())[0])
        if not (math.isfinite(mean) and mean > 0):
            raise IntervalError("The device's model has no finite mean life: some never fail, so failure finding "
                                "can't be worked out from it.")
        return model, DAYS_IN[key], {"source": "model", "distribution": name, "unit": TASK_UNIT[key],
                                     "mean_life": mean, "rate": None}
    rate = _number(failure_rate, "device's failure rate (failures a year)", positive=True)
    from surpyval import Exponential

    return Exponential.from_params([rate]), DAYS_A_YEAR, {"source": "rate", "rate": rate, "unit": "years",
                                                           "mean_life": 1 / rate, "distribution": "Exponential"}


def _unavailability(model, tau: float) -> tuple[float, float]:
    """(mean unavailability, mean cycle) of a device tested every ``tau`` (the
    model's unit): RePyability's notes. Exact."""
    mean = float(np.ravel(model.mean())[0])
    if type(model.dist).__name__.lower().startswith("exponential"):
        rate = 1.0 / mean
        decay = -math.expm1(-rate * tau)
        return 1.0 - decay / (rate * tau), tau / decay
    chunk, total, j = 4096, 0.0, 0
    while True:
        times = (j + np.arange(chunk)) * tau
        values = np.asarray(model.sf(times), dtype=float).ravel()
        total += float(values.sum())
        j += chunk
        if values[-1] < 1e-17 * max(total, 1.0):
            break
        if j >= 20_000_000:
            raise IntervalError("The tests are far shorter than the device's life: use a longer interval.")
        chunk = min(2 * chunk, 4_000_000)
    cycle = tau * total
    return 1.0 - mean / cycle, cycle


def _ff_numbers(model, tau, test, repair, demand, consequence) -> dict:
    fn = _repy("failure_finding")
    if fn is not None:
        from repyability.non_repairable import NonRepairable

        r = fn(NonRepairable(model), tau, test_cost=test, repair_cost=repair, demand_rate=demand,
               consequence_cost=consequence)
        return {"mean_unavailability": float(r.mean_unavailability),
                "multiple_failure_rate": None if r.multiple_failure_rate is None else float(r.multiple_failure_rate),
                "cost_rate": None if r.cost_rate is None else float(r.cost_rate)}
    u, cycle = _unavailability(model, tau)
    multiple = None if demand is None else demand * u
    cost = test / tau + repair / cycle + (consequence * multiple if multiple is not None else 0.0)
    priced = test > 0 or repair > 0 or consequence > 0
    return {"mean_unavailability": u, "multiple_failure_rate": multiple, "cost_rate": cost if priced else None}


def _optimal_ff(model, target, test, repair, demand, consequence) -> float:
    """The interval (the model's unit): the longest within ``target``, or the cheapest.

    RePyability's search starts the target's at a hundred-millionth of the mean
    life, too fine for a life whose failure rate isn't constant (it gives up:
    NotImplementedError); then the search here starts at a thousandth, each
    point still RePyability's ``failure_finding``."""
    fn = _repy("optimal_failure_finding_interval")
    if fn is not None:
        from repyability.non_repairable import NonRepairable

        try:
            return float(fn(NonRepairable(model), target_unavailability=target, test_cost=test, repair_cost=repair,
                            demand_rate=demand, consequence_cost=consequence).interval)
        except ValueError as exc:
            raise IntervalError(_ff_words(str(exc))) from None
        except NotImplementedError:
            pass
    scale = float(np.ravel(model.mean())[0])
    if target is not None:
        low, high = math.log(1e-3 * scale), math.log(50.0 * scale)

        def excess(log_tau: float) -> float:
            return _ff_numbers(model, math.exp(log_tau), 0.0, 0.0, None, 0.0)["mean_unavailability"] - target

        if excess(high) <= 0:
            raise IntervalError(_ff_words("needs no testing"))
        if excess(low) > 0:
            raise IntervalError("The target is tighter than any practical test interval can meet: even testing at a "
                                "thousandth of the device's mean life misses it. Check the target and the device's life.")
        return math.exp(brentq(excess, low, high, xtol=1e-13))

    def rate(log_tau: float) -> float:
        return _ff_numbers(model, math.exp(log_tau), test, repair, demand, consequence)["cost_rate"]

    grid = np.linspace(math.log(1e-3 * scale), math.log(20.0 * scale), 200)
    values = np.array([rate(g) for g in grid])
    i = int(np.argmin(values))
    refined = minimize_scalar(rate, bounds=(grid[max(i - 1, 0)], grid[min(i + 1, len(grid) - 1)]),
                              method="bounded", options={"xatol": 1e-12})
    return math.exp(refined.x if refined.fun <= values[i] else grid[i])


def _ff_words(message: str) -> str:
    if "needs no testing" in message:
        return ("The device stays within the target at any test interval up to 50 mean lives: it needs no testing "
                "for this target.")
    return message


def failure_finding_interval(failure_rate=None, distribution_id: Optional[str] = None, params=None,
                             model_unit: Optional[str] = None, extras: Optional[dict] = None,
                             target_unavailability=None, test_cost=0.0, repair_cost=0.0, demand_rate=None,
                             consequence_cost=0.0, unit: Optional[str] = None,
                             current_interval=None, current_unit: Optional[str] = None) -> dict:
    """How often to test a protective device whose failure is hidden: the longest
    interval that keeps its mean unavailability (the chance it's failed when
    needed) within ``target_unavailability``, or without a target the cheapest
    (tests, repairs and demands met by a failed device). The device: its
    ``failure_rate`` a year, or a model (``distribution_id``, ``params``, its time
    unit ``model_unit``). ``demand_rate``: how often it's needed, a year.
    ``current_interval`` (in ``current_unit``): the task's interval now."""
    target = _number(target_unavailability, "target unavailability", positive=True, allow_none=True)
    if target is not None and target >= 1:
        raise IntervalError("The target unavailability is a chance, less than 1 (1% is 0.01).")
    test = _number(test_cost or 0, "cost of a test")
    repair = _number(repair_cost or 0, "cost of a repair")
    demand = _number(demand_rate, "demand rate (demands a year)", allow_none=True)
    consequence = _number(consequence_cost or 0, "cost of a demand met by a failed device")
    if consequence > 0 and not demand:
        raise IntervalError("A cost of a demand met by a failed device needs the demand rate: how often a year "
                            "the device is needed.")
    if target is None and not (test > 0 and consequence > 0 and demand):
        raise IntervalError("Give a target unavailability (1% is 0.01), or the cost of a test, the demand rate and "
                            "the cost of a demand met by a failed device, to find the cheapest interval.")
    model, unit_days, device = _device(failure_rate, distribution_id, params, model_unit, extras)
    per_unit = None if demand is None else demand * unit_days / DAYS_A_YEAR
    tau = _optimal_ff(model, target, test, repair, per_unit, consequence)
    best_days = tau * unit_days
    shown = _result_unit(unit, best_days)
    nice = nice_interval(best_days) if not unit else {
        "value": _floor_value(best_days / shown["days"]), "unit": shown["unit"]}
    nice_days = nice["value"] * DAYS_IN[normalize_unit(nice["unit"])]
    a_year = DAYS_A_YEAR / unit_days  # model units in a year

    def numbers(days: float) -> dict:
        r = _ff_numbers(model, days / unit_days, test, repair, per_unit, consequence)
        return {"mean_unavailability": r["mean_unavailability"],
                "multiple_failures_per_year": None if r["multiple_failure_rate"] is None
                else r["multiple_failure_rate"] * a_year,
                "cost_rate": None if r["cost_rate"] is None else r["cost_rate"] * a_year}

    best, at = numbers(best_days), numbers(nice_days)
    out = {
        "kind": "failure_finding_interval",
        "basis": "target" if target is not None else "cost",
        "device": device, "target_unavailability": target, "test_cost": test, "repair_cost": repair,
        "demand_rate": demand, "consequence_cost": consequence,
        "unit": nice["unit"], "interval": best_days / DAYS_IN[normalize_unit(nice["unit"])],
        "recommended": {"value": nice["value"], "unit": nice["unit"]},
        "mean_unavailability": best["mean_unavailability"], "cost_rate": best["cost_rate"],
        "multiple_failures_per_year": best["multiple_failures_per_year"],
        "at_recommended": at,
        "explanation": ("A protective device can fail without anyone knowing; only a test shows it. The longer between "
                        "tests, the likelier it's already failed when it's needed (its unavailability). "
                        + ("This finds the longest interval that keeps that chance within the target."
                           if target is not None else
                           "This finds the interval with the lowest cost a year: tests, repairs and demands met by a "
                           "failed device.")),
    }
    if current_interval not in (None, ""):
        cur = _number(current_interval, "task's interval now", positive=True)
        cur_days = cur * DAYS_IN[_time_unit(current_unit, "task's interval now")]
        now = numbers(cur_days)
        out["current"] = {"value": cur, "unit": current_unit, **now,
                          "meets_target": None if target is None else now["mean_unavailability"] <= target + 1e-12}
    if target is not None:
        out["summary"] = (f"Test every {_with_unit(nice['value'], nice['unit'])}: the device is failed when needed "
                          f"{_pct(at['mean_unavailability'])} of the time, within the {_pct(target)} target. "
                          f"The longest interval that meets it is {_with_unit(out['interval'], nice['unit'])}.")
    else:
        out["summary"] = (f"Test every {_with_unit(nice['value'], nice['unit'])}: about ${fmt_num(at['cost_rate'])} a "
                          f"year, the device failed when needed {_pct(at['mean_unavailability'])} of the time.")
    return out


def _pct(p: float) -> str:
    """A small chance as a percentage people read: 0.8%, 0.05%, 12%."""
    v = 100 * p
    if v >= 10:
        return f"{v:.0f}%"
    if v >= 0.1:
        return f"{v:.2g}%" if v < 1 else f"{v:.1f}%".replace(".0%", "%")
    return f"{v:.2g}%"


# ---- what the calculators start from (the task card's dialog) --------------------------

def model_inputs(model) -> dict:
    """A saved plain non-repairable model as a calculator's inputs (distribution_id,
    params, extras, unit, name), or an IntervalError saying why it can't be one."""
    if getattr(model, "kind", None) != "distribution":
        raise IntervalError(f"“{model.name}” is a {model.kind} model: the calculators need a plain life distribution.")
    r = model.results or {}
    return {"model_id": model.id, "name": model.name,
            "distribution_id": r.get("distribution_id") or model.distribution_id,
            "params": [{"name": p.get("name"), "value": p.get("value")} for p in (r.get("params") or [])],
            "extras": r.get("extras") or None, "unit": r.get("unit") or ""}


def _yearly_rate(model_in: dict) -> Optional[float]:
    """Failures a year from a model's mean life, when its unit is a time."""
    key = normalize_unit(model_in.get("unit"))
    if key not in DAYS_IN:
        return None
    try:
        model, _ = _model_from_params(model_in["distribution_id"], model_in["params"], model_in.get("extras"))
        mean = float(np.ravel(model.mean())[0])
    except Exception:
        return None
    if not (math.isfinite(mean) and mean > 0):
        return None
    return DAYS_A_YEAR / (mean * DAYS_IN[key])


def history_rate(rows: list[dict], mode_text: str = "") -> Optional[dict]:
    """Failures a year at a position from its life data (one row per fitment: days
    in service ``x``, ``c`` 0 or 2 failed): this failure mode's failures when any
    are recorded against it, else every failure there. None without a failure."""
    exposure = sum(max(0.0, float(r.get("x") or 0)) for r in rows)
    failed = [r for r in rows if r.get("c") in (0, 2)]
    mine = [r for r in failed if mode_text and (r.get("failure_mode") or "").strip().lower() == mode_text.strip().lower()]
    used = mine or failed
    if not used or exposure <= 0:
        return None
    years = exposure / DAYS_A_YEAR
    what = "of this failure mode" if mine else "of any kind"
    n = len(used)
    return {"rate": n / years, "source": "history",
            "text": f"{n} failure{'s' if n != 1 else ''} {what} in {fmt_num(years)} years of service at this position"}


def starting_inputs(mode: dict, rows: list[dict], fetch) -> dict:
    """What the task card's calculators start from for a failure mode: its linked
    evidence (a non-repairable model, a saved replacement or interval analysis, a
    degradation model) and its position's failure history. Each value says where it
    came from; anything not found is left for the user to type."""
    decision = mode.get("decision") or {}
    evidence = decision.get("evidence") or {}
    out: dict = {"onset_rate": None, "device": None, "life_model": None, "pf": None, "costs": {}, "evidence": None}
    artifact = fetch(evidence["type"], evidence["id"]) if evidence.get("type") and evidence.get("id") else None
    if artifact is not None:
        out["evidence"] = {"type": evidence["type"], "id": evidence["id"], "name": getattr(artifact, "name", "")}
    if evidence.get("type") == "model" and artifact is not None:
        try:
            model_in = model_inputs(artifact)
        except IntervalError:
            model_in = None
        if model_in:
            out["life_model"] = out["device"] = model_in
            rate = _yearly_rate(model_in)
            if rate:
                out["onset_rate"] = {"rate": rate, "source": "model",
                                     "text": f"one over the mean life of “{artifact.name}”"}
    elif evidence.get("type") == "strategy_analysis" and artifact is not None:
        inputs = artifact.inputs or {}
        if artifact.kind == "optimal_replacement" and inputs.get("distribution_id"):
            out["life_model"] = {"name": artifact.name, "distribution_id": inputs["distribution_id"],
                                 "params": inputs.get("params") or [], "extras": inputs.get("extras"),
                                 "unit": inputs.get("unit") or ""}
            out["costs"] = {"planned_cost": inputs.get("planned_cost"), "unplanned_cost": inputs.get("unplanned_cost")}
        elif artifact.kind == "failure_finding" and inputs.get("distribution_id"):
            out["device"] = {"name": artifact.name, "distribution_id": inputs["distribution_id"],
                             "params": inputs.get("params") or [], "extras": inputs.get("extras"),
                             "unit": inputs.get("unit") or ""}
        elif artifact.kind in ("on_condition_interval", "failure_finding_interval"):
            out["previous"] = {"kind": artifact.kind, "inputs": inputs}
    elif evidence.get("type") == "degradation_model" and artifact is not None:
        # A degradation model says the failure develops measurably; how long the warning
        # lasts depends on where a reading is first called a warning, so the P-F interval
        # is still the user's (the dialog says so).
        out["pf"] = {"source": "degradation_model", "name": artifact.name,
                     "text": f"“{artifact.name}” shows the failure develops measurably; enter how long from the first "
                             "sign to the failure."}
    if out["onset_rate"] is None:
        out["onset_rate"] = history_rate(rows, mode.get("text") or "")
    return out
