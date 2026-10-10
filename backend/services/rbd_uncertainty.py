"""Confidence band on a non-repairable RBD's reliability from the uncertainty
in its fitted component models (RePyability 0.9's epistemic uncertainty).

A block that references a saved, maximum-likelihood fitted model carries that
fit's parameter uncertainty: each of ``n_draws`` draws gives it plausible
parameters from the fit's own covariance (surpyval's ``hess_inv``), drawn by
RePyability's ``"fit"`` sampler on scales that keep every draw valid (log for
a positive parameter, logit for one in (0, 1); an offset, zero-inflation or
LFP parameter keeps its fitted value). The system reliability is computed
exactly for every draw and the band is the equal-tailed percentile interval
over the draws, per time. The MTTF and B-lives get their intervals from the
same draws.

Why not ``NonRepairableRBD.sf_uncertainty`` directly: a Reliafy node is often
a *wrapper* around the fitted model — a series/parallel count block, a standby
arrangement, a nested sub-system — which that method can't redraw, and it
takes no what-if pins, conditional age or common-cause groups. So the draws
are made the same way (``repyability.rbd.uncertainty.draw_models``) and each
node is rebuilt per draw by the analysis' own builder, then the system is
evaluated with the same exact engine (``system_probability``), vectorised over
all draws at once. Everything that references the same saved model shares one
draw per iteration — RePyability's tuple semantics — whether those are two
blocks, the units of one parallel block, or a block inside a sub-system:
drawing them independently would understate the uncertainty, which is about
the one population's parameters.

Saved models persist their fitted surpyval model (with ``hess_inv``), so no
refit is needed; older saved models without it are refitted once from their
dataset by the existing refit-on-demand path and cached. Blocks with
hand-entered parameters, regression (proportional-hazards / AFT) models,
non-parametric models and load-sharing groups stay fixed, and the result says
which blocks carried uncertainty and why the others didn't.
"""

from __future__ import annotations

import zlib
from typing import Any, Callable, Optional

import numpy as np

from backend.fitting import DISTRIBUTIONS
from backend.services import rbd_analysis as ra
from repyability import UncertaintyResult
from repyability.rbd.helper_classes import PerfectReliability
from repyability.rbd.uncertainty import draw_models
from repyability.utils.wrappers import conditional_survival

DEFAULT_LEVEL = 0.95
# Draws of every uncertain model. Cold/warm standby blocks are rebuilt per draw
# (each ~5-15 ms: RePyability prepares the switching integral), so diagrams with
# uncertain standby blocks use fewer draws to keep the band quick.
_MAX_DRAWS = 1000
_MIN_DRAWS = 200
_STANDBY_DRAW_BUDGET = 300  # draws x uncertain standby blocks
# Fixed seed: the same diagram gives the same band every time.
SEED = 20261
# Points on the long grid the per-draw MTTF / B-lives are integrated over.
_LIFE_POINTS = 1500
# Rough cap on the per-chunk array size (draws x times) handed to the engine.
_CHUNK_ELEMENTS = 2_000_000

# Why a block didn't carry uncertainty — shown to the user.
_HAND_ENTERED = "hand-entered parameters"
_REGRESSION = "regression (covariate) model — kept at its fitted curve"
_NONPARAMETRIC = "non-parametric model"
_LOADSHARE = "load-sharing group — kept at its fitted load-life model"
_STALE = ("its parameters differ from the saved model's current fit — "
          "re-pick the model to refresh them")
_UNREADABLE = "the saved model's fit couldn't be loaded"


class _SavedDraws:
    """The draws of one saved fitted model, shared by every block using it."""

    def __init__(self, model_id: str, live, params: list):
        self.model_id = model_id
        self.live = live
        self.params = params  # n_draws parameter vectors (dist param order)


