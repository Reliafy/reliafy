"""When the item is replaced: restart the task's schedule, or keep it (forecast plan step 5, Nov 2026;
forecast-rules 1.8).

Each task has one setting, ``on_replace``:

* **restart**: a new item fitted at the task's position, or at a position above it, restarts the
  schedule from the day it was fitted. The default for a task on its own (by the item's hours or age).
* **keep**: the schedule runs on regardless. The default for a calendar-rule task (the first
  Tuesday) and for a task done in a package (the package's visits set its dates).

Where it matters:

* **Next due** (exact, no statistics): a restart task counts its interval from the later of when it
  was last done and when the item there was fitted.
* **A task that replaces the part**: restart is age replacement (a failure restarts the clock, so
  the planned replacements are a chance); keep is block replacement (planned on fixed dates). Both
  worked out by RePyability (``NonRepairable.cost_by_window(resets=...)``).
* **A task that doesn't replace the part** (servicing): each replacement drops the part-used
  interval, about half a task. The forecast shows the scheduled count with a note on how much
  smaller it may be: about interval ÷ (2 × the mean life).

New events (older logs replay unchanged; no projection changes shape):

* ``task.on_replace_set {id, on_replace}``: restart, keep, or None (back to the default);
* ``task.done_before_fit {id, fit_on, last_done, last_done_reading}``: emitted just before an item is
  fitted, for each task there it renews (item.fitted counts them from the fitting, as it always has),
  so a keep task can count from its last real doing. A fitting logged before this event existed falls
  back to the task's latest closed work order.

The projectors read only the payload and write through the store.
"""

from __future__ import annotations

from backend.maintenance.store import GraphStore

VALUES = ("restart", "keep")
WORDS = {"restart": "Restart the schedule", "keep": "Keep the schedule"}
#: Below this share of tasks lost to restarts, the scheduled count is shown with a note (forecast-rules 1.8).
NOTE_BELOW = 0.05


def _task_on_replace_set(s: GraphStore, org: str, p: dict) -> None:
    s.patch_node(org, p["id"], {"on_replace": p.get("on_replace")})


def _task_done_before_fit(s: GraphStore, org: str, p: dict) -> None:
    s.patch_node(org, p["id"], {"done_before_fit": {"fit_on": p["fit_on"], "last_done": p.get("last_done"),
                                                    "last_done_reading": p.get("last_done_reading")}})


PROJECTORS = {"task.on_replace_set": _task_on_replace_set, "task.done_before_fit": _task_done_before_fit}


def shortfall(interval_in_life_unit: float, mean_life: float | None) -> float | None:
    """The share of a servicing task's doings lost to the part's replacements (each drops half an
    interval on average): interval ÷ (2 × the mean life), or None."""
    if not mean_life or mean_life <= 0 or interval_in_life_unit is None:
        return None
    return float(interval_in_life_unit) / (2.0 * float(mean_life))


class RestartOps:
    """The setting and what it does to Next due (methods added to ``Maintenance``)."""

    def task_on_replace(self, task: dict) -> dict:
        """{value (in force), set (as typed, or None), default, words, why}."""
        packaged = task["id"] in self._package_index()
        default = "keep" if task.get("rule") or packaged else "restart"
        why = ("in a package: its visits set the dates" if packaged else
               "a calendar pattern: it keeps its dates" if task.get("rule") else
               "a task on its own: it counts from the item fitted")
        value = task.get("on_replace") or default
        return {"value": value, "set": task.get("on_replace"), "default": default, "words": WORDS[value],
                "why": why}

    def set_task_on_replace(self, task_id: str, on_replace) -> dict:
        """When the item is replaced: restart the schedule, keep it, or None (the default)."""
        from backend.maintenance import service as sv

        task = self._get(task_id, "Task")
        if task.get("retired"):
            raise sv.Invalid("That task has been retired.")
        value = on_replace or None
        if value is not None and value not in VALUES:
            raise sv.Invalid("When the item is replaced, the task's schedule restarts (restart) or keeps going "
                             "(keep); null: the default.")
        if value != task.get("on_replace"):
            self._emit("task.on_replace_set", {"id": task["id"], "on_replace": value})
        return self._task_view(self._get(task["id"], "Task"))

    def restart_from(self, task: dict) -> str | None:
        """The day the item at the task's position (or a position above it) was fitted, when the task
        restarts on a replacement; None otherwise."""
        from backend.maintenance import service as sv

        if self.task_on_replace(task)["value"] != "restart":
            return None
        subject = sv._subject(self.s, self.org, task)
        if subject is None or subject.get("label") != "Position":
            return None
        # A fitting at the task's own position renews it as it happens (the projection, item.fitted);
        # one at a position above it, after the task was made, restarts it here.
        days = []
        for pid in self._ancestor_ids(subject["id"]):
            fit = self.current_fitment(pid)
            if fit and fit.get("from") and str(fit["from"])[:10] >= (task.get("start") or ""):
                days.append(str(fit["from"])[:10])
        return max(days) if days else None

    def note_done_before_fit(self, position_id: str, day: str) -> None:
        """Before an item is fitted at ``position_id`` on ``day``: each task there it will renew keeps
        its last real doing (task.done_before_fit)."""
        for task in self._tasks_on(position_id):
            if task.get("last_done") and task["last_done"] >= day:
                continue
            self._emit("task.done_before_fit", {"id": task["id"], "fit_on": day, "last_done": task.get("last_done"),
                                                "last_done_reading": task.get("last_done_reading")})

    def _renewed_by_fit(self, task: dict) -> bool:
        """Its last done is a fitting at its own position (item.fitted renews them), not a real doing."""
        from backend.maintenance import service as sv

        done = task.get("last_done")
        if not done:
            return False
        if (task.get("done_before_fit") or {}).get("fit_on") == done:
            return True
        subject = sv._subject(self.s, self.org, task)
        if subject is None or subject.get("label") != "Position":
            return False
        return any(str(f.get("from"))[:10] == done for f in self._fitments_at(subject["id"]) if not f.get("voided"))

    def _last_real_doing(self, task: dict) -> tuple[str | None, float | None]:
        """When it was last really done, before the fitting that renewed it: from task.done_before_fit,
        else (a fitting logged before that event) its latest closed work order on or before then."""
        before = task.get("done_before_fit") or {}
        if before.get("fit_on") == task.get("last_done"):
            return before.get("last_done"), before.get("last_done_reading")
        closed = [w.get("closed") for w in self.s.inn(self.org, task["id"], "FOR")
                  if w.get("label") == "WorkOrder" and w.get("status") == "closed" and w.get("closed")
                  and w["closed"] <= task["last_done"]]
        return (max(closed) if closed else None), None

    def restarted(self, task: dict) -> dict:
        """The task as its schedule counts it: a restart task with an item fitted since it was last done
        (here or above) counts from the fitting (its last done reading then read from the counter at that
        day); a keep task renewed by a fitting counts from its last real doing."""
        if self.task_on_replace(task)["value"] == "keep":
            if self._renewed_by_fit(task):
                done, reading = self._last_real_doing(task)
                return {**task, "last_done": done, "last_done_reading": reading, "kept_from": done}
            return task
        day = self.restart_from(task)
        if not day or day <= (task.get("last_done") or task.get("start") or ""):
            # Renewed by a fitting at its own position already (item.fitted does that): say so.
            return {**task, "restarted_on": task["last_done"]} if self._renewed_by_fit(task) else task
        return {**task, "last_done": day, "last_done_reading": None, "restarted_on": day}
