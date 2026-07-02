"""Strategy / decision-support API: model comparison and optimal replacement."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Depends, File, Form, UploadFile
from fastapi.responses import JSONResponse

from backend.auth import get_current_user
from backend.fitting import read_dataframe
from backend.services import strategy as strategy_service
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
