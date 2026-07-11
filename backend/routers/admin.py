"""Operator-only endpoints (ADMIN_EMAILS accounts)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from backend.auth import get_current_user
from backend.config import SAMPLE_OWNER
from backend.db import get_session
from backend.services import billing as billing_service

router = APIRouter(prefix="/api/admin")

_ARTIFACTS = (
    "datasets", "models", "rbds", "degradation_models",
    "tracked_items", "strategy_analyses", "rcm_studies",
)


@router.get("/stats")
def stats(session=Depends(get_session), user: dict = Depends(get_current_user)) -> JSONResponse:
    """A quick operator dashboard: signups, plans, and artifact volumes."""
    if not billing_service.is_admin_user(user):
        return JSONResponse(status_code=403, content={"detail": "Operator accounts only."})

    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)
    users_total = session.users.count_documents({})
    users_7d = session.users.count_documents({"created_at": {"$gte": week_ago}})
    pro_users = session.users.count_documents({"plan": "pro"})
    artifacts = {
        coll: session[coll].count_documents({"owner_id": {"$ne": SAMPLE_OWNER}})
        for coll in _ARTIFACTS
    }
    return JSONResponse(content={
        "users_total": users_total,
        "users_new_7d": users_7d,
        "pro_users": pro_users,
        "teams": session.teams.count_documents({}),
        "shares": session.shares.count_documents({}),
        "artifacts": artifacts,
        "generated_at": now.isoformat(),
    })
