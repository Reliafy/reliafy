"""Adjust a life model for conditions: a known hazard ratio (SurPyval's ``hr``).

A model with hazard ratio ``hr`` has ``hr`` times the hazard of the model it
came from at every age, so its reliability is the original's raised to ``hr``:
``R(t) = R0(t) ** hr``. It keeps the original's shape. A part run hotter than
the fleet it was fitted on, a harsher site, a handbook's environment factor:
"1.5 times the hazard" is ``hr = 1.5``.

The result is a new saved model, "<name> (×1.5 hazard)", that records the
model it came from and the ratio (``spec.adjusted``); the original is left as
it is. Everything that takes a model (RBD blocks, positions, forecasts,
Optimise, missions) rebuilds it with ``hr`` through ``fitting.surpyval_extras``.

The numbers are SurPyval's own. A fitted original keeps its fit: the adjusted
model is the same fit with ``hr`` set (SurPyval's ``to_dict`` / ``from_dict``),
so its Wald bounds hold ``hr`` fixed as a known constant. SurPyval refuses a
bound on the mean life of a model with a hazard ratio; that is said in words
(``life_bounds.HR_MEAN_NOTE``), never worked out here.

A life scale ("lasts about 2/3 as long") is a hazard ratio only where it is
exact: a Weibull (``hr = k ** -beta``) or an exponential (``hr = 1 / k``), with
no offset, limited failure population or zero inflation. Anywhere else only a
hazard ratio is taken, and the refusal says why.
"""

from __future__ import annotations

import copy
import math
import uuid
from typing import Optional

import numpy as np
import surpyval

from backend import fitting, life_bounds
from backend.db import to_doc
from backend.schema import Model
from backend.services import models as models_service

#: The hazard ratios taken: a positive number, not absurdly far from 1.
HR_MIN, HR_MAX = 0.001, 1000.0
#: What the adjustment assumes, said wherever it's shown.
SAME_SHAPE = ("It assumes the conditions multiply the hazard by the same factor at every age, so the shape "
              "stays the same: only how soon failures come changes.")


class AdjustError(ValueError):
    """The model can't be adjusted, or the ratio isn't one: the message says what to do."""


def _dist_id(model: Model) -> str:
    return (model.results or {}).get("distribution_id") or model.distribution_id or ""


def why_not(model: Model) -> Optional[str]:
    """Why ``model`` can't be adjusted, in words, or None when it can: a single parametric
    distribution (fitted to data or made from parameters)."""
    results = model.results or {}
    spec = model.spec or {}
    if model.kind != "distribution" or _dist_id(model) not in fitting.DISTRIBUTIONS:
        return ("Adjust for conditions works on a single-distribution life model (Weibull, exponential, "
                "lognormal and the like), not on this kind of model.")
    if spec.get("method") == "bayesian_update" or results.get("method") == "bayesian_update":
        return "A Bayesian update can't be adjusted yet: adjust its prior model, then update that."
    if spec.get("per_demand") or not results.get("params"):
        return "This model has no distribution parameters to adjust."
    if results.get("no_finite_maximum"):
        return "This fit has no finite maximum, so its numbers aren't estimates to adjust. Refit it first."
    return None


def check_hr(value) -> float:
    """``value`` as a hazard ratio, or AdjustError in words."""
    try:
        hr = float(value)
    except (TypeError, ValueError):
        raise AdjustError("The hazard ratio must be a number above 0, e.g. 1.5 for harsher conditions.") from None
    if not math.isfinite(hr) or hr <= 0:
        raise AdjustError("The hazard ratio must be a number above 0, e.g. 1.5 for harsher conditions.")
    if not HR_MIN <= hr <= HR_MAX:
        raise AdjustError(f"Give a hazard ratio between {HR_MIN:g} and {HR_MAX:g}.")
    return hr


def _param(results: dict, name: str) -> Optional[float]:
    p = next((p for p in results.get("params") or [] if p.get("name") == name), None)
    try:
        return float(p["value"]) if p else None
    except (TypeError, ValueError):
        return None


def life_scale_note(model: Model) -> Optional[str]:
    """Why a life scale isn't exact for ``model`` (so only a hazard ratio is taken), or None
    when it is: a Weibull or an exponential with no offset, LFP or zero inflation."""
    results = model.results or {}
    dist_id = _dist_id(model)
    extras = {k: v for k, v in (results.get("extras") or {}).items() if k in ("gamma", "p", "f0") and v is not None}
    if dist_id not in ("weibull", "exponential"):
        name = (fitting.DISTRIBUTIONS.get(dist_id) or {}).get("name") or dist_id
        return (f"A {name} model's life doesn't scale by a fixed hazard ratio, so give the hazard ratio itself. "
                "\"Lasts k times as long\" is exact only for a Weibull or an exponential.")
    if extras:
        return ("This model has an offset, a limited failure population or zero inflation, so its life doesn't "
                "scale by a fixed hazard ratio: give the hazard ratio itself.")
    return None


