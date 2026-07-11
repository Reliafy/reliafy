"""Direct-sharing API: grant, list, and revoke view-only artifact shares."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse

from backend.auth import get_current_user
from backend.db import get_session
from backend.services import shares as shares_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/shares")


@router.post("")
def create_share(
    collection: str = Body(...),
    artifact_id: str = Body(...),
    email: str = Body(...),
    session=Depends(get_session),
    user: dict = Depends(get_current_user),
) -> JSONResponse:
    try:
        share = shares_service.create_share(session, collection, artifact_id, email, user)
    except shares_service.ShareError as exc:
        return JSONResponse(status_code=exc.status, content={"detail": str(exc)})
    return JSONResponse(content=shares_service.public(share))


@router.get("")
def list_shares(
    collection: str,
    artifact_id: str,
    session=Depends(get_session),
    user: dict = Depends(get_current_user),
) -> dict:
    return {
        "shares": [
            shares_service.public(s)
            for s in shares_service.list_for_artifact(session, artifact_id, user["uid"])
        ]
    }


@router.delete("/{share_id}")
def revoke_share(
    share_id: str, session=Depends(get_session), user: dict = Depends(get_current_user)
) -> JSONResponse:
    if not shares_service.revoke(session, share_id, user["uid"]):
        return JSONResponse(status_code=404, content={"detail": "Share not found."})
    return JSONResponse(content={"ok": True})
