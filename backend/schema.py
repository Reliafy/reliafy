"""Document models for saved datasets, models, and RBDs (stored in MongoDB).

A *Dataset* is an immutable, content-addressed copy of an uploaded CSV (the raw
bytes are stored inline). A *Model* is a saved fit: a small recipe (which
dataset + how to fit it) plus a cached copy of the computed results so a reopen
is instant. ``owner_id`` is present but unused in Phase 1 (single-user); it lets
us add auth later without changing the core shape.

These are plain pydantic models — the persistence layer (:mod:`backend.db`)
maps them to/from MongoDB documents, using ``id`` as the document ``_id``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field, model_validator


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Dataset(BaseModel):
    id: str
    name: str
    owner_id: Optional[str] = None
    updated_by: Optional[dict] = None
    created_at: datetime = Field(default_factory=_now)
    checksum: str = ""  # sha256 of the file (content-addressed)
    n_rows: int = 0
    columns: list = Field(default_factory=list)
    data: bytes = b""  # raw CSV bytes (excluded from API responses)
    notes: Optional[str] = None  # free-text annotation (set over MCP: update_dataset)


class Model(BaseModel):
    id: str
    name: str
    owner_id: Optional[str] = None
    updated_by: Optional[dict] = None
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)
    dataset_id: str = ""

    kind: str = "distribution"  # 'distribution' | 'regression'
    distribution_id: str = ""
    spec: dict = Field(default_factory=dict)
    results: dict = Field(default_factory=dict)
    # Serialised live model (surpyval to_dict + grid/fields) so the calculator /
    # confidence bounds rehydrate it directly instead of re-fitting on demand.
    # None for older docs or per-demand models — those fall back to refit.
    serialized: Optional[dict] = None

    surpyval_version: Optional[str] = None
    status: str = "ready"  # 'ready' | 'error'
    error: Optional[str] = None


class Rbd(BaseModel):
    """A saved reliability block diagram (the React Flow graph: nodes+edges)."""

    id: str
    name: str
    owner_id: Optional[str] = None
    updated_by: Optional[dict] = None
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)
    graph: dict = Field(default_factory=dict)


class DegradationModelDoc(BaseModel):
    """A saved degradation model: the fit recipe (dataset + column mapping +
    threshold + path form) plus cached results. Like ``Model``, the live
    SurPyval object can't be pickled, so predictions re-fit on demand."""

    id: str
    name: str
    owner_id: Optional[str] = None
    updated_by: Optional[dict] = None
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)
    dataset_id: str = ""
    spec: dict = Field(default_factory=dict)
    results: dict = Field(default_factory=dict)
    serialized: Optional[dict] = None  # persisted fit; rehydrated w/o refit
    surpyval_version: Optional[str] = None
    status: str = "ready"
    error: Optional[str] = None


class RecurrentModelDoc(BaseModel):
    """A saved recurrent-event (repairable-system) model: the fit recipe
    (dataset + column mapping + model form) plus cached results. Like the other
    fits, the live SurPyval object can't be pickled, so it re-fits on demand."""

    id: str
    name: str
    owner_id: Optional[str] = None
    updated_by: Optional[dict] = None
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)
    dataset_id: str = ""
    spec: dict = Field(default_factory=dict)
    results: dict = Field(default_factory=dict)
    serialized: Optional[dict] = None  # persisted fit; rehydrated w/o refit
    surpyval_version: Optional[str] = None
    status: str = "ready"
    error: Optional[str] = None


class AltModelDoc(BaseModel):
    """A saved Accelerated Life Testing model: the fit recipe (dataset + time /
    stress column mapping + distribution + life-stress relationship) plus cached
    results. The live SurPyval object is serialised for rehydration without a
    re-fit; ``spec`` holds the mapping, stress columns/labels, and model ids."""

    id: str
    name: str
    owner_id: Optional[str] = None
    updated_by: Optional[dict] = None
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)
    dataset_id: str = ""
    spec: dict = Field(default_factory=dict)
    results: dict = Field(default_factory=dict)
    serialized: Optional[dict] = None  # persisted fit; rehydrated w/o refit
    surpyval_version: Optional[str] = None
    status: str = "ready"
    error: Optional[str] = None


