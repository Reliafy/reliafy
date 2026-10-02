"""What the compute service runs (#146), and the self-contained requests it
runs them on.

The compute service (``backend/compute_app.py``) has no database: everything
an analysis needs travels in the request. This module builds such a request
from a builder graph on the web side, and runs one on the compute side (or
in-process). It must never import the DB layer — ``backend.db``,
``backend.services.models`` / ``rbds`` / ``access`` — and the tests check that.

What can be inlined. A repairable (availability) diagram is component blocks
— each a life model and a repair model — plus k-of-n voting gates. A
component's *parametric* model (distribution id + parameters, any fitted
extras) is already stored on the node, so the analysis never looks up the
saved model it came from; the saved-model id is dropped from the request.
Models that only exist as a re-fit of saved data — proportional-hazards /
regression (``kind: "regression"``) and non-parametric (``kind:
"nonparametric"``) models, and load-sharing groups — have no serialisable
form, and nested sub-system blocks reference other saved diagrams. A graph
with any of these is not self-contained: :func:`availability_request` returns
None and the web app runs it in-process, as before (the repairable analysis
rejects most of them anyway).
"""

from __future__ import annotations

import json
import math
from typing import Any, Optional

from backend.services import rbd_analysis

# Node-data keys holding a life/repair model spec.
_MODEL_KEYS = ("model", "repair", "standbyModel")
# Model kinds that only exist as a re-fit of a saved model's data.
NEEDS_SAVED_MODEL = frozenset({"regression", "nonparametric"})
# Saved-artifact references: not needed once the model is inline.
_REFERENCE_KEYS = frozenset({"modelId", "model_id"})
# Display-only node fields (React Flow), dropped from the request.
_UI_KEYS = frozenset({
    "position", "positionAbsolute", "selected", "dragging", "width", "height",
    "className", "measured", "style", "sourcePosition", "targetPosition",
    "deletable", "hidden", "zIndex",
})

KINDS = ("availability",)

# Request option bounds (the compute service validates what it is sent).
_MAX_SIMULATIONS = 200_000
_MAX_BUDGET_S = 120.0


class InvalidRequest(ValueError):
    """A compute request that is malformed (not a user's modelling error)."""


def _no_saved_models(model_id: str):
    """The compute path's ``resolve_model``: there is no database here."""
    raise rbd_analysis.AnalysisError(
        "This block uses a saved model that has to be re-fitted from its data, "
        "which the calculation service can't do."
    )


def needs_saved_models(graph: dict) -> list[str]:
    """Labels of the blocks that can't be inlined (see the module docstring)."""
    out = []
    for node in (graph or {}).get("nodes") or []:
        data = node.get("data") or {}
        label = data.get("label") or node.get("id")
        if node.get("type") in ("subsystem", "loadshare"):
            out.append(label)
            continue
        for key in _MODEL_KEYS:
            spec = data.get(key)
            if isinstance(spec, dict) and spec.get("kind") in NEEDS_SAVED_MODEL:
                out.append(label)
                break
    return out


def _clean(value):
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items() if k not in _REFERENCE_KEYS}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    return value


def inline_graph(graph: dict) -> dict:
    """The analysis-relevant graph as plain JSON: nodes reduced to id/type/data
    (no saved-model ids, no layout), edges to source/target."""
    graph = graph or {}
    nodes = [
        {
            "id": n.get("id"),
            "type": n.get("type"),
            "data": _clean({k: v for k, v in (n.get("data") or {}).items() if k not in _UI_KEYS}),
        }
        for n in graph.get("nodes") or []
        if isinstance(n, dict)
    ]
    edges = [
        {"source": e.get("source"), "target": e.get("target")}
        for e in graph.get("edges") or []
        if isinstance(e, dict) and e.get("source") and e.get("target")
    ]
    out = {
        "nodes": nodes,
        "edges": edges,
        "unit": (graph.get("unit") or "").strip(),
        "repairable": bool(graph.get("repairable")),
        "ccf_groups": graph.get("ccf_groups") or [],
    }
    # A JSON round trip: plain types only, exactly what the queue will carry.
    return json.loads(json.dumps(out, default=str))


def availability_options(
    t_simulation: Optional[float] = None,
    n_simulations: Optional[int] = None,
    time_budget_s: Optional[float] = None,
    seed: Optional[int] = None,
    max_replications: Optional[int] = None,
) -> dict:
    """The options of an availability run, without the unset ones."""
    raw = {
        "t_simulation": t_simulation,
        "n_simulations": n_simulations,
        "time_budget_s": time_budget_s,
        "seed": seed,
        "max_replications": max_replications,
    }
    return {k: v for k, v in raw.items() if v is not None}


def availability_request(graph: dict, **options) -> Optional[dict]:
    """A self-contained availability request ``{"graph", "options"}``, or None
    when the graph needs saved models the compute service can't have."""
    if needs_saved_models(graph):
        return None
    return {"graph": inline_graph(graph), "options": availability_options(**options)}


def _number(options: dict, key: str, lo: float, hi: float, integer: bool = False):
    value = options.get(key)
    if value is None:
        return None
    try:
        value = int(value) if integer else float(value)
    except (TypeError, ValueError):
        raise InvalidRequest(f"{key} must be a number.") from None
    if not math.isfinite(value) or not lo <= value <= hi:
        raise InvalidRequest(f"{key} must be between {lo:g} and {hi:g}.")
    return value


def _validated_options(options: Any) -> dict:
    if options is None:
        options = {}
    if not isinstance(options, dict):
        raise InvalidRequest("options must be an object.")
    unknown = set(options) - {"t_simulation", "n_simulations", "time_budget_s", "seed", "max_replications"}
    if unknown:
        raise InvalidRequest(f"Unknown options: {', '.join(sorted(unknown))}.")
    out = {
        "t_simulation": _number(options, "t_simulation", 0.0, 1e300),
        "n_simulations": _number(options, "n_simulations", 1, _MAX_SIMULATIONS, integer=True),
        "time_budget_s": _number(options, "time_budget_s", 0.0, _MAX_BUDGET_S),
        "seed": _number(options, "seed", 0, 2**63 - 1, integer=True),
        "max_replications": _number(options, "max_replications", 1, _MAX_SIMULATIONS, integer=True),
    }
    return {k: v for k, v in out.items() if v is not None}


def run_availability(request: dict) -> dict:
    """Run a self-contained availability request. Raises
    :class:`rbd_analysis.AnalysisError` for a diagram that can't be analysed
    and :class:`InvalidRequest` for a malformed request."""
    if not isinstance(request, dict) or not isinstance(request.get("graph"), dict):
        raise InvalidRequest("The request needs a graph.")
    graph = request["graph"]
    if not graph.get("repairable"):
        raise InvalidRequest("Only repairable (availability) diagrams are computed here.")
    options = _validated_options(request.get("options"))
    return rbd_analysis.analyze_availability(graph, resolve_model=_no_saved_models, **options)


def run(kind: str, request: dict) -> dict:
    """Run one compute request of ``kind`` and return its JSON-able result."""
    if kind != "availability":
        raise InvalidRequest(f"Unknown kind {kind!r}.")
    result = run_availability(request)
    # Plain types only (no numpy scalars), as the result crosses the wire.
    return json.loads(json.dumps(result, default=float))