class _Collector:
    """Resolves saved models to their draws, once per model id, and records
    which blocks are uncertain and which stay fixed (and why)."""

    def __init__(self, resolve_model, n_draws: int, seed: int):
        self.resolve_model = resolve_model
        self.n_draws = n_draws
        self.seed = seed
        self._cache: dict[str, Any] = {}  # model id -> _SavedDraws | reason
        self.uncertain: list[dict] = []
        self.fixed: list[dict] = []

    def draws(self, model_id: str, label: str):
        """``_SavedDraws`` for a saved model, or a reason string."""
        if model_id not in self._cache:
            self._cache[model_id] = self._load(model_id, label)
        return self._cache[model_id]

    def _load(self, model_id: str, label: str):
        if self.resolve_model is None:
            return _UNREADABLE
        try:
            entry = self.resolve_model(model_id)
        except Exception:  # noqa: BLE001 - a refit that fails leaves it fixed
            entry = None
        live = (entry or {}).get("model")
        if live is None or not hasattr(getattr(live, "dist", None), "from_params"):
            return _UNREADABLE
        if getattr(live, "hess_inv", None) is None:
            return "no parameter covariance (not a maximum-likelihood fit)"
        # Per-model seed: adding or removing another block never changes this
        # model's draws.
        rng = np.random.default_rng([self.seed, zlib.crc32(model_id.encode())])
        try:
            models = draw_models(live, "fit", self.n_draws, rng, label)
        except ValueError as exc:
            return str(exc).split(": ", 1)[-1]
        params = [list(np.atleast_1d(np.asarray(m.params, dtype=float))) for m in models]
        return _SavedDraws(model_id, live, params)


def _saved_id(model: Optional[dict]) -> Optional[str]:
    if not model or model.get("source") != "saved":
        return None
    return model.get("modelId") or model.get("model_id")


def _matches(model: dict, live) -> bool:
    """Whether a block's stored parameters are its saved model's current fit
    (a block keeps the parameters it was given when the model was picked)."""
    entry = DISTRIBUTIONS.get(model.get("distribution_id"))
    if entry is None:
        return False
    dist = entry["dist"]
    if live.dist is not dist and getattr(live.dist, "name", None) != getattr(dist, "name", ""):
        return False
    by_name = {p.get("name"): p.get("value") for p in (model.get("params") or [])}
    names = list(getattr(dist, "parameter_names", []) or [])
    try:
        values = [float(by_name[n]) for n in names]
    except (KeyError, TypeError, ValueError):
        return False
    fitted = np.atleast_1d(np.asarray(live.params, dtype=float))
    return len(values) == len(fitted) and np.allclose(values, fitted, rtol=1e-6, atol=0.0)


def _drawn_model(model: dict, params: list) -> dict:
    """The block's life model with draw ``params`` in place of its own."""
    dist = DISTRIBUTIONS[model["distribution_id"]]["dist"]
    names = list(getattr(dist, "parameter_names", []) or [])
    return {
        "source": "params",
        "distribution_id": model["distribution_id"],
        "params": [{"name": n, "value": float(v)} for n, v in zip(names, params)],
        "extras": model.get("extras"),
    }


def _model_slots(node: dict) -> list[str]:
    """The ``data`` keys holding a life model the node is built from."""
    ntype = node.get("type")
    if ntype in ("component", "series", "parallel"):
        return ["model"]
    if ntype == "standby":
        return ["model", "standbyModel"]
    return []


def _is_slow_standby(node: dict) -> bool:
    if node.get("type") != "standby":
        return False
    try:
        return ra._standby_dormancy(node.get("data") or {}, "") < 1.0
    except ra.AnalysisError:
        return False


class _DrawnRbd:
    """A built RBD whose uncertain nodes have one model per draw.

    ``drawn`` maps node id -> a list of per-draw node reliabilities, or a
    nested ``_DrawnRbd`` for a sub-system containing uncertain blocks. Every
    other node keeps its own reliability.
    """

    def __init__(self, rbd, drawn: dict, working=frozenset(), broken=frozenset(), ages=None):
        self.rbd = rbd
        self.drawn = drawn
        self.working = set(working)
        self.broken = set(broken)
        # As of now (#173): blocks that have run some time, conditioned on it.
        self.ages = dict(ages or {})

    def _node_sf(self, node, model, times: np.ndarray) -> np.ndarray:
        age = self.ages.get(node)
        if age:
            out = np.asarray(conditional_survival(model, times, age), dtype=float)
            return np.clip(np.nan_to_num(out), 0.0, 1.0)
        return np.asarray(model.sf(times), dtype=float)

    def sf(self, times: np.ndarray, lo: int, hi: int) -> np.ndarray:
        """System reliability of draws ``lo:hi`` at ``times``: ``(hi-lo, T)``."""
        n, T = hi - lo, len(times)
        probs: dict = {}
        for node, model in self.rbd.reliabilities.items():
            if node in self.working:
                probs[node] = np.ones(n * T)
            elif node in self.broken:
                probs[node] = np.zeros(n * T)
            elif isinstance(model := self.drawn.get(node, model), _DrawnRbd):
                probs[node] = model.sf(times, lo, hi).reshape(-1)
            elif isinstance(model, list):
                probs[node] = np.concatenate([
                    np.broadcast_to(self._node_sf(node, m, times), (T,))
                    for m in model[lo:hi]
                ])
            else:
                probs[node] = np.tile(
                    np.broadcast_to(self._node_sf(node, model, times), (T,)), n
                )
        if self.rbd.ccf_groups:
            out = self.rbd._ccf_system_probability(probs, self.working, self.broken, "p")
        else:
            out = self.rbd.system_probability(probs)
        return np.asarray(out, dtype=float).reshape(n, T)


