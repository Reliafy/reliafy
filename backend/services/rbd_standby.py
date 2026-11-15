"""k-of-n standby (#84), as plants run it: a standby block with ``k`` units
running and its spares idle, e.g. a 2-of-3 duty/standby pump train with a
warm spare.

The block holds ``k`` (the units that must run, by default 1) beside its
``spares``; it has ``k + spares`` units. RePyability's ``StandbyModel(units,
k)`` and a repairable diagram's standby group (``"standby": {"units", "k"}``)
take any ``k``.

Units that differ: every unit fails by the block's ``model`` unless it has a
model of its own. ``standbyModel`` is every spare's (cold, warm or hot);
``runningModels`` (up to ``k`` entries) and ``spareModels`` (up to
``spares``) give single units their own, ``null`` keeping the default, e.g.
an older duty pump beside a new one, or a smaller spare. Spares are switched
in in order. Up to :data:`MAX_OWN_UNITS` units take a model of their own.

"Chance a spare starts" (``startProb``) is RePyability's ``start_probability``
(0.17): a spare that fails to start is skipped and the next one is tried, on
cold, warm and hot standby alike.

What RePyability 0.18 works out, and so what Reliafy offers free: exactly or
numerically every arrangement of exponential units (a Markov chain), cold
standby of identical units or with at most 2 running, warm or hot standby
with one running, and hot standby whose spares always start. Where it has no
exact reliability (warm standby with ``k >= 2`` of other lives, cold standby
of different units with ``k >= 3``, hot standby with ``k >= 2`` and spares
that may fail to start) the library's own ``is_simulated`` says so, and the
block is refused in its words, with the offer to simulate it: a block with
``"simulate": true`` is then simulated (:class:`SimulatedStandby`, from
``StandbyModel.random``) where the caller allows it (:func:`simulation`;
the builder's Calculate and ``analyse rbd`` do for Pro), and refused
(:class:`SimulationNeedsPro`) elsewhere.

In a repairable diagram the group's units are identical (as before); its
exact long-run values need exponential lives and repairs (RePyability's
Markov chain), otherwise it is simulated, whatever ``k``. There the library's
group takes only a switch that may fail (``switching_probability``).
"""

from __future__ import annotations

import contextlib
import json
import math
from contextvars import ContextVar
from typing import Any, Callable, Iterator, Optional

import numpy as np

from backend.services.rbd_analysis import AnalysisError

MAX_UNITS = 1000
#: The most units (running and spares together) that take a model of their own.
MAX_OWN_UNITS = 12
#: The per-unit model lists on a standby block's data.
OWN_KEYS = ("runningModels", "spareModels")
#: Lifetimes drawn to simulate a block (Calculate, analyse rbd), and to check
#: the diagram (validation: the structure only). The same seed every time, so
#: the same diagram gives the same figures.
SIM_LIVES = 200_000
CHECK_LIVES = 2_000
SIM_SEED = 1
#: Two-sided confidence of the simulated curve's band (backend.levels: 90%).
SIM_CONFIDENCE = 0.90

#: The caller's leave to simulate a block that asks for it: None (refuse),
#: "check" (a few lifetimes: validation reads only the structure) or "run".
_MODE: ContextVar[Optional[str]] = ContextVar("rbd_standby_simulation", default=None)
_SIMULATED: ContextVar[Optional[list]] = ContextVar("rbd_standby_simulated", default=None)


class StandbyLimit(AnalysisError):
    """A non-repairable standby arrangement RePyability can't work out
    exactly (a repairable diagram's standby group isn't one)."""

    nonrepairable_only = True


class SimulationNeedsPro(StandbyLimit):
    """A block set to be simulated, where the caller doesn't simulate it:
    the analysis routes answer 402 for a user without Pro."""

    code = "pro_required"


SIMULATE_OFFER = ("Or simulate it (tick “Simulate this block”, Pro): the reliability is then estimated from "
                  f"{SIM_LIVES:,} simulated lifetimes.")
PRO_MESSAGE = ("Simulating a standby arrangement with no exact reliability is part of Pro. Subscribe to Pro, "
               "change the block so it can be worked out exactly, or download the diagram and run it with "
               "RePyability.")


def operating(data: dict, label: str) -> int:
    """How many of the block's units must run (``k``), by default 1."""
    raw = data.get("k")
    if raw in (None, ""):
        return 1
    if isinstance(raw, bool):
        raise AnalysisError(f"“{label}”: the units running must be a whole number, 1 or more.")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise AnalysisError(f"“{label}”: the units running must be a whole number, 1 or more.") from None
    if value != int(value) or not 1 <= value <= MAX_UNITS:
        raise AnalysisError(f"“{label}”: the units running must be a whole number from 1 to {MAX_UNITS:,}.")
    return int(value)


