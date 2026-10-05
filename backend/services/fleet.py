"""Fleet failure forecasting.

A fleet is a set of in-service items running against one saved model.
Each item has its accumulated use (in the model's time unit); the fleet sets
a horizon (N periods, e.g. 12 months) and a default usage rate per period
(with per-item overrides). The forecast answers "how many failures should we
expect in that window?" two ways, user-selectable:

- ``single``  — each item fails at most once: the analytic conditional
  probability p = (F(a+u) − F(a)) / R(a), summed across the fleet, with the
  exact Poisson-binomial interval (``surpyval.forecast``, #234). Right for
  "which items are at risk". It also runs on a regression or ALT model, each
  item at its own covariates or stress, and can stop counting at a warranty
  limit.
- ``renewals`` — failed items are replaced and can fail again: Monte Carlo
  over conditional residual lives (T = qf(F(a) + U·R(a)) − a, then fresh
  lives), counting failures per period. Right for spares demand.

A fleet on a recurrent-event model (``model_kind`` "recurrent", #235) counts
every failure of repairable items instead: Poisson-process means from the
model's cumulative intensity, with Poisson intervals.

Like RCM evidence, the forecast is computed live on read from the referenced
model — never stored — so it always reflects the model's current fit.
"""

from __future__ import annotations

import math
import uuid
import warnings

import numpy as np
import pandas as pd
import surpyval

from backend.db import from_doc, to_doc
from backend.schema import FLEET_MODEL_COLLECTIONS, FLEET_MODEL_KINDS, Fleet
from backend.services import access
from backend.services import alt as alt_service
from backend.services import models as models_service
from backend.services import recurrent as recurrent_service
from backend.services.strategy import _model_from_params, StrategyError
from backend.units import unit_in_text


class FleetNotFound(KeyError):
    """Raised when a fleet id is unknown / not visible."""


class FleetValidationError(ValueError):
    """Raised when fleet input fails validation (HTTP 422)."""


METHODS = ("renewals", "single")
# What a fleet's model_id is (Fleet.model_kind, see backend.schema): a plain
# life distribution, a regression life model or an ALT model (first failures,
# each item at its own covariates or stress, #234), or a recurrent-event
# (repairable-system) model whose every failure is counted (#235).
MODEL_KINDS = FLEET_MODEL_KINDS
MODEL_COLLECTIONS = FLEET_MODEL_COLLECTIONS  # the collection each kind's model_id lives in
# The repairable forecast's interval: P10–P90, as the life-model forecasts report.
_LEVELS = (0.10, 0.90)
RATE_SOURCES = ("manual", "estimated")

# Per-item fields maintained by the ingest API's rate estimator (never taken
# from client input; carried over when the items are replaced from the UI).
ESTIMATE_KEYS = ("last_reading_use", "last_reading_at", "latest_read_at",
                 "estimated_rate", "estimated_rate_n")

# Wall-clock length of one period, in days, for the recognised period labels
# (singular or plural, any case). Other labels can't convert elapsed time to
# periods, so no usage rate is estimated for them.
PERIOD_DAYS = {
    "day": 1.0,
    "week": 7.0,
    "month": 30.4375,
    "quarter": 91.3125,
    "year": 365.25,
}


def period_days(label) -> float | None:
    """Days per period for a period label, or None when unrecognised."""
    key = str(label or "").strip().lower()
    if key in PERIOD_DAYS:
        return PERIOD_DAYS[key]
    if key.endswith("s") and key[:-1] in PERIOD_DAYS:
        return PERIOD_DAYS[key[:-1]]
    return None


def item_rate(item: dict, default_rate: float, rate_source: str) -> tuple[float, str]:
    """(usage per period, basis) for one item.

    ``estimated`` uses the item's API-estimated rate when it has one, then
    falls back like ``manual``: the item's explicit rate, then the fleet
    default.
    """
    if (rate_source == "estimated" and (item.get("estimated_rate_n") or 0) >= 1
            and item.get("estimated_rate") is not None):
        return float(item["estimated_rate"]), "estimated"
    if item.get("rate") is not None:
        return float(item["rate"]), "manual"
    return float(default_rate), "default"

