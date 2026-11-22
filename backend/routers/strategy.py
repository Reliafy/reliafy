"""Strategy / decision-support API: optimal replacement and decision support."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse

from backend.auth import get_current_user
from backend.db import get_session
from backend.services import samples as samples_service
from backend.services import strategy as strategy_service
from backend.services import access as access_service
from backend.services import shares as shares_service
from backend.services.access import AccessCtx, get_access
from backend.schema import StrategyAnalysis
from backend.services import strategy_store
from backend.services.strategy import StrategyError
from backend.services import billing as billing_service
from backend.services import strategy_calendar
from backend.services import strategy_calendar_api
from backend.services.rbd_analysis import AnalysisError
from backend.errors import client_message

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/strategy")


def _position_clock(ctx: AccessCtx, position_id, unit) -> dict:
    """Run from a position (the Explorer's Strategy pane, or MCP analyse with position_id) with a
    model in running hours or in use (km, cycles): the position's clock, ``{"clock"}``, and
    ``"hours_per_day"`` (the model's units a day there: its duty's hours, else 24; its km a day)
    when the duty gives a rate in that unit (running_clock). Without one, the clock alone: the
    calculators then say plainly why the model can't meet the calendar. Empty otherwise (no
    position, a calendar or blank unit, or a position the reader can't read)."""
    from backend.maintenance.rbd_tree_plan import maintenance_for
    from backend.services import running_clock

    if not position_id or not (running_clock.is_running_hours(unit) or running_clock.is_use(unit)):
        return {}
    m = maintenance_for(ctx)
    if m is None:
        return {}
    try:
        m._any(str(position_id))
    except Exception:  # noqa: BLE001 - not a position the reader has: stand-alone
        return {}
    clock = running_clock.for_position(m, str(position_id))
    rate = clock.per_day(unit)
    return {"clock": clock.to_dict(), **({"hours_per_day": rate[0]} if rate else {})}


@router.post("/optimal-replacement")
def optimal_replacement_endpoint(
    distribution_id: str = Body(...),
    params: list = Body(default=[]),
    planned_cost: float | None = Body(default=None),
    unplanned_cost: float | None = Body(default=None),
    unit: str | None = Body(default=None),
    extras: dict | None = Body(default=None),
    use_per_year: float | None = Body(default=None),
    units: float | None = Body(default=None),
    position_id: str | None = Body(default=None, max_length=200),
    ctx: AccessCtx = Depends(get_access),
) -> JSONResponse:
    """Compute the cost-optimal preventive-replacement interval (and the
    saving a year with ``use_per_year``). With
    ``position_id`` and a model in running hours, ``calendar`` gives the interval in days at
    the position's duty (else running all the time)."""
    try:
        return JSONResponse(
            content=strategy_store.compute("optimal_replacement", {
                "distribution_id": distribution_id, "params": params, "planned_cost": planned_cost,
                "unplanned_cost": unplanned_cost, "unit": unit, "extras": extras, "use_per_year": use_per_year,
                "units": units, **_position_clock(ctx, position_id, unit)})
        )
    except StrategyError as exc:
        return JSONResponse(status_code=422, content={"detail": client_message(exc)})
    except Exception:  # pragma: no cover - defensive
        logger.exception("Optimal replacement failed")
        return JSONResponse(
            status_code=500, content={"detail": "Calculation failed. The error has been logged."}
        )


@router.post("/overhaul-replace")
def overhaul_replace_endpoint(
    body: dict = Body(...),
    session=Depends(get_session),
    ctx: AccessCtx = Depends(get_access),
) -> JSONResponse:
    """Overhaul every X, replace after N overhauls: the cheapest rule for a repairable unit,
    against running to failure, overhauling only and replacing only (RePyability, exact: free).
    JSON: ``recurrent_model_id`` (a saved repairable model; its unit is used) or ``form`` +
    ``params``, with ``cost_repair``, ``cost_overhaul``, ``cost_replace``, ``overhaul_restores``
    (% of its age an overhaul takes off), optional downtimes (hours) with ``downtime_cost``, and
    ``max_overhauls``. Read-only: nothing is saved."""
    from backend.fitting import FitError
    from backend.schema import RecurrentModelDoc
    from backend.services import overhaul_replace
    from backend.services import recurrent as recurrent_service

    inputs = dict(body or {})
    live = None
    try:
        mid = inputs.get("recurrent_model_id")
        if mid:
            doc, _ = access_service.fetch_readable(session, "recurrent_models", RecurrentModelDoc, str(mid), ctx)
            if doc is None or doc.id in ctx.hidden:
                return JSONResponse(status_code=404, content={"detail": "Repairable model not found."})
            live = recurrent_service.get_live_model(session, doc.id, [*ctx.read_owners, doc.owner_id])
            inputs["unit"] = (doc.results or {}).get("unit") or inputs.get("unit") or ""
        return JSONResponse(content=overhaul_replace.from_inputs(inputs, live))
    except recurrent_service.ModelNotFound:
        return JSONResponse(status_code=404, content={"detail": "Repairable model not found."})
    except (FitError, StrategyError, ValueError, TypeError) as exc:
        return JSONResponse(status_code=422, content={"detail": client_message(exc)})
    except Exception:  # pragma: no cover - defensive
        logger.exception("Overhaul and replace failed")
        return JSONResponse(
            status_code=500, content={"detail": "Calculation failed. The error has been logged."}
        )


@router.post("/calendar-replacement")
def calendar_replacement_endpoint(
    distribution_id: str = Body(...),
    params: list = Body(default=[]),
    extras: dict | None = Body(default=None),
    unit: str | None = Body(default=None),
    today: str | None = Body(default=None, max_length=10),
    opportunities: list = Body(default=[]),
    failure_cost: float | None = Body(default=None),
    anytime_cost: float | None = Body(default=None),
    max_age: float | None = Body(default=None),
    method: str = Body(default="dp", max_length=20),
    mc_samples: int | None = Body(default=None),
    seed: int | None = Body(default=None),
    horizon_months: int | None = Body(default=None),
    position_id: str | None = Body(default=None, max_length=200),
    session=Depends(get_session),
    ctx: AccessCtx = Depends(get_access),
) -> JSONResponse:
    """The long-run best replacement rule over a calendar of shuts (today is
    time 0). The exact methods (``dp``, ``integration``) answer here and are
    free; ``sampling`` is Pro and runs as a job (202 with ``job`` to poll at
    ``/api/rbd-jobs/{id}``) when the compute queue is configured."""
    inputs = {
        "distribution_id": distribution_id, "params": params, "extras": extras, "unit": unit, "today": today,
        "opportunities": opportunities, "failure_cost": failure_cost, "anytime_cost": anytime_cost,
        "max_age": max_age, "method": method, "mc_samples": mc_samples, "seed": seed,
        "horizon_months": horizon_months,
    }
    user = ctx.user
    try:
        # Run from a position: its running hours meet the shut dates at its duty (running_clock).
        inputs.update(_position_clock(ctx, position_id, unit))
        code, payload = strategy_calendar_api.run(
            session, user, inputs, entitled=billing_service.premium_compute_allowed(session, user))
        return JSONResponse(status_code=code, content=payload)
    except (StrategyError, AnalysisError) as exc:
        return JSONResponse(status_code=422, content={"detail": client_message(exc)})
    except Exception:  # pragma: no cover - defensive
        logger.exception("Calendar replacement failed")
        return JSONResponse(
            status_code=500, content={"detail": "Calculation failed. The error has been logged."}
        )


@router.post("/calendar-next")
def calendar_next_endpoint(
    distribution_id: str = Body(...),
    params: list = Body(default=[]),
    extras: dict | None = Body(default=None),
    unit: str | None = Body(default=None),
    today: str | None = Body(default=None, max_length=10),
    opportunities: list = Body(default=[]),
    failure_cost: float | None = Body(default=None),
    anytime_cost: float | None = Body(default=None),
    max_age: float | None = Body(default=None),
    age: float | None = Body(default=None),
    now_cost: float | None = Body(default=None),
    position_id: str | None = Body(default=None, max_length=200),
    ctx: AccessCtx = Depends(get_access),
) -> JSONResponse:
    """One unit in service on the calendar: replace it now, at the next shut,
    between shuts, or run it to failure, with break-even ages (exact, free). With
    ``position_id``, a model in running hours meets the dates at its duty."""
    if age is None:
        return JSONResponse(status_code=422, content={"detail": "Enter the unit's age."})
    try:
        return JSONResponse(content=strategy_calendar.calendar_next(
            distribution_id, params, age=age, now_cost=now_cost, extras=extras, unit=unit, today=today,
            opportunities=opportunities, failure_cost=failure_cost, anytime_cost=anytime_cost,
            max_age=max_age, **_position_clock(ctx, position_id, unit),
        ))
    except StrategyError as exc:
        return JSONResponse(status_code=422, content={"detail": client_message(exc)})
    except Exception:  # pragma: no cover - defensive
        logger.exception("Calendar next replacement failed")
        return JSONResponse(
            status_code=500, content={"detail": "Calculation failed. The error has been logged."}
        )


def _saved_bounds(session, model_id, ctx: AccessCtx) -> dict | None:
    """A saved model's B10 and median lower bounds (90% one-sided), or None
    when it can't be read or bounded (the comparison stands without them)."""
    from backend.services import models as models_service

    try:
        out = models_service.life(session, str(model_id), {"reliability": [0.9, 0.5], "confidence": 0.9},
                                  ctx.read_owners)
    except Exception:  # noqa: BLE001 - the comparison doesn't depend on its bounds
        return None
    pts = out.get("points") or []
    if len(pts) < 2:
        return None
    return {"b10": pts[0].get("lower"), "median": pts[1].get("lower"), "note": out.get("bounds_note")}


@router.post("/compare-two")
def compare_two_endpoint(
    a: dict = Body(...),
    b: dict = Body(...),
    unit: str | None = Body(default=None),
    user: dict = Depends(get_current_user),
    session=Depends(get_session),
    ctx: AccessCtx = Depends(get_access),
) -> JSONResponse:
    """Compare two models' reliability (which item is more reliable). A side
    given as a saved model (``model_id``) also gets its B10 and median's 90%
    one-sided lower bounds from that model's own fit."""
    try:
        result = strategy_service.compare_two(a, b, unit=unit)
        bounds = {k: _saved_bounds(session, side.get("model_id"), ctx) for k, side in (("a", a), ("b", b))
                  if isinstance(side, dict) and side.get("model_id")}
        # A side converted to the comparison's unit: its saved fit's bounds are converted too.
        for k, factor in (result.get("factors") or {}).items():
            if bounds.get(k):
                bounds[k] = {**bounds[k], **{m: (bounds[k][m] * factor if bounds[k].get(m) is not None else None)
                                             for m in ("b10", "median")}}
        if any(bounds.values()):
            result = strategy_service.with_life_bounds(result, bounds)
        return JSONResponse(content=result)
    except StrategyError as exc:
        return JSONResponse(status_code=422, content={"detail": client_message(exc)})
    except Exception:  # pragma: no cover - defensive
        logger.exception("Two-model comparison failed")
        return JSONResponse(
            status_code=500, content={"detail": "Comparison failed. The error has been logged."}
        )


@router.post("/failure-finding")
def failure_finding_endpoint(
    distribution_id: str = Body(...),
    params: list = Body(default=[]),
    target_availability: float = Body(...),
    unit: str | None = Body(default=None),
    extras: dict | None = Body(default=None),
    test_duration: float | None = Body(default=None),
    test_cost: float | None = Body(default=None),
    renewed_at_test: bool = Body(default=True),
    position_id: str | None = Body(default=None, max_length=200),
    ctx: AccessCtx = Depends(get_access),
) -> JSONResponse:
    """Failure-finding interval for a hidden failure (protective device),
    from the model's curve, with its 90% one-sided bound. With ``position_id`` and a model
    in running hours, ``calendar`` gives the interval in days at the position's duty."""
    try:
        return JSONResponse(
            content=strategy_store.compute("failure_finding", {
                "distribution_id": distribution_id, "params": params, "target_availability": target_availability,
                "unit": unit, "extras": extras, "test_duration": test_duration, "test_cost": test_cost,
                "renewed_at_test": renewed_at_test, **_position_clock(ctx, position_id, unit)})
        )
    except StrategyError as exc:
        return JSONResponse(status_code=422, content={"detail": client_message(exc)})
    except Exception:  # pragma: no cover - defensive
        logger.exception("Failure-finding calculation failed")
        return JSONResponse(
            status_code=500, content={"detail": "Calculation failed. The error has been logged."}
        )


@router.post("/demonstration-test")
def demonstration_test_endpoint(
    method: str = Body(default="attribute"),
    reliability: float | None = Body(default=None),
    confidence: float | None = Body(default=0.90),
    mission_time: float | None = Body(default=None),
    failures: float | None = Body(default=0),
    test_multiple: float | None = Body(default=1.0),
    shape: float | None = Body(default=None),
    units: float | None = Body(default=None),
    mtbf: float | None = Body(default=None),
    design_reliability: float | None = Body(default=None),
    design_mtbf: float | None = Body(default=None),
    unit: str | None = Body(default=None),
    producer_risk: float | None = Body(default=None),
    b_life: float | None = Body(default=None),
    shape_interval: list[float] | None = Body(default=None),
    shape_model: str | None = Body(default=None, max_length=200),
    failure_terminated: bool | None = Body(default=None),
    user: dict = Depends(get_current_user),
) -> JSONResponse:
    """Plan a reliability demonstration test: units, test time and allowed failures
    (with ``producer_risk`` and the good design, a plan that keeps both risks;
    with ``b_life``, for a B-life requirement; with ``shape_interval``, how far
    the plan moves across β's interval — #295)."""
    try:
        return JSONResponse(
            content=strategy_service.demonstration_test(
                reliability=reliability, confidence=confidence, mission_time=mission_time,
                failures=failures, test_multiple=test_multiple, shape=shape, units=units,
                method=method, mtbf=mtbf, design_reliability=design_reliability,
                design_mtbf=design_mtbf, unit=unit, producer_risk=producer_risk,
                b_life=b_life, shape_interval=shape_interval, shape_model=shape_model,
                failure_terminated=failure_terminated,
            )
        )
    except StrategyError as exc:
        return JSONResponse(status_code=422, content={"detail": client_message(exc)})
    except Exception:  # pragma: no cover - defensive
        logger.exception("Demonstration test planning failed")
        return JSONResponse(
            status_code=500, content={"detail": "Calculation failed. The error has been logged."}
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
        # A strategy added for a model on a position (the Explorer's Modelling tab): the model's row on that
        # position (its link id), so the row shows a Strategy item under it once one is saved.
        **({"position_link_id": str((doc.inputs or {})["position_link_id"])}
           if (doc.inputs or {}).get("position_link_id") else {}),
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
        if kind in ("optimal_replacement", "failure_finding", "calendar_replacement") and \
                (inputs or {}).get("position_id") and "clock" not in (inputs or {}):
            # Saved from a position: the duty it was run at is kept with it, so it recomputes the same.
            inputs = {**inputs, **_position_clock(ctx, inputs["position_id"], inputs.get("unit"))}
        doc = strategy_store.save_analysis(session, name, kind, inputs, ctx.write_owner)
        access_service.stamp_editor(session, "strategy_analyses", doc.id, ctx)
    except StrategyError as exc:
        return JSONResponse(status_code=422, content={"detail": client_message(exc)})
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
