"""A repairable RBD's maintenance plan, read from the tree (Nov 2026).

Derryn: "The RBD maintenance plan needs to come from the Explorer maintenance tasks. It can't be
the other way around." So for a block that stands for a position (an RBD built from, or linked
to, the position the block's position sits inside), the position's tasks on the Explorer's
Maintenance tab are the one source of its planned work. Nothing is copied into the diagram: the
plan is read from the tasks each time the diagram is shown or calculated, and a block with no
tasks there runs to failure. A block drawn by hand (no position) keeps its own plan, edited in
the RBD as before.

What a task gives the block (an RCM decision says *what* a task does; its LSA says *how*):

* what it does, from its RCM kind: ``fixed_interval`` -> replace on age (at fixed times when its
  package visits on fixed dates); ``on_condition`` -> inspect on condition; ``failure_finding`` ->
  proof test. Routine work with no kind isn't modelled (what it does to the block's life isn't
  known), and the plan says so;
* how often: its interval on the calendar, or in running hours (turned into calendar time by the
  block's duty), in the diagram's unit;
* how long it takes the block off-line: its LSA's downtime, else its elapsed time;
* what it costs each time (task_costs.py); its package (the block's maintenance group); who does
  it (the LSA's labour, in words: the RBD's crews are one pool);
* restoration: as new, until the library takes a Kijima restoration from the RCM decision.

A block takes one task today: of several, a fixed-interval task first, then on condition, then a
proof test; the rest are listed as not modelled.

The diagram keeps only what belongs to it, in ``data.tree_settings``: an on-condition block's
replacement threshold, cost and time off-line (the inspection task doesn't say them), an age
replacement's early-renewal age at a group stop, a proof test's first test, coverage and full test.
Duty, crew priority and (for a task in no package) the maintenance group stay on the block.

What nothing says is left blank and flagged, never filled in (a cost nothing prices, a time
off-line, a repair time: no position history or class holds one today).

Saved calculations: :func:`fingerprint` is the version of each task a calculation used; an RBD
whose saved simulation used tasks that have changed since says so (and isn't rerun silently).
"""

from __future__ import annotations

import copy
import hashlib
import json

from backend.maintenance.service import Maintenance

_ORDER = {"fixed_interval": 0, "on_condition": 1, "failure_finding": 2}
_PLAN_TASK = {"on_condition": "condition", "failure_finding": "test"}
_KIND_WORDS = {"fixed_interval": "Fixed interval", "on_condition": "On condition", "failure_finding": "Failure finding"}
_HOURS_IN = {"hour": 1.0, "day": 24.0, "week": 168.0, "month": 730.5, "year": 8766.0, "minute": 1 / 60}
RESTORATION_NOTE = "As new: restoring it only partly (Kijima) comes with a later library release."

#: The diagram's own settings for a tree-linked block, by what its task does.
SETTINGS = {
    "age": ("opportunity",),
    "block": (),
    "condition": ("threshold", "cost", "duration"),
    "test": ("offset", "coverage", "full_test"),
}


def _hours_per(unit: str | None) -> float | None:
    """Hours in one of ``unit`` (a calendar or clock unit), or None (cycles, km, ...)."""
    from backend.units import normalize_unit

    return _HOURS_IN.get(normalize_unit(unit or "") or "")


def _tidy(v: float | None) -> float | None:
    return None if v is None else float(f"{v:.6g}")


def task_kind(m: Maintenance, task: dict) -> str | None:
    """What the task does, as an RCM decision says it: its own outcome (a task a decision made, or
    one added with a kind), else the decision of a failure mode it serves (its member in a
    combination). None for routine work with no kind."""
    if task.get("outcome") in _ORDER:
        return task["outcome"]
    for fm in m.s.out(m.org, task["id"], "MITIGATES"):
        for o in fm.get("outcomes") or []:
            if o.get("task_id") == task["id"] and o.get("outcome") in _ORDER:
                return o["outcome"]
        if not fm.get("outcomes") and fm.get("outcome") in _ORDER:
            return fm["outcome"]
    return None


def _crew_words(view: dict) -> str:
    """Who does it, from its LSA: "Fitter ×2 · 3 h of labour"."""
    r = view.get("resources") or {}
    trades = []
    for line in r.get("labour") or []:
        trade = line.get("trade") or view.get("trade") or "no trade"
        people = int(line.get("people") or 1)
        trades.append(f"{trade} ×{people}" if people > 1 else trade)
    if not trades and view.get("trade"):
        trades.append(view["trade"])
    if not trades:
        return ""
    hours = r.get("labour_hours") or 0
    return " · ".join([", ".join(dict.fromkeys(trades))] + ([f"{hours:g} h of labour"] if hours else []))


