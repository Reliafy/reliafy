"""Persistence for saved reliability block diagrams (RBDs)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from backend.services import access
from backend.db import from_doc, to_doc
from backend.schema import Rbd
from backend.services import models as models_service
from backend.services import rbd_analysis


class RbdNotFound(KeyError):
    """Raised when an RBD id is unknown."""


def save_rbd(db, name: str, graph: dict, owner_id: str, rbd_id: str | None = None) -> Rbd:
    """Create a new RBD or update an existing owned one (when ``rbd_id`` given)."""
    if rbd_id:
        existing = db.rbds.find_one({"_id": rbd_id, "owner_id": owner_id})
        if existing is not None:
            rbd = from_doc(Rbd, existing)
            rbd.name = name
            rbd.graph = graph
            rbd.updated_at = datetime.now(timezone.utc)
            db.rbds.update_one(
                {"_id": rbd_id, "owner_id": owner_id},
                {"$set": {"name": name, "graph": graph, "updated_at": rbd.updated_at}},
            )
            return rbd

    rbd = Rbd(id=uuid.uuid4().hex, name=name, owner_id=owner_id, graph=graph)
    db.rbds.insert_one(to_doc(rbd))
    return rbd


def list_rbds(db, owner_id: str | list[str], hidden=frozenset()) -> list[Rbd]:
    """The owner's RBDs plus the shared samples, minus hidden samples."""
    return [
        from_doc(Rbd, r)
        for r in db.rbds.find(
            {"owner_id": {"$in": access.owner_in(owner_id)}}
        ).sort("created_at", -1)
        if r["_id"] not in hidden
    ]


def get_rbd(db, rbd_id: str, owner_id: str | list[str]) -> Rbd | None:
    """Fetch an RBD by id. Shared sample RBDs are visible to every owner."""
    return from_doc(
        Rbd,
        db.rbds.find_one({"_id": rbd_id, "owner_id": {"$in": access.owner_in(owner_id)}}),
    )


def delete_rbd(db, rbd_id: str, owner_id: str) -> None:
    result = db.rbds.delete_one({"_id": rbd_id, "owner_id": owner_id})
    if result.deleted_count == 0:
        raise RbdNotFound(rbd_id)


def analyze_graph(
    db,
    graph: dict,
    owner_id: str,
    t_max: float | None = None,
    covariates: dict | None = None,
    conditional_age: float | None = None,
) -> dict:
    """Run the RePyability reliability analysis for a graph.

    Sub-system nodes are resolved against the caller's saved RBDs, so a diagram
    can embed previously saved diagrams as nested blocks. Resolution is scoped
    to ``owner_id`` so a graph can't reference another user's RBDs/models.
    ``t_max`` is the upper limit of the time axis. ``covariates`` maps node id ->
    covariate values for proportional-hazards nodes. ``conditional_age``
    conditions the curves on having already survived to that age.
    """

    def resolve_subsystem(sub_id: str) -> dict | None:
        sub = get_rbd(db, sub_id, owner_id)
        return sub.graph if sub is not None else None

    def resolve_model(model_id: str) -> dict | None:
        return models_service.get_live_model(db, model_id, owner_id)

    return rbd_analysis.analyze(
        graph,
        resolve_subsystem=resolve_subsystem,
        t_max=t_max,
        covariates=covariates,
        resolve_model=resolve_model,
        conditional_age=conditional_age,
    )


def analyze_rbd(
    db,
    rbd_id: str,
    owner_id: str,
    t_max: float | None = None,
    covariates: dict | None = None,
    conditional_age: float | None = None,
) -> dict:
    """Load a saved owned RBD and analyse it."""
    rbd = get_rbd(db, rbd_id, owner_id)
    if rbd is None:
        raise RbdNotFound(rbd_id)
    return analyze_graph(
        db,
        rbd.graph or {},
        owner_id,
        t_max=t_max,
        covariates=covariates,
        conditional_age=conditional_age,
    )


def validate_graph(db, graph: dict, owner_id: str) -> dict:
    """Check whether a graph is a valid, analytically solvable RBD."""

    def resolve_subsystem(sub_id: str) -> dict | None:
        sub = get_rbd(db, sub_id, owner_id)
        return sub.graph if sub is not None else None

    return rbd_analysis.validate_graph(graph, resolve_subsystem=resolve_subsystem)


def validate_rbd(db, rbd_id: str, owner_id: str) -> dict:
    """Load a saved owned RBD and validate it."""
    rbd = get_rbd(db, rbd_id, owner_id)
    if rbd is None:
        raise RbdNotFound(rbd_id)
    return validate_graph(db, rbd.graph or {}, owner_id)
