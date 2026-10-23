"""The library's record schema: the allowed values, the distribution maths
behind each family, and :func:`problems`, the check every shipped record must
pass (the tests run it over every data file, and the importers run it before
writing one). docs/library.md describes the fields in words.

One schema for every source. NRC / INL industry averages (a gamma or beta
spread), handbook prediction models such as MIL-HDBK-217F (a point base rate,
its environment factors and the handbook factors it leaves out) and Weibull
tables (beta and eta, maybe a range) differ in ``kind``, ``basis``,
``distribution.family`` and which optional fields they fill, never in the
shape of a record. Why one shape: search, the API and the
conversions to block models read every source the same way, and a new source
is a data file, not a schema change.
"""

from __future__ import annotations

import math
from typing import Any

from scipy import stats
from scipy.special import gamma as gamma_fn

SCHEMA_VERSION = 1

#: What the numbers are. A record's ``kind``.
KINDS = {
    "rate": "A failure rate: failures per unit of exposure (usually per hour).",
    "per_demand": "A probability of failure on demand (each start, opening or trip).",
    "life": "A life distribution in time (e.g. Weibull beta and eta).",
}

#: Where the numbers come from. Never mixed: a record has one basis.
BASES = {
    "field_data": "Counted from equipment in service (operating experience).",
    "prediction_model": "A handbook prediction model (base rates and factors), not observed failures.",
    "certificate": "A manufacturer's or test house's certified figure.",
}

#: The unit of the value, by kind. ``per_hour_per_foot`` is a pipe's rate per
#: foot of length.
VALUE_UNITS = {
    "rate": {"per_hour", "per_hour_per_foot"},
    "per_demand": {"per_demand"},
    "life": {"hours", "cycles"},
}

#: For a rate per hour: hours of running, or calendar hours (whether the
#: equipment was running, in standby or shut down).
TIME_BASES = {"operating", "calendar"}

#: Distribution families and their parameter names (SurPyval's where SurPyval
#: has the family). gamma: alpha is the shape and beta the rate, so the mean
#: is alpha / beta (SurPyval's Gamma and the NRC's convention). beta: the
#: mean is a / (a + b). lognormal: mu and sigma of the log. point: one value
#: with no spread (handbook prediction models).
FAMILIES: dict[str, tuple[str, ...]] = {
    "gamma": ("alpha", "beta"),
    "beta": ("alpha", "beta"),
    "lognormal": ("mu", "sigma"),
    "point": ("value",),
    "exponential": ("failure_rate",),
    "weibull": ("alpha", "beta"),
}

#: Which families describe which kind of number.
FAMILIES_BY_KIND = {
    "rate": {"gamma", "lognormal", "point", "exponential"},
    "per_demand": {"beta", "lognormal", "point"},
    "life": {"weibull"},
}

#: Licences whose data may be republished. A source under any other licence
#: (or none) is listed as a link only and never has records.
LICENCES = {
    "us-government-work": {
        "name": "U.S. Government work (no copyright asserted)",
        "url": "https://www.nrc.gov/site-help/disclaimer.html",
    },
    "cc-by-4.0": {
        "name": "Creative Commons Attribution 4.0",
        "url": "https://creativecommons.org/licenses/by/4.0/",
    },
    "ogl-uk-3.0": {
        "name": "Open Government Licence v3.0",
        "url": "https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/",
    },
}

#: The library's equipment types (its own words), for filtering and for
#: matching a record to a block.
EQUIPMENT_TYPES = {
    "valve": "Valves",
    "relief_valve": "Relief and safety valves",
    "pump": "Pumps",
    "generator": "Generators",
    "electrical": "Electrical equipment",
    "filter_strainer": "Filters, strainers and screens",
    "instrument_control": "Instruments, logic and relays",
    "control_rod": "Control rods (nuclear)",
    "damper": "Dampers",
    "hvac": "Air handling and chillers",
    "fan": "Fans",
    "compressed_air": "Compressed air",
    "vessel_tank": "Tanks and accumulators",
    "pipe": "Pipes and orifices",
    "heat_exchanger": "Heat exchangers",
    "resistor": "Resistors",
    "capacitor": "Capacitors",
    "inductive": "Transformers and coils (electronic)",
    "semiconductor": "Diodes, transistors and other semiconductors",
    "switch": "Switches (electronic)",
    "connector": "Connectors, sockets and connections",
    "electronic_other": "Other electronic parts (filters, vibrators, microwave parts)",
}