def task_plan(m: Maintenance, view: dict, unit: str) -> dict:
    """What one task gives a block in a diagram whose clock is ``unit``.

    ``view``: the task as read (Maintenance._task_view). Returns {id, name, kind, kind_words,
    modelled (it has an RCM kind), plan: {task: age|block|condition|test, interval,
    operating_interval, duration, cost, inspection_cost, group} or None, interval_words, crew,
    package, flags (what's blank, in words), notes}."""
    task = m.s.node(m.org, view["id"], "Task") or {}
    kind = task_kind(m, task)
    every, every_unit = view.get("interval"), view.get("unit") or ""
    words = f"every {every:g} {every_unit}" if isinstance(every, (int, float)) else "no interval"
    entry = m._package_index().get(view["id"])
    out = {"id": view["id"], "name": view["name"], "kind": kind, "kind_words": _KIND_WORDS.get(kind, "Routine work"),
           "modelled": kind is not None, "interval_words": words, "crew": _crew_words(view),
           "package": {"id": entry["package"]["id"], "name": entry["package"].get("name")} if entry else None,
           "flags": [], "notes": [], "plan": None}
    if kind is None:
        out["notes"].append(f"“{view['name']}” is routine work with no RCM kind (replace, inspect on condition or "
                            "proof test), so what it does to the block's life isn't known: it isn't modelled.")
        return out
    plan_task = _PLAN_TASK.get(kind, "age")
    group = None
    if entry:
        root = entry["root"]
        if kind == "fixed_interval" and root.get("timing") == "fixed":
            plan_task = "block"
        if plan_task == "test":
            out["notes"].append(f"It's in the package “{entry['package'].get('name')}”, but a proof-tested block "
                                "can't be in a maintenance group (nobody knows it has failed when the group stops).")
        else:
            group = root.get("name") or entry["package"].get("name")
    plan: dict = {"task": plan_task, "interval": None, "operating_interval": None, "duration": None, "cost": None,
                  "inspection_cost": None, "group": group}
    diagram_h, every_h = _hours_per(unit), _hours_per(every_unit)
    if diagram_h is None:
        out["flags"].append(f"The diagram's clock ({unit or 'no unit'}) isn't a time, so {words} can't be put on it.")
    elif every_h is None:
        out["flags"].append(f"{words.capitalize()} counts {every_unit}, which the diagram's clock can't take.")
    elif view.get("by_use"):
        if plan_task == "test":
            out["flags"].append(f"A proof test {words} of running time can't be modelled yet: give the task a "
                                "calendar interval.")
        else:  # running hours: the block's duty turns them into calendar time
            plan["operating_interval"] = _tidy(every * every_h / diagram_h)
    else:
        plan["interval"] = _tidy(every * every_h / diagram_h)
    if view.get("also_interval"):
        out["notes"].append(f"It's also due every {view['also_interval']:g} {view.get('also_unit') or ''}, "
                            "whichever comes first: only the first limit is modelled.")
    r = view.get("resources") or {}
    off = (r.get("access") or {}).get("downtime_hours")
    if off is None:
        off = r.get("duration_hours")
    cost_view = view.get("cost") or {}
    cost = cost_view.get("amount")
    if plan_task == "condition":
        plan["inspection_cost"] = cost  # the task is the inspection; the replacement is set on the RBD
    else:
        if off is not None and diagram_h is not None and off:
            plan["duration"] = _tidy(float(off) / diagram_h)
        if off is None:
            out["flags"].append("No time off-line on its LSA, so it doesn't take the block down. Set the downtime "
                                "or duration on the task's LSA if it does.")
        plan["cost"] = cost
        if cost is None:
            out["flags"].append("No cost: type one on the task, or price its LSA.")
    lsa = cost_view.get("lsa") or {}
    if cost is not None and cost_view.get("source") == "lsa" and not lsa.get("complete"):
        missing = [*(lsa.get("missing_rates") or []), *(lsa.get("missing_prices") or [])]
        out["flags"].append(f"Its cost is partial: nothing prices {', '.join(missing[:4])}"
                            f"{' …' if len(missing) > 4 else ''}.")
    out["plan"] = plan
    return out


