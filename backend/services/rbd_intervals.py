"""Maintenance and proof-test intervals chosen together for a repairable RBD
(#172, #228), on RePyability 0.12's ``optimal_replacement_intervals`` and
``optimal_inspection_intervals``.

* **Scheduled replacement** (``schedule="replacement"``): the age-replacement
  interval of each block under age replacement, chosen together (a block whose
  failure stops the system is worth replacing sooner than one with a standby),
  by a gradient search over the exact long-run values. An interval may come
  out as "never" (run to failure).
* **Proof tests** (``schedule="proof_test"``): the test interval of each block
  with hidden failures, from a calendar (``allowed``: monthly, quarterly, …,
  in the diagram's unit, and the block's own interval), every combination
  tried up to RePyability's 2000 and a local search beyond. With ``stagger``
  the first tests' times are chosen too, as even shares of the interval
  (``offsets="stagger"``): testing redundant channels apart finds a
  common-cause failure sooner. The best plan with every test at the same time
  is found beside it, so the effect of staggering on the PFDavg and the cost
  shows.

The target is one of: the lowest long-run cost rate (default), the lowest
cost that keeps the availability at least ``min_availability`` (for a safety
function, a PFDavg of at most ``max_pfd``, or the top of a ``target_sil``
band), or the highest availability within ``max_cost_rate``. A safety
function's common-cause groups are in the PFDavg the intervals are chosen by
(as in the analysis's PFDavg), where RePyability's chain covers them.

Repair crews (#228). The exact long-run values the intervals are chosen by
have no place for a block waiting for a crew (RePyability's Markov chain of
the repair queue has none for scheduled maintenance or tests). With the
diagram's crews limited the choice is refused unless
``assume_unlimited_crews``: then the intervals are chosen as if every repair
started at once, the result says so, and the diagram with the plan on it
(:func:`apply_plan`) is what the app and MCP simulate with the crews to show
what the waiting costs in availability and PFDavg (the paid simulation).

Everything here is exact (or numerical) and free. A search of more than
:data:`INLINE_EVALUATIONS` candidate plans runs as a compute job (#149, kind
``intervals``; the in-process answer otherwise). Nothing is saved: the
result's ``blocks`` (each block's interval and first test) are what the
builder writes on the canvas (:func:`apply_plan` here), and what Download as
Python then exports.
"""

from __future__ import annotations

import copy
import math
import re
from typing import Any, Optional

import numpy as np

from backend.services import rbd_analysis as ra
from backend.services import rbd_maintenance as rm
from backend.services import rbd_policies as rp
from backend.services.rbd_analysis import AnalysisError
from backend.units import normalize_unit, unit_in_text

SCHEDULES = ("replacement", "proof_test")
#: The most age-replaced blocks chosen at once (a gradient search: quick).
MAX_REPLACED = 12
#: The most proof-tested blocks chosen at once (a search over combinations).
MAX_TESTED = 6
#: The most intervals a proof-tested block chooses from.
MAX_ALLOWED = 8
#: Searches over more candidate plans than this run as a compute job.
INLINE_EVALUATIONS = 250
#: RePyability tries every combination up to this many (a local search beyond).
EXHAUSTIVE = 2000
#: The default proof-test calendar, in months: monthly, quarterly, half-yearly,
#: yearly, two-, three- and four-yearly.
CALENDAR_MONTHS = (1, 3, 6, 12, 24, 36, 48)
_TARGETS = ("min_availability", "max_cost_rate", "max_pfd", "target_sil")


def _blank(v) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


def _float(value, what: str) -> float:
    if isinstance(value, bool):
        raise AnalysisError(f"The {what} must be a number.")
    try:
        x = float(value)
    except (TypeError, ValueError):
        raise AnalysisError(f"The {what} must be a number.") from None
    if not math.isfinite(x):
        raise AnalysisError(f"The {what} must be a finite number.")
    return x


