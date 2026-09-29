"""Compact <-> persisted RBD graphs, server side.

A Python port of ``frontend/src/rbdGraph.js`` (``normalizeRbdGraph`` /
``compactGraph``) so programmatic callers — the MCP server — speak the same
compact node format as the in-app assistant and get diagrams that open on the
builder canvas exactly as if the assistant had drawn them: input/output
handles, fleshed-out life models and a tidy left-to-right layered layout.

Compact node (what an assistant writes and reads)::

    {"id": "p1", "type": "component", "label": "Pump A",
     "model": {"distribution_id": "weibull",
               "params": [{"name": "alpha", "value": 900}, {"name": "beta", "value": 1.4}],
               "placeholder": true},          # optional: a guessed value
     "repair": {...},                         # repairable diagrams only
     "n": 2, "k": 3, "spares": 1, "cold": true,
     "subsystem_rbd_id": "<saved rbd id>"}

A node may instead carry the persisted ``data: {...}`` object; both are
accepted. ``model.saved_model_id`` references a saved plain life model; it is
resolved (owner-scoped) into the same shape the builder's model picker stores.
"""

from __future__ import annotations

from typing import Callable, Optional

COL_GAP = 280
ROW_GAP = 150

NODE_TYPES = ("input", "output", "component", "series", "parallel", "knode", "standby", "subsystem")

_ARROW = {"type": "arrowclosed", "width": 18, "height": 18}


class GraphError(ValueError):
    """A compact graph that can't be turned into a diagram (user-facing text)."""


def layout_graph(nodes: list[dict], edges: list[dict]) -> list[dict]:
    """Longest-path layered layout (mirrors the builder's Auto-arrange)."""
    ids = {n["id"] for n in nodes}
    indeg = {n["id"]: 0 for n in nodes}
    adj: dict[str, list[str]] = {n["id"]: [] for n in nodes}
    for e in edges:
        if e["source"] not in ids or e["target"] not in ids:
            continue
        adj[e["source"]].append(e["target"])
        indeg[e["target"]] += 1

    rank: dict[str, int] = {}
    remaining = dict(indeg)
    queue = [n["id"] for n in nodes if remaining[n["id"]] == 0]
    for nid in queue:
        rank[nid] = 0
    while queue:
        nid = queue.pop(0)
        r = rank.get(nid, 0)
        for t in adj[nid]:
            rank[t] = max(rank.get(t, 0), r + 1)
            remaining[t] -= 1
            if remaining[t] == 0:
                queue.append(t)
    for n in nodes:
        rank.setdefault(n["id"], 0)

    max_rank = max(rank.values(), default=0)
    if "input" in ids:
        rank["input"] = 0
    if "output" in ids:
        rank["output"] = max(max_rank, 1)

    cols: dict[int, list[dict]] = {}
    for n in nodes:
        cols.setdefault(rank[n["id"]], []).append(n)
    out = []
    for r, members in cols.items():
        members.sort(key=lambda n: n["id"])
        m = len(members)
        for i, n in enumerate(members):
            out.append({**n, "position": {"x": r * COL_GAP, "y": (i - (m - 1) / 2) * ROW_GAP}})
    return out


def _params(raw, where: str) -> list[dict]:
    out = []
    for p in raw or []:
        if not isinstance(p, dict) or p.get("name") is None or p.get("value") is None:
            raise GraphError(f"{where}: params must be a list of {{name, value}}.")
        try:
            out.append({"name": str(p["name"]), "value": float(p["value"])})
        except (TypeError, ValueError):
            raise GraphError(f"{where}: parameter '{p['name']}' must be a number.") from None
    return out


def _inline_model(model: dict, where: str) -> dict:
    """Flesh out an inline ``{distribution_id, params}`` model."""
    from backend import fitting

    dist = str(model.get("distribution_id") or model.get("distribution") or "").strip()
    if not dist:
        raise GraphError(f"{where}: the model needs a distribution_id (or a saved_model_id).")
    try:
        dist_id = fitting.resolve_distribution_id(dist)
    except fitting.FitError:
        raise GraphError(
            f"{where}: unsupported distribution '{dist}' — use one of {', '.join(fitting.DISTRIBUTIONS)}."
        ) from None
    params = _params(model.get("params"), where)
    if not params:
        raise GraphError(f"{where}: the model needs params, e.g. [{{\"name\": \"alpha\", \"value\": 900}}].")
    try:
        fitting.param_values(dist_id, params, where)  # SurPyval names only
    except fitting.FitError as exc:
        raise GraphError(str(exc)) from None
    out = {
        "source": "params",
        "distribution": fitting.DISTRIBUTIONS[dist_id]["name"],
        "distribution_id": dist_id,
        "params": params,
    }
    if model.get("placeholder"):
        out["placeholder"] = True
    return out


def _saved_model(model_id: str, where: str, resolve_saved_model) -> dict:
    """The builder model-picker shape for a saved model reference."""
    saved = resolve_saved_model(model_id) if resolve_saved_model else None
    if saved is None:
        raise GraphError(f"{where}: saved model '{model_id}' not found.")
    r = saved.results or {}
    if saved.kind not in ("distribution", "regression", "nonparametric"):
        raise GraphError(
            f"{where}: model “{saved.name}” is a {saved.kind} model — RBD blocks need a "
            "life distribution; give distribution_id + params inline instead."
        )
    return {
        "source": "saved",
        "kind": saved.kind,
        "modelId": saved.id,
        "name": saved.name,
        "distribution": r.get("distribution"),
        "distribution_id": r.get("distribution_id") or saved.distribution_id,
        "params": [{"name": p.get("name"), "value": p.get("value")} for p in (r.get("params") or [])],
        "extras": r.get("extras"),
        "covariates": (r.get("functions") or {}).get("covariates") or [],
        "unit": r.get("unit") or "",
    }


