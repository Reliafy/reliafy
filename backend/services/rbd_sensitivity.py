"""What to improve (#225): how a repairable diagram's availability and cost
move with each lever, ranked — RePyability's lever sensitivity
(``RepairableRBD.parameter_sensitivity``, one of its "Greeks").

The levers are RePyability's own (``RepairableRBD.levers()``, public since
0.13, each moved with ``with_levers``):
each block's life and repair models' parameters, its scheduled
replacement's and proof tests' intervals, durations, threshold and coverage,
its standby group's, its imperfect repair's, and one more repair crew. Each
is named in plain words here: a model's scale parameter as its *mean* (the
mean life, the mean repair time), so that a "10% shorter mean repair time"
is what moves, whatever the distribution; its other parameters as shapes.

Each lever gets

* RePyability's derivative (``derivative``): the slope of the availability
  (and of the cost per unit time, for a priced diagram) in the lever's own
  units — a central difference of the system's exact or numerical value,
  the diagram rebuilt with the lever moved (RePyability's route for
  ``parameter_sensitivity`` is "numerical" for that reason);
* the effect of a stated step (``effect``): the lever moved by ``step``
  (10% by default: a 10% longer mean life, a 10% shorter test interval;
  one more crew or standby unit) in the direction that improves what the
  levers are ranked by, worked out on the rebuilt diagram. In the long run
  that is a difference of exact (or numerical) values; over a window, and
  for an interval whose schedule shares a calendar with others' (where the
  long-run values jump), it is the derivative times the step ("linear").

They are ranked by that benefit, or — given a cost to make each change
(``costs``) — by benefit per unit of cost. RePyability's own ``unit_costs``
ranking is the derivative over the cost of a unit change of the lever: the
``per_unit_cost`` here, the same number.

Where RePyability has no exact or numerical value (limited repair crews for
wear-out lives, say: its route for the long run is refused), the effects are
simulated: each changed diagram against the diagram as it is, with common
random numbers (as "Compare with…", :mod:`backend.services.rbd_compare`),
over the availability simulation's window. That is the paid simulation
(Pro or credits); the exact and numerical answers are free.

The diagram is built exactly as the availability analysis builds it, so the
base values are the results tab's, and pinned blocks are held. Its
common-cause groups (#226) are in it wherever the analysis has them: each
group's β is then a lever ("Common-cause β", a lower β meaning fewer shared
failures), and its members' life and repair parameters move together (the
group's lever, on "A & B"), as RePyability's chains need the members alike.
Where RePyability refuses the groups they're left out here too, and the
notes say why.

Speed (#225), the whole analysis (derivatives and steps) timed with
RePyability 0.12 on a laptop (Cloud Run's 1 vCPU is about half as fast):

* exact long run, priced (both quantities): the instrument-air sample
  (8 blocks) 0.08 s; series-parallel 10 blocks 0.12 s, 20 0.26 s, 40 0.9 s,
  60 2.0 s, 120 8.0 s. In-process up to :data:`INLINE_MAX_BLOCKS` blocks.
* numerical long run (half the blocks with age replacement or proof tests):
  4 blocks 3 s, 10 blocks 8.6 s, 20 blocks 90 s — a job, up to
  :data:`NUMERICAL_MAX_BLOCKS` blocks (the compute task's deadline is 290 s).
* over a window (availability only — the window's cost rebuilds the whole
  system's cost curves for every lever, 14× slower): the sample 0.5 s;
  10 blocks 5.6 s, 30 blocks 19 s, 60 blocks 40 s — a job, up to
  :data:`WINDOW_MAX_BLOCKS`.
* simulated (up to four paired simulations a lever, their size set by
  :data:`SIM_TIME_BUDGET_S`): the sample with one crew 30 s (670
  simulations each); one crew over 4 / 10 / 20 blocks 13 / 31 / 37 s
  (2,147 / 896 / 201 simulations) — a job.

Jobs run on the compute service (``KIND_SENSITIVITY``), through the queue
like a simulation (#149); in-process where no queue is configured.
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

#: The default step: each lever moved 10% of its value (a 10% longer mean life).
DEFAULT_STEP = 0.10
#: The steps the app offers (any in [MIN_STEP, MAX_STEP] is taken).
STEPS = (0.10, 0.25, 0.50)
MIN_STEP = 0.01
MAX_STEP = 0.90
#: The exact long run runs in-process up to this many blocks (0.9 s at 40
#: blocks on a laptop; Cloud Run's 1 vCPU is about half as fast).
INLINE_MAX_BLOCKS = 40
#: No lever sensitivity on this service above this many blocks (the exact
#: figures' own limit): "Download as Python" computes it locally.
MAX_BLOCKS = ra.EXACT_MAX_BLOCKS
#: A numerical long run (maintenance, timed tests) up to this many blocks
#: (90 s at 20 on a laptop), and a window's up to this many (38 s at 60).
NUMERICAL_MAX_BLOCKS = 20
WINDOW_MAX_BLOCKS = ra.EXACT_WINDOW_MEAN_MAX_BLOCKS
#: What to rank by.
RANK_BY = ("availability", "cost")
#: How the levers are ordered: by benefit alone (costs or not), or the levers
#: given a cost to change first, by benefit per unit spent.
ORDERS = ("benefit", "benefit_per_cost")
#: The simulation's time budget for all its levers, and the replications of
#: each paired run it may take.
SIM_TIME_BUDGET_S = 90.0
SIM_MIN_N = 100
SIM_MAX_N = 4000
#: Above this a simulation would overrun the compute service's deadline.
SIM_HARD_LIMIT_S = 240.0
_SIM_PILOT = 20

BASES = ("exact", "numerical", "simulation")

# ---------------------------------------------------------------------------
# The levers, in plain words
# ---------------------------------------------------------------------------
#: A model parameter that sets its mean: how a mean ``k`` times as long moves
#: it. "scale": θ·k; "rate": θ/k; "log": θ + ln k; "shift": θ + (k−1)·mean.
MEAN_PARAMETERS = {
    ("Weibull", "alpha"): "scale",
    ("LogLogistic", "alpha"): "scale",
    ("ExpoWeibull", "alpha"): "scale",
    ("Rayleigh", "sigma"): "scale",
    ("Exponential", "failure_rate"): "rate",
    ("Gamma", "beta"): "rate",
    ("LogNormal", "mu"): "log",
    ("Normal", "mu"): "shift",
    ("Logistic", "mu"): "shift",
    ("Gumbel", "mu"): "shift",
    ("GumbelLEV", "mu"): "shift",
}
_GREEK = {"alpha": "α", "beta": "β", "mu": "μ", "sigma": "σ", "gamma": "γ", "failure_rate": "λ"}
_DIST_NAMES = {"LogNormal": "lognormal", "LogLogistic": "log-logistic", "ExpoWeibull": "exponentiated Weibull",
               "GumbelLEV": "Gumbel (largest)", "Gumbel": "Gumbel"}

# What a model is the time of, by the lever's prefix: (mean's name, noun).
_MODELS = {
    "reliability": ("Mean life (MTTF)", "mean life", "life"),
    "repairability": ("Mean repair time (MTTR)", "mean repair time", "repair time"),
    "preventive.duration": ("Mean scheduled-replacement time", "mean scheduled-replacement time",
                            "scheduled-replacement time"),
    "inspection.duration": ("Mean proof-test time", "mean proof-test time", "proof-test time"),
}

# The other levers: (name, noun, kind). Kinds: "time" (longer/shorter),
# "probability" (higher/lower, within [0, 1]), "factor" (higher/lower),
# "count" (one more).
_OPTIONS = {
    "preventive.interval": ("Replacement interval", "replacement interval", "time"),
    "preventive.threshold": ("Replacement threshold", "replacement threshold", "probability"),
    "preventive.opportunity": ("Opportunity age", "opportunity age", "time"),
    "inspection.interval": ("Proof-test interval", "proof-test interval", "time"),
    "inspection.coverage": ("Proof-test coverage", "proof-test coverage", "probability"),
    "inspection.offset": ("First proof test at", "first proof-test time", "time"),
    "standby.dormancy_factor": ("Standby dormancy factor", "dormancy factor", "factor"),
    "standby.switching_probability": ("Switch-over success", "switch-over success probability", "probability"),
    "standby.units": ("Standby units", "standby unit", "count"),
    "repair.q": ("Repair effectiveness q", "repair effectiveness q", "probability"),
    "repair_crews": ("Repair crews", "repair crew", "count"),
}


class _Lever:
    """One of RePyability's levers with what this module adds: its plain
    name, how a step moves it, and the value a user reads."""

    def __init__(self, rbd, lever, labels: dict, unit: str):
        self.raw = lever
        self.key = lever.key
        self.name = lever.name
        self.value = float(lever.value)
        self.discrete = bool(lever.discrete)
        self.block_id = None if lever.key is None else (
            "+".join(map(str, lever.key)) if isinstance(lever.key, tuple) else str(lever.key))
        self.block = ("System" if lever.key is None
                      else " & ".join(labels.get(k, str(k)) for k in lever.key) if isinstance(lever.key, tuple)
                      else labels.get(lever.key, str(lever.key)))
        self.id = "repair_crews" if lever.key is None else f"{self.block_id}|{lever.name}"
        self.unit = unit
        self.model = None
        self.mean_kind = None  # how the mean moves the parameter, for a mean lever
        self.mean = None
        self.extras: dict = {}
        self.cls = None
        self.params = None
        self.index = None
        self._describe(rbd)

    # -- naming --------------------------------------------------------------
    def _describe(self, rbd) -> None:
        prefix, _, param = self.name.rpartition(".")
        if prefix in _MODELS:
            model = _model_of(rbd, self.raw, prefix)
            spec = _parametric(model)
            if spec is not None:
                cls, params, names, extras = spec
                self.cls, self.params, self.extras = cls, list(params), dict(extras)
                self.index = list(names).index(param) if param in names else None
                dist = getattr(cls, "name", type(cls).__name__)
                kind = MEAN_PARAMETERS.get((dist, param))
                mean = _mean(cls, self.params, self.extras)
                if kind and mean is not None and self.index is not None and not self.extras.get("gamma"):
                    self.mean_kind, self.mean = kind, mean
                    self.kind = "mean"
                    self.label, self.noun, _ = _MODELS[prefix]
                    return
                thing = _MODELS[prefix][2]
                symbol = _GREEK.get(param, param)
                self.kind = "shape"
                self.label = f"{thing[0].upper()}{thing[1:]} {symbol} ({_DIST_NAMES.get(dist, dist)})"
                self.noun = f"{_DIST_NAMES.get(dist, dist)} {symbol} of the {thing}"
                return
        option = _OPTIONS.get(self.name)
        if option is not None:
            label, noun, kind = option
            if self.name.startswith("preventive.") and _policy(rbd, self.raw) == "condition":
                if self.name == "preventive.interval":
                    label, noun = "Condition-check interval", "condition-check interval"
            self.label, self.noun, self.kind = label, noun, kind
            return
        if self.name.startswith("ccf_"):
            letter = self.name[4:]
            self.label = f"Common-cause {_GREEK.get(letter, letter)}"
            self.noun, self.kind = f"common-cause {_GREEK.get(letter, letter)}", "probability"
            return
        self.label, self.noun, self.kind = self.name, self.name, "factor"

    # -- steps ---------------------------------------------------------------
    def stepped(self, step: float, up: bool) -> Optional[float]:
        """The lever's raw value moved one step: for a mean lever, the
        parameter that makes the mean ``1 ± step`` times as long; otherwise
        ``1 ± step`` times the value (one more for a count), within the
        lever's bounds. None where there is no such step (a value at 0, or
        at a bound)."""
        if self.discrete:
            return self.value + 1.0 if up else None
        k = 1.0 + step if up else 1.0 - step
        theta = self.value
        if self.mean_kind == "scale":
            return theta * k
        if self.mean_kind == "rate":
            return theta / k
        if self.mean_kind == "log":
            return theta + math.log(k)
        if self.mean_kind == "shift":
            return theta + (k - 1.0) * self.mean
        if theta == 0.0:
            return None
        moved = theta * k
        if self.kind == "probability":
            moved = min(max(moved, 0.0), 1.0)
        if moved == theta:
            return None
        return moved

    def shown(self, raw: Optional[float]) -> Optional[float]:
        """The value a user reads at the raw value ``raw``: the mean for a
        mean lever, else the value itself."""
        if raw is None:
            return None
        if self.mean_kind is None:
            return raw
        trial = list(self.params)
        trial[self.index] = raw
        return _mean(self.cls, trial, self.extras)

    def raw_per_shown(self) -> Optional[float]:
        """d(raw parameter) / d(shown value): turns RePyability's derivative
        into one per unit of the mean (per hour of mean repair time)."""
        if self.mean_kind is None:
            return 1.0
        theta, mean = self.value, self.mean
        if not mean:
            return None
        return {"scale": theta / mean, "rate": -theta / mean, "log": 1.0 / mean, "shift": 1.0}[self.mean_kind]

    def change_words(self, step: float, up: bool) -> str:
        """"10% shorter mean repair time", "one more repair crew"."""
        if self.discrete:
            return f"one more {self.noun}"
        pct = f"{round(step * 100):g}%"
        if self.kind in ("mean", "time"):
            word = "longer" if up else "shorter"
        else:
            word = "higher" if up else "lower"
        return f"a {pct} {word} {self.noun}"


def _parametric(model):
    from repyability.rbd._model_utils import parametric_spec

    if model is None or isinstance(model, str):
        return None
    try:
        return parametric_spec(model)
    except Exception:  # noqa: BLE001 - not a model RePyability moves
        return None


def _mean(cls, params, extras) -> Optional[float]:
    try:
        with np.errstate(all="ignore"), warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            m = float(cls.from_params(list(params), **extras).mean())
    except Exception:  # noqa: BLE001
        return None
    return m if math.isfinite(m) else None


def _spec_of(rbd, lever) -> Optional[dict]:
    """The spec Reliafy built ``lever``'s block from (a common-cause group's:
    its first member's), or None for the crews, a nested RBD or a junction."""
    components = dict(rbd._init_args["components"])
    key = lever.key[0] if isinstance(lever.key, tuple) else lever.key
    if key is None or key not in components:
        return None
    component = components[key]
    if isinstance(component, dict):
        return component
    life, repair = getattr(component, "reliability", None), getattr(component, "time_to_replace", None)
    return None if life is None or repair is None else {"reliability": life, "repairability": repair}


