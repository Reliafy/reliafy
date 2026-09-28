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

import time
import warnings
from itertools import combinations
from math import comb
from typing import Any, Callable, Optional

import numpy as np
import pandas as pd

from backend.fitting import DISTRIBUTIONS
from backend.services import rbd_repeats
from repyability.rbd.helper_classes import PerfectReliability
from repyability.rbd.non_repairable_rbd import NonRepairableRBD
from repyability.rbd.repairable_rbd import RepairableRBD
from repyability.rbd.ccf import CCFGroup
from repyability import BetaFactor, LoadSharingModel
from repyability.non_repairable import NonRepairable
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


_LOADSHARE_SIMS = 2000  # MC replicates for the load-sharing group's KM fit


def _loadshare_model(data: dict, label: str, resolve_model=None):
    """Build a load-sharing group's reliability. The units share a total load L;
    each of ``s`` survivors carries ``L / s``, so survivors fail faster. The unit
    is a saved accelerated-failure-time (AFT) model with the load as its single
    covariate (``phi(load)``). ``units`` identical units, ``k`` required."""
    model = data.get("model") or {}
    model_id = model.get("modelId") or model.get("model_id")
    if not model_id:
        raise AnalysisError(f"{label}: pick the load-life (AFT) model for the units.")
    if resolve_model is None:
        # Structural/validation context: a load-sharing node is analytic; stand
        # in with a perfectly-reliable node (the real fit isn't needed here).
        return PerfectReliability
    entry = resolve_model(model_id)
    if not entry:
        raise AnalysisError(f"{label}: saved load-life model not found — re-fit it or pick another.")
    fitted = entry["model"]
    fields = entry.get("fields") or []
    if len(fields) != 1:
        raise AnalysisError(
            f"{label}: the load-life model must be an AFT model with exactly one "
            "covariate — the load. Fit an accelerated-failure-time model (e.g. "
            "weibull_aft) with a single load column.")
    try:
        n = max(int(data.get("units") or 2), 2)
        k = max(int(data.get("k") or 1), 1)
        load = float(data.get("load"))
    except (TypeError, ValueError):
        raise AnalysisError(f"{label}: set the total load, the number of units, and k.")
    if load <= 0:
        raise AnalysisError(f"{label}: the total load must be a positive number.")
    if k > n:
        raise AnalysisError(f"{label}: k ({k}) can't exceed the number of units ({n}).")
    try:
        return LoadSharingModel([fitted] * n, load=load, k=k, n_sims=_LOADSHARE_SIMS, seed=1)
    except Exception as exc:  # RePyability validates the AFT unit
        raise AnalysisError(
            f"{label}: {exc} — load-sharing needs an accelerated-failure-time (AFT) "
            "life model with the load as its covariate.") from exc


def _standby_model(data: dict, label: str, resolve_model=None, cov_values=None):
    """Build the reliability of a standby node from its builder data."""
    primary = _build_distribution(data.get("model"), label, resolve_model, cov_values)
    spares = int(data.get("spares") or 1)
    spare_src = data.get("standbyModel") or data.get("model")
    spare = _build_distribution(
        spare_src, f"{label} (spare)", resolve_model, cov_values
    )
    units = [primary] + [spare for _ in range(max(spares, 0))]

    dormancy = _standby_dormancy(data, label)
    if dormancy == 0.0:
        # Cold standby: spares are dormant until switched in (k=1 operating).
        try:
            switch = float(data.get("startProb", 1.0))
        except (TypeError, ValueError):
            switch = 1.0
        return StandbyModel(units, k=1, switching_probability=switch)
    if dormancy < 1.0:
        # Warm standby: an idle spare ages at `dormancy` × its operating rate
        # (cumulative exposure) and can fail latent, dead before it's needed.
        # Exact for identical exponential units, simulated otherwise.
        return StandbyModel(units, k=1, dormancy_factor=dormancy)
    # Hot standby: every unit runs from t=0 -> active parallel redundancy.
    return _ReducedModel(units, "parallel")


def _standby_dormancy(data: dict, label: str) -> float:
    """A standby node's dormancy factor: 0 cold, 1 hot, in between warm.

    ``dormancy`` wins when set; older diagrams carry only ``cold`` (true =
    cold, otherwise hot)."""
    raw = data.get("dormancy")
    if raw is None or raw == "":
        return 0.0 if data.get("cold") else 1.0
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise AnalysisError(f"{label}: the dormancy factor must be a number from 0 (cold) to 1 (hot).") from None
    if not 0.0 <= value <= 1.0:
        raise AnalysisError(f"{label}: the dormancy factor must be between 0 (cold) and 1 (hot).")
    return value


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

    if ntype == "loadshare":
        return _loadshare_model(data, label, resolve_model), None

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

    Returns ``(rbd, labels, node_types, reliabilities, working_nodes,
    broken_nodes)`` where ``labels`` and ``node_types`` map node id -> display
    label / builder type for the participating nodes (everything but
    input/output), and the last two are the ids pinned working/failed.
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
    # Manual what-if overrides: nodes pinned working/failed keep their real
    # life model in the RBD but are forced perfectly reliable/unreliable via
    # RePyability's native ``working_nodes``/``broken_nodes`` arguments.
    working_nodes: set = set()
    broken_nodes: set = set()
    # Repeated blocks (#102): a linked copy is passed to RePyability as the
    # name of the node it repeats, so every appearance is one component.
    repeats, problems = rbd_repeats.find_repeats(nodes)
    if problems:
        raise AnalysisError(next(iter(problems.values())))

    for node in nodes:
        nid = node.get("id")
        ntype = node.get("type")
        if ntype in ("input", "output"):
            continue
        data = node.get("data") or {}
        labels[nid] = data.get("label") or nid
        node_types[nid] = ntype
        if nid in repeats:
            # The original's model and pinned state apply to every appearance.
            reliabilities[nid] = repeats[nid]
            continue
        state = data.get("state")
        pinned = state in ("working", "failed")
        if state == "working":
            working_nodes.add(nid)
        elif state == "failed":
            broken_nodes.add(nid)
        try:
            reliability, k_required = _node_reliability(
                node, resolve_subsystem, visited, resolve_model, covariates
            )
        except AnalysisError:
            # A pinned node is overridden anyway, so it needs no life model of
            # its own — stand in with a placeholder (never actually evaluated).
            if not pinned:
                raise
            reliability, k_required = PerfectReliability, None
        reliabilities[nid] = reliability
        if k_required is not None:
            k[nid] = k_required

    if not reliabilities:
        raise AnalysisError("The diagram has no component nodes to analyse.")
    labels.update(rbd_repeats.copy_labels(nodes, repeats))

    input_node = "input" if "input" in node_ids else None
    output_node = "output" if "output" in node_ids else None

    ccf_groups = _ccf_groups(graph, reliabilities)
    if repeats and not rbd_repeats.core_search_fits(
            edges, reliabilities, repeats, k, input_node, output_node):
        raise AnalysisError(rbd_repeats.CORE_MESSAGE)

    def _make(with_ccf: bool):
        try:
            return NonRepairableRBD(
                edges,
                reliabilities,
                k=k,
                input_node=input_node,
                output_node=output_node,
                on_infeasible_rbd="raise",
                ccf_groups=ccf_groups if (with_ccf and ccf_groups) else None,
            )
        except ValueError as exc:
            raise AnalysisError(
                "The diagram isn't a valid reliability block diagram: "
                f"{exc}. Check that every component is wired between the input "
                "and output."
            ) from exc

    rbd = _make(with_ccf=True)
    # Keep a common-cause-free twin so the analysis can show the CCF impact.
    baseline = _make(with_ccf=False) if ccf_groups else None
    return rbd, labels, node_types, reliabilities, working_nodes, broken_nodes, baseline


