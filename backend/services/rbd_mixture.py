"""A mixture life on an RBD block: two (or more) failure modes in one
population, e.g. infant mortality and wear-out (#318).

Since RePyability 0.13 (its #227) a surpyval ``MixtureModel`` is taken
wherever a parametric life is, in a ``RepairableRBD`` as well as a
``NonRepairableRBD``: the exact and numerical analyses use its survival
function and mean, and the simulations draw its lives by inverting its
distribution function (imperfect repair draws a life given the age through
its cumulative hazard). Reliafy only turns a block's stored model into that
object; the maths stays in the engines.

A block's mixture life has the shape a saved mixture fit already has
(:func:`backend.fitting._fit_mixture`), whether it was picked from the saved
models or built in the block dialog::

    {"source": "params" | "saved",
     "distribution_id": "mixture",
     "base_distribution_id": "weibull",      # the distribution every mode follows
     "mixture": 2,                            # the number of modes (optional)
     "distribution": "Weibull mixture (2 components)",
     "params": [{"name": "alpha1", "value": 12}, {"name": "beta1", "value": 0.7},
                {"name": "weight1", "value": 0.2},
                {"name": "alpha2", "value": 900}, {"name": "beta2", "value": 3.5},
                {"name": "weight2", "value": 0.8}]}

Each mode ``j`` (from 1) has the base distribution's parameters suffixed
``j`` and its ``weight{j}``, the share of the population that fails by it;
the weights add up to 1. A mixture's parameters have no covariance (the fit
is by expectation-maximisation), so the parameter-uncertainty analyses
refuse it, as RePyability does.
"""

from __future__ import annotations

import math
import re
from typing import Optional

MIXTURE_ID = "mixture"
MAX_MODES = 4
#: How far the weights' sum may stray from 1 before it's refused.
WEIGHT_TOLERANCE = 1e-6

_NAME = re.compile(r"^(.+?)(\d+)$")


class MixtureError(ValueError):
    """A mixture life that can't be built (user-facing text)."""


def is_mixture(model) -> bool:
    """Whether a block's life model is a mixture."""
    return isinstance(model, dict) and model.get("distribution_id") == MIXTURE_ID


def base_id(model: dict) -> Optional[str]:
    """The distribution every mode follows (Weibull when a saved fit doesn't
    say, as the fit's own default)."""
    raw = model.get("base_distribution_id") or (model.get("options") or {}).get("mixture_distribution")
    return str(raw) if raw else "weibull"


def _bases() -> dict:
    from backend import fitting

    return fitting.best_candidates()


def modes(model: dict, where: str) -> tuple[str, list[list[float]], list[float]]:
    """``(base distribution id, each mode's parameters in the base's order,
    the weights)`` of a mixture life, checked. Raises :class:`MixtureError`."""
    bases = _bases()
    base = base_id(model)
    entry = bases.get(base)
    if entry is None:
        raise MixtureError(f"{where}: a mixture's modes must follow one of "
                           f"{', '.join(sorted(bases))} (got {base!r}).")
    names = list(entry["dist"].parameter_names)
    values: dict[int, dict[str, float]] = {}
    for p in model.get("params") or []:
        if not isinstance(p, dict):
            raise MixtureError(f"{where}: params must be a list of {{name, value}}.")
        match = _NAME.match(str(p.get("name") or ""))
        if not match:
            raise MixtureError(f"{where}: mixture parameter '{p.get('name')}' needs its mode's number, e.g. "
                               f"{names[0]}1, weight1.")
        stem, j = match.group(1), int(match.group(2))
        if stem not in names and stem != "weight":
            raise MixtureError(f"{where}: '{p.get('name')}' isn't a parameter of a {entry['name']} mixture "
                               f"({', '.join(names)} and weight, numbered by mode).")
        try:
            value = float(p.get("value"))
        except (TypeError, ValueError):
            raise MixtureError(f"{where}: mixture parameter '{p.get('name')}' must be a number.") from None
        if isinstance(p.get("value"), bool) or not math.isfinite(value):
            raise MixtureError(f"{where}: mixture parameter '{p.get('name')}' must be a finite number.")
        values.setdefault(j, {})[stem] = value
    count = len(values)
    if count < 2:
        raise MixtureError(f"{where}: a mixture needs at least two modes ({names[0]}1 … weight1, "
                           f"{names[0]}2 … weight2).")
    if count > MAX_MODES or sorted(values) != list(range(1, count + 1)):
        raise MixtureError(f"{where}: a mixture's modes are numbered 1 to {count} (at most {MAX_MODES}).")
    rows, weights = [], []
    for j in range(1, count + 1):
        missing = [n for n in [*names, "weight"] if n not in values[j]]
        if missing:
            raise MixtureError(f"{where}: mode {j} of the mixture is missing "
                               f"{', '.join(f'{n}{j}' for n in missing)}.")
        try:
            entry["dist"].from_params([values[j][n] for n in names])  # surpyval checks the parameters
        except Exception as exc:  # noqa: BLE001 - its own message, per mode
            raise MixtureError(f"{where}: mode {j} of the mixture: {exc}") from None
        rows.append([values[j][n] for n in names])
        weights.append(values[j]["weight"])
    if any(not 0.0 < w < 1.0 for w in weights):
        raise MixtureError(f"{where}: each mode's weight (its share of the population) must be between 0 and 1.")
    if abs(sum(weights) - 1.0) > WEIGHT_TOLERANCE:
        raise MixtureError(f"{where}: the modes' weights must add up to 1 (they add up to {sum(weights):.6g}).")
    return base, rows, weights


