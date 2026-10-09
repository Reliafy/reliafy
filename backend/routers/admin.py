"""Operator-only endpoints (ADMIN_EMAILS accounts)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from backend.auth import get_current_user
from backend.config import SAMPLE_OWNER
from backend.db import get_session
from backend.services import billing as billing_service
from backend.services import email_campaigns as email_campaigns_service
from backend.services import metrics as metrics_service
from backend.services import usage as usage_service

router = APIRouter(prefix="/api/admin")

_ARTIFACTS = (
    "datasets", "models", "rbds", "degradation_models",
    "tracked_items", "tracked_fleets", "strategy_analyses", "rcm_studies", "fleets",
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


_SIGNUPS_SHOWN = 20


def _aware(ts):
    """Mongo hands back naive UTC datetimes; make them comparable."""
    if ts is None:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


@router.get("/signups")
def signups(
    days: int = 7,
    session=Depends(get_session),
    user: dict = Depends(get_current_user),
) -> JSONResponse:
    """New accounts in the last ``days`` days: how many, and the latest few
    with only what an operator needs to follow up — email, plan, when they
    joined and when they were last active (their latest sign-in or usage
    event, which is kept 90 days)."""
    if not billing_service.is_admin_user(user):
        return JSONResponse(status_code=403, content={"detail": "Operator accounts only."})
    days = max(1, min(int(days or 7), 365))
    since = datetime.now(timezone.utc) - timedelta(days=days)
    query = {"created_at": {"$gte": since}}
    count = session.users.count_documents(query)
    docs = session.users.find(
        query, {"email": 1, "plan": 1, "plan_until": 1, "created_at": 1, "last_login": 1},
    ).sort("created_at", -1).limit(_SIGNUPS_SHOWN)
    rows = []
    for d in docs:
        seen = [_aware(d.get("last_login"))]
        latest = session.usage_events.find_one({"uid": d["_id"]}, {"ts": 1}, sort=[("ts", -1)])
        if latest:
            seen.append(_aware(latest.get("ts")))
        seen = [t for t in seen if t is not None]
        rows.append({
            "email": d.get("email"),
            "plan": billing_service.active_plan({"plan": d.get("plan", "free"), "plan_until": d.get("plan_until")}),
            "joined": _aware(d.get("created_at")).isoformat() if d.get("created_at") else None,
            "last_active": max(seen).isoformat() if seen else None,
        })
    return JSONResponse(content={"days": days, "count": count, "signups": rows})


@router.get("/traffic")
def traffic(
    days: int = 14,
    session=Depends(get_session),
    user: dict = Depends(get_current_user),
) -> JSONResponse:
    """First-party visitor analytics: daily traffic, pages, referrers, UTM."""
    if not billing_service.is_admin_user(user):
        return JSONResponse(status_code=403, content={"detail": "Operator accounts only."})
    return JSONResponse(content=metrics_service.traffic(session, days=days))


@router.get("/email-campaigns")
def email_campaigns(
    days: int = 90,
    session=Depends(get_session),
    user: dict = Depends(get_current_user),
) -> JSONResponse:
    """What each email brought in (#269): recipients, tagged visitors and the
    pages they reached, and recipients active within a few days of the send."""
    if not billing_service.is_admin_user(user):
        return JSONResponse(status_code=403, content={"detail": "Operator accounts only."})
    return JSONResponse(content=email_campaigns_service.report(session, days=days))


@router.get("/usage")
def usage(
    days: int = 30,
    include_admin: bool = False,
    session=Depends(get_session),
    user: dict = Depends(get_current_user),
) -> JSONResponse:
    """Product usage by channel (app / MCP / API): daily series, top MCP tools
    and app features, MCP outcomes and clients, the MCP plan wall and
    conversions. Rolls up finished days first (there's no cron)."""
    if not billing_service.is_admin_user(user):
        return JSONResponse(status_code=403, content={"detail": "Operator accounts only."})
    days = days if days in (7, 30, 90, 365) else 30
    return JSONResponse(content=usage_service.report(session, days=days, include_admin=include_admin))
