"""JSON round-trip for RePyability's availability tally (``_Tally``).

The tally is RePyability 0.10.1's private running total of an availability
simulation; ``_Tally.merge`` adds two of them. A worker ships one tally per
block of replications, and the merger folds them back together in block
order, which is exactly what ``RepairableRBD._run_parallel`` does in one
process, so the merged result matches a single-machine ``n_jobs=1`` run
digit for digit. Floats survive JSON exactly (``json`` writes ``repr``).

Private API, pinned to RePyability 0.10.1: an experiment, not production.
RePyability #114 is to make a public, serialisable tally.
"""

from __future__ import annotations

from collections import Counter, defaultdict

from repyability.rbd.repairable_rbd import _Tally

_SCALARS = ("n", "system_restorations", "system_failures", "system_planned_outages",
            "system_uptime", "system_downtime")
_NODE_TOTALS = ("node_uptime", "node_downtime", "intersection_uptime", "intersection_downtime",
                "union_uptime", "union_downtime")


def to_dict(t: _Tally) -> dict:
    return {
        **{k: getattr(t, k) for k in _SCALARS},
        # Time -> net change in the number of systems working, as pairs
        # (JSON keys would have to be strings).
        "changes": [[time, change] for time, change in t.changes.items()],
        **{k: dict(getattr(t, k)) for k in _NODE_TOTALS},
        "RCI": {node: dict(c) for node, c in t.RCI.items()},
        "FCI": {node: dict(c) for node, c in t.FCI.items()},
        "uptimes": list(t.uptimes),
        "cost_samples": list(t.cost_samples),
        "cost_by_category": dict(t.cost_by_category),
        "cost_by_component": dict(t.cost_by_component),
    }


def from_dict(d: dict, costs: dict) -> _Tally:
    t = _Tally(costs)
    for k in _SCALARS:
        setattr(t, k, d[k])
    t.changes = defaultdict(int, {time: change for time, change in d["changes"]})
    for k in _NODE_TOTALS:
        setattr(t, k, defaultdict(int, d[k]))
    t.RCI = defaultdict(Counter, {node: Counter(c) for node, c in d["RCI"].items()})
    t.FCI = defaultdict(Counter, {node: Counter(c) for node, c in d["FCI"].items()})
    t.uptimes = list(d["uptimes"])
    t.cost_samples = list(d["cost_samples"])
    t.cost_by_category = dict(d["cost_by_category"])
    t.cost_by_component = dict(d["cost_by_component"])
    return t
