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
    "life": "A life distribution in time (e.g. Weibull beta and eta), or a saved parametric life model.",
    "covariate_model": ("A covariate model: a base failure rate scaled by factors for the conditions a part works "
                        "in (load, speed, temperature...), each with the handbook's limits."),
}

#: Where the numbers come from. Never mixed: a record has one basis.
BASES = {
    "field_data": "Counted from equipment in service (operating experience).",
    "prediction_model": "A handbook prediction model (base rates and factors), not observed failures.",
    "certificate": "A manufacturer's or test house's certified figure.",
    "fitted": "A life model fitted in Reliafy and added to a user's own library (a snapshot of the saved model).",
}

#: The unit of the value, by kind. ``per_hour_per_foot`` is a pipe's rate per
#: foot of length. A life's unit is any time or usage unit (hours, cycles,
#: kilometres: whatever the model was fitted in), checked as non-empty text.
VALUE_UNITS = {
    "rate": {"per_hour", "per_hour_per_foot"},
    "per_demand": {"per_demand"},
}

#: For a rate per hour: hours of running, or calendar hours (whether the
#: equipment was running, in standby or shut down).
TIME_BASES = {"operating", "calendar"}

#: Distribution families and their parameter names (SurPyval's where SurPyval
#: has the family). gamma: alpha is the shape and beta the rate, so the mean
#: is alpha / beta (SurPyval's Gamma and the NRC's convention). beta: the
#: mean is a / (a + b). lognormal: mu and sigma of the log. normal: mu and
#: sigma. point: one value with no spread (handbook prediction models).
FAMILIES: dict[str, tuple[str, ...]] = {
    "gamma": ("alpha", "beta"),
    "beta": ("alpha", "beta"),
    "lognormal": ("mu", "sigma"),
    "normal": ("mu", "sigma"),
    "point": ("value",),
    "exponential": ("failure_rate",),
    "weibull": ("alpha", "beta"),
}

#: Which families describe which kind of number. A life is a parametric life
#: distribution in time (the families the app's non-repairable fit offers);
#: the same family names mean a spread on a rate when the kind is ``rate``.
FAMILIES_BY_KIND = {
    "rate": {"gamma", "lognormal", "point", "exponential"},
    "per_demand": {"beta", "lognormal", "point"},
    "life": {"weibull", "exponential", "lognormal", "normal", "gamma"},
}
#: Parameters that may be any real number (the others must be positive).
REAL_PARAMS = {("lognormal", "mu"), ("normal", "mu")}

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
    "microcircuit": "Microcircuits (integrated circuits, memories, SAW devices)",
    "rotating": "Motors, synchros and resolvers",
    "circuit_board": "Printed circuit boards",
    "switch": "Switches (electronic)",
    "connector": "Connectors, sockets and connections",
    "electronic_other": "Other electronic parts (crystals, lamps, lasers, filters, microwave parts)",
    "seal": "Seals and gaskets",
    "spring": "Springs",
    "solenoid": "Solenoids and contactors",
    "bearing": "Bearings",
    "gear": "Gears and splines",
    "actuator": "Actuators",
    "brake_clutch": "Brakes and clutches",
    "compressor": "Compressors",
    "electric_motor": "Electric motors",
    "fastener": "Threaded fasteners",
    "coupling": "Mechanical couplings and joints",
    "mechanism": "Mechanisms (slider cranks, cams, screws)",
    "sensor": "Sensors and transducers",
    "shaft": "Shafts and axles",
    "belt_chain": "Belt and chain drives",
    "other": "Other equipment",
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


def life_mean_of(family: str, params: dict[str, float]) -> float | None:
    """The mean life a life record's parameters imply (None where it isn't
    finite, so nothing shows a 'mean life' that is infinite)."""
    if family == "exponential":
        return 1 / params["failure_rate"]
    if family == "normal":
        return params["mu"]
    mean = mean_of(family, params)
    return mean if math.isfinite(mean) else None


def life_quantile_of(family: str, params: dict[str, float], q: float) -> float | None:
    """The time by which a fraction ``q`` of a life record's population has
    failed (q = 0.1 is the B10 life)."""
    if family == "exponential":
        return float(stats.expon(scale=1 / params["failure_rate"]).ppf(q))
    if family == "normal":
        return float(stats.norm(loc=params["mu"], scale=params["sigma"]).ppf(q))
    return quantile_of(family, params, q)


def life_summary(family: str, params: dict[str, float]) -> dict:
    """A life record's summary: mean, median, b10 and the 5th and 95th
    percentile lives, each None where undefined."""
    return {"mean": life_mean_of(family, params), "median": life_quantile_of(family, params, 0.5),
            "b10": life_quantile_of(family, params, 0.1), "p05": life_quantile_of(family, params, 0.05),
            "p95": life_quantile_of(family, params, 0.95)}


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
    if kind == "covariate_model":
        # Its model is checked by covariate.problems (with the records it uses, by the importer and
        # the tests: here without them); it has no distribution.
        from backend.library import covariate

        if units.get("value") not in covariate.RATE_UNITS:
            bad(f"unknown units {units.get('value')!r} for a covariate model")
        if rec.get("basis") != "prediction_model":
            bad("a covariate model is a prediction model")
        return out + covariate.problems(rec)
    if kind in VALUE_UNITS and units.get("value") not in VALUE_UNITS[kind]:
        bad(f"unknown units {units.get('value')!r} for a {kind}")
    if kind == "life" and not (isinstance(units.get("value"), str) and units["value"].strip()):
        bad("a life needs units.value, the unit its times are in")
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
        if (family, name) in REAL_PARAMS:
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
    if kind == "life":
        _life_summary_problems(family, params, summary, bad)
        return out
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


