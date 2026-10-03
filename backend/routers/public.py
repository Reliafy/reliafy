"""Public share links: manage them (authed) and resolve them (no auth).

The public GET replays the artifact's normal detail handler under a guest
access context — same payload the owner sees, minus identity fields — so
evidence resolution, forecasts, and live statuses all behave identically to
the in-app view without duplicating any of that logic here.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import JSONResponse

from backend.auth import get_current_user
from backend.db import get_session
from backend.routers.telemetry import _client_ip
from backend.services import public_links as links_service
from backend.services import rbds as rbds_service
from backend.services.rbd_analysis import AnalysisError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


@router.post("/public-links")
def create_link(
    collection: str = Body(...),
    artifact_id: str = Body(...),
    label: str | None = Body(default=None),
    expires_in_days: int | None = Body(default=None),
    password: str | None = Body(default=None),
    generate_password: bool = Body(default=False),
    session=Depends(get_session),
    user: dict = Depends(get_current_user),
) -> JSONResponse:
    """Create a new link (an artifact can have several). A generated
    passphrase comes back once, as ``passphrase``; a typed one never does."""
    try:
        link = links_service.create_link(
            session, collection, artifact_id, user, label=label, expires_in_days=expires_in_days,
            password=password, generate_password=generate_password,
        )
    except links_service.PublicLinkError as exc:
        return JSONResponse(status_code=exc.status, content={"detail": str(exc)})
    return JSONResponse(content=links_service.public(link))


@router.get("/public-links")
def list_links(
    collection: str | None = None,
    artifact_id: str | None = None,
    session=Depends(get_session),
    user: dict = Depends(get_current_user),
) -> dict:
    """The caller's live links (optionally for one artifact), newest first.
    ``link`` is the newest one, for clients written when there was only one."""
    links = [links_service.public(link)
             for link in links_service.list_links(session, user["uid"], collection, artifact_id)]
    return {"links": links, "link": links[0] if links else None}


@router.patch("/public-links/{token}")
def update_link(
    token: str,
    changes: dict = Body(default={}),
    session=Depends(get_session),
    user: dict = Depends(get_current_user),
) -> JSONResponse:
    """Relabel a link, or set (``password``), rotate (``generate_password``)
    or remove (``remove_password``) its password. Any password change ends
    every earlier unlock."""
    try:
        link = links_service.update_link(
            session, token, user["uid"],
            label=changes.get("label"), set_label="label" in changes,
            password=changes.get("password") or None,
            generate_password=bool(changes.get("generate_password")),
            remove_password=bool(changes.get("remove_password")),
        )
    except links_service.PublicLinkError as exc:
        return JSONResponse(status_code=exc.status, content={"detail": str(exc)})
    if link is None:
        return JSONResponse(status_code=404, content={"detail": "Link not found."})
    return JSONResponse(content=links_service.public(link))


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


AVAILABILITY_NOT_RUN = "The owner hasn't run the availability simulation for this diagram yet."


def _with_rbd_analysis(session, payload: dict, rbd_id: str, owner_id: str, ctx) -> dict:
    """Attach the server-side analysis to a public RBD payload.

    The graph is analysed under the grantor's read scope (plus the diagram's
    owner) so nested sub-systems and saved-model references resolve exactly as
    they do in the builder. The graph itself goes out through
    :func:`rbds_service.public_graph`, which drops the saved-artifact ids a
    viewer can't use. Reliability (non-repairable) analysis is recomputed on
    every hit, like the builder's own Calculate button.

    Repairable diagrams are NEVER simulated for an anonymous viewer (the
    Monte-Carlo availability run is a paid, CPU-heavy feature): the owner's
    saved result is served when it matches the graph, otherwise the analysis
    is null with an explanatory ``analysis_note``.
    """
    graph = payload.get("graph") or {}
    note = None
    try:
        if graph.get("repairable"):
            doc = session.rbds.find_one({"_id": rbd_id})
            analysis = rbds_service.cached_availability(
                doc, rbds_service.availability_cache_key(graph)
            )
            # The owner's saved exact figures (#154) ride along, or stand in
            # for a simulation that hasn't been run: read, never computed here.
            exact = rbds_service.cached_exact(doc, rbds_service.exact_cache_key(graph, None, None))
            if analysis is not None:
                analysis = {**analysis, "has_simulation": True,
                            **({"exact": exact["exact"]} if exact else {})}
            elif exact is not None:
                analysis = {**exact, "has_simulation": False, "cached": False, "computed_at": None}
            else:
                note = AVAILABILITY_NOT_RUN
        else:
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
        "analysis_note": note,
    }


# ---- unauthenticated: opening a link -------------------------------------------

_GONE = "This link doesn't exist, has expired or was revoked."
# The whole body of a protected link's answer before unlock: no name, no
# sharer, not even the kind of artifact.
_PASSWORD_REQUIRED = {"password_required": True}

UNLOCK_HEADER = "X-Share-Unlock"


def _unlock_token(request: Request) -> str | None:
    """The viewer's unlock token: the header (the app) or ``?unlock=`` (a
    plain download link)."""
    return request.headers.get(UNLOCK_HEADER) or request.query_params.get("unlock") or None


def _open_link(session, token: str, request: Request):
    """``(link, None)`` when the viewer may see the link's content, else
    ``(None, response)``: 404 for a missing, expired or revoked link, 401
    ``{password_required: true}`` for a protected one without a valid unlock."""
    link = links_service.resolve(session, token)
    if link is None:
        return None, JSONResponse(status_code=404, content={"detail": _GONE})
    if not links_service.can_view(link, _unlock_token(request)):
        return None, JSONResponse(status_code=401, content=_PASSWORD_REQUIRED,
                                  headers={"Cache-Control": "no-store"})
    return link, None


@router.post("/public/{token}/unlock")
def unlock_public(
    token: str,
    request: Request,
    password: str = Body(default="", embed=True),
    session=Depends(get_session),
) -> JSONResponse:
    """Trade a protected link's password for a short-lived unlock token.

    Attempts are counted per client IP and per link *before* the password is
    checked (so parallel guesses can't race past the limit); past either
    limit the answer is 429 with ``Retry-After``. The check itself is scrypt
    plus a constant-time compare."""
    too_many = JSONResponse(
        status_code=429,
        content={"detail": "Too many attempts. Wait a few minutes, then try again."},
        headers={"Retry-After": str(links_service.retry_after_seconds())},
    )
    if not links_service.consume_attempt(
        session, links_service.ip_key(_client_ip(request)), links_service.IP_ATTEMPTS
    ):
        return too_many
    link = links_service.resolve(session, token)
    if link is None:
        return JSONResponse(status_code=404, content={"detail": _GONE})
    if not links_service.is_protected(link):
        return JSONResponse(status_code=400, content={"detail": "This link doesn't need a password."})
    if not links_service.consume_attempt(session, f"link:{link['_id']}", links_service.LINK_ATTEMPTS):
        return too_many
    if not links_service.check_password(link, password or ""):
        return JSONResponse(status_code=401, content={"detail": "That password isn't right."})
    return JSONResponse(content=links_service.issue_unlock(link), headers={"Cache-Control": "no-store"})


@router.get("/public/{token}/export.py")
def export_public_rbd(token: str, request: Request, session=Depends(get_session)):
    """Unauthenticated "Download as Python" for a publicly linked RBD.

    Same checks as :func:`view_public` (the link resolves and is unlocked if
    protected, the diagram still exists, the grantor can still read it —
    replayed through the RBD detail handler under the guest ctx), and the
    same resolution scope as the public analysis (the grantor's read scope
    plus the diagram's owner). The script carries no saved-artifact ids or
    identities.
    """
    from backend.routers.rbds import python_download

    link, refusal = _open_link(session, token, request)
    if refusal is not None:
        return refusal
    if link["collection"] != "rbds":
        return JSONResponse(status_code=404, content={"detail": _GONE})
    doc = session.rbds.find_one({"_id": link["artifact_id"]})
    if doc is None:
        return JSONResponse(status_code=404, content={"detail": "The shared analysis no longer exists."})
    ctx = links_service.guest_ctx(doc["owner_id"], link["grantor_uid"])
    response = _detail_handler("rbds")(link["artifact_id"], session, ctx)
    if getattr(response, "status_code", 200) != 200:
        return JSONResponse(status_code=404, content={"detail": "The shared analysis is unavailable."})
    payload = json.loads(response.body)
    try:
        # Export exactly what the public page shows: public_graph drops nested
        # sub-system and saved-model ids, so a public download never reveals
        # more than the viewer can see (those blocks become explained
        # placeholders in the script; inline-parameter blocks export in full).
        filename, source = rbds_service.export_python(
            session, payload.get("name") or "",
            rbds_service.public_graph(payload.get("graph") or {}),
            [*ctx.read_owners, doc["owner_id"]],
        )
    except Exception:  # pragma: no cover - defensive
        logger.exception("Failed to export public RBD as Python")
        return JSONResponse(status_code=500, content={"detail": "This diagram couldn't be exported."})
    return python_download(filename, source)


@router.get("/public/{token}")
def view_public(token: str, request: Request, session=Depends(get_session)) -> JSONResponse:
    """Unauthenticated read of a publicly linked artifact."""
    link, refusal = _open_link(session, token, request)
    if refusal is not None:
        return refusal

    doc = session[link["collection"]].find_one({"_id": link["artifact_id"]})
    if doc is None:
        return JSONResponse(status_code=404, content={"detail": "The shared analysis no longer exists."})

    ctx = links_service.guest_ctx(doc["owner_id"], link["grantor_uid"])
    response = _detail_handler(link["collection"])(link["artifact_id"], session, ctx)
    if getattr(response, "status_code", 200) != 200:
        return JSONResponse(status_code=404, content={"detail": "The shared analysis is unavailable."})

    payload = json.loads(response.body)
    if link["collection"] == "rbds":
        payload = _with_rbd_analysis(session, payload, link["artifact_id"], doc["owner_id"], ctx)
    payload = links_service.sanitize(payload)
    grantor = session.users.find_one({"_id": link["grantor_uid"]}) or {}
    # A protected page mustn't linger in a shared cache once it's unlocked.
    headers = {"Cache-Control": "no-store"} if links_service.is_protected(link) else None
    return JSONResponse(content={
        "collection": link["collection"],
        "artifact": payload,
        "shared_by": grantor.get("name") or "a Reliafy user",
        "protected": links_service.is_protected(link),
    }, headers=headers)
