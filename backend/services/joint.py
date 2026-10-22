"""Condition monitoring models (joint models of readings and failures): saving,
fitting as a compute job, and the live model.

A joint model is a saved model (``models``, ``kind: "joint"``) fitted to two
datasets: the lifetimes (one row per unit) and the readings (one row per
reading). It stores its recipe (``spec``), what the results page shows
(``results``) and ``serialized``: SurPyval's ``JointModel.to_dict()`` with
the running units' inputs (age, covariates, readings), so the model and any
running unit's prediction rehydrate without a refit
(:func:`models_service.get_live_model` → :func:`live_entry`).

The fit is heavy (8-40 s for a real fleet), so with the compute queue
configured it runs as a job on the compute service (``joint_fit``); the
model is saved when the job finishes (:func:`on_job_done`). Without a queue
(self-hosted, dev, tests) it runs in-process.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from collections import OrderedDict
from typing import Any, Optional

import surpyval

from backend import joint
from backend.db import to_doc
from backend.fitting import FitError
from backend.schema import Model
from backend.services import compute_core, compute_queue
from backend.services import datasets as datasets_service
from backend.services import rbd_jobs as rbd_jobs_service

logger = logging.getLogger(__name__)

KIND = "joint"
PRO_PAYLOAD = {
    "detail": ("Condition monitoring models fit two models at once on the calculation service, so fitting "
               "one is part of Pro. Opening a saved one is free."),
    "code": "pro_required",
    "upgrade": True,
}

_LIVE: "OrderedDict[str, tuple[str, Any]]" = OrderedDict()
_LIVE_MAX = 32


class ModelNotFound(KeyError):
    """A joint model id that is unknown or not visible."""


# ---- The fit's inputs -------------------------------------------------------------


def _dataset(db, dataset_id, owners, what: str):
    if not dataset_id or not isinstance(dataset_id, str):
        raise FitError(f"Pick the {what} dataset.")
    ds = datasets_service.get_dataset(db, dataset_id, owner_id=owners)
    if ds is None:
        raise FitError(f"The {what} dataset wasn't found.")
    return ds


def spec_from(body: dict) -> dict:
    """The recipe kept on the model, from a request body."""
    body = body or {}
    path = body.get("path_model") or joint.DEFAULT_PATH
    if path not in joint.PATHS:
        raise FitError(f"Unknown path model {path!r}: use one of {', '.join(joint.PATHS)}.")
    covariates = [str(c) for c in (body.get("covariates") or []) if c]
    return {
        "lifetimes_dataset_id": body.get("lifetimes_dataset_id"),
        "readings_dataset_id": body.get("readings_dataset_id"),
        "mapping": {k: v for k, v in (body.get("mapping") or {}).items() if k in joint.LIFE_KEYS and v},
        "readings_mapping": {k: v for k, v in (body.get("readings_mapping") or {}).items()
                             if k in joint.READING_KEYS and v},
        "covariates": covariates,
        "hazard_covariates": body.get("hazard_covariates"),
        "path_covariates": body.get("path_covariates"),
        "c_invert": bool(body.get("c_invert")),
        "path_model": path,
        "unit": (body.get("unit") or "").strip(),
        "marker": (body.get("marker") or "").strip() or (body.get("readings_mapping") or {}).get("value") or "",
        "marker_unit": (body.get("marker_unit") or "").strip(),
    }


def _outcome_rows(table, mapping: dict):
    """One table holding both: its rows with an outcome (the censoring flag
    filled in) are the lifetimes, one per unit; every row is a reading."""
    c = mapping.get("c")
    if not c or c not in table.columns:
        raise FitError("Pick the censoring column: the rows where it is filled in are each unit's outcome.")
    return table[table[c].notna()]


def items_for(db, spec: dict, owners) -> tuple[list, dict]:
    """The units of a spec's datasets, grouped (:func:`joint.build_items`)."""
    life_ds = _dataset(db, spec.get("lifetimes_dataset_id"), owners, "lifetimes")
    read_ds = _dataset(db, spec.get("readings_dataset_id"), owners, "readings")
    life = datasets_service.load_dataframe(life_ds)
    readings = datasets_service.load_dataframe(read_ds)
    if life_ds.id == read_ds.id:
        life = _outcome_rows(life, spec.get("mapping") or {})
    return joint.build_items(life, readings, spec.get("mapping") or {}, spec.get("readings_mapping") or {},
                             spec.get("covariates") or [], bool(spec.get("c_invert")))


def check(db, body: dict, owners) -> dict:
    """What a fit would take, before running it: counts and notes."""
    spec = spec_from(body)
    _, summary = items_for(db, spec, owners)
    return {"ok": True, **summary}


def _request(db, spec: dict, owners) -> dict:
    items, summary = items_for(db, spec, owners)
    request = joint.fit_request(
        items, spec["covariates"], path_model=spec["path_model"], hazard_covariates=spec.get("hazard_covariates"),
        path_covariates=spec.get("path_covariates"), unit=spec.get("unit") or "", marker=spec.get("marker") or "",
        marker_unit=spec.get("marker_unit") or "", summary=summary)
    if compute_queue.configured():
        size = len(json.dumps(request, separators=(",", ":"), default=float))
        if size > compute_queue.MAX_BODY_BYTES - 20_000:
            raise FitError("These tables are too large to send to the calculation service in one go: fit fewer "
                           "units, or thin the readings (every other one, say).")
    return request


