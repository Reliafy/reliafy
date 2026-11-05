"""Build a position's RCM in tests from a worksheet-shaped tree (functions ›
failures › modes, each mode with its consequence and decision), the way the
sample truck template and the worksheet import do: through the service's own
methods, so every change is an ordinary event."""

from __future__ import annotations


def apply_tree(m, position_id: str, functions) -> dict:
    """Add ``functions`` to the position; returns the counts added."""
    counts = {"functions": 0, "functional_failures": 0, "failure_modes": 0, "decisions": 0}
    for fn in functions or []:
        function = m.add_function(position_id, fn["text"], fn.get("standard", ""))
        counts["functions"] += 1
        for failure in fn.get("failures") or []:
            ff = m.add_functional_failure(function["id"], failure["text"])
            counts["functional_failures"] += 1
            for mode in failure.get("modes") or []:
                fm = m.add_failure_mode(position_id, mode["text"], functional_failure_id=ff["id"])
                counts["failure_modes"] += 1
                if mode.get("effects") or mode.get("notes"):
                    m.update_failure_mode(fm["id"], effects=mode.get("effects"), notes=mode.get("notes"))
                if mode.get("consequence") or mode.get("decision"):
                    m.decide_failure_mode(fm["id"], consequence=mode.get("consequence"),
                                          decision=mode.get("decision") or None)
                    counts["decisions"] += bool(mode.get("decision"))
    return counts


def position_with_rcm(m, functions, name="Position", parent_id=None, **position_kw) -> dict:
    """A new position with that RCM: {position (as m.position reads it), the
    counts, tasks (how many its decisions scheduled)}."""
    pid = m.create_position(name, parent_id=parent_id, **position_kw)["id"]
    counts = apply_tree(m, pid, functions)
    return {"position": m.position(pid), **counts, "tasks": len(m._tasks_on(pid))}