def hr_for_life_scale(model: Model, scale) -> float:
    """The hazard ratio that makes ``model`` last ``scale`` times as long (2/3: about two thirds as long),
    exact for a Weibull (``scale ** -beta``) or an exponential (``1 / scale``). AdjustError elsewhere."""
    note = life_scale_note(model)
    if note:
        raise AdjustError(note)
    try:
        k = float(scale)
    except (TypeError, ValueError):
        raise AdjustError("The life scale must be a number above 0, e.g. 0.67 for lasting about 2/3 as long.") from None
    if not math.isfinite(k) or k <= 0:
        raise AdjustError("The life scale must be a number above 0, e.g. 0.67 for lasting about 2/3 as long.")
    results = model.results or {}
    if _dist_id(model) == "exponential":
        return check_hr(1.0 / k)
    beta = _param(results, "beta")
    if beta is None or not beta > 0:
        raise AdjustError("This Weibull has no shape β to convert a life scale with: give the hazard ratio itself.")
    return check_hr(k ** (-beta))


def _hr_of(model: Model) -> float:
    try:
        return float(((model.results or {}).get("extras") or {}).get("hr") or 1.0)
    except (TypeError, ValueError):
        return 1.0


def _live_of(db, model: Model, owners):
    """The parent's live SurPyval model (its fit, or built from its parameters)."""
    if models_service.is_params_only(model):
        results = model.results or {}
        entry = fitting.DISTRIBUTIONS[_dist_id(model)]
        return entry["dist"].from_params(fitting.param_values(_dist_id(model), results["params"]),
                                         **fitting.surpyval_extras(results.get("extras")))
    entry = models_service.get_live_model(db, model.id, owners)
    if not entry or entry.get("model") is None:
        raise AdjustError("This model's fit couldn't be brought back (its data may be gone), so it can't be adjusted.")
    return entry["model"]


def with_hr(live, hr: float):
    """``live`` with hazard ratio ``hr``: for a fit, the same fit (data, covariance) with ``hr``
    set, by SurPyval's own save and load (``to_dict`` / ``from_dict``), so its bounds hold ``hr``
    fixed; for a model from parameters, ``with_params(..., hr=)``."""
    if getattr(live, "method", None) == "given parameters" or getattr(live, "data", None) is None:
        return live.with_params(live.params, hr=hr)
    saved = live.to_dict()
    saved["hr"] = hr
    return surpyval.from_dict(saved)


def _b10_and_mean(life: Optional[dict]) -> dict:
    """{b10, b10_lower, mean, mean_lower, mean_note} from a life summary."""
    life = life or {}
    b10 = next((b for b in life.get("b_lives") or [] if b.get("label") == "B10"), {}) or {}
    mttf = life.get("mttf") or {}
    return {"b10": b10.get("value"), "b10_lower": b10.get("lower"),
            "mean": mttf.get("value"), "mean_lower": mttf.get("lower"),
            **({"mean_note": mttf["note"]} if mttf.get("note") else {}),
            "bounds_note": life.get("bounds_note")}


def words(hr: float) -> str:
    """The ratio in words: "1.5 times the hazard (harsher)"."""
    if abs(hr - 1.0) < 1e-12:
        return "the same hazard (no change)"
    how = "harsher" if hr > 1 else "milder"
    return f"{hr:.4g} times the hazard at every age ({how} conditions)"


def default_name(parent_name: str, hr: float) -> str:
    return f"{parent_name} (×{hr:.4g} hazard)"[:200]


def _resolve_hr(model: Model, hazard_ratio=None, life_scale=None) -> tuple[float, Optional[float]]:
    if (hazard_ratio is None) == (life_scale is None):
        raise AdjustError("Give a hazard ratio (e.g. 1.5 for 1.5 times the hazard), or a life scale (e.g. 0.67 for "
                          "lasting about 2/3 as long), not both.")
    if hazard_ratio is not None:
        return check_hr(hazard_ratio), None
    return hr_for_life_scale(model, life_scale), float(life_scale)