def _model_of(rbd, lever, prefix: str):
    spec = _spec_of(rbd, lever)
    if spec is None:
        return None
    if prefix in ("reliability", "repairability"):
        return spec.get(prefix)
    key = prefix.split(".")[0]
    options = spec.get(key)
    return options.get("duration") if isinstance(options, dict) else None


def _policy(rbd, lever) -> Optional[str]:
    spec = _spec_of(rbd, lever) or {}
    pm = spec.get("preventive")
    return pm.get("policy") if isinstance(pm, dict) else None


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------
def parse_step(value) -> float:
    if value is None or value == "":
        return DEFAULT_STEP
    if isinstance(value, bool):
        raise AnalysisError("step must be a fraction, e.g. 0.1 for 10%.")
    try:
        step = float(value)
    except (TypeError, ValueError):
        raise AnalysisError("step must be a fraction, e.g. 0.1 for 10%.") from None
    if step > 1.0 and step <= 90.0:
        step = step / 100.0  # "10" meant 10%
    if not (math.isfinite(step) and MIN_STEP <= step <= MAX_STEP):
        raise AnalysisError(f"step must be between {MIN_STEP:g} and {MAX_STEP:g} (a fraction: 0.1 is 10%).")
    return step


def parse_costs(raw) -> dict:
    """``{lever_id: cost}``: the cost to make each lever's stated change.
    Blank or zero costs are dropped (no cost given)."""
    if raw in (None, {}):
        return {}
    if not isinstance(raw, dict):
        raise AnalysisError("costs must be an object of lever id → the cost to make that change.")
    out = {}
    for key, value in raw.items():
        if value is None or value == "":
            continue
        if isinstance(value, bool):
            raise AnalysisError(f"The cost for {key!r} must be a number.")
        try:
            v = float(value)
        except (TypeError, ValueError):
            raise AnalysisError(f"The cost for {key!r} must be a number.") from None
        if not math.isfinite(v) or v < 0:
            raise AnalysisError(f"The cost for {key!r} must be finite and ≥ 0.")
        if v > 0:
            out[str(key)] = v
    return out