def spare_count(data: dict) -> int:
    """The block's spares, as every reader has taken them (1 when unset)."""
    try:
        return max(int(data.get("spares") or 1), 0)
    except (TypeError, ValueError):
        return 1


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def start_probability(data: dict) -> float:
    """The block's "Chance a spare starts", 1 when unset or unreadable."""
    raw = data.get("startProb")
    if raw in (None, ""):
        return 1.0
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 1.0
    return value if 0.0 <= value <= 1.0 else 1.0


# ---------------------------------------------------------------------------
# Units with models of their own
# ---------------------------------------------------------------------------
def _own_list(data: dict, key: str) -> list:
    raw = data.get(key)
    return list(raw) if isinstance(raw, (list, tuple)) else []


def own_units(data: dict) -> bool:
    """Whether any single unit has a model of its own."""
    return any(isinstance(m, dict) for key in OWN_KEYS for m in _own_list(data, key))


def own_errors(data: dict, label: str) -> list[str]:
    """What's wrong with the block's per-unit models (empty when nothing)."""
    errors = []
    try:
        k = operating(data, label)
    except AnalysisError:
        return errors  # reported where k is read
    spares = spare_count(data)
    for key, count, what in (("runningModels", k, "running"), ("spareModels", spares, "spare")):
        raw = data.get(key)
        if raw is None:
            continue
        if not isinstance(raw, (list, tuple)):
            errors.append(f"“{label}”: {key} must be a list of models (null keeps the block's model).")
            continue
        if len(raw) > count:
            errors.append(f"“{label}”: {len(raw)} {what} units' models given, but it has "
                          f"{_plural(count, what + ' unit')}.")
        if any(m is not None and not isinstance(m, dict) for m in raw):
            errors.append(f"“{label}”: each entry of {key} is a model or null.")
    if own_units(data) and k + spares > MAX_OWN_UNITS:
        errors.append(f"“{label}”: units take a model of their own only when the block has at most "
                      f"{MAX_OWN_UNITS} units in all; it has {k + spares}.")
    return errors


def unit_specs(data: dict, label: str) -> list:
    """Every unit's model spec, the ``k`` running units first, then the
    spares in the order they're switched in."""
    errors = own_errors(data, label)
    if errors:
        raise AnalysisError(errors[0])
    k = operating(data, label)
    spares = spare_count(data)
    base = data.get("model")
    spare_base = data.get("standbyModel") or base
    running = _own_list(data, "runningModels")
    spare_own = _own_list(data, "spareModels")
    out = [running[i] if i < len(running) and isinstance(running[i], dict) else base for i in range(k)]
    out += [spare_own[j] if j < len(spare_own) and isinstance(spare_own[j], dict) else spare_base
            for j in range(spares)]
    return out


def unit_names(data: dict, label: str) -> list[str]:
    """Each unit's name, as :func:`unit_specs` orders them."""
    k = operating(data, label)
    spares = spare_count(data)
    running = [f"{label} (running unit {i + 1})" if k > 1 else f"{label} (running unit)" for i in range(k)]
    return running + [f"{label} (spare {j + 1})" if spares > 1 else f"{label} (spare)" for j in range(spares)]


