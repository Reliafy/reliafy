"""A repairable RBD's maintenance plan, read from the tree (Nov 2026).

Derryn: "The RBD maintenance plan needs to come from the Explorer maintenance tasks. It can't be
the other way around." So for a block that stands for a position (an RBD built from, or linked
to, the position the block's position sits inside), the position's tasks on the Explorer's
Maintenance tab are the one source of its planned work. Nothing is copied into the diagram: the
plan is read from the tasks each time the diagram is shown or calculated, and a block with no
tasks there runs to failure. A block drawn by hand (no position) keeps its own plan, edited in
the RBD as before.

What a task gives the block (an RCM decision says *what* a task does; its LSA says *how*):

* what it does, from its RCM kind: ``fixed_interval`` -> replace at age, counted from the last
  replacement as the work orders count it (at fixed times when its package visits on fixed dates);
  ``on_condition`` -> inspect on condition; ``failure_finding`` -> proof test. Routine work with no
  kind isn't modelled (what it does to the block's life isn't known), and the plan says so;
* how often: its interval on the calendar, or in running hours (turned into calendar time by the
  block's duty), in the diagram's unit;
* how long it takes the block off-line: its LSA's downtime, else its elapsed time;
* what it costs each time (task_costs.py); its package (the block's maintenance group); who does
  it (the LSA's labour, in words: the RBD's crews are one pool);
* what it leaves the block as (restoration.py): as new, or restored partly (Kijima I or II with a
  restoration factor q), with every Nth task a full replacement; set on the task or its RCM
  decision. Several decisions disagreeing: the least restoring, flagged;
* whether it's counted in running hours (its unit is a meter's, or ``basis`` operating): then
  the block's duty puts it on the calendar;
* a shutdown it's done at (its work package is a shutdown, shutdowns.py), and "only if older than".

What the installed RePyability can't take yet (:data:`SUPPORTS`, found by capability) is never
dropped silently: the plan computes with what it can (as new, no shutdowns) and each such task
says :data:`PENDING`. The duty a position's running-hours meter suggests is proposed beside the
block's own ("Runs X% of the time"), never applied.

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
_KIND_WORDS = {"fixed_interval": "Replace at age", "on_condition": "On condition", "failure_finding": "Failure finding"}
_HOURS_IN = {"hour": 1.0, "day": 24.0, "week": 168.0, "month": 730.5, "year": 8766.0, "minute": 1 / 60}
RESTORATION_NOTE = "As new: the task renews it."
#: What a saved task says while the library can't use it in results yet.
PENDING = "Saved — used in results once the next library update is in."
#: The app passes shutdowns to the library only once the diagram builder and the cost categories
#: take them (the library adoption step); until then they're shown, saved and pending.
_APP_TAKES_SHUTDOWNS = False


def supports() -> dict:
    """What the plan can use in results now: {restoration: [kinds], shutdowns: bool}."""
    from backend.services import repy_compat

    lib = repy_compat.plan_supports()
    return {"restoration": ["as_new", "kijima1", "kijima2"] if lib["restoration"] else ["as_new"],
            "shutdowns": bool(lib["shutdowns"] and _APP_TAKES_SHUTDOWNS)}

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


def task_plan(m: Maintenance, view: dict, unit: str, can: dict | None = None) -> dict:
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
           "flags": [], "notes": [], "pending": [], "plan": None, "restoration": None,
           "basis": view.get("basis") or "calendar"}
    can = can or supports()
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
            out["kind_words"] = "Replace at fixed times (its package's dates)"
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
    elif view.get("by_use") or view.get("basis") == "operating":
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
    if plan_task in ("age", "block"):
        _restoration_into(out, plan, view.get("restoration") or {}, can)
    out["plan"] = plan
    return out


def _restoration_into(out: dict, plan: dict, r: dict, can: dict) -> None:
    """What a fixed-interval task leaves the block as, into its row and (when the library takes
    it) its plan in RePyability's shape: ``restoration`` {model, q}, ``replace_every``,
    ``replacement_cost`` (none given: 0, flagged)."""
    from backend.maintenance import restoration as rs

    value = r.get("restoration")
    out["restoration"] = {"kind": (value or {}).get("kind") or "as_new", "q": (value or {}).get("q"),
                          "replace_every": (value or {}).get("replace_every"),
                          "replacement_cost": (value or {}).get("replacement_cost"),
                          "words": rs.words(value), "source": r.get("source")}
    if r.get("conflict"):
        out["flags"].append(r["conflict"])
    if not value:
        return
    if value["kind"] not in can["restoration"]:
        out["pending"].append(f"{rs.words(value)}. {PENDING} Until then it's calculated as new.")
        return
    plan["restoration"] = {"model": value["kind"], "q": value["q"]}
    if value.get("replace_every"):
        plan["replace_every"] = value["replace_every"]
        plan["replacement_cost"] = value.get("replacement_cost") or 0.0
        if value.get("replacement_cost") is None:
            out["flags"].append("No replacement cost: every replacement is charged nothing until a price is set "
                                "on the task.")


def _duty_proposal(m: Maintenance, position: dict) -> dict | None:
    """The share of the time the position runs, from its running-hours meter (or its fitted
    item's): running hours a calendar hour over the last year of readings. A proposal
    beside the block's own duty, never applied."""
    from backend.maintenance import service as sv

    holders = [position]
    fitted = m.current_fitment(position["id"])
    item = fitted and m.s.inn(m.org, fitted["id"], "IN")
    if item:
        holders.append(item[0])
    for holder in holders:
        point = sv._counter_on(m.s, m.org, holder["id"], "hours")
        if point is None:
            continue
        readings = sv._readings(m.s, m.org, point, m.tz)
        rate = sv._rate(readings)
        if not rate or rate <= 0:
            continue
        duty = min(rate / 24.0, 1.0)
        pct = float(f"{duty * 100:.3g}")
        return {"duty": round(duty, 4), "percent": pct, "words": f"Runs {pct:g}% of the time",
                "point": {"id": point["id"], "name": point.get("name") or ""},
                "basis": f"from {point.get('name') or 'its running-hours meter'} over the last year of readings",
                "since": readings[0]["on"] if readings else None, "to": readings[-1]["on"] if readings else None}
    return None


def position_plan(m: Maintenance, position: dict, unit: str, can: dict | None = None) -> dict:
    """A position's plan for the block standing for it: {position {id, name}, tasks: [task_plan],
    used (the task modelled, or None: runs to failure), restoration, flags, notes}."""
    can = can or supports()
    plans = [task_plan(m, m._task_view(t), unit, can) for t in m._tasks_on(position["id"])]
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
            "restoration": (({**used["restoration"], "note": used["restoration"]["words"]} if used["restoration"]
                             else {"kind": "as_new", "words": "As new", "note": RESTORATION_NOTE})
                            if used and used["plan"]["task"] != "test" else None),
            "flags": list(used["flags"]) if used else [], "notes": notes,
            "pending": list(used["pending"]) if used else [], "duty_proposal": _duty_proposal(m, position)}


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
        source = x.get("source") or {}
        out.append({"id": x["position_id"], "name": p.get("name") or "",
                    "built": source.get("built_from") is not None,
                    "built_ids": [str(i) for i in source.get("position_ids") or []]})
    return out


