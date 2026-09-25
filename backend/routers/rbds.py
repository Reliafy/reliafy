"""Saved RBD (reliability block diagram) API."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse, Response

from backend.db import get_session
from backend.services import billing as billing_service
from backend.services import rbds as rbds_service
from backend.services import samples as samples_service
from backend.services import access as access_service
from backend.services import shares as shares_service
from backend.services.access import AccessCtx, get_access
from backend.schema import Rbd
from backend.services.rbd_analysis import AnalysisError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


def _summary(rbd, ctx: AccessCtx) -> dict:
    graph = rbd.graph or {}
    return {
        "id": rbd.id,
        "name": rbd.name,
        "n_nodes": len(graph.get("nodes", [])),
        "n_edges": len(graph.get("edges", [])),
        "created_at": rbd.created_at.isoformat(),
        "updated_at": rbd.updated_at.isoformat(),
        "is_sample": samples_service.is_sample(rbd.owner_id),
        "read_only": not access_service.can_write(ctx, rbd.owner_id),
        "updated_by": (rbd.updated_by or {}).get("name"),
    }


@router.get("/rbds")
def list_rbds(session=Depends(get_session), ctx: AccessCtx = Depends(get_access)) -> dict:
    shared_by = shares_service.shared_by_map(session, ctx.uid, "rbds") if ctx.is_personal else {}
    return {
        "rbds": [
            {**_summary(r, ctx), **({"shared_by": shared_by[r.id]} if r.id in shared_by else {})}
            for r in rbds_service.list_rbds(session, ctx.list_owners, ctx.hidden, shared=set(shared_by))
        ]
    }


@router.post("/rbds")
def save_rbd(
    name: str = Body(...),
    graph: dict = Body(...),
    id: str | None = Body(default=None),
    expected_updated_at: str | None = Body(default=None),
    session=Depends(get_session),
    ctx: AccessCtx = Depends(get_access),
) -> JSONResponse:
    denied = access_service.workspace_write_denial(ctx)
    if denied is not None:
        status, payload = denied
        return JSONResponse(status_code=status, content=payload)
    # Free-plan cap applies only when creating a new diagram (updating one you
    # own, or forking a sample, is checked by whether you already own it).
    existing = rbds_service.get_rbd(session, id, ctx.read_owners) if id else None
    creating = existing is None or existing.owner_id != ctx.write_owner
    if (
        creating
        and ctx.is_personal
        and not billing_service.is_admin_user(ctx.user)
        and billing_service.would_exceed_cap(session, ctx.uid, "rbds")
    ):
        return JSONResponse(
            status_code=402,
            content={"detail": "You've reached the free-plan limit of 1 saved RBD. Upgrade to Pro for unlimited diagrams.", "code": "cap", "upgrade": True},
        )
    try:
        rbd = rbds_service.save_rbd(
            session, name, graph, ctx.write_owner, rbd_id=id,
            expected_updated_at=expected_updated_at,
        )
    except access_service.EditConflict:
        return JSONResponse(status_code=409, content={"detail": access_service.CONFLICT_MSG, "code": "conflict"})
    access_service.stamp_editor(session, "rbds", rbd.id, ctx)
    rbd.updated_by = access_service.editor_of(ctx)
    return JSONResponse(content=_summary(rbd, ctx))


@router.get("/rbds/{rbd_id}")
def get_rbd(
    rbd_id: str, session=Depends(get_session), ctx: AccessCtx = Depends(get_access)
) -> JSONResponse:
    rbd, _ = access_service.fetch_readable(session, "rbds", Rbd, rbd_id, ctx)
    if rbd is None or rbd.id in ctx.hidden:
        return JSONResponse(status_code=404, content={"detail": "RBD not found."})
    return JSONResponse(content={**_summary(rbd, ctx), "graph": rbd.graph})


@router.patch("/rbds/{rbd_id}")
def rename_rbd(
    rbd_id: str,
    name: str = Body(..., embed=True),
    session=Depends(get_session),
    ctx: AccessCtx = Depends(get_access),
) -> JSONResponse:
    existing, _ = access_service.fetch_readable(session, "rbds", Rbd, rbd_id, ctx)
    if existing is not None:
        denial = access_service.write_denial(ctx, existing.owner_id)
        if denial:
            status, payload = denial
            return JSONResponse(status_code=status, content=payload)
    try:
        rbd = rbds_service.rename_rbd(session, rbd_id, name, ctx.write_owner)
        access_service.stamp_editor(session, "rbds", rbd.id, ctx)
    except rbds_service.RbdNotFound:
        return JSONResponse(status_code=404, content={"detail": "RBD not found."})
    return JSONResponse(content=_summary(rbd, ctx))


@router.delete("/rbds/{rbd_id}")
def delete_rbd(
    rbd_id: str, session=Depends(get_session), ctx: AccessCtx = Depends(get_access)
) -> JSONResponse:
    rbd, _ = access_service.fetch_readable(session, "rbds", Rbd, rbd_id, ctx)
    if rbd is None or rbd.id in ctx.hidden:
        return JSONResponse(status_code=404, content={"detail": "RBD not found."})

    if access_service.can_write(ctx, rbd.owner_id):
        try:
            rbds_service.delete_rbd(session, rbd_id, ctx.write_owner)
        except rbds_service.RbdNotFound:
            return JSONResponse(status_code=404, content={"detail": "RBD not found."})
    elif samples_service.is_sample(rbd.owner_id) or access_service.is_shared_with(session, ctx.uid, rbd_id):
        # Samples and shared-with-me diagrams are hidden, not deleted.
        samples_service.hide_sample(session, ctx.uid, rbd_id)
    else:
        status, payload = access_service.write_denial(ctx, rbd.owner_id)
        return JSONResponse(status_code=status, content=payload)
    return JSONResponse(content={"ok": True})


# Availability (repairable RBDs) runs thousands of Monte-Carlo replications on a
# one-CPU service, so running it is a paid feature. Free users still build,
# validate and view diagrams — and any saved (cached) result.
AVAILABILITY_PRO_PAYLOAD = {
    "detail": (
        "Availability simulation is a paid feature. Subscribe to Pro or buy AI "
        "credits — or download the diagram and run it locally with RePyability."
    ),
    "code": "pro_required",
    "upgrade": True,
}


def _availability(
    session, ctx: AccessCtx, graph: dict, t_max, rbd, force: bool, resolve_owners
) -> JSONResponse:
    """Serve a repairable (availability) analysis: the saved result when it
    matches the graph, else compute it — if the user is entitled.

    ``rbd`` is the saved diagram the request is about (None for an unsaved
    graph, which is never cached). A fresh result is written back only when
    the caller may edit the diagram; read-only viewers (samples, shares) get
    the computation without touching the owner's document.
    """
    key = rbds_service.availability_cache_key(graph, t_max)
    doc = session.rbds.find_one({"_id": rbd.id}) if rbd is not None else None
    cached = rbds_service.cached_availability(doc, key)
    entitled = billing_service.premium_compute_allowed(session, ctx.user)
    if cached is not None and not (force and entitled):
        # ``can_recompute`` lets the UI offer "Re-run" only to entitled users.
        return JSONResponse(content={**cached, "can_recompute": entitled})
    if not entitled:
        return JSONResponse(status_code=402, content=AVAILABILITY_PRO_PAYLOAD)

    result = rbds_service.analyze_graph(session, graph, resolve_owners, t_max=t_max)
    computed_at = None
    if (
        rbd is not None
        and access_service.can_write(ctx, rbd.owner_id)
        and rbds_service.should_store_availability(doc, key)
    ):
        computed_at = rbds_service.store_availability(session, rbd.id, key, result, ctx.uid)
    return JSONResponse(content={
        **result, "cached": False, "computed_at": computed_at, "can_recompute": True,
    })


@router.post("/rbds/analyze")
def analyze_graph(
    graph: dict = Body(..., embed=True),
    t_max: float | None = Body(default=None),
    covariates: dict = Body(default={}),
    conditional_age: float | None = Body(default=None),
    rbd_id: str | None = Body(default=None),
    force: bool = Body(default=False),
    session=Depends(get_session),
    ctx: AccessCtx = Depends(get_access),
) -> JSONResponse:
    """Analyse an (unsaved) RBD graph with RePyability and return the results.

    ``t_max`` is the upper limit of the time axis to compute over.
    ``covariates`` maps node id -> covariate values for proportional-hazards
    nodes. ``conditional_age`` conditions the curves on having already survived
    to that age (so the result is the conditional survival).

    Repairable graphs run the (paid) availability simulation. ``rbd_id`` names
    the saved diagram being edited so a saved result can be served / stored;
    ``force`` re-runs even when a saved result matches (entitled users only).
    """
    try:
        if graph.get("repairable"):
            rbd = None
            if rbd_id:
                rbd, _ = access_service.fetch_readable(session, "rbds", Rbd, rbd_id, ctx)
            return _availability(session, ctx, graph, t_max, rbd, force, ctx.read_owners)
        return JSONResponse(
            content=rbds_service.analyze_graph(
                session,
                graph,
                ctx.read_owners,
                t_max=t_max,
                covariates=covariates,
                conditional_age=conditional_age,
            )
        )
    except AnalysisError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("Failed to analyse RBD graph")
        return JSONResponse(
            status_code=500, content={"detail": f"Failed to analyse RBD: {exc}"}
        )


@router.get("/rbds/{rbd_id}/analyze")
def analyze_rbd(
    rbd_id: str,
    t_max: float | None = None,
    force: bool = False,
    session=Depends(get_session),
    ctx: AccessCtx = Depends(get_access),
) -> JSONResponse:
    """Analyse a saved RBD with RePyability and return the results."""
    rbd, _ = access_service.fetch_readable(session, "rbds", Rbd, rbd_id, ctx)
    if rbd is None:
        return JSONResponse(status_code=404, content={"detail": "RBD not found."})
    graph = rbd.graph or {}
    owners = [*ctx.read_owners, rbd.owner_id]
    try:
        if graph.get("repairable"):
            return _availability(session, ctx, graph, t_max, rbd, force, owners)
        return JSONResponse(
            content=rbds_service.analyze_graph(session, graph, owners, t_max=t_max)
        )
    except rbds_service.RbdNotFound:
        return JSONResponse(status_code=404, content={"detail": "RBD not found."})
    except AnalysisError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("Failed to analyse RBD %s", rbd_id)
        return JSONResponse(
            status_code=500, content={"detail": f"Failed to analyse RBD: {exc}"}
        )


def python_download(filename: str, source: str) -> Response:
    """A generated script as a file download."""
    return Response(
        content=source,
        media_type="text/x-python; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


@router.get("/rbds/{rbd_id}/export.py")
def export_rbd_python(
    rbd_id: str, session=Depends(get_session), ctx: AccessCtx = Depends(get_access)
) -> Response:
    """Download a saved RBD as a standalone SurPyval + RePyability script.

    Free for anyone who can view the diagram (owner, team, share recipient,
    samples) — not metered and not plan-gated. Sub-systems and saved models
    resolve in the same scope as the diagram's analysis.
    """
    rbd, _ = access_service.fetch_readable(session, "rbds", Rbd, rbd_id, ctx)
    if rbd is None or rbd.id in ctx.hidden:
        return JSONResponse(status_code=404, content={"detail": "RBD not found."})
    try:
        filename, source = rbds_service.export_python(
            session, rbd.name, rbd.graph or {}, [*ctx.read_owners, rbd.owner_id]
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("Failed to export RBD %s as Python", rbd_id)
        return JSONResponse(
            status_code=500, content={"detail": f"Failed to export RBD: {exc}"}
        )
    return python_download(filename, source)


@router.post("/rbds/validate")
def validate_graph(
    graph: dict = Body(..., embed=True),
    session=Depends(get_session),
    ctx: AccessCtx = Depends(get_access),
) -> JSONResponse:
    """Check whether an (unsaved) graph is a valid, analytically solvable RBD."""
    return JSONResponse(content=rbds_service.validate_graph(session, graph, ctx.read_owners))


@router.get("/rbds/{rbd_id}/validate")
def validate_rbd(
    rbd_id: str, session=Depends(get_session), ctx: AccessCtx = Depends(get_access)
) -> JSONResponse:
    """Check whether a saved RBD is valid and analytically solvable."""
    rbd, _ = access_service.fetch_readable(session, "rbds", Rbd, rbd_id, ctx)
    if rbd is None:
        return JSONResponse(status_code=404, content={"detail": "RBD not found."})
    return JSONResponse(
        content=rbds_service.validate_graph(session, rbd.graph or {}, [*ctx.read_owners, rbd.owner_id])
    )