_SIMS = 2000
_MAX_DRAWS = 2_000_000  # items × sims ceiling — clamp sims for huge fleets


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
    rate_source = settings.get("rate_source") or "manual"
    if rate_source not in RATE_SOURCES:
        raise FleetValidationError(f"Unknown usage-rate source '{rate_source}'.")
    out = {
        "periods": periods,
        "period_label": label[:24],
        "default_rate": default_rate,
        "method": method,
        "rate_source": rate_source,
    }
    # #234: fleet-wide covariate values and a warranty limit, only when set
    # (a fleet without them keeps exactly the settings it had).
    covariates = _clean_covariates(settings.get("covariates"), "The fleet")
    if covariates:
        out["covariates"] = covariates
    for key, what in (("warranty_use", "use"), ("warranty_periods", "periods")):
        value = _optional_number(settings.get(key), f"The warranty limit ({what})")
        if value is not None:
            out[key] = value
    return out


MAX_COVARIATES = 20


def _optional_number(value, label: str) -> float | None:
    """A non-negative number, or None for blank."""
    if value is None or value == "":
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise FleetValidationError(f"{label} must be a number.")
    if not math.isfinite(value) or value < 0:
        raise FleetValidationError(f"{label} must be a finite number, at least 0.")
    return value


def _clean_covariates(values, who: str) -> dict:
    """Covariate (or stress) values by name: numbers stay numbers, anything
    else is a category level; blanks are dropped (the default applies). Whether
    the names and values suit the model is checked when it is evaluated."""
    if values is None or values == "":
        return {}
    if not isinstance(values, dict):
        raise FleetValidationError(f"{who}: covariates must be an object of name: value.")
    if len(values) > MAX_COVARIATES:
        raise FleetValidationError(f"{who}: at most {MAX_COVARIATES} covariates.")
    out = {}
    for name, value in values.items():
        name = str(name).strip()[:80]
        if not name or value is None or (isinstance(value, str) and not value.strip()):
            continue
        if isinstance(value, bool):
            value = str(value).lower()
        if isinstance(value, (int, float)):
            if not math.isfinite(float(value)):
                raise FleetValidationError(f"{who}: '{name}' must be a finite number.")
            out[name] = float(value)
        else:
            out[name] = str(value).strip()[:120]
    return out


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
        service = item.get("next_service_at")
        if service is not None and service != "":
            # The use (age) at which the item is next serviced: a repairable
            # fleet reports the chance of a failure before it.
            try:
                service = float(service)
            except (TypeError, ValueError):
                raise FleetValidationError(f"'{name}': the next service must be a number (the use it's due at).")
            if not np.isfinite(service) or service < 0:
                raise FleetValidationError(f"'{name}': the next service can't be negative.")
            cleaned["next_service_at"] = service
        covariates = _clean_covariates(item.get("covariates"), f"'{name}'")
        if covariates:
            cleaned["covariates"] = covariates
        in_service = _optional_number(item.get("service_periods"), f"'{name}': time in service")
        if in_service is not None:
            cleaned["service_periods"] = in_service
        out.append(cleaned)
    return out


# ---- CRUD ------------------------------------------------------------------------

