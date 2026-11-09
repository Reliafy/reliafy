"""A library record's covariates: every input a record needs before it gives a rate, declared in one
place and handled by the one covariate mechanism NSWC-11, accelerated life and proportional-hazards
models already use (Derryn, 9 Nov 2026: "records need inputs before they give a rate").

Each input has the shape NSWC-11's inputs have (``backend.library.covariate``): ``key``, ``name``,
``label``, ``symbol``, ``unit``, ``kind`` (number or choice, with ``choices``), ``role`` (design,
use or environment), ``default`` and ``default_basis``, ``limits`` (``refuse`` or ``warn``) and
``help``. One more field: ``needed_if`` ({other key: [values]}) asks for an input only when another
has one of those values (running hours a year only when the clock is changed).

What each kind of record reads:

- **A pipe's rate per foot** (NRC/INL external leaks): ``length_ft``, the pipe's length (design).
- **A rate per hour** (NRC/INL): ``clock`` (use), the hours the model counts: calendar hours or
  hours of running, the record's own by default; and ``running_hours_per_year`` (use), only when the
  clock differs from the record's (a fails-to-run rate in calendar time, a leak per running hour).
- **A probability per demand** (NRC/INL): ``demands_per_year`` (use), to be a rate in time.
- **A handbook rate** (MIL-HDBK-217F): ``environment`` (environment), a choice of the handbook's
  use environments with each one's πE (or a parts-count record's generic rate); ``quality``
  (design), a parts-count record's quality grade with its πQ, the handbook's lowest grade by
  default; or ``quality_factor`` (design), πQ as a number for a part-stress record, 1 (not
  applied) by default.
- **A covariate model** (NSWC-11): its own inputs (its conditions), plus ``cycles_per_hour`` (use)
  for one whose rate is per cycle or operation.
- **A life record** (a user library's snapshot of a model) reads none.

:func:`evaluate` turns a record and a full or partial set of covariates into a rate on the clock
asked for, in the time unit asked for, or raises :class:`RecordCovariateError` naming every
covariate still missing. :func:`from_legacy` maps the old special-case arguments
(``length_ft``, ``operating_hours_per_year``, ``time_basis``, ``environment``,
``demands_per_year``, ``conditions``, ``cycles_per_hour``, ``quality_factor``) onto covariates, so
callers and saved data that used them keep working.
"""

from __future__ import annotations

import math
from typing import Any, Callable, Optional

from backend.library import schema

HOURS_PER_YEAR = 8760.0

#: The keys of the covariates this module declares (NSWC-11's own inputs come from the record).
LENGTH = "length_ft"
CLOCK = "clock"
RUNNING_HOURS = "running_hours_per_year"
DEMANDS = "demands_per_year"
ENVIRONMENT = "environment"
QUALITY = "quality"
QUALITY_FACTOR = "quality_factor"
CYCLES = "cycles_per_hour"

#: A quality grade left out where the handbook names no default (πQ isn't applied).
NOT_APPLIED = "not_applied"

CLOCKS = {"calendar": "Calendar hours (running or not)", "operating": "Hours of running"}

Resolver = Callable[[str], dict]


class RecordCovariateError(ValueError):
    """Covariates a record can't use, said for the user: ``problems`` lists every reason and
    ``missing`` the keys still needed (no value and no default)."""

    def __init__(self, problems: list[str], missing: Optional[list[str]] = None):
        self.problems = list(problems)
        self.missing = list(missing or [])
        super().__init__(" ".join(self.problems))


# ---- what a record reads ------------------------------------------------------------------------

def _fmt(x: Any) -> str:
    if isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) and x != 0:
        return f"{float(f'{x:.4g}'):g}"
    return str(x)


def _num(key: str, label: str, unit: str, role: str, help_: str, limits: list, **extra) -> dict:
    return {"key": key, "name": key, "kind": "number", "label": label, "unit": unit, "role": role, "group": None,
            "limits": limits, "help": help_, **extra}


def _choice(key: str, label: str, role: str, choices: list[dict], help_: str, **extra) -> dict:
    return {"key": key, "name": key, "kind": "choice", "label": label, "unit": "", "role": role, "group": None,
            "limits": [], "choices": choices, "help": help_, **extra}


