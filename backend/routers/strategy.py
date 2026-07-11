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
from backend.services import strategy_store
from backend.services.strategy import StrategyError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/strategy")


@router.post("/compare")
async def compare_endpoint(
    file: UploadFile = File(...),
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
    """Fit and rank every parametric distribution against a dataset."""
    contents = await file.read()
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

def _analysis_summary(doc) -> dict:
    return {
        "id": doc.id,
        "name": doc.name,
        "kind": doc.kind,
        "headline": strategy_store.headline(doc),
        "is_sample": samples_service.is_sample(doc.owner_id),
        "created_at": doc.created_at.isoformat(),
        "updated_at": doc.updated_at.isoformat(),
    }


@router.post("/analyses")
def save_analysis(
    name: str = Body(...),
    kind: str = Body(...),
    inputs: dict = Body(default={}),
    session=Depends(get_session),
    user: dict = Depends(get_current_user),
) -> JSONResponse:
    """Persist a strategy analysis. Results are recomputed server-side from the
    inputs — clients never supply results (saved analyses are RCM evidence)."""
    try:
        doc = strategy_store.save_analysis(session, name, kind, inputs, user["uid"])
    except StrategyError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    return JSONResponse(content={**_analysis_summary(doc), "inputs": doc.inputs, "results": doc.results})


@router.get("/analyses")
def list_analyses(session=Depends(get_session), user: dict = Depends(get_current_user)) -> dict:
    hidden = samples_service.hidden_sample_ids(session, user["uid"])
    return {"analyses": [_analysis_summary(d) for d in strategy_store.list_analyses(session, user["uid"], hidden)]}


@router.get("/analyses/{analysis_id}")
def get_analysis(
    analysis_id: str, session=Depends(get_session), user: dict = Depends(get_current_user)
) -> JSONResponse:
    hidden = samples_service.hidden_sample_ids(session, user["uid"])
    doc = strategy_store.get_analysis(session, analysis_id, user["uid"])
    if doc is None or doc.id in hidden:
        return JSONResponse(status_code=404, content={"detail": "Analysis not found."})
    return JSONResponse(content={**_analysis_summary(doc), "inputs": doc.inputs, "results": doc.results})


@router.patch("/analyses/{analysis_id}")
def rename_analysis(
    analysis_id: str,
    name: str = Body(..., embed=True),
    session=Depends(get_session),
    user: dict = Depends(get_current_user),
) -> JSONResponse:
    existing = strategy_store.get_analysis(session, analysis_id, user["uid"])
    if existing is not None and samples_service.is_sample(existing.owner_id):
        return JSONResponse(status_code=403, content={"detail": "Sample analyses are read-only."})
    try:
        doc = strategy_store.rename_analysis(session, analysis_id, name, user["uid"])
    except strategy_store.AnalysisNotFound:
        return JSONResponse(status_code=404, content={"detail": "Analysis not found."})
    return JSONResponse(content=_analysis_summary(doc))


@router.delete("/analyses/{analysis_id}")
def delete_analysis(
    analysis_id: str, session=Depends(get_session), user: dict = Depends(get_current_user)
) -> JSONResponse:
    uid = user["uid"]
    hidden = samples_service.hidden_sample_ids(session, uid)
    doc = strategy_store.get_analysis(session, analysis_id, uid)
    if doc is None or doc.id in hidden:
        return JSONResponse(status_code=404, content={"detail": "Analysis not found."})
    if samples_service.is_sample(doc.owner_id):
        samples_service.hide_sample(session, uid, analysis_id)
        return JSONResponse(content={"ok": True})
    try:
        strategy_store.delete_analysis(session, analysis_id, uid)
    except strategy_store.AnalysisNotFound:
        return JSONResponse(status_code=404, content={"detail": "Analysis not found."})
    return JSONResponse(content={"ok": True})