def parse_window(value) -> Optional[float]:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise AnalysisError("window must be a time in the diagram's unit.")
    try:
        w = float(value)
    except (TypeError, ValueError):
        raise AnalysisError("window must be a time in the diagram's unit.") from None
    if not (math.isfinite(w) and w > 0):
        raise AnalysisError("window must be a positive time in the diagram's unit.")
    return w


def parse_order(value) -> str:
    order = value or "benefit"
    if order not in ORDERS:
        raise AnalysisError("order must be 'benefit' or 'benefit_per_cost'.")
    return order


def options(window=None, step=None, rank_by=None, costs=None, n_simulations=None, seed=None,
            order=None) -> dict:
    """The validated options of a sensitivity request (plain JSON)."""
    rank = rank_by or "availability"
    if rank not in RANK_BY:
        raise AnalysisError("rank_by must be 'availability' or 'cost'.")
    out: dict[str, Any] = {
        "window": parse_window(window),
        "step": parse_step(step),
        "rank_by": rank,
        "order": parse_order(order),
        "costs": parse_costs(costs),
    }
    if n_simulations is not None:
        n = int(n_simulations)
        if not 2 <= n <= SIM_MAX_N * 10:
            raise AnalysisError("n_simulations is out of range.")
        out["n_simulations"] = n
    if seed is not None:
        if isinstance(seed, bool) or not isinstance(seed, (int, np.integer)) or not 0 <= seed < 2**32:
            raise AnalysisError("seed must be a whole number from 0 to 2**32 - 1.")
        out["seed"] = int(seed)
    return {k: v for k, v in out.items() if v is not None and v != {}}


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------
def _route(rbd, name: str) -> tuple[str, str]:
    try:
        r = rbd.analysis_routes()[name]
        return r.route, route_reason(r)
    except Exception:  # noqa: BLE001
        return "refused", ""


