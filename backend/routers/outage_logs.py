"""Outage logs on a saved RBD: import, history, and models fitted from it
(issue #159; the logic is in :mod:`backend.services.outage_logs`).

Owner-only: a log belongs to the diagram's owner (a user, or a team whose
members co-own it). Nobody else sees it — not a share recipient, not a public
link — and a shared sample can't carry one.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse

from backend.db import get_session
from backend.fitting import FitError
from backend.services import access as access_service
from backend.services import billing as billing_service
from backend.services import outage_logs as logs_service
from backend.services import rbds as rbds_service
from backend.services import samples as samples_service
from backend.services.access import AccessCtx, get_access

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

SAMPLE_MSG = ("This is a shared sample diagram: outage logs go on your own diagrams. Save a copy of it first, "
              "then import the log there.")
PREVIEW_ROWS = 50


def _err(status: int, detail: str, **extra) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": detail, **extra})


def _rbd(session, rbd_id: str, ctx: AccessCtx, write: bool):
    """``(rbd, None)`` when the caller owns the diagram (a write also needs a
    writable workspace), else ``(None, error response)``."""
    rbd = rbds_service.get_rbd(session, rbd_id, ctx.read_owners)
    if rbd is None:
        return None, _err(404, "RBD not found.")
    if samples_service.is_sample(rbd.owner_id):
        return None, _err(403, SAMPLE_MSG, code="sample")
    if write:
        denial = access_service.write_denial(ctx, rbd.owner_id)
        if denial:
            status, payload = denial
            return None, JSONResponse(status_code=status, content=payload)
    return rbd, None


def _log(session, rbd, log_id: str):
    log = logs_service.get_log(session, log_id, [rbd.owner_id], rbd_id=rbd.id)
    if log is None:
        return None, _err(404, "Outage log not found.")
    return log, None


def _parse_args(body: dict) -> dict:
    return {
        "mapping": body.get("mapping") or None,
        "unit": body.get("unit") or None,
        "window_start": body.get("window_start"),
        "window_end": body.get("window_end"),
        "date_order": body.get("date_order") or "auto",
        "asset_map": body.get("asset_map") or None,
    }


@router.post("/rbds/{rbd_id}/outage-logs/preview")
def preview_log(
    rbd_id: str,
    body: dict = Body(...),
    session=Depends(get_session),
    ctx: AccessCtx = Depends(get_access),
) -> JSONResponse:
    """Check a log before saving: the table's headers, the detected mapping,
    and either the parsed outages (first rows), assets and notes or every
    error found. A table that can't be read at all is a 400."""
    rbd, denied = _rbd(session, rbd_id, ctx, write=True)
    if denied:
        return denied
    text = body.get("csv") or ""
    try:
        df = logs_service.read_table(text)
    except logs_service.OutageLogError as exc:
        return _err(400, str(exc))
    headers = list(df.columns)
    detected = logs_service.detect_columns(headers)
    out = {"headers": headers, "detected": detected, "n_rows": int(len(df)),
           "sample": df.head(5).to_dict("records")}
    try:
        parsed = logs_service.parse_log(text, rbd.graph or {}, **_parse_args(body))
    except logs_service.OutageLogError as exc:
        return JSONResponse(content={**out, "ok": False, "error": str(exc), "errors": exc.errors})
    return JSONResponse(content={
        **out,
        "ok": True,
        "mapping": parsed["columns"],
        "unit": parsed["unit"],
        "time_kind": parsed["time_kind"],
        "origin": parsed["origin"],
        "window": parsed["window"],
        "n_outages": len(parsed["rows"]),
        "rows": parsed["rows"][:PREVIEW_ROWS],
        "assets": parsed["assets"],
        "unmapped": parsed["unmapped"],
        "notes": parsed["notes"],
        "blocks": _block_options(rbd.graph or {}),
    })


def _block_options(graph: dict) -> list[dict]:
    return [{"id": nid, "label": b["label"]} for nid, b in logs_service.diagram_blocks(graph).items()
            if b["type"] != "knode"]


@router.post("/rbds/{rbd_id}/outage-logs")
def create_log(
    rbd_id: str,
    body: dict = Body(...),
    session=Depends(get_session),
    ctx: AccessCtx = Depends(get_access),
) -> JSONResponse:
    """Import and save an outage log against the diagram; answers with the
    log and the history it gives."""
    rbd, denied = _rbd(session, rbd_id, ctx, write=True)
    if denied:
        return denied
    if (
        ctx.is_personal
        and not billing_service.is_admin_user(ctx.user)
        and billing_service.would_exceed_cap(session, ctx.uid, "outage_logs")
    ):
        return _err(402, billing_service.cap_message(session, ctx.uid, "outage_logs"), code="cap", upgrade=True)
    try:
        parsed = logs_service.parse_log(body.get("csv") or "", rbd.graph or {}, **_parse_args(body))
        log = logs_service.create_log(session, rbd, parsed, ctx.write_owner, body.get("name") or "")
    except logs_service.OutageLogError as exc:
        return _err(400, str(exc), errors=exc.errors)
    out = {**logs_service.summary(log), "assets": parsed["assets"], "unmapped": parsed["unmapped"]}
    try:
        out["history"] = logs_service.system_history(rbd.graph or {}, log)
    except logs_service.OutageLogError as exc:
        out["history_error"] = str(exc)
    return JSONResponse(status_code=201, content=out)


