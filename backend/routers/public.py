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
from backend.services import rbds as rbds_service
from backend.services.rbd_analysis import AnalysisError

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
    from backend.routers import degradation, fleet, models, rbds, rcm, strategy

    return {
        "models": models.get_model,
        "datasets": models.get_dataset,
        "degradation_models": degradation.get_model,
        "strategy_analyses": strategy.get_analysis,
        "rcm_studies": rcm.get_study,
        "fleets": fleet.get_fleet,
        "rbds": rbds.get_rbd,
    }[collection]


def _with_rbd_analysis(session, payload: dict, owner_id: str, ctx) -> dict:
    """Attach the server-side analysis to a public RBD payload.

    The graph is analysed under the grantor's read scope (plus the diagram's
    owner) so nested sub-systems and saved-model references resolve exactly as
    they do in the builder. The graph itself goes out through
    :func:`rbds_service.public_graph`, which drops the saved-artifact ids a
    viewer can't use. Nothing is cached: every hit recomputes, like the
    builder's own Calculate button.
    """
    graph = payload.get("graph") or {}
    try:
        analysis = rbds_service.analyze_graph(session, graph, [*ctx.read_owners, owner_id])
        error = None
    except AnalysisError as exc:
        analysis, error = None, str(exc)
    except Exception:  # pragma: no cover - defensive
        logger.exception("Failed to analyse public RBD")
        analysis, error = None, "This diagram couldn't be analysed."
    return {
        **payload,
        "graph": rbds_service.public_graph(graph),
        "analysis": analysis,
        "analysis_error": error,
    }


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

    payload = json.loads(response.body)
    if link["collection"] == "rbds":
        payload = _with_rbd_analysis(session, payload, doc["owner_id"], ctx)
    payload = links_service.sanitize(payload)
    grantor = session.users.find_one({"_id": link["grantor_uid"]}) or {}
    return JSONResponse(content={
        "collection": link["collection"],
        "artifact": payload,
        "shared_by": grantor.get("name") or "a Reliafy user",
    })