def per_foot(rec: dict) -> bool:
    return (rec.get("units") or {}).get("value") == "per_hour_per_foot"


def own_clock(rec: dict) -> Optional[str]:
    """The record's own clock: 'calendar' or 'operating' for a rate per hour, else None."""
    if rec.get("kind") != "rate" or rec.get("basis") == "prediction_model":
        return None
    basis = (rec.get("units") or {}).get("time_basis")
    return basis if basis in schema.TIME_BASES else None


def _by_environment(rec: dict) -> dict:
    return (rec.get("environment_factors") or rec.get("generic_rates") or {}).get("values") or {}


def _environment_input(rec: dict) -> dict:
    values = _by_environment(rec)
    generic = bool(rec.get("generic_rates"))
    choices = []
    for code, (name, _covers) in schema.ENVIRONMENTS.items():
        if code not in values:
            continue
        what = f"λg {_fmt(values[code])} per 10⁶ h" if generic else f"πE {_fmt(values[code])}"
        choices.append({"code": code, "label": f"{code} · {name} ({what})", "value": values[code]})
    src = rec.get("generic_rates") if generic else rec.get("environment_factors")
    return _choice(ENVIRONMENT, "Environment", "environment", choices,
                   ("Where the part works, one of the handbook's use environments: "
                    + ("each has its own generic rate (environment included)." if generic
                       else "its environment factor πE multiplies the base rate.")),
                   symbol="λg" if generic else "πE", page=(src or {}).get("page"))


def _quality_input(rec: dict) -> Optional[dict]:
    q = rec.get("quality_factors") or {}
    if q.get("levels"):
        choices = [{"code": lv["code"], "label": f"{lv['name']} (πQ {_fmt(lv['value'])})", "value": lv["value"]}
                   for lv in q["levels"]]
        if q.get("default") is None:
            # The handbook names no lowest grade for these: left as it was, πQ isn't applied (× 1).
            choices.insert(0, {"code": NOT_APPLIED, "label": "Not applied (πQ 1)", "value": 1.0})
            return _choice(QUALITY, "Quality grade", "design", choices,
                           "How the part was procured and screened: its quality factor πQ multiplies the rate. Not "
                           "applied unless you choose a grade.", symbol="πQ", default=NOT_APPLIED, default_basis="neutral",
                           page=q.get("page"))
        return _choice(QUALITY, "Quality grade", "design", choices,
                       "How the part was procured and screened: its quality factor πQ multiplies the rate. The "
                       "handbook's lowest grade (commercial or unknown screening) unless you know better.",
                       symbol="πQ", default=q.get("default"), default_basis="handbook", page=q.get("page"))
    pred = rec.get("prediction") or {}
    rng = pred.get("quality_factor_range")
    if rng or any(f.get("symbol") == "πQ" for f in pred.get("not_applied") or []):
        limits = [{"min": 0, "exclusive": True, "severity": "refuse", "why": "a quality factor is above 0"}]
        if rng:
            limits.append({"min": rng[0], "max": rng[1], "severity": "warn", "why": "outside the handbook's range"})
        return _num(QUALITY_FACTOR, "Quality factor", "", "design",
                    "The handbook's quality factor πQ for this part (its own table). Left at 1 it isn't applied: "
                    "the base rate × πE only.", limits, symbol="πQ", default=1.0, default_basis="neutral")
    return None