def create_fleet(db, name: str, model_id: str, owner_id: str, model_kind: str | None = None) -> Fleet:
    """A new fleet on ``model_id``. ``model_kind`` says which collection it's
    in: "alt" (an ALT model), "recurrent" (a recurrent-event model), or "life"
    (the default) for a saved life model — stored as "regression" when that
    model is a regression model."""
    if not (name or "").strip():
        raise FleetValidationError("The fleet needs a name.")
    model_kind = model_kind or "life"
    if model_kind not in MODEL_KINDS:
        raise FleetValidationError(
            f"Unknown model kind '{model_kind}' (life, regression, alt or recurrent).")
    settings = _clean_settings(None)
    if model_kind == "recurrent":
        if recurrent_service.get_model(db, model_id, owner_id) is None:
            raise FleetValidationError("Recurrent model not found.")
    elif model_kind == "alt":
        if alt_service.get_model(db, model_id, owner_id) is None:
            raise FleetValidationError("ALT model not found.")
        # Each item is forecast at its own stress: first failures (#234).
        settings["method"] = "single"
    else:
        model = models_service.get_model(db, model_id, owner_id)
        if model is None:
            raise FleetValidationError("Life model not found.")
        if (model.results or {}).get("kind") == "regression":
            model_kind = "regression"
            settings["method"] = "single"
        else:
            model_kind = "life"
    fleet = Fleet(
        id=uuid.uuid4().hex,
        name=name.strip(),
        owner_id=owner_id,
        model_id=model_id,
        model_kind=model_kind,
        settings=settings,
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
    fleet.updated_at = access.next_updated_at(fleet.updated_at)
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
    query = {"_id": fleet_id, "owner_id": owner_id}
    if expected_updated_at and fleet.updated_at is not None:
        if not access.timestamps_match(fleet.updated_at, expected_updated_at):
            raise access.EditConflict()
        # Conditional on the stamp checked: a save racing in between conflicts.
        query["updated_at"] = fleet.updated_at
    fleet.settings = _clean_settings(settings)
    previous = {it.get("id"): it for it in (fleet.items or [])}
    fleet.items = _clean_items(items)
    for it in fleet.items:
        # Rate-estimator state belongs to the server; keep it across UI saves.
        old = previous.get(it["id"]) or {}
        for key in ESTIMATE_KEYS:
            if key in old:
                it[key] = old[key]
    fleet.updated_at = access.next_updated_at(fleet.updated_at)
    result = db.fleets.update_one(
        query,
        {"$set": {"settings": fleet.settings, "items": fleet.items,
                  "updated_at": fleet.updated_at}},
    )
    if result.matched_count == 0:
        raise access.EditConflict()
    return fleet


# ---- Forecast --------------------------------------------------------------------

def compute(db, fleet: Fleet, owners, *, item_periods: bool = False) -> dict:
    """The live forecast for a fleet (never stored).

    ``item_periods`` adds each item's cumulative chance of failing by the end
    of every period (first-failures forecasts only)."""
    kind = fleet.model_kind
    if kind == "recurrent":
        return _compute_recurrent(db, fleet, owners)
    if kind == "alt":
        return _compute_covariate(db, fleet, owners, None, item_periods)
    # "life" or "regression": a saved life model. Its own fit decides which
    # forecast runs, so a fleet stored as "life" on a model that is now a
    # regression model (or the reverse) still forecasts correctly.
    model = models_service.get_model(db, fleet.model_id, owners)
    if model is None:
        return {"status": "stale",
                "reason": "The linked life model no longer exists."}
    results = model.results or {}
    if results.get("kind") == "regression":
        return _compute_covariate(db, fleet, owners, model, item_periods)
    if not results.get("params"):
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
        "model_kind": "life",
        "unit": results.get("unit", ""),
        "n_items": len(items),
        "rate_source": settings.get("rate_source", "manual"),
    }
    if not items:
        return {**base, "expected": 0.0, "interval": [0.0, 0.0],
                "per_item": [], "per_period": [0.0] * periods}

    chosen = [item_rate(it, default_rate, base["rate_source"]) for it in items]
    ages = np.array([float(it["current_use"]) for it in items])
    rates = np.array([rate for rate, _basis in chosen])
    uses = rates * periods  # projected additional use over the whole horizon

    if method == "single":
        try:
            out = {**base, **_forecast_single(
                dist, ages, rates, periods, items, item_periods=item_periods, unit=base["unit"],
                limits=_period_limits(settings, items, ages, rates, periods))}
        except StrategyError as exc:
            return {"status": "stale", "reason": str(exc)}
    else:
        out = {**base, **_forecast_renewals(dist, ages, uses, rates, periods, items)}
    for row, (rate, basis) in zip(out["per_item"], chosen):
        row["rate_used"] = rate
        row["rate_basis"] = basis  # "estimated" | "manual" | "default"
    return out


# ---- Regression and ALT fleets (#234) ----------------------------------------------
#
# Each item is forecast at its own conditions: covariate values for a
# regression model (load, site, duty), stress values for an ALT model. An
# item's own value wins, then the fleet's default, then (regression only) the
# model's default — the training-data mean of a numeric covariate, the most
# common level of a categorical one, as the model calculator uses.