def _spec_key(spec) -> str:
    try:
        return json.dumps(spec, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return str(id(spec))


def build_units(data: dict, label: str, build: Callable[[Any, str], Any]) -> list:
    """Every unit's lifetime model (``build(spec, where)``), one object per
    distinct spec, so identical units are recognised as identical."""
    made: dict[str, Any] = {}
    out = []
    for spec, where in zip(unit_specs(data, label), unit_names(data, label)):
        key = _spec_key(spec)
        if key not in made:
            made[key] = build(spec, where)
        out.append(made[key])
    return out


def model_paths(data: dict) -> list[tuple]:
    """Where the block's non-repairable models sit: ``("model",)``,
    ``("standbyModel",)``, ``("runningModels", i)``, ``("spareModels", j)``
    (each set one only)."""
    out: list[tuple] = []
    for key in ("model", "standbyModel"):
        if isinstance(data.get(key), dict):
            out.append((key,))
    for key in OWN_KEYS:
        for i, m in enumerate(_own_list(data, key)):
            if isinstance(m, dict):
                out.append((key, i))
    return out


def get_path(data: dict, path: tuple):
    value = data.get(path[0])
    if len(path) == 1:
        return value
    return value[path[1]] if isinstance(value, (list, tuple)) and path[1] < len(value) else None


def set_path(data: dict, path: tuple, value) -> None:
    """Set the model at ``path`` in ``data`` (copying a list it changes)."""
    if len(path) == 1:
        data[path[0]] = value
        return
    items = _own_list(data, path[0])
    while len(items) <= path[1]:
        items.append(None)
    items[path[1]] = value
    data[path[0]] = items


def map_own_models(data: dict, fn: Callable[[dict, str], Any]) -> dict:
    """``data`` with ``fn(model, where)`` applied to each per-unit model."""
    out = dict(data)
    for key in OWN_KEYS:
        raw = data.get(key)
        if isinstance(raw, (list, tuple)):
            out[key] = [fn(m, f"{key}[{i}]") if isinstance(m, dict) else None for i, m in enumerate(raw)]
    return out


def _percent(value: float) -> str:
    pct = value * 100.0
    return f"{pct:.0f}%" if abs(pct - round(pct)) < 1e-9 else f"{pct:.3g}%"


def describe(data: dict, label: str = "") -> str:
    """The arrangement in plant words: "2 running, 1 warm spare ageing at
    30% while waiting; each spare starts 95% of the time"."""
    try:
        k = operating(data, label or "block")
    except AnalysisError:
        k = 1
    spares = spare_count(data)
    try:
        from backend.services.rbd_analysis import _standby_dormancy

        dormancy = _standby_dormancy(data, label or "block")
    except AnalysisError:
        dormancy = 0.0
    kind = "cold" if dormancy == 0.0 else "hot" if dormancy >= 1.0 else "warm"
    text = f"{k} running, {spares} {kind} spare{'' if spares == 1 else 's'}"
    if kind == "warm":
        text += f" ageing at {_percent(dormancy)} while waiting"
    elif kind == "cold":
        text += " (not ageing while waiting)"
    else:
        text += " (ageing as if running)"
    start = start_probability(data)
    if start < 1.0:
        text += f"; each spare starts {_percent(start)} of the time"
    own = [i + 1 for i, m in enumerate(_own_list(data, "runningModels")) if isinstance(m, dict)]
    spare_own = [j + 1 for j, m in enumerate(_own_list(data, "spareModels")) if isinstance(m, dict)]
    if own or spare_own or isinstance(data.get("standbyModel"), dict):
        parts = []
        if own:
            parts.append("running unit" + ("s " if len(own) > 1 else " ") + ", ".join(map(str, own)))
        if spare_own:
            parts.append("spare" + ("s " if len(spare_own) > 1 else " ") + ", ".join(map(str, spare_own)))
        elif isinstance(data.get("standbyModel"), dict):
            parts.append("the spares")
        many = len(own) + len(spare_own) > 1 or (not spare_own and isinstance(data.get("standbyModel"), dict))
        text += "; " + " and ".join(parts) + (" have their own models" if many else " has its own model")
    return text


# ---------------------------------------------------------------------------
# Exact, numerical, or simulated
# ---------------------------------------------------------------------------
def limit_message(label: str, k: int, dormancy: float, different: bool, start: float = 1.0,
                  why: str = "") -> str:
    """Why a non-repairable standby block has no exact reliability, for an
    arrangement RePyability only simulates (``StandbyModel.is_simulated``),
    in plain words (``why``, the library's own reason, is for logs only)."""
    if 0.0 < dormancy < 1.0 and k >= 2:
        text = (f"“{label}”: warm standby with {_plural(k, 'unit')} running can be worked out exactly only when "
                "every unit has a constant failure rate (exponential). Make the spares cold, run one unit at a "
                "time, or use exponential lives.")
    elif dormancy >= 1.0 and k >= 2 and start < 1.0:
        text = (f"“{label}”: hot standby with {_plural(k, 'unit')} running and spares that may fail to start can "
                "be worked out exactly only when every unit has a constant failure rate (exponential). Set the "
                "chance a spare starts to 100%, run one unit at a time, or use exponential lives.")
    elif dormancy == 0.0 and different and k >= 3:
        text = (f"“{label}”: cold standby with {_plural(k, 'unit')} running and units that differ can be worked "
                "out exactly only when every unit has a constant failure rate (exponential). Give every unit "
                "one model, or run at most 2 units.")
    else:
        text = (f"“{label}”: this standby arrangement has too many different units to work out exactly. Give "
                "more of its units one model, or use fewer spares.")
    return text


def standby_model(data: dict, label: str, units: list, dormancy: float, start: Optional[float] = None):
    """RePyability's ``StandbyModel`` of the block's ``units``, ``k``
    running, as given (simulated or not)."""
    from repyability.rbd.standby_node import StandbyModel

    k = operating(data, label)
    start = start_probability(data) if start is None else start
    return StandbyModel(list(units), k=k, dormancy_factor=dormancy, start_probability=start)


def _refusal(data: dict, label: str, model) -> str:
    k = operating(data, label)
    different = len({_spec_key(s) for s in unit_specs(data, label)}) > 1
    return limit_message(label, k, model.dormancy_factor, different, start_probability(data),
                         getattr(model, "_why", "") or "")


def nonrepairable_model(data: dict, label: str, units: list, dormancy: float, start: Optional[float] = None):
    """The reliability of a non-repairable standby block: RePyability's
    ``StandbyModel`` (exact or numerical), or, where it has neither and
    the block asks to be simulated, a :class:`SimulatedStandby` when the
    caller allows it (:func:`simulation`). Raises :class:`StandbyLimit`
    (with the offer to simulate) or :class:`SimulationNeedsPro`."""
    model = standby_model(data, label, units, dormancy, start)
    if not model.is_simulated:
        return model
    reason = _refusal(data, label, model)
    if data.get("simulate"):
        mode = _MODE.get()
        if mode in ("check", "run"):
            return SimulatedStandby(model, label, reason, CHECK_LIVES if mode == "check" else SIM_LIVES)
        raise SimulationNeedsPro(
            f"{reason} It's set to be simulated: the diagram's reliability (Calculate, analyse rbd) simulates "
            "it with Pro; this analysis needs every block worked out exactly or numerically.")
    raise StandbyLimit(f"{reason} {SIMULATE_OFFER}")


def is_simulation_only(data: dict, label: str, units: list, dormancy: float) -> bool:
    """Whether RePyability only simulates this arrangement."""
    return bool(standby_model(data, label, units, dormancy).is_simulated)


@contextlib.contextmanager
def simulation(mode: Optional[str]) -> Iterator[list]:
    """Within it, blocks set to be simulated are (``"run"``), or are taken
    with a few lifetimes for the diagram's structure (``"check"``). Yields
    the list of :class:`SimulatedStandby` blocks built."""
    built: list = []
    t1 = _MODE.set(mode)
    t2 = _SIMULATED.set(built)
    try:
        yield built
    finally:
        _MODE.reset(t1)
        _SIMULATED.reset(t2)


def simulated_now() -> list:
    """The blocks simulated so far within :func:`simulation`."""
    return list(_SIMULATED.get() or [])


def dkw_half_width(n: int, confidence: float = SIM_CONFIDENCE) -> float:
    """The half-width of a simultaneous band on an empirical survival curve
    of ``n`` lifetimes (Dvoretzky-Kiefer-Wolfowitz, two-sided)."""
    return math.sqrt(math.log(2.0 / (1.0 - confidence)) / (2.0 * n))


class SimulatedStandby:
    """A standby block RePyability has no exact or numerical reliability
    for, its reliability the share of ``lives`` simulated lifetimes still
    running (``StandbyModel.random``, seeded): every point of the curve is
    within :func:`dkw_half_width` of the truth at 90%, all at once."""

    def __init__(self, model, label: str, reason: str, lives: int = SIM_LIVES, seed: int = SIM_SEED):
        self.model = model
        self.label = label
        self.reason = reason
        self.lives = int(lives)
        draws = np.sort(np.asarray(model.random(self.lives, seed=seed), dtype=float))
        self._draws = draws
        self._hi = float(np.quantile(draws, 0.99)) if draws.size else 1.0
        from backend.services.rbd_analysis import _DistName

        self.dist = _DistName("SimulatedStandby")
        built = _SIMULATED.get()
        if built is not None:
            built.append(self)

    @property
    def half_width(self) -> float:
        return dkw_half_width(self.lives)

    def sf(self, x, *args, **kwargs):
        x = np.asarray(x, dtype=float)
        failed = np.searchsorted(self._draws, x, side="right")
        out = 1.0 - failed / float(self.lives)
        return out if out.ndim else float(out)

    def ff(self, x, *args, **kwargs):
        return 1.0 - self.sf(x)

    def cs(self, x, X):
        from repyability.utils.wrappers import conditional_survival

        return conditional_survival(self, x, X)

    def random(self, size, seed=None):
        return self.model.random(size, seed=seed)

    def mean(self, *args, **kwargs) -> float:
        return float(self._draws.mean())

    def summary(self) -> dict:
        return {"label": self.label, "lives": self.lives, "half_width": round(self.half_width, 4),
                "reason": self.reason}


def simulated_summary(blocks: list) -> Optional[dict]:
    """What a result says of its simulated blocks (None when none)."""
    runs = [b for b in blocks if b.lives >= SIM_LIVES]
    if not runs:
        return None
    names = ", ".join(f"“{b.label}”" for b in runs)
    half = max(b.half_width for b in runs)
    return {
        "blocks": [b.summary() for b in runs],
        "confidence": SIM_CONFIDENCE,
        "note": (f"{names} {'has' if len(runs) == 1 else 'have'} no exact or numerical reliability, so "
                 f"{'it was' if len(runs) == 1 else 'they were'} simulated ({runs[0].lives:,} lifetimes each, "
                 f"the same seed every time): each simulated block's reliability is within ±{half:.3f} of the "
                 f"truth at every time ({SIM_CONFIDENCE:.0%} two-sided). The rest of the diagram is exact."),
    }


def limit_for(data: dict, label: str) -> Optional[str]:
    """Why a non-repairable standby block (its stored data) has no exact
    reliability, or None when it has one (or its lives can't be read here).
    Blocks set to be simulated count as having none too."""
    from backend.services import rbd_analysis as ra

    try:
        dormancy = ra._standby_dormancy(data, label)
        units = build_units(data, label, lambda spec, where: ra._build_distribution(spec, where))
        model = standby_model(data, label, units, dormancy)
        if model.is_simulated:
            return _refusal(data, label, model)
    except Exception:  # noqa: BLE001 - unreadable lives are reported where they're built
        return None
    return None


def from_document(k, units: int) -> Optional[int]:
    """A standby group's ``k`` from a RePyability document, or None when it
    isn't a whole number from 1 to fewer than its units."""
    if isinstance(k, bool):
        return None
    try:
        value = float(k)
    except (TypeError, ValueError):
        return None
    if value != int(value) or not 1 <= value < units:
        return None
    return int(value)


def own_from_units(models: list, k: int) -> dict:
    """Builder data for a standby block whose units are ``models`` (``k``
    running first, then the spares in order), as an import reads them:
    ``model`` the first running unit's, and any unit that differs from it
    its own entry (``standbyModel`` when every spare shares one)."""
    if not models:
        return {}
    base = models[0]
    running = models[:k]
    spares = models[k:]
    out: dict = {"model": base}
    if any(m != base for m in running):
        out["runningModels"] = [None if m == base else m for m in running]
    if spares and all(m == spares[0] for m in spares):
        if spares[0] != base:
            out["standbyModel"] = spares[0]
    elif spares:
        out["spareModels"] = [None if m == base else m for m in spares]
    return out


def route_of(node: dict, resolve_model=None) -> dict:
    """How a standby block (as the builder would save it) is worked out, for
    its dialog: ``route`` "exact" or "numerical" (free), or "simulated"
    (RePyability has neither: ``reason`` says why in plain words; Pro, when
    the block is set to be simulated), with the arrangement in words.
    Raises :class:`AnalysisError` for a block that can't be read."""
    from backend.services import rbd_analysis as ra
    from repyability.rbd import routes

    data = (node or {}).get("data") or {}
    label = data.get("label") or (node or {}).get("id") or "The block"
    units = build_units(data, label, lambda spec, where: ra._build_distribution(spec, where, resolve_model))
    dormancy = ra._standby_dormancy(data, label)
    k = operating(data, label)
    start = start_probability(data)
    out = {"label": label, "words": describe(data, label), "units": len(units),
           "own_units_max": MAX_OWN_UNITS, "simulate": bool(data.get("simulate"))}
    if k == 1 and dormancy >= 1.0 and start == 1.0:
        return {**out, "route": "exact", "how": "every unit runs from the start, any one keeping it up"}
    model = standby_model(data, label, units, dormancy, start)
    if model.is_simulated:
        return {**out, "route": "simulated", "reason": _refusal(data, label, model), "pro": True,
                "lives": SIM_LIVES}
    route, how = routes.model_route(model)
    return {**out, "route": "exact" if route == routes.EXACT else "numerical", "how": how}