def inputs(rec: dict, resolve: Optional[Resolver] = None) -> list[dict]:
    """Every covariate the record reads, each in the shape NSWC-11's inputs have."""
    kind = rec.get("kind")
    if kind == "covariate_model":
        from backend.library import covariate
        from backend.library import service as library

        out = library.covariate_inputs(rec)
        if covariate.per_cycle(rec):
            word = "Operations" if covariate.rate_unit(rec) == "per_million_operations" else "Cycles"
            out.append(_num(CYCLES, f"{word} an hour", "per hour", "use",
                            f"Its rate is {covariate.rate_unit_words(rec)}: how many it makes an hour turns it into "
                            "a rate per hour.",
                            [{"min": 0, "exclusive": True, "severity": "refuse", "why": "it must work to wear"}]))
        return out
    out: list[dict] = []
    if kind == "rate" and rec.get("basis") == "prediction_model":
        if _by_environment(rec):
            out.append(_environment_input(rec))
        q = _quality_input(rec)
        if q:
            out.append(q)
        return out
    if kind == "rate":
        if per_foot(rec):
            out.append(_num(LENGTH, "Pipe length", "ft", "design",
                            "The source's rate is per foot of pipe: the model is for this length.",
                            [{"min": 0, "exclusive": True, "severity": "refuse", "why": "a pipe has some length"}],
                            symbol="L"))
        own = own_clock(rec)
        if own:
            other = "operating" if own == "calendar" else "calendar"
            out.append(_choice(CLOCK, "Clock", "use",
                               [{"code": c, "label": w} for c, w in CLOCKS.items()],
                               ("The hours the model counts. The record's rate is per "
                                + ("calendar hour (running or not)" if own == "calendar" else "hour of running")
                                + ": keep it, or change it and give the hours it runs a year. An RBD's time is "
                                  "calendar time."),
                               default=own, default_basis="record"))
            out.append(_num(RUNNING_HOURS, "Running hours a year", "hours a year", "use",
                            "How many hours a year it runs (of 8,760), to change the rate's clock.",
                            [{"min": 0, "exclusive": True, "severity": "refuse", "why": "it must run some hours"},
                             {"max": HOURS_PER_YEAR, "severity": "refuse", "why": "a year has 8,760 hours"}],
                            needed_if={CLOCK: [other]}))
        return out
    if kind == "per_demand":
        out.append(_num(DEMANDS, "Demands a year", "demands a year", "use",
                        "How often it's asked to work (starts, openings, trips): the probability per demand × the "
                        "demands a year is its rate in calendar time.",
                        [{"min": 0, "exclusive": True, "severity": "refuse", "why": "it must be demanded to fail on demand"}]))
    return out


def keys(rec: dict, resolve: Optional[Resolver] = None) -> list[str]:
    return [i["key"] for i in inputs(rec, resolve)]


#: Keys a record accepts besides its listed inputs: a parts-count line may give its own πQ as a
#: number (a custom screening programme), overriding the grade.
def _extra_keys(rec: dict) -> set[str]:
    return {QUALITY_FACTOR} if (rec.get("quality_factors") or {}).get("levels") else set()


# ---- the old arguments ------------------------------------------------------------------------

#: The old special-case argument → the covariate it is.
LEGACY = {"length_ft": LENGTH, "operating_hours_per_year": RUNNING_HOURS, "time_basis": CLOCK,
          "environment": ENVIRONMENT, "demands_per_year": DEMANDS, "cycles_per_hour": CYCLES,
          "quality_factor": QUALITY_FACTOR, "quality": QUALITY}


def from_legacy(options: Optional[dict] = None, covariates: Optional[dict] = None) -> dict:
    """Covariates from the old arguments (``length_ft``, ``operating_hours_per_year``,
    ``time_basis``, ``environment``, ``demands_per_year``, ``cycles_per_hour``, ``quality_factor``;
    NSWC-11's ``conditions`` dict), with ``covariates`` given explicitly winning. None and blank
    values are left out. ``operating_hours_per_year`` without ``time_basis`` meant "change the
    clock", which is kept: the clock is then the other one (said by :func:`evaluate`)."""
    out: dict = {}
    opts = dict(options or {})
    conds = opts.pop("conditions", None)
    if isinstance(conds, dict):
        out.update({k: v for k, v in conds.items() if v is not None and v != ""})
    for old, new in LEGACY.items():
        v = opts.get(old)
        if v is not None and v != "":
            out[new] = v
    out.update({k: v for k, v in (covariates or {}).items() if v is not None and v != ""})
    return out


# ---- reading values -----------------------------------------------------------------------------

def _limit_side(v: float, limit: dict) -> Optional[str]:
    excl = bool(limit.get("exclusive"))
    lo, hi = limit.get("min"), limit.get("max")
    if lo is not None and (v < lo or (excl and v == lo)):
        return "below"
    if hi is not None and (v > hi or (excl and v == hi)):
        return "above"
    return None


