"""Compare two repairable RBDs (#104): is design B more available than design
A, and by how much?

Both designs are simulated over the same window with **common random
numbers** (RePyability 0.9's ``RepairableRBD.compare``): in each simulation a
block with the same id in both diagrams draws the same random numbers, so the
same failures and repairs where it is modelled the same way, and matching ones
(the same quantiles) where it isn't. The per-simulation differences then come
from how the designs differ rather than from chance, and their mean is a far
more precise estimate of the difference than two separate runs give — most of
all for a copy of a diagram with one change, where every other block pairs up.

Like the availability analysis, the comparison runs to a precision target on
the difference (in batches, until its confidence interval is within the
tolerance) inside the same time budget. The exact long-run availabilities of
both designs, and their difference, come alongside; they don't depend on the
simulation.

The result keeps each compared quantity under ``differences`` in one shape:
``availability`` always, and ``cost`` (#99) when both designs are priced — the
difference in the window's simulated cost from the same paired simulations
(so the same common random numbers), with the exact long-run cost-rate
difference alongside where RePyability has it. The run stops on the
availability target; the cost interval shows the precision it reached.
"""

from __future__ import annotations

import time
from typing import Optional

import numpy as np

from backend.services import rbd_analysis as ra
from backend.services.rbd_analysis import AnalysisError

# Pilot replications timing one paired simulation, drawn from streams of their
# own (a batch index no real run reaches) and then discarded.
_PILOT_SIMS = 20
_PILOT_BATCH = 2**31 - 1
# The difference is run to a fifth of the availability analysis's tolerance
# (so 1% of the less available design's unavailability): a design change
# typically moves the unavailability by a few percent, and common random
# numbers make that precision cheap — usually one batch.
_TOLERANCE_FRACTION = 0.2


def _design(graph: dict, resolve_model) -> dict:
    """A repairable RBD built exactly as the availability analysis builds it,
    with its pins/voting gates and exact long-run availability."""
    if not (graph or {}).get("repairable"):
        raise AnalysisError(
            "Only repairable (availability) diagrams can be compared — both "
            "diagrams need repair times on their blocks."
        )
    rbd, labels, gate_ids, working, broken = ra._build_repairable_rbd(graph, resolve_model)
    overrides = {"working_nodes": working | gate_ids, "broken_nodes": broken}
    try:
        with np.errstate(all="ignore"):
            steady = float(rbd.mean_availability(**overrides))
    except NotImplementedError:
        steady = None  # block replacement, timed proof tests…: simulated only
    except Exception as exc:  # noqa: BLE001
        raise AnalysisError(f"Couldn't compute availability: {exc}") from exc
    cost_rate = None
    if rbd.has_costs:
        try:
            with np.errstate(all="ignore"):
                cost_rate = float(rbd.expected_cost_rate(**overrides))
        except NotImplementedError:
            cost_rate = None
    return {
        "rbd": rbd,
        "overrides": overrides,
        "steady": steady,
        "priced": bool(rbd.has_costs),
        "cost_rate": cost_rate,
        "blocks": {nid for nid in rbd.components if nid not in gate_ids},
    }


def _key(entropy) -> int:
    """A stream key, derived as ``RepairableRBD.compare`` derives it from a seed."""
    return int(np.random.SeedSequence(entropy).generate_state(1, np.uint64)[0])


def _paired_run(design: dict, t_sim: float, n: int, key: int):
    """``(fractions, costs)``: each simulation's fraction of the window up and
    (for a priced design, else None) its cost, from streams keyed by ``key``
    and the block ids (common random numbers). This is
    ``RepairableRBD.compare``'s inner run, but with the diagram's pinned blocks
    and voting gates held as the analysis holds them — ``compare`` itself
    takes no overrides."""
    from repyability.rbd.repairable_rbd import _KeyedStreams

    ov = design["overrides"]
    tally = design["rbd"]._run(
        t_sim, set(ov["working_nodes"]), set(ov["broken_nodes"]), "c", n, False,
        key % 2**32, streams=_KeyedStreams(key),
    )
    costs = np.asarray(tally.cost_samples, dtype=float) if design["priced"] else None
    return np.asarray(tally.uptimes, dtype=float) / t_sim, costs


def _paired_fractions(design: dict, t_sim: float, n: int, key: int) -> np.ndarray:
    """Each simulation's fraction of the window up (see :func:`_paired_run`)."""
    return _paired_run(design, t_sim, n, key)[0]


