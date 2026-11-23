"""An RBD generated from the plant: the positions inside a system are its blocks,
their connections say how the blocks are wired, and redundancy groups say where
k of n is enough.

* Each child position is a block. Its model is the position's own model in use, else its
  class's fitted model, else its parts-count rate, else (positions inside it) a sub-system
  built from them (position_models._tree_parts); with none of these, no model: the block is
  named in the notes and says so, and the diagram isn't calculated until it has one (a life is
  never invented for it).
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
* Positions that look alike (the same name but for a unit suffix, "Pump set 1" and "Pump set
  2", and the same class) with no redundancy set are never quietly taken as both needed:
  ``ask`` lists them, the app asks how they work together before building
  (``arrangements``: parallel, standby or series), and a diagram built without an answer says
  in its notes that they're drawn in series until the tree says otherwise.

The diagram is saved as a normal Reliafy RBD (re-generating updates the same
one), so it's analysed by RePyability like any other.
"""

from __future__ import annotations

from backend.maintenance.service import Invalid, Maintenance, class_id



def _bid(pid: str) -> str:
    return "p" + pid[:10]


#: A block with no model: its own words (its tooltip). No life is invented in its place.
NO_MODEL_SOURCE = ("No life model yet: this position has no model in use, no class model and no parts-count "
                   "rate. Give it a model, or mark it as never failing (Status › Working)")


def _children(m: Maintenance, scope_id: str) -> list[dict]:
    return sorted([c for c in m.s.inn(m.org, scope_id, "PART_OF")
                   if c["label"] == "Position" and not c.get("retired")], key=lambda c: c["name"].lower())


def suspected_sets(m: Maintenance, children: list[dict], said_series=()) -> list[dict]:
    """Positions among ``children`` that look like units of one job (the same name but for a unit
    suffix, as the Calculator's series-redundancy check reads labels, and the same class) and are
    in no redundancy set: [{position_ids, names}]. ``said_series``: sets of ids the user has said
    are all needed, left out."""
    from backend.services.rbd_analysis import _label_stem

    said = {frozenset(x) for x in said_series}
    buckets: dict = {}
    for c in children:
        if m.groups_of(c["id"]):
            continue
        stem, tok = _label_stem(c["name"])
        if not stem or tok is None:
            continue
        # The free-text class, not _class_key: on a product (and items built from it) each design
        # position is a class of its own, so Pump set 1 and Pump set 2 would never match.
        buckets.setdefault((stem, (c.get("position_class") or "").strip().lower()), []).append(c)
    out = []
    for kids in buckets.values():
        if len(kids) < 2 or len({_label_stem(c["name"])[1] for c in kids}) < len(kids):
            continue
        ids = [c["id"] for c in kids]
        if frozenset(ids) in said:
            continue
        out.append({"position_ids": ids, "names": [c["name"] for c in kids]})
    return sorted(out, key=lambda x: x["names"][0].lower())


def ask(m: Maintenance, scope_id: str) -> list[dict]:
    """What to ask before building ``scope_id``'s diagram: its look-alike positions with no set."""
    m._get(scope_id, "Position")
    return suspected_sets(m, _children(m, scope_id))


ARRANGEMENTS = ("parallel", "standby", "series")


def apply_arrangements(m: Maintenance, scope_id: str, arrangements) -> list[frozenset]:
    """Record how look-alike positions work together, as the user answered before building:
    each ``{position_ids, how: parallel | standby | series, k?, standby?}``. parallel: a set where
    any k (default 1) will do; standby: k running (default 1), the others waiting (cold unless
    ``standby`` says warm or hot); both are redundancy sets on the tree (shown there, and used by
    every rebuild). series: every one needed, nothing recorded. Returns the series answers."""
    ids = {c["id"] for c in _children(m, scope_id)}
    series: list[frozenset] = []
    for a in arrangements or []:
        if not isinstance(a, dict):
            raise Invalid("Each arrangement is {position_ids, how: parallel | standby | series}.")
        how = a.get("how")
        members = [pid for pid in dict.fromkeys(a.get("position_ids") or []) if isinstance(pid, str)]
        if how not in ARRANGEMENTS:
            raise Invalid("how is parallel (any of them can do the job), standby (duty and standby) or series "
                          "(every one needed).")
        if len(members) < 2 or any(pid not in ids for pid in members):
            raise Invalid("An arrangement names two or more of the positions directly inside this one.")
        if how == "series":
            series.append(frozenset(members))
            continue
        m.create_group(str(a.get("name") or ""), members, k=a.get("k") or 1,
                       mode="active" if how == "parallel" else "standby",
                       standby=a.get("standby") or "cold")
    return series