#: The use environments of MIL-HDBK-217F (its Table 3-2), by the handbook's
#: own symbol: the name, and what it covers in our words. A handbook record's
#: ``environment_factors`` are keyed by these.
ENVIRONMENTS: dict[str, tuple[str, str]] = {
    "GB": ("Ground, benign", "Indoors with temperature and humidity controlled: labs, offices, computer rooms."),
    "GF": ("Ground, fixed", "Permanent racks with adequate cooling, perhaps in unheated buildings."),
    "GM": ("Ground, mobile", "On wheeled or tracked vehicles, or carried by hand."),
    "NS": ("Naval, sheltered", "Below deck or sheltered on surface ships; inside submarines."),
    "NU": ("Naval, unsheltered", "On deck, exposed to the weather, or immersed in salt water."),
    "AIC": ("Airborne, inhabited, cargo", "Crewed compartments of transport and cargo aircraft."),
    "AIF": ("Airborne, inhabited, fighter", "Crewed compartments of fighters and other high-performance aircraft."),
    "AUC": ("Airborne, uninhabited, cargo", "Uncrewed bays of transport and cargo aircraft."),
    "AUF": ("Airborne, uninhabited, fighter", "Uncrewed bays of fighters and other high-performance aircraft."),
    "ARW": ("Airborne, rotary winged", "On helicopters, inside or outside."),
    "SF": ("Space, flight", "In orbit or in space, not in powered flight or re-entry."),
    "MF": ("Missile, flight", "Powered flight of missiles, and unpowered free flight."),
    "ML": ("Missile, launch", "Missile and space-vehicle launch, re-entry and landing."),
    "CL": ("Cannon, launch", "Guided projectiles fired from a cannon, from launch to impact."),
}

#: How far a record's stated mean may sit from its parameters' mean. The
#: sources print parameters to three or four significant figures, so a
#: correct record agrees to well under 1%; 2% leaves room for that rounding.
MEAN_TOLERANCE = 0.02
#: The same for the stated 5th, 50th and 95th percentiles (checked where the
#: family has a spread).
QUANTILE_TOLERANCE = 0.02


#: How far (relatively) a handbook record's rate as printed (per million
#: hours) may sit from its value per hour: the same number in other units.
BASE_RATE_TOLERANCE = 1e-9


def param_dict(distribution: dict) -> dict[str, float]:
    return {p["name"]: p["value"] for p in distribution.get("params") or []}


def mean_of(family: str, params: dict[str, float]) -> float:
    """The mean the parameters imply."""
    if family in ("gamma",):
        return params["alpha"] / params["beta"]
    if family == "beta":
        return params["alpha"] / (params["alpha"] + params["beta"])
    if family == "lognormal":
        return math.exp(params["mu"] + params["sigma"] ** 2 / 2)
    if family == "point":
        return params["value"]
    if family == "exponential":
        return params["failure_rate"]
    if family == "weibull":
        return params["alpha"] * float(gamma_fn(1 + 1 / params["beta"]))
    raise ValueError(f"Unknown distribution family '{family}'.")


def quantile_of(family: str, params: dict[str, float], q: float) -> float | None:
    """The q-quantile the parameters imply (None for a point value, or for a
    rate given only as an exponential, which has no spread of its own)."""
    if family == "gamma":
        return float(stats.gamma(a=params["alpha"], scale=1 / params["beta"]).ppf(q))
    if family == "beta":
        return float(stats.beta(params["alpha"], params["beta"]).ppf(q))
    if family == "lognormal":
        return float(stats.lognorm(s=params["sigma"], scale=math.exp(params["mu"])).ppf(q))
    if family == "weibull":
        return float(stats.weibull_min(params["beta"], scale=params["alpha"]).ppf(q))
    return None


