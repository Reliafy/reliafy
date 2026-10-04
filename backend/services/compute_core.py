"""What the compute service runs (#146), and the self-contained requests it
runs them on.

The compute service (``backend/compute_app.py``) has no database: everything
an analysis needs travels in the request. This module builds such a request
from a builder graph on the web side, and runs one on the compute side (or
in-process). It must never import the DB layer — ``backend.db``,
``backend.services.models`` / ``rbds`` / ``access`` — and the tests check that.

What can be inlined. A repairable (availability) diagram is component blocks
— each a life model and a repair model — plus k-of-n voting gates (junctions
since RePyability 0.12), and the diagram's own settings: common-cause groups
(with their rate/probability basis), costs, repair crews, maintenance groups
and a safety function (:data:`backend.services.rbd_graph.DIAGRAM_KEYS`; every
top-level key is carried, so a new setting needs no change here). A
component's *parametric* model (distribution id + parameters, any fitted
extras) is already stored on the node, so the analysis never looks up the
saved model it came from. Its id stays on the node, never resolved (some
checks compare blocks by it, so dropping it could change a result). Models
that only exist as a re-fit of saved data — proportional-hazards /
regression (``kind: "regression"``) and non-parametric (``kind:
"nonparametric"``) models, and load-sharing groups — have no serialisable
form, and nested sub-system blocks reference other saved diagrams. A graph
with any of these is not self-contained: :func:`availability_request` returns
None and the web app runs it in-process, as before (the repairable analysis
rejects most of them anyway: a non-parametric, Kaplan–Meier block is refused
since RePyability 0.12, so the user hears it at once, not from a job).

Same seed, same result. The compute service runs exactly
:func:`rbd_analysis.analyze_availability`, the in-process path's function, on
the same image: RePyability 0.12 seeds every simulation's draws from the run's
seed and the simulation's index alone, whatever the engine, so a request
gives the in-process result to the last bit. Only where a *time budget*
sizes the run (a Pro run to its precision target that the 20 s budget stops,
or a free quick run) can the count of replications differ with the
machine's speed; the result is then that of the count it reports.

Job kinds (:data:`RUNNERS`). ``availability``, and ``sensitivity`` — what
to improve (#225): a repairable diagram's levers ranked by what a step of
each gains (:mod:`backend.services.rbd_sensitivity`), when that is
numerical, over a window, simulated or large. The next failure from the
current state (#240) is not a kind of its own: the availability analysis
runs it whenever the request carries a ``state``
(:mod:`backend.services.rbd_next_failure`), so it comes back in the same
job, from the same seed. Another analysis joins by adding a request builder
here, a runner to ``RUNNERS``, and a ``KIND_…`` in
:mod:`backend.services.rbd_jobs` — e.g. the exact figures over time of a
large diagram.
"""

from __future__ import annotations

import json
import math
from typing import Any, Callable, Optional

from backend.services import rbd_analysis, rbd_sensitivity

# Node-data keys holding a life/repair model spec.
_MODEL_KEYS = ("model", "repair", "standbyModel")
# Model kinds that only exist as a re-fit of a saved model's data.
NEEDS_SAVED_MODEL = frozenset({"regression", "nonparametric"})
# Display-only node fields (React Flow), dropped from the request.
_UI_KEYS = frozenset({
    "position", "positionAbsolute", "selected", "dragging", "width", "height",
    "className", "measured", "style", "sourcePosition", "targetPosition",
    "deletable", "hidden", "zIndex",
})

# Top-level graph keys the analysis never reads (the builder's view).
_GRAPH_UI_KEYS = frozenset({"viewport", "position", "selected"})

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


