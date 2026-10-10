"""Allocation: what each block needs for the system to meet a target (#53).

Given a system target — a reliability at a mission time for a non-repairable
diagram, a long-run availability for a repairable one — this apportions it to
the blocks with RePyability's allocation methods (0.13), and shows what each
block needs against what it has now.

Non-repairable (``NonRepairableRBD``, each block's reliability at ``t``):

* ``equal`` — ``equal_allocation``: every block the same reliability;
* ``simple`` — ``simple_allocation``: the smallest weighted change from 50/50,
  by the diagram's structure alone (no component data);
* ``minimum_effort`` — ``minimum_effort_allocation``: Albert's method for a
  series system, raising the weakest blocks to one common level;
* ``improvement`` — ``improvement_allocation``: every free block's
  unreliability cut by one common factor, with blocks held fixed;
* ``cost_based`` — ``cost_based_allocation``: Mettas's cheapest allocation,
  from each block's maximum reliability and feasibility.

Repairable (``RepairableRBD``, long-run availability):

* ``availability`` — ``availability_allocation``: each block's availability
  (by cost-based, improvement, minimum-effort or equal apportionment), and
  the MTTF or the MTTR that gives it;
* ``mttf_mttr`` — ``mttf_mttr_allocation``: the cheapest MTTF and MTTR
  pair for each block (or only one lever).

An unreachable target raises :class:`AllocationError` with the reachable
range RePyability reports. Nothing is saved.
"""

from __future__ import annotations

import copy
import math
import re
import warnings
from typing import Any, Callable, Optional

import numpy as np

from backend.services import rbd_analysis
from backend.services.rbd_analysis import AnalysisError

NONREPAIRABLE_METHODS = ("equal", "simple", "minimum_effort", "improvement", "cost_based")
REPAIRABLE_METHODS = ("availability", "mttf_mttr")
#: ``availability_allocation``'s own methods (its ``method`` argument).
AVAILABILITY_METHODS = ("cost_based", "improvement", "minimum_effort", "equal")
LEVERS = ("both", "mttf", "mttr")

#: Plain names, for messages and the MCP tool.
METHOD_NAMES = {
    "equal": "Equal",
    "simple": "Simple (weighted)",
    "minimum_effort": "Minimum effort",
    "improvement": "Improvement",
    "cost_based": "Cost-based",
    "availability": "Availability",
    "mttf_mttr": "MTTF and MTTR",
}

# RePyability's reachable-range wording (0.13).
_RANGE = re.compile(r"can only range from ([-+0-9.eE]+) to ([-+0-9.eE]+)")
_BETWEEN = re.compile(r"strictly between ([-+0-9.eE]+) and ([-+0-9.eE]+)")
_APPROACH = re.compile(r"\(([-+0-9.eE]+)\) the system can only approach ([-+0-9.eE]+)")
_AT_MOST = re.compile(r"hold the system to at most ([-+0-9.eE]+)")


class AllocationError(ValueError):
    """A target or setting that can't be allocated (user-facing text).
    ``reachable`` is ``{"low", "high", "high_reached"}`` when the target is
    out of reach."""

    def __init__(self, message: str, reachable: Optional[dict] = None):
        super().__init__(message)
        self.reachable = reachable


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------
def _number(raw, what: str, low: float, high: float, *, low_open=False, high_open=False) -> float:
    if isinstance(raw, bool):
        raise AllocationError(f"{what} must be a number.")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise AllocationError(f"{what} must be a number.") from None
    bad = (not math.isfinite(value) or value < low or value > high
           or (low_open and value == low) or (high_open and value == high))
    if bad:
        lo, hi = ("above" if low_open else "from"), ("below" if high_open else "to")
        raise AllocationError(f"{what} must be {lo} {low:g} {hi} {high:g}.")
    return value


def _per_block(raw, what: str, ids: dict, low: float, high: float, **kw) -> dict:
    """A ``{block id: number}`` option, checked against the diagram's blocks."""
    if not raw:
        return {}
    if not isinstance(raw, dict):
        raise AllocationError(f"{what} must be an object of block ids and numbers.")
    out = {}
    for bid, value in raw.items():
        if value in (None, ""):
            continue
        if bid not in ids:
            raise AllocationError(f"{what}: “{bid}” isn't a block of this diagram.")
        out[bid] = _number(value, f"{what} for “{ids[bid]}”", low, high, **kw)
    return out


