"""An RBD generated from the plant: the positions inside a system are its blocks,
their connections say how the blocks are wired, and redundancy groups say where
k of n is enough.

* Each child position is a block. Its non-repairable model is its class's fitted model
  (in days); with none, a placeholder, named in the notes.
* A connection from A to B is an edge A -> B.
* A redundancy group (k of its n members needed) becomes a vote node: each
  member feeds it, and it feeds whatever the members fed. A standby group of
  identical single blocks becomes one standby block instead (cold, warm or hot,
  with its switch-start chance); any other standby group is a vote whose members
  each run k/n of the time (redundancy_units).
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


def build(m: Maintenance, scope_id: str, block_model=None, unit: str = "days") -> dict:
    """The compact RBD graph for a position's children, and notes on how it was built.
    ``block_model(child) -> (node fields or None, note or None)`` gives each block its model
    (the Modelling tab's "Build an RBD from what's inside": the child's model in use; None:
    a placeholder); by default the child's class model, in days."""
    scope = m._get(scope_id, "Position")
    children = sorted([c for c in m.s.inn(m.org, scope_id, "PART_OF")
                       if c["label"] == "Position" and not c.get("retired")], key=lambda c: c["name"].lower())
    if len(children) < 1:
        raise Invalid(f"{scope['name']} has no positions inside it to make blocks from.")
    ids = {c["id"] for c in children}
    notes, placeholders = [], []
    nodes = [{"id": "in", "type": "input"}, {"id": "out", "type": "output"}]
    for c in children:
        if block_model is not None:
            fields, note = block_model(c)
            if note:
                notes.append(note)
            if fields is None:
                fields = {"model": dict(PLACEHOLDER)}
                placeholders.append(c["name"])
            # A position whose block is an RBD of its own is a sub-system block (analysed as one).
            sub = fields.get("subsystem_rbd_id") or ((fields.get("data") or {}).get("rbd") or {}).get("id")
            nodes.append({"id": _bid(c["id"]), "type": "subsystem" if sub else "component", "label": c["name"], **fields})
            continue
        cls = (c.get("position_class") or "").strip()
        model_node = m.s.node(m.org, class_id(m.org, cls)) if cls else None
        model = (model_node or {}).get("model")
        if model:
            fields = {"distribution_id": model["distribution"], "params": model["params"]}
            if model.get("extras"):
                fields["extras"] = model["extras"]
        else:
            fields = dict(PLACEHOLDER)
            placeholders.append(c["name"])
        nodes.append({"id": _bid(c["id"]), "type": "component", "label": c["name"], "model": fields})

    edges: set[tuple[str, str]] = set()
    for c in children:
        for i in m._interfaces(c["id"], "FROM"):
            if i["to"]["id"] in ids:
                edges.add((_bid(c["id"]), _bid(i["to"]["id"])))
    connected_by_tree = bool(edges)

    # Redundancy sets among the children (the Explorer's, or topology groups): a standby block,
    # or the members wired into a k-of-n vote (redundancy, never series).
    units, used = redundancy_units(m, children, nodes, notes)
    by_member = {b: u for u in units for b in u["members"]}
    for u in units:
        bids = set(u["members"])
        if u["kind"] == "standby":
            # One standby block stands for the members: edges to or from any of them are its own.
            sb = u["id"]
            edges = {(sb if s in bids else s, sb if t in bids else t) for (s, t) in edges}
            edges = {(s, t) for (s, t) in edges if s != t}
            continue
        vote = u["id"]
        targets = {t for (s, t) in edges if s in bids and t not in bids}
        edges = {(s, t) for (s, t) in edges if not (s in bids and t not in bids)}
        edges |= {(b, vote) for b in bids} | {(vote, t) for t in targets}

    blocks = [n["id"] for n in nodes if n["type"] not in ("input", "output")]
    if not connected_by_tree:
        # Nothing inside is connected: the sets and the other blocks one after another, by name
        # (a set where its first member comes), each set its members side by side.
        chain, done = [], set()
        for c in children:
            b = _bid(c["id"])
            u = by_member.get(b)
            if u is None:
                chain.append(([b], b))
            elif u["id"] not in done:
                done.add(u["id"])
                chain.append(([u["id"]], u["id"]) if u["kind"] == "standby" else (sorted(u["members"]), u["id"]))
        edges = set(edges)
        tail = ["in"]
        for heads, end in chain:
            edges |= {(t, h) for t in tail for h in heads}
            tail = [end]
        edges |= {(t, "out") for t in tail}
        unit_ids = {u["id"] for u in units}
        singles = sum(1 for _, end in chain if end not in unit_ids)
        if len(chain) > 1 and not units:
            notes.append("Nothing inside is connected yet, so every block is taken to be needed "
                         "(in series). Add connections, or mark the positions that back each other up "
                         "(Redundancy…), to say how they're wired.")
        elif len(chain) > 1 and singles:
            notes.append("Nothing inside is connected yet, so the blocks outside a redundancy set are taken to "
                         "be needed (in series with the sets).")
    else:
        connected = {x for e in edges for x in e}
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
                     "the position's class, or give each block a model in the RBD builder." if block_model is None else
                     f"No model in use yet for {', '.join(placeholders)}: a placeholder (flagged) stands in. Give "
                     "each a model on the Modelling tab and rebuild, or set one in the RBD builder.")
    graph = {"nodes": nodes, "unit": unit,
             "edges": [{"source": s, "target": t} for (s, t) in sorted(edges)]}
    return {"graph": graph, "notes": notes, "placeholders": placeholders, "scope": scope, "redundancy": used}


