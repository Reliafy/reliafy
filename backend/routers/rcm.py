"""RCM study API: worksheet CRUD + live evidence validation."""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Body, Depends, File, Form, UploadFile
from fastapi.responses import JSONResponse

from backend.auth import get_current_user
from backend.db import get_session
from backend.routers import excel as excel_router
from backend.services import billing as billing_service
from backend.services import excel
from backend.services import rcm_import
from backend.services import rbd_rcm
from backend.services import rcm as rcm_service
from backend.services import samples as samples_service
from backend.services import access as access_service
from backend.services import shares as shares_service
from backend.services.access import AccessCtx, get_access
from backend.schema import RcmStudy

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/rcm")

# The decision-diagram guidance surfaced in the UI. Suggestions follow the
# classic RCM logic: hidden failures need failure-finding; safety/environmental
# consequences demand proactive tasks or redesign; economic consequences allow
# run-to-failure when the numbers support it.
CONSEQUENCE_OPTIONS = [
    {"id": "safety", "label": "Safety",
     "hint": "Could hurt someone. A proactive task must reduce the risk to a tolerable level — otherwise redesign is compulsory.",
     "suggested_outcomes": ["on_condition", "fixed_interval", "redesign"]},
    {"id": "environmental", "label": "Environmental",
     "hint": "Could breach an environmental standard. Treat like safety: proactive task or redesign.",
     "suggested_outcomes": ["on_condition", "fixed_interval", "redesign"]},
    {"id": "operational", "label": "Operational",
     "hint": "Affects output or quality. A proactive task must cost less than the consequences it prevents — otherwise run-to-failure.",
     "suggested_outcomes": ["on_condition", "fixed_interval", "rtf"]},
    {"id": "non_operational", "label": "Non-operational",
     "hint": "Only the repair cost matters. Proactive maintenance rarely pays — run-to-failure unless the numbers say otherwise.",
     "suggested_outcomes": ["rtf", "fixed_interval", "accept"]},
    {"id": "hidden", "label": "Hidden",
     "hint": "The failure is invisible in normal operation (protective devices). Schedule failure-finding checks, or redesign to make it evident.",
     "suggested_outcomes": ["failure_finding", "on_condition", "redesign"]},
]

OUTCOME_OPTIONS = [
    {"id": "on_condition", "label": "On-condition (monitor)",
     "expected_evidence": "degradation_model",
     "fields": ["task", "interval"],
     "hint": "Monitor a degradation signal and act before the threshold. Link the degradation model that shows the failure develops measurably."},
    {"id": "fixed_interval", "label": "Fixed-interval replacement",
     "expected_evidence": "strategy_analysis",
     "fields": ["task", "interval"],
     "hint": "Replace or restore on a schedule. Link the optimal-replacement analysis showing the interval is cost-optimal."},
    {"id": "rtf", "label": "Run-to-failure",
     "expected_evidence": None,  # depends on rtf_basis
     "fields": ["rtf_basis", "task"],
     "hint": "Let it fail, then fix it. Justify with either a life model showing random failures, or a replacement analysis showing prevention isn't economic."},
    {"id": "failure_finding", "label": "Failure-finding task",
     "expected_evidence": "strategy_analysis",
     "fields": ["task", "interval"],
     "hint": "Periodically check a hidden function. Link the failure-finding-interval analysis that sets the check frequency."},
    {"id": "redesign", "label": "Redesign",
     "expected_evidence": None, "fields": ["notes"],
     "hint": "No suitable task exists — change the design (or the operating context) instead."},
    {"id": "accept", "label": "Accept risk / no scheduled maintenance",
     "expected_evidence": None, "fields": ["notes"],
     "hint": "The consequences are tolerable and no task is worthwhile. Document why."},
]


@router.get("/options")
def rcm_options(user: dict = Depends(get_current_user)) -> dict:
    return {
        "consequences": CONSEQUENCE_OPTIONS,
        "outcomes": OUTCOME_OPTIONS,
        "rtf_bases": [
            {"id": "random", "label": "Failures are random",
             "expected_evidence": "model",
             "hint": "Evidence: a Weibull fit whose β confidence interval contains 1, or an Exponential fit."},
            {"id": "uneconomic", "label": "Prevention isn't economic",
             "expected_evidence": "strategy_analysis",
             "hint": "Evidence: an optimal-replacement analysis showing no beneficial interval."},
        ],
    }