def _limit_words(inp: dict, v: float, limit: dict, side: str) -> str:
    unit = f" {inp['unit']}" if inp.get("unit") else ""
    bound = limit["min"] if side == "below" else limit["max"]
    rel = ("must be more than" if limit.get("exclusive") else "must be at least") if side == "below" else (
        "must be less than" if limit.get("exclusive") else "must be at most")
    if limit.get("severity") == "warn":
        rel = rel.replace("must be", "the handbook's range is")
    why = f": {limit['why']}" if limit.get("why") else ""
    return f"{inp['label']} is {_fmt(v)}{unit}; {rel} {_fmt(bound)}{unit}{why}."


def needed(inp: dict, values: dict) -> bool:
    """Whether an input is asked for, given the values of the others (``needed_if``)."""
    cond = inp.get("needed_if")
    if not cond:
        return True
    return all(values.get(k) in allowed for k, allowed in cond.items())


def read(rec: dict, values: Optional[dict] = None, resolve: Optional[Resolver] = None) -> dict:
    """The record's covariates from ``values`` (a given value, else the default), checked against
    their choices and limits: {values, from: {key: given|default}, warnings, problems, missing}.
    NSWC-11's own inputs are checked by its model (:func:`evaluate`), not here."""
    ins = inputs(rec, resolve)
    given = {k: v for k, v in (values or {}).items() if v is not None and v != ""}
    known = {i["key"] for i in ins} | _extra_keys(rec)
    problems: list[str] = []
    unknown = sorted(k for k in given if k not in known)
    if unknown:
        reads = ", ".join(sorted(known)) or "none"
        problems.append(f"Unknown covariate{'s' if len(unknown) != 1 else ''} {', '.join(unknown)}: "
                        f"'{rec.get('label') or rec.get('id')}' reads {reads}.")
    out: dict = {}
    src: dict = {}
    warnings: list[str] = []
    missing: list[str] = []
    for inp in ins:
        k = inp["key"]
        if k in given:
            raw, src[k] = given[k], "given"
        elif inp.get("default") is not None:
            raw, src[k] = inp["default"], "default"
        else:
            raw = None
        out[k] = raw
    for inp in ins:  # second pass: an input asked for only with some value of another
        k = inp["key"]
        raw = out.get(k)
        if not needed(inp, out):
            if k in given:
                warnings.append(f"{inp['label']} isn't used here (it's only for "
                                + ", ".join(f"{a} = {' or '.join(map(str, b))}" for a, b in inp["needed_if"].items())
                                + ").")
            out.pop(k, None)
            src.pop(k, None)
            continue
        if raw is None:
            if rec.get("kind") == "covariate_model" and k != CYCLES:
                out.pop(k, None)  # its model says what it needs
                continue
            unit = f", in {inp['unit']}" if inp.get("unit") else ""
            problems.append(f"{inp['label']} is needed{unit}: there's no default.")
            missing.append(k)
            out.pop(k, None)
            continue
        if inp["kind"] == "choice":
            codes = [c["code"] for c in inp.get("choices") or []]
            code = str(raw).strip()
            if k == ENVIRONMENT:
                from backend.library import convert

                code = code.upper()
                try:
                    convert.environment_factor(rec, code)
                except convert.ConversionError as exc:  # the handbook's own words for a missing environment
                    problems.append(str(exc))
                    out.pop(k, None)
                    continue
            if codes and code not in codes:
                problems.append(f"{inp['label']} must be one of {', '.join(codes)}, not '{raw}'.")
                out.pop(k, None)
                continue
            out[k] = code
            continue
        if rec.get("kind") == "covariate_model" and k != CYCLES:
            continue  # NSWC-11's own numbers are checked by its model
        try:
            v = float(raw)
        except (TypeError, ValueError):
            problems.append(f"{inp['label']} must be a number, not '{raw}'.")
            out.pop(k, None)
            continue
        if not math.isfinite(v):
            problems.append(f"{inp['label']} must be a finite number.")
            out.pop(k, None)
            continue
        for limit in inp.get("limits") or []:
            side = _limit_side(v, limit)
            if side:
                (problems if limit.get("severity", "refuse") == "refuse" else warnings).append(
                    _limit_words(inp, v, limit, side))
        out[k] = v
    for k in _extra_keys(rec):
        if k in given:
            try:
                v = float(given[k])
            except (TypeError, ValueError):
                problems.append(f"The quality factor must be a number, not '{given[k]}'.")
                continue
            if not (math.isfinite(v) and v > 0):
                problems.append("The quality factor must be a number above 0.")
                continue
            out[k], src[k] = v, "given"
    return {"values": out, "from": src, "warnings": warnings, "problems": problems, "missing": missing}