def position_plan(m: Maintenance, position: dict, unit: str) -> dict:
    """A position's plan for the block standing for it: {position {id, name}, tasks: [task_plan],
    used (the task modelled, or None: runs to failure), restoration, flags, notes}."""
    plans = [task_plan(m, m._task_view(t), unit) for t in m._tasks_on(position["id"])]
    plans.sort(key=lambda x: (_ORDER.get(x["kind"], 9), str(x["name"]).lower(), x["id"]))
    modelled = [x for x in plans if x["modelled"]]
    used = modelled[0] if modelled else None
    notes = [n for x in plans for n in x["notes"]]
    if len(modelled) > 1:
        notes.append(f"{position['name']} has {len(modelled)} tasks; a block takes one today, so "
                     f"“{used['name']}” is modelled and the others aren't.")
    for x in plans:
        x["used"] = used is not None and x["id"] == used["id"]
    return {"position": {"id": position["id"], "name": position.get("name") or ""}, "tasks": plans,
            "used": used["id"] if used else None, "plan": used["plan"] if used else None,
            "restoration": ({"kind": "as_new", "note": RESTORATION_NOTE}
                            if used and used["plan"]["task"] != "test" else None),
            "flags": list(used["flags"]) if used else [], "notes": notes}


def _children(m: Maintenance, position_id: str) -> list[dict]:
    return [c for c in m.s.inn(m.org, position_id, "PART_OF") if c["label"] == "Position" and not c.get("retired")]


def _below(m: Maintenance, position_id: str, depth: int = 6) -> list[dict]:
    """The live positions further inside ``position_id`` than its children (grandchildren on)."""
    out, level = [], _children(m, position_id)
    for _ in range(depth - 1):
        level = [g for c in level for g in _children(m, c["id"])]
        if not level:
            break
        out += level
    return out


def block_positions(m: Maintenance, position_id: str, blocks: list[dict]) -> dict:
    """{block id: position} for the diagram's blocks that stand for a position inside
    ``position_id`` (or for that position itself): a block built from it (its id), else one with
    the position's name. A block built from a position further inside (a sub-system's block, once
    the sub-system is expanded into the diagram) is matched by its id."""
    from backend.maintenance import rbd_derive

    me = m.s.node(m.org, position_id, "Position")
    # A position's own one-block diagram (New blank RBD, one block for itself) reads its own tasks.
    kids = _children(m, position_id) + ([me] if me else [])
    by_bid = {rbd_derive._bid(c["id"]): c for c in _below(m, position_id)} | {rbd_derive._bid(c["id"]): c for c in kids}
    by_name: dict = {}
    for c in kids:
        by_name.setdefault(" ".join(str(c.get("name") or "").split()).casefold(), c)
    out, taken = {}, set()
    for b in blocks:
        c = by_bid.get(b.get("id")) or by_name.get(" ".join(str(b.get("label") or "").split()).casefold())
        if c is not None and c["id"] not in taken:
            out[b["id"]] = c
            taken.add(c["id"])
    return out


def positions_of_rbd(m: Maintenance, rbd_id: str) -> list[dict]:
    """The positions an RBD is linked to (its built row first), as {id, name, built}."""
    rows = [x for x in m.all_position_models() if x.get("model_type") == "rbd" and x.get("model_id") == rbd_id]
    rows.sort(key=lambda x: ((x.get("source") or {}).get("built_from") is None, not x.get("in_use")))
    out, seen = [], set()
    for x in rows:
        if x["position_id"] in seen:
            continue
        seen.add(x["position_id"])
        p = m.s.node(m.org, x["position_id"], "Position") or {}
        out.append({"id": x["position_id"], "name": p.get("name") or "",
                    "built": (x.get("source") or {}).get("built_from") is not None})
    return out


def _component_blocks(graph: dict) -> list[dict]:
    """The diagram's own component blocks (a repeated block is its original's unit)."""
    return [{"id": n.get("id"), "label": (n.get("data") or {}).get("label") or "", "data": n.get("data") or {}}
            for n in (graph or {}).get("nodes") or []
            if isinstance(n, dict) and n.get("type") == "component" and not (n.get("data") or {}).get("repeat_of")]


