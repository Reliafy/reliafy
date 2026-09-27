"""Fleet failure-forecast API."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse

from backend.db import get_session
from backend.schema import Fleet, TrackedFleet
from backend.services import billing as billing_service
from backend.services import degradation as degradation_service
from backend.services import fleet as fleet_service
from backend.services import fleet_alerts as alerts_service
from backend.services import samples as samples_service
from backend.services import shares as shares_service
from backend.services import access as access_service
from backend.services.access import AccessCtx, get_access

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/fleet")

_CAP_MSG = (
    "You've reached the free-plan limit of 1 failure forecast. "
    "Upgrade to Pro for unlimited forecasts."
)


def _summary(fleet, ctx: AccessCtx, forecast: dict | None = None) -> dict:
    out = {
        "id": fleet.id,
        "name": fleet.name,
        "model_id": fleet.model_id,
        "settings": fleet.settings,
        "n_items": len(fleet.items or []),
        "is_sample": samples_service.is_sample(fleet.owner_id),
        "read_only": not access_service.can_write(ctx, fleet.owner_id),
        "updated_by": (fleet.updated_by or {}).get("name"),
        "created_at": fleet.created_at.isoformat(),
        "updated_at": fleet.updated_at.isoformat(),
    }
    if forecast is not None:
        out["headline"] = fleet_service.headline(fleet, forecast)
        out["expected"] = forecast.get("expected")
        out["forecast_status"] = forecast.get("status")
    return out


@router.post("/fleets")
def create_fleet(
    name: str = Body(...),
    model_id: str = Body(...),
    session=Depends(get_session),
    ctx: AccessCtx = Depends(get_access),
) -> JSONResponse:
    denied = access_service.workspace_write_denial(ctx)
    if denied is not None:
        status, payload = denied
        return JSONResponse(status_code=status, content=payload)
    if (
        ctx.is_personal
        and not billing_service.is_admin_user(ctx.user)
        and billing_service.would_exceed_cap(session, ctx.uid, "fleets")
    ):
        return JSONResponse(status_code=402, content={"detail": _CAP_MSG, "code": "cap", "upgrade": True})
    try:
        fleet = fleet_service.create_fleet(session, name, model_id, ctx.write_owner)
    except fleet_service.FleetValidationError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    access_service.stamp_editor(session, "fleets", fleet.id, ctx)
    return JSONResponse(content=_summary(fleet, ctx))


@router.get("/fleets")
def list_fleets(session=Depends(get_session), ctx: AccessCtx = Depends(get_access)) -> dict:
    shared_by = shares_service.shared_by_map(session, ctx.uid, "fleets") if ctx.is_personal else {}
    out = []
    for fleet in fleet_service.list_fleets(session, ctx.list_owners, ctx.hidden, shared=set(shared_by)):
        forecast = fleet_service.compute(session, fleet, [*ctx.read_owners, fleet.owner_id])
        row = _summary(fleet, ctx, forecast)
        if fleet.id in shared_by:
            row["shared_by"] = shared_by[fleet.id]
        out.append(row)
    return {"fleets": out}


@router.get("/fleets/{fleet_id}")
def get_fleet(
    fleet_id: str, session=Depends(get_session), ctx: AccessCtx = Depends(get_access)
) -> JSONResponse:
    fleet, via_share = access_service.fetch_readable(session, "fleets", Fleet, fleet_id, ctx)
    if fleet is None or fleet.id in ctx.hidden:
        return JSONResponse(status_code=404, content={"detail": "Fleet not found."})
    forecast = fleet_service.compute(session, fleet, [*ctx.read_owners, fleet.owner_id])
    payload = {**_summary(fleet, ctx, forecast), "items": fleet.items, "forecast": forecast}
    if via_share:
        payload["shared_by"] = shares_service.shared_by_for(session, ctx.uid, fleet.id)
    return JSONResponse(content=payload)


@router.patch("/fleets/{fleet_id}")
def rename_fleet(
    fleet_id: str,
    name: str = Body(..., embed=True),
    session=Depends(get_session),
    ctx: AccessCtx = Depends(get_access),
) -> JSONResponse:
    existing, _ = access_service.fetch_readable(session, "fleets", Fleet, fleet_id, ctx)
    if existing is not None:
        denial = access_service.write_denial(ctx, existing.owner_id)
        if denial:
            status, payload = denial
            return JSONResponse(status_code=status, content=payload)
    try:
        fleet = fleet_service.rename_fleet(session, fleet_id, name, ctx.write_owner)
        access_service.stamp_editor(session, "fleets", fleet.id, ctx)
    except fleet_service.FleetNotFound:
        return JSONResponse(status_code=404, content={"detail": "Fleet not found."})
    return JSONResponse(content=_summary(fleet, ctx))


@router.delete("/fleets/{fleet_id}")
def delete_fleet(
    fleet_id: str, session=Depends(get_session), ctx: AccessCtx = Depends(get_access)
) -> JSONResponse:
    fleet, _ = access_service.fetch_readable(session, "fleets", Fleet, fleet_id, ctx)
    if fleet is None or fleet.id in ctx.hidden:
        return JSONResponse(status_code=404, content={"detail": "Fleet not found."})
    if access_service.can_write(ctx, fleet.owner_id):
        try:
            fleet_service.delete_fleet(session, fleet_id, ctx.write_owner)
            alerts_service.delete_for_fleet(session, fleet_id)
        except fleet_service.FleetNotFound:
            return JSONResponse(status_code=404, content={"detail": "Fleet not found."})
    elif samples_service.is_sample(fleet.owner_id) or access_service.is_shared_with(session, ctx.uid, fleet_id):
        samples_service.hide_sample(session, ctx.uid, fleet_id)
    else:
        status, payload = access_service.write_denial(ctx, fleet.owner_id)
        return JSONResponse(status_code=status, content=payload)
    return JSONResponse(content={"ok": True})


@router.put("/fleets/{fleet_id}/items")
def put_items(
    fleet_id: str,
    settings: dict = Body(default={}),
    items: list = Body(default=[]),
    expected_updated_at: str | None = Body(default=None),
    session=Depends(get_session),
    ctx: AccessCtx = Depends(get_access),
) -> JSONResponse:
    existing, _ = access_service.fetch_readable(session, "fleets", Fleet, fleet_id, ctx)
    if existing is not None:
        denial = access_service.write_denial(ctx, existing.owner_id)
        if denial:
            status, payload = denial
            return JSONResponse(status_code=status, content=payload)
    try:
        fleet = fleet_service.replace_items(
            session, fleet_id, settings, items, ctx.write_owner,
            expected_updated_at=expected_updated_at,
        )
    except fleet_service.FleetNotFound:
        return JSONResponse(status_code=404, content={"detail": "Fleet not found."})
    except fleet_service.FleetValidationError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    except access_service.EditConflict:
        return JSONResponse(status_code=409, content={"detail": access_service.CONFLICT_MSG, "code": "conflict"})
    access_service.stamp_editor(session, "fleets", fleet_id, ctx)
    fleet.updated_by = access_service.editor_of(ctx)
    forecast = fleet_service.compute(session, fleet, [*ctx.read_owners, fleet.owner_id])
    return JSONResponse(content={**_summary(fleet, ctx, forecast), "items": fleet.items, "forecast": forecast})


# ---- Alerts on a fleet's expected failures ------------------------------------------
#
# Same access rule as editing the fleet: anyone who may write it may list and
# manage its alerts (404 unknown/unreadable, 403/402 read-only). Rules are
# evaluated when usage arrives through the ingest API (routers/ingest.py).

def _editable_fleet(session, fleet_id: str, ctx: AccessCtx):
    """(fleet, None) when the caller may edit it, else (None, JSONResponse)."""
    fleet, _ = access_service.fetch_readable(session, "fleets", Fleet, fleet_id, ctx)
    if fleet is None or fleet.id in ctx.hidden:
        return None, JSONResponse(status_code=404, content={"detail": "Fleet not found."})
    denial = access_service.write_denial(ctx, fleet.owner_id)
    if denial:
        status, payload = denial
        return None, JSONResponse(status_code=status, content=payload)
    return fleet, None


def _alert_owners(ctx: AccessCtx, fleet) -> list[str]:
    return [*ctx.read_owners, fleet.owner_id]


@router.get("/fleets/{fleet_id}/alerts")
def list_fleet_alerts(
    fleet_id: str, session=Depends(get_session), ctx: AccessCtx = Depends(get_access)
) -> JSONResponse:
    fleet, error = _editable_fleet(session, fleet_id, ctx)
    if error:
        return error
    forecast = alerts_service.current_forecast(session, fleet, _alert_owners(ctx, fleet))
    return JSONResponse(content={
        "alerts": [
            alerts_service.public(d, ctx.uid, fleet, forecast)
            for d in alerts_service.list_alerts(session, fleet.id)
        ],
        # Expected failures over the horizon — the 'above'/'change' metric.
        "current_value": (forecast or {}).get("expected"),
        "periods": (fleet.settings or {}).get("periods"),
        "period_label": (fleet.settings or {}).get("period_label"),
        "max_alerts": alerts_service.MAX_RULES,
    })


@router.post("/fleets/{fleet_id}/alerts")
def create_fleet_alert(
    fleet_id: str,
    kind: str = Body(...),
    threshold: float | None = Body(default=None),
    percent: float | None = Body(default=None),
    x: float | None = Body(default=None),
    y_periods: float | None = Body(default=None),
    enabled: bool = Body(default=True),
    session=Depends(get_session),
    ctx: AccessCtx = Depends(get_access),
) -> JSONResponse:
    fleet, error = _editable_fleet(session, fleet_id, ctx)
    if error:
        return error
    try:
        doc = alerts_service.create_alert(
            session, fleet, ctx.uid, _alert_owners(ctx, fleet),
            kind=kind, threshold=threshold, percent=percent, x=x, y_periods=y_periods,
            enabled=enabled,
        )
    except (alerts_service.AlertValidationError, alerts_service.AlertLimitError) as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    return JSONResponse(content=alerts_service.public(doc, ctx.uid, fleet))


@router.patch("/fleets/{fleet_id}/alerts/{alert_id}")
def update_fleet_alert(
    fleet_id: str,
    alert_id: str,
    changes: dict = Body(...),
    session=Depends(get_session),
    ctx: AccessCtx = Depends(get_access),
) -> JSONResponse:
    fleet, error = _editable_fleet(session, fleet_id, ctx)
    if error:
        return error
    allowed = {k: v for k, v in (changes or {}).items() if k in ("kind", "threshold", "percent", "x", "y_periods", "enabled")}
    try:
        doc = alerts_service.update_alert(session, fleet, alert_id, _alert_owners(ctx, fleet), allowed)
    except alerts_service.AlertNotFound:
        return JSONResponse(status_code=404, content={"detail": "Alert not found."})
    except alerts_service.AlertValidationError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    return JSONResponse(content=alerts_service.public(doc, ctx.uid, fleet))


@router.delete("/fleets/{fleet_id}/alerts/{alert_id}")
def delete_fleet_alert(
    fleet_id: str, alert_id: str, session=Depends(get_session), ctx: AccessCtx = Depends(get_access)
) -> JSONResponse:
    fleet, error = _editable_fleet(session, fleet_id, ctx)
    if error:
        return error
    try:
        alerts_service.delete_alert(session, fleet.id, alert_id)
    except alerts_service.AlertNotFound:
        return JSONResponse(status_code=404, content={"detail": "Alert not found."})
    return JSONResponse(content={"ok": True})


# ---- Tracked fleets (degradation tracking groups) ---------------------------------

def _tracked_summary(fleet, model, items, ctx: AccessCtx) -> dict:
    return {
        "id": fleet.id,
        "name": fleet.name,
        "model_id": fleet.model_id,
        "model_name": model.name if model else None,
        "unit": (model.results or {}).get("unit", "") if model else "",
        "n_items": len(items),
        "tracking": degradation_service.tracking_rollup(items),
        "is_sample": samples_service.is_sample(fleet.owner_id),
        "read_only": not access_service.can_write(ctx, fleet.owner_id),
        "updated_by": (fleet.updated_by or {}).get("name"),
        "created_at": fleet.created_at.isoformat(),
        "updated_at": fleet.updated_at.isoformat(),
    }


@router.post("/tracked")
def create_tracked_fleet(
    name: str = Body(...),
    model_id: str = Body(...),
    session=Depends(get_session),
    ctx: AccessCtx = Depends(get_access),
) -> JSONResponse:
    denied = access_service.workspace_write_denial(ctx)
    if denied is not None:
        status, payload = denied
        return JSONResponse(status_code=status, content=payload)
    try:
        fleet = degradation_service.create_tracked_fleet(session, name, model_id, ctx.write_owner)
    except degradation_service.ModelNotFound:
        return JSONResponse(status_code=404, content={"detail": "Degradation model not found."})
    except Exception as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    access_service.stamp_editor(session, "tracked_fleets", fleet.id, ctx)
    model = degradation_service.get_model(session, model_id, ctx.read_owners)
    return JSONResponse(content=_tracked_summary(fleet, model, [], ctx))


@router.get("/tracked")
def list_tracked_fleets(session=Depends(get_session), ctx: AccessCtx = Depends(get_access)) -> dict:
    # Fold any pre-fleet items into auto-created fleets first.
    degradation_service.adopt_orphan_items(session, ctx.write_owner)
    out = []
    for fleet in degradation_service.list_tracked_fleets(session, ctx.list_owners, ctx.hidden):
        owners = [*ctx.read_owners, fleet.owner_id]
        model = degradation_service.get_model(session, fleet.model_id, owners)
        items = degradation_service.list_fleet_items(session, fleet, owners, ctx.hidden)
        out.append(_tracked_summary(fleet, model, items, ctx))
    return {"fleets": out}


@router.get("/tracked/{fleet_id}")
def get_tracked_fleet(
    fleet_id: str, session=Depends(get_session), ctx: AccessCtx = Depends(get_access)
) -> JSONResponse:
    fleet = degradation_service.get_tracked_fleet(session, fleet_id, ctx.read_owners)
    if fleet is None or fleet.id in ctx.hidden:
        return JSONResponse(status_code=404, content={"detail": "Tracked fleet not found."})
    owners = [*ctx.read_owners, fleet.owner_id]
    model = degradation_service.get_model(session, fleet.model_id, owners)
    items = degradation_service.list_fleet_items(session, fleet, owners, ctx.hidden)
    payload = _tracked_summary(fleet, model, items, ctx)
    if model is not None:
        payload["model"] = {
            "id": model.id, "name": model.name,
            "path_model": (model.results or {}).get("path_model", {}).get("name"),
            "threshold": (model.results or {}).get("threshold"),
            "unit": (model.results or {}).get("unit", ""),
            "measurement_unit": (model.results or {}).get("measurement_unit", ""),
            "results": model.results,
        }
    payload["items"] = [
        {
            "id": it.id, "model_id": it.model_id, "fleet_id": it.fleet_id,
            "name": it.name, "meta": it.meta or {},
            "n_measurements": len(it.measurements),
            "measurements": it.measurements, "prediction": it.prediction,
            "is_sample": samples_service.is_sample(it.owner_id),
            "read_only": not access_service.can_write(ctx, it.owner_id),
            "created_at": it.created_at.isoformat(),
            "updated_at": it.updated_at.isoformat(),
        }
        for it in items
    ]
    return JSONResponse(content=payload)


@router.patch("/tracked/{fleet_id}")
def rename_tracked_fleet(
    fleet_id: str,
    name: str = Body(..., embed=True),
    session=Depends(get_session),
    ctx: AccessCtx = Depends(get_access),
) -> JSONResponse:
    existing = degradation_service.get_tracked_fleet(session, fleet_id, ctx.read_owners)
    if existing is not None:
        denial = access_service.write_denial(ctx, existing.owner_id)
        if denial:
            status, payload = denial
            return JSONResponse(status_code=status, content=payload)
    try:
        fleet = degradation_service.rename_tracked_fleet(session, fleet_id, name, ctx.write_owner)
        access_service.stamp_editor(session, "tracked_fleets", fleet.id, ctx)
    except degradation_service.ModelNotFound:
        return JSONResponse(status_code=404, content={"detail": "Tracked fleet not found."})
    model = degradation_service.get_model(session, fleet.model_id, ctx.read_owners)
    items = degradation_service.list_fleet_items(session, fleet, ctx.read_owners, ctx.hidden)
    return JSONResponse(content=_tracked_summary(fleet, model, items, ctx))


@router.delete("/tracked/{fleet_id}")
def delete_tracked_fleet(
    fleet_id: str, session=Depends(get_session), ctx: AccessCtx = Depends(get_access)
) -> JSONResponse:
    fleet = degradation_service.get_tracked_fleet(session, fleet_id, ctx.read_owners)
    if fleet is None or fleet.id in ctx.hidden:
        return JSONResponse(status_code=404, content={"detail": "Tracked fleet not found."})
    if access_service.can_write(ctx, fleet.owner_id):
        try:
            degradation_service.delete_tracked_fleet(session, fleet_id, ctx.write_owner)
        except degradation_service.ModelNotFound:
            return JSONResponse(status_code=404, content={"detail": "Tracked fleet not found."})
    elif samples_service.is_sample(fleet.owner_id):
        samples_service.hide_sample(session, ctx.uid, fleet_id)
    else:
        status, payload = access_service.write_denial(ctx, fleet.owner_id)
        return JSONResponse(status_code=status, content=payload)
    return JSONResponse(content={"ok": True})