def _draw_graph(
    graph: dict,
    rbd,
    collector: _Collector,
    n: int,
    resolve_subsystem,
    resolve_model,
    covariates,
    prefix: str = "",
    working=frozenset(),
    broken=frozenset(),
    visited=frozenset(),
    ages=None,
) -> Optional[_DrawnRbd]:
    """Rebuild each uncertain node of ``graph`` once per draw. Returns None
    when no node in it (or its sub-systems) carries uncertainty."""
    by_id = {nd.get("id"): nd for nd in graph.get("nodes") or []}
    drawn: dict = {}
    for nid, base in rbd.reliabilities.items():
        node = by_id.get(nid)
        if node is None or nid in working or nid in broken:
            continue
        ntype = node.get("type")
        data = node.get("data") or {}
        label = prefix + (data.get("label") or str(nid))
        if ntype == "subsystem":
            ref = data.get("rbd") or {}
            sub_graph = resolve_subsystem(ref["id"]) if (resolve_subsystem and ref.get("id")) else None
            if sub_graph is None or ref["id"] in visited:
                continue
            sub = _draw_graph(
                sub_graph, base, collector, n, resolve_subsystem, resolve_model,
                covariates, prefix=f"{label} › ", visited=visited | {ref["id"]},
            )
            if sub is not None:
                drawn[nid] = sub
            continue
        if ntype == "loadshare":
            collector.fixed.append({"id": nid, "label": label, "reason": _LOADSHARE})
            continue
        slots = _model_slots(node)
        if not slots or base is PerfectReliability:
            continue  # voting gates / placeholders: nothing to draw
        swaps: dict[str, _SavedDraws] = {}
        reasons: list[str] = []
        for slot in slots:
            model = data.get(slot)
            if not model:
                continue
            kind = model.get("kind")
            model_id = _saved_id(model)
            if kind == "regression":
                reasons.append(_REGRESSION)
            elif kind == "nonparametric":
                reasons.append(_NONPARAMETRIC)
            elif model_id is None:
                reasons.append(_HAND_ENTERED)
            else:
                got = collector.draws(model_id, label)
                if not isinstance(got, _SavedDraws):
                    reasons.append(got)
                elif not _matches(model, got.live):
                    reasons.append(_STALE)
                else:
                    swaps[slot] = got
        if not swaps:
            reason = reasons[0] if reasons else _HAND_ENTERED
            collector.fixed.append({"id": nid, "label": label, "reason": reason})
            continue
        models = []
        for i in range(n):
            new_data = dict(data)
            for slot, saved in swaps.items():
                new_data[slot] = _drawn_model(data[slot], saved.params[i])
            node_i = {**node, "data": new_data}
            rel, _ = ra._node_reliability(node_i, None, set(), resolve_model, covariates)
            models.append(rel)
        drawn[nid] = models
        entry = {"id": nid, "label": label,
                 "models": sorted({(data[slot].get("name") or "saved model")
                                   for slot in swaps}),
                 "model_ids": sorted({s.model_id for s in swaps.values()})}
        if reasons:  # e.g. a standby spare with hand-entered parameters
            entry["partly_fixed"] = reasons[0]
        collector.uncertain.append(entry)
    if not drawn:
        return None
    return _DrawnRbd(rbd, drawn, working, broken, ages)


def _count_slow_standby(graph: dict, resolve_subsystem, visited=frozenset()) -> int:
    """Uncertain-looking cold/warm standby blocks, sub-systems included."""
    count = 0
    for node in graph.get("nodes") or []:
        data = node.get("data") or {}
        if node.get("type") == "subsystem":
            ref = (data.get("rbd") or {}).get("id")
            if ref and resolve_subsystem and ref not in visited:
                sub = resolve_subsystem(ref)
                if sub:
                    count += _count_slow_standby(sub, resolve_subsystem, visited | {ref})
        elif _is_slow_standby(node) and any(
            _saved_id(data.get(s)) for s in ("model", "standbyModel")
        ):
            count += 1
    return count