def plans_for_graph(m: Maintenance, rbd_id: str, graph: dict) -> dict:
    """{position: {id, name} | None, blocks: {block id: position_plan + repair_missing}} for a
    diagram saved as ``rbd_id`` (as it stands in ``graph``: unsaved edits included)."""
    positions = positions_of_rbd(m, rbd_id)
    if not positions:
        return {"position": None, "positions": [], "unit": (graph or {}).get("unit") or "", "blocks": {}}
    top = positions[0]
    unit = (graph or {}).get("unit") or ""
    blocks = _component_blocks(graph)
    mapped = block_positions(m, top["id"], blocks)
    out = {}
    for b in blocks:
        c = mapped.get(b["id"])
        if c is None:
            continue
        row = position_plan(m, c, unit)
        if not (b["data"].get("repair") or b["data"].get("instant_repair")):
            row["repair_missing"] = (f"No repair time: neither {c['name']}'s history nor its class holds one. Set "
                                     "the block's repair time; nothing is assumed.")
        out[b["id"]] = row
    return {"position": {"id": top["id"], "name": top["name"]}, "positions": positions, "unit": unit, "blocks": out}


def merge(data: dict, row: dict) -> dict:
    """A tree-linked block's data for calculation: its own plan replaced by its position's task
    (none: it runs to failure), with the diagram's own settings for it (``tree_settings``), and
    ``tree_plan`` naming where it came from. The same rule as frontend/src/rbdTreePlan.js.

    ``tree_settings`` stays on the result, so merging again gives the same data: the browser sends
    the diagram as it calculates it (already merged), and the server reads the tree once more.
    Dropping them there lost every on-condition, proof-test and early-renewal setting."""
    out = {k: v for k, v in copy.deepcopy(data or {}).items() if k not in ("preventive", "inspection")}
    plan = (row or {}).get("plan")
    out["tree_plan"] = {"position_id": row["position"]["id"], "task_id": row.get("used")}
    if not plan:
        return out
    own = {k: v for k, v in ((data or {}).get("tree_settings") or {}).items() if k in SETTINGS[plan["task"]]
           and v not in (None, "")}
    pick = lambda d: {k: v for k, v in d.items() if v not in (None, "")}  # noqa: E731
    if plan["task"] == "test":
        out["inspection"] = pick({"interval": plan["interval"], "duration": plan["duration"], "cost": plan["cost"],
                                  **own})
        out.pop("maintenance_group", None)
        return out
    pm = {"policy": plan["task"], "interval": plan["interval"], "operating_interval": plan["operating_interval"]}
    if plan["task"] == "condition":
        pm.update(inspection_cost=plan["inspection_cost"])
        pm.update(own)
    else:
        pm.update(duration=plan["duration"], cost=plan["cost"], **own)
    out["preventive"] = pick(pm)
    if plan.get("group"):
        out["maintenance_group"] = plan["group"]
    return out


def apply(graph: dict, plans: dict) -> dict:
    """The diagram with every tree-linked block's plan read from its position (:func:`merge`);
    the rest as drawn. ``plans``: :func:`plans_for_graph`."""
    rows = (plans or {}).get("blocks") or {}
    if not rows:
        return graph
    nodes = []
    for n in (graph or {}).get("nodes") or []:
        row = rows.get(n.get("id")) if isinstance(n, dict) else None
        nodes.append({**n, "data": merge(n.get("data") or {}, row)} if row else n)
    return {**graph, "nodes": nodes}


def fingerprint(plans: dict) -> dict:
    """{task id: version} of the tasks a calculation used: a hash of what each gave its block."""
    out = {}
    for row in ((plans or {}).get("blocks") or {}).values():
        for t in row.get("tasks") or []:
            if t.get("used"):
                blob = json.dumps({"plan": t.get("plan"), "name": t.get("name")}, sort_keys=True, default=str)
                out[t["id"]] = hashlib.sha1(blob.encode()).hexdigest()[:12]
    return out


def changed_tasks(used: dict | None, now: dict | None, names: dict | None = None) -> list[str]:
    """The tasks whose version differs between a saved calculation's and now's (names where
    known): one used then and gone or changed, or one used now and not then."""
    used, now = used or {}, now or {}
    ids = sorted({k for k in used if used.get(k) != now.get(k)} | {k for k in now if k not in used})
    return [(names or {}).get(i) or i for i in ids]


def maintenance_for(ctx) -> Maintenance | None:
    """The caller's Maintenance workspace, or None where they can't use it (it's off, or not for
    them): their diagrams are then calculated as drawn."""
    from fastapi import HTTPException

    try:
        from backend.routers.maintenance import maintenance

        return maintenance(ctx)
    except HTTPException:
        return None
    except Exception:  # noqa: BLE001 - a diagram is never kept from calculating by the tree
        import logging

        logging.getLogger(__name__).exception("Couldn't open the maintenance workspace for an RBD's plan")
        return None