class AgentSessionDoc(BaseModel):
    """A saved Reliability Agent conversation. The transcript itself lives on the
    Managed Agents platform (keyed by ``id`` = the platform session id); this row
    just links the session to its owner so the user can list, reopen, and resume
    their past runs."""

    id: str  # the platform session id (sesn_…)
    owner_id: str
    title: str = "Untitled analysis"
    turns: int = 0
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class RcmStudy(BaseModel):
    """A Reliability Centred Maintenance study: an embedded worksheet tree
    (Function → Functional Failure → Failure Mode) where each failure mode can
    carry a maintenance decision linked to the analysis that justifies it.

    The tree lives inside the study document: a study is one cohesive editing
    unit of a few dozen nodes, always read and written whole, so a single
    document gives atomic updates for free. Evidence statuses are computed at
    read time from the linked artifacts — never stored.
    """

    id: str
    name: str
    system: str = ""
    description: str = ""
    owner_id: Optional[str] = None
    updated_by: Optional[dict] = None
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)
    functions: list = Field(default_factory=list)


class StrategyAnalysis(BaseModel):
    """A saved strategy calculation (optimal replacement, two-model comparison,
    or failure-finding interval): the inputs plus the computed results — the
    persistent evidence an RCM decision can link to."""

    id: str
    name: str
    owner_id: Optional[str] = None
    updated_by: Optional[dict] = None
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)
    kind: str = "optimal_replacement"  # | 'compare_two' | 'failure_finding' | 'demonstration_test'
    inputs: dict = Field(default_factory=dict)
    results: dict = Field(default_factory=dict)


class TrackedItem(BaseModel):
    """An asset monitored against a degradation model: its measurement history
    plus the cached threshold-crossing prediction (recomputed on append)."""

    id: str
    model_id: str
    # The tracked fleet this item belongs to (one model can back many fleets).
    # Legacy items without one are adopted into an auto-created fleet on read.
    fleet_id: Optional[str] = None
    name: str
    owner_id: Optional[str] = None
    updated_by: Optional[dict] = None
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)
    meta: dict = Field(default_factory=dict)
    measurements: list = Field(default_factory=list)  # [{"t": float, "y": float}]
    prediction: Optional[dict] = None


FLEET_MODEL_KINDS = ("life", "regression", "alt", "recurrent")
# The collection each kind's model_id lives in.
FLEET_MODEL_COLLECTIONS = {"life": "models", "regression": "models",
                           "alt": "alt_models", "recurrent": "recurrent_models"}


def fleet_model_kind(doc: dict) -> str:
    """A fleet's model kind from its raw document, reading the field names
    either feature branch saved before they were unified: ``model_kind``
    ("life" / "recurrent", #235) and ``model_source`` (None / "alt", #234)."""
    kind = doc.get("model_kind")
    if kind in FLEET_MODEL_KINDS and kind != "life":
        return kind
    if doc.get("model_source") == "alt":
        return "alt"
    return "life"


class Fleet(BaseModel):
    """A fleet failure forecast: in-service items running against one saved
    life model. Items and settings live in the document; the forecast itself
    (expected failures over the horizon) is computed at read time from the
    linked model — never stored — so it always reflects the current fit.
    """

    id: str
    name: str
    owner_id: Optional[str] = None
    updated_by: Optional[dict] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    model_id: str
    # What model_id is, and so how the fleet is forecast — one field:
    #   "life"       a plain life distribution (``models``): first failures
    #                or failures with replacement;
    #   "regression" a regression life model (``models``, #234): first
    #                failures, each item at its own covariates;
    #   "alt"        an ALT model (``alt_models``, #234): first failures,
    #                each item at its own stress;
    #   "recurrent"  a recurrent-event model (``recurrent_models``, #235):
    #                each item a repairable system, every failure counted.
    # Fleets saved before the field was unified may carry ``model_source:
    # "alt"`` instead; ``fleet_model_kind`` reads either.
    model_kind: str = "life"
    # {periods, period_label, default_rate, method: "renewals"|"single",
    #  rate_source: "manual"|"estimated", + #234: covariates {name: value}
    #  (fleet defaults for a regression/ALT model), warranty_use,
    #  warranty_periods}
    settings: dict = Field(default_factory=dict)
    # [{id, name, current_use, rate|null, notes?, + rate-estimator state from
    #  API readings: last_reading_use/at, latest_read_at, estimated_rate(_n),
    #  + next_service_at? (recurrent, #235), + #234: covariates {name: value}
    #  overrides, service_periods}]
    items: list = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _unify_model_kind(cls, data):
        if isinstance(data, dict):
            kind = fleet_model_kind(data)
            if data.get("model_kind") != kind:
                data = {**data, "model_kind": kind}
        return data


class TrackedFleet(BaseModel):
    """A named group of tracked items monitored against one degradation model.

    One model can back any number of fleets (e.g. "Sydney trucks" and
    "Brisbane trucks" both tracked against the same brake-wear model).
    """

    id: str
    name: str
    owner_id: Optional[str] = None
    updated_by: Optional[dict] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    model_id: str
