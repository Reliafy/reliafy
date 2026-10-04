"""Persistence for saved reliability block diagrams (RBDs)."""

from __future__ import annotations

import hashlib
import json
import threading
import uuid
from collections import OrderedDict
from datetime import datetime, timezone

from backend.services import access
from backend.db import from_doc, to_doc
from backend.schema import Rbd
from backend.services import models as models_service
from backend.services import rbd_analysis



def _list_query(owner_id, shared=frozenset()):
    """Owner-scoped filter, optionally unioned with directly-shared ids."""
    query = {"owner_id": {"$in": access.owner_in(owner_id)}}
    if shared:
        return {"$or": [query, {"_id": {"$in": sorted(shared)}}]}
    return query

class RbdNotFound(KeyError):
    """Raised when an RBD id is unknown."""


def save_rbd(db, name: str, graph: dict, owner_id: str, rbd_id: str | None = None,
             expected_updated_at: str | None = None) -> Rbd:
    """Create a new RBD or update an existing owned one (when ``rbd_id`` given).

    ``expected_updated_at`` (the isoformat the client loaded) makes the update
    optimistic: a mismatch raises :class:`access.EditConflict` instead of
    overwriting another editor's save. A graph over the size or unit-count
    limits raises :class:`backend.services.rbd_graph.GraphError`.
    """
    from backend.services.rbd_graph import check_limits

    check_limits(graph)
    if rbd_id:
        existing = db.rbds.find_one({"_id": rbd_id, "owner_id": owner_id})
        if existing is not None:
            if expected_updated_at and existing.get("updated_at") is not None:
                if not access.timestamps_match(existing["updated_at"], expected_updated_at):
                    raise access.EditConflict()
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


def list_rbds(db, owner_id: str | list[str], hidden=frozenset(), shared=frozenset()) -> list[Rbd]:
    """The owner's RBDs plus the shared samples, minus hidden samples."""
    return [
        from_doc(Rbd, r)
        for r in db.rbds.find(
            _list_query(owner_id, shared)
        ).sort("created_at", -1)
        if r["_id"] not in hidden
    ]


def get_rbd(db, rbd_id: str, owner_id: str | list[str]) -> Rbd | None:
    """Fetch an RBD by id. Shared sample RBDs are visible to every owner."""
    return from_doc(
        Rbd,
        db.rbds.find_one({"_id": rbd_id, "owner_id": {"$in": access.owner_in(owner_id)}}),
    )


def rename_rbd(db, rbd_id: str, name: str, owner_id: str) -> Rbd:
    rbd = get_rbd(db, rbd_id, owner_id)
    if rbd is None or rbd.owner_id != owner_id:
        raise RbdNotFound(rbd_id)
    rbd.name = name
    rbd.updated_at = datetime.now(timezone.utc)
    db.rbds.update_one(
        {"_id": rbd_id, "owner_id": owner_id},
        {"$set": {"name": name, "updated_at": rbd.updated_at}},
    )
    return rbd


def delete_rbd(db, rbd_id: str, owner_id: str) -> None:
    result = db.rbds.delete_one({"_id": rbd_id, "owner_id": owner_id})
    if result.deleted_count == 0:
        raise RbdNotFound(rbd_id)
    # Its outage logs go with it (they mean nothing without the diagram).
    db.outage_logs.delete_many({"rbd_id": rbd_id, "owner_id": owner_id})


# Node-data keys that reference the owner's other saved artifacts by id. A
# public viewer can't open them, so the ids are dropped from the shared graph;
# the analysis (which needs them) runs server-side before the graph goes out.
_REFERENCE_KEYS = ("modelId", "model_id")


def public_graph(graph: dict) -> dict:
    """The graph as shown to an anonymous viewer.

    Life/repair models keep the distribution and parameters stored on the node
    (that is what the canvas renders) but lose their saved-model id; nested
    sub-system blocks keep the name but lose the RBD id. Proportional-hazards
    and non-parametric nodes carry no parameters on the node — the viewer sees
    their name and covariates while the analysis resolves the fit server-side.
    """

    def _model(m):
        if not isinstance(m, dict):
            return m
        return {k: v for k, v in m.items() if k not in _REFERENCE_KEYS}

    nodes = []
    for n in graph.get("nodes") or []:
        data = dict(n.get("data") or {})
        for key in ("model", "repair"):
            if key in data:
                data[key] = _model(data[key])
        if isinstance(data.get("rbd"), dict):
            data["rbd"] = {"name": data["rbd"].get("name")}
        nodes.append({**n, "data": data})
    return {**graph, "nodes": nodes}