_WAIT = {"cold": 0.0, "hot": 1.0}


def _same_model(a: dict, b: dict) -> bool:
    """Whether two blocks have the same life model (a standby block's units are identical)."""
    return bool(a.get("model")) and a.get("model") == b.get("model") and not (a.get("data") or {}).get("rbd") \
        and not (b.get("data") or {}).get("rbd")


def _pct(x: float) -> str:
    return f"{x * 100:.3g}%"


def redundancy_units(m: Maintenance, children: list[dict], nodes: list[dict], notes: list[str]) -> tuple[list, list]:
    """The redundancy sets among ``children`` as the diagram draws them, adding their nodes to
    ``nodes``: ([{id, kind: vote | standby, members: [block ids]}], [the groups used, in brief]).

    * Active (k of n needed): the members, each its own block, into a k-of-n vote.
    * Standby whose members are identical single blocks (one life model, none a sub-system): one
      standby block, k running and the rest waiting: cold, warm (ageing at its dormancy) or hot,
      with the chance a waiting one starts when switched in. The members' own blocks go.
    * Any other standby set (sub-systems, or different models): the members into a k-of-n vote,
      each running k/n of the time (they take turns; a repairable diagram's "Runs" share).
      Nothing about switching or ageing while waiting can be drawn on separate blocks, so the
      notes say what's counted."""
    ids = {c["id"] for c in children}
    by_bid = {n["id"]: n for n in nodes}
    units, used, taken = [], [], set()
    for g in {g["id"]: g for c in children for g in m.groups_of(c["id"])}.values():
        members = [mm for mm in g["members"] if mm["id"] in ids and mm["id"] not in taken]
        if len(members) < 2:
            continue
        taken |= {mm["id"] for mm in members}
        bids = [_bid(mm["id"]) for mm in members]
        n = len(members)
        need = min(g["k"], n - 1)
        if len(g["members"]) > n:
            notes.append(f"{g['name']} has members outside this position: only the {n} inside it are drawn.")
        brief = {"id": g["id"], "name": g["name"], "mode": g["mode"], "k": need, "n": n,
                 "members": [mm["name"] for mm in members]}
        blocks = [by_bid[b] for b in bids]
        if g["mode"] == "standby":
            first = blocks[0]
            identical = all(b.get("type") == "component" for b in blocks) and all(
                _same_model(first, b) for b in blocks[1:])
            dormancy = _WAIT.get(g["standby"], g.get("dormancy"))
            if identical and dormancy is not None:
                sid = "s" + g["id"][:10]
                spb = g.get("start_probability")
                node = {"id": sid, "type": "standby", "label": f"{g['name']} ({need} running, {n - need} standby)",
                        "model": first["model"], "k": need, "spares": n - need, "dormancy": dormancy,
                        "cold": dormancy == 0.0,
                        "data": {"redundancy_group": g["id"], "positions": [mm["id"] for mm in members],
                                 **({"model_source": (first.get("data") or {}).get("model_source")}
                                    if (first.get("data") or {}).get("model_source") else {})}}
                if spb is not None and dormancy == 0.0:
                    node["startProb"] = spb
                nodes[:] = [x for x in nodes if x["id"] not in set(bids)] + [node]
                units.append({"id": sid, "kind": "standby", "members": bids})
                words = {0.0: "cold"}.get(dormancy, "hot" if dormancy == 1.0 else f"warm, ageing at {_pct(dormancy)}")
                start = (f", each starting when switched in with a {_pct(spb)} chance" if spb is not None and
                         dormancy == 0.0 else "")
                notes.append(f"{g['name']} is one standby block ({words}): {need} of {', '.join(brief['members'])} "
                             f"running, the other{'s' if n - need > 1 else ''} waiting{start}.")
                used.append({**brief, "drawn": "standby"})
                continue
            why = ("its members are sub-systems" if any(b.get("type") != "component" for b in blocks) else
                   "its members have different models" if not identical else
                   "a warm standby needs how fast a waiting one ages (set it on the set)")
            share = need / n
            for b in blocks:
                b.setdefault("data", {})
                if not (b["data"].get("duty")):
                    b["data"]["duty"] = share
            notes.append(f"{g['name']} is a {g['standby']} standby set; {why}, so it's drawn as {need} of {n} with "
                         f"each running {_pct(share)} of the time (they take turns: change it under Runs in the "
                         "Maintenance plan). A non-repairable result counts every member as running.")
            used.append({**brief, "drawn": "vote", "runs": share})
        else:
            used.append({**brief, "drawn": "vote"})
        vote = "g" + g["id"][:10]
        nodes.append({"id": vote, "type": "knode", "label": f"{g['name']} ({need} of {n})", "n": need, "k": n})
        units.append({"id": vote, "kind": "vote", "members": bids})
    return units, used


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
