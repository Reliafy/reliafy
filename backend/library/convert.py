"""From a library record to a model an RBD block can use. Pure functions:
no database, no RBD code.

- A rate becomes an exponential (:func:`rate_to_exponential`). A rate per
  calendar hour (leaks, spurious operation) and a rate per hour of running
  (fails to run) are different numbers for a component that doesn't run all
  year: converting one to the other needs the hours it runs a year.
- A gamma (or lognormal) spread on a rate gives the point value and its 5th
  and 95th percentiles (:func:`spread`), from the parameters themselves. The
  model keeps that distribution on its failure rate (:func:`rate_uncertainty`):
  times to failure are exponential given the rate, and the gamma says how the
  rate varies from plant to plant. It is never turned into a gamma *life*
  distribution: the gamma is on the rate, not on the time.
- A probability per demand stays a probability per demand
  (:func:`demand_to_per_demand`): the per-demand reliability, the start-success
  probability of a cold-standby spare, and, given how often it's demanded, an
  equivalent rate in time.
- A Weibull record (beta and eta) is a Weibull (:func:`life_to_model`).
- A handbook base rate with environment factors (MIL-HDBK-217F) needs the
  environment the part works in: the rate is the base rate times that
  environment's factor, and the result says which of the handbook's other
  factors it leaves out.

Every result names its record (id, version, citation, licence) and carries a
badge saying it's a generic estimate, so a block never presents it as the
user's own data. Combinations that can't convert raise
:class:`ConversionError` with what to do instead.
"""

from __future__ import annotations

from typing import Literal, Optional

from backend import units as units_mod
from backend.library import schema

#: Hours in each calendar time unit (a month is a twelfth of a 365-day year).
HOURS_PER = {"second": 1 / 3600, "minute": 1 / 60, "hour": 1.0, "day": 24.0, "week": 168.0,
             "month": 730.0, "year": 8760.0}
HOURS_PER_YEAR = 8760.0

Point = Literal["mean", "median"]


class ConversionError(ValueError):
    """A record that can't become the model asked for, with what to do instead."""


def hours_per_unit(time_unit: str) -> float:
    key = units_mod.normalize_unit(time_unit)
    if key not in HOURS_PER:
        raise ConversionError(f"'{time_unit}' isn't a unit of time this can convert to; use hours, days, weeks, "
                              "months or years.")
    return HOURS_PER[key]


def _origin(rec: dict) -> dict:
    return {"id": rec["id"], "version": rec["version"], "label": rec["label"],
            "citation": rec.get("citation"), "licence": rec.get("licence"),
            **({"model": rec["model"], "library_id": rec["source"]} if rec.get("basis") == "fitted" else {})}


def _badge(rec: dict) -> str:
    if rec.get("basis") == "fitted":
        m = rec.get("model") or {}
        return (f"From your data library: a snapshot of the model “{m.get('name') or rec['label']}” when it was added, "
                "not this equipment's own failure data.")
    where = f"{rec['citation'].get('report') or rec['source']}, {rec['citation']['table']}"
    if rec.get("basis") == "prediction_model":
        return (f"Handbook prediction ({where}), not failures counted in service or your equipment's own: "
                "replace it with your own failure data when you have it.")
    return (f"Generic estimate from published data ({where}), not your equipment's own: replace it with your "
            "own failure data when you have it.")


def spread(rec: dict, point: Point = "mean") -> dict:
    """The record's point value and its 5th and 95th percentiles, computed
    from its distribution's parameters (a point family has no spread: the
    bounds are null)."""
    if point not in ("mean", "median"):
        raise ConversionError("point is 'mean' or 'median'.")
    family = rec["distribution"]["family"]
    params = schema.param_dict(rec["distribution"])
    mean = schema.mean_of(family, params)
    median = schema.quantile_of(family, params, 0.5)
    p05 = schema.quantile_of(family, params, 0.05)
    p95 = schema.quantile_of(family, params, 0.95)
    if point == "median" and median is None:
        raise ConversionError(f"A {family} value has no median of its own; use the mean.")
    return {
        "family": family,
        "point": mean if point == "mean" else median,
        "point_is": point,
        "mean": mean, "median": median, "p05": p05, "p95": p95,
        "error_factor": (p95 / median) if (p95 is not None and median) else None,
    }


