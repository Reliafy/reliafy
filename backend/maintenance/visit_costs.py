"""What a visit costs, besides its tasks (Nov 2026): the call-out, travel, setting up and the crew
standing by while the asset is out of use.

A **package's** ``visit_cost`` is charged once for each of its visits. A task in no package can carry
its own ``visit_cost``, charged each time it's done (it's a visit of its own). Visits to the same
position at the same time (a 50 h and a 100 h service together) are one visit: the forecast charges
the larger visit cost once (position_forecast.py).

New events (older logs replay unchanged):

* ``package.visit_cost_set {id, visit_cost}``: a number, or None (no visit cost);
* ``task.visit_cost_set {id, visit_cost}``: the same, on a task.

Projectors read only the payload, and write through the store interface.
"""

from __future__ import annotations

import math

from backend.maintenance.store import GraphStore

MAX_COST = 1e12


def _visit_cost_set(s: GraphStore, org: str, p: dict) -> None:
    s.patch_node(org, p["id"], {"visit_cost": p.get("visit_cost")})


PROJECTORS = {
    "package.visit_cost_set": _visit_cost_set,
    "task.visit_cost_set": _visit_cost_set,
}


def clean(value) -> float | None:
    """A visit cost as stored: 0 or more; None or "" for none."""
    from backend.maintenance.service import Invalid

    if value is None or value == "":
        return None
    try:
        v = float(value)
    except (TypeError, ValueError, OverflowError):
        raise Invalid("A visit's cost must be a number.") from None
    if not math.isfinite(v) or not 0 <= v <= MAX_COST:
        raise Invalid("A visit's cost is 0 or more.")
    return round(v, 2)


class VisitCostOps:
    """Setting a package's or a task's visit cost (methods added to ``Maintenance``)."""

    def set_package_visit_cost(self, package_id, visit_cost) -> dict:
        """What each of the package's visits costs besides its tasks (call-out, setup); None: none."""
        pkg = self._live_package(package_id)
        value = clean(visit_cost)
        if value != pkg.get("visit_cost"):
            self._emit("package.visit_cost_set", {"id": pkg["id"], "visit_cost": value})
        return self.package(pkg["id"])

    def set_task_visit_cost(self, task_id, visit_cost) -> dict:
        """What doing the task costs besides itself when it's a visit of its own (in no package):
        call-out, setup. None: none."""
        from backend.maintenance.service import Invalid

        task = self._live_task(task_id)
        value = clean(visit_cost)
        if value is not None and task["id"] in self._package_index():
            raise Invalid(f"“{task['name']}” is done on its package's visits: set the visit's cost on the package.")
        if value != task.get("visit_cost"):
            self._emit("task.visit_cost_set", {"id": task["id"], "visit_cost": value})
        return self._task_view(self._get(task["id"], "Task"))