def _intervals(raw, where: str) -> list[float]:
    if not isinstance(raw, (list, tuple)):
        raise AnalysisError(f"The intervals to choose from ({where}) must be a list of numbers.")
    out = sorted({_float(v, f"interval to choose from ({where})") for v in raw})
    if not out:
        raise AnalysisError(f"Give at least one interval to choose from ({where}).")
    if out[0] <= 0:
        raise AnalysisError(f"The intervals to choose from ({where}) must be positive.")
    if len(out) > MAX_ALLOWED:
        raise AnalysisError(f"Give at most {MAX_ALLOWED} intervals to choose from ({where}).")
    return out


def options(schedule=None, blocks=None, min_availability=None, max_cost_rate=None, max_pfd=None,
            target_sil=None, allowed=None, stagger=False, assume_unlimited_crews=False) -> dict:
    """The request's options, validated and canonical (JSON-able, unset ones
    left out): what a compute job carries. Raises :class:`AnalysisError`."""
    out: dict[str, Any] = {}
    if not _blank(schedule):
        if schedule not in SCHEDULES:
            raise AnalysisError("Choose the replacement intervals (schedule “replacement”) or the proof-test "
                                "intervals (“proof_test”).")
        out["schedule"] = schedule
    given = {k: v for k, v in (("min_availability", min_availability), ("max_cost_rate", max_cost_rate),
                               ("max_pfd", max_pfd), ("target_sil", target_sil)) if not _blank(v)}
    if len(given) > 1:
        raise AnalysisError("Give one target: a minimum availability, a maximum PFDavg, a target SIL or a "
                            "maximum cost rate (or none, for the lowest cost).")
    for key, value in given.items():
        if key == "target_sil":
            sil = rp._whole(value)
            if sil is None or not 1 <= sil <= 4:
                raise AnalysisError("The target SIL must be 1, 2, 3 or 4.")
            out[key] = sil
            continue
        x = _float(value, {"min_availability": "minimum availability", "max_cost_rate": "maximum cost rate",
                           "max_pfd": "maximum PFDavg"}[key])
        if key == "max_cost_rate":
            if x <= 0:
                raise AnalysisError("The maximum cost rate must be positive.")
        elif not 0.0 < x < 1.0:
            raise AnalysisError(f"The {'minimum availability' if key == 'min_availability' else 'maximum PFDavg'} "
                                "must be between 0 and 1.")
        out[key] = x
    if blocks is not None:
        if not isinstance(blocks, (list, tuple)) or not all(isinstance(b, str) and b for b in blocks):
            raise AnalysisError("blocks must be a list of block ids.")
        if blocks:
            out["blocks"] = list(dict.fromkeys(blocks))
    if allowed is not None and allowed != []:
        if isinstance(allowed, dict):
            out["allowed"] = {str(k): _intervals(v, f"block {k}") for k, v in allowed.items()}
        else:
            out["allowed"] = _intervals(allowed, "every block")
    if stagger:
        out["stagger"] = True
    if assume_unlimited_crews:
        out["assume_unlimited_crews"] = True
    return out


# ---------------------------------------------------------------------------
# The blocks whose intervals can be chosen
# ---------------------------------------------------------------------------
def _label(node: dict) -> str:
    return (node.get("data") or {}).get("label") or node.get("id")


def maintained(graph: dict) -> dict:
    """The blocks under age replacement and with proof tests, as drawn:
    ``{"replacement": [row], "proof_test": [row], "partial": [row]}`` (a row
    ``{id, label, interval, offset}``); ``partial`` are tested blocks whose
    tests miss failures (coverage below 1), whose intervals aren't chosen."""
    out: dict[str, list] = {"replacement": [], "proof_test": [], "partial": []}
    for node in (graph or {}).get("nodes") or []:
        if node.get("type") != "component":
            continue
        data = node.get("data") or {}
        pm, test = data.get("preventive"), data.get("inspection")
        row = {"id": node.get("id"), "label": _label(node)}
        try:
            if isinstance(pm, dict) and (pm.get("policy") or "age") == "age":
                out["replacement"].append({**row, "interval": float(pm.get("interval"))})
            elif isinstance(test, dict):
                interval = float(test.get("interval"))
                offset = 0.0 if _blank(test.get("offset")) else float(test.get("offset"))
                coverage = test.get("coverage")
                partial = not _blank(coverage) and float(coverage) < 1.0
                out["partial" if partial else "proof_test"].append({**row, "interval": interval, "offset": offset})
        except (TypeError, ValueError):
            continue  # an unset or bad interval: the build reports it
    return out