def rate_uncertainty(rec: dict, scale: float, point: Optional[float] = None,
                     length_ft: Optional[float] = None, time_unit: str = "hours") -> Optional[dict]:
    """The record's distribution on its rate, carried onto a model whose rate
    is ``scale`` times the record's (length, environment, clock and time unit
    all multiply the rate, so they all go into ``scale``).

    A gamma (shape α, rate β) on λ becomes a gamma with the same shape and
    rate β / scale on scale × λ; a lognormal (mu, sigma on log λ) moves its
    mu by log(scale). The 5th and 95th percentiles are the record's, scaled.
    None for a record with no spread (a point value)."""
    import math

    family = rec["distribution"]["family"]
    params = schema.param_dict(rec["distribution"])
    if family == "gamma":
        out = {"distribution": "gamma", "shape": params["alpha"], "rate": params["beta"] / scale}
    elif family == "lognormal":
        out = {"distribution": "lognormal", "mu": params["mu"] + math.log(scale), "sigma": params["sigma"]}
    else:
        return None
    sp = spread(rec)
    out.update({
        "mean": sp["mean"] * scale,
        "point": (point if point is not None else sp["mean"] * scale),
        "p05": None if sp["p05"] is None else sp["p05"] * scale,
        "p95": None if sp["p95"] is None else sp["p95"] * scale,
        "unit": units_mod.canonical_unit(time_unit),
        "record": {"family": family, "params": dict(params), "units": (rec.get("units") or {}).get("as_given")
                   or (rec.get("units") or {}).get("value"),
                   "time_basis": (rec.get("units") or {}).get("time_basis")},
        "source": {"record_id": rec["id"], "label": rec["label"]},
    })
    if length_ft:
        out["length_ft"] = length_ft
    return out


