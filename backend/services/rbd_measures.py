"""What to improve, the other measures (#225): RePyability's sensitivity
measures beyond the ranked lever steps (:mod:`backend.services.rbd_sensitivity`),
each answering one plain question about a repairable diagram.

* ``over_time`` — "Which blocks matter most, and when?": each block's Birnbaum
  importance over time from new (``birnbaum_importance(x=...)``, the delta of
  RePyability's Greeks), and in the long run.
* ``shares`` — "Where would an all-round improvement pay off?": the shares of
  the gain from improving every lever by the same fraction
  (``differential_importance(over="parameters", change="proportional",
  improving=True, groups=...)``), grouped by block or by kind of lever.
* ``joint`` — "Which blocks are worth improving together?": each pair's joint
  importance (``joint_importance``, gamma): complements (improving one makes
  the other worth more) and substitutes.
* ``rate`` — "What's moving availability now?": each block's part in how fast
  the availability is changing at each time (``availability_rate``, theta),
  and its share of the system's failures (``barlow_proschan_importance``).
* ``uncertainty`` — "Whose uncertainty widens the answer?": the long-run
  availability over draws of the fitted models (``mean_availability_
  uncertainty``) and each uncertain input's share of its variance
  (``uncertainty_importance``, vega): the delta method (free, quick) or the
  Sobol indices from draws (``method="sobol"``, Pro). With ``times`` (#325),
  the availability at several times and the mean over ``[0, t]`` for each,
  with their intervals, from one run (``point_availability_uncertainty`` and
  ``mission_availability_uncertainty`` with array targets), Pro.

The diagram is built exactly as the availability analysis builds it (pinned
blocks held, common-cause groups in wherever RePyability takes them). A
measure RePyability refuses for this diagram (its route ``refused``) comes
back with ``status: "refused"`` and RePyability's reason, never approximated.

The uncertain inputs are the blocks whose life (or repair) is a saved model
fitted by maximum likelihood, whose parameters are still the fit's: the
diagram is rebuilt with each such model carrying its fit's parameter
covariance (``hess_inv``), one model object per saved model, so blocks
sharing a saved model are drawn together (RePyability's populations).
Everything else stays fixed, and the result says why. The covariances travel
with a compute request (``fits``), as the compute service has no database.
"""

from __future__ import annotations

import math
import time
import warnings
from typing import Any, Optional

import numpy as np

from backend.services import rbd_analysis as ra
from backend.services.method_labels import route_reason
from backend.services.rbd_analysis import AnalysisError
from backend.units import unit_in_text

MEASURES = ("over_time", "shares", "joint", "rate", "uncertainty")
#: The plain question each measure answers (its tab's title).
QUESTIONS = {
    "levers": "Which change gains most?",
    "over_time": "Which blocks matter most, and when?",
    "shares": "Where would an all-round improvement pay off?",
    "joint": "Which blocks are worth improving together?",
    "rate": "What's moving availability now?",
    "uncertainty": "Whose uncertainty widens the answer?",
}
GROUP_BY = ("block", "kind")
METHODS = ("delta", "sobol")
#: Points of a curve over time: even, plus log-spaced ones near the start.
CURVE_POINTS = 61
EARLY_POINTS = 20
#: The most blocks a measure is worked out for here (the exact figures' limit).
MAX_BLOCKS = ra.EXACT_MAX_BLOCKS
#: Over time, numerically: as the window's figures.
TIMED_MAX_BLOCKS = ra.EXACT_WINDOW_MEAN_MAX_BLOCKS
#: The uncertainty's draws: the long run (one exact value a draw, quick), over
#: time (one numerical curve a draw: about 85 s for 1000 draws of 5 blocks on a
#: laptop, so fewer), and each Sobol set.
N_DRAWS = 1000
N_DRAWS_OVER_TIME = 200
N_DRAWS_SOBOL = 500
MAX_TIMES = 6
LEVEL = 0.95
SEED = 20261
#: Uncertain inputs above which a Sobol run is refused (n_draws × (inputs + 2)
#: evaluations).
SOBOL_MAX_INPUTS = 12
#: Where a run is heavy enough to be Pro (and a compute job): Sobol indices,
#: or the availability over time over draws.
HEAVY = "heavy"

_KINDS = (
    ("reliability.", "Lives"),
    ("repairability.", "Repair times"),
    ("preventive.", "Scheduled replacement"),
    ("inspection.", "Proof tests"),
    ("standby.", "Standby"),
    ("repair.", "Repair quality"),
    ("ccf_", "Common cause"),
)

