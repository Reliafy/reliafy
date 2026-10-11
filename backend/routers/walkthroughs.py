"""Guided walkthroughs (#32): a user's one automatic start per walkthrough.

The walkthrough events themselves go through ``/api/metrics/event``
(backend/routers/telemetry.py), like the first-run starts.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from backend.auth import current_user_doc
from backend.db import get_session
from backend.services import walkthroughs as walkthroughs_service

router = APIRouter(prefix="/api")


class AutoStart(BaseModel):
    id: str


@router.post("/me/walkthroughs/auto")
def claim_auto_start(body: AutoStart, user: dict = Depends(current_user_doc), session=Depends(get_session)):
    """Claim walkthrough ``id``'s automatic start: ``{"start": true}`` the
    first time for this user, false after that."""
    if not walkthroughs_service.is_walkthrough(body.id):
        return JSONResponse(status_code=422, content={"detail": "Unknown walkthrough."})
    return {"start": walkthroughs_service.claim_auto_start(session, user["uid"], body.id)}