def _summary(study, ctx: AccessCtx, rollup=None) -> dict:
    return {
        "id": study.id,
        "name": study.name,
        "system": study.system,
        "description": study.description,
        "is_sample": samples_service.is_sample(study.owner_id),
        "read_only": not access_service.can_write(ctx, study.owner_id),
        "updated_by": (study.updated_by or {}).get("name"),
        "rollup": rollup,
        "created_at": study.created_at.isoformat(),
        "updated_at": study.updated_at.isoformat(),
    }


@router.post("/studies")
def create_study(
    name: str = Body(...),
    system: str = Body(default=""),
    description: str = Body(default=""),
    session=Depends(get_session),
    ctx: AccessCtx = Depends(get_access),
) -> JSONResponse:
    denied = access_service.workspace_write_denial(ctx)
    if denied is not None:
        status, payload = denied
        return JSONResponse(status_code=status, content=payload)
    if (
        ctx.is_personal
        and not billing_service.is_admin_user(ctx.user)
        and billing_service.would_exceed_cap(session, ctx.uid, "rcm_studies")
    ):
        return JSONResponse(status_code=402, content={"detail": billing_service.cap_message(session, ctx.uid, "rcm_studies"), "code": "cap", "upgrade": True})
    try:
        study = rcm_service.create_study(session, name, system, description, ctx.write_owner)
    except rcm_service.RcmValidationError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    access_service.stamp_editor(session, "rcm_studies", study.id, ctx)
    return JSONResponse(content=_summary(study, ctx))


@router.get("/studies")
def list_studies(session=Depends(get_session), ctx: AccessCtx = Depends(get_access)) -> dict:
    shared_by = shares_service.shared_by_map(session, ctx.uid, "rcm_studies") if ctx.is_personal else {}
    out = []
    for study in rcm_service.list_studies(session, ctx.list_owners, ctx.hidden, shared=set(shared_by)):
        # Resolve as the study's own owner too, so a shared study's evidence
        # statuses match what its author sees.
        resolved = rcm_service.resolve(session, study, [*ctx.read_owners, study.owner_id], ctx.hidden)
        row = _summary(study, ctx, resolved["rollup"])
        if study.id in shared_by:
            row["shared_by"] = shared_by[study.id]
        out.append(row)
    return {"studies": out}


@router.get("/studies/{study_id}")
def get_study(
    study_id: str, session=Depends(get_session), ctx: AccessCtx = Depends(get_access)
) -> JSONResponse:
    study, via_share = access_service.fetch_readable(session, "rcm_studies", RcmStudy, study_id, ctx)
    if study is None or study.id in ctx.hidden:
        return JSONResponse(status_code=404, content={"detail": "Study not found."})
    resolved = rcm_service.resolve(session, study, [*ctx.read_owners, study.owner_id], ctx.hidden)
    payload = {**_summary(study, ctx, resolved["rollup"]), "functions": resolved["functions"]}
    if via_share:
        payload["shared_by"] = shares_service.shared_by_for(session, ctx.uid, study.id)
    return JSONResponse(content=payload)


@router.get("/studies/{study_id}/maintenance-tasks")
def maintenance_tasks(
    study_id: str, unit: str = "", session=Depends(get_session), ctx: AccessCtx = Depends(get_access)
) -> JSONResponse:
    """The study's tasks as a repairable RBD block's maintenance (#100): what
    each would fill (scheduled replacement or proof test) in a diagram whose
    time unit is ``unit``, or why it can't."""
    study, _ = access_service.fetch_readable(session, "rcm_studies", RcmStudy, study_id, ctx)
    if study is None or study.id in ctx.hidden:
        return JSONResponse(status_code=404, content={"detail": "Study not found."})
    return JSONResponse(content=rbd_rcm.maintenance_tasks(
        session, study, [*ctx.read_owners, study.owner_id], ctx.hidden, unit[:40],
    ))


@router.patch("/studies/{study_id}")
def rename_study(
    study_id: str,
    name: str = Body(..., embed=True),
    session=Depends(get_session),
    ctx: AccessCtx = Depends(get_access),
) -> JSONResponse:
    existing, _ = access_service.fetch_readable(session, "rcm_studies", RcmStudy, study_id, ctx)
    if existing is not None:
        denial = access_service.write_denial(ctx, existing.owner_id)
        if denial:
            status, payload = denial
            return JSONResponse(status_code=status, content=payload)
    try:
        study = rcm_service.rename_study(session, study_id, name, ctx.write_owner)
    except rcm_service.StudyNotFound:
        return JSONResponse(status_code=404, content={"detail": "Study not found."})
    return JSONResponse(content=_summary(study, ctx))