def calendar(graph: dict) -> Optional[list[float]]:
    """The default proof-test calendar (:data:`CALENDAR_MONTHS`) in the
    diagram's unit, or None for a unit that isn't a calendar one."""
    per_year = rm.UNITS_PER_YEAR.get(normalize_unit(graph.get("unit")) or "")
    if per_year is None:
        return None
    return [float(f"{m * per_year / 12.0:.6g}") for m in CALENDAR_MONTHS]


def _schedule(opts: dict, found: dict) -> str:
    if opts.get("schedule"):
        return opts["schedule"]
    kinds = [k for k in SCHEDULES if found[k]]
    if len(kinds) == 1:
        return kinds[0]
    if not kinds:
        raise AnalysisError(_none_message(found))
    raise AnalysisError("The diagram has blocks under age replacement and blocks with proof tests: say which "
                        "intervals to choose (schedule “replacement” or “proof_test”).")


def _none_message(found: dict) -> str:
    if found["partial"]:
        return ("The proof-tested blocks' tests miss some failures (a coverage below 1), whose intervals must "
                "divide their full tests', so they aren't chosen here. Give a block age replacement or full-"
                "coverage proof tests (double-click it → Cost & maintenance).")
    return ("No block has scheduled replacement by age or proof tests to choose intervals for: give one a "
            "preventive schedule (age replacement) or proof tests (double-click it → Cost & maintenance).")


def _chosen(opts: dict, found: dict, schedule: str) -> list[dict]:
    rows = found[schedule]
    if not rows:
        if schedule == "proof_test" and found["partial"]:
            raise AnalysisError(_none_message(found))
        what = "age replacement" if schedule == "replacement" else "proof tests"
        raise AnalysisError(f"No block has {what} to choose intervals for: give one a "
                            + ("preventive schedule (age replacement)" if schedule == "replacement"
                               else "proof test") + " (double-click it → Cost & maintenance).")
    if opts.get("blocks"):
        by_id = {r["id"]: r for r in rows}
        missing = [b for b in opts["blocks"] if b not in by_id]
        if missing:
            what = "under age replacement" if schedule == "replacement" else "proof-tested (with full coverage)"
            raise AnalysisError(f"Block(s) {', '.join(missing)} aren't {what}, so their intervals can't be "
                                "chosen here.")
        rows = [by_id[b] for b in opts["blocks"]]
    limit = MAX_REPLACED if schedule == "replacement" else MAX_TESTED
    if len(rows) > limit:
        what = "replacement" if schedule == "replacement" else "proof-test"
        raise AnalysisError(f"Choose the {what} intervals of at most {limit} blocks at once — pick the blocks "
                            f"(this diagram has {len(rows)}).")
    return rows


def _allowed(opts: dict, graph: dict, rows: list[dict], found: dict) -> Optional[dict]:
    """The intervals each chosen proof-tested block chooses from: the ones
    given, else the calendar with its own interval; None for one block with
    nothing given and no calendar unit (searched continuously)."""
    given = opts.get("allowed")
    base = calendar(graph)
    out = {}
    for row in rows:
        if isinstance(given, dict) and row["id"] in given:
            options_ = list(given[row["id"]])
        elif isinstance(given, list):
            options_ = list(given)
        elif base is not None:
            options_ = sorted({*base, row["interval"]})
        else:
            options_ = None
        if options_ is None:
            out = None
            break
        out[row["id"]] = options_
    if out is None:
        if len(rows) == 1 and len(found["proof_test"]) + len(found["partial"]) == 1 and not opts.get("stagger"):
            return None
        raise AnalysisError("Give the intervals to choose from: the diagram's time unit isn't a calendar one, "
                            "so there's no monthly / quarterly / yearly calendar to start from.")
    return out


