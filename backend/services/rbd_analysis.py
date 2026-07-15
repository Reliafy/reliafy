"""Reliability analysis of a saved RBD graph using RePyability.

The RBD builder (``frontend/src/views/RbdBuilder.jsx``) produces a React Flow
graph — a list of ``nodes`` and ``edges`` — where each component node carries a
SurPyval life model (a distribution id plus its parameters). This module turns
that graph into a :class:`repyability.rbd.non_repairable_rbd.NonRepairableRBD`
and computes:

* the system reliability ``R(t)`` and unreliability ``F(t)`` over a time grid,
* the reliability of each node over the same grid,
* the mean time to failure (MTTF),
* the Birnbaum and Fussell-Vesely importance of each node at a representative
  time, and
* the structural reduction (minimal path sets and minimal cut sets).

Every builder node maps to exactly one RBD node so that the per-node results
line up with the diagram. Series/parallel "count" blocks and hot standby are
reduced to a single equivalent reliability node (so a parallel block of ``n``
identical units is ``1 - (1 - R)^n``); cold standby uses RePyability's
``StandbyModel``; and a sub-system node is built recursively as a nested RBD.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

import numpy as np
import pandas as pd

from backend.fitting import DISTRIBUTIONS
from repyability.rbd.helper_classes import PerfectReliability, PerfectUnreliability
from repyability.rbd.non_repairable_rbd import NonRepairableRBD
from repyability.rbd.standby_node import StandbyModel
from repyability.utils.wrappers import conditional_survival

# Number of points on the reliability time grid.
_GRID_POINTS = 200
# Monte-Carlo samples used for the (simulation-based) MTTF.
_MTTF_SAMPLES = 5000


class AnalysisError(ValueError):
    """Raised when a graph can't be turned into an analysable RBD."""


class _DistName:
    """Minimal stand-in for a SurPyval ``model.dist`` so RePyability's
    fixed-probability check (``model.dist.name``) works on reduced blocks."""

    def __init__(self, name: str):
        self.name = name


class _ReducedModel:
    """An equivalent reliability for a series or parallel arrangement of
    independent models.

    * ``series``   — all units must survive: ``R = prod(R_i)``.
    * ``parallel`` — at least one must survive: ``R = 1 - prod(1 - R_i)``.

    Exposes the ``sf``/``ff``/``random``/``mean`` surface RePyability uses for
    analytic system probability and Monte-Carlo MTTF.
    """

    def __init__(self, models: list, kind: str):
        if not models:
            raise AnalysisError("A redundancy block needs at least one model.")
        self.models = list(models)
        self.kind = kind
        self.dist = _DistName(f"{kind.capitalize()}Block")

    def sf(self, x) -> np.ndarray:
        x = np.asarray(x, dtype=float)
        sfs = [np.asarray(m.sf(x), dtype=float) for m in self.models]
        if self.kind == "series":
            out = np.ones_like(sfs[0])
            for s in sfs:
                out = out * s
            return out
        out = np.ones_like(sfs[0])
        for s in sfs:
            out = out * (1.0 - s)
        return 1.0 - out

    def ff(self, x) -> np.ndarray:
        return 1.0 - self.sf(x)

    def cs(self, x, X) -> np.ndarray:
        return conditional_survival(self, x, X)

    def random(self, size) -> np.ndarray:
        draws = np.vstack(
            [np.asarray(m.random(size), dtype=float) for m in self.models]
        )
        # Series fails at the first unit failure; parallel at the last.
        return draws.min(axis=0) if self.kind == "series" else draws.max(axis=0)

    def mean(self, N: int = _MTTF_SAMPLES) -> float:
        return float(self.random(N).mean())