def _ccf_groups(graph: dict, reliabilities: dict) -> list:
    """Build RePyability CCFGroups from ``graph['ccf_groups']`` — each a set of
    ≥2 redundant components coupled by a beta-factor shared cause. Groups whose
    members aren't all present (or fewer than two) are skipped."""
    out = []
    for g in graph.get("ccf_groups") or []:
        # A repeated block (its model is the name of its original) is no member.
        members = [m for m in (g.get("members") or []) if m in reliabilities
                   and not isinstance(reliabilities[m], str)]
        if len(set(members)) < 2:
            continue
        try:
            beta = float(g.get("beta"))
        except (TypeError, ValueError):
            continue
        if not (0.0 < beta < 1.0):
            continue
        out.append(CCFGroup(members=list(dict.fromkeys(members)), model=BetaFactor(beta)))
    return out


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
          "can_calculate": bool,    # valid (non-analytic nodes are simulated)
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
    repeats, problems = rbd_repeats.find_repeats(nodes)
    errors.extend(problems.values())
    for node in nodes:
        ntype = node.get("type")
        if ntype in ("input", "output"):
            continue
        nid = node.get("id")
        labels[nid] = (node.get("data") or {}).get("label") or nid
        if nid in repeats:
            reliabilities[nid] = repeats[nid]  # a linked copy: no model of its own
            continue
        if rbd_repeats.repeat_of(node) is not None:
            reliabilities[nid] = PerfectReliability  # a broken copy (reported above)
            continue
        # A node pinned working/failed is overridden in analysis, so it needs
        # no life model — don't flag one as missing here.
        pinned = (node.get("data") or {}).get("state") in ("working", "failed")
        try:
            reliability, k_required = _node_reliability(
                node, resolve_subsystem, visited
            )
            reliabilities[nid] = reliability
            if k_required is not None:
                k[nid] = k_required
        except AnalysisError as exc:
            if not pinned:
                errors.append(str(exc))
            reliabilities[nid] = PerfectReliability  # structural placeholder

    labels.update(rbd_repeats.copy_labels(nodes, repeats))
    node_ids = {n.get("id") for n in nodes}
    too_tied = bool(edges and reliabilities and repeats) and not rbd_repeats.core_search_fits(
        edges, reliabilities, repeats, k,
        "input" if "input" in node_ids else None, "output" if "output" in node_ids else None)
    if too_tied:
        errors.append(rbd_repeats.CORE_MESSAGE)
    if edges and reliabilities and not too_tied:
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

    repairable = bool(graph.get("repairable"))
    if repairable:
        # Availability mode is a distinct contract: every component needs a
        # repair-time distribution, only component + k-of-n blocks are supported,
        # and common-cause coupling is reliability-only. Check that here so the
        # Validate step reflects what Calculate will actually accept.
        if repeats:
            errors.append(rbd_repeats.repairable_message(nodes, repeats))
        for node in nodes:
            ntype = node.get("type")
            if ntype in ("input", "output") or node.get("id") in repeats:
                continue
            lbl = labels.get(node.get("id"), node.get("id"))
            data = node.get("data") or {}
            if ntype == "knode":
                continue
            if ntype != "component":
                errors.append(
                    f"“{lbl}” isn't supported in a repairable diagram — availability "
                    "uses component blocks (each with a life model and a repair time) "
                    "and k-of-n gates. Switch to a non-repairable diagram to use it.")
            elif data.get("state") not in ("working", "failed") and not data.get("repair"):
                errors.append(
                    f"“{lbl}” has no repair-time distribution. Repairable diagrams "
                    "analyse availability, so every component needs one (double-click "
                    "the block to set it).")
        if graph.get("ccf_groups"):
            warnings.append(
                "Common-cause groups are a reliability-only feature and are "
                "ignored in a repairable (availability) diagram.")
        valid = len(errors) == 0
        # Availability is always estimated by simulation — never "analytic".
        return {
            "valid": valid, "analytic": False, "can_calculate": valid,
            "errors": errors, "warnings": warnings, "non_analytic_nodes": {},
        }

    # Non-repairable (reliability): common-cause groups should couple identical
    # (symmetric) components — warn if the members' life models differ.
    for msg in _ccf_symmetry_warnings(graph, labels):
        warnings.append(msg)

    valid = len(errors) == 0
    analytic = valid and len(non_analytic) == 0
    # Standby and load-sharing nodes have no closed form, but ``analyze`` solves
    # them by simulation (StandbyModel / LoadSharingModel), so a valid diagram
    # is always calculable — ``analytic`` only tells the UI how to label it.
    return {
        "valid": valid,
        "analytic": analytic,
        "can_calculate": valid,
        "errors": errors,
        "warnings": warnings,
        "non_analytic_nodes": non_analytic,
    }


def _ccf_symmetry_warnings(graph: dict, labels: dict) -> list:
    """Beta-factor common cause assumes symmetric groups (identical member
    models). Warn when a group's members carry different life models."""
    out = []
    by_id = {n.get("id"): (n.get("data") or {}) for n in (graph.get("nodes") or [])}

    def _model_key(nid):
        m = (by_id.get(nid) or {}).get("model") or {}
        # Compare the distribution + parameter values (a saved model by its id).
        if m.get("modelId"):
            return ("saved", m.get("modelId"))
        params = tuple(sorted((p.get("name"), round(float(p.get("value")), 6))
                              for p in (m.get("params") or []) if p.get("name") is not None))
        return (m.get("distribution_id"), params)

    for g in graph.get("ccf_groups") or []:
        members = [m for m in (g.get("members") or []) if m in by_id]
        if len(members) < 2:
            continue
        keys = {_model_key(m) for m in members}
        if len(keys) > 1:
            names = ", ".join(labels.get(m, str(m)) for m in members)
            out.append(
                f"Common-cause group ({names}) mixes different life models. The "
                "beta-factor model assumes identical redundant components, so give "
                "them the same model for a meaningful result.")
    return out


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