def gone_blocks(m: Maintenance, top_id: str, graph: dict, built_ids) -> list[dict]:
    """The diagram's blocks built from a position that has since been deleted, or moved out of
    ``top_id``: [{id, label, position: {id, name}, why: "deleted" | "moved"}]. A rebuild keeps them
    (every edit to a diagram is kept), so they're named rather than silently left standing."""
    from backend.maintenance import rbd_derive

    live = {c["id"] for c in _children(m, top_id)} | {c["id"] for c in _below(m, top_id)}
    by_bid = {rbd_derive._bid(pid): pid for pid in built_ids or [] if pid not in live}
    if not by_bid:
        return []
    out = []
    for b in _component_blocks(graph):
        pid = by_bid.get(b["id"])
        if pid is None:
            continue
        node = m.s.node(m.org, pid, "Position") or {}
        out.append({"id": b["id"], "label": b["label"] or node.get("name") or "",
                    "position": {"id": pid, "name": node.get("name") or ""},
                    "why": "deleted" if not node or node.get("retired") else "moved"})
    return out


def gone_note(gone: list[dict], top_name: str) -> str | None:
    """One sentence naming blocks whose positions have gone (gone_blocks), or None."""
    if not gone:
        return None
    names = ", ".join(f"“{g['label']}”" for g in gone[:8]) + (" …" if len(gone) > 8 else "")
    one = len(gone) == 1
    return (f"{names} {'stands' if one else 'stand'} for {'a position' if one else 'positions'} no longer inside "
            f"{top_name} (deleted or moved): {'it was' if one else 'they were'} kept in the diagram. Delete "
            f"{'the block' if one else 'those blocks'} from the RBD if {'it has' if one else 'they have'} gone.")