def plan(graph: dict, resolve_model=None, window: Optional[float] = None) -> dict:
    """How the sensitivity of this diagram is worked out, without working it
    out: ``basis`` ("exact" / "numerical" / "simulation"), whether it runs
    ``inline`` (in the request) or as a compute job, ``n_blocks`` and, for a
    refusal, ``too_large``. Raises :class:`AnalysisError` for a diagram the
    availability analysis can't build."""
    n_blocks = ra.count_blocks(graph)
    rbd, labels, *_ = ra._build_repairable_rbd(graph, resolve_model)
    value = "mission_availability" if window is not None else "mean_availability"
    route, reason = _route(rbd, value)
    sens_route, sens_reason = _route(rbd, "parameter_sensitivity")
    if _deterministic_route(route, sens_route, window):
        basis = route
    else:
        basis = "simulation"
        reason = (reason if window is not None else sens_reason) or reason
    inline = basis == "exact" and window is None and n_blocks <= INLINE_MAX_BLOCKS
    limit = block_limit(basis, window)
    return {
        "basis": basis,
        "reason": ra._with_labels(reason or "", labels),
        "inline": inline,
        "n_blocks": n_blocks,
        "limit": limit,
        "too_large": n_blocks > limit,
        "window": window,
    }


def block_limit(basis: str, window: Optional[float]) -> int:
    """The most blocks worked out here: over a window
    :data:`WINDOW_MAX_BLOCKS`, a numerical long run
    :data:`NUMERICAL_MAX_BLOCKS`, else :data:`MAX_BLOCKS`."""
    if window is not None:
        return WINDOW_MAX_BLOCKS
    if basis == "numerical":
        return NUMERICAL_MAX_BLOCKS
    return MAX_BLOCKS


def _deterministic_route(route: str, sens_route: str, window: Optional[float]) -> bool:
    """Whether RePyability differences exact or numerical values here: the
    long run's (``parameter_sensitivity``'s own route), or the window's."""
    if route not in ("exact", "numerical"):
        return False
    return window is not None or sens_route != "refused"


def too_large_message(n_blocks: int, limit: int = MAX_BLOCKS, basis: str = "exact",
                      window: Optional[float] = None) -> str:
    what = ("over a window" if window is not None
            else "with scheduled maintenance or timed tests (numerical)" if basis == "numerical" else "")
    return (f"This diagram has {n_blocks} blocks; what to improve is worked out here {what + ' ' if what else ''}"
            f"for up to {limit}. Download it as Python to run RePyability's parameter_sensitivity locally"
            + (", or rank the long run." if window is not None else "."))