def inline_graph(graph: dict) -> dict:
    """The analysis-relevant graph as plain JSON: nodes reduced to id/type/data
    (no layout), edges to source/target, and every diagram-level setting."""
    graph = graph or {}
    nodes = [
        {
            "id": n.get("id"),
            "type": n.get("type"),
            "data": {k: v for k, v in (n.get("data") or {}).items() if k not in _UI_KEYS},
        }
        for n in graph.get("nodes") or []
        if isinstance(n, dict)
    ]
    edges = [
        {"source": e.get("source"), "target": e.get("target")}
        for e in graph.get("edges") or []
        if isinstance(e, dict) and e.get("source") and e.get("target")
    ]
    settings = {k: v for k, v in graph.items()
                if k not in ("nodes", "edges") and k not in _GRAPH_UI_KEYS}
    out = {
        **settings,
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
    state: Optional[dict] = None,
) -> dict:
    """The options of an availability run, without the unset ones. ``state``
    is a canonical current state (``rbd_analysis.parse_current_state``)."""
    raw = {
        "t_simulation": t_simulation,
        "n_simulations": n_simulations,
        "time_budget_s": time_budget_s,
        "seed": seed,
        "max_replications": max_replications,
        "state": state or None,
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


_OPTIONS = frozenset({"t_simulation", "n_simulations", "time_budget_s", "seed", "max_replications", "state"})


def _validated_options(options: Any, graph: dict) -> dict:
    if options is None:
        options = {}
    if not isinstance(options, dict):
        raise InvalidRequest("options must be an object.")
    unknown = set(options) - _OPTIONS
    if unknown:
        raise InvalidRequest(f"Unknown options: {', '.join(sorted(unknown))}.")
    out = {
        "t_simulation": _number(options, "t_simulation", 0.0, 1e300),
        "n_simulations": _number(options, "n_simulations", 1, _MAX_SIMULATIONS, integer=True),
        "time_budget_s": _number(options, "time_budget_s", 0.0, _MAX_BUDGET_S),
        "seed": _number(options, "seed", 0, 2**63 - 1, integer=True),
        "max_replications": _number(options, "max_replications", 1, _MAX_SIMULATIONS, integer=True),
        # Canonical already; parsing again validates it against this graph
        # (AnalysisError: the user's input, reported as such).
        "state": rbd_analysis.parse_current_state(graph, options.get("state")),
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
    options = _validated_options(request.get("options"), graph)
    return rbd_analysis.analyze_availability(graph, resolve_model=_no_saved_models, **options)


def sensitivity_request(graph: dict, **options) -> Optional[dict]:
    """A self-contained what-to-improve request ``{"graph", "options"}``
    (the options as :func:`rbd_sensitivity.options` validates them), or None
    when the graph needs saved models the compute service can't have."""
    if needs_saved_models(graph):
        return None
    return {"graph": inline_graph(graph), "options": rbd_sensitivity.options(**options)}


_SENSITIVITY_OPTIONS = frozenset({"window", "step", "rank_by", "order", "costs", "n_simulations", "seed"})


def run_sensitivity(request: dict) -> dict:
    """Run a self-contained what-to-improve request (#225): the levers ranked,
    simulated where there is no exact or numerical route (the web app queues
    that only for a user entitled to the simulation)."""
    if not isinstance(request, dict) or not isinstance(request.get("graph"), dict):
        raise InvalidRequest("The request needs a graph.")
    graph = request["graph"]
    if not graph.get("repairable"):
        raise InvalidRequest("Only repairable (availability) diagrams are computed here.")
    options = request.get("options") or {}
    if not isinstance(options, dict):
        raise InvalidRequest("options must be an object.")
    unknown = set(options) - _SENSITIVITY_OPTIONS
    if unknown:
        raise InvalidRequest(f"Unknown options: {', '.join(sorted(unknown))}.")
    # Validated again here (AnalysisError: the user's input, reported as such).
    checked = rbd_sensitivity.options(**options)
    return rbd_sensitivity.analyze_sensitivity(graph, resolve_model=_no_saved_models, simulate=True, **checked)


# What the compute service runs, by job kind. A new analysis adds its runner
# here; the web side adds a request builder above and a KIND_ in rbd_jobs.
# (#240's next failure rides in ``availability`` when a state is given.)
RUNNERS: dict[str, Callable[[dict], dict]] = {
    "availability": run_availability,
    "sensitivity": run_sensitivity,
}
KINDS = tuple(RUNNERS)


def to_wire(result: dict) -> dict:
    """A result as it crosses the wire: plain JSON types only (no numpy
    scalars), exactly what the callback carries and the job stores."""
    return json.loads(json.dumps(result, default=float))


def run(kind: str, request: dict) -> dict:
    """Run one compute request of ``kind`` and return its JSON-able result."""
    runner = RUNNERS.get(kind)
    if runner is None:
        raise InvalidRequest(f"Unknown kind {kind!r}.")
    return to_wire(runner(request))