def for_saved_rbd(ctx, rbd, graph: dict) -> tuple[dict, dict | None]:
    """(graph with the tree's plans, plans) for a saved repairable diagram; (graph, None) where
    there's no tree to read (no maintenance, no linked position, no tree-linked block)."""
    if rbd is None or not (graph or {}).get("repairable"):
        return graph, None
    m = maintenance_for(ctx)
    if m is None:
        return graph, None
    plans = plans_for_graph(m, rbd.id, graph)
    if not plans["blocks"]:
        return graph, None
    return apply(graph, plans), plans


def task_names(plans: dict | None) -> dict:
    return {t["id"]: t["name"] for row in ((plans or {}).get("blocks") or {}).values() for t in row.get("tasks") or []}


def _last_calculation(doc: dict) -> dict | None:
    """An RBD's last saved availability calculation: {availability, cost_rate, unit, at}."""
    entry = (doc or {}).get("availability_cache") or {}
    res = entry.get("result") or {}
    a = res.get("steady_state_availability")
    cost = (res.get("costs") or {}).get("cost_rate") if isinstance(res.get("costs"), dict) else None
    if a is None and cost is None:
        return None
    return {"availability": a, "cost_rate": cost, "unit": res.get("unit") or "", "at": entry.get("computed_at")}


def rbds_using_tasks(m: Maintenance, db, owners, hidden, task_ids) -> list[dict]:
    """The RBDs whose plans read these tasks: [{rbd {id, name, unit}, block {id, label}, position
    {id, name}, task {id, name}, used (modelled there; false: another of the position's tasks is),
    last (the RBD's last saved availability calculation, if any), outdated (that calculation used
    an older version of the task)}]. For the Maintenance tab."""
    from backend.maintenance.position_models import fetcher

    wanted = [str(t) for t in (task_ids or []) if t][:500]
    if not wanted:
        return []
    fetch = fetcher(db, owners, hidden)
    by_parent: dict = {}
    for tid in wanted:
        task = m.s.node(m.org, tid, "Task")
        if task is None or task.get("retired"):
            continue
        on = [x for x in m.s.out(m.org, tid, "ON") if x["label"] == "Position"]
        if not on:
            continue
        # The positions above it, nearest first: a diagram on any of them may hold its block (a
        # sub-system expanded into its parent's diagram puts a grandchild's block there).
        here = on[0]["id"]
        for _ in range(6):
            up = [x for x in m.s.out(m.org, here, "PART_OF") if x["label"] == "Position"]
            if not up:
                break
            here = up[0]["id"]
            by_parent.setdefault(here, set()).add(tid)
    out = []
    for parent_id, tids in by_parent.items():
        for link in m.position_models(parent_id):
            if link.get("model_type") != "rbd":
                continue
            doc = fetch("rbd", link["model_id"])
            if doc is None or not (doc.graph or {}).get("repairable"):
                continue
            # A diagram linked to several positions reads its first (built) one.
            if (positions_of_rbd(m, doc.id) or [{}])[0].get("id") != parent_id:
                continue
            plans = plans_for_graph(m, doc.id, doc.graph or {})
            raw = db.rbds.find_one({"_id": doc.id}, {"availability_cache": 1, "tree_tasks": 1}) or {}
            last = _last_calculation(raw)
            saved = raw.get("tree_tasks") or {}
            stale = set()
            if last and saved.get("key") == (raw.get("availability_cache") or {}).get("key"):
                now = fingerprint(plans)
                stale = {k for k in set(saved.get("tasks") or {}) | set(now)
                         if (saved.get("tasks") or {}).get(k) != now.get(k)}
            for block_id, row in plans["blocks"].items():
                label = next((b["label"] for b in _component_blocks(doc.graph or {}) if b["id"] == block_id), block_id)
                for t in row["tasks"]:
                    if t["id"] not in tids:
                        continue
                    out.append({"rbd": {"id": doc.id, "name": doc.name, "unit": (doc.graph or {}).get("unit") or ""},
                                "block": {"id": block_id, "label": label}, "position": row["position"],
                                "task": {"id": t["id"], "name": t["name"]}, "used": bool(t.get("used")),
                                "last": last, "outdated": bool(last) and t["id"] in stale})
    out.sort(key=lambda r: (r["rbd"]["name"].lower(), r["block"]["label"].lower(), r["task"]["name"].lower()))
    return out
