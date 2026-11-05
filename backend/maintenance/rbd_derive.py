"""An RBD generated from the plant: the positions inside a system are its blocks,
their connections say how the blocks are wired, and redundancy groups say where
k of n is enough.

* Each child position is a block. Its non-repairable model is its class's fitted model
  (in days); with none, a placeholder, named in the notes.
* A connection from A to B is an edge A -> B.
* A redundancy group (k of its n members needed) becomes a vote node: each
  member feeds it, and it feeds whatever the members fed.
* Blocks with nothing upstream start from the input; blocks with nothing
  downstream end at the output. With no connections at all, the blocks are
  taken to be in series (every one needed), and the notes say so; a block not
  connected to the others is put in series too.

The diagram is saved as a normal Reliafy RBD (re-generating updates the same
one), so it's analysed by RePyability like any other.
"""

from __future__ import annotations

from backend.maintenance.service import Invalid, Maintenance, class_id

PLACEHOLDER = {"distribution_id": "exponential", "params": [{"name": "failure_rate", "value": 0.001}],
               "placeholder": True}


def _bid(pid: str) -> str:
    return "p" + pid[:10]


def build(m: Maintenance, scope_id: str) -> dict:
    """The compact RBD graph for a position's children, and notes on how it was built."""
    scope = m._get(scope_id, "Position")
    children = sorted([c for c in m.s.inn(m.org, scope_id, "PART_OF")
                       if c["label"] == "Position" and not c.get("retired")], key=lambda c: c["name"].lower())
    if len(children) < 1:
        raise Invalid(f"{scope['name']} has no positions inside it to make blocks from.")
    ids = {c["id"] for c in children}
    notes, placeholders = [], []
    nodes = [{"id": "in", "type": "input"}, {"id": "out", "type": "output"}]
    for c in children:
        cls = (c.get("position_class") or "").strip()
        model_node = m.s.node(m.org, class_id(m.org, cls)) if cls else None
        model = (model_node or {}).get("model")
        if model:
            block_model = {"distribution_id": model["distribution"], "params": model["params"]}
            if model.get("extras"):
                block_model["extras"] = model["extras"]
        else:
            block_model = dict(PLACEHOLDER)
            placeholders.append(c["name"])
        nodes.append({"id": _bid(c["id"]), "type": "component", "label": c["name"], "model": block_model})

    edges: set[tuple[str, str]] = set()
    for c in children:
        for i in m._interfaces(c["id"], "FROM"):
            if i["to"]["id"] in ids:
                edges.add((_bid(c["id"]), _bid(i["to"]["id"])))

    # Redundancy groups among the children: members -> vote node -> their targets.
    for g in {g["id"]: g for c in children for g in m.groups_of(c["id"])}.values():
        members = [mm["id"] for mm in g["members"] if mm["id"] in ids]
        if len(members) < 2:
            continue
        vote = "g" + g["id"][:10]
        bids = {_bid(mid) for mid in members}
        targets = {t for (s, t) in edges if s in bids and t not in bids}
        edges = {(s, t) for (s, t) in edges if not (s in bids and t not in bids)}
        need = min(g["k"], len(members) - 1) if len(members) > 1 else 1
        nodes.append({"id": vote, "type": "knode", "label": f"{g['name']} ({need} of {len(members)})",
                      "n": need, "k": len(members)})
        edges |= {(b, vote) for b in bids} | {(vote, t) for t in targets}
        if g["mode"] == "standby":
            notes.append(f"{g['name']} is a {g['standby']} standby group; it's drawn as {need} of "
                         f"{len(members)} with every member running.")

    blocks = [n["id"] for n in nodes if n["type"] not in ("input", "output")]
    connected = {x for e in edges for x in e}
    if not edges:
        chain = [_bid(c["id"]) for c in children]
        edges = {("in", chain[0]), (chain[-1], "out")} | set(zip(chain, chain[1:]))
        if len(chain) > 1:
            notes.append("Nothing inside is connected yet, so every block is taken to be needed "
                         "(in series). Add connections to say how they're wired.")
    else:
        loose = [b for b in blocks if b not in connected]
        if loose:
            names = [n["label"] for n in nodes if n["id"] in loose]
            notes.append(f"{', '.join(names)} {'isn' if len(names) == 1 else 'aren'}'t connected to the "
                         f"others, so {'it is' if len(names) == 1 else 'they are'} taken to be needed (in series).")
        sources = [b for b in blocks if b in connected and not any(t == b for (_, t) in edges)]
        sinks = [b for b in blocks if b in connected and not any(s == b for (s, _) in edges)]
        head = "in"
        for b in loose:
            edges.add((head, b))
            head = b
        edges |= {(head, b) for b in sources} | {(b, "out") for b in sinks}

    if placeholders:
        notes.append(f"No non-repairable model yet for {', '.join(placeholders)}: a placeholder is used. Fit one for "
                     "the position's class, or give each block a model in the RBD builder.")
    graph = {"nodes": nodes, "unit": "days",
             "edges": [{"source": s, "target": t} for (s, t) in sorted(edges)]}
    return {"graph": graph, "notes": notes, "placeholders": placeholders, "scope": scope}


def save(m: Maintenance, db, scope_id: str) -> dict:
    """Build the RBD and save it to the workspace (updating the one made before)."""
    from backend.services import rbds as rbds_service
    from backend.services.rbd_graph import GraphError, normalize_graph

    built = build(m, scope_id)
    scope = built["scope"]
    try:
        graph = normalize_graph(built["graph"])
        existing = scope.get("rbd_id")
        if existing and not db.rbds.find_one({"_id": existing, "owner_id": m.org}):
            existing = None
        rbd = rbds_service.save_rbd(db, f"{scope['name']} (from Maintenance)", graph, m.org, rbd_id=existing)
    except GraphError as err:
        raise Invalid(f"The diagram couldn't be made: {err}") from None
    if rbd.id != scope.get("rbd_id"):
        m._emit("position.rbd_linked", {"id": scope_id, "changes": {"rbd_id": rbd.id}})
    return {"rbd_id": rbd.id, "name": rbd.name, "notes": built["notes"], "placeholders": built["placeholders"],
            "blocks": sum(1 for n in built["graph"]["nodes"] if n["type"] == "component")}