def _independent_run(design: dict, t_sim: float, n: int, seed: int):
    """``(fractions, costs)`` of an ordinary seeded run: the fallback when a
    block's draws can't be replayed from a stream of its own (non-parametric
    models)."""
    res = design["rbd"].availability(t_simulation=t_sim, N=n, method="c", seed=seed,
                                     **design["overrides"])
    costs = np.asarray(res.cost.samples, dtype=float) if res.cost is not None else None
    return np.asarray(res.uptimes, dtype=float) / t_sim, costs


def _batch_runs(a: dict, b: dict, t_sim: float, n: int, index: int, paired: bool):
    """``((fractions_a, costs_a), (fractions_b, costs_b))`` for batch
    ``index`` (its own streams, so batches are independent and a run is the
    same however it is split)."""
    key = _key([ra._AVAIL_SEED, index])
    if paired:
        return _paired_run(a, t_sim, n, key), _paired_run(b, t_sim, n, key)
    return (_independent_run(a, t_sim, n, key % 2**32),
            _independent_run(b, t_sim, n, (key + 1) % 2**32))


def _batch(a: dict, b: dict, t_sim: float, n: int, index: int, paired: bool):
    """``(fractions_a, fractions_b)`` for batch ``index``."""
    (fa, _), (fb, _) = _batch_runs(a, b, t_sim, n, index, paired)
    return fa, fb


def _difference(fa: np.ndarray, fb: np.ndarray, paired: bool) -> tuple[float, float]:
    """``(estimate, standard_error)`` of mean(B) − mean(A): from the paired
    differences with common random numbers, else from two independent means."""
    n = len(fa)
    if n < 2:
        return float(np.mean(fb) - np.mean(fa)), float("nan")
    if paired:
        return float(np.mean(fb - fa)), float(np.std(fb - fa, ddof=1) / np.sqrt(n))
    se = np.sqrt(np.var(fa, ddof=1) / n + np.var(fb, ddof=1) / n)
    return float(np.mean(fb) - np.mean(fa)), float(se)


def compare_availability(
    graph_a: dict,
    graph_b: dict,
    resolve_model_a=None,
    resolve_model_b=None,
    t_simulation: Optional[float] = None,
    n_simulations: Optional[int] = None,
) -> dict:
    """Design B against design A: the simulated difference in the window's mean
    availability (B − A) with its confidence interval, and both exact long-run
    availabilities and their difference.

    The window is the longer of the two designs' default horizons unless
    ``t_simulation`` is given. ``n_simulations`` runs exactly that many
    simulations of each instead of running to the precision target."""
    a = _design(graph_a, resolve_model_a)
    b = _design(graph_b, resolve_model_b)
    user_horizon = bool(t_simulation and t_simulation > 0)
    t_sim = float(t_simulation) if user_horizon else max(
        ra._availability_horizon(graph_a), ra._availability_horizon(graph_b))
    worse = max(_unavailability(a, t_sim), _unavailability(b, t_sim))
    tolerance = _TOLERANCE_FRACTION * ra._availability_tolerance(worse)
    expect_downtime = bool(np.isfinite(worse) and worse > 0.0)

    # Pilot: time one paired replication (and learn whether the blocks' draws
    # can be replayed for common random numbers at all).
    paired = True
    start = time.perf_counter()
    try:
        _batch(a, b, t_sim, _PILOT_SIMS, _PILOT_BATCH, True)
    except NotImplementedError:
        paired = False
        start = time.perf_counter()
        _batch(a, b, t_sim, _PILOT_SIMS, _PILOT_BATCH, False)
    per_rep = max((time.perf_counter() - start) / _PILOT_SIMS, 1e-9)

    shortened = False
    if n_simulations:
        batch = max_n = max(2, int(n_simulations))
    else:
        batch, max_n, t_sim, shortened = ra._plan_simulation(
            per_rep, ra._AVAIL_SIMS, t_sim, user_horizon)

    z = ra._z(ra._AVAIL_CONFIDENCE)
    fa: list = []
    fb: list = []
    ca: list = []
    cb: list = []
    costed = a["priced"] and b["priced"]
    index = 0
    reached = False
    while len(fa) < max_n:
        (xa, ya), (xb, yb) = _batch_runs(a, b, t_sim, min(batch, max_n - len(fa)), index, paired)
        fa.extend(xa)
        fb.extend(xb)
        if costed:
            ca.extend(ya)
            cb.extend(yb)
        index += 1
        est, se = _difference(np.asarray(fa), np.asarray(fb), paired)
        # Batches that saw no downtime in either design say nothing yet.
        evidence = not expect_downtime or min(min(fa), min(fb)) < 1.0
        reached = bool(np.isfinite(se) and z * se <= tolerance and evidence)
        if reached and not n_simulations:
            break
    fa_arr, fb_arr = np.asarray(fa), np.asarray(fb)
    est, se = _difference(fa_arr, fb_arr, paired)
    half = z * se if np.isfinite(se) else None
    lower = est - half if half is not None else None
    upper = est + half if half is not None else None
    if lower is not None and lower > 0:
        verdict = "b_higher"
    elif upper is not None and upper < 0:
        verdict = "a_higher"
    else:
        verdict = "no_detectable_difference"

    exact_a, exact_b = ra._f(a["steady"]), ra._f(b["steady"])
    differences = {
        # B − A.
        "availability": {
            "estimate": ra._f(est),
            "lower": ra._f(lower),
            "upper": ra._f(upper),
            "standard_error": ra._f(se),
            "half_width": ra._f(half),
            "confidence": ra._AVAIL_CONFIDENCE,
            "tolerance": tolerance,
            "reached": reached,
            "verdict": verdict,
            "exact": (exact_b - exact_a) if exact_a is not None and exact_b is not None else None,
        },
    }
    if costed:
        differences["cost"] = _cost_difference(a, b, np.asarray(ca), np.asarray(cb), paired, z)
    cost_note = None
    if a["priced"] != b["priced"]:
        cost_note = (f"Only design {'A' if a['priced'] else 'B'} is priced, so costs aren't "
                     "compared — give both designs costs to compare them.")
    return {
        "kind": "repairable_comparison",
        "unit": (graph_a.get("unit") or "").strip(),
        "t_simulation": float(t_sim),
        "horizon_shortened": shortened,
        "designs": {
            key: {
                "steady_state_availability": exact,
                "unavailability": (1.0 - exact) if exact is not None else None,
                "window_availability": ra._f(np.mean(arr)),
                "priced": design["priced"],
                "cost_rate": ra._f(design["cost_rate"]) if design["cost_rate"] is not None else None,
                "window_cost": ra._f(np.mean(costs)) if costed and len(costs) else None,
            }
            for key, exact, arr, design, costs in (
                ("a", exact_a, fa_arr, a, ca), ("b", exact_b, fb_arr, b, cb))
        },
        "differences": differences,
        "cost_note": cost_note,
        "n_simulations": len(fa),
        "max_simulations": None if n_simulations else max_n,
        "common_random_numbers": paired,
        "shared_blocks": len(a["blocks"] & b["blocks"]),
        "repyability_version": ra._repyability_version(),
    }