def _evaluations(rows: list[dict], allowed: Optional[dict], stagger: bool, every_tested: bool) -> int:
    """How many candidate plans the proof-test search scores (a local search
    beyond :data:`EXHAUSTIVE` is costed as that)."""
    if allowed is None:
        return 40
    count = math.prod(len(allowed[r["id"]]) for r in rows)
    together = count
    if stagger:
        n = len(rows)
        count *= n ** (n - 1 if every_tested else n)
    return min(count, 4 * EXHAUSTIVE) + (min(together, EXHAUSTIVE) if stagger else 0)


def plan(graph: dict, **raw) -> dict:
    """What a request will do, from the graph alone: ``{schedule, n_blocks,
    evaluations, inline}`` (``inline``: answered in the request rather than
    as a job). Raises :class:`AnalysisError` for bad input."""
    opts = options(**raw)
    found = maintained(graph)
    schedule = _schedule(opts, found)
    rows = _chosen(opts, found, schedule)
    if schedule == "replacement":
        return {"schedule": schedule, "n_blocks": len(rows), "evaluations": 0, "inline": True}
    allowed = _allowed(opts, graph, rows, found)
    every = len(rows) == len(found["proof_test"]) + len(found["partial"])
    n = _evaluations(rows, allowed, bool(opts.get("stagger")) and len(rows) > 1, every)
    return {"schedule": schedule, "n_blocks": len(rows), "evaluations": n, "inline": n <= INLINE_EVALUATIONS}


# ---------------------------------------------------------------------------
# Choosing the intervals
# ---------------------------------------------------------------------------
def _target(opts: dict, safety: bool) -> tuple[Optional[float], Optional[float], dict]:
    if opts.get("target_sil") is not None:
        sil = opts["target_sil"]
        high = next(h for s, _, h in rp.SIL_BANDS if s == sil)
        # The band holds PFDavg below its top.
        pfd = high * (1.0 - 1e-9)
        return 1.0 - pfd, None, {"type": "target_sil", "sil": sil, "max_pfd": high}
    if opts.get("max_pfd") is not None:
        return 1.0 - opts["max_pfd"], None, {"type": "max_pfd", "max_pfd": opts["max_pfd"]}
    if opts.get("min_availability") is not None:
        return opts["min_availability"], None, {"type": "min_availability",
                                                "min_availability": opts["min_availability"]}
    if opts.get("max_cost_rate") is not None:
        return None, opts["max_cost_rate"], {"type": "max_cost_rate", "max_cost_rate": opts["max_cost_rate"]}
    return None, None, {"type": "lowest_cost"}


def _sig(x: float, digits: int = 4) -> float:
    if not math.isfinite(x) or x == 0:
        return x
    return float(f"{x:.{digits}g}")


def _figures(cost, availability, safety: bool, min_av, max_cost) -> dict:
    out: dict[str, Any] = {"cost_rate": ra._f(cost), "availability": ra._f(availability)}
    if availability is not None:
        out["unavailability"] = ra._f(1.0 - float(availability))
    if safety and availability is not None:
        pfd = 1.0 - float(availability)
        out["pfd_avg"] = ra._f(pfd)
        out["sil"] = rp.sil_band(pfd)
    if min_av is not None and availability is not None:
        out["meets_target"] = bool(float(availability) >= min_av - 1e-12)
    elif max_cost is not None and cost is not None:
        out["meets_target"] = bool(float(cost) <= max_cost * (1 + 1e-12))
    return out


def _exact(rbd) -> tuple[Optional[float], Optional[float], Optional[str]]:
    try:
        with np.errstate(all="ignore"):
            return float(rbd.expected_cost_rate()), float(rbd.mean_availability()), None
    except (NotImplementedError, ValueError) as exc:
        return None, None, ra.plain_reason(str(exc))


_BEST = re.compile(r"(?:give|cost) is ([-+]?[0-9]+(?:\.[0-9]+)?(?:[eE][-+]?[0-9]+)?)")


