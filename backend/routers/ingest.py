"""Personal API tokens + the ingestion API.

Token management uses normal session auth. The ``/api/ingest`` endpoints
accept either a personal API token (``Authorization: Bearer rlf_…``) or a
normal session — tokens work *only* here, so a leaked token can push data
but never read analyses.

Bodies are JSON or raw ``text/csv`` (``curl --data-binary @file.csv -H
"Content-Type: text/csv"``), matching how this data leaves a CMMS.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from backend.auth import get_current_user
from backend.db import get_session
from backend.services import billing as billing_service
from backend.services import ingest as ingest_service
from backend.services import metrics as metrics_service
from backend.services import tokens as tokens_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

_PRO_REQUIRED = (
    "The programmatic API is a Pro feature. Upgrade to Pro to create tokens "
    "and push data to Reliafy."
)

# Simple per-user sliding-window rate limit for the ingest endpoints. In-memory
# (per instance) — a genuine abuse ceiling, not billing-grade accounting.
_RATE_LIMIT = 120  # requests / minute
_hits: dict[str, deque] = defaultdict(deque)


def _rate_check(uid: str) -> None:
    now = time.monotonic()
    window = _hits[uid]
    while window and now - window[0] > 60:
        window.popleft()
    if len(window) >= _RATE_LIMIT:
        raise HTTPException(status_code=429, detail="Rate limit exceeded — max 120 requests/minute.")
    window.append(now)


def ingest_user(
    authorization: str | None = Header(default=None),
    session=Depends(get_session),
) -> dict:
    """Token-or-session auth for the ingest endpoints, gated to Pro.

    The Pro check runs on every ingest request (not just token creation) so a
    token minted while Pro stops working the moment the plan lapses.
    """
    if authorization and authorization.startswith("Bearer rlf_"):
        user = tokens_service.verify(session, authorization.split(" ", 1)[1].strip())
        if user is None:
            raise HTTPException(status_code=401, detail="Invalid or revoked API token.")
    else:
        user = get_current_user(authorization)
    if not billing_service.api_access_allowed(session, user):
        raise HTTPException(status_code=402, detail=_PRO_REQUIRED)
    return user


# ---- token management (session auth) ----------------------------------------

@router.post("/tokens")
def create_token(
    name: str = Body(default="", embed=True),
    session=Depends(get_session),
    user: dict = Depends(get_current_user),
) -> JSONResponse:
    if not billing_service.api_access_allowed(session, user):
        return JSONResponse(status_code=402, content={"detail": _PRO_REQUIRED, "code": "pro_required"})
    try:
        return JSONResponse(content=tokens_service.create_token(session, user["uid"], name))
    except tokens_service.TokenError as exc:
        return JSONResponse(status_code=exc.status, content={"detail": str(exc)})


@router.get("/tokens")
def list_tokens(session=Depends(get_session), user: dict = Depends(get_current_user)) -> dict:
    return {
        "tokens": tokens_service.list_tokens(session, user["uid"]),
        "allowed": billing_service.api_access_allowed(session, user),
    }


@router.delete("/tokens/{token_id}")
def revoke_token(
    token_id: str, session=Depends(get_session), user: dict = Depends(get_current_user)
) -> JSONResponse:
    if not tokens_service.revoke_token(session, user["uid"], token_id):
        return JSONResponse(status_code=404, content={"detail": "Token not found."})
    return JSONResponse(content={"ok": True})


# ---- ingestion (token or session auth) ---------------------------------------

async def _handle(request: Request, user: dict, op, *args) -> JSONResponse:
    _rate_check(user["uid"])
    body = await request.body()
    try:
        result = op(request.headers.get("content-type", ""), body, *args)
    except ingest_service.IngestError as exc:
        return JSONResponse(status_code=exc.status, content={"detail": str(exc)})
    return JSONResponse(content=result)


@router.post("/ingest/fleets/{fleet_id}/usage")
async def ingest_fleet_usage(
    fleet_id: str,
    request: Request,
    session=Depends(get_session),
    user: dict = Depends(ingest_user),
) -> JSONResponse:
    """Update forecast-fleet items' current use (and optional rate)."""

    def op(content_type, body):
        rows = ingest_service.rows_from_request(content_type, body, ("items", "usage", "rows"))
        result = ingest_service.update_fleet_usage(session, fleet_id, user["uid"], rows)
        metrics_service.record_event(session, name="ingest_usage", path=f"/api/ingest/fleets/{fleet_id}")
        return result

    return await _handle(request, user, op)