def _fixed(raw, ids: dict) -> list:
    if not raw:
        return []
    if not isinstance(raw, (list, tuple)):
        raise AllocationError("The fixed blocks must be a list of block ids.")
    for bid in raw:
        if bid not in ids:
            raise AllocationError(f"The fixed blocks: “{bid}” isn't a block of this diagram.")
    return list(dict.fromkeys(raw))


def _unpinned(graph: dict) -> dict:
    """The diagram without what-if pins: an allocation is about the blocks'
    real reliability."""
    out = copy.deepcopy(graph)
    for node in out.get("nodes") or []:
        (node.get("data") or {}).pop("state", None)
    return out


def _num(text: str) -> float:
    """A number RePyability quotes at the end of a sentence."""
    return float(text.rstrip("."))


def _reachable(text: str) -> Optional[dict]:
    m = _RANGE.search(text)
    if m:
        return {"low": _num(m.group(1)), "high": _num(m.group(2)), "high_reached": True}
    m = _BETWEEN.search(text)
    if m:
        return {"low": _num(m.group(1)), "high": _num(m.group(2)), "high_reached": False}
    m = _APPROACH.search(text)
    if m:
        return {"low": _num(m.group(1)), "high": _num(m.group(2)), "high_reached": False}
    m = _AT_MOST.search(text)
    if m:
        return {"low": None, "high": _num(m.group(1)), "high_reached": True}
    return None


def _pct(v: float) -> str:
    return f"{v * 100:.6g}%"


def _engine_error(exc: Exception, labels: dict, measure: str, target: float) -> AllocationError:
    """A RePyability refusal in the panel's words: the reachable range for an
    out-of-reach target, the block labels in place of ids otherwise."""
    text = str(exc)
    if "cannot be reached" in text:
        reach = _reachable(text)
        if reach is not None:
            top = "up to" if reach["high_reached"] else "towards (but not to)"
            span = (f"from {_pct(reach['low'])} {top} {_pct(reach['high'])}" if reach["low"] is not None
                    else f"{top} {_pct(reach['high'])}")
            return AllocationError(
                f"A system {measure} of {_pct(target)} can't be reached with these settings: it can go {span}. "
                "Lower the target, free more blocks or raise their limits.",
                reach,
            )
    if "minimum-effort algorithm applies to a series system" in text:
        return AllocationError(
            "Minimum effort works on a series system only (every block on the one path). This diagram has "
            "redundancy: use cost-based or improvement allocation instead.")
    if "No component can be allocated an availability" in text:
        # The engine keeps more blocks than its message names (#84, #282).
        return AllocationError(
            "No block can be allocated an availability: only blocks with corrective repair alone can, so not "
            "those with scheduled maintenance or proof tests, standby groups, sub-systems, members of a "
            "common-cause group or fixed blocks.")
    text = rbd_analysis._with_labels(text, labels)
    return AllocationError(text[:1].upper() + text[1:])


def _model_mean(model) -> Optional[float]:
    """A SurPyval model's mean (its own ``mean()``), or ``None``."""
    try:
        value = float(np.ravel(model.mean())[0])
    except Exception:  # noqa: BLE001 - a model without a mean has none to show
        return None
    return value if math.isfinite(value) else None