def _not_met(text: str, safety: bool, min_av, max_cost, unit: str) -> str:
    m = _BEST.search(text)
    best = float(m.group(1)) if m else None
    if min_av is not None:
        if safety:
            want = f"a PFDavg of at most {1 - min_av:.3g}"
            got = f" the lowest they give is {1 - best:.3g}" if best is not None else ""
        else:
            want = f"an availability of at least {min_av:.6g}"
            got = f" the most they give is {best:.6g}" if best is not None else ""
        return (f"No intervals to choose from meet {want}:{got}. Add shorter intervals to choose from, relax the "
                "target" + (", or stagger the tests" if safety else "") + ".")
    per = f" per {unit_in_text(unit).rstrip('s')}" if unit else " per unit time"
    got = f" the least they cost is {best:.4g}{per}" if best is not None else ""
    return f"No intervals keep the cost rate within {max_cost:.4g}{per}:{got}. Raise the budget."


def _friendly(exc: Exception, labels: dict, safety: bool, min_av, max_cost, unit: str) -> AnalysisError:
    text = str(exc)
    if "cannot be met" in text:
        return AnalysisError(_not_met(text, safety, min_av, max_cost, unit))
    if "Nothing is priced" in text:
        return AnalysisError(
            "Nothing is priced, so no interval costs more than another: give the blocks' "
            + ("proof tests a cost" if safety else "replacements, repairs or tests costs")
            + " (double-click a block → Cost & maintenance), or set the system downtime cost.")
    if "repeat together only after" in text:
        return AnalysisError("These intervals line up again only after too many tests to average over: choose "
                             "intervals that are multiples of one another (monthly, quarterly, yearly…).")
    return AnalysisError("Couldn't choose the intervals: " + ra._component_message(text, labels))


def apply_plan(graph: dict, rows: list[dict]) -> dict:
    """The diagram with a plan's block rows (a result's ``blocks``) on it:
    each block's interval, and a proof-tested block's first test; a
    replacement that is never made (``never``) removes the block's schedule,
    as RePyability's ``with_intervals`` does. Nothing else changes. The app
    does the same on the canvas (``applyIntervals`` in RbdIntervals.jsx)."""
    out = copy.deepcopy(graph)
    by_id = {r["id"]: r for r in rows}
    for node in out.get("nodes") or []:
        row = by_id.get(node.get("id"))
        if row is None:
            continue
        data = node.setdefault("data", {})
        if isinstance(data.get("preventive"), dict):
            if row.get("never"):
                data.pop("preventive", None)
            else:
                data["preventive"] = {**data["preventive"], "interval": float(row["interval"])}
        elif isinstance(data.get("inspection"), dict):
            new = {**data["inspection"], "interval": float(row["interval"])}
            if row.get("offset"):
                new["offset"] = float(row["offset"])
            else:
                new.pop("offset", None)
            data["inspection"] = new
    return out


def _rows(chosen: list[dict], intervals: dict, offsets: Optional[dict], schedule: str) -> list[dict]:
    out = []
    for row in chosen:
        value = float(intervals[row["id"]])
        r: dict[str, Any] = {"id": row["id"], "label": row["label"], "interval_now": row["interval"],
                             "interval": None if math.isinf(value) else value, "never": math.isinf(value)}
        changed = math.isinf(value) or abs(value - row["interval"]) > 1e-9 * row["interval"]
        if schedule == "proof_test":
            if offsets is not None and row["id"] in offsets:
                offset = float(offsets[row["id"]])
            else:
                offset = row["offset"] / row["interval"] * value
            r["offset_now"] = row["offset"]
            r["offset"] = _sig(offset, 9)
            changed = changed or abs(r["offset"] - row["offset"]) > 1e-9 * value
        r["changed"] = bool(changed)
        out.append(r)
    return out


def _ccf_count(graph: dict) -> int:
    return sum(1 for g in graph.get("ccf_groups") or [] if len(g.get("members") or []) >= 2)


