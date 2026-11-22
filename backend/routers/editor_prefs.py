"""How the app's editors behave for the signed-in user: for now, whether the RBD
builder saves a diagram by itself after each change (on unless turned off).

Kept on the user's profile (``users.editor_prefs``), so the choice follows them
to every browser. Settings › Editing and the builder's ⋯ menu both change it.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.auth import current_user_doc, get_current_user
from backend.db import get_session

router = APIRouter(prefix="/api")


class EditorPreferences(BaseModel):
    autosave: bool


def _read(doc: dict | None) -> dict:
    prefs = (doc or {}).get("editor_prefs") or {}
    # On unless the user turned it off.
    return {"autosave": prefs.get("autosave") is not False}


@router.get("/me/editor-preferences")
def get_editor_preferences(user: dict = Depends(get_current_user), session=Depends(get_session)):
    return _read(session.users.find_one({"_id": user["uid"]}))


@router.put("/me/editor-preferences")
def put_editor_preferences(prefs: EditorPreferences, user: dict = Depends(current_user_doc),
                           session=Depends(get_session)):
    doc = session.users.find_one({"_id": user["uid"]}) or {}
    merged = {**(doc.get("editor_prefs") or {}), "autosave": bool(prefs.autosave)}
    session.users.update_one({"_id": user["uid"]}, {"$set": {"editor_prefs": merged}})
    return _read(session.users.find_one({"_id": user["uid"]}))
