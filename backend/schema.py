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

from pydantic import BaseModel, Field


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
    surpyval_version: Optional[str] = None
    status: str = "ready"
    error: Optional[str] = None


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
    kind: str = "optimal_replacement"  # | 'compare_two' | 'failure_finding'
    inputs: dict = Field(default_factory=dict)
    results: dict = Field(default_factory=dict)


class TrackedItem(BaseModel):
    """An asset monitored against a degradation model: its measurement history
    plus the cached threshold-crossing prediction (recomputed on append)."""

    id: str
    model_id: str
    name: str
    owner_id: Optional[str] = None
    updated_by: Optional[dict] = None
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)
    meta: dict = Field(default_factory=dict)
    measurements: list = Field(default_factory=list)  # [{"t": float, "y": float}]
    prediction: Optional[dict] = None


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
    # {periods, period_label, default_rate, method: "renewals"|"single"}
    settings: dict = Field(default_factory=dict)
    # [{id, name, current_use, rate|null, notes?}]
    items: list = Field(default_factory=list)