def optimise(graph: dict, resolve_model=None, **raw) -> dict:
    """Choose the intervals (see the module docstring). Returns the plan
    beside the diagram as drawn (and, staggering, the best with every test at
    once), each block's interval (and first test) now and in the plan, and
    the crews and common-cause notes; or ``status: "crews_limited"`` when the
    crews are limited and ``assume_unlimited_crews`` wasn't given. Raises
    :class:`AnalysisError`."""
    ra.require_blocks(graph)
    if not (graph or {}).get("repairable"):
        raise AnalysisError("Interval optimisation is for repairable (availability) diagrams.")
    opts = options(**raw)
    from backend.services.rbd_costs import _as_drawn

    drawn = _as_drawn(graph)
    found = maintained(drawn)
    schedule = _schedule(opts, found)
    chosen = _chosen(opts, found, schedule)
    ids = [r["id"] for r in chosen]
    safety = bool(graph.get("safety_function"))
    unit = (graph.get("unit") or "").strip()
    min_av, max_cost, target = _target(opts, safety)
    allowed = _allowed(opts, drawn, chosen, found) if schedule == "proof_test" else None
    stagger = bool(opts.get("stagger")) and schedule == "proof_test" and len(chosen) > 1
    notes: list[str] = []
    if opts.get("stagger") and schedule == "proof_test" and not stagger:
        notes.append("Staggering needs two or more proof-tested blocks chosen together; there's nothing to "
                     "stagger.")
    # The intervals are chosen by the exact long-run values, which take the
    # common-cause groups in wherever RePyability's long-run chain covers
    # them (#136, #226): for any diagram, a safety function's PFDavg or not.
    groups = _ccf_count(drawn)
    with_ccf = "long_run" if groups > 0 else False
    common_cause = None
    labels = {n.get("id"): _label(n) for n in drawn.get("nodes") or []}

    def left_out(reason: str) -> dict:
        what = "PFDavg is" if safety else "figures are"
        return {"groups": groups, "included": False,
                "note": f"The common-cause groups are left out: {reason.rstrip('.')}. The {what} optimistic by "
                        "their contribution."}

    try:
        result = _choose(drawn, resolve_model, with_ccf, schedule, ids, allowed, stagger, min_av, max_cost,
                         opts, safety, unit)
    except NotImplementedError as exc:
        if not (with_ccf and str(exc).startswith(("Common-cause", "Node(s)"))):
            raise
        common_cause = left_out(ra._component_message(str(exc), labels))
        result = _choose(drawn, resolve_model, False, schedule, ids, allowed, stagger, min_av, max_cost, opts,
                         safety, unit)
    if groups and common_cause is None:
        status = result.pop("common_cause_status", None) or {}
        common_cause = ({"groups": groups, "included": True, "note": None} if status.get("included")
                        else left_out(status.get("reason") or "RePyability's long-run chain doesn't cover them."))
    result.pop("common_cause_status", None)
    if result.get("status") == "crews_limited":
        return {"kind": "maintenance_intervals", "schedule": schedule, "unit": unit, **result}

    intervals, offsets = result.pop("intervals"), result.pop("offsets")
    rows = _rows(chosen, intervals, offsets, schedule)
    changed = any(r["changed"] for r in rows)
    together = result.pop("together", None)
    if together is not None:
        t_int, t_off = together.pop("intervals"), together.pop("offsets")
        together["blocks"] = _rows(chosen, t_int, t_off, schedule) if together["met"] else []
    out = {
        "kind": "maintenance_intervals",
        "status": "ok",
        "schedule": schedule,
        "unit": unit,
        "safety_function": safety,
        "target": target,
        "blocks": rows,
        **result,
        "together": together,
        "stagger": stagger,
        "allowed": allowed,
        "common_cause": common_cause,
        "changed": changed,
        "notes": notes,
        "repyability_version": ra._repyability_version(),
    }
    return out


