"""Compare groups within a dataset (#175): POST /api/datasets/{id}/compare-groups.

Non-parametric (Kaplan-Meier curves, log-rank, RMST, Gray's test): nothing is
fitted or simulated, so it is open to every plan, like the two-model
comparison under Strategy.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse

from backend.db import get_session
from backend.schema import Dataset
from backend.services import access as access_service
from backend.services import compare_groups as compare_service
from backend.services import datasets as datasets_service
from backend.services.access import AccessCtx, get_access

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


@router.post("/datasets/{dataset_id}/compare-groups")
def compare_groups_endpoint(
    dataset_id: str,
    time_column: str = Body(...),
    group_column: str = Body(...),
    censor_column: Optional[str] = Body(default=None),
    count_column: Optional[str] = Body(default=None),
    cause_column: Optional[str] = Body(default=None),
    c_invert: bool = Body(default=False),
    groups: Optional[list] = Body(default=None),
    reference: Optional[str] = Body(default=None),
    tau: Optional[float] = Body(default=None),
    unit: Optional[str] = Body(default=None),
    session=Depends(get_session),
    ctx: AccessCtx = Depends(get_access),
) -> JSONResponse:
    """Split the dataset by ``group_column`` and compare the groups' life."""
    dataset, _ = access_service.fetch_readable(session, "datasets", Dataset, dataset_id, ctx)
    if dataset is None or dataset.id in ctx.hidden:
        return JSONResponse(status_code=404, content={"detail": "Dataset not found."})
    try:
        df = datasets_service.load_dataframe(dataset)
        data = compare_service.prepare(
            df, time_column=time_column, group_column=group_column, censor_column=censor_column or None,
            count_column=count_column or None, cause_column=cause_column or None, c_invert=c_invert)
        result = compare_service.compare_groups(
            data, groups=groups, reference=reference or None, tau=tau, unit=unit, group_column=group_column)
    except ValueError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    except Exception:  # pragma: no cover - defensive
        logger.exception("Group comparison failed")
        return JSONResponse(status_code=500, content={"detail": "Comparison failed. The error has been logged."})
    return JSONResponse(content=result)