def _live_covariate_model(db, fleet: Fleet, owners, model):
    """``(live model, fields, info)`` for a regression or ALT fleet, or
    ``(None, None, stale)`` when it can't be evaluated."""
    def stale(reason):
        return None, None, {"status": "stale", "reason": reason}

    if model is None:  # an ALT model
        doc = alt_service.get_model(db, fleet.model_id, owners)
        if doc is None:
            return stale("The linked ALT model no longer exists.")
        try:
            live = alt_service.get_live_model(db, doc.id, owners)
        except Exception:  # noqa: BLE001 - dataset gone, or the refit failed
            live = None
        if live is None:
            return stale("The linked ALT model can't be evaluated (its dataset is no longer available).")
        results = doc.results or {}
        stresses = results.get("stresses") or [
            {"column": c} for c in (doc.spec or {}).get("stress_cols") or []]
        fields = [{"name": s["column"], "label": s.get("label") or s["column"], "type": "number",
                   "default": None} for s in stresses]
        info = {"model_name": doc.name, "model_id": doc.id, "model_kind": "alt",
                "unit": results.get("unit", ""), "model_url": f"/modelling/alt/{doc.id}",
                "notice": results.get("no_finite_maximum")}
        return live, fields, info
    try:
        entry = models_service.get_live_model(db, model.id, owners)
    except Exception:  # noqa: BLE001 - dataset gone, or the refit failed
        entry = None
    if not entry or entry.get("model") is None:
        return stale("The linked regression model can't be evaluated (its dataset is no longer available).")
    results = model.results or {}
    info = {"model_name": model.name, "model_id": model.id, "model_kind": "regression",
            "unit": results.get("unit", ""), "model_url": f"/modelling/m/{model.id}",
            "notice": results.get("no_finite_maximum")}
    return entry["model"], list(entry.get("fields") or []), info


def _covariate_rows(fields: list, settings: dict, items: list) -> list[dict]:
    """Each item's covariate values (``{name: value}``, in the model's field
    order). Raises ``StrategyError`` naming what's missing or wrong."""
    defaults = settings.get("covariates") or {}
    known = [f["name"] for f in fields]
    given = set(defaults)
    for it in items:
        given |= set(it.get("covariates") or {})
    unknown = sorted(given - set(known))
    if unknown:
        raise StrategyError(
            f"Unknown covariate{'s' if len(unknown) != 1 else ''} {', '.join(unknown)}: this model takes "
            f"{', '.join(known) or 'none'}.")
    rows = []
    for it in items:
        own = it.get("covariates") or {}
        row = {}
        for f in fields:
            name, label = f["name"], f.get("label") or f["name"]
            if name in own:
                value = own[name]
            elif name in defaults:
                value = defaults[name]
            elif f.get("default") is not None:
                value = f["default"]
            else:
                raise StrategyError(f"Set {label} for the fleet, or for each item (“{it['name']}” has none).")
            if f.get("type") == "number":
                try:
                    value = float(value)
                except (TypeError, ValueError):
                    raise StrategyError(f"“{it['name']}”: {label} must be a number.") from None
                if not math.isfinite(value):
                    raise StrategyError(f"“{it['name']}”: {label} must be a finite number.")
            else:
                value = str(value)
                if f.get("options") and value not in f["options"]:
                    raise StrategyError(
                        f"“{it['name']}”: {label} must be one of {', '.join(map(str, f['options']))}.")
            row[name] = value
        rows.append(row)
    return rows


