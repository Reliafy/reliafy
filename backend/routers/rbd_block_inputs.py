"""A block's model entered as its mean, and its mean and median (#299): the
block dialog's "Enter as Mean" and its echo. Quick and exact, so not
plan-gated; nothing is saved."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse

from backend.auth import get_current_user
from backend.services import rbd_block_inputs

router = APIRouter(prefix="/api")


@router.get("/rbd-blocks/mean-forms")
def mean_forms(user: dict = Depends(get_current_user)) -> dict:
    """The distributions a mean can be entered for, and the parameters each
    takes with it (SurPyval's names): ``{"weibull": {"given": ["beta"]}}``."""
    return {"forms": rbd_block_inputs.mean_entry_forms()}


@router.post("/rbd-blocks/model")
def block_model(
    distribution_id: str = Body(...),
    params: list | None = Body(default=None),
    mean: float | None = Body(default=None),
    given: dict | None = Body(default=None),
    user: dict = Depends(get_current_user),
) -> JSONResponse:
    """A model's SurPyval parameters, mean and median: from ``params``
    (``[{name, value}]``), or from its ``mean`` and the shape or spread in
    ``given`` (``{"beta": 1.6}``). 422 with a plain reason when SurPyval
    can't build it."""
    try:
        if mean is not None:
            out = rbd_block_inputs.from_mean(distribution_id, mean, given)
        else:
            out = rbd_block_inputs.summary(distribution_id, params or [])
    except rbd_block_inputs.BlockInputError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    return JSONResponse(content=out)