def _component_blocks(graph: dict) -> list[dict]:
    """The diagram's own component blocks (a repeated block is its original's unit)."""
    return [{"id": n.get("id"), "label": (n.get("data") or {}).get("label") or "", "data": n.get("data") or {}}
            for n in (graph or {}).get("nodes") or []
            if isinstance(n, dict) and n.get("type") == "component" and not (n.get("data") or {}).get("repeat_of")]


def plans_for_graph(m: Maintenance, rbd_id: str, graph: dict) -> dict:
    """{position: {id, name} | None, blocks: {block id: position_plan + repair_missing}} for a
    diagram saved as ``rbd_id`` (as it stands in ``graph``: unsaved edits included)."""
    can = supports()
    positions = positions_of_rbd(m, rbd_id)
    if not positions:
        return {"position": None, "positions": [], "unit": (graph or {}).get("unit") or "", "blocks": {},
                "shutdowns": [], "supports": can, "gone": []}
    top = positions[0]
    unit = (graph or {}).get("unit") or ""
    blocks = _component_blocks(graph)
    mapped = block_positions(m, top["id"], blocks)
    out = {}
    for b in blocks:
        c = mapped.get(b["id"])
        if c is None:
            continue
        row = position_plan(m, c, unit, can)
        if not (b["data"].get("repair") or b["data"].get("instant_repair")):
            row["repair_missing"] = (f"No repair time: neither {c['name']}'s history nor its class holds one. Set "
                                     "the block's repair time; nothing is assumed.")
        out[b["id"]] = row
    shuts = _shutdowns(m, top, unit, blocks, mapped, out, can)
    gone = gone_blocks(m, top["id"], graph, top.get("built_ids"))
    return {"position": {"id": top["id"], "name": top["name"]}, "positions": positions, "unit": unit, "blocks": out,
            "shutdowns": shuts, "supports": can, "gone": gone}