def _finite_positive(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v > 0


def problems(rec: dict) -> list[str]:
    """Everything wrong with one record (empty when it may ship)."""
    out: list[str] = []
    rid = rec.get("id") or "<no id>"

    def bad(msg: str) -> None:
        out.append(f"{rid}: {msg}")

    for key in ("id", "source", "name", "label", "source_text"):
        if not isinstance(rec.get(key), str) or not rec[key].strip():
            bad(f"missing {key}")
    if not isinstance(rec.get("version"), int) or rec["version"] < 1:
        bad("version must be a whole number from 1")
    if rec.get("equipment_type") not in EQUIPMENT_TYPES:
        bad(f"unknown equipment_type {rec.get('equipment_type')!r}")
    kind = rec.get("kind")
    if kind not in KINDS:
        bad(f"unknown kind {kind!r}")
    if rec.get("basis") not in BASES:
        bad(f"unknown basis {rec.get('basis')!r}")

    fm = rec.get("failure_mode") or {}
    if not fm.get("code") or not fm.get("name"):
        bad("failure_mode needs a code and a name")

    citation = rec.get("citation") or {}
    for key in ("title", "publisher", "table", "page", "year", "url", "retrieved"):
        if not citation.get(key):
            bad(f"citation is missing {key}")
    licence = rec.get("licence") or {}
    if licence.get("id") not in LICENCES:
        bad(f"licence {licence.get('id')!r} is not one the library may republish")
    if not (licence.get("attribution") or "").strip():
        bad("licence has no attribution text")

    units = rec.get("units") or {}
    if kind in VALUE_UNITS and units.get("value") not in VALUE_UNITS[kind]:
        bad(f"unknown units {units.get('value')!r} for a {kind}")
    if kind == "rate" and units.get("time_basis") not in TIME_BASES:
        bad("a rate needs units.time_basis (operating or calendar)")

    dist = rec.get("distribution") or {}
    family = dist.get("family")
    if family not in FAMILIES:
        bad(f"unknown distribution family {family!r}")
        return out
    if kind in FAMILIES_BY_KIND and family not in FAMILIES_BY_KIND[kind]:
        bad(f"a {family} distribution can't describe a {kind}")
    names = [p.get("name") for p in dist.get("params") or []]
    if sorted(names) != sorted(FAMILIES[family]):
        bad(f"{family} takes {', '.join(FAMILIES[family])}, not {', '.join(map(str, names)) or 'nothing'}")
        return out
    params = param_dict(dist)
    for name, value in params.items():
        if family == "lognormal" and name == "mu":
            ok = isinstance(value, (int, float)) and math.isfinite(value)
        else:
            ok = _finite_positive(value)
        if not ok:
            bad(f"parameter {name} must be a positive number")
    if out:
        return out
    if family == "beta" and kind == "per_demand" and mean_of(family, params) >= 1:
        bad("a probability must be below 1")

    _prediction_problems(rec, bad)
    if out:
        return out

    summary = rec.get("summary") or {}
    mean = summary.get("mean")
    if not _finite_positive(mean):
        bad("summary.mean must be a positive number")
        return out
    implied = mean_of(family, params)
    if abs(implied - mean) > MEAN_TOLERANCE * mean:
        bad(f"mean {mean:.4g} disagrees with its parameters' mean {implied:.4g}")
    p05, p95 = summary.get("p05"), summary.get("p95")
    if p05 is not None and p95 is not None and not (p05 <= mean <= p95):
        bad("summary must have p05 <= mean <= p95")
    for key, q in (("p05", 0.05), ("median", 0.5), ("p95", 0.95)):
        stated = summary.get(key)
        implied_q = quantile_of(family, params, q)
        if stated is None or implied_q is None:
            continue
        if not _finite_positive(stated) or abs(implied_q - stated) > QUANTILE_TOLERANCE * stated:
            bad(f"{key} {stated!r} disagrees with its parameters' {implied_q:.4g}")
    return out


def _prediction_problems(rec: dict, bad) -> None:
    """A handbook prediction model's extra fields: what the handbook's full
    model is and which of its factors the record leaves out (so nothing
    presents a base rate as the whole prediction), and its environment
    factors, keyed by the handbook's environments. Calls ``bad`` for each
    problem."""
    factors = rec.get("environment_factors")
    if factors is not None:
        values = factors.get("values") if isinstance(factors, dict) else None
        if not isinstance(values, dict) or not values or not factors.get("symbol"):
            bad("environment_factors needs a symbol and values by environment")
        else:
            unknown = sorted(set(values) - set(ENVIRONMENTS))
            if unknown:
                bad(f"unknown environments {', '.join(unknown)} in environment_factors")
            for code, value in values.items():
                if not _finite_positive(value):
                    bad(f"environment factor {code} must be a positive number")
    if rec.get("basis") != "prediction_model":
        if factors is not None:
            bad("only a prediction model has environment_factors")
        return
    pred = rec.get("prediction")
    if not isinstance(pred, dict) or not str(pred.get("formula") or "").strip():
        bad("a prediction model needs prediction.formula, the handbook's full model")
        return
    not_applied = pred.get("not_applied")
    if not isinstance(not_applied, list) or not all(
            isinstance(f, dict) and f.get("symbol") and f.get("name") for f in not_applied):
        bad("prediction.not_applied must list each factor left out (symbol and name), or be empty")
    base = pred.get("per_million_hours")
    value = param_dict(rec.get("distribution") or {}).get("value")
    if not _finite_positive(base):
        bad("prediction.per_million_hours must be a positive number")
    elif value is not None and abs(base * 1e-6 - value) > BASE_RATE_TOLERANCE * value:
        bad(f"{base:g} per million hours disagrees with the value {value:g} per hour")