def _hours_rate(rec: dict, value: Optional[float], length_ft: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    if rec["units"]["value"] == "per_hour_per_foot":
        return value * length_ft
    return value


def _by_environment(rec: dict) -> dict:
    """A handbook record's numbers by environment: its environment factors, or a parts-count
    record's generic rates."""
    return (rec.get("environment_factors") or rec.get("generic_rates") or {}).get("values") or {}


def environment_choices(rec: dict) -> str:
    """The environments a handbook record has factors (or, for a parts-count
    record, generic rates) for, as 'GB (ground, benign), GF (ground, fixed), ...'."""
    values = _by_environment(rec)
    return ", ".join(f"{code} ({schema.ENVIRONMENTS[code][0].lower()})" for code in schema.ENVIRONMENTS
                     if code in values)


def environment_factor(rec: dict, environment: Optional[str]) -> Optional[dict]:
    """The record's factor for ``environment`` (a handbook symbol such as
    'GF'; any case), as {code, name, factor}; None for a record without
    environment factors. Raises :class:`ConversionError` when the record
    needs an environment and none is given, or the one given isn't one it
    has a factor for."""
    factors = rec.get("environment_factors") or rec.get("generic_rates")
    if not factors:
        if environment is not None:
            raise ConversionError(f"'{rec['label']}' doesn't depend on the environment: leave out environment.")
        return None
    if environment is None or not str(environment).strip():
        raise ConversionError(f"'{rec['label']}' is a handbook rate that depends on where the part works: give "
                              f"environment, one of {environment_choices(rec)}.")
    code = str(environment).strip().upper()
    if code not in schema.ENVIRONMENTS:
        raise ConversionError(f"Unknown environment '{environment}'. Use one of {environment_choices(rec)}.")
    if code not in factors["values"]:
        what = "generic rate" if rec.get("generic_rates") else "environment factor"
        raise ConversionError(f"The handbook gives no {what} for {code} "
                              f"({schema.ENVIRONMENTS[code][0].lower()}) for '{rec['label']}'. Use one of "
                              f"{environment_choices(rec)}.")
    if rec.get("generic_rates"):
        return generic_rate(rec, code)
    return {"code": code, "name": schema.ENVIRONMENTS[code][0], "factor": factors["values"][code]}


def generic_rate(rec: dict, code: str) -> dict:
    """A parts-count record's generic rate λg for the environment ``code`` (one it has), as
    {code, name, generic_rate_per_million_hours, factor}: ``factor`` is λg over the record's own
    value (its reference environment's rate), so value × factor is the environment's rate."""
    values = rec["generic_rates"]["values"]
    ref = values[(rec.get("prediction") or {}).get("reference_environment") or "GB"]
    return {"code": code, "name": schema.ENVIRONMENTS[code][0], "generic_rate_per_million_hours": values[code],
            "factor": values[code] / ref}


def quality_default(rec: dict) -> Optional[dict]:
    """A parts-count record's default quality level {code, name, value} (the lowest grade the
    handbook lists), or None."""
    q = rec.get("quality_factors") or {}
    return next((lv for lv in q.get("levels") or [] if lv["code"] == q.get("default")), None)


def _quality_for(rec: dict, quality: Optional[str] = None, quality_factor: Optional[float] = None) -> Optional[dict]:
    """The πQ a handbook record's rate takes: {value, name, given}. A parts-count record: the grade
    asked for (its lowest grade by default), or a number given for it; a part-stress record: the
    number given (none given: None, πQ isn't applied). Raises ConversionError for a grade it hasn't."""
    q = rec.get("quality_factors") or {}
    if quality_factor is not None:
        return {"value": float(quality_factor), "name": "as given", "given": True}
    if not q.get("levels"):
        if quality is not None:
            raise ConversionError(f"'{rec['label']}' has no quality grades: give its quality factor as a number.")
        return None
    code = quality if quality is not None else q.get("default")
    if code is None:
        return None  # the handbook names no default grade: πQ isn't applied unless one is chosen
    level = next((lv for lv in q["levels"] if lv["code"] == code), None)
    if level is None:
        raise ConversionError(f"'{rec['label']}' has no quality grade '{quality}'. Use one of "
                              f"{', '.join(lv['code'] for lv in q['levels'])}.")
    return {"value": float(level["value"]), "name": level["name"], "given": quality is not None
            and quality != q.get("default"), "code": level["code"]}


def _handbook_assumption(rec: dict, env: dict, q: Optional[dict] = None) -> str:
    pred = rec.get("prediction") or {}
    if rec.get("generic_rates"):
        said = (f"Rate = the handbook's parts-count generic rate λg {env['generic_rate_per_million_hours']:g} per "
                f"million hours for {env['name'].lower()} ({env['code']}), environment included")
        if q:
            why = "the handbook's lowest grade" if not q["given"] and q.get("code") else "as given"
            said += f", × πQ {q['value']:g} ({q['name'].lower()}, {why})."
        else:
            said += "."
        held = pred.get("not_applied") or []
        if held:
            said += (" It holds the handbook's other factors at its defaults: "
                     + "; ".join(f"{f['symbol']} ({f['name']}) at {f.get('held_at') or 'its default'}" for f in held)
                     + ".")
        return said
    said = (f"Rate = {pred.get('per_million_hours', 0):g} per million hours × πE {env['factor']:g} for "
            f"{env['name'].lower()} ({env['code']})")
    said += f" × πQ {q['value']:g} (as given)." if q else "."
    left_out = [f for f in pred.get("not_applied") or [] if not (q and f.get("symbol") == "πQ")]
    if not left_out:
        return said + " That's the handbook's whole model for this part."
    names = ", ".join(f"{f['symbol']} ({f['name']})" for f in left_out)
    return (said + f" The handbook's other factors aren't applied: {names}. Real rates depend on them; work them "
            "out from the handbook for your design if it matters.")


def rate_to_exponential(rec: dict, time_unit: str = "hours", time_basis: Optional[str] = None,
                        operating_hours_per_year: Optional[float] = None, length_ft: Optional[float] = None,
                        point: Point = "mean", environment: Optional[str] = None, quality: Optional[str] = None,
                        quality_factor: Optional[float] = None) -> dict:
    """An exponential model (failure_rate in ``time_unit``) from a rate record. These arguments are
    the record's covariates (backend/library/record_covariates.py, which declares them and checks
    them; :func:`to_block_model` takes them as ``covariates`` too).

    ``time_basis``: the block's clock, 'operating' (hours of running) or
    'calendar'; by default the record's own. Changing it needs
    ``operating_hours_per_year`` (how many hours a year the component runs).
    A pipe's rate is per foot: give ``length_ft``. A handbook rate with
    environment factors needs ``environment`` (e.g. 'GF', ground, fixed); a parts-count record takes
    its ``quality`` grade (the lowest by default), and either takes ``quality_factor`` (πQ) as a
    number."""
    if rec["kind"] != "rate":
        hint = " Use demand_to_per_demand." if rec["kind"] == "per_demand" else " Use life_to_model."
        raise ConversionError(f"'{rec['label']}' is a {rec['kind'].replace('_', ' ')} value, not a rate.{hint}")
    own_basis = rec["units"].get("time_basis")
    target = time_basis or own_basis
    if target not in schema.TIME_BASES:
        raise ConversionError("time_basis is 'operating' or 'calendar'.")
    if rec["units"]["value"] == "per_hour_per_foot":
        if not length_ft or length_ft <= 0:
            raise ConversionError(f"'{rec['label']}' is a rate per foot of pipe: give length_ft, the pipe's length "
                                  "in feet.")
    elif length_ft is not None:
        raise ConversionError(f"'{rec['label']}' isn't a rate per foot of pipe: leave out length_ft.")
    env = environment_factor(rec, environment)
    factor = env["factor"] if env else 1.0
    q = _quality_for(rec, quality, quality_factor) if env else None
    if q:
        factor *= q["value"]
    assumptions: list[str] = [_handbook_assumption(rec, env, q)] if env else []
    if target != own_basis:
        if not operating_hours_per_year or not 0 < operating_hours_per_year <= HOURS_PER_YEAR:
            raise ConversionError(
                f"'{rec['label']}' is per {'calendar hour' if own_basis == 'calendar' else 'hour of running'}; "
                f"to use it per {'hour of running' if target == 'operating' else 'calendar hour'} give "
                "operating_hours_per_year (0 to 8760), the hours a year the component runs.")
        factor *= (HOURS_PER_YEAR / operating_hours_per_year if own_basis == "calendar"
                   else operating_hours_per_year / HOURS_PER_YEAR)
        assumptions.append(f"Runs {operating_hours_per_year:g} hours a year (of 8,760).")
    per_unit = hours_per_unit(time_unit)
    if units_mod.normalize_unit(time_unit) in ("month", "year"):
        assumptions.append("A year is 8,760 hours (365 days); a month is a twelfth of that.")
    if length_ft:
        assumptions.append(f"{length_ft:g} feet of pipe.")
    sp = spread(rec, point)

    def scale(v):
        v = _hours_rate(rec, v, length_ft)
        return None if v is None else v * factor * per_unit

    rate = scale(sp["point"])
    unc = rate_uncertainty(rec, (length_ft or 1.0) * factor * per_unit, rate, length_ft, time_unit)
    out = {
        "model": {"distribution_id": "exponential", "params": [{"name": "failure_rate", "value": rate}]},
        "unit": units_mod.canonical_unit(time_unit),
        "time_basis": target,
        "failure_rate": rate,
        "point_is": point,
        "bounds": {"p05": scale(sp["p05"]), "p95": scale(sp["p95"])},
        "mean_time_to_failure": 1 / rate,
        "assumptions": assumptions,
        "badge": _badge(rec),
        "source": _origin(rec),
    }
    if unc:
        out["rate_uncertainty"] = unc
    if env:
        out["environment"] = env
    if q:
        out["quality_factor"] = q
    return out


def demand_to_per_demand(rec: dict, demands_per_year: Optional[float] = None, time_unit: str = "hours",
                         point: Point = "mean") -> dict:
    """A per-demand probability with its spread, the per-demand reliability
    and the start-success probability a cold-standby spare uses; with
    ``demands_per_year``, also an equivalent exponential in ``time_unit``
    (calendar time: failures on demand spread evenly over the year)."""
    if rec["kind"] != "per_demand":
        raise ConversionError(f"'{rec['label']}' is a {rec['kind'].replace('_', ' ')} value, not a probability "
                              "per demand. Use rate_to_exponential.")
    sp = spread(rec, point)
    p = sp["point"]
    out = {
        "model": {"distribution_id": "binomial", "params": [{"name": "p", "value": p}]},
        "probability": p,
        "point_is": point,
        "bounds": {"p05": sp["p05"], "p95": sp["p95"]},
        "reliability_per_demand": 1 - p,
        "start_success_probability": 1 - p,
        "assumptions": [],
        "badge": _badge(rec),
        "source": _origin(rec),
    }
    if demands_per_year is not None:
        if demands_per_year <= 0:
            raise ConversionError("demands_per_year must be above 0.")
        per_unit = hours_per_unit(time_unit)

        def rate(v):
            return None if v is None else v * demands_per_year / HOURS_PER_YEAR * per_unit

        out["rate_model"] = {
            "model": {"distribution_id": "exponential", "params": [{"name": "failure_rate", "value": rate(p)}]},
            "unit": units_mod.canonical_unit(time_unit),
            "time_basis": "calendar",
            "failure_rate": rate(p),
            "bounds": {"p05": rate(sp["p05"]), "p95": rate(sp["p95"])},
        }
        out["assumptions"].append(
            f"Demanded {demands_per_year:g} times a year, evenly: the rate is failures on demand per calendar "
            "time. For a standby component that's only demanded by tests and trips, the per-demand probability "
            "in a proof-test or standby model is the truer picture.")
    return out


def life_to_model(rec: dict) -> dict:
    """A life record (a Weibull table's beta and eta, or a saved model's
    snapshot) as a model of its own family, in the record's own unit, with
    the parameters' bounds where the record has them."""
    if rec["kind"] != "life":
        raise ConversionError(f"'{rec['label']}' isn't a life distribution.")
    d = rec["distribution"]
    params = [{"name": p["name"], "value": p["value"]} for p in d["params"]]
    bounds = {p["name"]: list(p["ci"]) for p in d["params"] if p.get("ci")}
    s = rec.get("summary") or {}
    return {
        "model": {"distribution_id": d["family"], "params": params},
        "unit": units_mod.canonical_unit(rec["units"]["value"]),
        **({"bounds": bounds, "bounds_level": d.get("level")} if bounds else {}),
        "mean_life": s.get("mean"), "b10": s.get("b10"),
        "assumptions": [],
        "badge": _badge(rec),
        "source": _origin(rec),
    }


def to_block_model(rec: dict, covariates: Optional[dict] = None, **options) -> dict:
    """The record as a block model, by its kind. ``covariates`` are the record's covariates by key
    (backend/library/record_covariates.py); the old arguments (``length_ft``,
    ``operating_hours_per_year``, ``time_basis``, ``environment``, ``demands_per_year``,
    ``quality_factor``) still work as aliases, and ``time_unit`` and ``point`` pass through. Only what
    is given is applied: a covariate left out is what the record's own conversion does without it
    (a handbook rate still asks for its environment)."""
    from backend.library import record_covariates as rc

    if rec["kind"] == "covariate_model":
        raise ConversionError(f"'{rec['label']}' is a covariate model: its rate depends on the conditions the part "
                              "works in. Use it in a reliability prediction (a parts-list line's Conditions…), or "
                              "try it on its library page.")
    if rec["kind"] not in ("rate", "per_demand", "life"):
        raise ConversionError(f"Unknown kind '{rec['kind']}'.")
    passthrough = {k: options.pop(k) for k in ("time_unit", "point") if k in options}
    unknown = sorted(k for k in options if k not in rc.LEGACY)
    if unknown:
        raise TypeError(f"to_block_model() got unexpected arguments {', '.join(unknown)}")
    given = rc.from_legacy(options, covariates)
    if rec["kind"] != "rate" and given.get(rc.ENVIRONMENT) is not None:
        raise ConversionError(f"'{rec['label']}' doesn't depend on the environment: leave out environment.")
    if rec["kind"] == "life":
        return life_to_model(rec)
    read = rc.read(rec, given)
    if len(read["problems"]) > len(read["missing"]):  # a missing one is said by the conversion itself
        raise ConversionError(" ".join(read["problems"]))
    vals = {k: v for k, v in read["values"].items() if read["from"].get(k) == "given" or k == rc.CLOCK}
    if rec["kind"] == "per_demand":
        return demand_to_per_demand(rec, vals.get(rc.DEMANDS), **passthrough)
    return rate_to_exponential(
        rec, time_basis=vals.get(rc.CLOCK), operating_hours_per_year=vals.get(rc.RUNNING_HOURS),
        length_ft=vals.get(rc.LENGTH), environment=given.get(rc.ENVIRONMENT),
        quality=None if vals.get(rc.QUALITY) == rc.NOT_APPLIED else vals.get(rc.QUALITY),
        quality_factor=vals.get(rc.QUALITY_FACTOR), **passthrough)