def build(m: Maintenance, scope_id: str, block_model=None, unit: str = "days", said_series=()) -> dict:
    """The compact RBD graph for a position's children, and notes on how it was built.
    ``block_model(child) -> (node fields or None, note or None)`` gives each block its model
    (the Modelling tab's "Build an RBD from what's inside": the child's model in use; None:
    no model, listed in ``placeholders``); by default the child's class model, in days."""
    scope = m._get(scope_id, "Position")
    children = _children(m, scope_id)
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
                fields = {"data": {"model_source": NO_MODEL_SOURCE}}
                placeholders.append(c["name"])
            # A position whose block is an RBD of its own is a sub-system block (analysed as one).
            sub = fields.get("subsystem_rbd_id") or ((fields.get("data") or {}).get("rbd") or {}).get("id")
            nodes.append({"id": _bid(c["id"]), "type": "subsystem" if sub else "component", "label": c["name"], **fields})
            continue
        cls = m._class_key(c)
        model_node = m.s.node(m.org, class_id(m.org, cls)) if cls else None
        model = (model_node or {}).get("model")
        if model:
            fields = {"distribution_id": model["distribution"], "params": model["params"]}
            if model.get("extras"):
                fields["extras"] = model["extras"]
            nodes.append({"id": _bid(c["id"]), "type": "component", "label": c["name"], "model": fields})
        else:
            placeholders.append(c["name"])
            nodes.append({"id": _bid(c["id"]), "type": "component", "label": c["name"],
                          "data": {"model_source": NO_MODEL_SOURCE}})

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
        notes.append(f"No life model yet for {', '.join(placeholders)}, so the diagram can't be worked out until "
                     + ("each has one: fit one for the position's class, or give each block a model in the RBD builder."
                        if block_model is None else
                        "each has one: give each a model on its Models tab and rebuild, or set one in the RBD builder.")
                     + " A block that never fails (a frame, say) can be marked Working under Status instead.")
    alike = suspected_sets(m, children, said_series)
    for x in alike:
        names = x["names"]
        notes.append(f"{', '.join(names[:-1])} and {names[-1]} look like units of one job, but nothing says how they "
                     "work together, so they're drawn in series (every one needed). If fewer will do, mark them as a "
                     "set (Redundancy inside…, or answer when you build) and rebuild.")
    graph = {"nodes": nodes, "unit": unit,
             "edges": [{"source": s, "target": t} for (s, t) in sorted(edges)]}
    return {"graph": graph, "notes": notes, "placeholders": placeholders, "scope": scope, "redundancy": used,
            "ask": alike}


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
    * Standby whose members are single blocks (none a sub-system; with different life models,
      up to rbd_standby.MAX_OWN_UNITS, each unit keeping its own): one standby block, k running
      and the rest waiting: cold, warm (ageing at its dormancy) or hot, with the chance a waiting
      one starts when switched in. The members' own blocks go.
    * Any other standby set (sub-systems, or too many different models): the members into a k-of-n vote,
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
            from backend.services.rbd_standby import MAX_OWN_UNITS, own_from_units

            identical = all(b.get("type") == "component" for b in blocks) and all(
                _same_model(first, b) for b in blocks[1:])
            # Single blocks with models that differ (an older duty pump, a smaller spare):
            # one standby block too, each unit on its own model (#363).
            differing = not identical and n <= MAX_OWN_UNITS and all(
                b.get("type") == "component" and b.get("model") and not (b.get("data") or {}).get("rbd")
                for b in blocks)
            dormancy = _WAIT.get(g["standby"], g.get("dormancy"))
            if (identical or differing) and dormancy is not None:
                sid = "s" + g["id"][:10]
                spb = g.get("start_probability")
                node = {"id": sid, "type": "standby", "label": f"{g['name']} ({need} running, {n - need} standby)",
                        "model": first["model"], "k": need, "spares": n - need, "dormancy": dormancy,
                        "cold": dormancy == 0.0,
                        "data": {"redundancy_group": g["id"], "positions": [mm["id"] for mm in members],
                                 **({"model_source": (first.get("data") or {}).get("model_source")}
                                    if (first.get("data") or {}).get("model_source") else {})}}
                if spb is not None:  # cold, warm or hot: a spare that fails to start is skipped
                    node["startProb"] = spb
                if differing:  # the members in order: the first `need` running, then the spares
                    node.update(own_from_units([b["model"] for b in blocks], need))
                nodes[:] = [x for x in nodes if x["id"] not in set(bids)] + [node]
                units.append({"id": sid, "kind": "standby", "members": bids})
                words = {0.0: "cold"}.get(dormancy, "hot" if dormancy == 1.0 else f"warm, ageing at {_pct(dormancy)}")
                start = (f", each starting when switched in with a {_pct(spb)} chance" if spb is not None
                         else "")
                own = " Its units have different models, each kept on its own unit." if differing else ""
                notes.append(f"{g['name']} is one standby block ({words}): {need} of {', '.join(brief['members'])} "
                             f"running, the other{'s' if n - need > 1 else ''} waiting{start}.{own}")
                used.append({**brief, "drawn": "standby"})
                continue
            why = ("its members are sub-systems" if any(b.get("type") != "component" for b in blocks) else
                   f"its members have different models and there are more than {MAX_OWN_UNITS}"
                   if not identical and n > MAX_OWN_UNITS else
                   "a member has no model" if not identical and not differing else
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


EXISTING_CHOICES = ("open", "copy", "rebuild")


def _existing_rbd(m: Maintenance, db, scope_id: str):
    """The RBD made from this structure before, while it's still saved (else None)."""
    scope = m.s.node(m.org, scope_id) or {}
    rid = scope.get("rbd_id")
    return db.rbds.find_one({"_id": rid, "owner_id": m.org}) if rid else None


def save(m: Maintenance, db, scope_id: str, owners=None, hidden=frozenset(), arrangements=None,
         check: bool = False, existing: str | None = None) -> dict:
    """Build the RBD and save it to the workspace. Each block takes what Build from what's inside
    gives it (the position's model in use, its class's, its parts-count rate, or a sub-system of
    what's inside it); a block with none of these has no model. ``check``: only what to ask first
    ({ask}, and {existing} when an RBD was made from it before), nothing saved. ``arrangements``:
    the answers (apply_arrangements), recorded before building.

    An RBD made from this structure before is never overwritten unasked: ``existing`` says what to
    do with it. None or "open": nothing is built or saved, it comes back ({existing: true, rbd_id,
    name}); "copy": a new RBD beside it (the position stays linked to the first); "rebuild": built
    again over it, which replaces every edit made to it since."""
    from backend.maintenance import position_models as pm
    from backend.services import rbds as rbds_service
    from backend.services.rbd_graph import GraphError, normalize_graph, wrap_layout

    if existing not in (None, *EXISTING_CHOICES):
        raise Invalid("existing is open, copy or rebuild.")
    had = _existing_rbd(m, db, scope_id)
    when = had.get("updated_at") if had else None
    found = ({"rbd_id": had["_id"], "name": had.get("name", ""),
              "updated_at": when.isoformat() if hasattr(when, "isoformat") else when} if had else None)
    if check:
        return {"ask": ask(m, scope_id), **({"existing": found} if found else {})}
    if found and existing in (None, "open"):
        return {**found, "existing": True, "notes": [], "placeholders": [], "ask": []}
    said = apply_arrangements(m, scope_id, arrangements)
    owners = list(owners or [m.org])
    _, fetch, _, unit, block, nested = pm._tree_parts(m, db, owners, hidden, scope_id, owner_id=m.org)
    built = build(m, scope_id, block_model=block, unit=unit, said_series=said)
    scope = built["scope"]
    if nested:
        built["notes"].append(f"No life model yet inside sub-systems: {', '.join(nested[:8])}"
                              f"{' …' if len(nested) > 8 else ''}. Give each a model and rebuild.")
    try:
        graph = normalize_graph(built["graph"], resolve_saved_model=lambda mid: fetch("model", mid))
        graph["nodes"] = wrap_layout(graph["nodes"])
        copy = bool(found) and existing == "copy"
        name = f"{scope['name']} (from Maintenance)" + (" (copy)" if copy else "")
        rbd = rbds_service.save_rbd(db, name, graph, m.org,
                                    rbd_id=found["rbd_id"] if found and existing == "rebuild" else None)
    except GraphError as err:
        raise Invalid(f"The diagram couldn't be made: {err}") from None
    if not copy and rbd.id != scope.get("rbd_id"):
        m._emit("position.rbd_linked", {"id": scope_id, "changes": {"rbd_id": rbd.id}})
    return {"rbd_id": rbd.id, "name": rbd.name, "notes": built["notes"],
            "placeholders": built["placeholders"] + nested, "ask": built["ask"], "unit": unit,
            "blocks": sum(1 for n in built["graph"]["nodes"] if n["type"] in ("component", "subsystem", "standby"))}
