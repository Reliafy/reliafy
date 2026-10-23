"""From a library record to a model an RBD block can use. Pure functions:
no database, no RBD code.

- A rate becomes an exponential (:func:`rate_to_exponential`). A rate per
  calendar hour (leaks, spurious operation) and a rate per hour of running
  (fails to run) are different numbers for a component that doesn't run all
  year: converting one to the other needs the hours it runs a year.
- A gamma (or lognormal) spread on a rate gives the point value and its 5th
  and 95th percentiles (:func:`spread`), from the parameters themselves.
- A probability per demand stays a probability per demand
  (:func:`demand_to_per_demand`): the per-demand reliability, the start-success
  probability of a cold-standby spare, and, given how often it's demanded, an
  equivalent rate in time.
- A Weibull record (beta and eta) is a Weibull (:func:`life_to_model`).

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
            "citation": rec["citation"], "licence": rec["licence"]}


def _badge(rec: dict) -> str:
    return (f"Generic estimate from published data ({rec['citation'].get('report') or rec['source']}, "
            f"{rec['citation']['table']}), not your equipment's own: replace it with your own failure data "
            "when you have it.")


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


def _hours_rate(rec: dict, value: Optional[float], length_ft: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    if rec["units"]["value"] == "per_hour_per_foot":
        return value * length_ft
    return value


def rate_to_exponential(rec: dict, time_unit: str = "hours", time_basis: Optional[str] = None,
                        operating_hours_per_year: Optional[float] = None, length_ft: Optional[float] = None,
                        point: Point = "mean") -> dict:
    """An exponential model (failure_rate in ``time_unit``) from a rate record.

    ``time_basis``: the block's clock, 'operating' (hours of running) or
    'calendar'; by default the record's own. Changing it needs
    ``operating_hours_per_year`` (how many hours a year the component runs).
    A pipe's rate is per foot: give ``length_ft``."""
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
    factor = 1.0
    assumptions: list[str] = []
    if target != own_basis:
        if not operating_hours_per_year or not 0 < operating_hours_per_year <= HOURS_PER_YEAR:
            raise ConversionError(
                f"'{rec['label']}' is per {'calendar hour' if own_basis == 'calendar' else 'hour of running'}; "
                f"to use it per {'hour of running' if target == 'operating' else 'calendar hour'} give "
                "operating_hours_per_year (0 to 8760), the hours a year the component runs.")
        factor = (HOURS_PER_YEAR / operating_hours_per_year if own_basis == "calendar"
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
    return {
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
    """A Weibull record as a Weibull model, in the record's own time unit."""
    if rec["kind"] != "life":
        raise ConversionError(f"'{rec['label']}' isn't a life distribution.")
    family = rec["distribution"]["family"]
    return {
        "model": {"distribution_id": family, "params": [dict(p) for p in rec["distribution"]["params"]]},
        "unit": units_mod.canonical_unit(rec["units"]["value"]),
        "assumptions": [],
        "badge": _badge(rec),
        "source": _origin(rec),
    }


def to_block_model(rec: dict, **options) -> dict:
    """The record as a block model, by its kind (options go to the converter)."""
    if rec["kind"] == "rate":
        return rate_to_exponential(rec, **options)
    if rec["kind"] == "per_demand":
        return demand_to_per_demand(rec, **options)
    if rec["kind"] == "life":
        return life_to_model(rec, **options)
    raise ConversionError(f"Unknown kind '{rec['kind']}'.")