_ROLES = {"model": "reliability", "repair": "repairability"}
_ROLE_WORDS = {"reliability": "life", "repairability": "repair time"}


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------
def _times(raw) -> Optional[list]:
    if raw in (None, "", []):
        return None
    if not isinstance(raw, (list, tuple)):
        raise AnalysisError("times must be a list of times in the diagram's unit.")
    out = []
    for v in raw:
        if isinstance(v, bool):
            raise AnalysisError("times must be numbers.")
        try:
            x = float(v)
        except (TypeError, ValueError):
            raise AnalysisError("times must be numbers.") from None
        if not (math.isfinite(x) and x > 0):
            raise AnalysisError("times must be positive times in the diagram's unit.")
        out.append(x)
    out = sorted(set(out))
    if len(out) > MAX_TIMES:
        raise AnalysisError(f"Give at most {MAX_TIMES} times.")
    return out


def options(measure=None, window=None, group_by=None, method=None, times=None, level=None) -> dict:
    """The validated options of a measures request (plain JSON)."""
    if measure not in MEASURES:
        raise AnalysisError("measure must be one of " + ", ".join(MEASURES) + ".")
    out: dict[str, Any] = {"measure": measure}
    if window not in (None, ""):
        if isinstance(window, bool):
            raise AnalysisError("window must be a time in the diagram's unit.")
        try:
            w = float(window)
        except (TypeError, ValueError):
            raise AnalysisError("window must be a time in the diagram's unit.") from None
        if not (math.isfinite(w) and w > 0):
            raise AnalysisError("window must be a positive time in the diagram's unit.")
        out["window"] = w
    if measure == "shares":
        g = group_by or "block"
        if g not in GROUP_BY:
            raise AnalysisError("group_by must be 'block' or 'kind'.")
        out["group_by"] = g
    if measure == "uncertainty":
        m = method or "delta"
        if m not in METHODS:
            raise AnalysisError("method must be 'delta' or 'sobol'.")
        out["method"] = m
        ts = _times(times)
        if ts:
            out["times"] = ts
        if level not in (None, ""):
            try:
                lv = float(level)
            except (TypeError, ValueError):
                raise AnalysisError("level must be a confidence level such as 0.95.") from None
            if not 0.5 <= lv < 1.0:
                raise AnalysisError("The confidence level must be from 50% up to (not including) 100%.")
            out["level"] = lv
    return out


def heavy(opts: dict) -> bool:
    """Whether a request is a heavy one: Pro (or credits), run as a compute
    job — the Sobol indices, or the uncertainty over time."""
    return opts.get("measure") == "uncertainty" and (opts.get("method") == "sobol" or bool(opts.get("times")))


# ---------------------------------------------------------------------------
# Building
# ---------------------------------------------------------------------------
def _build(graph: dict, resolve_model):
    ra.require_blocks(graph)
    if not (graph or {}).get("repairable"):
        raise AnalysisError("These measures are for repairable (availability) diagrams.")
    n_blocks = ra.count_blocks(graph)
    if n_blocks > MAX_BLOCKS:
        raise AnalysisError(f"This diagram has {n_blocks} blocks; these measures are worked out here for up to "
                            f"{MAX_BLOCKS}. Download it as Python to run RePyability's measures locally.")
    rbd, labels, gate_ids, working, broken = ra._build_repairable_rbd(graph, resolve_model)
    return rbd, labels, set(gate_ids), set(working), set(broken), n_blocks


def _name(key, labels: dict) -> str:
    if key is None:
        return "System"
    if isinstance(key, tuple):
        return " & ".join(str(labels.get(k, k)) for k in key)
    return str(labels.get(key, key))


def _route(rbd, name: str) -> tuple[str, str]:
    try:
        r = rbd.analysis_routes()[name]
        return r.route, route_reason(r)
    except Exception:  # noqa: BLE001
        return "refused", ""


def _refused(head: dict, name: str, reason: str, labels: dict) -> dict:
    return {**head, "status": "refused", "basis": "refused",
            "message": ra._with_labels(reason or f"RePyability has no {name} for this diagram.", labels)}


def _num(v) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _series(values) -> list:
    return [_num(v) for v in np.asarray(values, dtype=float).reshape(-1)]