def analyze_graph(
    db,
    graph: dict,
    owner_id: str,
    t_max: float | None = None,
    covariates: dict | None = None,
    conditional_age: float | None = None,
    n_simulations: int | None = None,
    at_times=None,
    band: dict | None = None,
    state: dict | None = None,
) -> dict:
    """Run the RePyability reliability analysis for a graph.

    Sub-system nodes are resolved against the caller's saved RBDs, so a diagram
    can embed previously saved diagrams as nested blocks. Resolution is scoped
    to ``owner_id`` so a graph can't reference another user's RBDs/models.
    ``t_max`` is the upper limit of the time axis. ``covariates`` maps node id ->
    covariate values for proportional-hazards nodes. ``conditional_age``
    conditions the curves on having already survived to that age.
    ``at_times`` (non-repairable) adds the system reliability evaluated
    exactly at those times. ``band`` (``{"level": 0.95}``) adds a confidence band from the fitted blocks'
    parameter uncertainty (non-repairable diagrams only). ``state`` (repairable, canonical: see
    :func:`rbd_analysis.parse_current_state`) starts the availability simulation from the blocks'
    current states.
    """

    def resolve_subsystem(sub_id: str) -> dict | None:
        sub = get_rbd(db, sub_id, owner_id)
        return sub.graph if sub is not None else None

    def resolve_model(model_id: str) -> dict | None:
        return models_service.get_live_model(db, model_id, owner_id)

    # A repairable diagram is a distinct modelling choice: it reports
    # availability (uptime) rather than a reliability curve.
    if graph.get("repairable"):
        return rbd_analysis.analyze_availability(
            graph, resolve_model=resolve_model, t_simulation=t_max,
            n_simulations=n_simulations, state=state,
        )

    return rbd_analysis.analyze(
        graph,
        resolve_subsystem=resolve_subsystem,
        t_max=t_max,
        covariates=covariates,
        resolve_model=resolve_model,
        conditional_age=conditional_age,
        at_times=at_times,
        band=band,
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


def export_python(db, name: str, graph: dict, owner_id) -> tuple[str, str]:
    """Render a diagram as a standalone SurPyval + RePyability script.

    Returns ``(filename, source)``. Sub-systems and saved-model references
    resolve exactly as :func:`analyze_graph` resolves them — scoped to
    ``owner_id`` — so the script rebuilds what the viewer's analysis uses.
    Saved models are read from their stored fit summary (no re-fit): the
    block's own stored parameters are what the analysis uses, and the summary
    only fills in what a block lacks.
    """
    from backend.services import rbd_export

    def resolve_subsystem(sub_id: str) -> dict | None:
        sub = get_rbd(db, sub_id, owner_id)
        return sub.graph if sub is not None else None

    def resolve_model(model_id: str) -> dict | None:
        model = models_service.get_model(db, model_id, owner_id)
        if model is None:
            return None
        results = model.results or {}
        return {
            "name": model.name,
            "kind": results.get("kind") or model.kind,
            "distribution_id": results.get("distribution_id") or model.distribution_id,
            "distribution": results.get("distribution"),
            "params": results.get("params") or [],
            "extras": results.get("extras"),
            "unit": results.get("unit"),
        }

    source = rbd_export.to_python(
        graph or {},
        name,
        resolve_model=resolve_model,
        resolve_subsystem=resolve_subsystem,
    )
    return rbd_export.filename(name), source


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


# ---- Saved availability results -------------------------------------------
#
# The Monte-Carlo availability simulation (repairable diagrams) is CPU-heavy
# and a paid feature, so its result is saved on the RBD document as
#
#     availability_cache = {"key", "result", "computed_at", "computed_by"}
#
# ``key`` is a hash of everything the analysis depends on; moving a block on
# the canvas (or any other UI-only change) leaves it unchanged, while editing
# a parameter, a label, or a connection invalidates it. Free users and public
# links only ever *read* a matching entry.

# Node fields React Flow / the builder add for display only. Nodes are reduced
# to id/type/data, so these matter only if they turn up inside ``data``.
_UI_ONLY_KEYS = frozenset({
    "position", "positionAbsolute", "selected", "dragging", "width", "height",
    "className", "measured", "style", "sourcePosition", "targetPosition",
    "deletable", "hidden", "zIndex",
})

AVAILABILITY_CACHE_VERSION = 1


def _strip_ui(value):
    if isinstance(value, dict):
        return {k: _strip_ui(v) for k, v in value.items() if k not in _UI_ONLY_KEYS}
    if isinstance(value, list):
        return [_strip_ui(v) for v in value]
    return value


# Node data that records where values came from (#100: the RCM study a
# block's maintenance was filled from). The filled values themselves are in
# the key; the link isn't, so it never invalidates a saved result.
_PROVENANCE_KEYS = frozenset({"rcm_source"})


def _analysis_data(data: dict) -> dict:
    return _strip_ui({k: v for k, v in data.items() if k not in _PROVENANCE_KEYS})


def canonical_analysis_graph(graph: dict) -> dict:
    """The analysis-relevant part of a graph, in a canonical order."""
    graph = graph or {}
    nodes = [
        {
            "id": n.get("id"),
            "type": n.get("type"),
            "data": _analysis_data(n.get("data") or {}),
        }
        for n in graph.get("nodes") or []
        if isinstance(n, dict)
    ]
    nodes.sort(key=lambda n: str(n["id"]))
    edges = sorted(
        {
            (str(e.get("source")), str(e.get("target")))
            for e in graph.get("edges") or []
            if isinstance(e, dict) and e.get("source") and e.get("target")
        }
    )
    out = {
        "nodes": nodes,
        "edges": [list(e) for e in edges],
        "unit": (graph.get("unit") or "").strip(),
        "repairable": bool(graph.get("repairable")),
        "ccf_groups": graph.get("ccf_groups") or [],
    }
    # Diagram-level costs (#99: system downtime cost, ownership horizon).
    # Block costs and maintenance live in node data, already covered above.
    # Only present when set, so diagrams without costs keep their saved key.
    if graph.get("costs"):
        out["costs"] = graph["costs"]
    # Repair crews, maintenance groups and a safety function (#156, #157):
    # likewise only when set.
    for key in ("repair_crews", "maintenance_groups", "safety_function", "target_sil"):
        if graph.get(key):
            out[key] = graph[key]
    return out


def _t_sim(t_simulation) -> float | None:
    try:
        t = float(t_simulation)
    except (TypeError, ValueError):
        return None
    return t if t > 0 else None


def availability_cache_key(graph: dict, t_simulation: float | None = None) -> str:
    """Deterministic key for an availability result: sha256 of the canonical
    JSON of the analysis graph plus the simulation settings."""
    payload = {
        "v": AVAILABILITY_CACHE_VERSION,
        "graph": canonical_analysis_graph(graph),
        "t_simulation": _t_sim(t_simulation),
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def cached_availability(doc: dict | None, key: str) -> dict | None:
    """The saved result on a raw RBD doc if its key matches, as a response
    payload (``cached: True`` + ``computed_at``); else None."""
    entry = (doc or {}).get("availability_cache") or {}
    if not entry or entry.get("key") != key or not isinstance(entry.get("result"), dict):
        return None
    return {**entry["result"], "cached": True, "computed_at": entry.get("computed_at")}


def store_availability(db, rbd_id: str, key: str, result: dict, uid: str | None) -> str:
    """Save an availability result on the RBD doc. Returns ``computed_at``."""
    computed_at = datetime.now(timezone.utc).isoformat()
    clean = {k: v for k, v in result.items() if k not in ("cached", "computed_at")}
    # JSON round-trip: plain types only (no numpy scalars) in the document.
    clean = json.loads(json.dumps(clean, default=float))
    db.rbds.update_one(
        {"_id": rbd_id},
        {"$set": {"availability_cache": {
            "key": key,
            "result": clean,
            "computed_at": computed_at,
            "computed_by": uid,
        }}},
    )
    return computed_at


def availability_state_key(graph: dict, t_simulation: float | None, state: dict | None) -> str:
    """The key of a simulation from a current state (#155): never the saved
    from-new key, so such a run can't be served as, or replace, the saved
    result."""
    payload = {"base": availability_cache_key(graph, t_simulation), "state": state or {}}
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# ---- Exact availability results (#154 / #155) --------------------------------
#
# The exact figures over time (rbd_analysis.exact_availability) take from a
# fraction of a second to a minute, so they are cached by a hash of the graph,
# the window and the current state: on the RBD document (``exact_cache``, a
# few entries, newest kept) when the caller may edit it, and in a small
# per-process LRU (scoped to the caller's read owners, as saved models resolve
# in that scope) for unsaved graphs, viewers and samples. They never touch
# ``availability_cache``, the saved simulation.

EXACT_CACHE_VERSION = 1
EXACT_DOC_ENTRIES = 6
_EXACT_LRU_SIZE = 64
_exact_lru: "OrderedDict[tuple, dict]" = OrderedDict()
_exact_lock = threading.Lock()


def exact_cache_key(graph: dict, horizon: float | None, state: dict | None) -> str:
    """sha256 of the canonical analysis graph, the window (None: the default
    horizon) and the canonical current state."""
    payload = {
        "v": EXACT_CACHE_VERSION,
        "graph": canonical_analysis_graph(graph),
        "horizon": _t_sim(horizon),
        "state": state or {},
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _scope(owner_id) -> tuple:
    return tuple(sorted(str(o) for o in (owner_id if isinstance(owner_id, (list, tuple, set)) else [owner_id])))


def cached_exact(doc: dict | None, key: str, owner_id=None) -> dict | None:
    """A cached exact payload for ``key``: from the RBD doc, else this
    process's LRU (in ``owner_id``'s scope; None reads the doc only)."""
    entry = ((doc or {}).get("exact_cache") or {}).get(key)
    if isinstance(entry, dict) and isinstance(entry.get("result"), dict):
        return entry["result"]
    if owner_id is None:
        return None
    with _exact_lock:
        hit = _exact_lru.get((_scope(owner_id), key))
        if hit is not None:
            _exact_lru.move_to_end((_scope(owner_id), key))
        return hit


def remember_exact(key: str, result: dict, owner_id=None) -> None:
    """Keep an exact payload in this process's LRU."""
    with _exact_lock:
        _exact_lru[(_scope(owner_id), key)] = result
        _exact_lru.move_to_end((_scope(owner_id), key))
        while len(_exact_lru) > _EXACT_LRU_SIZE:
            _exact_lru.popitem(last=False)


def clear_exact_lru() -> None:
    with _exact_lock:
        _exact_lru.clear()


def store_exact(db, rbd_id: str, key: str, result: dict) -> None:
    """Save an exact payload on the RBD doc, keeping the newest
    :data:`EXACT_DOC_ENTRIES` entries."""
    doc = db.rbds.find_one({"_id": rbd_id}, {"exact_cache": 1}) or {}
    entries = dict(doc.get("exact_cache") or {})
    entries[key] = {
        "result": json.loads(json.dumps(result, default=float)),
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }
    newest = sorted(entries.items(), key=lambda kv: kv[1].get("computed_at") or "", reverse=True)
    db.rbds.update_one({"_id": rbd_id}, {"$set": {"exact_cache": dict(newest[:EXACT_DOC_ENTRIES])}})


def analyze_exact(db, graph: dict, owner_id, horizon: float | None = None,
                  state: dict | None = None) -> dict:
    """The free (no simulation) availability payload: the exact long-run
    figures, importance and costs (:func:`rbd_analysis.analyze_availability`
    with ``simulate=False``) plus the ``exact`` block over time
    (:func:`rbd_analysis.exact_availability`). Saved models resolve in
    ``owner_id``'s scope, as for :func:`analyze_graph`."""

    def resolve_model(model_id: str) -> dict | None:
        return models_service.get_live_model(db, model_id, owner_id)

    base = rbd_analysis.analyze_availability(
        graph, resolve_model=resolve_model, t_simulation=horizon, simulate=False)
    exact = rbd_analysis.exact_availability(graph, resolve_model=resolve_model, horizon=horizon, state=state)
    return {**base, "exact": exact}


def long_run_only(db, graph: dict, owner_id, horizon: float | None = None) -> dict:
    """The free payload without the figures over time (they're deferred)."""

    def resolve_model(model_id: str) -> dict | None:
        return models_service.get_live_model(db, model_id, owner_id)

    return rbd_analysis.analyze_availability(
        graph, resolve_model=resolve_model, t_simulation=horizon, simulate=False)


def should_store_availability(doc: dict | None, key: str) -> bool:
    """Whether a freshly computed result for ``key`` should replace the saved
    one. Always when it's for the diagram as saved; for an unsaved what-if
    variation only when the saved entry is already stale (so exploring edits
    never clobbers the result public links and free viewers rely on)."""
    if doc is None:
        return False
    saved_key = availability_cache_key(doc.get("graph") or {})
    if key == saved_key:
        return True
    entry = doc.get("availability_cache") or {}
    return entry.get("key") != saved_key