def to_dict(model: dict, where: str) -> dict:
    """surpyval's ``MixtureModel.to_dict()`` form of a mixture life."""
    base, rows, weights = modes(model, where)
    dist = _bases()[base]["dist"]
    return {"model": "MixtureModel", "dist": dist.name, "m": len(rows), "params": rows, "w": weights}


def build(model: dict, where: str):
    """The surpyval ``MixtureModel`` of a block's mixture life."""
    from surpyval import MixtureModel

    return MixtureModel.from_dict(to_dict(model, where))


def name(base: str, count: int) -> str:
    """The model's display name, as a saved mixture fit's."""
    entry = _bases().get(base) or {}
    return f"{entry.get('name') or base} mixture ({count} components)"


def normalize(model: dict, where: str) -> dict:
    """An inline (compact) mixture life in the persisted shape, checked."""
    base, rows, weights = modes(model, where)
    names = list(_bases()[base]["dist"].parameter_names)
    params = []
    for j, (row, weight) in enumerate(zip(rows, weights), start=1):
        params += [{"name": f"{n}{j}", "value": v} for n, v in zip(names, row)]
        params.append({"name": f"weight{j}", "value": weight})
    out = {"source": "params", "distribution": name(base, len(rows)), "distribution_id": MIXTURE_ID,
           "base_distribution_id": base, "mixture": len(rows), "params": params}
    if model.get("placeholder"):
        out["placeholder"] = True
    return out


def describe(model: dict) -> str:
    """One line for a script's comment: each mode's share and parameters."""
    try:
        base, rows, weights = modes(model, "the block")
    except MixtureError:
        return str(model.get("distribution") or "mixture")
    names = list(_bases()[base]["dist"].parameter_names)
    parts = []
    for row, weight in zip(rows, weights):
        values = ", ".join(f"{n}={v:g}" for n, v in zip(names, row))
        parts.append(f"{weight:.0%} {_bases()[base]['name']}({values})")
    return " + ".join(parts)


def script_expr(model: dict, label: str) -> str:
    """The surpyval expression "Download as Python" writes for it."""
    d = to_dict(model, f"Block '{label}'")
    rows = ", ".join("[" + ", ".join(repr(float(v)) for v in row) + "]" for row in d["params"])
    weights = ", ".join(repr(float(w)) for w in d["w"])
    return (f'surv.MixtureModel.from_dict({{"model": "MixtureModel", "dist": "{d["dist"]}", '
            f'"m": {d["m"]}, "params": [{rows}], "w": [{weights}]}})')


def from_document(m: dict) -> Optional[dict]:
    """A block's mixture life from a RePyability document's surpyval
    ``MixtureModel`` dict, or None when it isn't one Reliafy can hold."""
    if not isinstance(m, dict) or m.get("model") != "MixtureModel":
        return None
    by_name = {v["dist"].name: k for k, v in _bases().items()}
    base = by_name.get(m.get("dist"))
    rows, weights = m.get("params"), m.get("w")
    if base is None or not isinstance(rows, list) or not isinstance(weights, list) or len(rows) != len(weights):
        return None
    names = list(_bases()[base]["dist"].parameter_names)
    params = []
    try:
        for j, (row, weight) in enumerate(zip(rows, weights), start=1):
            if not isinstance(row, list) or len(row) != len(names):
                return None
            params += [{"name": f"{n}{j}", "value": float(v)} for n, v in zip(names, row)]
            params.append({"name": f"weight{j}", "value": float(weight)})
    except (TypeError, ValueError):
        return None
    model = {"source": "params", "distribution": name(base, len(rows)), "distribution_id": MIXTURE_ID,
             "base_distribution_id": base, "mixture": len(rows), "params": params}
    try:
        modes(model, "the block")
    except MixtureError:
        return None
    return model
