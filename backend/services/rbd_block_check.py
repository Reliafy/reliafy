"""Check an exact standby or load-sharing mean by simulation (#326).

RePyability 0.13 (its #233) works out a standby arrangement's or a
load-sharing group's mean life exactly or numerically, and can estimate the
same mean from simulated lives. "Check by simulation" on such a block shows
the two side by side: the exact mean, and the simulated mean with its
confidence interval (``NonRepairableRBD.mean_time_to_failure_interval`` on
the block alone; the interval is the simulation's error only).

Hot standby with one unit running is Reliafy's parallel block, an ordinary
k-out-of-n arrangement; it is checked as RePyability's hot ``StandbyModel``
of the same units, which is exactly that.
"""

from __future__ import annotations

import math
import warnings
from typing import Optional

import numpy as np

from backend.services import rbd_analysis as ra
from backend.services.rbd_analysis import AnalysisError

CHECK_SAMPLES = 20_000
CHECK_SEED = 1
CONFIDENCE = 0.95
TYPES = ("standby", "loadshare")


def _node_model(node: dict, resolve_model):
    """The block's RePyability model (a hot pair as a hot ``StandbyModel``)."""
    from repyability.rbd.standby_node import StandbyModel

    model, _ = ra._node_reliability(node, None, set(), resolve_model)
    if isinstance(model, ra._ReducedModel):
        model = StandbyModel(list(model.models), k=1, dormancy_factor=1.0)
    return model


def check_mean(node: dict, resolve_model=None, unit: str = "",
               samples: int = CHECK_SAMPLES, seed: int = CHECK_SEED) -> dict:
    """The block's exact mean life and its simulated estimate with a
    confidence interval. Raises :class:`AnalysisError` (user-facing)."""
    from repyability import NonRepairableRBD

    if not isinstance(node, dict) or node.get("type") not in TYPES:
        raise AnalysisError("Check by simulation is for standby and load-sharing blocks.")
    label = (node.get("data") or {}).get("label") or node.get("id") or "The block"
    if resolve_model is None and node.get("type") == "loadshare":
        raise AnalysisError(f"“{label}”: its load-life model can't be read here.")
    model = _node_model(node, resolve_model)
    with warnings.catch_warnings(), np.errstate(all="ignore"):
        warnings.simplefilter("ignore")
        try:
            exact = float(model.mean(method="exact"))
        except NotImplementedError as exc:
            raise AnalysisError(f"“{label}” has no exact mean to check: {ra.plain_reason(str(exc))}") from None
        rbd = NonRepairableRBD([("in", "block"), ("block", "out")], {"block": model},
                               input_node="in", output_node="out")
        ci = rbd.mean_time_to_failure_interval(mc_samples=int(samples), confidence=CONFIDENCE, seed=int(seed))
    lower, upper = float(ci.lower), float(ci.upper)
    out = {
        "label": label,
        "unit": (unit or "").strip(),
        "exact_mean": exact if math.isfinite(exact) else None,
        "simulated": {"estimate": float(ci.estimate), "lower": lower, "upper": upper,
                      "standard_error": float(ci.standard_error), "confidence": float(ci.confidence),
                      "n_samples": int(ci.n_samples), "seed": int(seed)},
        "within": bool(math.isfinite(exact) and lower <= exact <= upper),
    }
    out["summary"] = summary(out)
    return out


def _fmt(v: Optional[float]) -> str:
    if v is None or not math.isfinite(v):
        return "—"
    return f"{v:,.4g}" if abs(v) < 1e5 else f"{v:,.0f}"


def summary(result: dict) -> str:
    """One plain sentence for the result."""
    sim = result["simulated"]
    unit = f" {result['unit'].lower()}" if result.get("unit") else ""
    verdict = "inside" if result["within"] else "outside"
    return (f"Exact mean life {_fmt(result['exact_mean'])}{unit}; {sim['n_samples']:,} simulated lives give "
            f"{_fmt(sim['estimate'])}{unit} ({sim['confidence']:.0%} interval {_fmt(sim['lower'])} to "
            f"{_fmt(sim['upper'])}{unit}), so the exact mean is {verdict} the interval.")