@router.post("/ingest/tracking/{fleet_id}/measurements")
async def ingest_measurements(
    fleet_id: str,
    request: Request,
    session=Depends(get_session),
    user: dict = Depends(ingest_user),
) -> JSONResponse:
    """Append degradation readings (item, time, value) to a tracked fleet."""

    def op(content_type, body):
        rows = ingest_service.rows_from_request(content_type, body, ("measurements", "readings", "rows"))
        result = ingest_service.append_measurements(session, fleet_id, user["uid"], rows)
        metrics_service.record_event(session, name="ingest_measurements", path=f"/api/ingest/tracking/{fleet_id}")
        return result

    return await _handle(request, user, op)


@router.post("/import/models")
async def import_model(
    request: Request,
    session=Depends(get_session),
    user: dict = Depends(ingest_user),
) -> JSONResponse:
    """Import a model built elsewhere (e.g. a SurPyval notebook).

    JSON body: ``name``, ``distribution`` (SurPyval name or Reliafy id),
    optional ``unit``; then either ``data`` (``{x, c?, n?}`` arrays — refit
    server-side into a full model) or ``params`` (``[{name, value}, …]`` for a
    params-only model), with optional ``options`` (offset/zi/lfp for the data
    path) or ``extras`` (gamma/p/f0 values for the params path).
    """
    from backend.services import models as models_service

    _rate_check(user["uid"])
    import json

    try:
        payload = json.loads(await request.body() or b"{}")
    except json.JSONDecodeError:
        return JSONResponse(status_code=422, content={"detail": "Body must be JSON."})
    name = str(payload.get("name") or "").strip()
    if not name:
        return JSONResponse(status_code=422, content={"detail": "A 'name' is required."})
    if not payload.get("data") and not payload.get("params"):
        return JSONResponse(status_code=422, content={"detail": "Provide 'data' arrays or 'params'."})

    try:
        model = models_service.import_model(
            session, user["uid"], name,
            distribution=payload.get("distribution", ""),
            unit=payload.get("unit"),
            data=payload.get("data"),
            params=payload.get("params"),
            options=payload.get("options"),
            extras=payload.get("extras"),
        )
    except ingest_service.IngestError as exc:  # pragma: no cover - defensive
        return JSONResponse(status_code=exc.status, content={"detail": str(exc)})
    except Exception as exc:
        # fitting.FitError and friends carry a user-facing message.
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    metrics_service.record_event(session, name="import_model", path="/api/import/models")
    return JSONResponse(content={
        "id": model.id,
        "name": model.name,
        "distribution": (model.results or {}).get("distribution", model.distribution_id),
        "params_only": bool((model.results or {}).get("params_only")),
        "url": f"/modelling/m/{model.id}",
    })


@router.post("/ingest/datasets/{dataset_id}/lives")
async def ingest_dataset_lives(
    dataset_id: str,
    request: Request,
    refit: bool = True,
    session=Depends(get_session),
    user: dict = Depends(ingest_user),
) -> JSONResponse:
    """Append rows to a dataset; by default, refit its models in place."""

    def op(content_type, body):
        df = ingest_service.dataframe_from_request(content_type, body)
        result = ingest_service.append_dataset_rows(session, dataset_id, user["uid"], df, refit=refit)
        metrics_service.record_event(session, name="ingest_lives", path=f"/api/ingest/datasets/{dataset_id}")
        return result

    return await _handle(request, user, op)