def _compute_covariate(db, fleet: Fleet, owners, model, item_periods: bool) -> dict:
    """The live first-failure forecast of a regression or ALT fleet."""
    live, fields, info = _live_covariate_model(db, fleet, owners, model)
    if live is None:
        return info
    if not fields:
        return {"status": "stale", "reason": "The linked model has no covariates to evaluate it at."}
    settings = fleet.settings or {}
    periods = int(settings.get("periods", 12))
    default_rate = float(settings.get("default_rate", 0) or 0)
    method = settings.get("method", "single")
    items = fleet.items or []
    kind = "an ALT" if info["model_kind"] == "alt" else "a regression"
    if method != "single":
        return {"status": "stale",
                "reason": f"The linked model is {kind} model: each item is forecast at its own conditions, "
                          "counting first failures. Switch this forecast to the 'first failures' method."}
    base = {
        "status": "ok",
        "method": method,
        "periods": periods,
        "period_label": settings.get("period_label", "months"),
        "model_name": info["model_name"],
        "model_id": info["model_id"],
        "model_kind": info["model_kind"],
        "model_url": info["model_url"],
        "unit": info["unit"],
        "n_items": len(items),
        "rate_source": settings.get("rate_source", "manual"),
        "covariate_fields": fields,
    }
    notes = []
    if info.get("notice"):
        notes.append(f"{info['notice'].get('message', '')} The forecast extrapolates from that fit, so "
                     "don't rely on it.".strip())
    try:
        rows = _covariate_rows(fields, settings, items)
    except StrategyError as exc:
        return {**base, "status": "stale", "reason": str(exc)}
    if not items:
        return {**base, "expected": 0.0, "interval": [0.0, 0.0], "interval_level": INTERVAL_LEVEL,
                "per_item": [], "per_period": [0.0] * periods,
                **({"warnings": notes} if notes else {})}

    chosen = [item_rate(it, default_rate, base["rate_source"]) for it in items]
    ages = np.array([float(it["current_use"]) for it in items])
    rates = np.array([rate for rate, _basis in chosen])
    names = [f["name"] for f in fields]
    if info["model_kind"] == "alt":
        Z = np.array([[row[n] for n in names] for row in rows], dtype=float).reshape(len(items), len(names))
    else:
        Z = pd.DataFrame(rows, columns=names)
    try:
        out = {**base, **_forecast_single(
            live, ages, rates, periods, items, Z=Z, item_periods=item_periods, unit=info["unit"],
            limits=_period_limits(settings, items, ages, rates, periods))}
    except StrategyError as exc:
        return {**base, "status": "stale", "reason": str(exc)}
    except Exception as exc:  # noqa: BLE001 - SurPyval refusing these values
        return {**base, "status": "stale",
                "reason": f"The linked model couldn't be evaluated at these items' conditions: {exc}"}
    if notes:
        out["warnings"] = [*notes, *(out.get("warnings") or [])]
    for row, values, (rate, basis) in zip(out["per_item"], rows, chosen):
        row["covariates"] = values
        row["rate_used"] = rate
        row["rate_basis"] = basis
    return out


def _cond_prob(dist, age, extra):
    """P(fail within `extra` more use | survived to `age`), clamped to [0,1]."""
    age = np.asarray(age, dtype=float)
    extra = np.asarray(extra, dtype=float)
    sf = np.maximum(np.asarray(dist.sf(age), dtype=float), 1e-12)
    p = (np.asarray(dist.ff(age + extra), dtype=float) - np.asarray(dist.ff(age), dtype=float)) / sf
    return np.clip(np.nan_to_num(p, nan=0.0), 0.0, 1.0)


# The single (first-failure) forecast's interval: P10–P90, the same level as
# the renewals simulation's percentile interval.
INTERVAL_LEVEL = 0.8


