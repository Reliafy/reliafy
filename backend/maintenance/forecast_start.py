"""What the quick forecast tool (Decisions › Forecasts: Spares, Hours and Cost forecast) and Optimal
replacement take from a node in the Explorer (Derryn, 23 Nov 2026: "Open in ›"), so they open filled
in: a position and everything below it, one task, or a work package. Only what's recorded:

- the model: the non-repairable model in use on the positions there (the one most of them use);
- the units: those positions, each with its fitted item's age in the model's unit (block_age:
  its counter, or the calendar since fitting; never an age assumed from running all day);
- hours a day from the duty in Operations (none: left for the analyst to type);
- a task's interval as the planned replacement age (in the model's unit only), its labour hours
  and its cost each time; a failure's cost from the failure mode or the position class.

Nothing is written. ``from`` names where it came from, with a link back to the Explorer."""

from __future__ import annotations

from collections import Counter

from backend.maintenance.rcm_decisions import norm_unit
from backend.services import running_clock


def _path(m, node_id: str, root: str | None) -> str:
    """"Mower 3 › Deck": the way down from the asset opened (``root``) to the node."""
    ids = [node_id]
    for a in m._ancestor_ids(node_id):
        ids.append(a)
        if a == root:
            break
    names = [(m.s.node(m.org, i) or {}).get("name") or "" for i in reversed(ids)]
    return " › ".join(x for x in names if x)


def _explorer_link(node_id: str, root: str | None, tab: str = "maintenance", sel: str | None = None) -> str:
    from urllib.parse import urlencode

    q = {"arrange": "positions", "tab": tab, "sel": sel or node_id}
    if root:
        q["root"] = root
    return f"/asset-register/explorer?{urlencode(q)}"


def forecast_start(m, fetch, positions: list[str], tasks: list[dict], root: str | None, node: dict) -> dict:
    """The prefill from ``positions`` (ids, the node's and everything below it) and ``tasks`` (the
    raw tasks the node holds); ``node`` {kind, id, name, sel}: what it came from."""
    from backend.maintenance import rbd_tree_plan

    out = {"from": {**node, "path": _path(m, node["position_id"], root) if node.get("position_id") else node.get("name", ""),
                    "link": _explorer_link(node.get("position_id") or node["id"], root, sel=node.get("sel"))},
           "model": None, "units": None, "ages": [], "hours_per_day": None, "duty": None, "replace_at": None,
           "interval": None, "planned_cost": None, "planned_hours": None, "failure_cost": None, "task": None,
           "notes": []}
    links = [x for x in m.all_position_models(positions) if x.get("model_type") == "model" and x.get("in_use")]
    if not links:
        links = [x for x in m.all_position_models(positions) if x.get("model_type") == "model"]
    count = Counter(x["model_id"] for x in links)
    doc, unit = None, ""
    for model_id, _n in count.most_common():
        doc = fetch("model", model_id)
        if doc is not None:
            break
    if doc is not None:
        results = getattr(doc, "results", None) or {}
        unit = results.get("unit") or ""
        out["model"] = {"id": doc.id, "name": getattr(doc, "name", "") or "", "unit": unit}
        if len(count) > 1:
            out["notes"].append(f"{len(count)} models are in use here: {out['model']['name'] or 'the most used one'} "
                                "is filled in. Pick another if you need to.")
        using = sorted({x["position_id"] for x in links if x["model_id"] == doc.id})
        ages, missing = [], 0
        for pid in using:
            p = m.s.node(m.org, pid)
            got = rbd_tree_plan.block_age(m, p, unit) if p is not None and unit else {"reason": "no unit"}
            if "age" in got and got.get("basis") != "continuous":
                ages.append(round(float(got["age"]), 4))
            else:
                missing += 1
        out["units"] = len(using)
        out["ages"] = ages
        if missing:
            out["notes"].append(f"{missing} of the {len(using)} positions using it have no age to read (nothing fitted, "
                                "or no counter readings): enter their ages.")
        # What one failure costs there (the failure mode's figure, else the position class's).
        if using:
            try:
                cons = m.failure_consequence(m.s.node(m.org, using[0]))
                out["failure_cost"] = cons.get("per_failure")
            except Exception:  # noqa: BLE001 - a figure we can't read is left for the analyst
                pass
    else:
        out["notes"].append("No non-repairable model on the positions here: pick one, or type its parameters.")
    clock_at = (positions or [None])[0]
    clock = running_clock.for_position(m, clock_at, root) if clock_at else None
    if clock is not None and clock.basis == "duty" and clock.hours_per_day > 0:
        out["hours_per_day"] = round(clock.hours_per_day, 4)
        out["duty"] = clock.plan or "its duty"
    else:
        out["notes"].append("No duty in Operations here: enter the hours a unit runs a day.")
    # A task (the one given, else the first by the model's unit among the node's): its interval as
    # the planned replacement age, its labour hours and its cost each time.
    fit = [t for t in tasks if unit and t.get("interval") and norm_unit(t.get("unit")) == norm_unit(unit)]
    task = (tasks[0] if len(tasks) == 1 else None) or (fit[0] if fit else None)
    if task is not None:
        view = m._task_view(task)
        out["task"] = {"id": task["id"], "name": task.get("name", ""), "interval": task.get("interval"), "unit": task.get("unit")}
        out["interval"] = {"every": task.get("interval"), "unit": task.get("unit")}
        if unit and task.get("interval") and norm_unit(task.get("unit")) == norm_unit(unit):
            out["replace_at"] = float(task["interval"])
        elif task.get("interval"):
            out["notes"].append(f"{task.get('name', 'The task')} goes by {task.get('unit')}, not the model's unit: "
                                "enter the replacement age in the model's unit.")
        res = view.get("resources") or {}
        hours = res.get("labour_hours") or res.get("duration_hours")
        out["planned_hours"] = float(hours) if hours else None
        amount = (view.get("cost") or {}).get("amount")
        out["planned_cost"] = float(amount) if amount is not None else None
    if out["model"] is not None and not out["ages"]:
        out["notes"].append("Enter the units' ages now.")
    return out


