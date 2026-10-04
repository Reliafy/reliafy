"""Saved RBD (reliability block diagram) API."""

from __future__ import annotations

import json
import logging

import os

from fastapi import APIRouter, Body, Depends, File, Form, UploadFile
from fastapi.responses import JSONResponse, Response

from backend.auth import get_current_user
from backend.db import get_session
from backend.services import billing as billing_service
from backend.routers import excel as excel_router
from backend.services import import_guard
from backend.services import rbd_import
from backend.services import rbds as rbds_service
from backend.services import samples as samples_service
from backend.services import access as access_service
from backend.services import shares as shares_service
from backend.services import usage as usage_service
from backend.services.access import AccessCtx, get_access
from backend.schema import Rbd
from backend.services.rbd_analysis import AnalysisError
from backend.services.rbd_graph import GraphError, check_limits, normalize_graph

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


def _summary(rbd, ctx: AccessCtx) -> dict:
    graph = rbd.graph or {}
    return {
        "id": rbd.id,
        "name": rbd.name,
        "n_nodes": len(graph.get("nodes", [])),
        "n_edges": len(graph.get("edges", [])),
        "repairable": bool(graph.get("repairable")),
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
    try:
        check_limits(graph)
    except GraphError as exc:
        return JSONResponse(status_code=422, content={"detail": f"Can't save: {exc}"})
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
            content={"detail": billing_service.cap_message(session, ctx.uid, "rbds"), "code": "cap", "upgrade": True},
        )
    # Saved models and sub-system diagrams on the blocks must be ones the
    # writer can open (links the diagram already had are kept as they are).
    kept = access_service.graph_refs(existing.graph) if not creating else ()
    try:
        access_service.check_references(session, ctx, access_service.graph_refs(graph), keep=kept)
    except access_service.UnreadableReference as exc:
        return JSONResponse(status_code=exc.status, content={"detail": str(exc), "code": "unreadable_reference"})
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


@router.get("/rbds/import/template.xlsx")
def rbd_import_template(user: dict = Depends(get_current_user)) -> Response:
    """The Excel template for importing a diagram: a README sheet, and Blocks
    + Connections sheets holding a small worked example."""
    from backend.services.rbd_import import excel as rbd_excel

    return Response(
        content=rbd_excel.build_template(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": 'attachment; filename="reliafy-rbd-template.xlsx"',
            "Cache-Control": "no-store",
        },
    )


@router.post("/rbds/import")
def import_rbd_file(
    file: UploadFile = File(...),
    mapping: str | None = Form(default=None),
    ctx: AccessCtx = Depends(get_access),
) -> JSONResponse:
    """Parse another tool's diagram file into builder graphs — nothing is saved.

    The builder opens the chosen diagram unsaved, so the usual save (and the
    free-plan cap) applies when the user keeps it.

    ``mapping`` (JSON, Excel workbooks only) names the sheets and columns
    holding the blocks and connections. Without it a workbook must follow the
    template; one that doesn't is refused with ``code: "excel_mapping"`` so
    the frontend can ask the user to map its columns.
    """
    data = file.file.read(rbd_import.MAX_UPLOAD_BYTES + 1)
    ext = os.path.splitext(file.filename or "")[1].lower()[:12]
    kwargs = {}
    if mapping:
        try:
            kwargs["excel_mapping"] = json.loads(mapping)
        except ValueError:
            return JSONResponse(status_code=422, content={"detail": "The column mapping isn't valid JSON."})
    try:
        diagrams = excel_router.guarded(ctx.uid, rbd_import.import_file, data, file.filename or "", **kwargs)
    except (import_guard.ImportBusy, import_guard.ImportBudgetExceeded) as exc:
        return excel_router.guard_error(exc)
    except rbd_import.RbdImportError as exc:
        logger.info("RBD import refused: ext=%s bytes=%d — %s", ext, len(data), exc)
        content = {"detail": str(exc)}
        if getattr(exc, "code", None):
            content["code"] = exc.code
        return JSONResponse(status_code=422, content=content)
    except Exception:  # untrusted input: never 500 on a malformed file
        logger.exception("RBD import failed: ext=%s bytes=%d", ext, len(data))
        return JSONResponse(
            status_code=422,
            content={"detail": "Couldn't read this file — it may be damaged or from an unsupported version."},
        )

    out = []
    for d in diagrams:
        try:
            graph = normalize_graph(d.graph)
        except GraphError as exc:
            out.append({"name": d.name, "source_format": d.source_format, "error": str(exc), "warnings": d.warnings})
            continue
        out.append({
            "name": d.name,
            "source_format": d.source_format,
            "warnings": d.warnings,
            "graph": graph,
            "n_nodes": len(graph["nodes"]),
            "n_edges": len(graph["edges"]),
        })
    logger.info(
        "RBD import: format=%s ext=%s diagrams=%d ok=%d",
        diagrams[0].source_format, ext, len(out), sum(1 for d in out if "graph" in d),
    )
    return JSONResponse(content={"diagrams": out})


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


