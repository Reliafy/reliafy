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
difference in what owning each for the window from new costs, purchases
included (#321, RePyability 0.13's ``compare(quantity="cost")``, its #234),
with the exact long-run cost-rate difference alongside where RePyability has
it. The run stops on the availability target; the cost interval shows the
precision it reached.

Since RePyability 0.13 ``compare`` is exact where both designs have exact
values over the window (``mission_availability``, ``expected_cost``; its
#236): the difference then has no simulation noise at all, and nothing is
simulated (#321). A quantity with no exact route for either design is
simulated as above; one that has is exact even when the other is simulated.
``compare`` takes no pinned blocks, so with pins the exact difference is the
designs' own ``mission_availability`` / ``expected_cost`` with the pins held,
which is what ``compare`` works out without them.
"""

from __future__ import annotations

import time
import warnings
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
    overrides = {"working_nodes": working, "broken_nodes": broken}
    try:
        with np.errstate(all="ignore"):
            steady = float(rbd.mean_availability(**overrides))
    except NotImplementedError:
        steady = None  # timed proof tests (or repairs): simulated only
    except Exception as exc:  # noqa: BLE001
        raise AnalysisError(f"Couldn't compute availability: {exc}") from exc
    cost_rate = None
    if rbd.has_costs:
        try:
            with np.errstate(all="ignore"):
                cost_rate = float(rbd.expected_cost_rate(**overrides))
        except NotImplementedError:
            cost_rate = None
    acquisition = float(rbd.acquisition_cost)
    return {
        "rbd": rbd,
        "graph": graph,
        "overrides": overrides,
        "steady": steady,
        # Running costs (the paired run's cost samples), and purchases too:
        # what compare(quantity="cost") counts (#321).
        "priced": bool(rbd.has_costs),
        "acquisition": acquisition,
        "owned": bool(rbd.has_costs) or acquisition > 0,
        "cost_rate": cost_rate,
        "blocks": {nid for nid in rbd.components if nid not in gate_ids},
        # Common-cause groups (#226): in the design's figures, or not and why.
        "common_cause": ra.common_cause_status(rbd),
    }


def _key(entropy) -> int:
    """A run's stream entropy, derived as ``RepairableRBD.compare`` derives it
    from a seed (RePyability's ``_streams.entropy_of``): an int seed is
    used as is, a list (``[seed, batch index]``) is first folded into one."""
    from repyability.rbd import _streams

    if not isinstance(entropy, (int, np.integer)):
        entropy = int(np.random.SeedSequence(entropy).generate_state(1, np.uint32)[0])
    return _streams.entropy_of(int(entropy))


def _paired_run(design: dict, t_sim: float, n: int, key: int):
    """``(fractions, costs)``: each simulation's fraction of the window up and
    (for a priced design, else None) its cost, from streams seeded by ``key``
    and named by the block ids (common random numbers). This is
    ``RepairableRBD.compare``'s inner run, but with the diagram's pinned blocks
    and voting gates held as the analysis holds them — ``compare`` itself
    takes no overrides. Since RePyability 0.13 a stream's draws are a function
    of the key, its name, the simulation and the draw alone (counter-based),
    so both designs draw the same uniforms from each stream however their
    runs are laid out. Raises NotImplementedError where a block's draws
    can't be streamed."""
    ov = design["overrides"]
    tally = design["rbd"]._run(
        t_sim, set(ov["working_nodes"]), set(ov["broken_nodes"]), "c", n, False, None,
        entropy=key, common=True,
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
    res = design["rbd"].availability(t_simulation=t_sim, mc_samples=n, method="c", seed=seed,
                                     control_variate=False, conditional=False, **design["overrides"])
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
    exact: bool = True,
) -> dict:
    """Design B against design A: the difference in the window's mean
    availability (B − A) — exact where both designs have exact values over
    the window, else simulated with its confidence interval — and both exact
    long-run availabilities and their difference; with both designs priced,
    the difference in what owning each for the window costs, purchases
    included (#321).

    The window is the longer of the two designs' default horizons unless
    ``t_simulation`` is given. ``n_simulations`` runs exactly that many
    simulations of each instead of running to the precision target, and,
    like ``exact=False`` (``compare``'s ``control_variate=False``), simulates
    every quantity."""
    a = _design(graph_a, resolve_model_a)
    b = _design(graph_b, resolve_model_b)
    t_chosen, capped = ra.chosen_horizon(t_simulation, graph_a, graph_b)
    user_horizon = t_chosen is not None
    t_sim = t_chosen if user_horizon else max(
        ra._availability_horizon(graph_a), ra._availability_horizon(graph_b))
    costed = a["owned"] and b["owned"]
    quantities = ("availability", "cost") if costed else ("availability",)
    # Exact where both designs have exact values over the window (#321): with
    # every compared quantity exact, nothing is simulated.
    simulate_all = bool(n_simulations) or not exact
    exacts = {} if simulate_all else _exact_window(a, b, t_sim, quantities)
    if all(q in exacts for q in quantities):
        return _result(a, b, graph_a, t_sim, capped, exacts, None)
    # Pilot: time paired replications (and learn whether the blocks' draws
    # can be replayed for common random numbers at all). A chosen window is
    # probed with a couple first, and the pilot batch skipped when it alone
    # would overrun the budget.
    paired = True

    def timed(n: int) -> float:
        nonlocal paired
        start = time.perf_counter()
        try:
            _batch(a, b, t_sim, n, _PILOT_BATCH, paired)
        except NotImplementedError:
            if not paired:
                raise
            paired = False
            start = time.perf_counter()
            _batch(a, b, t_sim, n, _PILOT_BATCH, False)
        return max((time.perf_counter() - start) / n, 1e-9)

    per_rep = timed(ra._AVAIL_PROBE_SIMS) if user_horizon else None
    if per_rep is None or per_rep * _PILOT_SIMS <= ra._AVAIL_TIME_BUDGET:
        per_rep = timed(_PILOT_SIMS)

    shortened = capped
    if n_simulations:
        batch = max_n = max(2, int(n_simulations))
    else:
        batch, max_n, t_sim, short = ra._plan_simulation(
            per_rep, ra._AVAIL_SIMS, t_sim, user_horizon)
        shortened = shortened or short
    worse = max(_unavailability(a, t_sim), _unavailability(b, t_sim))
    tolerance = _TOLERANCE_FRACTION * ra._availability_tolerance(worse)
    expect_downtime = bool(np.isfinite(worse) and worse > 0.0)

    z = ra._z(ra._AVAIL_CONFIDENCE)
    fa: list = []
    fb: list = []
    ca: list = []
    cb: list = []
    index = 0
    reached = False
    while len(fa) < max_n:
        n_batch = min(batch, max_n - len(fa))
        (xa, ya), (xb, yb) = _batch_runs(a, b, t_sim, n_batch, index, paired)
        fa.extend(xa)
        fb.extend(xb)
        if costed:
            # A design priced by its purchases alone runs at no cost.
            ca.extend(ya if ya is not None else np.zeros(n_batch))
            cb.extend(yb if yb is not None else np.zeros(n_batch))
        index += 1
        est, se = _difference(np.asarray(fa), np.asarray(fb), paired)
        # Batches that saw no downtime in either design say nothing yet.
        evidence = not expect_downtime or min(min(fa), min(fb)) < 1.0
        reached = bool(np.isfinite(se) and z * se <= tolerance and evidence)
        if reached and not n_simulations:
            break
    fa_arr, fb_arr = np.asarray(fa), np.asarray(fb)
    est, se = _difference(fa_arr, fb_arr, paired)
    simulated = {
        "availability": {
            **_interval(est, se, z),
            "tolerance": tolerance,
            "reached": reached,
            "values": (ra._f(np.mean(fa_arr)), ra._f(np.mean(fb_arr))),
        },
    }
    if costed:
        simulated["cost"] = _cost_simulated(a, b, np.asarray(ca), np.asarray(cb), paired, z)
    # The quantities with an exact route at the window run (shortened or not)
    # are exact; the simulation stands for the rest.
    exacts = {} if simulate_all else _exact_window(a, b, t_sim, quantities)
    run = {
        "simulated": simulated,
        "n_simulations": len(fa),
        "max_simulations": None if n_simulations else max_n,
        "common_random_numbers": paired,
        "shortened": shortened,
    }
    return _result(a, b, graph_a, t_sim, capped, exacts, run)


def _interval(est: float, se: float, z: float) -> dict:
    """A simulated difference (B − A) with its interval and verdict."""
    half = z * se if np.isfinite(se) else None
    lower = est - half if half is not None else None
    upper = est + half if half is not None else None
    if lower is not None and lower > 0:
        verdict = "b_higher"
    elif upper is not None and upper < 0:
        verdict = "a_higher"
    else:
        verdict = "no_detectable_difference"
    return {
        "estimate": ra._f(est),
        "lower": ra._f(lower),
        "upper": ra._f(upper),
        "standard_error": ra._f(se),
        "half_width": ra._f(half),
        "confidence": ra._AVAIL_CONFIDENCE,
        "verdict": verdict,
        "method": "simulated",
    }


def _exact_interval(est: float) -> dict:
    """An exact difference (B − A): no interval, no noise."""
    verdict = "b_higher" if est > 0 else "a_higher" if est < 0 else "no_detectable_difference"
    return {
        "estimate": ra._f(est), "lower": ra._f(est), "upper": ra._f(est), "standard_error": 0.0,
        "half_width": 0.0, "confidence": ra._AVAIL_CONFIDENCE, "verdict": verdict, "method": "exact",
        "tolerance": None, "reached": True,
    }


def _held(design: dict) -> bool:
    ov = design["overrides"]
    return bool(ov["working_nodes"] or ov["broken_nodes"])


def _exact_window(a: dict, b: dict, t_sim: float, quantities) -> dict:
    """``{quantity: {"difference", "values": (A, B), "route"}}`` for each of
    ``quantities`` both designs have exact (or numerical) values of over the
    window from new: RePyability's ``compare`` (exact by default since 0.13),
    with each design's own value beside it (``mission_availability``, and
    the purchases plus ``expected_cost``: what ``compare(quantity="cost")``
    counts). With pinned blocks, which ``compare`` doesn't take, the
    difference is those values' (``compare``'s own exact route). Not above
    :data:`rbd_analysis.EXACT_WINDOW_MEAN_MAX_BLOCKS` blocks, as for an
    availability result's window."""
    if not (ra.window_mean_exact_ok(a["graph"]) and ra.window_mean_exact_ok(b["graph"])):
        return {}
    routes = [ra.window_routes(d["rbd"]) for d in (a, b)]
    out: dict = {}
    for q in quantities:
        key = "mission_availability" if q == "availability" else "expected_cost"
        needs = [d["priced"] for d in (a, b)] if q == "cost" else [True, True]
        if any(need and r[key] not in ra._OVER_TIME_OK for need, r in zip(needs, routes)):
            continue
        try:
            with warnings.catch_warnings(), np.errstate(all="ignore"):
                warnings.simplefilter("ignore", RuntimeWarning)
                values = tuple(_window_value(d, t_sim, q) for d in (a, b))
                difference = None
                if not (_held(a) or _held(b)):
                    # B − A by the library itself; two simulations at most
                    # should it ever find no exact route after all.
                    got = b["rbd"].compare(a["rbd"], float(t_sim), mc_samples=2, seed=0, quantity=q)
                    if got.method != "exact":
                        continue
                    difference = float(got.estimate)
        except (NotImplementedError, ValueError):
            continue
        if difference is None:
            difference = values[1] - values[0]
        route = "numerical" if "numerical" in (routes[0][key], routes[1][key]) else "exact"
        out[q] = {"difference": difference, "values": values, "route": route}
    return out


def _window_value(design: dict, t_sim: float, quantity: str) -> float:
    """A design's exact value over the window from new: its mission
    availability, or what owning it costs (purchases plus the expected
    running cost)."""
    rbd, ov = design["rbd"], design["overrides"]
    if quantity == "availability":
        return float(rbd.mission_availability(float(t_sim), **ov))
    running = float(rbd.expected_cost(float(t_sim), **ov).mean) if design["priced"] else 0.0
    return running + design["acquisition"]


def _result(a: dict, b: dict, graph_a: dict, t_sim: float, capped: bool, exact: dict,
            run: Optional[dict]) -> dict:
    """The comparison: each quantity exact where :func:`_exact_window` found
    it, else from the paired simulation ``run`` (None: nothing simulated)."""
    sims = (run or {}).get("simulated") or {}
    costed = a["owned"] and b["owned"]
    differences: dict = {}
    windows: dict = {}
    for q in ("availability", "cost") if costed else ("availability",):
        if q in exact:
            differences[q] = {**_exact_interval(exact[q]["difference"]), "route": exact[q]["route"]}
            windows[q] = exact[q]["values"]
        else:
            sim = dict(sims[q])
            windows[q] = sim.pop("values")
            differences[q] = sim
    exact_a, exact_b = ra._f(a["steady"]), ra._f(b["steady"])
    # The long-run difference (B − A), beside the window's.
    differences["availability"]["exact"] = (exact_b - exact_a) if exact_a is not None and exact_b is not None \
        else None
    if costed:
        cost = differences["cost"]
        # Per unit time (the window's difference is a total over it).
        cost["exact"] = (ra._f(b["cost_rate"] - a["cost_rate"])
                         if a["cost_rate"] is not None and b["cost_rate"] is not None else None)
        cost["exact_kind"] = "rate"
        cost["includes_acquisition"] = True
        cost["acquisition"] = b["acquisition"] - a["acquisition"]
        if cost.get("estimate") is not None:
            cost["running"] = ra._f(cost["estimate"] - cost["acquisition"])
        cost.setdefault("tolerance", None)
        cost.setdefault("reached", None)
    cost_note = None
    if a["owned"] != b["owned"]:
        cost_note = (f"Only design {'A' if a['owned'] else 'B'} is priced, so costs aren't "
                     "compared — give both designs costs to compare them.")
    simulated_any = run is not None and any(d.get("method") == "simulated" for d in differences.values())
    designs = {}
    for key, design, i in (("a", a, 0), ("b", b, 1)):
        exact_value = exact_a if key == "a" else exact_b
        row = {
            "steady_state_availability": exact_value,
            "unavailability": (1.0 - exact_value) if exact_value is not None else None,
            "window_availability": ra._f(windows["availability"][i]),
            "window_availability_basis": differences["availability"].get("route", "simulation")
            if differences["availability"]["method"] == "exact" else "simulation",
            "priced": design["owned"],
            "cost_rate": ra._f(design["cost_rate"]) if design["cost_rate"] is not None else None,
            "acquisition_cost": design["acquisition"],
            # Owning it for the window from new: purchases and running costs.
            "window_cost": ra._f(windows["cost"][i]) if costed and windows["cost"][i] is not None else None,
            **({"common_cause_included": design["common_cause"]["included"],
                "common_cause_reason": design["common_cause"]["reason"]}
               if design["common_cause"] is not None else {}),
        }
        if costed and row["window_cost"] is not None:
            row["window_running_cost"] = ra._f(row["window_cost"] - design["acquisition"])
        designs[key] = row
    return {
        "kind": "repairable_comparison",
        "unit": (graph_a.get("unit") or "").strip(),
        "t_simulation": float(t_sim),
        "horizon_shortened": bool(capped or (run or {}).get("shortened")),
        "method": "simulated" if simulated_any else "exact",
        "designs": designs,
        "differences": differences,
        "cost_note": cost_note,
        "n_simulations": (run or {}).get("n_simulations", 0) if simulated_any else 0,
        "max_simulations": (run or {}).get("max_simulations") if simulated_any else None,
        "common_random_numbers": (run or {}).get("common_random_numbers", True) if simulated_any else None,
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


def _cost_simulated(a: dict, b: dict, ca: np.ndarray, cb: np.ndarray, paired: bool, z: float) -> dict:
    """The simulated difference (B − A) in what owning each design for the
    window costs — its running cost from the same simulations as the
    availability (so paired by common random numbers when they are) plus its
    purchases, as ``compare(quantity="cost")`` counts it (#321). ``b_higher``
    means design B costs more."""
    oa, ob = ca + a["acquisition"], cb + b["acquisition"]
    est, se = _difference(oa, ob, paired)
    return {**_interval(est, se, z), "values": (ra._f(np.mean(oa)), ra._f(np.mean(ob)))}


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