def preview(db, model: Model, owners, hazard_ratio=None, life_scale=None) -> dict:
    """What adjusting ``model`` does, saving nothing: the ratio, B10 and mean life before and
    after (with their 90% one-sided lower bounds where SurPyval gives them) and the words."""
    reason = why_not(model)
    if reason:
        raise AdjustError(reason)
    hr, scale = _resolve_hr(model, hazard_ratio, life_scale)
    live = _live_of(db, model, owners)
    after = with_hr(live, _hr_of(model) * hr)
    no_max = bool((model.results or {}).get("no_finite_maximum"))
    unit = (model.results or {}).get("unit") or (model.spec or {}).get("unit") or ""
    return {
        "model_id": model.id, "name": model.name, "hazard_ratio": hr,
        **({"life_scale": scale} if scale is not None else {}),
        "total_hazard_ratio": _hr_of(model) * hr,
        "unit": unit,
        "words": words(hr),
        "assumes": SAME_SHAPE,
        "life_scale_note": life_scale_note(model),
        "before": _b10_and_mean(life_bounds.life_for(live, no_max)),
        "after": _b10_and_mean(life_bounds.life_for(after, no_max)),
        "default_name": default_name(model.name, hr),
        "bound": "90% one-sided lower bounds on the B10 and the mean life",
    }


def adjust(db, model: Model, owners, owner_id: str, hazard_ratio=None, life_scale=None,
           name: Optional[str] = None) -> Model:
    """Save ``model`` adjusted by a hazard ratio as a new model of ``owner_id``'s; the parent is
    unchanged. Raises AdjustError in words."""
    reason = why_not(model)
    if reason:
        raise AdjustError(reason)
    hr, scale = _resolve_hr(model, hazard_ratio, life_scale)
    total = _hr_of(model) * hr
    live = _live_of(db, model, owners)
    child = with_hr(live, total)
    parent_results = model.results or {}
    no_max = bool(parent_results.get("no_finite_maximum"))
    grid = np.asarray(((parent_results.get("functions") or {}).get("curves") or {}).get("x") or [], dtype=float)
    if grid.size < 2:
        grid = np.asarray(fitting._function_curves(child)["x"], dtype=float)
    record = {"from_model_id": model.id, "from_name": model.name, "hazard_ratio": hr, "total_hazard_ratio": total,
              **({"life_scale": scale} if scale is not None else {}), "words": words(hr), "assumes": SAME_SHAPE}
    extras = {**(parent_results.get("extras") or {}), "hr": total}
    params_only = models_service.is_params_only(model)
    if params_only:
        results = fitting.result_from_params(_dist_id(model), parent_results["params"], extras,
                                             parent_results.get("unit") or (model.spec or {}).get("unit"))
        serialized = None
    else:
        results = copy.deepcopy(parent_results)
        cache_id = fitting.store_live(child, grid)
        results["functions"] = {"meta": fitting.FUNCTIONS, "curves": fitting._eval_functions(child, grid),
                                "model_id": cache_id}
        results["extras"] = extras
        results["extra_params"] = [{"name": fitting._EXTRA_LABELS[k], "value": v}
                                   for k, v in extras.items() if k in fitting._EXTRA_LABELS]
        # The probability plot and goodness of fit are the original fit's to its data: the
        # adjusted curve isn't fitted to those points, so neither is shown with it.
        results["plot"] = None
        results["gof"] = []
        life = life_bounds.life_for(child, no_max)
        if life:
            results["life"] = life
        else:
            results.pop("life", None)
        for key in ("selection", "randomness_note", "validation"):
            results.pop(key, None)
        serialized = {"model": child.to_dict(), "grid": grid.tolist(), "fields": []}
    results["adjusted"] = record
    spec = copy.deepcopy(model.spec or {})
    spec["adjusted"] = record
    notes = (f"Adjusted for conditions from “{model.name}”: {words(hr)}. {SAME_SHAPE}")
    if (spec.get("notes") or "").strip():
        notes += f" Its notes: {spec['notes'].strip()}"
    spec["notes"] = notes[:4000]
    for key in ("library_record_id", "library_component_id"):
        spec.pop(key, None)
    doc = Model(
        id=uuid.uuid4().hex,
        name=(name or "").strip()[:200] or default_name(model.name, hr),
        owner_id=owner_id,
        dataset_id=model.dataset_id or "",
        kind="distribution",
        distribution_id=_dist_id(model),
        spec=spec,
        results=fitting._json_safe(results),
        serialized=serialized,
        surpyval_version=getattr(surpyval, "__version__", None),
        status="ready",
    )
    db.models.insert_one(to_doc(doc))
    if not params_only:
        models_service.keep_live(doc.id, results["functions"]["model_id"])
    return doc


def summary(doc: Model, before: Optional[dict] = None) -> dict:
    """The saved adjusted model in brief, for the tools: its id, name, the ratio and its B10 and mean."""
    results = doc.results or {}
    return {"model_id": doc.id, "name": doc.name, "adjusted": results.get("adjusted"),
            "unit": results.get("unit") or "", "after": _b10_and_mean(results.get("life")),
            **({"before": before} if before else {})}