# The availability simulation (repairable RBDs) runs thousands of Monte-Carlo
# replications on a one-CPU service, so running it is a paid feature. Every
# user gets the exact figures (#154: long-run, and over time where RePyability
# has an exact route), and any saved (cached) simulation result.
AVAILABILITY_PRO_PAYLOAD = {
    "detail": (
        "Availability simulation is a paid feature. Subscribe to Pro or buy AI "
        "credits — or download the diagram and run it locally with RePyability."
    ),
    "code": "pro_required",
    "upgrade": True,
}


SIMULATION_PRO_MESSAGE = (
    "The simulation adds what only it gives (the spread of outcomes, the chance of no outage, "
    "percentiles and criticality indices): it's part of Pro, or buy AI credits — or download the "
    "diagram and run it locally with RePyability."
)


def _matches_saved(doc: dict | None, graph: dict) -> bool:
    """Whether ``graph`` is the diagram as saved (layout aside)."""
    if doc is None:
        return False
    return rbds_service.availability_cache_key(graph) == rbds_service.availability_cache_key(doc.get("graph") or {})


def exact_payload(session, graph: dict, t_max, state, doc, writable: bool, resolve_owners,
                  requested: bool) -> dict:
    """The free part of an availability result (#154): the exact long-run
    figures and the ``exact`` block over time, from the cache when it holds
    them. Above the size cap the figures over time wait for a request
    (``requested``), and the long-run figures come alone. A from-new result
    for the diagram as saved is kept on its document (when the caller may
    edit it); every result is kept in the process's cache."""
    from backend.services import rbd_analysis

    deferral = rbd_analysis.exact_deferral(graph, requested)
    if deferral is not None:
        return {**rbds_service.long_run_only(session, graph, resolve_owners, t_max), "exact": deferral}
    key = rbds_service.exact_cache_key(graph, t_max, state)
    hit = rbds_service.cached_exact(doc, key, resolve_owners)
    if hit is not None:
        return {**hit, "exact": {**(hit.get("exact") or {}), "cached": True}}
    result = rbds_service.analyze_exact(session, graph, resolve_owners, t_max, state)
    rbds_service.remember_exact(key, result, resolve_owners)
    if writable and state is None and _matches_saved(doc, graph):
        rbds_service.store_exact(session, doc["_id"], key, result)
    return {**result, "exact": {**result["exact"], "cached": False}}


def _has_figures(payload: dict) -> bool:
    """Whether a free payload has anything to show: the exact long-run
    availability, or the figures over time (computed, or on request)."""
    exact = payload.get("exact") or {}
    return payload.get("steady_state_availability") is not None or exact.get("status") in ("ok", "on_request")