def n_draws_for(graph: dict, resolve_subsystem=None) -> int:
    """Draws for a diagram: the maximum, fewer with uncertain standby blocks."""
    slow = _count_slow_standby(graph, resolve_subsystem)
    if not slow:
        return _MAX_DRAWS
    return max(_MIN_DRAWS, min(_MAX_DRAWS, _STANDBY_DRAW_BUDGET // slow))


def _evaluate(drawn: _DrawnRbd, times: np.ndarray, n: int) -> np.ndarray:
    """Per-draw system reliability at ``times``, in chunks of draws."""
    per = max(1, _CHUNK_ELEMENTS // max(len(times), 1))
    parts = [drawn.sf(times, lo, min(n, lo + per)) for lo in range(0, n, per)]
    return np.vstack(parts)


def _conditional(drawn: _DrawnRbd, t: np.ndarray, s: float, n: int) -> np.ndarray:
    """Per-draw ``R(t | s) = R(s + t) / R(s)`` (just ``R(t)`` when s = 0)."""
    if s <= 0:
        return np.clip(_evaluate(drawn, t, n), 0.0, 1.0)
    sf = _evaluate(drawn, np.concatenate([[s], s + t]), n)
    at_s, later = sf[:, :1], sf[:, 1:]
    with np.errstate(all="ignore"):
        out = np.where(at_s > 0, later / at_s, 0.0)
    return np.clip(np.where(np.isfinite(out), out, 0.0), 0.0, 1.0)


def _life_grid(drawn: _DrawnRbd, base_hi: float, s: float, n: int) -> np.ndarray:
    """A grid long enough for (nearly) every draw's reliability to decay,
    like the point MTTF's extension of the horizon (up to 256x)."""
    probe = np.geomspace(base_hi * 1e-3, base_hi * 256.0, 64)
    sf = _conditional(drawn, probe, s, n)
    dead = sf < 1e-4
    ends = np.where(dead.any(axis=1), probe[np.argmax(dead, axis=1)], probe[-1])
    t_end = max(float(np.percentile(ends, 99.0)), base_hi)
    return np.linspace(0.0, t_end, _LIFE_POINTS)


def _b_lives(grid: np.ndarray, sf: np.ndarray, frac: float) -> np.ndarray:
    """Per-draw time by which ``frac`` of systems have failed (inf if the
    draw never gets there on the grid), interpolated like the point B-life."""
    target = 1.0 - frac
    below = sf <= target
    hit = below.any(axis=1)
    i = np.argmax(below, axis=1)
    out = np.full(sf.shape[0], np.inf)
    rows = np.nonzero(hit)[0]
    for r in rows:
        k = i[r]
        if k == 0:
            out[r] = grid[0]
            continue
        s0, s1 = sf[r, k - 1], sf[r, k]
        f = 0.0 if s1 == s0 else (s0 - target) / (s0 - s1)
        out[r] = grid[k - 1] + f * (grid[k] - grid[k - 1])
    return out


def _interval(values: np.ndarray, level: float) -> dict:
    """Equal-tailed interval over draws; an end beyond the grid is None."""
    tail = 50.0 * (1.0 - level)
    lo, hi = np.percentile(values, [tail, 100.0 - tail], method="inverted_cdf")

    def clean(v):
        return float(v) if np.isfinite(v) else None

    return {"lower": clean(lo), "upper": clean(hi)}


def system_band(
    graph: dict,
    rbd,
    grid: np.ndarray,
    s: float = 0.0,
    working_nodes=frozenset(),
    broken_nodes=frozenset(),
    resolve_subsystem: Optional[Callable[[str], dict]] = None,
    resolve_model=None,
    covariates: Optional[dict] = None,
    level: Optional[float] = None,
    seed: int = SEED,
    target: Optional[float] = None,
    ages: Optional[dict] = None,
    fractions=None,
    times=None,
) -> dict:
    """The confidence band on a built RBD's reliability over ``grid`` (and
    intervals on its MTTF and B10/B50), from its fitted blocks' uncertainty.

    ``rbd`` is the analysis' own built RBD of ``graph``; ``s`` the conditional
    age (the band is then on ``R(t | s)`` and the MTTF interval on the mean
    residual life). ``ages`` (as of now, #173) conditions those blocks on the
    time they have run — the failed ones come in ``broken_nodes`` — so the
    band runs from now. ``target`` adds ``design_life``: the interval on the
    time the system reliability falls to it, found per draw as RePyability's
    ``time_to_reliability_uncertainty`` finds it.

    Several targets in one run (#325): ``fractions`` (e.g. ``[0.01, 0.1,
    0.5]``) adds ``targets.b_lives``, the interval on each B-life, and
    ``times`` adds ``targets.reliability``, the interval on the (mission)
    reliability at each time, all from the same draws.
    """
    try:
        level = float(level) if level is not None else DEFAULT_LEVEL
    except (TypeError, ValueError):
        level = DEFAULT_LEVEL
    if not 0.5 <= level < 1.0:
        raise ra.AnalysisError("The confidence level must be from 50% up to (not including) 100%.")
    n = n_draws_for(graph, resolve_subsystem)
    collector = _Collector(resolve_model, n, seed)
    drawn = _draw_graph(
        graph, rbd, collector, n, resolve_subsystem, resolve_model, covariates,
        working=working_nodes, broken=broken_nodes, ages=ages,
    )
    out: dict = {
        "level": level,
        "n_draws": n,
        "seed": seed,
        "uncertain": collector.uncertain,
        "fixed": collector.fixed,
        "sf_lower": None,
        "sf_upper": None,
        "mttf": None,
        "blife": None,
        **({"design_life": None} if target is not None else {}),
    }
    if drawn is None:
        return out

    # The band over the displayed grid, via RePyability's own summary.
    band = UncertaintyResult(samples=_conditional(drawn, grid, s, n), nominal=None, n_draws=n)
    lower, upper = band.interval(level)
    out["sf_lower"] = ra._clean(lower)
    out["sf_upper"] = ra._clean(upper)

    # MTTF / B-lives per draw, over a grid long enough for the draws to decay.
    life = _life_grid(drawn, float(grid[-1]) if grid[-1] > 0 else 1.0, s, n)
    life_sf = _conditional(drawn, life, s, n)
    trapezoid = getattr(np, "trapezoid", None) or np.trapz
    mttf = trapezoid(life_sf, life, axis=1)
    out["mttf"] = _interval(mttf, level)
    out["blife"] = {
        "b10": _interval(_b_lives(life, life_sf, 0.10), level),
        "b50": _interval(_b_lives(life, life_sf, 0.50), level),
    }
    if target is not None:
        out["design_life"] = _interval(_b_lives(life, life_sf, 1.0 - target), level)
    if fractions or times:
        out["targets"] = {
            "b_lives": [{"fraction": float(f), **_interval(_b_lives(life, life_sf, float(f)), level)}
                        for f in fractions or []],
            "reliability": [],
        }
        if times:
            at = np.asarray([float(t) for t in times], dtype=float)
            drawn_at = UncertaintyResult(samples=_conditional(drawn, at, s, n), nominal=None, n_draws=n)
            lo, hi = drawn_at.interval(level)
            out["targets"]["reliability"] = [
                {"t": float(t), "lower": ra._f(np.asarray(lo)[i]), "upper": ra._f(np.asarray(hi)[i])}
                for i, t in enumerate(at)]
    return out


#: The most B-lives and times a band takes at once (#325).
MAX_TARGETS = 8


def parse_targets(band: Optional[dict]) -> tuple[Optional[list], Optional[list]]:
    """A band request's ``b_lives`` (percent failed, e.g. ``[1, 10, 50]``, or
    fractions below 1) and ``times`` (positive, in the diagram's unit), as
    fractions and times; None for each one not asked for. Raises
    :class:`AnalysisError`."""
    if not band:
        return None, None
    out = []
    for key in ("b_lives", "times"):
        raw = band.get(key)
        if raw in (None, []):
            out.append(None)
            continue
        if not isinstance(raw, (list, tuple)):
            raise ra.AnalysisError(f"band.{key} must be a list of numbers.")
        values = []
        for v in raw:
            if isinstance(v, bool):
                raise ra.AnalysisError(f"band.{key} must be numbers.")
            try:
                x = float(v)
            except (TypeError, ValueError):
                raise ra.AnalysisError(f"band.{key} must be numbers.") from None
            if not np.isfinite(x) or x <= 0:
                raise ra.AnalysisError(f"band.{key} must be positive.")
            if key == "b_lives":
                x = x / 100.0 if x >= 1.0 else x
                if not 0.0 < x < 1.0:
                    raise ra.AnalysisError("A B-life is a percent failed between 0 and 100 (e.g. 10 for B10).")
            values.append(x)
        values = sorted(set(values))
        if len(values) > MAX_TARGETS:
            raise ra.AnalysisError(f"Give at most {MAX_TARGETS} {'B-lives' if key == 'b_lives' else 'times'}.")
        out.append(values)
    return out[0], out[1]
