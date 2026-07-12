"""Strategy / decision-support API: model comparison and optimal replacement."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Depends, File, Form, UploadFile
from fastapi.responses import JSONResponse

from backend.auth import get_current_user
from backend.db import get_session
from backend.fitting import read_dataframe
from backend.services import samples as samples_service
from backend.services import strategy as strategy_service
from backend.services import access as access_service
from backend.services import shares as shares_service
from backend.services.access import AccessCtx, get_access
from backend.schema import StrategyAnalysis
from backend.services import strategy_store
from backend.services.strategy import StrategyError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/strategy")


@router.post("/compare")
async def compare_endpoint(
    file: UploadFile | None = File(default=None),
    dataset_id: str | None = Form(default=None),
    x: str | None = Form(default=None),
    c: str | None = Form(default=None),
    n: str | None = Form(default=None),
    xl: str | None = Form(default=None),
    xr: str | None = Form(default=None),
    tl: str | None = Form(default=None),
    tr: str | None = Form(default=None),
    unit: str | None = Form(default=None),
    user: dict = Depends(get_current_user),
) -> JSONResponse:
    """Fit and rank every parametric distribution against a dataset (an
    uploaded CSV, or a saved dataset by id — e.g. the samples)."""
    if dataset_id:
        from backend.db import get_db
        from backend.services import datasets as datasets_service

        dataset = datasets_service.get_dataset(get_db(), dataset_id, owner_id=user["uid"])
        if dataset is None:
            return JSONResponse(status_code=404, content={"detail": "Dataset not found."})
        contents = dataset.data
    elif file is not None:
        contents = await file.read()
    else:
        return JSONResponse(status_code=422, content={"detail": "Provide a CSV file or a dataset_id."})
    mapping = {"x": x, "c": c, "n": n, "xl": xl, "xr": xr, "tl": tl, "tr": tr}
    try:
        df = read_dataframe(contents)
        return JSONResponse(
            content=strategy_service.compare_models(df, mapping, unit=unit)
        )
    except StrategyError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("Model comparison failed")
        return JSONResponse(
            status_code=500, content={"detail": f"Comparison failed: {exc}"}
        )


@router.post("/optimal-replacement")
def optimal_replacement_endpoint(
    distribution_id: str = Body(...),
    params: list = Body(default=[]),
    planned_cost: float | None = Body(default=None),
    unplanned_cost: float | None = Body(default=None),
    unit: str | None = Body(default=None),
    user: dict = Depends(get_current_user),
) -> JSONResponse:
    """Compute the cost-optimal preventive-replacement interval."""
    try:
        return JSONResponse(
            content=strategy_service.optimal_replacement(
                distribution_id, params, planned_cost, unplanned_cost, unit=unit
            )
        )
    except StrategyError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("Optimal replacement failed")
        return JSONResponse(
            status_code=500, content={"detail": f"Calculation failed: {exc}"}
        )


@router.post("/compare-two")
def compare_two_endpoint(
    a: dict = Body(...),
    b: dict = Body(...),
    unit: str | None = Body(default=None),
    user: dict = Depends(get_current_user),
) -> JSONResponse:
    """Compare two models' reliability (which item is more reliable)."""
    try:
        return JSONResponse(content=strategy_service.compare_two(a, b, unit=unit))
    except StrategyError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("Two-model comparison failed")
        return JSONResponse(
            status_code=500, content={"detail": f"Comparison failed: {exc}"}
        )


@router.post("/failure-finding")
def failure_finding_endpoint(
    distribution_id: str = Body(...),
    params: list = Body(default=[]),
    target_availability: float = Body(...),
    unit: str | None = Body(default=None),
    user: dict = Depends(get_current_user),
) -> JSONResponse:
    """Failure-finding interval for a hidden failure (protective device)."""
    try:
        return JSONResponse(
            content=strategy_service.failure_finding(
                distribution_id, params, target_availability, unit=unit
            )
        )
    except StrategyError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("Failure-finding calculation failed")
        return JSONResponse(
            status_code=500, content={"detail": f"Calculation failed: {exc}"}
        )


# ---- Saved analyses ----------------------------------------------------------

def _analysis_summary(doc, ctx: AccessCtx) -> dict:
    return {
        "id": doc.id,
        "name": doc.name,
        "kind": doc.kind,
        "headline": strategy_store.headline(doc),
        "is_sample": samples_service.is_sample(doc.owner_id),
        "read_only": not access_service.can_write(ctx, doc.owner_id),
        "updated_by": (doc.updated_by or {}).get("name"),
        "created_at": doc.created_at.isoformat(),
        "updated_at": doc.updated_at.isoformat(),
    }