@router.get("/rbds/{rbd_id}/outage-logs")
def list_logs(rbd_id: str, session=Depends(get_session), ctx: AccessCtx = Depends(get_access)) -> JSONResponse:
    rbd, denied = _rbd(session, rbd_id, ctx, write=False)
    if denied:
        return denied
    return JSONResponse(content={
        "logs": [logs_service.summary(d) for d in logs_service.list_logs(session, rbd.id, [rbd.owner_id])],
        "read_only": not access_service.can_write(ctx, rbd.owner_id),
    })


@router.get("/rbds/{rbd_id}/outage-logs/{log_id}")
def get_log(rbd_id: str, log_id: str, session=Depends(get_session),
            ctx: AccessCtx = Depends(get_access)) -> JSONResponse:
    rbd, denied = _rbd(session, rbd_id, ctx, write=False)
    if denied:
        return denied
    log, missing = _log(session, rbd, log_id)
    if missing:
        return missing
    names = sorted({r["asset"] for r in log.get("rows") or []})
    blocks = logs_service.diagram_blocks(rbd.graph or {})
    amap = log.get("asset_map") or {}
    units, _ = logs_service.unit_assignment(amap, log.get("asset_units"), blocks)
    return JSONResponse(content={
        **logs_service.summary(log),
        "rows": log.get("rows") or [],
        "assets": [{"name": n, "node_id": amap.get(n), "label": blocks.get(amap.get(n) or "", {}).get("label"),
                    "n_outages": sum(1 for r in log.get("rows") or [] if r["asset"] == n),
                    **({"unit": units[n]} if n in units else {})} for n in names],
        "blocks": _block_options(rbd.graph or {}),
    })


@router.patch("/rbds/{rbd_id}/outage-logs/{log_id}")
def update_log(
    rbd_id: str,
    log_id: str,
    body: dict = Body(...),
    session=Depends(get_session),
    ctx: AccessCtx = Depends(get_access),
) -> JSONResponse:
    """Rename the log, re-map its assets to blocks, or move its window."""
    rbd, denied = _rbd(session, rbd_id, ctx, write=True)
    if denied:
        return denied
    log, missing = _log(session, rbd, log_id)
    if missing:
        return missing
    try:
        log = logs_service.update_log(
            session, log, rbd.graph or {}, name=body.get("name"), asset_map=body.get("asset_map"),
            window_start=body.get("window_start"), window_end=body.get("window_end"))
    except logs_service.OutageLogError as exc:
        return _err(400, str(exc))
    return JSONResponse(content=logs_service.summary(log))


@router.delete("/rbds/{rbd_id}/outage-logs/{log_id}")
def delete_log(rbd_id: str, log_id: str, session=Depends(get_session),
               ctx: AccessCtx = Depends(get_access)) -> JSONResponse:
    rbd, denied = _rbd(session, rbd_id, ctx, write=True)
    if denied:
        return denied
    if not logs_service.delete_log(session, log_id, rbd.owner_id):
        return _err(404, "Outage log not found.")
    return JSONResponse(content={"ok": True})


@router.get("/rbds/{rbd_id}/outage-logs/{log_id}/history")
def history(rbd_id: str, log_id: str, session=Depends(get_session),
            ctx: AccessCtx = Depends(get_access)) -> JSONResponse:
    """The diagram's observed history from the log, merged through the
    diagram as it is now."""
    rbd, denied = _rbd(session, rbd_id, ctx, write=False)
    if denied:
        return denied
    log, missing = _log(session, rbd, log_id)
    if missing:
        return missing
    try:
        return JSONResponse(content=logs_service.system_history(rbd.graph or {}, log))
    except logs_service.OutageLogError as exc:
        return _err(422, str(exc))


@router.post("/rbds/{rbd_id}/outage-logs/{log_id}/fit")
def fit_models(
    rbd_id: str,
    log_id: str,
    distribution: Optional[str] = Body(default="weibull"),
    repair_distribution: Optional[str] = Body(default="lognormal"),
    session=Depends(get_session),
    ctx: AccessCtx = Depends(get_access),
) -> JSONResponse:
    """Fit a life and a repair model per block from the log's up periods and
    repairs (Reliafy's fitting), each ready to put on its block."""
    rbd, denied = _rbd(session, rbd_id, ctx, write=False)
    if denied:
        return denied
    log, missing = _log(session, rbd, log_id)
    if missing:
        return missing
    from backend import fitting

    try:
        life = fitting.resolve_distribution_id(distribution or "weibull")
        repair = fitting.resolve_distribution_id(repair_distribution or "lognormal")
        return JSONResponse(content=logs_service.fit_models(rbd.graph or {}, log, life, repair))
    except (logs_service.OutageLogError, FitError) as exc:
        return _err(422, str(exc))