class _PHModel:
    """Reliability of a node backed by a fitted proportional-hazards (or other
    covariate/regression) model, evaluated at a fixed set of covariate values.

    ``Z`` is a one-row DataFrame of the model's raw covariates. The fitted
    SurPyval regression model exposes ``sf(x, Z)``, which is closed form given
    the covariates, so a PH node is still analytically solvable.
    """

    def __init__(self, model, Z, name: str, hi: Optional[float] = None):
        self.model = model
        self.Z = Z
        self.dist = _DistName(name or "Proportional hazards")
        self._hi = hi

    def sf(self, x) -> np.ndarray:
        x = np.atleast_1d(np.asarray(x, dtype=float))
        with np.errstate(all="ignore"):
            return np.asarray(self.model.sf(x, self.Z), dtype=float)

    def ff(self, x) -> np.ndarray:
        return 1.0 - self.sf(x)

    def cs(self, x, X) -> np.ndarray:
        return conditional_survival(self, x, X)


def _ph_reliability(model: dict, where: str, resolve_model, cov_values):
    """Build a :class:`_PHModel` for a node that references a saved regression
    model, evaluated at ``cov_values`` (falling back to the model's defaults)."""
    model_id = model.get("modelId") or model.get("model_id")
    if not model_id:
        raise AnalysisError(f"{where}: no proportional-hazards model selected.")
    if resolve_model is None:
        # Structural context (validation): the fitted model isn't needed and a
        # PH node is analytic, so stand in with a perfectly-reliable node.
        return PerfectReliability
    entry = resolve_model(model_id)
    if not entry:
        raise AnalysisError(
            f"{where}: saved model not found — re-fit it or pick another."
        )
    fitted = entry["model"]
    fields = entry.get("fields") or []
    row: dict = {}
    for field in fields:
        value = (cov_values or {}).get(field["name"], field.get("default"))
        if field.get("type") == "number":
            try:
                value = float(value)
            except (TypeError, ValueError):
                value = float(field.get("default") or 0.0)
        else:
            value = str(value)
        row[field["name"]] = [value]
    Z = pd.DataFrame(row) if row else None
    grid = entry.get("grid")
    hi = float(grid[-1]) if grid is not None and len(grid) else None
    name = model.get("distribution") or "Proportional hazards"
    try:
        return _PHModel(fitted, Z, name, hi)
    except Exception as exc:
        raise AnalysisError(f"{where}: {exc}") from exc


def _nonparametric_reliability(model: dict, where: str, resolve_model):
    """Return the re-fitted empirical estimator for a non-parametric node.
    It exposes sf/ff, which is all series/parallel/k-of-n structures need."""
    model_id = model.get("modelId") or model.get("model_id")
    if not model_id:
        raise AnalysisError(f"{where}: no model selected.")
    if resolve_model is None:
        return PerfectReliability  # structural validation doesn't need the fit
    entry = resolve_model(model_id)
    if not entry or entry.get("model") is None:
        raise AnalysisError(f"{where}: saved model not found — re-fit it or pick another.")
    return entry["model"]