@router.delete("/studies/{study_id}")
def delete_study(
    study_id: str, session=Depends(get_session), ctx: AccessCtx = Depends(get_access)
) -> JSONResponse:
    study, _ = access_service.fetch_readable(session, "rcm_studies", RcmStudy, study_id, ctx)
    if study is None or study.id in ctx.hidden:
        return JSONResponse(status_code=404, content={"detail": "Study not found."})
    if access_service.can_write(ctx, study.owner_id):
        try:
            rcm_service.delete_study(session, study_id, ctx.write_owner)
        except rcm_service.StudyNotFound:
            return JSONResponse(status_code=404, content={"detail": "Study not found."})
    elif samples_service.is_sample(study.owner_id) or access_service.is_shared_with(session, ctx.uid, study_id):
        samples_service.hide_sample(session, ctx.uid, study_id)
    else:
        status, payload = access_service.write_denial(ctx, study.owner_id)
        return JSONResponse(status_code=status, content=payload)
    return JSONResponse(content={"ok": True})


def _import_tree(data: bytes, filename: str, sheet, header_row, options: str | None) -> dict:
    """Read the uploaded worksheet and map it into a tree (raises the
    user-facing ExcelError / RcmImportError / ValueError)."""
    try:
        opts = json.loads(options) if options else {}
    except ValueError:
        raise rcm_import.RcmImportError("The import options aren't valid JSON.") from None
    if not isinstance(opts, dict):
        raise rcm_import.RcmImportError("The import options must be an object.")
    table = excel.read_table(data, sheet, excel_router.header_row_param(header_row), filename)
    result = rcm_import.build_tree(table.header, table.rows, opts, table.row_numbers)
    result["notes"] = table.notes
    return result


def _import_error(exc: Exception, data: bytes, filename: str) -> JSONResponse:
    if isinstance(exc, (rcm_import.RcmImportError, excel.ExcelError)):
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    return excel_router.excel_error(exc, "rcm import", data, filename)


@router.post("/import/preview")
def import_preview(
    file: UploadFile = File(...),
    sheet: str | None = Form(default=None),
    header_row: str | None = Form(default=None),
    options: str | None = Form(default=None),
    ctx: AccessCtx = Depends(get_access),
) -> JSONResponse:
    """What an FMEA / RCM spreadsheet would import as — nothing is saved.

    ``options`` is JSON: ``{mapping, consequence_map, outcome_map,
    extra_columns}`` (see :func:`backend.services.rcm_import.build_tree`).
    The response lists the consequence / decision values found, with the
    automatic mapping of each, so the user can adjust them.
    """
    data = excel_router.read_upload(file)
    try:
        return JSONResponse(content=_import_tree(data, file.filename or "", sheet, header_row, options))
    except Exception as exc:
        return _import_error(exc, data, file.filename or "")