class _ItemClock:
    """The fleet's model with every item on its own clock (#234).

    ``surpyval.forecast`` takes one horizon for all units, but each item here
    adds its own use per period. On item ``i``'s clock, ``t`` periods from now
    is ``age_i + rate_i * t`` on the model's time scale, so its chance of
    failing within ``t`` periods is the model's conditional failure probability
    over ``rate_i * t`` more use (at its own covariates ``Z_i`` for a
    regression or ALT model). On this clock every item is at "age" 0 and the
    horizon is in periods; the probabilities, and the exact (Poisson-binomial)
    counting behind the intervals, are SurPyval's.

    ``forecast`` evaluates every unit at once, so the times passed in are one
    per item, lined up with ``age``, ``rate`` and the rows of ``Z``.
    """

    def __init__(self, model, age, rate, Z=None):
        self.model = model
        self.age = np.asarray(age, dtype=float)
        self.rate = np.asarray(rate, dtype=float)
        self._args = () if Z is None else (Z,)

    def sf(self, x):
        t = self.age + self.rate * np.asarray(x, dtype=float)
        return np.asarray(self.model.sf(t, *self._args), dtype=float)

    def cs(self, x, given):
        """Survival of ``x`` more periods given ``given`` survived: the model's
        own conditional survival (exact in the far tail) where it has one."""
        x, given = np.broadcast_arrays(np.asarray(x, dtype=float), np.asarray(given, dtype=float))
        start = self.age + self.rate * given
        if callable(getattr(self.model, "cs", None)):
            return np.asarray(self.model.cs(self.rate * x, start, *self._args), dtype=float)
        return (np.asarray(self.model.sf(start + self.rate * x, *self._args), dtype=float)
                / np.asarray(self.model.sf(start, *self._args), dtype=float))


def _period_limits(settings: dict, items, ages, rates, periods: int):
    """Each item's warranty end, in periods from now, or None without one.

    A use limit ends where the item's use reaches it; a calendar limit ends
    ``warranty_periods`` after it entered service (its ``service_periods``,
    else its use so far at its current rate). Whichever comes first. Past
    the horizon is clamped to just beyond it (``forecast`` takes finite
    limits); at or below 0 the item is out of warranty and counts nothing.
    """
    use_limit = settings.get("warranty_use")
    calendar = settings.get("warranty_periods")
    if use_limit is None and calendar is None:
        return None
    far = float(periods) + 1.0
    out = np.full(len(items), far)
    running = rates > 0
    safe_rates = np.where(running, rates, 1.0)
    if use_limit is not None:
        out = np.minimum(out, np.where(running, (float(use_limit) - ages) / safe_rates, far))
    if calendar is not None:
        served = np.array([
            float(it["service_periods"]) if it.get("service_periods") is not None
            else (float(ages[i]) / float(rates[i]) if rates[i] > 0 else 0.0)
            for i, it in enumerate(items)
        ])
        out = np.minimum(out, float(calendar) - served)
    return np.clip(out, 0.0, far)


def _rows(Z, keep):
    if Z is None:
        return None
    if isinstance(Z, pd.DataFrame):
        return Z.iloc[np.flatnonzero(keep)].reset_index(drop=True)
    return np.asarray(Z)[keep]