def _build_distribution(
    model: Optional[dict],
    where: str,
    resolve_model=None,
    cov_values: Optional[dict] = None,
):
    """Build a frozen SurPyval distribution from a node's life model.

    ``model`` is the object the picker stores on a node: ``distribution_id`` and
    an ordered list of ``{name, value}`` params. Parameters are reordered to the
    distribution's own ``param_names`` so the positional ``from_params`` call is
    correct regardless of the order they arrive in.
    """
    if not model:
        raise AnalysisError(f"{where} has no life model — set one to analyse.")
    # A node can reference a saved proportional-hazards / regression model,
    # whose reliability depends on covariate values supplied at calc time.
    if model.get("kind") == "regression":
        return _ph_reliability(model, where, resolve_model, cov_values)
    # Non-parametric models (KM/NA/Turnbull) have no parameters — resolve the
    # re-fitted empirical estimator (sf/ff) via the same refit-on-demand path.
    if model.get("kind") == "nonparametric":
        return _nonparametric_reliability(model, where, resolve_model)
    dist_id = model.get("distribution_id")
    entry = DISTRIBUTIONS.get(dist_id)
    if entry is None:
        raise AnalysisError(
            f"{where} uses an unsupported distribution "
            f"'{model.get('distribution') or dist_id}'."
        )
    dist = entry["dist"]
    params = model.get("params") or []
    by_name = {p["name"]: float(p["value"]) for p in params if "name" in p}
    names = list(getattr(dist, "param_names", []) or [])
    if names and all(n in by_name for n in names):
        values = [by_name[n] for n in names]
    else:
        # Fall back to the order they were given in.
        values = [float(p["value"]) for p in params]
    if not values:
        raise AnalysisError(f"{where} is missing distribution parameters.")
    # Extra fitted quantities (offset gamma, LFP p, ZI f0) rebuild the model
    # exactly as fitted; sf/ff are well-defined for all of them.
    extras = {
        k: float(v)
        for k, v in (model.get("extras") or {}).items()
        if k in ("gamma", "p", "f0") and v is not None
    }
    try:
        return dist.from_params(values, **extras)
    except Exception as exc:  # surpyval validates the parameters
        raise AnalysisError(f"{where}: {exc}") from exc


def _standby_model(data: dict, label: str, resolve_model=None, cov_values=None):
    """Build the reliability of a standby node from its builder data."""
    primary = _build_distribution(data.get("model"), label, resolve_model, cov_values)
    spares = int(data.get("spares") or 1)
    spare_src = data.get("standbyModel") or data.get("model")
    spare = _build_distribution(
        spare_src, f"{label} (spare)", resolve_model, cov_values
    )
    units = [primary] + [spare for _ in range(max(spares, 0))]

    if data.get("cold"):
        # Cold standby: spares are dormant until switched in (k=1 operating).
        try:
            switch = float(data.get("startProb", 1.0))
        except (TypeError, ValueError):
            switch = 1.0
        return StandbyModel(units, k=1, switching_probability=switch)
    # Hot standby: every unit runs from t=0 -> active parallel redundancy.
    return _ReducedModel(units, "parallel")


def _node_reliability(
    node: dict,
    resolve_subsystem: Optional[Callable[[str], dict]],
    visited: set,
    resolve_model=None,
    covariates: Optional[dict] = None,
):
    """Return ``(reliability, k_required)`` for a single builder node.

    ``k_required`` is the k-out-of-n value for a voting node (else ``None``).
    ``covariates`` maps node id -> covariate values for nodes backed by a
    proportional-hazards model.
    """
    ntype = node.get("type")
    data = node.get("data") or {}
    label = data.get("label") or node.get("id")
    cov_values = (covariates or {}).get(node.get("id"))

    # Manual what-if override: a node pinned "working" / "failed" ignores its
    # life model and contributes as perfectly reliable / perfectly unreliable.
    state = data.get("state")
    if state == "working":
        return PerfectReliability, None
    if state == "failed":
        return PerfectUnreliability, None

    if ntype == "component":
        model = _build_distribution(data.get("model"), label, resolve_model, cov_values)
        return model, None

    if ntype == "knode":
        # A pure voting gate: perfectly reliable itself, requiring `n` of the
        # branches feeding into it. RePyability's k applies to a node's
        # predecessors, which is exactly the voting branches in a left-to-right
        # diagram.
        n = int(data.get("n") or 1)
        return PerfectReliability, max(n, 1)

    if ntype in ("series", "parallel"):
        base = _build_distribution(data.get("model"), label, resolve_model, cov_values)
        count = int(data.get("n") or 1)
        return _ReducedModel([base] * max(count, 1), ntype), None

    if ntype == "standby":
        return _standby_model(data, label, resolve_model, cov_values), None

    if ntype == "subsystem":
        ref = data.get("rbd")
        if not ref or not ref.get("id"):
            raise AnalysisError(f"{label}: no sub-system RBD selected.")
        if resolve_subsystem is None:
            raise AnalysisError(
                f"{label}: sub-systems can't be resolved in this context."
            )
        sub_id = ref["id"]
        if sub_id in visited:
            raise AnalysisError(
                f"{label}: sub-system '{ref.get('name', sub_id)}' refers to "
                "itself (cycle)."
            )
        sub_graph = resolve_subsystem(sub_id)
        if sub_graph is None:
            raise AnalysisError(
                f"{label}: sub-system '{ref.get('name', sub_id)}' was not found."
            )
        rbd, *_ = _build_rbd(
            sub_graph,
            resolve_subsystem,
            visited | {sub_id},
            resolve_model,
            covariates,
        )
        return rbd, None

    raise AnalysisError(f"{label}: unsupported node type '{ntype}'.")


