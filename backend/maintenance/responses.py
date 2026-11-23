"""What's done when a failure mode happens anyway, or when an inspection finds it (forecast plan
steps 3 and 4, Nov 2026; forecast-rules section 2).

Both are tasks raised by an event rather than a schedule, on the failure mode's position, so "what
it needs" (the LSA: labour, spares, consumables), the trade rates and the cost-each-time rule work
for them as for any task, and each fact is typed once:

* the **corrective response** ("If it fails anyway"): a task with trigger {kind: failure,
  failure_mode_id}. It feeds the forecast's failure lines: their hours (its labour), spares (its
  spares) and cost (its cost each time). The failure mode's cost of a failure is derived from it;
  a typed cost of a failure on the mode overrides it (failure_costs.py);
* the **follow-on** ("If an inspection finds it"): a task with trigger {kind: found,
  failure_mode_id}. It feeds the follow-on line: the failures that would have happened × the share
  the inspection finds in time.

Both are optional: with none, the forecast still counts the failures (or the finds) and lists the
hours, spares and cost it can't know under "Not counted", never filled in. The free-text notes
(``task_note``, ``on_found``) stay as they are and become the response's name when it's first made.
Nothing new in the log: the tasks are made and changed with the task events there already
(task.created, task.trigger_set, task.resources_set, task.cost_set, task.retired).
"""

from __future__ import annotations

KINDS = ("failure", "found")
WORDS = {"failure": "If it fails anyway", "found": "If an inspection finds it"}


def response_task(m, mode_id: str, kind: str) -> dict | None:
    """The live response task of ``kind`` for the failure mode (on the mode's position), or None;
    the latest if several."""
    owners = m.s.inn(m.org, mode_id, "CAN_FAIL_AS")
    if not owners:
        return None
    found = None
    for t in m._tasks_on(owners[0]["id"]):
        trig = t.get("trigger") or {}
        if trig.get("kind") != kind or trig.get("failure_mode_id") != mode_id:
            continue
        if found is None or ((t.get("start") or ""), t["id"]) >= ((found.get("start") or ""), found["id"]):
            found = t
    return found


def labour_hours(view: dict) -> float | None:
    total = 0.0
    for line in (view.get("resources") or {}).get("labour") or []:
        try:
            total += float(line.get("people") or 1) * float(line.get("hours") or 0)
        except (TypeError, ValueError):
            continue
    return total or None


def response_view(m, mode_id: str, kind: str) -> dict | None:
    """{id, name, kind, words, hours_each, cost_each, cost_source, spares [{name, part_id, qty}],
    labour [...], gaps [...]} of the response, or None when none is recorded."""
    task = response_task(m, mode_id, kind)
    if task is None:
        return None
    view = m._task_view(task)
    res = view.get("resources") or {}
    cost = view.get("cost") or {}
    spares = [{"name": s.get("name") or "a spare", "part_id": s.get("part_id"), "qty": float(s.get("qty") or 1)}
              for s in res.get("spares") or []]
    hours = labour_hours(view)
    gaps = []
    if hours is None:
        gaps.append("no labour in it, so its hours are unknown")
    if cost.get("amount") is None:
        gaps.append("no cost each time")
    return {"id": task["id"], "name": task.get("name") or "", "kind": kind, "words": WORDS[kind],
            "hours_each": hours, "cost_each": cost.get("amount"), "cost_source": cost.get("source"),
            "spares": spares, "labour": res.get("labour") or [], "gaps": gaps}


class ResponseOps:
    """Recording a failure mode's corrective response and follow-on (methods added to
    ``Maintenance``)."""

    def mode_responses(self, mode_id: str) -> dict:
        fm, _pos = self._live_mode(mode_id)
        return {"failure": response_view(self, fm["id"], "failure"), "found": response_view(self, fm["id"], "found")}

    def set_mode_response(self, mode_id: str, kind: str, name=None, labour=..., cost=..., spares=...) -> dict:
        """Make or change the failure mode's response of ``kind`` (failure: if it fails anyway; found:
        if an inspection finds it): its name (what's done), labour [{trade, people, hours}], cost each
        time (None: from its LSA) and spares [{name, qty, part_id?}]. Left out (``...``): kept."""
        from backend.maintenance import service as sv

        if kind not in KINDS:
            raise sv.Invalid("A response is for a failure (failure) or for an inspection's find (found).")
        fm, pos = self._live_mode(mode_id)
        task = response_task(self, fm["id"], kind)
        default = (fm.get("task_note") if kind == "failure" else fm.get("on_found")) or (
            f"Put right: {fm.get('text') or 'the failure'}" if kind == "failure" else
            f"Act on the find: {fm.get('text') or 'the failure mode'}")
        text = " ".join(str(name).split())[:200] if name not in (None, "") else None
        if task is None:
            task = self.create_task(pos["id"], text or default[:200], None, "months",
                                    trigger={"kind": kind, "failure_mode_id": fm["id"]}, source="manual")
            task = self._get(task["id"], "Task")
        elif text and text != task.get("name"):
            self.update_task(task["id"], name=text)
        resources = {}
        if labour is not ...:
            resources["labour"] = labour or None
        if spares is not ...:
            resources["spares"] = spares or None
        if resources:
            self.set_task_resources(task["id"], resources)
        if cost is not ...:
            self.set_task_cost(task["id"], cost)
        return response_view(self, fm["id"], kind)

    def clear_mode_response(self, mode_id: str, kind: str) -> dict:
        """No response of ``kind`` any more: its task is retired (kept in the history)."""
        from backend.maintenance import service as sv

        if kind not in KINDS:
            raise sv.Invalid("A response is for a failure (failure) or for an inspection's find (found).")
        fm, _pos = self._live_mode(mode_id)
        task = response_task(self, fm["id"], kind)
        if task is not None:
            self.retire_task(task["id"], reason="no longer the failure mode's response")
        return self.mode_responses(fm["id"])