# ---- Fitting -----------------------------------------------------------------------


def start_fit(db, *, uid: str, owners, body: dict, save: bool = True,
              owner_id: Optional[str] = None) -> tuple[int, dict]:
    """Fit a joint model the caller may fit. ``save`` keeps it as a saved
    model (``body["name"]``) under ``owner_id``. Returns ``(status,
    payload)``: 200 with ``{"model_id"?, "results"}`` (in-process), 202 with
    a ``job`` to poll (``/api/rbd-jobs/{job_id}``, whose result gives the
    same), 503 when the queue can't take it. Raises :class:`FitError`."""
    spec = spec_from(body)
    name = " ".join(str((body or {}).get("name") or "").split())[:200]
    if save and not name:
        raise FitError("Give the model a name.")
    request = _request(db, spec, owners)
    pending = {"save": bool(save), "name": name, "owner_id": owner_id or uid, "spec": spec}
    if not compute_queue.configured():
        try:
            out = compute_core.run_joint_fit(request)
        except Exception as exc:
            from backend.services.rbd_analysis import AnalysisError

            if isinstance(exc, AnalysisError):
                raise FitError(str(exc)) from exc
            raise
        out = compute_core.to_wire(out)
        model_id = _save(db, pending, out).id if save else None
        return 200, {"model_id": model_id, "results": out["results"]}
    key = "joint_fit|" + hashlib.sha256(json.dumps(
        {"r": request, "p": pending}, sort_keys=True, default=float).encode()).hexdigest()
    existing = rbd_jobs_service.find_reusable(db, uid, key, False, include_done=False)
    if existing is not None:
        return 202, _accepted(db, existing)
    job = rbd_jobs_service.create(db, uid=uid, kind=rbd_jobs_service.KIND_JOINT_FIT, request=request,
                                  cache_key=key, rbd_id=None, quick=False, store=False,
                                  extra={"pending": pending})
    try:
        compute_queue.enqueue(job["_id"], rbd_jobs_service.KIND_JOINT_FIT, request)
    except compute_queue.QueueError as exc:
        rbd_jobs_service.finish(db, job["_id"], "failed", error=str(exc) or rbd_jobs_service.QUEUE_UNAVAILABLE)
        return 503, {"detail": rbd_jobs_service.QUEUE_UNAVAILABLE, "code": "compute_unavailable"}
    return 202, _accepted(db, job)


def _accepted(db, job: dict) -> dict:
    return {
        "kind": rbd_jobs_service.KIND_JOINT_FIT,
        "status": job.get("status"),
        "job": {"job_id": job["_id"], "status": job["status"],
                "queue_position": rbd_jobs_service.queue_position(db, job),
                "kind": rbd_jobs_service.KIND_JOINT_FIT},
    }


def _save(db, pending: dict, out: dict) -> Model:
    spec = dict(pending.get("spec") or {})
    model = Model(
        id=uuid.uuid4().hex,
        name=pending.get("name") or "Condition monitoring",
        owner_id=pending.get("owner_id"),
        dataset_id=spec.get("lifetimes_dataset_id") or "",
        kind=KIND,
        distribution_id=(out.get("results") or {}).get("distribution_id") or "joint",
        spec=spec,
        results=out.get("results") or {},
        serialized={"format": "surpyval_joint", "model": out.get("model"), "units": out.get("units") or {}},
        surpyval_version=getattr(surpyval, "__version__", None),
        status="ready",
    )
    db.models.insert_one(to_doc(model))
    return model


def on_job_done(db, job: dict, result: dict) -> None:
    """Save a finished fit job's model (once: :func:`rbd_jobs.finish` runs
    this only for the call that finished the job)."""
    pending = job.get("pending") or {}
    if not pending.get("save"):
        return
    try:
        model = _save(db, pending, result or {})
    except Exception:  # noqa: BLE001 - the job's result still stands
        logger.exception("Couldn't save the joint model of job %s", job.get("_id"))
        return
    db.rbd_jobs.update_one({"_id": job["_id"]}, {"$set": {"model_id": model.id}})


def job_result(job: dict) -> dict:
    """A finished fit job as the app and MCP see it: the saved model's id
    (when it was saved) and the results."""
    result = job.get("result") or {}
    return {"model_id": job.get("model_id"), "results": result.get("results") or {}}


# ---- The saved model --------------------------------------------------------------


def get(db, model_id: str, owners) -> Model:
    from backend.services import models as models_service

    model = models_service.get_model(db, model_id, owners)
    if model is None or model.kind != KIND:
        raise ModelNotFound(model_id)
    return model