def _horizon(graph: dict, window: Optional[float]) -> float:
    return float(window) if window else float(ra._availability_horizon(graph))


def _grid(horizon: float) -> np.ndarray:
    """Times over ``[0, horizon]``: even, with more near the start, where a
    diagram's availability moves most."""
    early = np.geomspace(horizon * 1e-4, horizon * 0.05, EARLY_POINTS)
    return np.unique(np.concatenate([np.linspace(0.0, horizon, CURVE_POINTS), early]))


def _pct(v: float, digits: int = 2) -> str:
    return f"{float(np.format_float_positional(v * 100, precision=digits, unique=False, fractional=False, trim='-')):g}%"


def _pct_pair(lo: float, hi: float) -> tuple[str, str]:
    """Two fractions as percentages to enough decimals to tell them apart."""
    spread = abs(hi - lo) * 100
    d = 1 if spread <= 0 else min(6, max(1, math.ceil(-math.log10(spread)) + 1))
    return f"{lo * 100:.{d}f}%", f"{hi * 100:.{d}f}%"


def _time_words(t: float, unit: str) -> str:
    r = float(f"{t:.3g}")
    text = f"{r:,.0f}" if abs(r) >= 1000 else f"{r:g}"
    u = unit_in_text(unit)
    return f"{text} {u}" if u else text