def _forecast_single(model, ages, rates, periods, items, *, Z=None, limits=None,
                     item_periods: bool = False, unit: str = "") -> dict:
    """First failures (each item fails at most once) from ``surpyval.forecast``:
    expected failures with an exact Poisson-binomial P10–P90 interval, the same
    per period, and each item's chance of failing (#234)."""
    k = len(items)
    horizon = np.arange(1, periods + 1, dtype=float)
    warranty = limits is not None
    limits = np.full(k, float(periods) + 1.0) if limits is None else np.asarray(limits, dtype=float)
    clock = _ItemClock(model, ages, rates, Z)
    # An item the model gives no chance of still running at its age (past a
    # bounded support, or a survival of exactly 0) can't be conditioned on:
    # it's counted as certain to fail in the first period, if covered.
    with np.errstate(all="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore")
        check = np.asarray(clock.cs(np.ones(k), np.zeros(k)), dtype=float)
    running = rates > 0
    doomed = running & ~np.isfinite(check) & (limits > 0)
    active = running & np.isfinite(check)

    prob = np.zeros((k, periods))
    prob[doomed, :] = 1.0
    n_doomed = int(doomed.sum())
    expected = np.full(periods, float(n_doomed))
    lower, upper = expected.copy(), expected.copy()
    period_expected = np.zeros(periods)
    period_expected[0] = n_doomed
    period_lower, period_upper = period_expected.copy(), period_expected.copy()
    if active.any():
        sub = _ItemClock(model, ages[active], rates[active], _rows(Z, active))
        with np.errstate(all="ignore"), warnings.catch_warnings():
            warnings.simplefilter("ignore")
            fc = surpyval.forecast(sub, age=np.zeros(int(active.sum())), horizon=horizon,
                                   limit=limits[active], alpha_ci=1.0 - INTERVAL_LEVEL)
        if not np.all(np.isfinite(fc.expected)):
            raise StrategyError("The linked model couldn't be evaluated at these items' ages.")
        prob[active] = np.clip(fc.probability, 0.0, 1.0)
        expected += fc.expected
        lower += fc.lower
        upper += fc.upper
        period_expected += fc.period_expected
        period_lower += fc.period_lower
        period_upper += fc.period_upper

    per_item = []
    for i, it in enumerate(items):
        row = {"id": it["id"], "prob_any": float(prob[i, -1]), "expected": float(prob[i, -1])}
        if item_periods:
            row["probability_by_period"] = [float(v) for v in prob[i]]
        per_item.append(row)
    out = {
        "expected": float(expected[-1]),
        "interval": [float(lower[-1]), float(upper[-1])],
        "interval_level": INTERVAL_LEVEL,
        "interval_method": "exact",  # Poisson-binomial, from SurPyval's forecast
        "per_item": per_item,
        "per_period": [float(v) for v in period_expected],
        "per_period_interval": [[float(a), float(b)] for a, b in zip(period_lower, period_upper)],
    }
    if warranty:
        out["out_of_warranty"] = int((limits <= 0).sum())
    if n_doomed:
        names = ", ".join(items[i]["name"] for i in np.flatnonzero(doomed)[:5])
        many = n_doomed != 1
        out["warnings"] = [
            f"{n_doomed} item{'s' if many else ''} ({names}{', …' if n_doomed > 5 else ''}) "
            f"{'are' if many else 'is'} past the age the model says any unit survives to, so "
            f"{'they are' if many else 'it is'} counted as certain to fail in the first period. "
            f"Check the current use is in the model's unit{f' ({unit_in_text(unit)})' if unit else ''}."
        ]
    return out


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


# ---- Repairable fleets: a recurrent-event model (#235) ----------------------------

REPAIRABLE_NOTE = (
    "Every failure is counted: each item is a repairable system, repaired to the state it was in just before "
    "the failure (minimal repair), so its failures follow the model's Poisson process. An item at age a expects "
    "Λ(a + u) − Λ(a) failures over u more use; the fleet's count is Poisson.")


def _compute_recurrent(db, fleet: Fleet, owners) -> dict:
    """The live forecast of a fleet running on a recurrent-event model."""
    doc = recurrent_service.get_model(db, fleet.model_id, owners)
    if doc is None:
        return {"status": "stale", "reason": "The linked recurrent model no longer exists."}
    try:
        live = recurrent_service.get_live_model(db, doc.id, [*owners, doc.owner_id])
    except Exception:  # noqa: BLE001 - dataset gone / no longer fits
        return {"status": "stale",
                "reason": "The linked recurrent model can't be evaluated (its dataset may have been deleted)."}
    if live is None:
        return {"status": "stale", "reason": "The linked recurrent model can't be evaluated."}

    settings = fleet.settings or {}
    periods = int(settings.get("periods", 12))
    default_rate = float(settings.get("default_rate", 0) or 0)
    items = fleet.items or []
    base = {
        "status": "ok",
        "method": "repairable",
        "model_kind": "recurrent",
        "periods": periods,
        "period_label": settings.get("period_label", "months"),
        "model_name": doc.name,
        "model_id": doc.id,
        "model": ((doc.results or {}).get("model") or {}).get("name"),
        "unit": (doc.results or {}).get("unit", ""),
        "n_items": len(items),
        "rate_source": settings.get("rate_source", "manual"),
        "interval_level": "P10–P90",
        "note": REPAIRABLE_NOTE,
    }
    if not items:
        return {**base, "expected": 0.0, "interval": [0.0, 0.0], "per_item": [],
                "per_period": [0.0] * periods, "per_period_interval": [[0.0, 0.0]] * periods}
    chosen = [item_rate(it, default_rate, base["rate_source"]) for it in items]
    ages = np.array([float(it["current_use"]) for it in items])
    rates = np.array([rate for rate, _basis in chosen])
    services = [it.get("next_service_at") for it in items]
    out = {**base, **forecast_repairable(live, ages, rates, periods, items, services)}
    for row, (rate, basis) in zip(out["per_item"], chosen):
        row["rate_used"] = rate
        row["rate_basis"] = basis
    return out


