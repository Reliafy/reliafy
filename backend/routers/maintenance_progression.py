"""Time to the limit for a watched level (the Signals tab): the same operations as the
maintenance tool's ``progression.*`` actions. Routes are added to the maintenance router."""

from __future__ import annotations

from fastapi import Depends
from fastapi.responses import JSONResponse

from backend.maintenance.service import Maintenance
from backend.routers.maintenance import _run, maintenance, router


@router.get("/signals/bands/{point_id}/time-to-limit")
def time_to_limit(point_id: str, process: str = "wiener", limit: float | None = None, since: str | None = None,
                  confidence: float = 0.8, m: Maintenance = Depends(maintenance)) -> JSONResponse:
    return _run(m.time_to_limit, point_id, process, limit, since, confidence)


@router.get("/signals/bands/{point_id}/degradation-series")
def degradation_series(point_id: str, since: str | None = None, unit_name: str | None = None,
                       m: Maintenance = Depends(maintenance)) -> JSONResponse:
    return _run(m.progression_series, point_id, since, unit_name)