# ---------------------------------------------------------------------------
# The analysis
# ---------------------------------------------------------------------------
def analyze_measure(graph: dict, resolve_model=None, *, measure: str, window: Optional[float] = None,
                    group_by: Optional[str] = None, method: Optional[str] = None, times=None,
                    level: Optional[float] = None, fits: Optional[dict] = None,
                    fixed: Optional[list] = None) -> dict:
    """One measure of a repairable diagram (see the module docstring), as a
    JSON-able payload with ``status`` "ok" (or "refused", "no_uncertainty"),
    the measure's figures, a plain ``answer`` and its ``question``.
    ``fits`` ({model id: {distribution_id, params, hess_inv, extras}}) are
    the saved models' fits for ``uncertainty`` and ``fixed`` the blocks that
    stay fixed (see :func:`fits_for`, which a compute request carries them
    from); without them they're looked up with ``resolve_model``."""
    started = time.perf_counter()
    opts = options(measure=measure, window=window, group_by=group_by, method=method, times=times, level=level)
    rbd, labels, gates, working, broken, n_blocks = _build(graph, resolve_model)
    unit = (graph.get("unit") or "").strip()
    head = {
        "kind": "measure",
        "measure": measure,
        "question": QUESTIONS[measure],
        "unit": unit,
        "n_blocks": n_blocks,
        "window": opts.get("window"),
        "pinned": sorted(labels.get(n, str(n)) for n in working | broken),
        "repyability_version": ra._repyability_version(),
    }
    common = ra.common_cause_status(rbd)
    notes = []
    if common is not None and not common["included"]:
        notes.append(ra.common_cause_left_out(common["groups"], common["reason"]))
    ctx = dict(rbd=rbd, labels=labels, gates=gates, working=working, broken=broken, unit=unit, graph=graph)
    runner = {"over_time": _over_time, "shares": _shares, "joint": _joint, "rate": _rate}.get(measure)
    with np.errstate(all="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        try:
            if runner is not None:
                out = runner(head, opts, **ctx)
            else:
                out = _uncertainty(head, opts, resolve_model, fits, fixed, **ctx)
        except NotImplementedError as exc:
            out = _refused(head, measure, ra._component_message(str(exc), labels), labels)
        except AnalysisError:
            raise
        except ValueError as exc:
            raise AnalysisError(ra._component_message(str(exc), labels)) from exc
    out["notes"] = notes + out.get("notes", [])
    out["compute_seconds"] = time.perf_counter() - started
    return out


def _blocks(rbd, gates: set) -> list:
    """The diagram's blocks (not its junctions), in its order."""
    return [n for n in rbd.components if n not in gates]


# -- Which blocks matter most, and when? (delta over time) --------------------
def _over_time(head, opts, *, rbd, labels, gates, working, broken, unit, graph) -> dict:
    route, reason = _route(rbd, "birnbaum_importance")
    if route == "refused":
        return _refused(head, "importance over time", reason, labels)
    if ra.count_blocks(graph) > TIMED_MAX_BLOCKS:
        return {**head, "status": "too_large", "message": (
            f"Over time these are worked out here for up to {TIMED_MAX_BLOCKS} blocks.")}
    horizon = _horizon(graph, opts.get("window"))
    grid = _grid(horizon)
    held = {"working_nodes": sorted(working, key=str), "broken_nodes": sorted(broken, key=str)}
    over = rbd.birnbaum_importance(**held, x=grid)
    steady = rbd.birnbaum_importance(**held)
    blocks = [n for n in _blocks(rbd, gates) if n in over and n not in working | broken]
    series = []
    for n in blocks:
        values = np.asarray(over[n], dtype=float)
        series.append({"id": str(n), "label": _name(n, labels), "values": _series(values),
                       "long_run": _num(steady.get(n))})
    series.sort(key=lambda s: -(s["long_run"] or 0.0))
    # Who leads when: the block with the highest importance at each time.
    leaders = []
    if series:
        stack = np.array([[v if v is not None else -np.inf for v in s["values"]] for s in series])
        top = np.argmax(stack, axis=0)
        for i, idx in enumerate(top):
            if not leaders or leaders[-1]["id"] != series[idx]["id"]:
                leaders.append({"id": series[idx]["id"], "label": series[idx]["label"], "from": float(grid[i])})
    out = {**head, "status": "ok", "basis": route, "basis_reason": ra._with_labels(reason, labels),
           "time": _series(grid), "series": series, "leaders": leaders}
    out["answer"] = _over_time_answer(out, unit)
    return out


def _over_time_answer(out: dict, unit: str) -> str:
    series, leaders = out["series"], out["leaders"]
    if not series:
        return "No block can be ranked: they're all pinned."
    best = series[0]
    lead = (f"In the long run {best['label']} matters most: it is critical (the system works only while it does) "
            f"{_pct(best['long_run'] or 0.0, 3)} of the time.")
    later = [ld for ld in leaders if ld["from"] > 0]
    if leaders and leaders[0]["id"] != best["id"]:
        return f"{leaders[0]['label']} matters most at first; " + (
            f"from about {_time_words(later[-1]['from'], unit)}, {leaders[-1]['label']}. " if later else "") + lead
    return lead


# -- Where would an all-round improvement pay off? (DIM) -----------------------
def _kind(lever_name: str) -> str:
    for prefix, word in _KINDS:
        if lever_name.startswith(prefix):
            return word
    return "Other"


def _shares(head, opts, *, rbd, labels, gates, working, broken, unit, graph) -> dict:
    route, reason = _route(rbd, "differential_importance")
    if route == "refused":
        return _refused(head, "shares of a change", reason, labels)
    from backend.services.rbd_sensitivity import _Lever

    held = set(working) | set(broken) | gates
    groups: dict[str, list] = {}
    levers = []
    for lever in rbd.levers():
        if lever.discrete or lever.key is None:
            continue  # one more crew or unit is no derivative: it takes no part
        members = set(lever.key) if isinstance(lever.key, tuple) else {lever.key}
        if members & held:
            continue
        name = _name(lever.key, labels) if opts["group_by"] == "block" else _kind(lever.name)
        groups.setdefault(name, []).append((lever.key, lever.name))
        levers.append(lever)
    if not groups:
        return {**head, "status": "ok", "basis": route, "group_by": opts["group_by"], "shares": [],
                "answer": "No lever can move: every block is pinned."}
    kw = {"window": opts["window"]} if opts.get("window") else {}
    shares = rbd.differential_importance(sorted(working, key=str), sorted(broken, key=str), over="parameters",
                                         change="proportional", improving=True, groups=groups, **kw)
    rows = [{"group": g, "share": _num(v), "levers": len(groups[g])} for g, v in shares.items()]
    if all(r["share"] is None for r in rows):
        return {**head, "status": "refused", "basis": route,
                "message": "There's nothing to share out: improving every lever together changes nothing here."}
    rows.sort(key=lambda r: -(r["share"] or 0.0))
    # The levers' own shares, for Details (plain names, as the ranked steps).
    singles = rbd.differential_importance(sorted(working, key=str), sorted(broken, key=str), over="parameters",
                                          change="proportional", improving=True, **kw)
    detail = []
    for lever in levers:
        lv = _Lever(rbd, lever, labels, unit)
        detail.append({"block": lv.block, "name": lv.label, "share": _num(singles.get((lever.key, lever.name)))})
    detail.sort(key=lambda r: -(r["share"] or 0.0))
    out = {**head, "status": "ok", "basis": route, "basis_reason": ra._with_labels(reason, labels),
           "group_by": opts["group_by"], "shares": rows, "levers": detail}
    top = rows[0]
    what = "in " + top["group"].lower() if opts["group_by"] == "kind" else "in " + top["group"] + "'s levers"
    span = "over the window" if opts.get("window") else "in the long run"
    out["answer"] = (f"Improve every lever by the same small fraction and {_pct(top['share'] or 0.0, 2)} of the "
                     f"gain {span} lies {what}"
                     + (f"; {_pct(rows[1]['share'] or 0.0, 2)} in "
                        + (rows[1]["group"].lower() if opts["group_by"] == "kind" else rows[1]["group"] + "'s")
                        if len(rows) > 1 and (rows[1]["share"] or 0) > 0 else "") + ".")
    return out


# -- Which blocks are worth improving together? (gamma) ------------------------
def _joint(head, opts, *, rbd, labels, gates, working, broken, unit, graph) -> dict:
    route, reason = _route(rbd, "joint_importance")
    if route == "refused":
        return _refused(head, "joint importance", reason, labels)
    kw = {"window": opts["window"]} if opts.get("window") else {}
    pairs = rbd.joint_importance(sorted(working, key=str), sorted(broken, key=str), **kw)
    held = set(working) | set(broken) | gates
    rows = []
    for (a, b), v in pairs.items():
        if a in held or b in held:
            continue
        x = _num(v)
        if x is None:
            continue
        rows.append({"a": str(a), "b": str(b), "label": f"{_name(a, labels)} & {_name(b, labels)}",
                     "value": x, "kind": "complements" if x > 0 else "substitutes" if x < 0 else "independent"})
    rows.sort(key=lambda r: -abs(r["value"]))
    out = {**head, "status": "ok", "basis": route, "basis_reason": ra._with_labels(reason, labels), "pairs": rows}
    comp = next((r for r in rows if r["kind"] == "complements"), None)
    sub = next((r for r in rows if r["kind"] == "substitutes"), None)
    parts = []
    if comp:
        parts.append(f"{comp['label']} are complements ({comp['value']:+.2f}): improving one makes improving the "
                     "other worth more, as in series")
    if sub:
        parts.append(f"{sub['label']} are substitutes ({sub['value']:+.2f}): improving one makes the other matter "
                     "less, as redundant units")
    out["answer"] = ("; ".join(parts) + ".") if parts else "No pair of blocks moves the other's importance."
    return out


# -- What's moving availability now? (theta, Barlow–Proschan) -----------------
def _rate(head, opts, *, rbd, labels, gates, working, broken, unit, graph) -> dict:
    route, reason = _route(rbd, "availability_rate")
    if route == "refused":
        return _refused(head, "availability rate", reason, labels)
    if ra.count_blocks(graph) > TIMED_MAX_BLOCKS:
        return {**head, "status": "too_large", "message": (
            f"Over time these are worked out here for up to {TIMED_MAX_BLOCKS} blocks.")}
    horizon = _horizon(graph, opts.get("window"))
    grid = _grid(horizon)
    held = {"working_nodes": sorted(working, key=str), "broken_nodes": sorted(broken, key=str)}
    br = rbd.availability_rate(grid, **held)
    series = []
    for key, values in br.node_rate.items():
        if key in gates:
            continue
        vals = np.asarray(values, dtype=float)
        series.append({"id": "+".join(map(str, key)) if isinstance(key, tuple) else str(key),
                       "label": _name(key, labels), "values": _series(vals)})
    jumps = []
    for i, t in enumerate(np.asarray(br.jump_times, dtype=float).reshape(-1)):
        parts = {}
        for key, values in br.node_jumps.items():
            v = _num(np.asarray(values, dtype=float).reshape(-1)[i])
            if v:
                parts[_name(key, labels)] = v
        jumps.append({"t": float(t), "jump": _num(np.asarray(br.jumps).reshape(-1)[i]), "parts": parts})
    bp_route, bp_reason = _route(rbd, "barlow_proschan_importance")
    causes, causes_window = [], []
    if bp_route != "refused":
        for target, kw in ((causes, {}), (causes_window, {"window": horizon})):
            try:
                shares = rbd.barlow_proschan_importance(**held, **kw)
            except NotImplementedError:
                continue
            for key, v in shares.items():
                if key in gates or _num(v) is None:
                    continue
                target.append({"id": "+".join(map(str, key)) if isinstance(key, tuple) else str(key),
                               "label": _name(key, labels), "share": _num(v)})
            target.sort(key=lambda r: -(r["share"] or 0.0))
    # Where the availability falls fastest, and who pulls it down then; and
    # whether it is still moving at the end of the window.
    rate = np.nan_to_num(np.asarray(br.rate, dtype=float).reshape(-1))
    scale = float(np.max(np.abs(rate))) if rate.size else 0.0
    steepest = int(np.argmin(rate)) if rate.size else 0
    end = len(grid) - 1

    def most_down(i):
        parts = sorted(((s["values"][i] or 0.0, s["label"]) for s in series), key=lambda p: p[0])
        return parts[0] if parts and parts[0][0] < 0 else None
    out = {**head, "status": "ok", "basis": route, "basis_reason": ra._with_labels(reason, labels),
           "time": _series(grid), "horizon": horizon, "rate": _series(br.rate), "series": series,
           "jumps": jumps[:50], "causes": causes, "causes_window": causes_window,
           "causes_basis": bp_route if bp_route != "refused" else None,
           "causes_note": None if bp_route != "refused" else ra._with_labels(bp_reason, labels)}
    fall = most_down(steepest) if scale > 0 and rate[steepest] < 0 else None
    out["fastest_fall"] = ({"t": float(grid[steepest]), "rate": float(rate[steepest]), "label": fall[1]}
                           if fall else None)
    still = most_down(end) if scale > 0 and abs(rate[end]) > 1e-3 * scale else None
    out["pulling_down"] = {"t": float(grid[end]), "label": still[1], "rate": still[0]} if still else None
    out["answer"] = _rate_answer(out, unit)
    return out


def _rate_answer(out: dict, unit: str) -> str:
    causes = out["causes"]
    parts = []
    if causes:
        top = causes[0]
        parts.append(f"{top['label']} causes {_pct(top['share'] or 0.0)} of the system's failures in the long run")
    fall, pull = out.get("fastest_fall"), out.get("pulling_down")
    if fall:
        when = "from new" if fall["t"] == 0 else f"at {_time_words(fall['t'], unit)}"
        parts.append(f"availability falls fastest {when}, pulled down most by {fall['label']}")
    if pull:
        parts.append(f"at {_time_words(pull['t'], unit)} {pull['label']} is still pulling it down most")
    else:
        parts.append(f"by {_time_words(out['horizon'], unit)} it has settled")
    text = "; ".join(parts) + "."
    return text[0].upper() + text[1:]


# -- Whose uncertainty widens the answer? (vega) -------------------------------
def fits_for(graph: dict, resolve_model) -> tuple[dict, list]:
    """The saved models' fits the diagram's blocks use, still matching the
    blocks' parameters: ``({model id: {distribution_id, params, hess_inv,
    extras}}, fixed)``, ``fixed`` the blocks that stay fixed and why."""
    from backend.services import rbd_uncertainty as ru

    fits: dict = {}
    fixed: list = []
    seen: dict = {}
    for node in graph.get("nodes") or []:
        if node.get("type") not in ("component", "standby"):
            continue
        data = node.get("data") or {}
        label = data.get("label") or node.get("id")
        if data.get("state") in ("working", "failed"):
            continue
        reasons = []
        uncertain = False
        for slot in ("model", "repair"):
            model = data.get(slot)
            if not isinstance(model, dict):
                continue
            mid = ru._saved_id(model)
            if model.get("kind") in ("regression", "nonparametric"):
                reasons.append(ru._REGRESSION if model.get("kind") == "regression" else ru._NONPARAMETRIC)
                continue
            if mid is None:
                reasons.append(ru._HAND_ENTERED)
                continue
            if node.get("type") == "standby":
                reasons.append("standby group — kept at its fitted model")
                continue
            if mid not in seen:
                seen[mid] = _fit_of(mid, resolve_model)
            got = seen[mid]
            if isinstance(got, str):
                reasons.append(got)
            elif not ru._matches(model, got["live"]):
                reasons.append(ru._STALE)
            else:
                fits[mid] = got["fit"]
                uncertain = True
        if not uncertain:
            fixed.append({"id": node.get("id"), "label": label, "reason": reasons[0] if reasons else ru._HAND_ENTERED})
    return fits, fixed


def _fit_of(model_id: str, resolve_model):
    from backend.services import rbd_uncertainty as ru

    if resolve_model is None:
        return ru._UNREADABLE
    try:
        entry = resolve_model(model_id)
    except Exception:  # noqa: BLE001 - a refit that fails leaves it fixed
        entry = None
    live = (entry or {}).get("model")
    if live is None or not hasattr(getattr(live, "dist", None), "from_params"):
        return ru._UNREADABLE
    cov = getattr(live, "hess_inv", None)
    if cov is None:
        return "no parameter covariance (not a maximum-likelihood fit)"
    cov = np.atleast_2d(np.asarray(cov, dtype=float))
    params = np.atleast_1d(np.asarray(live.params, dtype=float))
    if cov.shape != (len(params), len(params)) or not np.all(np.isfinite(cov)):
        return "its fit's parameter covariance doesn't match its parameters"
    return {"live": live, "fit": {"params": [float(v) for v in params], "hess_inv": cov.tolist()}}


def _with_fits(rbd, graph: dict, fits: dict, labels: dict) -> tuple[Any, list, list]:
    """The diagram rebuilt with each fitted block's life (or repair) the
    saved model with its fit's covariance — one object per saved model, so
    the blocks sharing it are one population — and the inputs:
    ``(rbd, uncertainty, inputs)``, ``uncertainty`` RePyability's
    ``{node or tuple: {role: "fit"}}`` and ``inputs`` their plain names."""
    from repyability import RepairableRBD
    from repyability.rbd.uncertainty import is_fit

    from backend.fitting import DISTRIBUTIONS, surpyval_extras

    components = dict(rbd._init_args["components"])
    objects: dict = {}
    users: dict = {}  # (role, model id) -> [node]
    names: dict = {}
    for node in graph.get("nodes") or []:
        nid = node.get("id")
        data = node.get("data") or {}
        spec = components.get(nid)
        if spec is not None and not isinstance(spec, dict) and hasattr(spec, "time_to_replace"):
            # A plain life-and-repair block: the same spec as a dict.
            spec = {"reliability": spec.reliability, "repairability": spec.time_to_replace}
        if not isinstance(spec, dict) or data.get("state") in ("working", "failed"):
            continue
        for slot, role in _ROLES.items():
            model = data.get(slot)
            if not isinstance(model, dict) or model.get("source") != "saved":
                continue
            mid = model.get("modelId") or model.get("model_id")
            if not mid or mid not in fits:
                continue
            if role not in spec:
                continue
            if mid not in objects:
                entry = DISTRIBUTIONS.get(model.get("distribution_id"))
                if entry is None:
                    continue
                obj = entry["dist"].from_params(list(fits[mid]["params"]), **surpyval_extras(model.get("extras")))
                obj.hess_inv = np.asarray(fits[mid]["hess_inv"], dtype=float)
                objects[mid] = obj if is_fit(obj) else None
            if objects[mid] is None:
                continue
            components[nid] = {**spec, **(components[nid] if isinstance(components[nid], dict) else {}),
                               role: objects[mid]}
            spec = components[nid]
            users.setdefault((role, mid), []).append(nid)
            names[mid] = model.get("name") or "saved model"
    if not users:
        return rbd, {}, []
    rebuilt = RepairableRBD(**{**rbd._init_args, "components": components})
    uncertainty: dict = {}
    inputs: list = []
    by_key: dict = {}
    for (role, mid), nodes in users.items():
        key = nodes[0] if len(nodes) == 1 else tuple(nodes)
        if key in uncertainty:
            uncertainty[key][role] = "fit"
            by_key[key]["roles"].append(role)
            continue
        uncertainty[key] = {role: "fit"}
        entry = {"key": key, "id": "+".join(map(str, nodes)), "label": _name(key, labels), "roles": [role],
                 "model": names[mid]}
        by_key[key] = entry
        inputs.append(entry)
    for entry in inputs:
        entry["what"] = " and ".join(_ROLE_WORDS[r] for r in entry["roles"])
    return rebuilt, uncertainty, inputs


def _uncertainty(head, opts, resolve_model, fits, fixed, *, rbd, labels, gates, working, broken, unit, graph) -> dict:
    level = opts.get("level", LEVEL)
    if fits is None:
        fits, fixed = fits_for(graph, resolve_model)
    fixed = list(fixed or [])
    if working or broken:
        fixed = [f for f in fixed if f["id"] not in working | broken]
    fitted, uncertainty, inputs = _with_fits(rbd, graph, fits, labels)
    base = {**head, "level": level, "method": opts["method"], "fixed": fixed,
            "inputs": [{k: v for k, v in i.items() if k != "key"} for i in inputs]}
    if not uncertainty:
        return {**base, "status": "no_uncertainty",
                "message": ("No block uses a saved model fitted by maximum likelihood, so there's no parameter "
                            "uncertainty to carry through. Pick saved fitted models for the blocks' lives (or "
                            "repairs) to see whose uncertainty matters.")}
    route, reason = _route(fitted, "mean_availability")
    if route not in ("exact", "numerical"):
        return _refused(base, "long-run availability", reason, labels)
    if opts["method"] == "sobol" and len(uncertainty) > SOBOL_MAX_INPUTS:
        raise AnalysisError(f"Sobol indices are worked out here for up to {SOBOL_MAX_INPUTS} uncertain inputs; "
                            "use the delta method.")
    if working or broken:
        # The draws' figures have no what-if pins: say so rather than mix them.
        return {**base, "status": "refused", "basis": "refused",
                "message": "Unpin the pinned blocks to see the parameter uncertainty: the draws are of the "
                           "diagram as it is."}
    long_run = fitted.mean_availability_uncertainty(uncertainty, n_draws=N_DRAWS, seed=SEED, sampling="sobol")
    lo, hi = long_run.interval(level)
    kw: dict = {"method": opts["method"]}
    if opts["method"] == "sobol":
        kw.update(n_draws=N_DRAWS_SOBOL, seed=SEED, sampling="sobol")
    parts = fitted.uncertainty_importance(None, uncertainty, **kw)
    rows = []
    for entry in inputs:
        first = _num(parts.first_order.get(entry["key"]))
        total = _num(parts.total.get(entry["key"]))
        rows.append({"id": entry["id"], "label": entry["label"], "what": entry["what"], "model": entry["model"],
                     "first_order": first, "total": total})
    rows.sort(key=lambda r: -(r["first_order"] or 0.0))
    out = {**base, "status": "ok", "basis": "exact" if route == "exact" else route,
           "basis_reason": ra._with_labels(reason, labels), "n_draws": N_DRAWS,
           "availability": {"nominal": _num(long_run.nominal), "lower": _num(lo), "upper": _num(hi)},
           "shares": rows, "variance": _num(parts.variance)}
    if opts["method"] == "sobol":
        out["n_draws_sobol"] = N_DRAWS_SOBOL
    times = opts.get("times")
    if times:
        x = np.asarray(times, dtype=float)
        point = fitted.point_availability_uncertainty(x, uncertainty, n_draws=N_DRAWS_OVER_TIME, seed=SEED,
                                                      sampling="sobol")
        mission = fitted.mission_availability_uncertainty(x, uncertainty, n_draws=N_DRAWS_OVER_TIME, seed=SEED,
                                                          sampling="sobol")
        p_lo, p_hi = point.interval(level)
        m_lo, m_hi = mission.interval(level)
        out["at_times"] = [
            {"t": float(t),
             "availability": {"nominal": _num(np.asarray(point.nominal)[i]), "lower": _num(np.asarray(p_lo)[i]),
                              "upper": _num(np.asarray(p_hi)[i])},
             "mean_availability": {"nominal": _num(np.asarray(mission.nominal)[i]),
                                   "lower": _num(np.asarray(m_lo)[i]), "upper": _num(np.asarray(m_hi)[i])}}
            for i, t in enumerate(times)]
        out["n_draws_over_time"] = N_DRAWS_OVER_TIME
    out["answer"] = _uncertainty_answer(out)
    return out


def _uncertainty_answer(out: dict) -> str:
    a = out["availability"]
    lvl = f"{round(out['level'] * 100):g}%"
    lo, hi = _pct_pair(a["lower"], a["upper"])
    mid = _pct_pair(a["nominal"], a["nominal"] + (a["upper"] - a["lower"]))[0]
    text = f"The long-run availability is {mid}, known to within {lo} to {hi} ({lvl})."
    rows = [r for r in out["shares"] if (r["first_order"] or 0) > 0]
    if rows:
        top = rows[0]
        text += (f" {top['label']}'s {top['what']} fit makes {_pct(top['first_order'], 2)} of that spread: "
                 "more data on it would narrow the answer most.")
    return text
