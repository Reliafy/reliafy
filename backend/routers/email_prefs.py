"""Product-update email preferences.

Public, token-authenticated routes back the unsubscribe link in every
update email (and the RFC 8058 one-click ``List-Unsubscribe-Post`` that
Gmail / Apple Mail send). ``GET`` only reads: mail scanners prefetch links,
so a GET must never opt anyone out. The signed-in user's own preference
lives under ``/api/me/email-preferences``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from backend.auth import current_user_doc
from backend.db import get_session
from backend.services import email_prefs

router = APIRouter(prefix="/api")


def _not_found() -> JSONResponse:
    # One answer for every bad token: nothing distinguishes "malformed" from
    # "unknown", so the endpoint can't be used to probe for accounts.
    return JSONResponse(
        status_code=404,
        content={"detail": "This unsubscribe link isn't valid. It may have been "
                           "cut short — try copying the whole link from the email."},
    )


def _state(doc: dict) -> dict:
    return {
        "email": email_prefs.mask_email(doc.get("email")),
        "subscribed": email_prefs.is_subscribed(doc),
    }


@router.get("/email/unsubscribe")
def unsubscribe_status(t: str = Query(default=""), session=Depends(get_session)):
    """Who the link is for (masked) and their current state. Changes nothing."""
    doc = email_prefs.user_by_token(session, t)
    if doc is None:
        return _not_found()
    return _state(doc)


@router.post("/email/unsubscribe")
async def unsubscribe(request: Request, t: str = Query(default=""),
                      session=Depends(get_session)):
    """Opt out. Accepts the RFC 8058 one-click form body
    (``List-Unsubscribe=One-Click``), JSON, or nothing at all; idempotent."""
    doc = email_prefs.user_by_token(session, t)
    if doc is None:
        return _not_found()
    body = (await request.body())[:1024]
    source = "one_click" if b"List-Unsubscribe=One-Click" in body else "link"
    email_prefs.set_opt_out(session, doc["_id"], True, source)
    return {"email": email_prefs.mask_email(doc.get("email")), "subscribed": False}


@router.post("/email/resubscribe")
def resubscribe(t: str = Query(default=""), session=Depends(get_session)):
    doc = email_prefs.user_by_token(session, t)
    if doc is None:
        return _not_found()
    email_prefs.set_opt_out(session, doc["_id"], False, "link")
    return {"email": email_prefs.mask_email(doc.get("email")), "subscribed": True}


class Preferences(BaseModel):
    updates: bool


@router.get("/me/email-preferences")
def get_preferences(user: dict = Depends(current_user_doc), session=Depends(get_session)):
    doc = session.users.find_one({"_id": user["uid"]}) or {}
    return {"updates": email_prefs.is_subscribed(doc)}


@router.put("/me/email-preferences")
def put_preferences(prefs: Preferences, user: dict = Depends(current_user_doc),
                    session=Depends(get_session)):
    email_prefs.set_opt_out(session, user["uid"], not prefs.updates, "settings")
    doc = session.users.find_one({"_id": user["uid"]}) or {}
    return {"updates": email_prefs.is_subscribed(doc)}