def availability_payload(
    session, ctx: AccessCtx, graph: dict, t_max, rbd, force: bool, resolve_owners,
    *, simulate: bool | None = None, current_state=None, exact: bool = False,
) -> tuple[int, dict]:
    """A repairable (availability) analysis as ``(status, payload)``.

    Every user gets the exact figures (#154): the long-run values and, where
    RePyability's ``analysis_routes()`` has an exact or numerical route, the
    availability over time and the window's expected failures, outages,
    downtime and cost (``payload["exact"]``), from new or from
    ``current_state`` (#155). The Monte-Carlo simulation stays paid (Pro or
    purchased credits): ``simulate`` None runs it when the user is entitled
    and no saved result matches (the API's behaviour before #154), False
    never runs it (a saved result is still served), True runs it; ``force``
    re-runs over a saved one. A user who isn't entitled gets the exact
    figures with ``simulation_status.state == "pro_required"`` — or, when
    the diagram has no exact figures at all (simulation-only), 402 +
    :data:`AVAILABILITY_PRO_PAYLOAD` as before.

    ``rbd`` is the saved diagram the request is about (None for an unsaved
    graph, whose simulation is never saved). A fresh simulation is written
    back only when the caller may edit the diagram, and never one from a
    current state; read-only viewers (samples, shares) get the computation
    without touching the owner's document. ``exact`` asks for the figures
    over time of a diagram above the automatic size cap. Shared by the REST
    endpoints below and the MCP server, so both apply the same paid gate.
    Raises :class:`AnalysisError` for an invalid current state.
    """
    from backend.services import rbd_analysis, rbd_policies

    state = rbd_analysis.parse_current_state(graph, current_state)
    doc = session.rbds.find_one({"_id": rbd.id}) if rbd is not None else None
    writable = rbd is not None and access_service.can_write(ctx, rbd.owner_id)
    entitled = billing_service.premium_compute_allowed(session, ctx.user)
    free = exact_payload(session, graph, t_max, state, doc, writable, resolve_owners, exact)

    # The simulation: the saved one (from new only), or a run.
    key = rbds_service.availability_cache_key(graph, t_max)
    cached = rbds_service.cached_availability(doc, key) if state is None else None
    wanted = bool(force) or (entitled if simulate is None else bool(simulate))
    run = entitled and wanted and (cached is None or bool(force))
    sim = None
    if run:
        result = rbds_service.analyze_graph(session, graph, resolve_owners, t_max=t_max, state=state)
        computed_at = None
        if state is None and writable and rbds_service.should_store_availability(doc, key):
            computed_at = rbds_service.store_availability(session, rbd.id, key, result, ctx.uid)
        sim = {**result, "cached": False, "computed_at": computed_at}
        status = {"state": "done"}
    elif cached is not None:
        sim = cached
        status = {"state": "saved"}
    elif not entitled:
        status = {"state": "pro_required", "message": SIMULATION_PRO_MESSAGE}
    else:
        status = {"state": "not_run"}

    if sim is None and not entitled and not _has_figures(free):
        # Simulation-only diagram (no exact figures at all): the paywall, as before.
        return 402, AVAILABILITY_PRO_PAYLOAD

    if sim is not None:
        out = {**sim, "exact": free.get("exact"), "has_simulation": True}
    else:
        out = {**free, "has_simulation": False, "cached": False, "computed_at": None}
    out.update(
        simulation_status=status,
        current_state=state,
        # ``can_simulate`` / ``can_recompute`` let the UI offer "Run simulation"
        # and "Re-run" to entitled users, and the Pro offer to the rest.
        can_simulate=entitled,
        can_recompute=entitled,
    )
    # Common-cause groups the availability figures leave out (#185), said
    # beside them; RePyability's reasons in Reliafy's words, saved ones too (#186).
    common_cause = rbd_policies.common_cause_note(graph, out)
    if common_cause is not None:
        out["common_cause"] = common_cause
    return 200, rbd_analysis.plain_reasons(out)


def _availability(
    session, ctx: AccessCtx, graph: dict, t_max, rbd, force: bool, resolve_owners,
    simulate: bool | None = None, current_state=None, exact: bool = False,
) -> JSONResponse:
    # The exact figures (free) unless the simulation runs or meets the paywall.
    usage_service.set_feature("availability_exact")
    status, payload = availability_payload(
        session, ctx, graph, t_max, rbd, force, resolve_owners,
        simulate=simulate, current_state=current_state, exact=exact)
    if status == 402 or (payload.get("simulation_status") or {}).get("state") == "done":
        usage_service.set_feature("availability_sim")
    return JSONResponse(status_code=status, content=payload)