def _system_horizon(rbd, ceiling: float, s: float = 0.0, **sf_kwargs) -> float:
    """An axis end sized to the *system*, not its longest-lived component.

    ``_time_grid`` bounds the axis by the nodes' own time scales, so one very
    reliable block (e.g. a pressure vessel at 1e-6/h) stretches it to millions
    of hours while the system is long dead — the curve becomes a cliff at the
    left edge and importances are read where everything has failed. Search a
    log-spaced grid up to that ceiling for where system reliability first falls
    to 1%, and end the axis a little beyond it. Falls back to the ceiling when
    the system never gets that low within it, or starts already failed.
    """
    if not (ceiling and np.isfinite(ceiling) and ceiling > 0):
        return ceiling
    probe = np.geomspace(ceiling * 1e-6, ceiling, 400)
    try:
        sf = _conditional_sf(rbd, probe, s, **sf_kwargs)
    except Exception:  # pragma: no cover - fall back to the component bound
        return ceiling
    if not np.all(np.isfinite(sf)) or sf[0] < 0.01:
        return ceiling
    below = np.nonzero(sf <= 0.01)[0]
    if below.size == 0:
        return ceiling
    return float(min(ceiling, probe[below[0]] * 1.15))


def _conditional_sf(model, times, s: float = 0.0, **sf_kwargs) -> np.ndarray:
    """Survival of a model over ``times``, conditioned on having survived to
    ``s`` when ``s > 0``.

    Both the RBD (``rbd.cs``) and every node reliability — SurPyval
    distributions, the redundancy/PH adapters, standby nodes and nested RBDs —
    expose ``cs(x, X)``, so the conditional survival ``R(t | s)`` is delegated
    to that method across the board. With ``s == 0`` this is just ``R(t)``.
    ``sf_kwargs`` (e.g. ``working_nodes``/``broken_nodes``) are forwarded to the
    RBD's ``sf``/``cs`` — pass none for a plain node model.
    """
    times = np.atleast_1d(np.asarray(times, dtype=float))
    if not s or s <= 0:
        return np.asarray(model.sf(times, **sf_kwargs), dtype=float)
    out = np.asarray(model.cs(times, float(s), **sf_kwargs), dtype=float)
    out = np.where(np.isfinite(out), out, 0.0)
    return np.clip(out, 0.0, 1.0)


# ---------------------------------------------------------------------------
# Path and cut sets on large diagrams
# ---------------------------------------------------------------------------
# RePyability (0.9+) evaluates any diagram exactly and fast: series–parallel
# parts reduce to closed-form modules, so even 10^9 path sets cost
# milliseconds. What can still explode is *listing* the sets: path sets
# multiply with redundancy in series (30 duplicated stages have 2^30), cut sets
# with long chains in parallel (4 chains of 40 blocks have 40^4). They're
# counted exactly first, from the same decomposition, and enumerated only when
# that's sensible; otherwise the lowest-order cut sets are found directly —
# they're what an engineer reads cut sets for, and they dominate the
# Fussell–Vesely importance, which is a sum over cut sets.
_MAX_ENUMERATED_SETS = 20_000
_LISTED_SETS = 200  # shown in the result, smallest first; the count is always given
_LOW_ORDER_CUT_MAX = 3
_LOW_ORDER_CANDIDATES_MAX = 250_000


def _set_counts(rbd) -> tuple[Optional[int], Optional[int]]:
    """``(minimal path sets, minimal cut sets)`` counted from RePyability's
    modular decomposition without enumerating them — the recursion of its
    ``Decomposition._families`` with sizes instead of lists (series adds,
    parallel multiplies, k-of-n sums products over the needed members). Exact
    for a series–parallel diagram; an upper bound over a non-reducible core.
    ``(None, None)`` if the (private) decomposition isn't available."""
    try:
        from repyability.rbd.modular import KOON, NODE, SERIES

        dec = rbd._decomposition()
        if dec.always_works:
            return 1, 0

        def counts(paths: bool) -> list:
            out: list = [0] * len(dec.terms)
            for i, term in enumerate(dec.terms):
                if term[0] == NODE:
                    out[i] = 1
                    continue
                members = [out[c] for c in term[1]]
                if term[0] == KOON:
                    size = term[2] if paths else len(members) - term[2] + 1
                    out[i] = sum(_product(chosen) for chosen in combinations(members, size))
                elif (term[0] == SERIES) == paths:
                    out[i] = _product(members)
                else:
                    out[i] = sum(members)
            return out

        result = []
        for paths in (True, False):
            fam = counts(paths)
            if dec.root is not None:
                result.append(fam[dec.root])
            else:
                core = dec.core if paths else dec.core_cut_sets()
                result.append(sum(_product(fam[c] for c in chosen) for chosen in core or []))
        return result[0], result[1]
    except Exception:  # noqa: BLE001 - fall back to conservative listing
        return None, None


def _product(values) -> int:
    out = 1
    for v in values:
        out *= v
    return out


def _low_order_cut_sets(rbd, max_order: int = _LOW_ORDER_CUT_MAX) -> list:
    """Minimal cut sets of up to ``max_order`` components, found by evaluating
    the structure function: a set of components is a cut set iff the system
    fails with them failed and everything else working. Every candidate of a
    given size is one column of a single vectorised exact evaluation."""
    comps = sorted((n for n in rbd.nodes if n not in (rbd.input_node, rbd.output_node)), key=str)
    if not comps:
        return []
    found: list[int] = []  # bitmasks, for the minimality (superset) check
    out: list[frozenset] = []
    for k in range(1, max_order + 1):
        if comb(len(comps), k) > _LOW_ORDER_CANDIDATES_MAX:
            break
        cands = []
        for cand in combinations(range(len(comps)), k):
            mask = 0
            for i in cand:
                mask |= 1 << i
            if not any(f & mask == f for f in found):
                cands.append((cand, mask))
        for start in range(0, len(cands), 20_000):
            chunk = cands[start:start + 20_000]
            probs = {n: np.ones(len(chunk)) for n in rbd.nodes}
            for col, (cand, _) in enumerate(chunk):
                for i in cand:
                    probs[comps[i]][col] = 0.0
            works = np.asarray(rbd.system_probability(probs), dtype=float)
            for col, (cand, mask) in enumerate(chunk):
                if works[col] < 0.5:
                    found.append(mask)
                    out.append(frozenset(comps[i] for i in cand))
    return out


def _structure_sets(rbd) -> dict:
    """The diagram's minimal path and cut sets, within listing limits:
    ``{paths, n_paths, cuts, n_cuts, cuts_complete}`` (``n_*`` None when the
    count isn't known)."""
    n_paths, n_cuts = _set_counts(rbd)
    paths = None
    if n_paths is not None and n_paths <= _MAX_ENUMERATED_SETS:
        paths = list(rbd.get_min_path_sets(include_in_out_nodes=False))
        n_paths = len(paths)
    if n_cuts is not None and n_cuts <= _MAX_ENUMERATED_SETS:
        cuts = list(rbd.get_min_cut_sets(include_in_out_nodes=False))
        return {"paths": paths, "n_paths": n_paths, "cuts": cuts,
                "n_cuts": len(cuts), "cuts_complete": True}
    return {"paths": paths, "n_paths": n_paths, "cuts": _low_order_cut_sets(rbd),
            "n_cuts": n_cuts, "cuts_complete": False}