def _build_rbd(
    graph: dict,
    resolve_subsystem: Optional[Callable[[str], dict]] = None,
    visited: Optional[set] = None,
    resolve_model=None,
    covariates: Optional[dict] = None,
):
    """Translate a builder graph into a NonRepairableRBD.

    Returns ``(rbd, labels, node_types, reliabilities)`` where ``labels`` and
    ``node_types`` map node id -> display label / builder type for the nodes
    that participate in the RBD (i.e. everything but input/output).
    """
    visited = visited or set()
    nodes = graph.get("nodes") or []
    raw_edges = graph.get("edges") or []
    edges = [
        (e["source"], e["target"])
        for e in raw_edges
        if e.get("source") and e.get("target")
    ]
    if not edges:
        raise AnalysisError("The diagram has no connections to analyse.")

    node_ids = {n.get("id") for n in nodes}
    reliabilities: dict[Any, Any] = {}
    k: dict[Any, int] = {}
    labels: dict[Any, str] = {}
    node_types: dict[Any, str] = {}

    for node in nodes:
        nid = node.get("id")
        ntype = node.get("type")
        if ntype in ("input", "output"):
            continue
        data = node.get("data") or {}
        labels[nid] = data.get("label") or nid
        node_types[nid] = ntype
        reliability, k_required = _node_reliability(
            node, resolve_subsystem, visited, resolve_model, covariates
        )
        reliabilities[nid] = reliability
        if k_required is not None:
            k[nid] = k_required

    if not reliabilities:
        raise AnalysisError("The diagram has no component nodes to analyse.")

    input_node = "input" if "input" in node_ids else None
    output_node = "output" if "output" in node_ids else None

    try:
        rbd = NonRepairableRBD(
            edges,
            reliabilities,
            k=k,
            input_node=input_node,
            output_node=output_node,
            on_infeasible_rbd="raise",
        )
    except ValueError as exc:
        raise AnalysisError(
            "The diagram isn't a valid reliability block diagram: "
            f"{exc}. Check that every component is wired between the input "
            "and output."
        ) from exc

    return rbd, labels, node_types, reliabilities


def _structure_errors(sc: dict, labels: dict) -> tuple[list[str], list[str]]:
    """Turn a RePyability ``structure_check`` into user-facing messages.

    Returns ``(errors, warnings)`` — errors block analysis, warnings don't.
    """
    errors: list[str] = []
    warnings: list[str] = []

    def names(key: str) -> str:
        return ", ".join(labels.get(n, str(n)) for n in (sc.get(key) or []))

    if sc.get("has_cycles"):
        errors.append(
            "The diagram contains a loop. A reliability block diagram must "
            "flow from the input to the output without cycles."
        )
    dangling_in = sc.get("nodes_with_no_predecessors") or []
    if dangling_in:
        errors.append(
            "Nothing feeds into: "
            f"{names('nodes_with_no_predecessors')}. Connect them from the "
            "input side."
        )
    elif not sc.get("has_unique_input_node", True):
        errors.append("The diagram needs exactly one input node.")
    dangling_out = sc.get("nodes_with_no_successors") or []
    if dangling_out:
        errors.append(
            "These nodes don't lead anywhere: "
            f"{names('nodes_with_no_successors')}. Connect them to the output "
            "side."
        )
    elif not sc.get("has_unique_output_node", True):
        errors.append("The diagram needs exactly one output node.")

    if sc.get("is_missing_distributions"):
        errors.append(
            "These nodes have no life model: "
            f"{names('nodes_with_no_reliability_distribution')}."
        )
    for message in sc.get("koon_errors") or []:
        errors.append(str(message))
    for message in sc.get("koon_warnings") or []:
        warnings.append(str(message))
    if sc.get("has_irrelevant_nodes"):
        warnings.append(
            "These nodes are not on any path and don't affect the result: "
            f"{names('irrelevant_nodes')}."
        )
    return errors, warnings