def _below(m, position_id: str, root: str | None) -> list[str]:
    inside = m.subtree_ids(position_id, root)
    return [position_id] + sorted(i for i in inside if i != position_id and (m.s.node(m.org, i) or {}).get("label") == "Position")


def _tasks_on(m, ids) -> list[dict]:
    from backend.maintenance.service import _subject

    wanted = set(ids)
    out = []
    for t in m.s.nodes(m.org, "Task"):
        if t.get("retired"):
            continue
        on = _subject(m.s, m.org, t)
        if on is not None and on["id"] in wanted:
            out.append(t)
    return sorted(out, key=lambda t: (t.get("name") or "", t["id"]))


def position_start(m, fetch, position_id: str, root: str | None = None) -> dict:
    """A position and everything below it."""
    pos = m._get(str(position_id), "Position")
    ids = _below(m, pos["id"], root)
    return forecast_start(m, fetch, ids, _tasks_on(m, ids), root,
                          {"kind": "position", "id": pos["id"], "name": pos.get("name", ""), "position_id": pos["id"]})


def task_start(m, fetch, task_id: str, root: str | None = None) -> dict:
    """One task: the position it's on (a task on an item or a place: refused)."""
    from backend.maintenance.service import Invalid, _subject

    task = m._get(str(task_id), "Task")
    on = _subject(m.s, m.org, task)
    if on is None or on.get("label") != "Position":
        raise Invalid("Only a task on a position can fill in a forecast.")
    return forecast_start(m, fetch, [on["id"]], [task], root,
                          {"kind": "task", "id": task["id"], "name": task.get("name", ""), "position_id": on["id"],
                           "sel": f"MT:{task['id']}"})


def package_start(m, fetch, package_id: str, root: str | None = None) -> dict:
    """A work package: the positions its tasks are on, and its tasks."""
    from backend.maintenance.service import _subject

    pkg = m._get(str(package_id), "WorkPackage")
    tasks = [t for t in (m.s.node(m.org, x["task_id"]) for x in pkg.get("members") or []) if t and not t.get("retired")]
    ids = []
    for t in tasks:
        on = _subject(m.s, m.org, t)
        if on is not None and on.get("label") == "Position" and on["id"] not in ids:
            ids.append(on["id"])
    return forecast_start(m, fetch, ids, tasks, root,
                          {"kind": "package", "id": pkg["id"], "name": pkg.get("name", ""),
                           "position_id": ids[0] if ids else None, "sel": f"MP:{pkg['id']}"})