def _fussell_vesely(probs: dict, cut_sets, q_sys: float) -> dict:
    """Fussell–Vesely importance from a list of minimal cut sets: the share of
    system unreliability (unavailability) from cut sets containing the node —
    RePyability's cut-set form with the rare-event sum (``approx=True``)."""
    num: dict = {}
    for cut in cut_sets:
        prob = 1.0
        for m in cut:
            prob *= 1.0 - float(np.atleast_1d(probs[m])[0])
        for m in cut:
            num[m] = num.get(m, 0.0) + prob
    with np.errstate(all="ignore"):
        return {n: np.float64(num.get(n, 0.0)) / np.float64(q_sys) for n in probs}


def _mttf(rbd, base_hi: float, s: float = 0.0, **sf_kwargs) -> Optional[float]:
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
        if _conditional_sf(rbd, np.array([t_max]), s, **sf_kwargs)[0] < 1e-4:
            break
        t_max *= 2.0
    grid = np.linspace(0.0, t_max, 4000)
    sf = _conditional_sf(rbd, grid, s, **sf_kwargs)
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
    band: Optional[dict] = None,
) -> dict:
    """Analyse a builder graph and return a JSON-serialisable result payload.

    ``t_max`` sets the upper limit of the time axis the curves are computed
    over; when omitted it is derived from the nodes' own time scales.
    ``covariates`` maps node id -> covariate values for nodes backed by a
    proportional-hazards model, and ``resolve_model`` loads a saved fitted
    model by id. ``conditional_age`` (``s``) conditions every curve on having
    already survived to ``s``: the time axis becomes additional time ``t`` and
    each reliability is ``R(s + t) / R(s)``; the MTTF becomes the mean residual
    life at ``s``. ``band`` (``{"level": 0.95}``) adds a confidence band on
    the reliability, MTTF and B-lives from the fitted blocks' parameter
    uncertainty (see :mod:`backend.services.rbd_uncertainty`); it isn't
    computed unless asked for. Raises :class:`AnalysisError` with a
    user-facing message if the graph can't be turned into a valid RBD.
    """
    rbd, labels, node_types, reliabilities, working_nodes, broken_nodes, baseline = _build_rbd(
        graph, resolve_subsystem, None, resolve_model, covariates
    )
    # RePyability's native what-if override for the system-level calls.
    overrides = {"working_nodes": working_nodes, "broken_nodes": broken_nodes}
    sets = _structure_sets(rbd)

    s = float(conditional_age) if conditional_age and conditional_age > 0 else 0.0
    grid = _time_grid(reliabilities, t_max)
    if not (t_max is not None and np.isfinite(t_max) and t_max > 0):
        # Auto axis: size it to the system, not the longest-lived block.
        grid = np.linspace(0.0, _system_horizon(rbd, float(grid[-1]), s, **overrides), _GRID_POINTS)
    system_sf = _conditional_sf(rbd, grid, s, **overrides)

    # Per-node reliability over the same grid (skip pure voting gates, which
    # are perfectly reliable and not informative to plot). A pinned node shows
    # the constant it's forced to (1 working, 0 failed), not its life model.
    node_payloads = []
    for nid in rbd.nodes:
        if node_types.get(nid) == "knode":
            continue
        if nid in working_nodes:
            node_sf = np.ones_like(grid)
        elif nid in broken_nodes:
            node_sf = np.zeros_like(grid)
        else:
            node_sf = _conditional_sf(reliabilities[nid], grid, s)
        node_payloads.append(
            {
                "id": nid,
                "label": labels.get(nid, nid),
                "type": node_types.get(nid),
                "sf": _clean(node_sf),
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
        # are consistent with the displayed curves; pinned nodes sit at 1 / 0.
        def _node_prob(n):
            if n in working_nodes:
                return np.array([1.0])
            if n in broken_nodes:
                return np.array([0.0])
            return _conditional_sf(reliabilities[n], np.array([t_rep]), s)

        node_probs = {n: _node_prob(n) for n in rbd.nodes}

        def _imp(measure: dict) -> dict:
            out = {}
            for n, v in measure.items():
                if node_types.get(n) == "knode":  # voting gates aren't components
                    continue
                val = float(np.atleast_1d(v)[0])
                out[str(n)] = val if np.isfinite(val) else None
            return out

        # All six RePyability importance measures, at the representative time.
        # Criticality is the failure-oriented form (RePyability 0.9's
        # default): the share of system failures a block accounts for. The
        # success-oriented form it replaced is exactly 1 for every block in
        # series, however unreliable, so it couldn't rank them.
        q_sys = 1.0 - float(np.atleast_1d(rbd.system_probability(node_probs))[0])
        importance = {
            "time": t_rep,
            "birnbaum": _imp(rbd._birnbaum_importance(node_probs)),
            "fussell_vesely": _imp(_fussell_vesely(node_probs, sets["cuts"], q_sys)),
            "risk_achievement_worth": _imp(rbd._risk_achievement_worth(node_probs)),
            "risk_reduction_worth": _imp(rbd._risk_reduction_worth(node_probs)),
            "criticality": _imp(rbd._criticality_importance(node_probs, kind="failure")),
            "improvement_potential": _imp(rbd._improvement_potential(node_probs)),
        }
        if not sets["cuts_complete"]:
            importance["fussell_vesely_basis"] = f"cut sets of up to {_LOW_ORDER_CUT_MAX} blocks"
    except Exception:
        importance = {}

    # Mean time to failure (or mean residual life at s), integrated from the
    # system reliability curve.
    try:
        mttf = _mttf(rbd, float(grid[-1]), s, **overrides)
    except Exception:
        mttf = None

    # System B-lives: time by which x% of systems have failed (R = 1 − x/100),
    # read off the (conditional) system reliability curve. None if beyond the
    # computed horizon.
    def _blife(frac: float):
        target = 1.0 - frac
        sf = np.asarray(system_sf, dtype=float)
        if not sf.size or sf[0] <= target:
            return float(grid[0]) if sf.size else None
        for i in range(1, len(grid)):
            if sf[i] <= target:
                s0, s1 = sf[i - 1], sf[i]
                if s1 == s0:
                    return float(grid[i])
                f = (s0 - target) / (s0 - s1)
                return float(grid[i - 1] + f * (grid[i] - grid[i - 1]))
        return None

    blife = {"b10": _blife(0.10), "b50": _blife(0.50)}

    def _named_sets(sets) -> list:
        return sorted(
            (sorted(labels.get(n, str(n)) for n in s_) for s_ in sets),
            key=len,
        )

    structure = {
        "min_path_sets": _named_sets(sets["paths"] or [])[:_LISTED_SETS],
        "min_cut_sets": _named_sets(sets["cuts"])[:_LISTED_SETS],
        "n_min_path_sets": sets["n_paths"],
        "n_min_cut_sets": sets["n_cuts"],
        "cut_sets_complete": sets["cuts_complete"],
    }
    if not sets["cuts_complete"]:
        structure["cut_sets_max_order"] = _LOW_ORDER_CUT_MAX

    # Common-cause impact: system reliability WITH vs WITHOUT the coupling, at the
    # representative time and across the grid — the headline "CCF cost".
    ccf = None
    if baseline is not None:
        try:
            base_sf = _conditional_sf(baseline, grid, s, **overrides)
            r_with = float(system_sf[target_idx])
            r_without = float(base_sf[target_idx])
            ccf = {
                "groups": [
                    {"members": [labels.get(m, str(m)) for m in (g.get("members") or [])],
                     "beta": float(g.get("beta"))}
                    for g in (graph.get("ccf_groups") or [])
                    if len([m for m in (g.get("members") or []) if m in reliabilities]) >= 2
                    and _valid_beta(g.get("beta"))
                ],
                "time": t_rep,
                "reliability_with": r_with,
                "reliability_without": r_without,
                "baseline_sf": _clean(base_sf),
            }
        except Exception:  # noqa: BLE001 - the main result still stands
            ccf = None

    result = {
        "unit": (graph.get("unit") or "").strip(),
        "time": grid.tolist(),
        "system": {"sf": _clean(system_sf), "ff": _clean(1.0 - system_sf)},
        "mttf": mttf,
        "blife": blife,
        "conditional_age": s,
        "nodes": node_payloads,
        "importance": importance,
        "structure": structure,
        "ccf": ccf,
        "repyability_version": _repyability_version(),
    }
    if band is not None:
        from backend.services import rbd_uncertainty

        result["band"] = rbd_uncertainty.system_band(
            graph, rbd, grid, s, working_nodes, broken_nodes,
            resolve_subsystem=resolve_subsystem, resolve_model=resolve_model,
            covariates=covariates, level=(band or {}).get("level"),
        )
    return result


def _valid_beta(v) -> bool:
    try:
        return 0.0 < float(v) < 1.0
    except (TypeError, ValueError):
        return False


# ---------------------------------------------------------------------------
# Repairable systems — availability analysis
# ---------------------------------------------------------------------------
# A repairable RBD is a distinct modelling choice: every component carries a
# failure distribution AND a repair-time (MTTR) distribution, and the system is
# characterised by its *availability* (long-run uptime), not a one-shot
# reliability curve. Built on RePyability's RepairableRBD.

# The availability simulation runs to a precision target (#104): replications
# are added in batches of _AVAIL_BATCH, in antithetic pairs, until the
# confidence interval of the window's mean availability is within the
# tolerance (see _availability_tolerance) — or the wall-clock budget runs out.
# A pilot batch measures the cost per replication to turn the budget into a
# replication limit (never below the minimum); if even the minimum wouldn't
# fit, the default horizon is shortened. The exact long-run figures don't
# depend on the simulation at all.
_AVAIL_SIMS = 20_000  # the most replications a run makes (the budget usually binds first)
_AVAIL_BATCH = 500  # first batch and step of a run to the target; also shapes the curve's band
_AVAIL_TIME_BUDGET = 20.0
_AVAIL_MIN_SIMS = 100
_AVAIL_PILOT_SIMS = 20
_AVAIL_SEED = 1
_AVAIL_CONFIDENCE = 0.95
# Tolerance on the window's mean availability, relative to the unavailability
# (a fixed absolute tolerance is meaningless at 99.99%: ±0.001 would swamp a
# 0.0001 unavailability), and never looser than 0.1 percentage point.
_AVAIL_REL_TOLERANCE = 0.05
_AVAIL_MAX_TOLERANCE = 1e-3
_AVAIL_MIN_TOLERANCE = 1e-12  # RePyability wants > 0; a never-down system meets it at once


def _always_up():
    """A repairable stand-in that never fails — used for pure logic/voting
    (k-of-n) gates, which carry no failure or repair behaviour of their own but
    must still be a repairable component for RePyability's availability solver.
    Callers also pin it working (``working_nodes``), so it is exactly perfect."""
    import surpyval as sp

    return NonRepairable(
        sp.Weibull.from_params([1e12, 1.0]),  # effectively never fails
        sp.LogNormal.from_params([0.1, 0.1]),
    )


def _repair_distribution(data: dict, label: str, resolve_model=None):
    """Build a component's time-to-repair distribution from its ``repair`` spec
    (same shape as a life model: distribution_id + params). Repairable
    components must have one."""
    spec = data.get("repair")
    if not spec:
        raise AnalysisError(
            f"{label}: repairable diagrams need a repair-time distribution on "
            "every component — add one (e.g. a Lognormal mean-time-to-repair)."
        )
    return _build_distribution(spec, f"{label} (repair)", resolve_model, None)


def _build_repairable_rbd(graph: dict, resolve_model=None):
    """Translate a builder graph into a RepairableRBD (availability).

    v1 supports plain component nodes (each a life model + repair) and k-of-n
    voting gates; other node types raise a clear error. Nodes pinned
    working/failed (``data.state``) are forced via RePyability's native
    ``working_nodes``/``broken_nodes`` overrides; a pinned node needs no life
    or repair model (validation doesn't ask for one), so a never-failing
    stand-in is used when it has none. Returns
    ``(rbd, labels, gate_ids, working_nodes, broken_nodes)``.
    """
    nodes = graph.get("nodes") or []
    raw_edges = graph.get("edges") or []
    edges = [
        (e["source"], e["target"])
        for e in raw_edges
        if e.get("source") and e.get("target")
    ]
    if not edges:
        raise AnalysisError("The diagram has no connections to analyse.")

    # RePyability's RepairableRBD simulates each node as its own unit, so a
    # repeated block (#102) can't be honoured: refuse rather than approximate.
    repeats, problems = rbd_repeats.find_repeats(nodes)
    if problems:
        raise AnalysisError(next(iter(problems.values())))
    if repeats:
        raise AnalysisError(rbd_repeats.repairable_message(nodes, repeats))

    node_ids = {n.get("id") for n in nodes}
    components: dict[Any, Any] = {}
    k: dict[Any, int] = {}
    labels: dict[Any, str] = {}
    gate_ids: set = set()  # synthetic voting gates — excluded from downtime
    working_nodes: set = set()
    broken_nodes: set = set()

    for node in nodes:
        nid = node.get("id")
        ntype = node.get("type")
        if ntype in ("input", "output"):
            continue
        data = node.get("data") or {}
        label = data.get("label") or nid
        labels[nid] = label
        state = data.get("state")
        if state == "working":
            working_nodes.add(nid)
        elif state == "failed":
            broken_nodes.add(nid)
        pinned = state in ("working", "failed")
        if ntype == "knode":
            components[nid] = _always_up()
            k[nid] = max(int(data.get("n") or 1), 1)
            gate_ids.add(nid)
            continue
        if ntype != "component":
            raise AnalysisError(
                f"{label}: “{ntype}” blocks aren't supported in repairable "
                "diagrams yet — use component blocks (each with a life model and "
                "a repair time), optionally with a k-of-n voting gate."
            )
        if pinned and not (data.get("model") and data.get("repair")):
            # The override fixes its state; the stand-in is never consulted.
            components[nid] = _always_up()
            continue
        reliability = _build_distribution(data.get("model"), label, resolve_model, None)
        repair = _repair_distribution(data, label, resolve_model)
        components[nid] = NonRepairable(reliability, repair)

    if not components:
        raise AnalysisError("The diagram has no component nodes to analyse.")

    input_node = "input" if "input" in node_ids else None
    output_node = "output" if "output" in node_ids else None
    try:
        rbd = RepairableRBD(
            edges, components, k=k, input_node=input_node, output_node=output_node,
        )
    except ValueError as exc:
        raise AnalysisError(
            "The diagram isn't a valid reliability block diagram: "
            f"{exc}. Check that every component is wired between the input and output."
        ) from exc
    return rbd, labels, gate_ids, working_nodes, broken_nodes


def _resample_step(timeline, values, grid) -> np.ndarray:
    """Resample a right-continuous step series onto ``grid``.

    ``values[i]`` holds from ``timeline[i]`` until the next event, so the value
    at grid time ``t`` is the one at the latest timeline point <= ``t`` (grid
    times before the first event take the first value). ``timeline`` must be
    sorted ascending; it is typically irregular (Monte-Carlo event times), which
    is why it can't simply be plotted against an evenly spaced axis.
    """
    timeline = np.asarray(timeline, dtype=float)
    values = np.asarray(values, dtype=float)
    idx = np.searchsorted(timeline, np.asarray(grid, dtype=float), side="right") - 1
    idx = np.clip(idx, 0, values.size - 1)
    return values[idx]


def _availability_curve(res, t_simulation: float) -> Optional[dict]:
    """The time-dependent availability curve (with its pointwise 95% band when
    the result provides one), resampled onto a uniform grid."""
    av_series = getattr(res, "availability", None)
    timeline = getattr(res, "timeline", None)
    if av_series is None or timeline is None:
        return None
    arr = np.atleast_1d(np.asarray(av_series, dtype=float))
    tl = np.atleast_1d(np.asarray(timeline, dtype=float))
    if arr.size < 2 or tl.size != arr.size:
        return None
    grid = np.linspace(0.0, float(t_simulation), _GRID_POINTS)
    curve = {"t": grid.tolist(), "availability": _clean(_resample_step(tl, arr, grid))}
    interval = getattr(res, "availability_interval", None)
    if callable(interval):
        try:
            lower, upper = interval(0.95)
            curve["lower"] = _clean(_resample_step(tl, lower, grid))
            curve["upper"] = _clean(_resample_step(tl, upper, grid))
            curve["confidence"] = 0.95
        except Exception:  # noqa: BLE001 - the band is optional
            pass
    return curve


_IMPORTANCE_METHODS = {
    # payload key -> RepairableRBD method (each evaluated at the blocks'
    # long-run availabilities)
    # (Fussell–Vesely is computed from the listed cut sets — see
    # _structure_sets — so a diagram with millions of cut sets stays fast.)
    "birnbaum": "birnbaum_importance",
    "criticality": "criticality_importance",  # failure-oriented (0.9 default)
    "risk_achievement_worth": "risk_achievement_worth",
    "risk_reduction_worth": "risk_reduction_worth",
    "improvement_potential": "improvement_potential",
}


def _steady_importance(rbd, labels, gate_ids, overrides, steady, cut_sets) -> dict:
    """Per-block steady-state importance measures, keyed by node id, evaluated
    at the blocks' long-run availabilities (RePyability's RepairableRBD
    methods). Voting gates are not components and are left out."""
    measures: dict[str, dict] = {}
    for key, method in _IMPORTANCE_METHODS.items():
        try:
            with np.errstate(all="ignore"):
                measures[key] = getattr(rbd, method)(**overrides)
        except Exception:  # noqa: BLE001 - report what we can
            measures[key] = {}
    try:
        node_av = rbd.node_availability()
    except Exception:  # noqa: BLE001
        node_av = {}
    try:
        probs = rbd._probabilities_with_overrides(
            node_av, overrides.get("working_nodes"), overrides.get("broken_nodes"))
        q_sys = (1.0 - steady) if steady is not None and np.isfinite(steady) else np.nan
        measures["fussell_vesely"] = {n: float(v) for n, v in _fussell_vesely(probs, cut_sets, q_sys).items()}
    except Exception:  # noqa: BLE001
        measures["fussell_vesely"] = {}
    working = overrides.get("working_nodes") or set()
    broken = overrides.get("broken_nodes") or set()
    sys_unavail = (1.0 - steady) if steady is not None and np.isfinite(steady) else None

    out: dict[str, dict] = {}
    for nid in rbd.components:
        if nid in gate_ids:
            continue
        if nid in working:
            a_i = 1.0
        elif nid in broken:
            a_i = 0.0
        else:
            a_i = _f(node_av.get(nid))
        row: dict[str, Any] = {
            "label": labels.get(nid, str(nid)),
            "availability": a_i,
            "pinned": "working" if nid in working else "failed" if nid in broken else None,
        }
        for key, vals in measures.items():
            row[key] = _f(vals[nid]) if nid in vals else None
        # Failure-oriented criticality: the share of system unavailability
        # attributable to this block, I_B·(1−A_i)/(1−A_sys). RePyability's
        # ``criticality_importance`` is the success-oriented form
        # (I_B·A_i/A_sys), which is ≈1 for every series block of a
        # high-availability system and so doesn't rank them.
        b = row.get("birnbaum")
        if b is not None and a_i is not None and sys_unavail and sys_unavail > 0:
            row["unavailability_criticality"] = _f(b * (1.0 - a_i) / sys_unavail)
        else:
            row["unavailability_criticality"] = None
        out[str(nid)] = row
    return out


def _simulated_criticality(res, labels, gate_ids) -> dict:
    """Per-block criticality indices observed in the availability simulation
    (``AvailabilityResult.criticalities``), keyed by node id; gates excluded."""
    crit = getattr(res, "criticalities", None)
    if crit is None:
        return {}
    oci = crit.operational_criticality_index
    fci = crit.failure_criticality_index
    rci = crit.restoration_criticality_index
    series = {
        "operational_criticality_up": oci.up,
        "operational_criticality_down": oci.down,
        "failure_criticality": fci.per_system_failure,
        "failure_criticality_per_component": fci.per_component_failure,
        "restoration_criticality": rci.by_system,
        "restoration_criticality_per_component": rci.by_component,
    }
    ids: set = set()
    for d in series.values():
        ids.update(d.keys())
    out: dict[str, dict] = {}
    for nid in ids:
        if nid in gate_ids:
            continue
        row: dict[str, Any] = {"label": labels.get(nid, str(nid))}
        for key, d in series.items():
            # A block that never failed/restored in the simulation has no
            # entry — a genuine zero share, not a missing value.
            row[key] = _f(d.get(nid, 0.0))
        out[str(nid)] = row
    return out


def _z(confidence: float) -> float:
    """The two-sided normal quantile for ``confidence``."""
    from scipy.stats import norm

    return float(norm.ppf(0.5 + confidence / 2.0))


def _even(n) -> int:
    """``n`` rounded down to an even count (antithetic runs come in pairs),
    at least 2."""
    return max(2, int(n) - int(n) % 2)


def _availability_tolerance(unavailability) -> float:
    """The half-width target for the window's mean availability:
    :data:`_AVAIL_REL_TOLERANCE` of the long-run unavailability (of the
    availability, for a system that is mostly down), never looser than
    :data:`_AVAIL_MAX_TOLERANCE`. So 99.99% is pinned to ±0.0005 percentage
    points, 98% to ±0.1."""
    try:
        u = float(unavailability)
    except (TypeError, ValueError):
        return _AVAIL_MAX_TOLERANCE
    if not np.isfinite(u):
        return _AVAIL_MAX_TOLERANCE
    scale = min(max(u, 0.0), max(1.0 - u, 0.0))
    return float(min(max(_AVAIL_REL_TOLERANCE * scale, _AVAIL_MIN_TOLERANCE), _AVAIL_MAX_TOLERANCE))


def _plan_simulation(per_rep: float, n_max: int, t_sim: float,
                     user_horizon: bool) -> tuple[int, int, float, bool]:
    """``(batch, max_n, horizon, shortened)`` fitting :data:`_AVAIL_TIME_BUDGET`
    at ``per_rep`` seconds per replication.

    ``max_n`` is the most replications that fit the budget, capped at
    ``n_max`` and floored at :data:`_AVAIL_MIN_SIMS`, and rounded down to
    whole batches so it moves in coarse steps (a run that reaches its target
    doesn't depend on it at all). When even the floor won't fit, a *default*
    horizon is shortened in proportion (simulation cost is proportional to the
    number of failure events, i.e. to the horizon); a horizon the user chose is
    kept.
    """
    n_max = _even(n_max)
    n_floor = _even(min(_AVAIL_MIN_SIMS, n_max))
    if per_rep * n_floor > _AVAIL_TIME_BUDGET:
        if user_horizon:
            return n_floor, n_floor, t_sim, False
        return n_floor, n_floor, t_sim * _AVAIL_TIME_BUDGET / (per_rep * n_floor), True
    max_n = _even(min(n_max, max(n_floor, _AVAIL_TIME_BUDGET / per_rep)))
    batch = _even(min(_AVAIL_BATCH, max_n))
    return batch, batch * (max_n // batch), t_sim, False


def _simulate(rbd, t_sim: float, overrides: dict, n: int, **kwargs):
    """``(result, antithetic)``: RePyability's availability simulation, seeded,
    in antithetic pairs when every block's draws can be replayed (surpyval
    parametric models) and plain otherwise. ``kwargs`` pass the stopping rule
    through; its "did not converge" warning is reported in the result's
    precision instead."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        try:
            res = rbd.availability(t_simulation=t_sim, N=_even(n), method="c", seed=_AVAIL_SEED,
                                   antithetic=True, **kwargs, **overrides)
            return res, True
        except NotImplementedError:
            return rbd.availability(t_simulation=t_sim, N=n, method="c", seed=_AVAIL_SEED,
                                    **kwargs, **overrides), False


def _size_simulation(rbd, t_sim: float, n_max: int, overrides: dict,
                     user_horizon: bool) -> tuple[int, int, float, bool]:
    """``(batch, max_n, horizon, shortened)`` for a run to the precision
    target: a pilot batch times one replication and :func:`_plan_simulation`
    turns the time budget into a replication limit."""
    if n_max <= _AVAIL_PILOT_SIMS:
        n = _even(n_max)
        return n, n, t_sim, False
    start = time.perf_counter()
    try:
        _simulate(rbd, t_sim, overrides, _AVAIL_PILOT_SIMS)
    except Exception:  # noqa: BLE001 - the real run reports the problem
        n = _even(min(_AVAIL_BATCH, n_max))
        return n, n, t_sim, False
    per_rep = max((time.perf_counter() - start) / _AVAIL_PILOT_SIMS, 1e-9)
    return _plan_simulation(per_rep, n_max, t_sim, user_horizon)


def _run_to_precision(rbd, t_sim: float, overrides: dict, batch: int, max_n: int,
                      tolerance: float, expect_downtime: bool):
    """``(result, antithetic)`` of a run to ``tolerance`` on the window's mean
    availability. RePyability stops as soon as the interval is narrow enough,
    and one batch that saw no system downtime at all has a zero-width
    interval — for a system that does go down that is a lack of evidence, not
    precision, so the run is then repeated at ``max_n``."""
    kwargs = {"confidence": _AVAIL_CONFIDENCE}
    if max_n > batch:
        kwargs.update(tolerance=tolerance, max_N=max_n)
    res, antithetic = _simulate(rbd, t_sim, overrides, batch, **kwargs)
    if (expect_downtime and max_n > getattr(res, "n_simulations", max_n)
            and not float(getattr(res, "system_downtime", 1.0) or 0.0) > 0.0):
        res, antithetic = _simulate(rbd, t_sim, overrides, max_n)
    return res, antithetic


def _precision(res, tolerance: float, antithetic: bool, max_n: Optional[int],
               expect_downtime: bool) -> Optional[dict]:
    """How precisely the simulation pinned down the window's mean availability:
    its confidence interval, the target it was run to, and whether it got
    there (``max_n`` is None for a fixed replication count)."""
    try:
        ci = res.mean_availability_interval(_AVAIL_CONFIDENCE)
    except Exception:  # noqa: BLE001 - a result without per-run up times
        return None
    se = _f(ci.standard_error)
    # z·SE, unclipped: the interval is clipped to [0, 1], its precision isn't.
    half = None if se is None else _z(_AVAIL_CONFIDENCE) * se
    reached = half is not None and half <= tolerance and (se > 0.0 or not expect_downtime)
    return {
        "window_availability": _f(ci.estimate),
        "lower": _f(ci.lower),
        "upper": _f(ci.upper),
        "half_width": half,
        "standard_error": se,
        "confidence": _AVAIL_CONFIDENCE,
        "tolerance": tolerance,
        "reached": bool(reached),
        "n_simulations": int(res.n_simulations),
        "max_simulations": max_n,
        "antithetic": bool(antithetic),
        "mode": "fixed" if max_n is None else "tolerance",
    }


def analyze_availability(
    graph: dict,
    resolve_model=None,
    t_simulation: Optional[float] = None,
    n_simulations: Optional[int] = None,
) -> dict:
    """Availability analysis of a repairable RBD: steady-state uptime, mean up/
    down time, failure frequency, each component's share of downtime, and
    per-block importance / criticality measures.

    The simulation runs to a precision target on the window's mean
    availability (see :func:`_availability_tolerance`), bounded by the time
    budget and by :data:`_AVAIL_SIMS` replications (read at call time so tests
    can shrink it). ``n_simulations`` runs exactly that many instead (rounded
    up to whole antithetic pairs)."""
    fixed_n = bool(n_simulations)
    n_sims = int(n_simulations) + int(n_simulations) % 2 if n_simulations else _AVAIL_SIMS
    rbd, labels, gate_ids, working_nodes, broken_nodes = _build_repairable_rbd(
        graph, resolve_model
    )
    # Voting gates are pinned working too: their never-failing stand-in is only
    # *nearly* perfect (unavailable ~1e-12), which would otherwise add a bias to
    # every exact figure of a highly available system.
    overrides = {"working_nodes": working_nodes | gate_ids, "broken_nodes": broken_nodes}
    sets = _structure_sets(rbd)

    try:
        steady = float(rbd.mean_availability(**overrides))
    except Exception as exc:  # noqa: BLE001
        raise AnalysisError(f"Couldn't compute availability: {exc}") from exc

    # A simulation horizon long enough to reach steady state: a few multiples of
    # the slowest component's characteristic life, unless the user set one.
    user_horizon = bool(t_simulation and t_simulation > 0)
    if not user_horizon:
        t_simulation = _availability_horizon(graph)
    horizon_shortened = False
    batch = max_n = n_sims
    if not fixed_n:
        batch, max_n, t_simulation, horizon_shortened = _size_simulation(
            rbd, float(t_simulation), n_sims, overrides, user_horizon)
    tolerance = _availability_tolerance(1.0 - steady)
    expect_downtime = bool(np.isfinite(steady) and steady < 1.0)

    per_node = []
    sim = {"mean_up_time": None, "mean_down_time": None, "failure_frequency": None}
    curve = None
    criticality: dict = {}
    precision = None
    try:
        if fixed_n:
            res, antithetic = _simulate(rbd, float(t_simulation), overrides, n_sims)
        else:
            res, antithetic = _run_to_precision(
                rbd, float(t_simulation), overrides, batch, max_n, tolerance, expect_downtime)
        n_sims = int(getattr(res, "n_simulations", n_sims))
        precision = _precision(res, tolerance, antithetic, None if fixed_n else max_n,
                               expect_downtime)
        sim = {
            "mean_up_time": _f(getattr(res, "mean_up_time", None)),
            "mean_down_time": _f(getattr(res, "mean_down_time", None)),
            "failure_frequency": _f(getattr(res, "failure_frequency", None)),
        }
        downtime = getattr(res, "node_downtime", None) or {}
        # Exclude synthetic voting gates (they never fail); share is over real
        # components only.
        real = {nid: dt for nid, dt in downtime.items() if nid not in gate_ids}
        total_dt = sum(v for v in real.values() if v) or 1.0
        for nid, dt in real.items():
            per_node.append({
                "id": str(nid), "label": labels.get(nid, str(nid)),
                "downtime": _f(dt),
                "share": _f((dt or 0.0) / total_dt),
            })
        per_node.sort(key=lambda r: (r["share"] or 0.0), reverse=True)
        # Time-dependent availability curve. The MC series is indexed by
        # irregular event times (``res.timeline``) — resample it onto a
        # uniform grid rather than plotting it against an even axis (#80).
        curve = _availability_curve(res, float(t_simulation))
        try:
            criticality = _simulated_criticality(res, labels, gate_ids)
        except Exception:  # noqa: BLE001
            criticality = {}
    except Exception:  # noqa: BLE001 - the steady-state figure still stands
        pass

    # Exact steady-state MUT / MDT / failure frequency (Birnbaum/Vesely
    # formula); the finite-window simulation estimates are the fallback.
    exact: dict[str, Optional[float]] = {}
    for key, method in (("mean_up_time", "mean_up_time"),
                        ("mean_down_time", "mean_down_time"),
                        ("failure_frequency", "system_failure_frequency")):
        try:
            with np.errstate(all="ignore"):
                exact[key] = _f(getattr(rbd, method)(**overrides))
        except Exception:  # noqa: BLE001
            exact[key] = None
    figures = {k: (exact[k] if exact.get(k) is not None else sim[k]) for k in sim}
    figures_basis = {
        k: ("exact" if exact.get(k) is not None else "simulation") for k in sim
    }

    try:
        importance = _steady_importance(rbd, labels, gate_ids, overrides, steady, sets["cuts"])
    except Exception:  # noqa: BLE001
        importance = {}

    return {
        "kind": "repairable",
        "unit": (graph.get("unit") or "").strip(),
        "steady_state_availability": steady,
        "unavailability": (1.0 - steady) if np.isfinite(steady) else None,
        "mean_up_time": figures["mean_up_time"],
        "mean_down_time": figures["mean_down_time"],
        "failure_frequency": figures["failure_frequency"],
        "figures_basis": figures_basis,
        "simulated": sim,
        "n_simulations": n_sims,
        "t_simulation": float(t_simulation),
        "horizon_shortened": horizon_shortened,
        "precision": precision,
        "per_node": per_node,
        "importance": importance,
        "criticality": criticality,
        "pinned": {
            "working": sorted(str(n) for n in working_nodes),
            "failed": sorted(str(n) for n in broken_nodes),
        },
        "curve": curve,
        "repyability_version": _repyability_version(),
    }


def _f(v) -> Optional[float]:
    try:
        v = float(np.atleast_1d(v)[0]) if hasattr(v, "__len__") else float(v)
        return v if np.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def _spec_mean(spec) -> Optional[float]:
    """Mean of an inline/saved life or repair spec (``distribution_id`` +
    ``params``), or None when it can't be built without more context."""
    try:
        entry = DISTRIBUTIONS[spec["distribution_id"]]
        values = [float(p["value"]) for p in spec.get("params") or []]
        mean = float(entry["dist"].from_params(values).mean())
    except Exception:  # noqa: BLE001 - covariate models, odd specs: skip
        return None
    return mean if np.isfinite(mean) and mean > 0 else None


def _settling_time(model: dict, repair: Optional[dict]) -> Optional[float]:
    """How long a component's point availability takes to settle, roughly: a
    few failure-repair cycles for a wear-out (non-exponential) life, but only a
    few repair times for an exponential one — its availability relaxes at rate
    λ + μ, however rare the failures."""
    life = _spec_mean(model)
    if life is None:
        return None
    mttr = _spec_mean(repair) if isinstance(repair, dict) else None
    if model.get("distribution_id") == "exponential":
        return mttr if mttr is not None else None
    return life + (mttr or 0.0)


def _availability_horizon(graph: dict) -> float:
    """A simulation length that reaches steady state: 10× the slowest settling
    time among the components that matter — those carrying ≥1% of the largest
    downtime weight (Birnbaum importance × unavailability). A reliable block
    off in a redundant corner, or an exponential block that rarely fails, no
    longer stretches the simulation for every other block. Fallback 1000.
    """
    nodes = {n.get("id"): (n.get("data") or {}) for n in graph.get("nodes") or []}
    settle = {
        nid: t for nid, data in nodes.items()
        if isinstance(data.get("model"), dict)
        and (t := _settling_time(data["model"], data.get("repair"))) is not None
    }
    if not settle:
        return 1000.0
    keep = set(settle)
    try:
        # Graph only (no model resolver), so the exported script computes the
        # very same horizon; saved life models carry their parameters inline.
        rbd, _, gate_ids, working, broken = _build_repairable_rbd(graph)
        probs = rbd._probabilities_with_overrides(
            rbd.node_availability(), working | gate_ids, broken)
        birnbaum = rbd._birnbaum_importance(probs)
        weight = {
            nid: float(np.atleast_1d(birnbaum.get(nid, 0.0))[0]) * (1.0 - float(np.atleast_1d(probs[nid])[0]))
            for nid in settle if nid in probs
        }
        top = max(weight.values(), default=0.0)
        if top > 0:
            keep = {nid for nid, w in weight.items() if w >= 0.01 * top}
    except Exception:  # noqa: BLE001 - fall back to every component
        pass
    hi = max((settle[nid] for nid in keep), default=0.0)
    return (hi * 10.0) if hi > 0 else 1000.0


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
