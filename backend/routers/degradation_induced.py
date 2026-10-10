"""A saved degradation model's induced life distribution (#63)."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse

from backend import degradation_induced
from backend.db import get_session
from backend.schema import DegradationModelDoc
from backend.services import access as access_service
from backend.services import degradation as degradation_service
from backend.services.access import AccessCtx, get_access

router = APIRouter(prefix="/api")


@router.post("/degradation/models/{model_id}/induced-life")
def induced_life(
    model_id: str,
    body: dict = Body(default={}),
    session=Depends(get_session),
    ctx: AccessCtx = Depends(get_access),
) -> JSONResponse:
    """The failure-time distribution the path model induces (Lu-Meeker):
    its curve beside the pseudo-failure fit's, mean, median and B10, plus
    ``times`` → reliability and ``reliability`` → time when given."""
    doc, _ = access_service.fetch_readable(session, "degradation_models", DegradationModelDoc, model_id, ctx)
    if doc is None or doc.id in ctx.hidden:
        return JSONResponse(status_code=404, content={"detail": "Model not found."})
    live = degradation_service.get_live_model(session, model_id, [*ctx.read_owners, doc.owner_id])
    if live is None:
        return JSONResponse(status_code=404, content={"detail": "Model not found."})
    body = body or {}
    try:
        out = degradation_induced.induced_life(live, body.get("times"), body.get("reliability"))
    except ValueError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    return JSONResponse(content=out)