def _choose(drawn: dict, resolve_model, with_ccf: bool, schedule: str, ids: list, allowed: Optional[dict],
            stagger: bool, min_av, max_cost, opts: dict, safety: bool, unit: str) -> dict:
    """The library's choice on the diagram (with or without its common-cause
    groups), and the figures as drawn and with the plan, exactly (as if every
    repair started at once where the crews are limited)."""
    rbd, labels, gate_ids, _, _ = ra._build_repairable_rbd(drawn, resolve_model, with_ccf=with_ccf)
    ccf_status = ra.common_cause_status(rbd)
    crews = rp.crews_summary(rbd, drawn, labels, gate_ids)
    waits = bool(rbd._crews_couple())
    if crews is not None:
        crews = {**crews, "waits": waits, "assumed_unlimited": waits and bool(opts.get("assume_unlimited_crews"))}
        if waits:
            crews["note"] = (
                f"With {crews['crews']} repair crew{'s' if crews['crews'] != 1 else ''} for {crews['jobs']} repair "
                "jobs a block can wait for a crew, which the exact long-run values the intervals are chosen by "
                "leave out (RePyability's Markov chain of the repair queue has no place for scheduled maintenance "
                "or tests).")
    if waits and not opts.get("assume_unlimited_crews"):
        return {"status": "crews_limited", "crews": crews,
                "message": crews["note"] + " Choose the intervals as if every repair started at once "
                           "(assume_unlimited_crews), then simulate the plan with the crews to see what the "
                           "waiting costs."}
    # The diagram with as many crews as jobs: the figures the choice is made by
    # (with the common-cause groups only where the choice has them too).
    twin = rbd if not waits else ra._build_repairable_rbd(
        {**drawn, "repair_crews": None}, resolve_model,
        with_ccf=with_ccf if (ccf_status or {}).get("included") else False)[0]
    kw = {"min_availability": min_av, "max_cost_rate": max_cost, "assume_unlimited_crews": waits}
    try:
        with np.errstate(all="ignore"):
            if schedule == "replacement":
                found = rbd.optimal_replacement_intervals(ids, **kw)
                offsets = None
            else:
                found = rbd.optimal_inspection_intervals(
                    ids, allowed=allowed, offsets="stagger" if stagger else None, **kw)
                offsets = ({n: float(v) for n, v in found.offsets.items()} if found.offsets is not None else None)
            exact = {n: float(v) for n, v in found.intervals.items()}
            # A searched interval goes on the canvas to four significant figures
            # (more if that would miss the target), and the figures are its.
            searched = schedule == "replacement" or allowed is None
            for digits in ((4, 6, None) if searched else (None,)):
                intervals = {n: (v if digits is None else _sig(v, digits)) for n, v in exact.items()}
                planned = twin.with_intervals(intervals, offsets=offsets)
                cost, availability, _ = _exact(planned)
                if _figures(cost, availability, False, min_av, max_cost).get("meets_target", True):
                    break
            together = None
            if stagger:
                try:
                    best = rbd.optimal_inspection_intervals(ids, allowed=allowed, offsets=[0.0], **kw)
                except ValueError as exc:
                    if "cannot be met" not in str(exc):
                        raise
                    together = {"met": False, "intervals": {}, "offsets": {},
                                "message": _not_met(str(exc), safety, min_av, max_cost, unit)}
                else:
                    together = {"met": True, "intervals": {n: float(v) for n, v in best.intervals.items()},
                                "offsets": {n: float(v) for n, v in (best.offsets or {}).items()},
                                **_figures(best.cost_rate, best.availability, safety, min_av, max_cost)}
    except NotImplementedError as exc:
        if str(exc).startswith("Common-cause"):
            raise
        raise _friendly(exc, labels, safety, min_av, max_cost, unit) from exc
    except ValueError as exc:
        raise _friendly(exc, labels, safety, min_av, max_cost, unit) from exc
    now_cost, now_av, now_reason = _exact(twin)
    current = _figures(now_cost, now_av, safety, min_av, max_cost) if now_av is not None else None
    try:
        basis = planned.analysis_routes()["mean_availability"].route
    except Exception:  # noqa: BLE001
        basis = "exact"
    return {
        "intervals": intervals,
        "offsets": offsets,
        "plan": _figures(cost, availability, safety, min_av, max_cost),
        "current": current,
        "current_note": None if current is not None else now_reason,
        "together": together,
        "basis": basis,
        "crews": crews,
        "common_cause_status": ccf_status,
    }
