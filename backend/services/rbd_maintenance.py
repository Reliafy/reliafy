"""What a repairable RBD block holds beyond its life and repair models (#99,
#100, #156, #157): costs, instant repair, scheduled preventive maintenance
(age, block or condition-based replacement, opportunistic renewal in a
maintenance group) and proof-tested hidden failures (staggered, imperfect
tests) — turned into RePyability ``RepairableRBD`` component specs.

Graph format (all optional; a block without any of them is built exactly as
before, as a plain ``NonRepairable``)::

    node.data = {
        ...,                                   # label, model, repair, state
        "instant_repair": true,                # repaired in zero time: it still
                                               #   fails (and costs), never down;
                                               #   no repair model needed
        "costs": {"repair": 200, "replace": 1500,   # charged per failure
                  "downtime": 50,                   # per unit time *this block* is down
                  "acquisition": 20000},            # purchase price (one-off)
        "preventive": {"policy": "age" | "block",   # scheduled replacement
                       "interval": 580, "duration": 7, "cost": 1000,
                       "opportunity": 400},         # age policy: renewed early, from
                                                    #   this age, at a stop of its
                                                    #   maintenance group (#108)
        "preventive": {"policy": "condition",       # replaced on condition (#96):
                       "interval": 720,             #   inspected this often, and
                       "threshold": 0.05,           #   replaced if more likely than
                       "inspection_cost": 40,       #   this to fail before the next
                       "duration": 7, "cost": 1000},
        "inspection": {"interval": 8760,            # hidden failures, found only
                       "duration": 4, "cost": 300,  #   at these proof tests (any
                       "offset": 4380,              #   life, #144); the first test
                       "coverage": 0.9,             #   (staggered), the share of
                       "full_test": 43800},         #   failures a test finds, and
                                                    #   the full test that finds
                                                    #   the rest (#136)
        "maintenance_group": "north pumps",    # shares the group's set-up cost
        "crew_priority": 2,                    # its place in the repair-crew queue
        "rcm_source": {"study_id", "mode_id", ...}, # where the schedule was filled
                                                    #   from (display only: never
                                                    #   analysed, not in the cache key)
    }
    graph["costs"] = {"downtime_rate": 500,    # per unit time the *system* is down
                      "horizon": 87600,        # ownership horizon for the total cost
                      "discount_rate": 7}      # % a year: the total as a present value (#219)
    graph["maintenance_groups"] = {"north pumps": {"setup_cost": 2000,
                                                   "system_down": false}}

The diagram's repair crews, standby groups and safety function are in
:mod:`backend.services.rbd_policies`.

A ``duration`` is a number (a fixed time), ``0``/missing for instant, or a
life-model-like spec (``distribution_id`` + ``params``). A cost charged per
action — ``repair``, ``replace`` and the preventive and test ``cost`` — may be
a range ``{"min": 100, "max": 300}`` instead of a number: RePyability draws it
afresh at every action from a uniform distribution (surpyval's ``Uniform``), so
the simulated cost spreads while the exact cost rate takes its mean. The
downtime cost and the purchase price are single numbers (as in RePyability).
A block has either a
preventive schedule or proof tests, not both (as in RePyability). Times are in
the diagram's unit, costs in whatever currency the user works in.

This module also splits the system's downtime into what failures cause and
what planned outages (maintenance and test durations) add, and extends the
default simulation window so maintenance cycles are covered.
"""

from __future__ import annotations

import copy
import math
from typing import Any, Optional

import numpy as np

from backend.services.rbd_analysis import AnalysisError

#: Block cost fields -> RePyability component spec keys.
COST_KEYS = {
    "repair": "repair_cost",
    "replace": "replace_cost",
    "downtime": "downtime_cost",
    "acquisition": "acquisition_cost",
}
COST_NAMES = {
    "repair": "repair cost",
    "replace": "replacement cost",
    "downtime": "downtime cost per unit time",
    "acquisition": "purchase price",
}
#: The block costs that may be a range (RePyability draws them per failure).
RANGED_COSTS = ("repair", "replace")
POLICIES = ("age", "block", "condition")
#: Block fields beyond the models that make a block a component spec.
EXTRA_KEYS = ("instant_repair", "costs", "preventive", "inspection", "maintenance_group", "crew_priority")
#: The default simulation window covers at least this many of the longest
#: maintenance or test interval in the diagram.
HORIZON_INTERVALS = 10
#: Replications of the planned-outage-free twin used to split simulated
#: downtime into failures and maintenance (paired with the main run's first).
SPLIT_SIMS = 2000


