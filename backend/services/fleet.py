"""Fleet failure forecasting.

A fleet is a set of in-service items running against one saved life model.
Each item has its accumulated use (in the model's time unit); the fleet sets
a horizon (N periods, e.g. 12 months) and a default usage rate per period
(with per-item overrides). The forecast answers "how many failures should we
expect in that window?" two ways, user-selectable:

- ``single``  — each item fails at most once: the analytic conditional
  probability p = (F(a+u) − F(a)) / R(a), summed across the fleet, with a
  Poisson-binomial normal interval. Right for "which items are at risk".
- ``renewals`` — failed items are replaced and can fail again: Monte Carlo
  over conditional residual lives (T = qf(F(a) + U·R(a)) − a, then fresh
  lives), counting failures per period. Right for spares demand.

Like RCM evidence, the forecast is computed live on read from the referenced
model — never stored — so it always reflects the model's current fit.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import numpy as np

from backend.db import from_doc, to_doc
from backend.schema import Fleet
from backend.services import access
from backend.services import models as models_service
from backend.services.strategy import _model_from_params, StrategyError


class FleetNotFound(KeyError):
    """Raised when a fleet id is unknown / not visible."""


class FleetValidationError(ValueError):
    """Raised when fleet input fails validation (HTTP 422)."""


METHODS = ("renewals", "single")

_SIMS = 2000
_MAX_DRAWS = 2_000_000  # items × sims ceiling — clamp sims for huge fleets


def _now():
    return datetime.now(timezone.utc)


def _list_query(owner_id, shared=frozenset()):
    query = {"owner_id": {"$in": access.owner_in(owner_id)}}
    if shared:
        return {"$or": [query, {"_id": {"$in": sorted(shared)}}]}
    return query


# ---- Validation ----------------------------------------------------------------

def _clean_settings(settings) -> dict:
    settings = settings or {}
    try:
        periods = int(settings.get("periods", 12))
        default_rate = float(settings.get("default_rate", 0))
    except (TypeError, ValueError):
        raise FleetValidationError("Horizon and usage rate must be numbers.")
    if not 1 <= periods <= 120:
        raise FleetValidationError("The horizon must be between 1 and 120 periods.")
    if default_rate < 0:
        raise FleetValidationError("The usage rate can't be negative.")
    method = settings.get("method", "renewals")
    if method not in METHODS:
        raise FleetValidationError(f"Unknown forecast method '{method}'.")
    label = str(settings.get("period_label") or "months").strip() or "months"
    return {
        "periods": periods,
        "period_label": label[:24],
        "default_rate": default_rate,
        "method": method,
    }


def _clean_items(items) -> list[dict]:
    if not isinstance(items, list):
        raise FleetValidationError("items must be a list.")
    if len(items) > 500:
        raise FleetValidationError("A fleet is limited to 500 items.")
    out = []
    for item in items:
        name = str(item.get("name") or "").strip()
        if not name:
            raise FleetValidationError("Every item needs a name.")
        try:
            current = float(item.get("current_use", 0) or 0)
        except (TypeError, ValueError):
            raise FleetValidationError(f"'{name}': current use must be a number.")
        if current < 0:
            raise FleetValidationError(f"'{name}': current use can't be negative.")
        rate = item.get("rate")
        if rate is not None and rate != "":
            try:
                rate = float(rate)
            except (TypeError, ValueError):
                raise FleetValidationError(f"'{name}': the usage-rate override must be a number.")
            if rate < 0:
                raise FleetValidationError(f"'{name}': the usage rate can't be negative.")
        else:
            rate = None
        nid = item.get("id")
        cleaned = {
            "id": nid if isinstance(nid, str) and nid.strip() else uuid.uuid4().hex,
            "name": name,
            "current_use": current,
            "rate": rate,
        }
        notes = str(item.get("notes") or "").strip()
        if notes:
            cleaned["notes"] = notes
        out.append(cleaned)
    return out


# ---- CRUD ------------------------------------------------------------------------

def create_fleet(db, name: str, model_id: str, owner_id: str) -> Fleet:
    if not (name or "").strip():
        raise FleetValidationError("The fleet needs a name.")
    model = models_service.get_model(db, model_id, owner_id)
    if model is None:
        raise FleetValidationError("Life model not found.")
    if (model.results or {}).get("kind") == "regression":
        raise FleetValidationError(
            "Forecasting needs a plain life distribution — proportional-hazards "
            "models aren't supported yet."
        )
    fleet = Fleet(
        id=uuid.uuid4().hex,
        name=name.strip(),
        owner_id=owner_id,
        model_id=model_id,
        settings=_clean_settings(None),
        items=[],
    )
    db.fleets.insert_one(to_doc(fleet))
    return fleet


def list_fleets(db, owner_id, hidden=frozenset(), shared=frozenset()) -> list[Fleet]:
    return [
        from_doc(Fleet, d)
        for d in db.fleets.find(_list_query(owner_id, shared)).sort("created_at", -1)
        if d["_id"] not in hidden
    ]


def get_fleet(db, fleet_id: str, owner_id=None) -> Fleet | None:
    query = {"_id": fleet_id}
    if owner_id is not None:
        query["owner_id"] = {"$in": access.owner_in(owner_id)}
    return from_doc(Fleet, db.fleets.find_one(query))


def rename_fleet(db, fleet_id: str, name: str, owner_id: str) -> Fleet:
    fleet = get_fleet(db, fleet_id, owner_id)
    if fleet is None or fleet.owner_id != owner_id:
        raise FleetNotFound(fleet_id)
    fleet.name = name
    fleet.updated_at = _now()
    db.fleets.update_one(
        {"_id": fleet_id, "owner_id": owner_id},
        {"$set": {"name": name, "updated_at": fleet.updated_at}},
    )
    return fleet


def delete_fleet(db, fleet_id: str, owner_id: str) -> None:
    result = db.fleets.delete_one({"_id": fleet_id, "owner_id": owner_id})
    if result.deleted_count == 0:
        raise FleetNotFound(fleet_id)


def replace_items(db, fleet_id: str, settings, items, owner_id: str,
                  expected_updated_at: str | None = None) -> Fleet:
    fleet = get_fleet(db, fleet_id, owner_id)
    if fleet is None or fleet.owner_id != owner_id:
        raise FleetNotFound(fleet_id)
    if expected_updated_at and fleet.updated_at is not None:
        if not access.timestamps_match(fleet.updated_at, expected_updated_at):
            raise access.EditConflict()
    fleet.settings = _clean_settings(settings)
    fleet.items = _clean_items(items)
    fleet.updated_at = _now()
    db.fleets.update_one(
        {"_id": fleet_id, "owner_id": owner_id},
        {"$set": {"settings": fleet.settings, "items": fleet.items,
                  "updated_at": fleet.updated_at}},
    )
    return fleet


# ---- Forecast --------------------------------------------------------------------

def compute(db, fleet: Fleet, owners) -> dict:
    """The live forecast for a fleet (never stored)."""
    model = models_service.get_model(db, fleet.model_id, owners)
    if model is None:
        return {"status": "stale",
                "reason": "The linked life model no longer exists."}
    results = model.results or {}
    if results.get("kind") == "regression" or not results.get("params"):
        return {"status": "stale",
                "reason": "The linked model can't be evaluated as a plain distribution."}
    try:
        dist, _name = _model_from_params(
            results.get("distribution_id"), results.get("params"), results.get("extras")
        )
    except StrategyError as exc:
        return {"status": "stale", "reason": str(exc)}

    settings = fleet.settings or {}
    periods = int(settings.get("periods", 12))
    default_rate = float(settings.get("default_rate", 0) or 0)
    method = settings.get("method", "renewals")
    if method == "renewals" and (results.get("extras") or {}).get("p") is not None:
        # LFP: a fraction of the population never fails, so there is no
        # quantile function to draw replacement lives from.
        return {"status": "stale",
                "reason": "The linked model is a limited-failure-population fit - "
                          "renewals forecasting can't sample replacement lives from it. "
                          "Switch this forecast to the 'first failures' method."}
    items = fleet.items or []

    base = {
        "status": "ok",
        "method": method,
        "periods": periods,
        "period_label": settings.get("period_label", "months"),
        "model_name": model.name,
        "model_id": model.id,
        "unit": results.get("unit", ""),
        "n_items": len(items),
    }
    if not items:
        return {**base, "expected": 0.0, "interval": [0.0, 0.0],
                "per_item": [], "per_period": [0.0] * periods}

    ages = np.array([float(it["current_use"]) for it in items])
    rates = np.array([
        float(it["rate"]) if it.get("rate") is not None else default_rate
        for it in items
    ])
    uses = rates * periods  # projected additional use over the whole horizon

    if method == "single":
        return {**base, **_forecast_single(dist, ages, rates, periods, items)}
    return {**base, **_forecast_renewals(dist, ages, uses, rates, periods, items)}


def _cond_prob(dist, age, extra):
    """P(fail within `extra` more use | survived to `age`), clamped to [0,1]."""
    age = np.asarray(age, dtype=float)
    extra = np.asarray(extra, dtype=float)
    sf = np.maximum(np.asarray(dist.sf(age), dtype=float), 1e-12)
    p = (np.asarray(dist.ff(age + extra), dtype=float) - np.asarray(dist.ff(age), dtype=float)) / sf
    return np.clip(np.nan_to_num(p, nan=0.0), 0.0, 1.0)


def _forecast_single(dist, ages, rates, periods, items) -> dict:
    uses = rates * periods
    p = _cond_prob(dist, ages, uses)
    expected = float(p.sum())
    sd = float(np.sqrt(np.maximum(p * (1 - p), 0).sum()))
    interval = [max(0.0, expected - 1.2816 * sd), expected + 1.2816 * sd]

    # Per-period: conditional probability of the first failure landing in each
    # period slice (still at most one failure per item).
    per_period = []
    for k in range(periods):
        a_k = ages + rates * k
        p_k = _cond_prob(dist, ages, rates * (k + 1)) - _cond_prob(dist, ages, rates * k)
        per_period.append(float(np.clip(p_k, 0, None).sum()))

    return {
        "expected": expected,
        "interval": [float(interval[0]), float(interval[1])],
        "per_item": [
            {"id": it["id"], "prob_any": float(p[i]), "expected": float(p[i])}
            for i, it in enumerate(items)
        ],
        "per_period": per_period,
    }


def _forecast_renewals(dist, ages, uses, rates, periods, items) -> dict:
    n = len(items)
    sims = max(200, min(_SIMS, _MAX_DRAWS // max(n, 1)))
    rng = np.random.default_rng(12345)  # deterministic: same fleet -> same forecast

    counts = np.zeros(sims)
    per_item_counts = np.zeros(n)
    per_period = np.zeros(periods)

    for i in range(n):
        a, u, rate = float(ages[i]), float(uses[i]), float(rates[i])
        if u <= 0:
            continue
        sf_a = max(float(dist.sf(a)), 1e-12)
        ff_a = float(dist.ff(a))
        remaining = np.full(sims, u)
        # First failure: conditional residual life given survival to age a.
        draws = np.asarray(dist.qf(ff_a + rng.uniform(size=sims) * sf_a), dtype=float) - a
        draws = np.nan_to_num(draws, nan=np.inf, posinf=np.inf)
        alive = draws < remaining
        item_total = 0.0
        elapsed = np.where(alive, draws, np.inf)
        while alive.any():
            counts[alive] += 1
            item_total += float(alive.sum())
            if rate > 0:
                idx = np.minimum((elapsed[alive] / rate).astype(int), periods - 1)
                np.add.at(per_period, idx, 1.0)
            # Replacement: a fresh unit's full life.
            fresh = np.asarray(dist.qf(rng.uniform(size=int(alive.sum()))), dtype=float)
            fresh = np.nan_to_num(fresh, nan=np.inf, posinf=np.inf)
            nxt = elapsed[alive] + fresh
            elapsed[alive] = nxt
            alive_idx = np.flatnonzero(alive)
            still = nxt < u
            alive[alive_idx] = still
        per_item_counts[i] = item_total / sims

    expected = float(counts.mean())
    p10, p90 = np.percentile(counts, [10, 90])
    prob_any = _cond_prob(dist, ages, uses)
    return {
        "expected": expected,
        "interval": [float(p10), float(p90)],
        "sims": sims,
        "per_item": [
            {"id": it["id"], "expected": float(per_item_counts[i]),
             "prob_any": float(prob_any[i])}
            for i, it in enumerate(items)
        ],
        "per_period": [float(x / sims) for x in per_period],
    }


# ---- API shaping ------------------------------------------------------------------

def headline(fleet: Fleet, forecast: dict) -> str:
    if forecast.get("status") != "ok":
        return "Needs attention — the linked model is unavailable."
    label = forecast.get("period_label", "periods")
    return (
        f"≈ {forecast.get('expected', 0):.1f} failures expected over "
        f"{forecast.get('periods', 0)} {label} ({len(fleet.items or [])} items)"
    )