# ---------------------------------------------------------------------------
# Values
# ---------------------------------------------------------------------------
def _values(rbd, quantities, overrides: dict, window: Optional[float]) -> dict:
    """``{"unavailability", "cost_rate"}`` of a diagram: in the long run
    (the unavailability worked out in its own right, so a small one keeps its
    precision), or over ``[0, window)`` from new."""
    out = {}
    with np.errstate(all="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        if "availability" in quantities:
            if window is None:
                out["unavailability"] = float(rbd.mean_unavailability(**overrides))
            else:
                out["unavailability"] = 1.0 - float(rbd.mission_availability(window, **overrides))
        if "cost_rate" in quantities:
            if window is None:
                out["cost_rate"] = float(rbd.expected_cost_rate(**overrides))
            else:
                out["cost_rate"] = float(np.asarray(rbd.expected_cost(window, **overrides).mean)) / window
    return out


def _rebuilt(rbd, lever: _Lever, value: float):
    try:
        return rbd.with_levers({lever.raw: value})
    except (ValueError, TypeError):
        return None


def _quantities(rbd, overrides: dict, window: Optional[float]) -> tuple[tuple, Optional[str]]:
    """What can be differenced: availability, and the cost rate when the
    diagram is priced and its cost has a route; the note when it hasn't."""
    if not rbd.has_costs:
        return ("availability",), None
    if window is not None:
        # The window's cost rebuilds every block's cost curves for each lever
        # (14× the availability's time): the long run ranks cost.
        return ("availability",), ("Over a window only availability is ranked; the long run ranks the "
                                   "running cost too.")
    route, reason = _route(rbd, "expected_cost_rate")
    if route not in ("exact", "numerical"):
        return ("availability",), f"No exact cost here, so only availability is ranked: {reason}"
    return ("availability", "cost_rate"), None


def _benefit(effect: dict, rank_by: str) -> Optional[float]:
    """What a step gains: availability (fraction) or cost per unit time saved."""
    if rank_by == "cost":
        v = effect.get("cost_rate")
        return None if v is None else -v
    return effect.get("availability")


# ---------------------------------------------------------------------------
# The analysis
# ---------------------------------------------------------------------------
def analyze_sensitivity(
    graph: dict,
    resolve_model=None,
    *,
    window: Optional[float] = None,
    step: float = DEFAULT_STEP,
    rank_by: str = "availability",
    costs: Optional[dict] = None,
    order: str = "benefit",
    simulate: bool = True,
    n_simulations: Optional[int] = None,
    seed: Optional[int] = None,
) -> dict:
    """The levers of a repairable diagram ranked by what a step of each
    gains (see the module docstring). ``window`` takes the mean over
    ``[0, window)`` from new instead of the long run; ``costs`` maps lever
    ids to the cost of making that lever's stated change (each row's
    benefit per cost); ``order`` "benefit" ranks by benefit alone, costs or
    not, "benefit_per_cost" puts the costed levers first, by benefit per
    unit spent, then the rest by benefit; ``simulate=False``
    refuses rather than simulating where there is no exact or numerical
    route (the caller's paid gate). ``n_simulations`` / ``seed`` fix a
    simulation's size and streams (else a time budget sizes it)."""
    started = time.perf_counter()
    ra.require_blocks(graph)
    if not (graph or {}).get("repairable"):
        raise AnalysisError("What to improve is for repairable (availability) diagrams.")
    step = parse_step(step)
    if rank_by not in RANK_BY:
        raise AnalysisError("rank_by must be 'availability' or 'cost'.")
    order = parse_order(order)
    costs = parse_costs(costs)
    n_blocks = ra.count_blocks(graph)
    if n_blocks > MAX_BLOCKS:
        raise AnalysisError(too_large_message(n_blocks))
    rbd, labels, gate_ids, working, broken = ra._build_repairable_rbd(graph, resolve_model)
    overrides = {"working_nodes": working, "broken_nodes": broken}
    pinned = set(working) | set(broken)
    unit = (graph.get("unit") or "").strip()
    found = _levers(rbd, labels, unit, pinned, gate_ids)
    unknown = sorted(set(costs) - {lv.id for lv in found})
    if unknown:
        raise AnalysisError(f"costs names {', '.join(unknown)}, which are not levers of this diagram.")

    value = "mission_availability" if window is not None else "mean_availability"
    route, reason = _route(rbd, value)
    sens_route, sens_reason = _route(rbd, "parameter_sensitivity")
    deterministic = _deterministic_route(route, sens_route, window)
    basis_now = route if deterministic else "simulation"
    limit = block_limit(basis_now, window)
    if n_blocks > limit:
        raise AnalysisError(too_large_message(n_blocks, limit, basis_now, window))
    quantities, cost_note = _quantities(rbd, overrides, window)
    if cost_note:
        cost_note = ra._with_labels(cost_note, labels)
    if rank_by == "cost" and "cost_rate" not in quantities:
        raise AnalysisError(cost_note or "This diagram has no costs, so there's no cost to rank by — rank by "
                            "availability, or give its blocks costs.")
    head = {
        "kind": "sensitivity",
        "unit": unit,
        "of": "window" if window is not None else "long_run",
        "window": window,
        "step": step,
        "order": order,
        "rank_by": rank_by,
        "priced": "cost_rate" in quantities,
        "n_blocks": n_blocks,
        "pinned": sorted(labels.get(n, str(n)) for n in pinned),
        "repyability_version": ra._repyability_version(),
    }
    notes = [cost_note] if cost_note else []
    common = ra.common_cause_status(rbd)
    if common is not None:
        head["common_cause_included"] = common["included"]
        n = common["groups"]
        if common["included"]:
            notes.append(f"The diagram's {n} common-cause group{'s' if n != 1 else ''} "
                         f"{'are' if n != 1 else 'is'} in the figures: each group's β is a lever, and its "
                         "members' life and repair move together.")
        else:
            notes.append(ra.common_cause_left_out(n, common["reason"]))
    if deterministic:
        result = _deterministic(rbd, found, overrides, window, step, rank_by, quantities, route)
        result["basis_reason"] = ra._with_labels(reason or "", labels)
    else:
        why = ra._with_labels((reason if window is not None else sens_reason) or reason, labels)
        if not simulate:
            return {**head, "status": "needs_simulation", "basis": "simulation", "basis_reason": why,
                    "levers": [], "notes": notes, "compute_seconds": time.perf_counter() - started}
        result = _simulated(graph, rbd, found, overrides, window, step, rank_by, quantities,
                            n_simulations, seed)
        result["basis_reason"] = why
        notes += result.pop("notes", [])
    rows = _rank(result.pop("rows"), rank_by, costs, order)
    out = finish_rows({
        **head,
        "status": "ok",
        **result,
        "levers": rows,
        "costs": costs,
        "notes": notes,
    })
    out["compute_seconds"] = time.perf_counter() - started
    return out


def _levers(rbd, labels, unit, pinned, gate_ids) -> list:
    out = []
    for lever in rbd.levers():
        key = lever.key
        members = set(key) if isinstance(key, tuple) else {key}
        if key is not None and (members & pinned or members & set(gate_ids)):
            continue  # a pinned block's levers move nothing
        out.append(_Lever(rbd, lever, labels, unit))
    return out


def _deterministic(rbd, found, overrides, window, step, rank_by, quantities, route) -> dict:
    """Derivatives from ``parameter_sensitivity``; step effects from the
    rebuilt diagram (long run) or the derivative times the step."""
    base = _values(rbd, quantities, overrides, window)
    kw = {"window": window} if window is not None else {}
    with np.errstate(all="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        sens = rbd.parameter_sensitivity(overrides["working_nodes"], overrides["broken_nodes"],
                                         of=tuple(quantities), **kw)
    rows = []
    for lv in found:
        derivative = {q: _fin(sens[q].get(lv.key, {}).get(lv.name)) for q in quantities}
        rank_q = "cost_rate" if rank_by == "cost" else "availability"
        d = derivative.get(rank_q)
        row = _row(lv, derivative, quantities)
        if lv.discrete:
            # RePyability's value for a count is the change one more makes.
            effect = {q: derivative.get(q) for q in quantities}
            row.update(_with_step(lv, step, True, effect, "exact" if route == "exact" else route, quantities))
            rows.append(row)
            continue
        if d is None:
            row["unranked"] = ("RePyability gives no derivative here (a value at its bound, or an interval "
                               "a common-cause group shares).")
            rows.append(row)
            continue
        # The direction that improves what is ranked: availability up, cost down.
        dshown = lv.raw_per_shown()
        slope = d * (dshown if dshown is not None else 1.0)
        gain = slope if rank_q == "availability" else -slope
        up = gain > 0 if gain != 0 else True
        target = lv.stepped(step, up)
        if target is None:
            row["unranked"] = ("At zero: a step in proportion to it moves nothing." if lv.value == 0
                               else "Already at its limit in the direction that helps.")
            rows.append(row)
            continue
        linear = window is not None or lv.raw.calendar
        effect = None
        basis = route
        if not linear:
            changed = _rebuilt(rbd, lv, target)
            if changed is not None:
                try:
                    moved = _values(changed, quantities, overrides, window)
                    effect = {}
                    if "availability" in quantities:
                        effect["availability"] = base["unavailability"] - moved["unavailability"]
                    if "cost_rate" in quantities:
                        effect["cost_rate"] = moved["cost_rate"] - base["cost_rate"]
                except (ValueError, NotImplementedError):
                    effect = None
        if effect is None:
            # The derivative times the step.
            delta = target - lv.value
            effect = {q: (derivative[q] * delta if derivative.get(q) is not None else None) for q in quantities}
            basis = "linear"
        row.update(_with_step(lv, step, up, effect, basis, quantities, target))
        rows.append(row)
    return {
        "basis": route,
        "derivative_basis": "numerical",
        "basis_reason": None,
        "availability": 1.0 - base["unavailability"] if "unavailability" in base else None,
        "cost_rate": base.get("cost_rate"),
        "rows": rows,
    }


def _fin(v) -> Optional[float]:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _row(lv: _Lever, derivative: dict, quantities) -> dict:
    per_shown = lv.raw_per_shown()
    return {
        "id": lv.id,
        "block_id": lv.block_id,
        "block": lv.block,
        "lever": lv.name,
        "name": lv.label,
        "kind": lv.kind,
        "discrete": lv.discrete,
        "value": lv.value,
        "shown_value": lv.shown(lv.value),
        "derivative": derivative,
        # Per unit of what a user reads (per hour of mean repair time).
        "derivative_shown": {q: (v * per_shown if v is not None and per_shown is not None else None)
                             for q, v in derivative.items()},
    }


def _with_step(lv: _Lever, step: float, up: bool, effect: dict, basis: str, quantities,
               target: Optional[float] = None) -> dict:
    if lv.discrete:
        target = lv.value + 1.0
    return {
        "direction": "increase" if up else "decrease",
        "change": lv.change_words(step, up),
        "to": target,
        "shown_to": lv.shown(target),
        "effect": {q: _fin(effect.get(q)) for q in quantities},
        "effect_basis": basis,
    }


def _rank(rows: list, rank_by: str, costs: dict, order: str = "benefit") -> list:
    """Ranked by ``order``: "benefit" — by benefit alone, costs or not;
    "benefit_per_cost" — the levers given a cost first, by benefit per unit
    spent, then the rest by benefit. Rows without an effect last."""
    for row in rows:
        effect = row.get("effect") or {}
        benefit = _benefit(effect, rank_by) if effect else None
        row["benefit"] = benefit
        cost = costs.get(row["id"])
        row["cost_to_change"] = cost
        row["benefit_per_cost"] = (benefit / cost) if (cost and benefit is not None) else None
        # RePyability's unit_costs ranking: the derivative over the cost of a
        # unit change of the lever.
        delta = None if row.get("to") is None else abs(row["to"] - row["value"])
        d = (row.get("derivative") or {}).get("cost_rate" if rank_by == "cost" else "availability")
        row["per_unit_cost"] = (d / (cost / delta)) if (cost and delta and d is not None) else None

    per_cost = order == "benefit_per_cost"

    def key(row):
        b, bpc = row.get("benefit"), row.get("benefit_per_cost")
        if b is None:
            return (3, 0.0)
        if per_cost and bpc is not None:
            return (0, -bpc)
        if b > 0:
            return (1, -b)
        return (2, -b)

    ordered = sorted(rows, key=key)
    for i, row in enumerate(ordered):
        row["rank"] = i + 1
    return ordered


# ---------------------------------------------------------------------------
# The simulation (no exact or numerical route)
# ---------------------------------------------------------------------------
def _simulated(graph, rbd, found, overrides, window, step, rank_by, quantities, n_simulations, seed) -> dict:
    """Each lever's step, both ways, against the diagram as it is, with
    common random numbers (as Compare with…): the effect and its interval;
    the derivative a central difference of the two."""
    from backend.services import rbd_compare as rc

    chosen, _ = ra.chosen_horizon(window, graph)
    t_sim = float(chosen if chosen is not None else ra._availability_horizon(graph))
    priced = "cost_rate" in quantities
    base = {"rbd": rbd, "overrides": overrides, "priced": priced}
    seed = ra._AVAIL_SEED if seed is None else int(seed)
    notes = []
    # Shapes aren't simulated: twice the levers for little a user can act on.
    simulated = [lv for lv in found if lv.kind != "shape"]
    skipped = [lv for lv in found if lv.kind == "shape"]
    if skipped:
        notes.append("Shape parameters aren't simulated (only means, intervals, coverage and counts are).")
    plans = []
    for lv in simulated:
        ways = [True] if lv.discrete else [True, False]
        for up in ways:
            target = lv.stepped(step, up)
            if target is None:
                continue
            changed = _rebuilt(rbd, lv, target)
            if changed is not None:
                plans.append((lv, up, target, {"rbd": changed, "overrides": overrides, "priced": priced}))
    paired = True

    def pair(design, n):
        nonlocal paired
        key = rc._key([seed, 0])
        if paired:
            try:
                return (rc._paired_run(base, t_sim, n, key), rc._paired_run(design, t_sim, n, key))
            except NotImplementedError:
                paired = False
        return (rc._independent_run(base, t_sim, n, key % 2**32), rc._independent_run(design, t_sim, n, key % 2**32))

    if n_simulations:
        n = max(2, int(n_simulations))
    else:
        t0 = time.perf_counter()
        if plans:
            pair(plans[0][3], _SIM_PILOT)
        per_pair = max((time.perf_counter() - t0) / _SIM_PILOT, 1e-9)
        n = int(SIM_TIME_BUDGET_S / max(per_pair * max(len(plans), 1), 1e-9))
        n = max(SIM_MIN_N, min(SIM_MAX_N, n))
        if per_pair * n * len(plans) > SIM_HARD_LIMIT_S:
            raise AnalysisError(
                f"This diagram has {len(plans)} lever steps to simulate, more than fit the calculation service's "
                "time limit. Download it as Python to run the sensitivity locally, or simplify the diagram.")
    z = ra._z(ra._AVAIL_CONFIDENCE)
    results: dict = {}
    for lv, up, target, design in plans:
        (fa, ca), (fb, cb) = pair(design, n)
        est, se = rc._difference(np.asarray(fa), np.asarray(fb), paired)
        eff = {"availability": (est, se)}
        if priced and ca is not None and cb is not None:
            c_est, c_se = rc._difference(np.asarray(ca), np.asarray(cb), paired)
            eff["cost_rate"] = (c_est / t_sim, c_se / t_sim)
        results.setdefault(lv.id, {})[up] = (target, eff)
    rows = []
    for lv in simulated:
        ways = results.get(lv.id) or {}
        derivative = {q: None for q in quantities}
        if True in ways and False in ways:
            (tu, eu), (td, ed) = ways[True], ways[False]
            for q in quantities:
                if q in eu and q in ed and tu != td:
                    derivative[q] = (eu[q][0] - ed[q][0]) / (tu - td)
        elif lv.discrete and True in ways:
            derivative = {q: ways[True][1][q][0] for q in quantities if q in ways[True][1]}
        row = _row(lv, derivative, quantities)
        if not ways:
            row["unranked"] = "No valid step to simulate."
            rows.append(row)
            continue
        rank_q = "cost_rate" if rank_by == "cost" else "availability"

        def gain(entry):
            v = entry[1].get(rank_q, (None,))[0]
            if v is None:
                return -math.inf
            return v if rank_q == "availability" else -v

        up = max(ways, key=lambda w: gain(ways[w]))
        target, eff = ways[up]
        effect = {q: eff[q][0] for q in quantities if q in eff}
        row.update(_with_step(lv, step, up, effect, "simulation", quantities, target))
        row["interval"] = {q: [eff[q][0] - z * eff[q][1], eff[q][0] + z * eff[q][1]] for q in quantities if q in eff}
        lo, hi = row["interval"].get("availability", [None, None])
        row["distinguishable"] = bool(lo is not None and (lo > 0 or hi < 0))
        rows.append(row)
    for lv in skipped:
        row = _row(lv, {q: None for q in quantities}, quantities)
        row["unranked"] = "Shape parameters aren't simulated."
        rows.append(row)
    return {
        "basis": "simulation",
        "derivative_basis": "simulation",
        "availability": None,
        "cost_rate": None,
        "t_simulation": t_sim,
        "n_simulations": n,
        "common_random_numbers": paired,
        "confidence": ra._AVAIL_CONFIDENCE,
        "rows": rows,
        "notes": notes,
    }


# ---------------------------------------------------------------------------
# Plain words
# ---------------------------------------------------------------------------
def _sig(v: float, digits: int = 2) -> str:
    """``v`` to ``digits`` significant figures, without an exponent."""
    if v == 0 or not math.isfinite(v):
        return "0"
    return np.format_float_positional(v, precision=digits, unique=False, fractional=False, trim="-")


def _num(v: float) -> str:
    """A value a user reads, to 3 significant figures: "56,400", "8.16"."""
    r = float(_sig(v, 3))
    return f"{r:,.0f}" if abs(r) >= 1000 else _sig(v, 3)


def _money(v: float) -> str:
    a = abs(v)
    if a >= 100:
        return f"{round(a):,}"
    return _sig(a, 3)


def _per(unit: str) -> str:
    u = unit_in_text(unit)
    if not u:
        return "per unit time"
    return "per " + (u[:-1] if u.endswith("s") else u)


def points(delta: float) -> str:
    """An availability change as percentage points: "0.04 points"."""
    return f"{_sig(abs(delta) * 100, 2)} points"


def plain_effect(row: dict) -> Optional[str]:
    """"A 10% shorter mean repair time for Strainer (8 → 7.2 hours) raises
    availability by about 0.04 points and cuts the running cost by about 12
    per hour"."""
    effect = row.get("effect")
    if not effect or row.get("change") is None:
        return None
    a = effect.get("availability")
    c = effect.get("cost_rate")
    change = row["change"]
    frm, to = row.get("shown_value"), row.get("shown_to")
    span = ""
    if not row.get("discrete") and frm is not None and to is not None:
        u = row.get("unit_word") or ""
        span = f" ({_num(frm)} → {_num(to)}{u})"
    lead = f"{change[0].upper()}{change[1:]} for {row['block']}{span}" if row.get("block_id") else \
        f"{change[0].upper()}{change[1:]}{span}"
    parts = []
    approx = "about " if row.get("effect_basis") in ("linear", "simulation", "numerical") else ""
    if a is not None:
        if a == 0:
            parts.append("leaves availability unchanged")
        else:
            parts.append(f"{'raises' if a > 0 else 'lowers'} availability by {approx}{points(a)}")
    if c is not None and c != 0:
        parts.append(f"{'cuts' if c < 0 else 'raises'} the running cost by {approx}{_money(c)} "
                     f"{row.get('per_word', 'per unit time')}")
    if not parts:
        return None
    text = f"{lead} {' and '.join(parts)}."
    if row.get("benefit_per_cost") is not None and row.get("cost_to_change"):
        text += f" At a cost of {_money(row['cost_to_change'])}, that is {_per_cost(row)}."
    return text


def _per_cost(row: dict) -> str:
    bpc = row["benefit_per_cost"]
    sign = "" if bpc >= 0 else "−"
    if row.get("_rank_by") == "cost":
        return f"{sign}{_sig(abs(bpc) * 1000, 2)} {row.get('per_word', 'per unit time')} saved for every 1,000 spent"
    return f"{sign}{_sig(abs(bpc) * 100 * 1000, 2)} points for every 1,000 spent"


def top_reading(result: dict) -> Optional[str]:
    """The top recommendation in a sentence or two — an actionable lever (a
    mean, an interval, coverage, a count) ahead of a model's shape."""
    rows = [r for r in result.get("levers") or [] if (r.get("benefit") or 0) > 0]
    if not rows:
        return ("No lever improves the system by the stated step"
                + (" — check that the diagram's blocks aren't all pinned." if result.get("pinned") else "."))
    actionable = [r for r in rows if r.get("kind") != "shape"] or rows
    best = actionable[0]
    text = best.get("plain") or ""
    if result.get("basis") == "simulation" and not best.get("distinguishable", True):
        text += " The simulation can't yet tell this apart from no change at all."
    others = [r for r in actionable[1:3]]
    if others:
        text += " Next: " + "; ".join(f"{r['change']} for {r['block']}" if r.get("block_id")
                                      else r["change"] for r in others) + "."
    return text


def finish_rows(result: dict) -> dict:
    """Plain words with the diagram's unit (the rows are built before the
    unit-specific words are known)."""
    unit = result.get("unit") or ""
    for row in result.get("levers") or []:
        row["unit_word"] = (" " + unit_in_text(unit)) if unit and row.get("kind") in ("mean", "time") else ""
        row["per_word"] = _per(unit)
        row["_rank_by"] = result.get("rank_by")
        row["plain"] = plain_effect(row)
        row.pop("_rank_by", None)
    result["top"] = top_reading(result)
    return result


# ---------------------------------------------------------------------------
# "Download as Python" (#225): the long-run ranking, standalone
# ---------------------------------------------------------------------------
# The function below goes into the exported script as it is (see
# :func:`export_source`): it needs only numpy and RePyability, and ranks the
# levers by availability as the app's panel does in the long run (the same
# derivatives, steps and effects; the tests run the script against the app).
# Over a window, by cost, with costs to change and the simulated route are
# the app's.


def what_to_improve(rbd, overrides, labels, junctions=(), step=0.1):
    """What to improve, as Reliafy's panel ranks it in the long run (#225):
    each lever RePyability's parameter_sensitivity has, moved one step (a
    ``step`` longer mean life, shorter mean repair time, ...; a count by one)
    the way that raises the availability, ranked by that gain. Returns the
    rows, or None when the diagram has no exact or numerical long run (the
    app simulates it then)."""
    from repyability.rbd._model_utils import parametric_spec

    routes = rbd.analysis_routes()
    if (routes["mean_availability"].route not in ("exact", "numerical")
            or routes["parameter_sensitivity"].route == "refused"):
        print("\nWhat to improve: no exact long run here, so Reliafy simulates each lever's effect: "
              + routes["parameter_sensitivity"].reason)
        return None
    working, broken = overrides["working_nodes"], overrides["broken_nodes"]
    held = set(working) | set(broken) | set(junctions)
    with np.errstate(all="ignore"):
        sens = rbd.parameter_sensitivity(working, broken)
        base = float(rbd.mean_unavailability(**overrides))
    components = dict(rbd._init_args["components"])

    def model_of(key, prefix):
        spec = components.get(key)
        if spec is not None and not isinstance(spec, dict):
            spec = {"reliability": getattr(spec, "reliability", None),
                    "repairability": getattr(spec, "time_to_replace", None)}
        if spec is None:
            return None
        if prefix in ("reliability", "repairability"):
            return spec.get(prefix)
        options = spec.get(prefix.split(".")[0])
        return options.get("duration") if isinstance(options, dict) else None

    rows = []
    for lever in rbd.levers():
        key = lever.key
        members = set(key) if isinstance(key, tuple) else {key}
        if key is not None and members & held:
            continue
        d = float(sens[key][lever.name])
        theta = float(lever.value)
        # A common-cause group's levers are its members' together ("a+b", as
        # the app names them).
        row = {"block": None if key is None else "+".join(map(str, key)) if isinstance(key, tuple) else str(key),
               "label": "System" if key is None else " & ".join(
                   str(labels.get(k, k)) for k in (key if isinstance(key, tuple) else (key,))),
               "lever": lever.name, "value": theta, "derivative": d}
        if lever.discrete:
            row.update(to=theta + 1.0, effect=d, basis="exact")
            rows.append(row)
            continue
        if not np.isfinite(d):
            continue
        prefix, _, param = lever.name.rpartition(".")
        kind, mean = None, None
        model = model_of(key[0] if isinstance(key, tuple) else key, prefix)
        spec = None if model is None or isinstance(model, str) else parametric_spec(model)
        if spec is not None and not spec[3].get("gamma"):
            kind = WHAT_TO_IMPROVE_MEANS.get((getattr(spec[0], "name", ""), param))
            if kind:
                mean = float(spec[0].from_params(list(spec[1]), **spec[3]).mean())
        if kind and not mean:
            kind = None
        per_mean = {None: 1.0, "scale": theta / (mean or 1.0), "rate": -theta / (mean or 1.0),
                    "log": 1.0 / (mean or 1.0), "shift": 1.0}[kind]
        up = d * per_mean >= 0
        k = 1.0 + step if up else 1.0 - step
        if kind == "scale":
            target = theta * k
        elif kind == "rate":
            target = theta / k
        elif kind == "log":
            target = theta + float(np.log(k))
        elif kind == "shift":
            target = theta + (k - 1.0) * mean
        elif theta == 0.0:
            continue
        else:
            target = theta * k
            if lever.name in WHAT_TO_IMPROVE_PROBABILITIES or lever.name.startswith("ccf_"):
                target = min(max(target, 0.0), 1.0)
            if target == theta:
                continue
        effect, basis = None, routes["mean_availability"].route
        if not lever.calendar:
            try:
                with np.errstate(all="ignore"):
                    moved = float(rbd.with_levers({lever: target}).mean_unavailability(**overrides))
                effect = base - moved
            except (ValueError, TypeError, NotImplementedError):
                effect = None
        if effect is None:
            effect, basis = d * (target - theta), "linear"
        row.update(to=target, effect=effect, basis=basis)
        rows.append(row)
    rows.sort(key=lambda r: -r["effect"])
    print(f"\nWhat to improve (long run; each lever {step:.0%} the way that helps, counts by one):")
    for i, r in enumerate(rows[:10], 1):
        where = r["label"]
        print(f"  {i:>2}. {where[:24]:<24} {r['lever']:<28} {r['value']:>12.6g} -> {r['to']:<12.6g}"
              f" {r['effect'] * 100:+.3g} points ({r['basis']})")
    return rows


#: The exported script's copies of the step rules above.
WHAT_TO_IMPROVE_MEANS = MEAN_PARAMETERS
WHAT_TO_IMPROVE_PROBABILITIES = tuple(name for name, (_, _, kind) in _OPTIONS.items() if kind == "probability")


def export_source() -> str:
    """:func:`what_to_improve` and the constants it needs, as "Download as
    Python" copies them into its script."""
    import inspect

    consts = (f"WHAT_TO_IMPROVE_MEANS = {WHAT_TO_IMPROVE_MEANS!r}\n"
              f"WHAT_TO_IMPROVE_PROBABILITIES = {WHAT_TO_IMPROVE_PROBABILITIES!r}\n"
              f"WHAT_TO_IMPROVE_STEP = {DEFAULT_STEP!r}")
    return f"{consts}\n\n\n{inspect.getsource(what_to_improve).rstrip()}\n"