def _shutdowns(m: Maintenance, top: dict, unit: str, blocks: list[dict], mapped: dict, rows: dict,
               can: dict) -> list[dict]:
    """The shutdown packages on the diagram's position or inside it, each in RePyability's
    shape (``spec``: period and offset, or times; duration, scope, cost, idle_ageing, in the
    diagram's unit), and the blocks whose task is done at it bound to it (``"shutdown"``,
    ``"older_than"`` in their plan) when the library takes shutdowns; else each says PENDING."""
    from datetime import date

    from backend.maintenance import shutdowns as sd_words

    found = m.shutdowns_for(top["id"])
    if not found:
        return []
    diagram_h = _hours_per(unit)
    label = {b["id"]: b["label"] for b in blocks}
    by_position = {c["id"]: bid for bid, c in mapped.items()}
    out, names = [], set()
    for x in found:
        sd, pkg = x["shutdown"], x["package"]
        name = pkg["name"] if pkg["name"] not in names else f"{pkg['name']} ({pkg['id'][:6]})"
        names.add(name)
        row = {"name": name, "package": {"id": pkg["id"], "name": pkg["name"]}, "position": x["position"],
               "when": ("on " + ", ".join(sd["dates"][:4]) + (" …" if len(sd["dates"]) > 4 else "")
                        if sd.get("dates") else pkg["cadence"]),
               "next": x["next"], "words": sd_words.words(sd), "duration_hours": sd["duration_hours"],
               "cost": sd.get("cost"), "idle_ageing": sd.get("idle_ageing", True), "blocks": [], "scope": None,
               "flags": [], "pending": None, "spec": None}
        # What it takes down: the diagram's position (the whole system), else the blocks standing
        # for the positions in its scope (its package's position by default) or inside them.
        scope_ids = sd.get("scope") or [x["position"]["id"]]
        if scope_ids == [top["id"]]:
            scope_blocks = None
        else:
            inside = set(scope_ids)
            for pid in scope_ids:
                inside |= {p["id"] for p in m._positions_inside(pid)}
            scope_blocks = [bid for pid, bid in by_position.items() if pid in inside]
            row["scope"] = [{"id": bid, "label": label.get(bid, bid)} for bid in scope_blocks]
            if not scope_blocks:
                row["flags"].append("None of the positions it takes down is a block in this diagram.")
        tasks = set(x["tasks"])
        for bid, r in rows.items():
            if r.get("used") in tasks and r.get("plan") and r["plan"]["task"] in ("age", "block"):
                used = next(t for t in r["tasks"] if t["id"] == r["used"])
                older = (m.s.node(m.org, used["id"], "Task") or {}).get("older_than")
                older_d = None
                if older and diagram_h:
                    older_d = _tidy(older["value"] * _HOURS_IN[older["unit"].rstrip("s")] / diagram_h)
                row["blocks"].append({"id": bid, "label": label.get(bid, bid), "task": used["name"],
                                      "older_than": older})
                if scope_blocks is not None and bid not in scope_blocks:
                    row["flags"].append(f"{label.get(bid, bid)}'s task is done at it, but it isn't in what it "
                                        "takes down.")
                if can["shutdowns"]:
                    r["plan"]["shutdown"] = name
                    if older_d is not None:
                        r["plan"]["older_than"] = older_d
                else:
                    said = (f"Done at the shutdown “{name}”"
                            + (f", only if older than {older['value']:g} {older['unit']}" if older else "")
                            + f". {PENDING} Until then it's calculated on its own interval.")
                    r["pending"].append(said)
                    used["pending"].append(said)
        if diagram_h is None:
            row["flags"].append(f"The diagram's clock ({unit or 'no unit'}) isn't a time, so the shutdown can't be "
                                "put on it.")
        else:
            spec: dict = {"duration": _tidy(sd["duration_hours"] / diagram_h), "scope": scope_blocks,
                          "idle_ageing": sd.get("idle_ageing", True)}
            if sd.get("cost") is not None:
                spec["cost"] = sd["cost"]
            today = date.fromisoformat(x["today"])
            if sd.get("dates"):
                spec["times"] = [_tidy((date.fromisoformat(d) - today).days * 24 / diagram_h)
                                 for d in sd["dates"] if d >= x["today"]]
            else:
                period_h = pkg["every"] * _HOURS_IN[str(pkg["unit"]).rstrip("s")]
                spec["period"] = _tidy(period_h / diagram_h)
                first = (date.fromisoformat(x["next"]) - today).days * 24 if x["next"] else 0
                spec["offset"] = _tidy((first % period_h) / diagram_h)
            row["spec"] = spec
        if not can["shutdowns"]:
            row["pending"] = PENDING
        out.append(row)
    return out


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
    # What the library takes only once it supports it (task_plan puts these in the plan only then).
    for key in ("restoration", "replace_every", "replacement_cost", "shutdown", "older_than"):
        if plan.get(key) is not None:
            pm[key] = plan[key]
    if plan.get("shutdown") is not None:  # the shut gives its calendar and how long it takes
        for key in ("interval", "operating_interval", "duration", "opportunity"):
            pm.pop(key, None)
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
    if ((plans or {}).get("supports") or {}).get("shutdowns") and plans.get("shutdowns"):
        graph = {**graph, "shutdowns": {s["name"]: s["spec"] for s in plans["shutdowns"] if s.get("spec")}}
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
                # What it leaves the block as and its shutdown are in the version too, so a saved
                # calculation says when they changed (even while they're pending).
                blob = json.dumps({"plan": t.get("plan"), "name": t.get("name"),
                                   **({"restoration": t["restoration"]}
                                      if (t.get("restoration") or {}).get("kind") not in (None, "as_new") else {}),
                                   **({"pending": t["pending"]} if t.get("pending") else {})},
                                  sort_keys=True, default=str)
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