@router.post("/rbds/analyze")
def analyze_graph(
    graph: dict = Body(..., embed=True),
    t_max: float | None = Body(default=None),
    covariates: dict = Body(default={}),
    conditional_age: float | None = Body(default=None),
    band: dict | None = Body(default=None),
    rbd_id: str | None = Body(default=None),
    force: bool = Body(default=False),
    simulate: bool | None = Body(default=None),
    current_state: dict | None = Body(default=None),
    exact: bool = Body(default=False),
    target_reliability: float | None = Body(default=None),
    session=Depends(get_session),
    ctx: AccessCtx = Depends(get_access),
) -> JSONResponse:
    """Analyse an (unsaved) RBD graph with RePyability and return the results.

    ``t_max`` is the upper limit of the time axis to compute over.
    ``covariates`` maps node id -> covariate values for proportional-hazards
    nodes. ``conditional_age`` conditions the curves on having already survived
    to that age (so the result is the conditional survival). ``band``
    (``{"level": 0.95}``) adds a confidence band from the fitted blocks'
    parameter uncertainty.

    Repairable graphs get the exact availability figures (free) and the
    availability simulation (paid; see :func:`availability_payload`).
    ``rbd_id`` names the saved diagram being edited so a saved result can be
    served / stored; ``force`` re-runs even when a saved result matches
    (entitled users only); ``simulate`` false skips the simulation, true asks
    for it; ``current_state`` (``{node_id: {"down": true, "since": …} |
    {"age": …}}``) starts the figures from now, over ``t_max``; ``exact``
    computes the figures over time of a diagram above the automatic size cap.

    Non-repairable graphs (#173): ``current_state`` (``{node_id: {"failed":
    true} | {"age": …}}``) analyses the diagram as of now — the curves, MTTF
    and B-lives run from now — and ``target_reliability`` (e.g. 0.9) adds the
    design life, the time the system reliability falls to it (with an
    interval when ``band`` is asked for). Both are exact, free for everyone.
    """
    try:
        if graph.get("repairable"):
            rbd = None
            if rbd_id:
                rbd, _ = access_service.fetch_readable(session, "rbds", Rbd, rbd_id, ctx)
            return _availability(session, ctx, graph, t_max, rbd, force, ctx.read_owners,
                                 simulate=simulate, current_state=current_state, exact=exact)
        return JSONResponse(
            content=rbds_service.analyze_graph(
                session,
                graph,
                ctx.read_owners,
                t_max=t_max,
                covariates=covariates,
                conditional_age=conditional_age,
                band=band,
                current_state=current_state,
                target_reliability=target_reliability,
            )
        )
    except AnalysisError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    except Exception:  # pragma: no cover - defensive
        logger.exception("Failed to analyse RBD graph")
        return JSONResponse(
            status_code=500, content={"detail": "Failed to analyse RBD. The error has been logged."}
        )


@router.get("/rbds/{rbd_id}/analyze")
def analyze_rbd(
    rbd_id: str,
    t_max: float | None = None,
    force: bool = False,
    simulate: bool | None = None,
    exact: bool = False,
    session=Depends(get_session),
    ctx: AccessCtx = Depends(get_access),
) -> JSONResponse:
    """Analyse a saved RBD with RePyability and return the results (for a
    repairable one, ``simulate`` and ``exact`` as for ``POST /rbds/analyze``)."""
    rbd, _ = access_service.fetch_readable(session, "rbds", Rbd, rbd_id, ctx)
    if rbd is None:
        return JSONResponse(status_code=404, content={"detail": "RBD not found."})
    graph = rbd.graph or {}
    owners = [*ctx.read_owners, rbd.owner_id]
    try:
        if graph.get("repairable"):
            return _availability(session, ctx, graph, t_max, rbd, force, owners,
                                 simulate=simulate, exact=exact)
        return JSONResponse(
            content=rbds_service.analyze_graph(session, graph, owners, t_max=t_max)
        )
    except rbds_service.RbdNotFound:
        return JSONResponse(status_code=404, content={"detail": "RBD not found."})
    except AnalysisError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    except Exception:  # pragma: no cover - defensive
        logger.exception("Failed to analyse RBD %s", rbd_id)
        return JSONResponse(
            status_code=500, content={"detail": "Failed to analyse RBD. The error has been logged."}
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
    except Exception:  # pragma: no cover - defensive
        logger.exception("Failed to export RBD %s as Python", rbd_id)
        return JSONResponse(
            status_code=500, content={"detail": "Failed to export RBD. The error has been logged."}
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