def _life_summary_problems(family: str, params: dict[str, float], summary: dict, bad) -> None:
    """A life record's stated mean, median, b10 and percentiles must be the ones its parameters
    imply (within the rounding tolerance); a mean that isn't finite is left out."""
    implied = life_summary(family, params)
    for key in ("mean", "median", "b10", "p05", "p95"):
        stated, want = summary.get(key), implied.get(key)
        if want is None:
            if stated is not None:
                bad(f"{key} is undefined for these parameters, so it must be left out")
            continue
        if stated is None:
            continue
        if not isinstance(stated, (int, float)) or not math.isfinite(stated) or abs(want - stated) > QUANTILE_TOLERANCE * abs(want):
            bad(f"{key} {stated!r} disagrees with its parameters' {want:.4g}")


def _rates_problems(block: Any, what: str, bad, each: str) -> dict | None:
    """A table of numbers by the handbook's environments (``environment_factors`` or
    ``generic_rates``; ``each`` names one of its numbers): its values, or None after calling
    ``bad``."""
    values = block.get("values") if isinstance(block, dict) else None
    if not isinstance(values, dict) or not values or not block.get("symbol"):
        bad(f"{what} needs a symbol and values by environment")
        return None
    unknown = sorted(set(values) - set(ENVIRONMENTS))
    if unknown:
        bad(f"unknown environments {', '.join(unknown)} in {what}")
    for code, value in values.items():
        if not _finite_positive(value):
            bad(f"{each} {code} must be a positive number")
    return values


def _parts_count_problems(rec: dict, bad) -> None:
    """A parts-count record (the handbook's Appendix A): generic failure rates by environment
    instead of a base rate and environment factors, its value the reference environment's rate,
    and a quality factor table whose default is one of its levels."""
    pred = rec.get("prediction") or {}
    if rec.get("environment_factors") is not None:
        bad("a parts-count record has generic_rates, not environment_factors")
    values = _rates_problems(rec.get("generic_rates"), "generic_rates", bad, "generic rate")
    if values is None:
        return
    ref = pred.get("reference_environment")
    value = param_dict(rec.get("distribution") or {}).get("value")
    if ref not in values:
        bad("prediction.reference_environment must be one of generic_rates' environments")
    elif value is not None and abs(values[ref] * 1e-6 - value) > BASE_RATE_TOLERANCE * value:
        bad(f"the value {value:g} per hour isn't the {ref} generic rate {values[ref]:g} per million hours")
    q = rec.get("quality_factors")
    if q is None:
        if pred.get("quality_factor_default") is not None:
            bad("a quality_factor_default needs quality_factors")
        return
    levels = q.get("levels") if isinstance(q, dict) else None
    if not isinstance(levels, list) or not levels or not all(
            isinstance(lv, dict) and lv.get("code") and lv.get("name") and _finite_positive(lv.get("value"))
            for lv in levels):
        bad("quality_factors needs levels, each with a code, a name and a positive value")
        return
    by_code = {lv["code"]: lv["value"] for lv in levels}
    if q.get("default") is not None and q["default"] not in by_code:
        bad(f"quality_factors.default {q['default']!r} isn't one of its levels")
    want = by_code.get(q.get("default")) if q.get("default") is not None else None
    if pred.get("quality_factor_default") != want:
        bad("prediction.quality_factor_default must be the default level's value")
    rng = pred.get("quality_factor_range")
    if rng != [min(by_code.values()), max(by_code.values())]:
        bad("prediction.quality_factor_range must span the quality levels")


def _prediction_problems(rec: dict, bad) -> None:
    """A handbook prediction model's extra fields: what the handbook's full
    model is and which of its factors the record leaves out (so nothing
    presents a base rate as the whole prediction), and its environment
    factors, keyed by the handbook's environments. Calls ``bad`` for each
    problem."""
    factors = rec.get("environment_factors")
    if factors is not None:
        _rates_problems(factors, "environment_factors", bad, "environment factor")
    if rec.get("basis") != "prediction_model":
        if factors is not None or rec.get("generic_rates") is not None:
            bad("only a prediction model has environment_factors or generic_rates")
        return
    pred = rec.get("prediction")
    if not isinstance(pred, dict) or not str(pred.get("formula") or "").strip():
        bad("a prediction model needs prediction.formula, the handbook's full model")
        return
    not_applied = pred.get("not_applied")
    if not isinstance(not_applied, list) or not all(
            isinstance(f, dict) and f.get("symbol") and f.get("name") for f in not_applied):
        bad("prediction.not_applied must list each factor left out (symbol and name), or be empty")
    if pred.get("method") == "parts_count" or rec.get("generic_rates") is not None:
        if pred.get("method") != "parts_count":
            bad("a record with generic_rates needs prediction.method 'parts_count'")
        _parts_count_problems(rec, bad)
    base = pred.get("per_million_hours")
    value = param_dict(rec.get("distribution") or {}).get("value")
    if not _finite_positive(base):
        bad("prediction.per_million_hours must be a positive number")
    elif value is not None and abs(base * 1e-6 - value) > BASE_RATE_TOLERANCE * value:
        bad(f"{base:g} per million hours disagrees with the value {value:g} per hour")