# ---------------------------------------------------------------------------
# Non-repairable
# ---------------------------------------------------------------------------
def _nonrepairable(graph, target, method, t, options, resolve_model, resolve_subsystem) -> dict:
    if t is None:
        raise AllocationError("Give the mission time the target reliability is for.")
    t = _number(t, "The mission time", 0.0, math.inf, low_open=True, high_open=True)
    if method not in NONREPAIRABLE_METHODS:
        raise AllocationError(
            "For a non-repairable diagram, the method must be one of: "
            + ", ".join(METHOD_NAMES[m].lower() for m in NONREPAIRABLE_METHODS) + ".")
    if graph.get("ccf_groups"):
        raise AllocationError(
            "Allocation treats the blocks as independent, so it can't meet a target for a diagram with "
            "common-cause groups. Remove the groups (or allocate on a copy without them).")
    try:
        rbd, labels, node_types, *_ = rbd_analysis._build_rbd(
            _unpinned(graph), resolve_subsystem, None, resolve_model)
    except AnalysisError as exc:
        raise AllocationError(str(exc)) from None
    blocks = {nid: labels[nid] for nid in labels if node_types.get(nid) != "knode" and nid in rbd.nodes}
    current = {nid: float(np.ravel(v)[0]) for nid, v in rbd.node_sf(t).items() if nid in blocks}
    system_now = float(np.ravel(rbd.sf(t))[0])
    weights = _per_block(options.get("weights"), "The weights", blocks, 0.0, 1e6)
    fixed = _fixed(options.get("fixed"), blocks)
    notes: list[str] = []
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            if method == "equal":
                allocated = rbd.equal_allocation(target)
            elif method == "simple":
                full = {nid: weights.get(nid, 1.0) for nid in blocks} if weights else None
                allocated = rbd.simple_allocation(target, weights=full)
            elif method == "minimum_effort":
                allocated = rbd.minimum_effort_allocation(target, current)
            elif method == "improvement":
                full = {nid: weights.get(nid, 1.0) for nid in blocks if nid not in fixed} if weights else None
                allocated = rbd.improvement_allocation(target, current, fixed=fixed or None, weights=full)
            else:
                maxima = _per_block(options.get("max"), "The most reliable it can be", blocks, 0.0, 1.0)
                for nid in fixed:
                    maxima[nid] = current[nid]
                feasibility = _per_block(options.get("feasibility"), "The feasibility", blocks, 0.0, 1.0,
                                         high_open=True)
                allocated = rbd.cost_based_allocation(
                    target, current, max_probabilities=maxima or None, feasibility=feasibility or None)
        except (ValueError, KeyError, NotImplementedError) as exc:
            raise _engine_error(exc, labels, "reliability", target) from None
    if any("may not be the cheapest" in str(w.message) for w in caught):
        notes.append("The cost search stopped before it fully converged: this allocation meets the target, but "
                     "may not be the cheapest.")
    achieved = float(np.ravel(rbd.system_probability(
        {nid: np.atleast_1d(v) for nid, v in allocated.items()}))[0])
    rows = []
    for nid, label in blocks.items():
        need = float(allocated.get(nid, current[nid]))
        rows.append({
            "id": nid, "label": label, "current": current[nid], "required": need,
            "fixed": nid in fixed,
        })
    return {
        "kind": "reliability", "method": method, "target": target, "t": t,
        "system": {"current": system_now, "allocated": achieved},
        "blocks": rows, "notes": notes,
    }