def list_models(db, owners, hidden=frozenset(), shared=frozenset()) -> list[Model]:
    from backend.services import models as models_service

    return [m for m in models_service.list_models(db, owners, hidden, shared=shared, kinds=(KIND,))]


def _fingerprint(model: Model) -> str:
    blob = json.dumps((model.serialized or {}).get("model"), sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


def live(model: Model):
    """The live ``JointModel`` of a saved one (cached by id and fit)."""
    if model.kind != KIND or not (model.serialized or {}).get("model"):
        raise FitError("This model has no saved joint fit.")
    fp = _fingerprint(model)
    hit = _LIVE.get(model.id)
    if hit and hit[0] == fp:
        _LIVE.move_to_end(model.id)
        return hit[1]
    try:
        jm = joint.restore(model.serialized["model"])
    except Exception as exc:  # noqa: BLE001 - a saved fit SurPyval can't read back
        raise FitError(f"This model's saved fit couldn't be read back ({exc}). Fit it again.") from exc
    _LIVE[model.id] = (fp, jm)
    while len(_LIVE) > _LIVE_MAX:
        _LIVE.popitem(last=False)
    return jm


def live_entry(model: Model) -> dict:
    """What :func:`models_service.get_live_model` gives for a joint model:
    the live model, its running units' inputs and its covariates."""
    return {
        "kind": KIND,
        "model": live(model),
        "units": (model.serialized or {}).get("units") or {},
        "covariates": list((model.results or {}).get("covariates") or []),
        "unit": (model.results or {}).get("unit") or "",
        "name": model.name,
    }


def unit_inputs(model: Model, unit_id: str) -> dict:
    units = (model.serialized or {}).get("units") or {}
    inp = units.get(str(unit_id))
    if inp is None:
        raise FitError(f"Unit {unit_id!r} isn't one of this model's running units.")
    return inp


def unit_view(model: Model, unit_id: str) -> dict:
    """A fitted running unit's updating prediction (``joint.unit_view``)."""
    inp = unit_inputs(model, unit_id)
    out = joint.unit_view(live(model), inp.get("covariates"), inp.get("markers"), inp.get("age"),
                          (model.results or {}).get("unit") or "", (model.results or {}).get("horizons"))
    return {"unit_id": str(unit_id), "source": "fitted", **out}


def predict(model: Model, body: dict) -> dict:
    """The prediction of a unit given by its values: ``{"age", "markers":
    [[age, value], ...], "covariates": {name: value}}``."""
    body = body or {}
    age = body.get("age")
    try:
        age = None if age is None or age == "" else float(age)
    except (TypeError, ValueError) as exc:
        raise FitError("The unit's age must be a number (since new).") from exc
    out = joint.unit_view(live(model), body.get("covariates") or {}, body.get("markers") or [], age,
                          (model.results or {}).get("unit") or "", (model.results or {}).get("horizons"))
    return {"unit_id": None, "source": "entered", **out}


def export_python(db, model: Model, owners) -> tuple[str, str]:
    """``(filename, source)``: a script that refits the model with
    ``fit_from_df`` from its datasets (embedded)."""
    from backend.services import rbd_export

    spec = model.spec or {}
    try:
        items, _ = items_for(db, spec, owners)
    except FitError as exc:
        raise FitError(f"The data this model was fitted to can't be read any more: {exc}") from exc
    h = ((model.results or {}).get("horizons") or {}).get("values") or [None, None]
    versions = {"surpyval": getattr(surpyval, "__version__", None)}
    source = joint.python_script(
        model.name, items, spec.get("covariates") or [], path_model=spec.get("path_model") or joint.DEFAULT_PATH,
        hazard_covariates=spec.get("hazard_covariates"), path_covariates=spec.get("path_covariates"),
        unit=(model.results or {}).get("unit") or spec.get("unit") or "", marker=spec.get("marker") or "",
        horizon=h[1] if len(h) > 1 else None, versions=versions)
    return f"{rbd_export.slugify(model.name)}.py", source


def summary(model: Model) -> dict:
    """A list row's fields."""
    r = model.results or {}
    return {
        "id": model.id,
        "name": model.name,
        "kind": KIND,
        "distribution": r.get("distribution"),
        "path_model": r.get("path_label"),
        "marker": r.get("marker"),
        "unit": r.get("unit") or "",
        "n_items": r.get("n_items"),
        "n_events": r.get("n_events"),
        "n_running": r.get("n_running"),
        "fit_ok": r.get("fit_ok"),
        "created_at": model.created_at.isoformat(),
    }


def running_units(model: Model) -> list[dict]:
    """The running units an RBD block can be (from the risk table, highest
    risk first, then any not listed)."""
    r = model.results or {}
    rows = r.get("risk") or []
    listed = [{"id": u["id"], "age": u.get("age"), "covariates": u.get("covariates") or {},
               "risk": u.get("risk")} for u in rows]
    seen = {u["id"] for u in listed}
    for uid, inp in ((model.serialized or {}).get("units") or {}).items():
        if uid not in seen:
            listed.append({"id": uid, "age": inp.get("age"), "covariates": inp.get("covariates") or {},
                           "risk": None})
    return listed