@router.post("/import")
def import_worksheet(
    file: UploadFile = File(...),
    sheet: str | None = Form(default=None),
    header_row: str | None = Form(default=None),
    options: str | None = Form(default=None),
    study_id: str | None = Form(default=None),
    mode: str = Form(default="append"),
    expected_updated_at: str | None = Form(default=None),
    name: str | None = Form(default=None),
    system: str = Form(default=""),
    description: str = Form(default=""),
    session=Depends(get_session),
    ctx: AccessCtx = Depends(get_access),
) -> JSONResponse:
    """Import a worksheet: into a new study (no ``study_id``: ``name``
    required, the free-plan cap applies), or into an existing one —
    ``mode="append"`` adds the imported functions after the existing ones,
    ``mode="replace"`` swaps the whole worksheet (decisions and evidence links
    included). ``expected_updated_at`` guards against overwriting someone
    else's save, as for ``PUT /tree``.
    """
    if mode not in ("append", "replace"):
        return JSONResponse(status_code=422, content={"detail": "mode must be 'append' or 'replace'."})
    existing = None
    if study_id:
        existing, _ = access_service.fetch_readable(session, "rcm_studies", RcmStudy, study_id, ctx)
        if existing is None or existing.id in ctx.hidden:
            return JSONResponse(status_code=404, content={"detail": "Study not found."})
        denial = access_service.write_denial(ctx, existing.owner_id)
        if denial:
            status, payload = denial
            return JSONResponse(status_code=status, content=payload)
    else:
        if not (name or "").strip():
            return JSONResponse(status_code=422, content={"detail": "The study needs a name."})
        denied = access_service.workspace_write_denial(ctx)
        if denied is not None:
            status, payload = denied
            return JSONResponse(status_code=status, content=payload)
        if (
            ctx.is_personal
            and not billing_service.is_admin_user(ctx.user)
            and billing_service.would_exceed_cap(session, ctx.uid, "rcm_studies")
        ):
            return JSONResponse(status_code=402, content={"detail": billing_service.cap_message(session, ctx.uid, "rcm_studies"), "code": "cap", "upgrade": True})

    data = excel_router.read_upload(file)
    try:
        result = _import_tree(data, file.filename or "", sheet, header_row, options)
    except Exception as exc:
        return _import_error(exc, data, file.filename or "")

    imported = result["functions"]
    try:
        if existing is None:
            study = rcm_service.create_study(session, name, system, description, ctx.write_owner)
            study = rcm_service.replace_tree(session, study.id, imported, ctx.write_owner, reader=ctx)
        else:
            functions = imported if mode == "replace" else [*(existing.functions or []), *imported]
            study = rcm_service.replace_tree(
                session, existing.id, functions, ctx.write_owner,
                expected_updated_at=expected_updated_at, reader=ctx,
            )
    except rcm_service.StudyNotFound:
        return JSONResponse(status_code=404, content={"detail": "Study not found."})
    except rcm_service.RcmValidationError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    except access_service.UnreadableReference as exc:
        return JSONResponse(status_code=exc.status, content={"detail": str(exc), "code": "unreadable_reference"})
    except access_service.EditConflict:
        return JSONResponse(status_code=409, content={"detail": access_service.CONFLICT_MSG, "code": "conflict"})
    access_service.stamp_editor(session, "rcm_studies", study.id, ctx)
    study.updated_by = access_service.editor_of(ctx)
    logger.info(
        "RCM import: %s modes=%d functions=%d decisions=%d",
        "new study" if existing is None else mode, result["counts"]["modes"],
        result["counts"]["functions"], result["counts"]["decisions"],
    )
    resolved = rcm_service.resolve(session, study, [*ctx.read_owners, study.owner_id], ctx.hidden)
    return JSONResponse(content={
        **_summary(study, ctx, resolved["rollup"]),
        "functions": resolved["functions"],
        "imported": {"counts": result["counts"], "warnings": result["warnings"]},
    })


@router.put("/studies/{study_id}/tree")
def put_tree(
    study_id: str,
    functions: list = Body(..., embed=True),
    expected_updated_at: str | None = Body(default=None),
    session=Depends(get_session),
    ctx: AccessCtx = Depends(get_access),
) -> JSONResponse:
    existing, _ = access_service.fetch_readable(session, "rcm_studies", RcmStudy, study_id, ctx)
    if existing is not None:
        denial = access_service.write_denial(ctx, existing.owner_id)
        if denial:
            status, payload = denial
            return JSONResponse(status_code=status, content=payload)
    try:
        study = rcm_service.replace_tree(
            session, study_id, functions, ctx.write_owner,
            expected_updated_at=expected_updated_at, reader=ctx,
        )
    except rcm_service.StudyNotFound:
        return JSONResponse(status_code=404, content={"detail": "Study not found."})
    except rcm_service.RcmValidationError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    except access_service.UnreadableReference as exc:
        return JSONResponse(status_code=exc.status, content={"detail": str(exc), "code": "unreadable_reference"})
    except access_service.EditConflict:
        return JSONResponse(status_code=409, content={"detail": access_service.CONFLICT_MSG, "code": "conflict"})
    access_service.stamp_editor(session, "rcm_studies", study_id, ctx)
    study.updated_by = access_service.editor_of(ctx)
    resolved = rcm_service.resolve(session, study, ctx.read_owners, ctx.hidden)
    return JSONResponse(content={**_summary(study, ctx, resolved["rollup"]), "functions": resolved["functions"]})
