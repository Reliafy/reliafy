"""What the quick spares forecast (Decisions › Forecasts › Spares forecast) can take from a position
or a task in the Explorer, so it opens filled in: the position's model in use, its hours a day from
its duty, and a task's interval as the planned replacement age. Only what's recorded: no duty means
no hours a day (the analyst types it), and ages are left for the analyst to give."""

from __future__ import annotations

from backend.maintenance.rcm_decisions import norm_unit
from backend.services import running_clock


def spares_start(m, fetch, position_id: str, task_id: str | None = None, root: str | None = None) -> dict:
    pos = m._get(str(position_id), "Position")
    out = {"position": {"id": pos["id"], "name": pos.get("name", "")}, "task": None, "model": None,
           "hours_per_day": None, "duty": None, "replace_at": None, "notes": []}
    links = [x for x in m.all_position_models([pos["id"]]) if x.get("model_type") == "model"]
    link = next((x for x in links if x.get("in_use")), None) or (links[0] if links else None)
    doc = fetch("model", link["model_id"]) if link else None
    unit = ""
    if doc is not None:
        results = getattr(doc, "results", None) or {}
        unit = results.get("unit") or ""
        out["model"] = {"id": doc.id, "name": getattr(doc, "name", "") or "", "unit": unit}
    else:
        out["notes"].append("No non-repairable model on this position: pick one, or type its parameters.")
    clock = running_clock.for_position(m, pos["id"], root)
    if clock.basis == "duty" and clock.hours_per_day > 0:
        out["hours_per_day"] = round(clock.hours_per_day, 4)
        out["duty"] = clock.plan or "its duty"
    else:
        out["notes"].append("No duty on this position: enter the hours a unit runs a day.")
    if task_id:
        task = m._get(str(task_id), "Task")
        out["task"] = {"id": task["id"], "name": task.get("name", ""), "interval": task.get("interval"),
                       "unit": task.get("unit")}
        if unit and task.get("interval") and norm_unit(task.get("unit")) == norm_unit(unit):
            out["replace_at"] = float(task["interval"])
        elif task.get("interval"):
            out["notes"].append(f"{task.get('name', 'The task')} goes by {task.get('unit')}, not the model's unit: "
                                "enter the replacement age in the model's unit.")
    out["notes"].append("Enter the units' ages now: they aren't filled in from the asset register.")
    return out