def _unavailability(design: dict, t_sim: float) -> float:
    """The design's long-run unavailability, or a quick simulated estimate
    when RePyability has no exact value (to set the precision target)."""
    if design["steady"] is not None:
        return 1.0 - design["steady"]
    from backend.services.rbd_maintenance import estimated_unavailability

    u = estimated_unavailability(design["rbd"], t_sim, design["overrides"])
    return u if u is not None else float("nan")


def _cost_difference(a: dict, b: dict, ca: np.ndarray, cb: np.ndarray, paired: bool,
                     z: float) -> dict:
    """The difference in the window's cost (B − A), from the same simulations
    as the availability (so paired by common random numbers when they are),
    and the exact long-run cost-rate difference when both rates are exact.
    ``b_higher`` means design B costs more."""
    est, se = _difference(ca, cb, paired)
    half = z * se if np.isfinite(se) else None
    lower = est - half if half is not None else None
    upper = est + half if half is not None else None
    if lower is not None and lower > 0:
        verdict = "b_higher"
    elif upper is not None and upper < 0:
        verdict = "a_higher"
    else:
        verdict = "no_detectable_difference"
    exact = None
    if a["cost_rate"] is not None and b["cost_rate"] is not None:
        exact = b["cost_rate"] - a["cost_rate"]
    return {
        "estimate": ra._f(est),
        "lower": ra._f(lower),
        "upper": ra._f(upper),
        "standard_error": ra._f(se),
        "half_width": ra._f(half),
        "confidence": ra._AVAIL_CONFIDENCE,
        "tolerance": None,
        "reached": None,
        "verdict": verdict,
        # Per unit time (the simulated difference is a total over the window).
        "exact": ra._f(exact) if exact is not None else None,
        "exact_kind": "rate",
    }


def compare_graphs(db, graph_a: dict, graph_b: dict, owners_a, owners_b,
                   t_simulation: Optional[float] = None) -> dict:
    """:func:`compare_availability` with each diagram's saved-model references
    resolved in its own scope (as :func:`backend.services.rbds.analyze_graph`
    resolves them)."""
    from backend.services import models as models_service

    def resolver(owners):
        return lambda model_id: models_service.get_live_model(db, model_id, owners)

    return compare_availability(
        graph_a, graph_b, resolver(owners_a), resolver(owners_b), t_simulation=t_simulation,
    )