def _blank(value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _number(value, what: str, label: str, *, positive: bool = False) -> Optional[float]:
    """A non-negative (or positive) finite number, None when left blank."""
    if _blank(value):
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        raise AnalysisError(f"“{label}”: the {what} must be a number.") from None
    if not np.isfinite(x) or x < 0 or (positive and x == 0):
        raise AnalysisError(
            f"“{label}”: the {what} must be {'a positive' if positive else 'a non-negative'} "
            "finite number."
        )
    return x


def _cost(value, what: str, label: str, *, ranged: bool = True):
    """A cost: a non-negative number (None when blank) or, where RePyability
    draws it afresh per action (``ranged``), a ``{"min", "max"}`` range as
    surpyval's ``Uniform`` — a range of zero width is just the number."""
    if not isinstance(value, dict):
        return _number(value, what, label)
    if not ranged:
        raise AnalysisError(f"“{label}”: the {what} must be a single number, not a range.")
    if set(value) - {"min", "max"}:
        raise AnalysisError(f"“{label}”: a {what} range takes only a min and a max.")
    low = _number(value.get("min"), f"{what} minimum", label)
    high = _number(value.get("max"), f"{what} maximum", label)
    if low is None or high is None:
        raise AnalysisError(f"“{label}”: the {what} range needs both a min and a max.")
    if low > high:
        raise AnalysisError(f"“{label}”: the {what} range's min is above its max.")
    if low == high:
        return low
    import surpyval as sp

    return sp.Uniform.from_params([low, high])


def _priced(cost) -> bool:
    """Whether a validated cost charges anything (a range always does)."""
    return cost is not None and not (isinstance(cost, float) and cost == 0.0)


def _dict(value, what: str, label: str) -> Optional[dict]:
    if value is None or value is False:
        return None
    if not isinstance(value, dict):
        raise AnalysisError(f"“{label}”: {what} must be an object.")
    return value


def block_costs(data: dict, label: str) -> dict:
    """The block's costs as RePyability spec keys (only those given)."""
    costs = _dict(data.get("costs"), "costs", label) or {}
    unknown = set(costs) - set(COST_KEYS)
    if unknown:
        raise AnalysisError(
            f"“{label}”: unknown cost field(s) {', '.join(sorted(map(str, unknown)))} — "
            f"use {', '.join(COST_KEYS)}."
        )
    out = {}
    for key, spec_key in COST_KEYS.items():
        value = _cost(costs.get(key), COST_NAMES[key], label, ranged=key in RANGED_COSTS)
        if value is not None:
            out[spec_key] = value
    return out


def _duration(raw, what: str, label: str, resolve_model):
    """``"instant"`` (blank or 0), a fixed time (a number), or a model."""
    if _blank(raw) or raw == "instant":
        return "instant"
    if isinstance(raw, dict):
        from backend.services.rbd_analysis import _build_distribution

        return _build_distribution(raw, f"{label} ({what})", resolve_model, None)
    value = _number(raw, what, label)
    if not value:
        return "instant"
    import surpyval as sp

    return sp.ExactEventTime.from_params(value)


def _probability(value, what: str, label: str) -> Optional[float]:
    """A probability in [0, 1], None when left blank."""
    x = _number(value, what, label)
    if x is not None and x > 1.0:
        raise AnalysisError(f"“{label}”: the {what} must be a probability, from 0 to 1.")
    return x


def preventive_spec(data: dict, label: str, resolve_model=None) -> Optional[dict]:
    """RePyability's ``"preventive"`` spec for the block, or None.

    ``"age"`` and ``"block"`` replace on a schedule; ``"condition"`` (#96)
    inspects the unit every ``interval`` while it is up, in no time, and
    replaces it when it is more likely than ``threshold`` to fail before the
    next inspection. An age-replaced block in a maintenance group may also be
    renewed early, from its ``opportunity`` age, at the group's stops (#108).
    """
    pm = _dict(data.get("preventive"), "the preventive maintenance", label)
    if pm is None:
        return None
    policy = pm.get("policy") or "age"
    if policy not in POLICIES:
        raise AnalysisError(
            f"“{label}”: the preventive-maintenance policy must be age, block or condition-based "
            "replacement."
        )
    condition = policy == "condition"
    interval = _number(pm.get("interval"),
                       "inspection interval" if condition else "preventive-maintenance interval",
                       label, positive=True)
    if interval is None:
        raise AnalysisError(
            f"“{label}”: set the inspection interval (how often its condition is checked)."
            if condition else
            f"“{label}”: set the preventive-maintenance interval (how often it's replaced).")
    spec: dict[str, Any] = {
        "interval": interval,
        "policy": policy,
        "duration": _duration(pm.get("duration"), "preventive-maintenance duration", label, resolve_model),
    }
    cost = _cost(pm.get("cost"), "preventive-maintenance cost", label)
    if _priced(cost):
        spec["cost"] = cost
    if condition:
        threshold = _probability(pm.get("threshold"), "replacement threshold", label)
        if threshold is None:
            raise AnalysisError(
                f"“{label}”: set the replacement threshold — the chance of failing before the next "
                "inspection above which the unit is replaced (e.g. 0.05).")
        spec["threshold"] = threshold
        inspecting = _cost(pm.get("inspection_cost"), "condition inspection cost", label)
        if _priced(inspecting):
            spec["inspection_cost"] = inspecting
    else:
        for key, name in (("threshold", "a replacement threshold"), ("inspection_cost", "an inspection cost")):
            if not _blank(pm.get(key)):
                raise AnalysisError(
                    f"“{label}”: {name} applies only to condition-based replacement.")
    opportunity = pm.get("opportunity")
    if not _blank(opportunity):
        if policy != "age":
            raise AnalysisError(
                f"“{label}”: early renewal at a group stop (the opportunity age) applies only to age "
                "replacement.")
        age = _number(opportunity, "opportunity age", label)
        if age > interval:
            raise AnalysisError(
                f"“{label}”: the opportunity age must be from 0 to the replacement interval "
                f"({interval:g}).")
        if maintenance_group(data, label) is None:
            raise AnalysisError(
                f"“{label}”: early renewal needs a maintenance group whose stops give the "
                "opportunity — set the block's maintenance group.")
        spec["opportunity"] = age
    return spec


def inspection_spec(data: dict, label: str, resolve_model=None) -> Optional[dict]:
    """RePyability's ``"inspection"`` spec (hidden failures, proof-tested), or None.

    Any life distribution (#144). A test may be staggered (``offset``, the time
    of the first test) and imperfect (``coverage``, the share of failures a
    test finds; the rest wait for a ``full_test``, which finds every one)."""
    test = _dict(data.get("inspection"), "the proof test", label)
    if test is None:
        return None
    interval = _number(test.get("interval"), "proof-test interval", label, positive=True)
    if interval is None:
        raise AnalysisError(
            f"“{label}”: set the proof-test interval — a hidden failure is only found by a test."
        )
    spec: dict[str, Any] = {
        "interval": interval,
        "duration": _duration(test.get("duration"), "proof-test duration", label, resolve_model),
    }
    cost = _cost(test.get("cost"), "proof-test cost", label)
    if _priced(cost):
        spec["cost"] = cost
    offset = _number(test.get("offset"), "first proof-test time", label)
    if offset:
        if offset >= interval:
            raise AnalysisError(
                f"“{label}”: the first proof test must fall within the first interval — from 0 to "
                f"less than {interval:g}.")
        spec["offset"] = offset
    coverage = _probability(test.get("coverage"), "proof-test coverage", label)
    if coverage is not None and coverage < 1.0:
        full = _number(test.get("full_test"), "full proof-test interval", label, positive=True)
        if full is None:
            raise AnalysisError(
                f"“{label}”: a proof test that finds only {coverage:.0%} of failures needs a full test "
                "that finds the rest — set the full-test interval (a whole multiple of the test "
                "interval).")
        ratio = full / interval
        if round(ratio) < 1 or abs(ratio - round(ratio)) > 1e-9 * ratio:
            raise AnalysisError(
                f"“{label}”: the full-test interval ({full:g}) must be a whole multiple of the "
                f"proof-test interval ({interval:g}).")
        spec["coverage"] = coverage
        spec["full_test"] = interval * round(ratio)
    return spec


def maintenance_group(data: dict, label: str) -> Optional[str]:
    """The block's maintenance group name (#108), or None."""
    group = data.get("maintenance_group")
    if _blank(group):
        return None
    if not isinstance(group, str):
        raise AnalysisError(f"“{label}”: the maintenance group must be a name.")
    return group.strip()


def crew_priority(data: dict, label: str) -> Optional[float]:
    """The block's place in the repair-crew queue (higher first), or None."""
    value = data.get("crew_priority")
    if _blank(value):
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        raise AnalysisError(f"“{label}”: the repair-crew priority must be a number.") from None
    if isinstance(value, bool) or not np.isfinite(x):
        raise AnalysisError(f"“{label}”: the repair-crew priority must be a finite number.")
    return x


def has_extras(data: dict) -> bool:
    """Whether a block uses anything beyond a life and a repair model."""
    return any(data.get(key) not in (None, False, "", {}) for key in EXTRA_KEYS)


def repairable_component(data: dict, label: str, reliability, resolve_model=None):
    """The RePyability component of a repairable block: a plain
    ``NonRepairable`` (life + repair), exactly as before, unless the block has
    costs, instant repair or maintenance — then a component spec dict."""
    from backend.services.rbd_analysis import NonRepairable, _repair_distribution

    repair = "instant" if data.get("instant_repair") else _repair_distribution(data, label, resolve_model)
    if not has_extras(data):
        return NonRepairable(reliability, repair)
    spec: dict[str, Any] = {"reliability": reliability, "repairability": repair}
    spec.update(block_costs(data, label))
    preventive = preventive_spec(data, label, resolve_model)
    inspection = inspection_spec(data, label, resolve_model)
    if preventive and inspection:
        raise AnalysisError(
            f"“{label}”: a block has either scheduled preventive maintenance or proof tests "
            "for hidden failures, not both."
        )
    if preventive:
        spec["preventive"] = preventive
    if inspection:
        spec["inspection"] = inspection
    group = maintenance_group(data, label)
    if group is not None:
        if inspection:
            raise AnalysisError(
                f"“{label}”: a block with hidden failures can't be in a maintenance group — nobody "
                "knows it has failed when the group stops.")
        spec["group"] = group
    priority = crew_priority(data, label)
    if priority is not None:
        spec["priority"] = priority
    return spec


def diagram_costs(graph: dict) -> dict:
    """``{"downtime_rate", "horizon", "discount_rate"}`` of the diagram (any
    may be None); the discount rate is a percentage a year (#219)."""
    costs = graph.get("costs")
    if costs is None:
        return {"downtime_rate": None, "horizon": None, "discount_rate": None}
    if not isinstance(costs, dict):
        raise AnalysisError("The diagram's costs must be an object.")
    return {
        "downtime_rate": _number(costs.get("downtime_rate"), "system downtime cost per unit time", "Diagram"),
        "horizon": _number(costs.get("horizon"), "ownership horizon", "Diagram", positive=True),
        "discount_rate": annual_discount(costs.get("discount_rate")),
    }


# ---------------------------------------------------------------------------
# Discounting (#219, RePyability 0.12's ``discount_rate``)
# ---------------------------------------------------------------------------
#: The diagram's time units in a year: a year of 365 days (8760 hours, as in
#: RePyability's own example and the app's "87600 h = 10 years"), a month a
#: twelfth of it.
UNITS_PER_YEAR = {
    "second": 365 * 86400.0, "minute": 365 * 1440.0, "hour": 8760.0, "day": 365.0,
    "week": 365 / 7, "month": 12.0, "year": 1.0,
}
#: The highest discount rate taken, % a year.
MAX_DISCOUNT_RATE = 100.0


def annual_discount(value) -> Optional[float]:
    """A discount rate in % a year (0 to :data:`MAX_DISCOUNT_RATE`), None when
    blank."""
    rate = _number(value, "discount rate (% a year)", "Diagram")
    if rate is not None and rate > MAX_DISCOUNT_RATE:
        raise AnalysisError(f"“Diagram”: the discount rate is a percentage a year, at most "
                            f"{MAX_DISCOUNT_RATE:g}%.")
    return rate


def discount(graph: dict, annual=None) -> Optional[dict]:
    """The discount the total cost of ownership is taken at: ``annual`` (%
    a year) when given, else the diagram's ``costs.discount_rate``; None when
    there is none (or it is 0: undiscounted).

    RePyability's ``discount_rate`` is a continuous rate per unit time of the
    models, so ``annual`` % a year is ``log(1 + annual / 100)`` a year, over
    the diagram's time units in a year. Returns ``{"annual", "per_unit",
    "unit"}``. A diagram whose time unit isn't a calendar one (cycles, km, or
    none) can't be discounted, and the error says so."""
    from backend.units import normalize_unit

    rate = annual_discount(annual) if not _blank(annual) else diagram_costs(graph)["discount_rate"]
    if not rate:
        return None
    unit = normalize_unit(graph.get("unit"))
    per_year = UNITS_PER_YEAR.get(unit or "")
    if per_year is None:
        shown = str(graph.get("unit") or "").strip() or "not set"
        raise AnalysisError(
            "A discount rate is a percentage a year, so it needs the diagram in a calendar time unit "
            f"(hours, days, weeks, months or years); its unit is {shown}. Change the unit, or clear "
            "the discount rate.")
    return {"annual": rate, "per_unit": math.log1p(rate / 100.0) / per_year, "unit": unit}


def downtime_cost_rate(graph: dict) -> float:
    return diagram_costs(graph)["downtime_rate"] or 0.0


def validation_errors(graph: dict) -> list[str]:
    """User-facing problems with the costs and maintenance of a repairable
    diagram (the Validate step reports them before Calculate would)."""
    errors: list[str] = []
    try:
        diagram_costs(graph)
        discount(graph)
    except AnalysisError as exc:
        errors.append(str(exc).replace("“Diagram”: the ", "The "))
    for node in graph.get("nodes") or []:
        if node.get("type") != "component":
            continue
        data = node.get("data") or {}
        if not has_extras(data):
            continue
        label = data.get("label") or node.get("id")
        try:
            block_costs(data, label)
            pm = preventive_spec(data, label)
            test = inspection_spec(data, label)
            if pm and test:
                raise AnalysisError(
                    f"“{label}”: a block has either scheduled preventive maintenance or proof "
                    "tests for hidden failures, not both."
                )
            if test and maintenance_group(data, label) is not None:
                raise AnalysisError(
                    f"“{label}”: a block with hidden failures can't be in a maintenance group — "
                    "nobody knows it has failed when the group stops.")
            crew_priority(data, label)
        except AnalysisError as exc:
            errors.append(str(exc))
        except Exception:  # noqa: BLE001 - a duration model that won't build
            errors.append(f"“{label}”: a maintenance or test duration model can't be built.")
    return errors


def maintained_blocks(graph: dict) -> list[dict]:
    """The component nodes with a preventive schedule or proof tests."""
    return [
        n for n in graph.get("nodes") or []
        if n.get("type") == "component"
        and ((n.get("data") or {}).get("preventive") or (n.get("data") or {}).get("inspection"))
    ]


def _has_outage(spec: Optional[dict]) -> bool:
    d = (spec or {}).get("duration")
    if _blank(d) or d == "instant":
        return False
    if isinstance(d, dict):
        return True
    try:
        return float(d) > 0
    except (TypeError, ValueError):
        return False


def horizon_floor(graph: dict) -> float:
    """The shortest default simulation window that covers the diagram's
    maintenance: :data:`HORIZON_INTERVALS` of its longest preventive or test
    interval (0 for a diagram without maintenance, so its window is as before)."""
    longest = 0.0
    for n in maintained_blocks(graph):
        data = n.get("data") or {}
        for key in ("preventive", "inspection"):
            try:
                longest = max(longest, float((data.get(key) or {}).get("interval") or 0.0))
            except (TypeError, ValueError):
                pass
    return HORIZON_INTERVALS * longest if np.isfinite(longest) else 0.0


def without_planned_outages(graph: dict) -> dict:
    """The diagram with every maintenance and test taking no time — same
    schedules, same failures: what's left of its downtime is the failures'."""
    out = copy.deepcopy(graph)
    for n in out.get("nodes") or []:
        data = n.get("data") or {}
        for key in ("preventive", "inspection"):
            if isinstance(data.get(key), dict):
                data[key] = {**data[key], "duration": None}
    return out


def estimated_unavailability(rbd, t_sim: float, overrides: dict) -> Optional[float]:
    """A quick simulated unavailability, to set the precision target when the
    exact long-run availability isn't known (limited repair crews for
    wear-out lives, say)."""
    from backend.services import rbd_analysis as ra

    try:
        res, _ = ra._simulate(rbd, t_sim, overrides, 5 * ra._AVAIL_PILOT_SIMS)
        window = float(res.system_uptime) / (res.n_simulations * t_sim)
    except Exception:  # noqa: BLE001
        return None
    return 1.0 - window if np.isfinite(window) else None


def downtime_split(graph: dict, resolve_model, overrides: dict, steady, res,
                   t_sim: float) -> Optional[dict]:
    """The system's downtime split into what failures cause and what the
    planned outages (maintenance and test durations) add, for a diagram with
    preventive maintenance or proof tests; None otherwise.

    The failures' share is the unavailability of the same diagram with every
    maintenance and test taking no time (same schedules); maintenance is the
    rest. Exact when the long-run availabilities are; otherwise simulated,
    pairing the first :data:`SPLIT_SIMS` histories of the main run with the
    same histories of the outage-free twin (same seed and streams).
    """
    from backend.services import rbd_analysis as ra

    blocks = maintained_blocks(graph)
    if not blocks:
        return None
    data = [(n.get("data") or {}) for n in blocks]
    planned = None
    if res is not None and getattr(res, "n_simulations", 0):
        planned = float(getattr(res, "system_planned_outages", 0) or 0) / res.n_simulations
    out: dict[str, Any] = {
        "planned_outages_per_window": planned,
        "preventive_blocks": sum(1 for d in data if d.get("preventive")),
        "tested_blocks": sum(1 for d in data if d.get("inspection")),
    }
    outages = any(_has_outage(d.get("preventive")) or _has_outage(d.get("inspection")) for d in data)

    if steady is not None:
        total = 1.0 - steady
        if not outages:
            return {**out, "basis": "exact", "total": total, "failures": total, "maintenance": 0.0}
        try:
            twin = ra._build_repairable_rbd(without_planned_outages(graph), resolve_model)[0]
            with np.errstate(all="ignore"):
                failures = 1.0 - float(twin.mean_availability(**overrides))
            return {**out, "basis": "exact", "total": total, "failures": failures,
                    "maintenance": max(total - failures, 0.0)}
        except NotImplementedError:
            pass

    uptimes = np.asarray(getattr(res, "uptimes", None) if res is not None else [], dtype=float)
    if uptimes.size == 0:
        return None
    total = 1.0 - float(np.mean(uptimes)) / t_sim
    if not outages:
        return {**out, "basis": "simulation", "total": total, "failures": total, "maintenance": 0.0}
    m = int(min(uptimes.size, SPLIT_SIMS))
    m -= m % 2
    if m < 2:
        return None
    twin = ra._build_repairable_rbd(without_planned_outages(graph), resolve_model)[0]
    twin_res, _ = ra._simulate(twin, t_sim, overrides, m)
    extra = (np.asarray(twin_res.uptimes, dtype=float)[:m] - uptimes[:m]) / t_sim
    maintenance = max(float(np.mean(extra)), 0.0)
    return {**out, "basis": "simulation", "total": total,
            "failures": max(total - maintenance, 0.0), "maintenance": maintenance,
            "paired_simulations": m}