@router.post("/analyses")
def save_analysis(
    name: str = Body(...),
    kind: str = Body(...),
    inputs: dict = Body(default={}),
    session=Depends(get_session),
    ctx: AccessCtx = Depends(get_access),
) -> JSONResponse:
    """Persist a strategy analysis. Results are recomputed server-side from the
    inputs — clients never supply results (saved analyses are RCM evidence)."""
    denied = access_service.workspace_write_denial(ctx)
    if denied is not None:
        status, payload = denied
        return JSONResponse(status_code=status, content=payload)
    try:
        doc = strategy_store.save_analysis(session, name, kind, inputs, ctx.write_owner)
        access_service.stamp_editor(session, "strategy_analyses", doc.id, ctx)
    except StrategyError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    return JSONResponse(content={**_analysis_summary(doc, ctx), "inputs": doc.inputs, "results": doc.results})


@router.get("/analyses")
def list_analyses(session=Depends(get_session), ctx: AccessCtx = Depends(get_access)) -> dict:
    shared_by = shares_service.shared_by_map(session, ctx.uid, "strategy_analyses") if ctx.is_personal else {}
    return {"analyses": [
        {**_analysis_summary(d, ctx), **({"shared_by": shared_by[d.id]} if d.id in shared_by else {})}
        for d in strategy_store.list_analyses(session, ctx.list_owners, ctx.hidden, shared=set(shared_by))
    ]}


@router.get("/analyses/{analysis_id}")
def get_analysis(
    analysis_id: str, session=Depends(get_session), ctx: AccessCtx = Depends(get_access)
) -> JSONResponse:
    doc, via_share = access_service.fetch_readable(session, "strategy_analyses", StrategyAnalysis, analysis_id, ctx)
    if doc is None or doc.id in ctx.hidden:
        return JSONResponse(status_code=404, content={"detail": "Analysis not found."})
    payload = {**_analysis_summary(doc, ctx), "inputs": doc.inputs, "results": doc.results}
    if via_share:
        payload["shared_by"] = shares_service.shared_by_for(session, ctx.uid, doc.id)
    return JSONResponse(content=payload)


@router.patch("/analyses/{analysis_id}")
def rename_analysis(
    analysis_id: str,
    name: str = Body(..., embed=True),
    session=Depends(get_session),
    ctx: AccessCtx = Depends(get_access),
) -> JSONResponse:
    existing, _ = access_service.fetch_readable(session, "strategy_analyses", StrategyAnalysis, analysis_id, ctx)
    if existing is not None:
        denial = access_service.write_denial(ctx, existing.owner_id)
        if denial:
            status, payload = denial
            return JSONResponse(status_code=status, content=payload)
    try:
        doc = strategy_store.rename_analysis(session, analysis_id, name, ctx.write_owner)
        access_service.stamp_editor(session, "strategy_analyses", doc.id, ctx)
    except strategy_store.AnalysisNotFound:
        return JSONResponse(status_code=404, content={"detail": "Analysis not found."})
    return JSONResponse(content=_analysis_summary(doc, ctx))


@router.delete("/analyses/{analysis_id}")
def delete_analysis(
    analysis_id: str, session=Depends(get_session), ctx: AccessCtx = Depends(get_access)
) -> JSONResponse:
    doc, _ = access_service.fetch_readable(session, "strategy_analyses", StrategyAnalysis, analysis_id, ctx)
    if doc is None or doc.id in ctx.hidden:
        return JSONResponse(status_code=404, content={"detail": "Analysis not found."})
    if access_service.can_write(ctx, doc.owner_id):
        try:
            strategy_store.delete_analysis(session, analysis_id, ctx.write_owner)
        except strategy_store.AnalysisNotFound:
            return JSONResponse(status_code=404, content={"detail": "Analysis not found."})
    elif samples_service.is_sample(doc.owner_id) or access_service.is_shared_with(session, ctx.uid, analysis_id):
        samples_service.hide_sample(session, ctx.uid, analysis_id)
    else:
        status, payload = access_service.write_denial(ctx, doc.owner_id)
        return JSONResponse(status_code=status, content=payload)
    return JSONResponse(content={"ok": True})