def validate_graph(
    graph: dict,
    resolve_subsystem: Optional[Callable[[str], dict]] = None,
) -> dict:
    """Check whether a builder graph is a valid, analytically solvable RBD.

    Never raises for an *expected* problem (a malformed diagram); instead it
    reports the problems so the UI can explain them and decide whether to allow
    a calculation. The shape is::

        {
          "valid": bool,            # structurally a valid RBD
          "analytic": bool,         # solvable in closed form (no simulation)
          "can_calculate": bool,    # valid and analytic
          "errors": [str, ...],     # blocking problems
          "warnings": [str, ...],   # non-blocking notes
          "non_analytic_nodes": {label: model_type, ...},
        }
    """
    errors: list[str] = []
    warnings: list[str] = []
    non_analytic: dict[str, str] = {}

    nodes = graph.get("nodes") or []
    raw_edges = graph.get("edges") or []
    edges = [
        (e["source"], e["target"])
        for e in raw_edges
        if e.get("source") and e.get("target")
    ]
    component_nodes = [
        n for n in nodes if n.get("type") not in ("input", "output", None)
    ]
    if not component_nodes:
        errors.append("Add at least one component to the diagram.")
    if not edges:
        errors.append(
            "The diagram has no connections. Wire the components between the "
            "input and output."
        )

    # Build each node's reliability, collecting per-node problems (a missing
    # life model, bad parameters, an unresolved sub-system). Failed nodes get a
    # placeholder so the structural checks below can still run.
    reliabilities: dict[Any, Any] = {}
    k: dict[Any, int] = {}
    labels: dict[Any, str] = {}
    visited: set = set()
    for node in nodes:
        ntype = node.get("type")
        if ntype in ("input", "output"):
            continue
        nid = node.get("id")
        labels[nid] = (node.get("data") or {}).get("label") or nid
        try:
            reliability, k_required = _node_reliability(
                node, resolve_subsystem, visited
            )
            reliabilities[nid] = reliability
            if k_required is not None:
                k[nid] = k_required
        except AnalysisError as exc:
            errors.append(str(exc))
            reliabilities[nid] = PerfectReliability  # structural placeholder

    if edges and reliabilities:
        node_ids = {n.get("id") for n in nodes}
        try:
            rbd = NonRepairableRBD(
                edges,
                reliabilities,
                k=k,
                input_node="input" if "input" in node_ids else None,
                output_node="output" if "output" in node_ids else None,
                on_infeasible_rbd="ignore",
            )
            struct_errors, struct_warnings = _structure_errors(
                rbd.structure_check, labels
            )
            errors.extend(struct_errors)
            warnings.extend(struct_warnings)
            try:
                non_analytic = {
                    labels.get(n, str(n)): t
                    for n, t in rbd.get_non_analytic_nodes().items()
                }
            except Exception:
                non_analytic = {}
        except ValueError as exc:
            # e.g. a k-out-of-n setting that leaves no path through the system.
            errors.append(f"The diagram can't be solved as drawn: {exc}")
        except Exception as exc:  # pragma: no cover - defensive
            errors.append(f"The diagram could not be analysed: {exc}")

    valid = len(errors) == 0
    analytic = valid and len(non_analytic) == 0
    return {
        "valid": valid,
        "analytic": analytic,
        "can_calculate": valid and analytic,
        "errors": errors,
        "warnings": warnings,
        "non_analytic_nodes": non_analytic,
    }