def _model(model, where: str, resolve_saved_model) -> dict:
    if not isinstance(model, dict):
        raise GraphError(f"{where}: model must be an object.")
    saved_id = model.get("saved_model_id") or model.get("modelId") or model.get("model_id")
    if saved_id:
        out = _saved_model(str(saved_id), where, resolve_saved_model)
        if model.get("placeholder"):
            out["placeholder"] = True
        return out
    return _inline_model(model, where)


def normalize_graph(
    graph: dict,
    resolve_saved_model: Optional[Callable[[str], object]] = None,
) -> dict:
    """Turn a compact ``{nodes, edges, unit, repairable?}`` into the persisted
    builder shape. Raises :class:`GraphError` with a fixable message."""
    raw_nodes = graph.get("nodes") or []
    raw_edges = graph.get("edges") or []
    if not isinstance(raw_nodes, list) or not isinstance(raw_edges, list):
        raise GraphError("nodes and edges must be lists.")

    nodes, seen = [], set()
    for raw in raw_nodes:
        if not isinstance(raw, dict):
            raise GraphError("each node must be an object.")
        nid = str(raw.get("id") or "").strip()
        ntype = str(raw.get("type") or "").strip()
        if not nid:
            raise GraphError("every node needs an id.")
        if nid in seen:
            raise GraphError(f"duplicate node id '{nid}'.")
        seen.add(nid)
        if ntype not in NODE_TYPES:
            raise GraphError(f"node '{nid}': type must be one of {', '.join(NODE_TYPES)}.")

        data = dict(raw.get("data") or {})
        for key in ("label", "model", "repair", "n", "k", "spares", "cold"):
            if raw.get(key) is not None and key not in data:
                data[key] = raw[key]
        if raw.get("subsystem_rbd_id") and "rbd" not in data:
            data["rbd"] = {"id": str(raw["subsystem_rbd_id"])}
        where = f"node '{data.get('label') or nid}'"
        if data.get("model") is not None:
            data["model"] = _model(data["model"], where, resolve_saved_model)
        if data.get("repair") is not None:
            if not isinstance(data["repair"], dict):
                raise GraphError(f"{where}: repair must be an object.")
            data["repair"] = _inline_model(data["repair"], f"{where} repair")
        if not data.get("label"):
            data["label"] = "Input" if ntype == "input" else "Output" if ntype == "output" else nid

        node = {"id": nid, "type": ntype, "data": data}
        if ntype == "input":
            node.update(sourcePosition="right", deletable=False, className="rbd-node rbd-io")
        elif ntype == "output":
            node.update(targetPosition="left", deletable=False, className="rbd-node rbd-io")
        nodes.append(node)

    edges = []
    for i, e in enumerate(raw_edges):
        if not isinstance(e, dict) or not e.get("source") or not e.get("target"):
            raise GraphError("each edge needs a source and a target node id.")
        src, tgt = str(e["source"]), str(e["target"])
        for end in (src, tgt):
            if end not in seen:
                raise GraphError(f"edge {src} -> {tgt} references unknown node '{end}'.")
        edges.append({
            "id": e.get("id") or f"e-{src}-{tgt}-{i}",
            "source": src,
            "target": tgt,
            "type": "smoothstep",
            "markerEnd": dict(_ARROW),
        })

    out = {"nodes": layout_graph(nodes, edges), "edges": edges, "unit": str(graph.get("unit") or "")}
    if graph.get("repairable"):
        out["repairable"] = True
    if graph.get("ccf_groups"):
        out["ccf_groups"] = graph["ccf_groups"]
    return out


def compact_graph(graph: dict) -> dict:
    """Strip a persisted graph to what an assistant needs to read and edit."""
    nodes = []
    for n in graph.get("nodes") or []:
        d = n.get("data") or {}
        node = {"id": n.get("id"), "type": n.get("type")}
        if d.get("label"):
            node["label"] = d["label"]
        for key in ("model", "repair"):
            m = d.get(key)
            if isinstance(m, dict):
                cm = {"distribution_id": m.get("distribution_id"), "params": m.get("params")}
                if m.get("modelId"):
                    cm["saved_model_id"] = m["modelId"]
                if m.get("placeholder"):
                    cm["placeholder"] = True
                node[key] = cm
        for key in ("n", "k", "spares", "cold"):
            if d.get(key) is not None:
                node[key] = d[key]
        if isinstance(d.get("rbd"), dict) and d["rbd"].get("id"):
            node["subsystem_rbd_id"] = d["rbd"]["id"]
        nodes.append(node)
    edges = [{"source": e.get("source"), "target": e.get("target")} for e in graph.get("edges") or []]
    out = {"nodes": nodes, "edges": edges, "unit": graph.get("unit") or ""}
    if graph.get("repairable"):
        out["repairable"] = True
    if graph.get("ccf_groups"):
        out["ccf_groups"] = graph["ccf_groups"]
    return out


def placeholder_labels(graph: dict) -> list[str]:
    """Labels of blocks whose life model is a guessed placeholder."""
    return [
        (n.get("data") or {}).get("label") or n.get("id")
        for n in graph.get("nodes") or []
        if isinstance((n.get("data") or {}).get("model"), dict) and n["data"]["model"].get("placeholder")
    ]
