"""Public share links: manage them (authed) and resolve them (no auth).

The public GET replays the artifact's normal detail handler under a guest
access context — same payload the owner sees, minus identity fields — so
evidence resolution, forecasts, and live statuses all behave identically to
the in-app view without duplicating any of that logic here.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse

from backend.auth import get_current_user
from backend.db import get_session
from backend.services import public_links as links_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


@router.post("/public-links")
def create_link(
    collection: str = Body(...),
    artifact_id: str = Body(...),
    session=Depends(get_session),
    user: dict = Depends(get_current_user),
) -> JSONResponse:
    try:
        link = links_service.create_link(session, collection, artifact_id, user)
    except links_service.PublicLinkError as exc:
        return JSONResponse(status_code=exc.status, content={"detail": str(exc)})
    return JSONResponse(content=links_service.public(link))


@router.get("/public-links")
def get_link(
    collection: str,
    artifact_id: str,
    session=Depends(get_session),
    user: dict = Depends(get_current_user),
) -> dict:
    link = links_service.get_for_artifact(session, collection, artifact_id, user["uid"])
    return {"link": links_service.public(link) if link else None}


@router.delete("/public-links/{token}")
def revoke_link(
    token: str, session=Depends(get_session), user: dict = Depends(get_current_user)
) -> JSONResponse:
    if not links_service.revoke(session, token, user["uid"]):
        return JSONResponse(status_code=404, content={"detail": "Link not found."})
    return JSONResponse(content={"ok": True})


# Detail handlers per collection, replayed under the guest ctx. Imported
# lazily inside the endpoint to avoid circular imports at module load.
def _detail_handler(collection: str):
    from backend.routers import degradation, fleet, models, rcm, strategy

    return {
        "models": models.get_model,
        "datasets": models.get_dataset,
        "degradation_models": degradation.get_model,
        "strategy_analyses": strategy.get_analysis,
        "rcm_studies": rcm.get_study,
        "fleets": fleet.get_fleet,
    }[collection]


@router.get("/public/{token}")
def view_public(token: str, session=Depends(get_session)) -> JSONResponse:
    """Unauthenticated read of a publicly linked artifact."""
    link = links_service.resolve(session, token)
    if link is None:
        return JSONResponse(status_code=404, content={"detail": "This link doesn't exist or was revoked."})

    doc = session[link["collection"]].find_one({"_id": link["artifact_id"]})
    if doc is None:
        return JSONResponse(status_code=404, content={"detail": "The shared analysis no longer exists."})

    ctx = links_service.guest_ctx(doc["owner_id"], link["grantor_uid"])
    response = _detail_handler(link["collection"])(link["artifact_id"], session, ctx)
    if getattr(response, "status_code", 200) != 200:
        return JSONResponse(status_code=404, content={"detail": "The shared analysis is unavailable."})

    payload = links_service.sanitize(json.loads(response.body))
    grantor = session.users.find_one({"_id": link["grantor_uid"]}) or {}
    return JSONResponse(content={
        "collection": link["collection"],
        "artifact": payload,
        "shared_by": grantor.get("name") or "a Reliafy user",
    })