def _model_hi(model) -> Optional[float]:
    """A sensible upper time bound for a single node's reliability."""
    hi = getattr(model, "_hi", None)
    if hi:
        return float(hi)
    qf = getattr(model, "qf", None)
    if callable(qf):
        try:
            v = float(np.asarray(qf(0.99)).item())
            if np.isfinite(v) and v > 0:
                return v
        except Exception:
            pass
    mean = getattr(model, "mean", None)
    if callable(mean):
        try:
            v = float(mean())
            if np.isfinite(v) and v > 0:
                return v * 3.0
        except Exception:
            pass
    return None


def _time_grid(reliabilities: dict, t_max: Optional[float] = None) -> np.ndarray:
    """Time grid from 0 to ``t_max``. When ``t_max`` isn't given (or isn't
    positive) it is auto-derived from the nodes' own time scales."""
    if t_max is not None and np.isfinite(t_max) and t_max > 0:
        hi = float(t_max)
    else:
        his = [hi for m in reliabilities.values() if (hi := _model_hi(m))]
        hi = max(his) if his else 1.0
    return np.linspace(0.0, hi, _GRID_POINTS)


def _conditional_sf(model, times, s: float = 0.0) -> np.ndarray:
    """Survival of a model over ``times``, conditioned on having survived to
    ``s`` when ``s > 0``.

    Both the RBD (``rbd.cs``) and every node reliability — SurPyval
    distributions, the redundancy/PH adapters, standby nodes and nested RBDs —
    expose ``cs(x, X)``, so the conditional survival ``R(t | s)`` is delegated
    to that method across the board. With ``s == 0`` this is just ``R(t)``.
    """
    times = np.atleast_1d(np.asarray(times, dtype=float))
    if not s or s <= 0:
        return np.asarray(model.sf(times), dtype=float)
    out = np.asarray(model.cs(times, float(s)), dtype=float)
    out = np.where(np.isfinite(out), out, 0.0)
    return np.clip(out, 0.0, 1.0)


def _mttf(rbd, base_hi: float, s: float = 0.0) -> Optional[float]:
    """Mean time to failure as ``integral_0^inf R(t) dt``, or — when ``s > 0`` —
    the mean residual life ``integral_0^inf R(t | s) dt`` at age ``s``.

    Integrated numerically over a grid extended until the (conditional) system
    reliability has decayed (or a cap is hit). Exact for analytically solvable
    RBDs and avoids RePyability's Monte-Carlo path.
    """
    if base_hi <= 0:
        return None
    t_max = base_hi
    for _ in range(8):  # extend up to 2^8 = 256x the base horizon
        if _conditional_sf(rbd, np.array([t_max]), s)[0] < 1e-4:
            break
        t_max *= 2.0
    grid = np.linspace(0.0, t_max, 4000)
    sf = _conditional_sf(rbd, grid, s)
    if not np.all(np.isfinite(sf)):
        return None
    # np.trapz was renamed to np.trapezoid in NumPy 2.0.
    trapezoid = getattr(np, "trapezoid", None) or np.trapz
    value = float(trapezoid(sf, grid))
    return value if np.isfinite(value) and value > 0 else None


def _clean(arr) -> list:
    """Coerce an array to a JSON-safe list (inf/nan -> null)."""
    out = []
    for v in np.atleast_1d(np.asarray(arr, dtype=float)):
        out.append(float(v) if np.isfinite(v) else None)
    return out