def _poisson_interval(mean) -> np.ndarray:
    """``[[lower, upper], ...]``: the P10–P90 interval of Poisson counts."""
    from scipy.stats import poisson

    mean = np.atleast_1d(np.asarray(mean, dtype=float))
    ends = [np.where(mean > 0, poisson.ppf(q, np.maximum(mean, 1e-300)), 0.0) for q in _LEVELS]
    return np.column_stack(ends)


_FORECAST_GROUPS = 16  # distinct usage rates run through surpyval.forecast; more are vectorised


def forecast_repairable(model, ages, rates, periods: int, items, services=None) -> dict:
    """Expected failures of repairable items under a Poisson-process model.

    Item ``i`` at age ``a_i`` using ``r_i`` per period expects
    ``Λ(a_i + k·r_i) − Λ(a_i)`` failures within ``k`` periods — SurPyval's
    ``forecast`` for a recurrent-event model, run once per distinct rate (its
    horizons are times ahead, the same for every unit). The fleet's count, and
    each period's, is Poisson with the summed mean. ``services[i]`` (the age
    the item is next serviced at, or None) adds its chance of at least one
    failure before then, ``1 − exp(−(Λ(s) − Λ(a)))``."""
    import surpyval

    ages = np.asarray(ages, dtype=float)
    rates = np.asarray(rates, dtype=float)
    k = ages.size
    cum = np.zeros((k, periods))
    steps = np.arange(1, periods + 1, dtype=float)
    distinct = np.unique(rates[rates > 0])  # an idle item adds no use, so no failures
    if distinct.size <= _FORECAST_GROUPS:
        for rate in distinct:
            idx = np.flatnonzero(rates == rate)
            with np.errstate(all="ignore"):
                fc = surpyval.forecast(model, age=ages[idx], horizon=rate * steps, alpha_ci=0.2)
            cum[idx] = np.asarray(fc.per_unit, dtype=float)
    else:
        # Many different rates: the same means, Λ(a + k·r) − Λ(a), in one
        # vectorised pass instead of one forecast per rate.
        busy = np.flatnonzero(rates > 0)
        ahead = ages[busy, None] + rates[busy, None] * steps[None, :]
        with np.errstate(all="ignore"):
            start = np.asarray(model.cif(ages[busy]), dtype=float)
            end = np.asarray(model.cif(ahead.ravel()), dtype=float).reshape(ahead.shape)
        cum[busy] = end - start[:, None]
    cum = np.nan_to_num(cum, nan=0.0, posinf=0.0)
    unit_period = np.diff(np.column_stack([np.zeros(k), cum]), axis=1)
    per_period = unit_period.sum(axis=0)
    expected = float(cum[:, -1].sum())
    interval = _poisson_interval(expected)[0]

    per_item = []
    for i, it in enumerate(items):
        mu = float(cum[i, -1])
        row = {"id": it["id"], "expected": mu, "prob_any": float(-np.expm1(-mu))}
        s = (services or [None] * k)[i]
        if s is not None:
            s = float(s)
            row["next_service_at"] = s
            if s <= ages[i]:
                row["service_overdue"] = True
                row["expected_before_service"] = row["prob_before_service"] = None
            else:
                with np.errstate(all="ignore"):
                    lam = np.asarray(model.cif(np.array([ages[i], s])), dtype=float)
                m_s = float(lam[1] - lam[0]) if np.all(np.isfinite(lam)) else None
                row["expected_before_service"] = m_s
                row["prob_before_service"] = float(-np.expm1(-m_s)) if m_s is not None else None
        per_item.append(row)

    return {
        "expected": expected,
        "interval": [float(interval[0]), float(interval[1])],
        "per_item": per_item,
        "per_period": [float(v) for v in per_period],
        "per_period_interval": [[float(lo), float(hi)] for lo, hi in _poisson_interval(per_period)],
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
