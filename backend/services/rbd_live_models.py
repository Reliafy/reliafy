"""A block linked to a saved model always takes the model's current parameters.

A block that picks a saved model keeps a copy of its fit (distribution, parameters, unit) so the
builder can show it and the analysis can run without re-fitting. That copy goes stale when the
model is revised: the diagram would go on using the old numbers while the model page says every
RBD block that uses it takes the new ones. So every read of a diagram, and every graph sent for
analysis, has its linked blocks refreshed from the saved model here: one source, the model.

A block whose model can't be read (deleted, or not visible to the reader) keeps what it has; the
analysis says so where it matters.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

#: Keys of a block's model that come from its saved model's fit.
_FIT_KEYS = ("distribution", "distribution_id", "params", "extras", "unit", "base_distribution_id", "mixture")

#: Block kinds refreshed here, by the saved model's kind. Others (regression, joint, alt_stress,
#: repairable) already read their saved model live in the analysis.
_KINDS = {"distribution": (None, "distribution"), "two_clock": ("two_clock",)}


def _linked_id(model: Any) -> Optional[str]:
    if not isinstance(model, dict) or model.get("source") != "saved":
        return None
    ref = model.get("modelId") or model.get("model_id")
    if not isinstance(ref, str) or not ref or ref.startswith(("repairable:", "alt:")):
        return None
    return ref


def current_model(model: dict, saved) -> dict:
    """``model`` (a block's stored model) with ``saved``'s (a Model document's) current fit in
    place of its copy. As it is when the kinds don't match or the saved fit has no parameters."""
    if saved is None or saved.kind not in _KINDS or model.get("kind") not in _KINDS[saved.kind]:
        return model
    from backend.services.rbd_graph import GraphError, _saved_model

    try:
        fresh = _saved_model(saved.id, "block", lambda _id: saved)
    except GraphError:
        return model
    if not fresh.get("params") or not fresh.get("distribution_id"):
        return model
    if _same_fit(model, fresh):
        return model  # already current: the block is left exactly as it is
    out = {k: v for k, v in model.items() if k not in _FIT_KEYS and k != "converted"}
    for key in _FIT_KEYS:
        if fresh.get(key) is not None:
            out[key] = fresh[key]
    if saved.name:
        out["name"] = saved.name
    return out


def _values(params) -> dict:
    out = {}
    for p in params or []:
        if isinstance(p, dict):
            try:
                out[str(p.get("name"))] = float(p.get("value"))
            except (TypeError, ValueError):
                out[str(p.get("name"))] = p.get("value")
    return out


def _same_fit(model: dict, fresh: dict) -> bool:
    """Whether a block's copy is the saved model's fit as it is now (in the model's own unit: a copy
    converted to the diagram's unit keeps what it was in ``converted``)."""
    own = model.get("converted") or model
    return (model.get("distribution_id") == fresh.get("distribution_id")
            and _values(own.get("params")) == _values(fresh.get("params"))
            and (own.get("extras") or None) == (fresh.get("extras") or None))


def refresh_graph(graph: Any, lookup: Callable[[str], Any]) -> Any:
    """``graph`` with every block linked to a saved model on that model's current fit.
    ``lookup(model_id)`` gives the Model document (or None). The graph passed in is not changed;
    one with nothing to refresh comes back as it is."""
    if not isinstance(graph, dict) or not isinstance(graph.get("nodes"), list):
        return graph
    from backend.services import rbd_standby

    seen: dict[str, Any] = {}

    def saved_of(ref: str):
        if ref not in seen:
            try:
                seen[ref] = lookup(ref)
            except Exception:  # noqa: BLE001 - an unreadable model keeps the block's copy
                seen[ref] = None
        return seen[ref]

    nodes, changed = [], False
    for node in graph["nodes"]:
        data = node.get("data") if isinstance(node, dict) else None
        if not isinstance(data, dict):
            nodes.append(node)
            continue
        new_data = None
        for path in rbd_standby.model_paths(data):
            model = rbd_standby.get_path(data, path)
            ref = _linked_id(model)
            if ref is None:
                continue
            new = current_model(model, saved_of(ref))
            if new != model:
                if new_data is None:
                    new_data = dict(data)
                rbd_standby.set_path(new_data, path, new)
        if new_data is not None:
            changed = True
            nodes.append({**node, "data": new_data})
        else:
            nodes.append(node)
    return {**graph, "nodes": nodes} if changed else graph


def refresh(db, graph: Any, owners) -> Any:
    """:func:`refresh_graph` with saved models read in ``owners``' scope."""
    from backend.services import models as models_service

    return refresh_graph(graph, lambda ref: models_service.get_model(db, ref, owners))


def refresh_doc(db, doc: Optional[dict], owners) -> Optional[dict]:
    """A stored RBD document with its graph refreshed (the diagram owner's models count too)."""
    if not isinstance(doc, dict) or not isinstance(doc.get("graph"), dict):
        return doc
    scope = [*(owners if isinstance(owners, (list, tuple)) else [owners]), doc.get("owner_id")]
    graph = refresh(db, doc["graph"], [o for o in scope if o])
    return doc if graph is doc["graph"] else {**doc, "graph": graph}