def analyze(
    graph: dict,
    resolve_subsystem: Optional[Callable[[str], dict]] = None,
    t_max: Optional[float] = None,
    covariates: Optional[dict] = None,
    resolve_model=None,
    conditional_age: Optional[float] = None,
) -> dict:
    """Analyse a builder graph and return a JSON-serialisable result payload.

    ``t_max`` sets the upper limit of the time axis the curves are computed
    over; when omitted it is derived from the nodes' own time scales.
    ``covariates`` maps node id -> covariate values for nodes backed by a
    proportional-hazards model, and ``resolve_model`` loads a saved fitted
    model by id. ``conditional_age`` (``s``) conditions every curve on having
    already survived to ``s``: the time axis becomes additional time ``t`` and
    each reliability is ``R(s + t) / R(s)``; the MTTF becomes the mean residual
    life at ``s``. Raises :class:`AnalysisError` with a user-facing message if
    the graph can't be turned into a valid RBD.
    """
    rbd, labels, node_types, reliabilities = _build_rbd(
        graph, resolve_subsystem, None, resolve_model, covariates
    )

    s = float(conditional_age) if conditional_age and conditional_age > 0 else 0.0
    grid = _time_grid(reliabilities, t_max)
    system_sf = _conditional_sf(rbd, grid, s)

    # Per-node reliability over the same grid (skip pure voting gates, which
    # are perfectly reliable and not informative to plot).
    node_payloads = []
    for nid in rbd.nodes:
        if node_types.get(nid) == "knode":
            continue
        model = reliabilities[nid]
        node_payloads.append(
            {
                "id": nid,
                "label": labels.get(nid, nid),
                "type": node_types.get(nid),
                "sf": _clean(_conditional_sf(model, grid, s)),
            }
        )

    # Importances at a representative time: where the system reliability is
    # closest to 0.9 (a typical design-life point), else the grid midpoint.
    target_idx = int(np.argmin(np.abs(system_sf - 0.9)))
    if not (0.0 < system_sf[target_idx] < 1.0):
        target_idx = len(grid) // 2
    t_rep = float(grid[target_idx])

    importance: dict[str, dict] = {}
    try:
        # Evaluate importances at the (conditional) node reliabilities so they
        # are consistent with the displayed curves.
        node_probs = {
            n: _conditional_sf(reliabilities[n], np.array([t_rep]), s)
            for n in rbd.nodes
        }
        birnbaum = rbd._birnbaum_importance(node_probs)
        fv = rbd._fussel_vesely(node_probs, fv_type="c")
        importance = {
            "time": t_rep,
            "birnbaum": {
                str(n): float(np.atleast_1d(v)[0])
                for n, v in birnbaum.items()
                if node_types.get(n) != "knode"
            },
            "fussell_vesely": {
                str(n): float(np.atleast_1d(v)[0])
                for n, v in fv.items()
                if node_types.get(n) != "knode"
            },
        }
    except Exception:
        importance = {}

    # Mean time to failure (or mean residual life at s), integrated from the
    # system reliability curve.
    try:
        mttf = _mttf(rbd, float(grid[-1]), s)
    except Exception:
        mttf = None

    def _named_sets(sets) -> list:
        return sorted(
            (sorted(labels.get(n, str(n)) for n in s_) for s_ in sets),
            key=len,
        )

    structure = {
        "min_path_sets": _named_sets(rbd.get_min_path_sets(include_in_out_nodes=False)),
        "min_cut_sets": _named_sets(rbd.get_min_cut_sets(include_in_out_nodes=False)),
    }

    return {
        "unit": (graph.get("unit") or "").strip(),
        "time": grid.tolist(),
        "system": {"sf": _clean(system_sf), "ff": _clean(1.0 - system_sf)},
        "mttf": mttf,
        "conditional_age": s,
        "nodes": node_payloads,
        "importance": importance,
        "structure": structure,
        "repyability_version": _repyability_version(),
    }


def _repyability_version() -> Optional[str]:
    try:
        import repyability

        version = getattr(repyability, "__version__", None)
        if version:
            return version
    except Exception:
        pass
    try:
        from importlib.metadata import version

        return version("repyability")
    except Exception:
        return None