# ---- the handbook's factors -------------------------------------------------------------------

def handbook_factors(rec: dict, values: dict) -> dict:
    """A MIL-HDBK-217F record's factors for read covariates: {environment: {code, name, factor,
    generic_rate_per_million_hours?} or None, pi_q, quality_source (given | default | none),
    quality_level (the grade's name, for a grade)}. The parts count and the conversions both read
    these, so a line and a block use the same numbers."""
    from backend.library import convert

    env = None
    code = values.get(ENVIRONMENT)
    if code is not None:
        env = convert.environment_factor(rec, code)
    q = rec.get("quality_factors") or {}
    level = None
    if values.get(QUALITY_FACTOR) is not None and not q.get("levels"):
        pi_q, source = float(values[QUALITY_FACTOR]), "given"
    elif q.get("levels") and values.get(QUALITY_FACTOR) is not None:
        pi_q, source = float(values[QUALITY_FACTOR]), "given"
    elif q.get("levels"):
        code_q = values.get(QUALITY) or q.get("default")
        level = next((lv for lv in q["levels"] if lv["code"] == code_q), None)
        pi_q = float(level["value"]) if level else 1.0
        source = ("none" if level is None else "default" if code_q == q.get("default") else "given")
    else:
        pi_q, source = 1.0, "none"
    return {"environment": env, "pi_q": pi_q, "quality_source": source,
            "quality_level": level["name"] if level else None, "quality_code": level["code"] if level else None}


# ---- the one evaluator ------------------------------------------------------------------------

def evaluate(rec: dict, values: Optional[dict] = None, time_unit: str = "hours", point: str = "mean",
             resolve: Optional[Resolver] = None, require_rate: bool = True) -> dict:
    """The record's rate under ``values`` (by covariate key; a missing one takes its default), on
    the clock the covariates say, in ``time_unit``: {record_id, kind, covariates (the values used),
    covariates_from (given | default), failure_rate, unit, clock, rate_per_hour, scale (the rate
    over the record's own mean rate per hour: what a prior's spread is scaled by), bounds, model
    (the block model), rate_uncertainty, assumptions, warnings, badge, source}. A probability per
    demand also gives ``probability``; without demands a year it has no rate, which is missing when
    ``require_rate``. Raises :class:`RecordCovariateError` naming every covariate missing or out of
    its limits."""
    from backend.library import convert

    if resolve is None and rec.get("kind") == "covariate_model":
        from backend.library import service as library

        resolve = library.resolve
    got = read(rec, values, resolve)
    problems, missing = list(got["problems"]), list(got["missing"])
    vals = got["values"]
    kind = rec.get("kind")
    if kind == "per_demand" and not require_rate and DEMANDS in missing:
        # Its probability alone is an answer too: the demands a year only make it a rate in time.
        missing.remove(DEMANDS)
        problems = [p for p in problems if not p.startswith("Demands a year is needed")]
    if problems or missing:
        if not problems:
            problems = [f"{k} is needed." for k in missing]
        raise RecordCovariateError(problems, missing)
    common = {"record_id": rec["id"], "kind": kind, "covariates": vals, "covariates_from": got["from"],
              "warnings": list(got["warnings"])}
    try:
        if kind == "covariate_model":
            return {**common, **_nswc(rec, vals, time_unit, resolve)}
        if kind == "rate":
            hf = handbook_factors(rec, vals) if rec.get("basis") == "prediction_model" else None
            made = convert.rate_to_exponential(
                rec, time_unit, time_basis=vals.get(CLOCK), operating_hours_per_year=vals.get(RUNNING_HOURS),
                length_ft=vals.get(LENGTH), point=point,
                environment=vals.get(ENVIRONMENT),
                quality=None if vals.get(QUALITY) == NOT_APPLIED else vals.get(QUALITY), quality_factor=(vals.get(QUALITY_FACTOR)
                                                           if got["from"].get(QUALITY_FACTOR) == "given" else None))
            per_hour = made["failure_rate"] / convert.hours_per_unit(time_unit)
            mean = schema.mean_of(rec["distribution"]["family"], schema.param_dict(rec["distribution"]))
            out = {**common, **made, "clock": made["time_basis"], "rate_per_hour": per_hour,
                   "scale": per_hour / mean if mean else None}
            if hf is not None:
                out["handbook_factors"] = hf
            return out
        if kind == "per_demand":
            made = convert.demand_to_per_demand(rec, vals.get(DEMANDS), time_unit, point)
            out = {**common, **made}
            rm = made.get("rate_model")
            if rm:
                per_hour = rm["failure_rate"] / convert.hours_per_unit(time_unit)
                out.update(failure_rate=rm["failure_rate"], unit=rm["unit"], clock="calendar",
                           rate_per_hour=per_hour, scale=vals[DEMANDS] / HOURS_PER_YEAR, model=rm["model"],
                           probability_model=made["model"], bounds_rate=rm["bounds"])
            return out
        if kind == "life":
            return {**common, **convert.life_to_model(rec)}
    except convert.ConversionError as exc:
        raise RecordCovariateError([str(exc)]) from None
    raise RecordCovariateError([f"Unknown kind '{kind}'."])