# ---------------------------------------------------------------------------
# Repairable
# ---------------------------------------------------------------------------
def _repairable(graph, target, method, options, resolve_model) -> dict:
    if method not in REPAIRABLE_METHODS:
        raise AllocationError("For a repairable diagram, the method must be availability or mttf_mttr.")
    try:
        rbd, labels, gates, *_ = rbd_analysis._build_repairable_rbd(_unpinned(graph), resolve_model)
    except AnalysisError as exc:
        raise AllocationError(str(exc)) from None
    blocks = {nid: label for nid, label in labels.items() if nid not in gates and nid in rbd.components}
    fixed = _fixed(options.get("fixed"), blocks)
    notes: list[str] = []
    status = rbd_analysis.common_cause_status(rbd)
    if status and not status.get("included") and status.get("reason"):
        notes.append("Common-cause groups are left out: " + status["reason"])
    try:
        current = {nid: float(v) for nid, v in rbd.node_availability().items() if nid in blocks}
        system_now = float(rbd.mean_availability())
    except (ValueError, NotImplementedError) as exc:
        from backend.services import rbd_repair_quality

        imperfect = rbd_repair_quality.exact_only_message(graph, "target allocation")
        if imperfect:
            raise AllocationError(imperfect) from None
        raise _engine_error(exc, labels, "availability", target) from None
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            if method == "availability":
                how = options.get("availability_method") or "cost_based"
                if how not in AVAILABILITY_METHODS:
                    raise AllocationError("The availability method must be cost-based, improvement, minimum "
                                          "effort or equal.")
                kwargs: dict[str, Any] = {"fixed": fixed or None}
                if how == "improvement" and options.get("weights"):
                    weights = _per_block(options.get("weights"), "The weights", blocks, 0.0, 1e6)
                    kwargs["weights"] = weights
                if how == "cost_based":
                    maxima = _per_block(options.get("max"), "The most available it can be", blocks, 0.0, 1.0)
                    feasibility = _per_block(options.get("feasibility"), "The feasibility", blocks, 0.0, 1.0,
                                             high_open=True)
                    kwargs.update(max_availabilities=maxima or None, feasibility=feasibility or None)
                result = rbd.availability_allocation(target, how, **kwargs)
            else:
                levers = options.get("levers") or "both"
                if levers not in LEVERS:
                    raise AllocationError("The levers must be both, mttf or mttr.")
                result = rbd.mttf_mttr_allocation(
                    target, levers=levers, fixed=fixed or None,
                    max_mttf=_per_block(options.get("max_mttf"), "The longest MTTF", blocks, 0.0, math.inf,
                                        low_open=True) or None,
                    min_mttr=_per_block(options.get("min_mttr"), "The shortest MTTR", blocks, 0.0, math.inf)
                    or None,
                    mttf_feasibility=_per_block(options.get("mttf_feasibility"), "The MTTF feasibility", blocks,
                                                0.0, 1.0, high_open=True) or None,
                    mttr_feasibility=_per_block(options.get("mttr_feasibility"), "The MTTR feasibility", blocks,
                                                0.0, 1.0, high_open=True) or None,
                )
        except AllocationError:
            raise
        except (ValueError, KeyError, NotImplementedError) as exc:
            raise _engine_error(exc, labels, "availability", target) from None
    if any("may not be the cheapest" in str(w.message) for w in caught):
        notes.append("The cost search stopped before it fully converged: this allocation meets the target, but "
                     "may not be the cheapest.")
    rows = []
    held = []
    for nid, label in blocks.items():
        comp = rbd.components.get(nid)
        reliability = getattr(comp, "reliability", None)
        repair = getattr(comp, "time_to_replace", None)
        row = {
            "id": nid, "label": label, "current": current.get(nid),
            "required": float(result.availability.get(nid, current.get(nid) or 0.0)),
            "fixed": nid in fixed,
            "current_mttf": _model_mean(reliability) if reliability is not None else None,
            "current_mttr": _model_mean(repair) if repair is not None else None,
        }
        if nid in result.mttf:
            row["mttf"] = _finite(result.mttf[nid])
            row["mttr"] = _finite(result.mttr[nid])
        else:
            row["kept"] = True
            if nid not in fixed:
                held.append(label)
        rows.append(row)
    if held:
        notes.append(
            "These blocks keep their availability (scheduled maintenance or proof tests, standby, instant repair "
            "or a common-cause group): " + ", ".join(held[:8]) + ("…" if len(held) > 8 else "") + ".")
    return {
        "kind": "availability", "method": method,
        "availability_method": (options.get("availability_method") or "cost_based")
        if method == "availability" else None,
        "levers": (options.get("levers") or "both") if method == "mttf_mttr" else None,
        "target": target,
        "system": {"current": system_now, "allocated": float(result.system_availability)},
        "blocks": rows, "notes": notes,
    }


def _finite(v) -> Optional[float]:
    v = float(v)
    return v if math.isfinite(v) else None


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------
def allocate(
    graph: dict,
    target,
    method: str,
    t: Optional[float] = None,
    options: Optional[dict] = None,
    resolve_model: Optional[Callable] = None,
    resolve_subsystem: Optional[Callable] = None,
) -> dict:
    """What each block needs for the system to meet ``target``: a reliability
    at ``t`` (non-repairable) or a long-run availability (repairable), by
    ``method``. ``options``: ``weights``, ``fixed``, ``max``, ``feasibility``
    (``{block id: value}``; ``fixed`` a list), and for repairable diagrams
    ``availability_method``, ``levers``, ``max_mttf``, ``min_mttr``,
    ``mttf_feasibility`` and ``mttr_feasibility``. Raises
    :class:`AllocationError`."""
    graph = graph or {}
    options = options or {}
    if not isinstance(options, dict):
        raise AllocationError("The options must be an object.")
    measure = "availability" if graph.get("repairable") else "reliability"
    target = _number(target, f"The target {measure}", 0.0, 1.0, low_open=True, high_open=True)
    if graph.get("repairable"):
        out = _repairable(graph, target, method, options, resolve_model)
    else:
        out = _nonrepairable(graph, target, method, t, options, resolve_model, resolve_subsystem)
    out["unit"] = graph.get("unit") or ""
    return out


def allocate_for_owner(db, graph: dict, owners, target, method: str, t: Optional[float] = None,
                       options: Optional[dict] = None) -> dict:
    """:func:`allocate` with saved models and sub-systems resolved in the
    caller's scope, as the analysis resolves them."""
    from backend.services import models as models_service
    from backend.services import rbds as rbds_service

    def resolve_subsystem(sub_id: str):
        sub = rbds_service.get_rbd(db, sub_id, owners)
        return sub.graph if sub is not None else None

    def resolve_model(model_id: str):
        return models_service.get_live_model(db, model_id, owners)

    return allocate(graph, target, method, t, options, resolve_model, resolve_subsystem)