def _nswc(rec: dict, vals: dict, time_unit: str, resolve: Resolver) -> dict:
    """An NSWC-11 model's rate under its conditions (its own inputs) and, per cycle, its cycles an
    hour: the same numbers the parts count and an RBD block use."""
    from backend.library import convert, covariate

    conds = {k: v for k, v in vals.items() if k != CYCLES or not covariate.per_cycle(rec)}
    try:
        got = covariate.evaluate(rec, conds, resolve)
    except covariate.CovariateError as exc:
        raise RecordCovariateError(exc.problems, exc.missing) from None
    per_million = got["total"]
    if covariate.per_cycle(rec):
        per_million *= float(vals[CYCLES])
    per_hour = per_million / 1e6
    rate = per_hour * convert.hours_per_unit(time_unit)
    if not rate > 0:
        raise RecordCovariateError(["Its rate comes out at 0 for these values: check them against the handbook's "
                                    "limits."])
    from backend import units as units_mod

    return {"failure_rate": rate, "unit": units_mod.canonical_unit(time_unit), "clock": "operating",
            "rate_per_hour": per_hour, "scale": None, "bounds": {"p05": None, "p95": None},
            "model": {"distribution_id": "exponential", "params": [{"name": "failure_rate", "value": rate}]},
            "mean_time_to_failure": 1 / rate, "covariate": got,
            "warnings_model": got.get("warnings") or [],
            "assumptions": [f"The handbook's covariate model: {covariate.rate_unit_words(rec)} under these conditions"
                            + (f", × {_fmt(vals[CYCLES])} an hour" if covariate.per_cycle(rec) else "") + "."],
            "badge": convert._badge(rec), "source": convert._origin(rec)}


def words(rec: dict, values: dict, resolve: Optional[Resolver] = None) -> str:
    """The covariates as one line: 'Pipe length 120 ft, Clock calendar hours'."""
    by_key = {i["key"]: i for i in inputs(rec, resolve)}
    parts = []
    for k, v in values.items():
        i = by_key.get(k)
        if i is None:
            continue
        if i["kind"] == "choice":
            shown = next((c["label"] for c in i.get("choices") or [] if c["code"] == v), v)
        else:
            shown = f"{_fmt(v)}{(' ' + i['unit']) if i.get('unit') else ''}"
        parts.append(f"{i['label']} {shown}")
    return ", ".join(parts)
