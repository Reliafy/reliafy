"""Blocks a repairable diagram can't simulate in good time yet.

A block whose life is a mixture (two or more failure modes, #318) and whose
repairs are imperfect (Kijima I or II, with or without replacement at the
N-th failure, #68) draws each life after a repair given the block's virtual
age, by inverting the mixture's cumulative hazard numerically. In
RePyability 0.13 that is slow and grows much faster than the window: on a
two-block series diagram, 100 replications take about 0.45 s over 2,000 h,
2.8 s over 10,000 h, 53 s over 15,000 h and more than 9 minutes over
20,000 h. Reliafy's time budgets plan a run from a timed pilot batch and
can't stop a batch once it has started, so a pilot (or a free quick run's
first block) at the default window could hold a web worker, or a compute
job, far past its limit.

So such a block is refused, wherever a repairable diagram is checked or
built: Validate, the app's and MCP's analyses (in process and on the
calculation service), MCP ``create_rbd`` / ``edit_rbd``, and the runtime
quote. A refusal by window instead would hang on the mixture's shape (an
early failure mode makes many more repairs than the same window with a
later one), so no window is safe for every mixture. A block pinned working
or failed is never simulated, so it isn't refused.
"""

from __future__ import annotations

from typing import Optional

MESSAGE = ("A two-failure-mode life with imperfect repair can't be simulated quickly yet; use one failure mode, "
           "or repair as good as new.")


def slow_blocks(graph: dict) -> list[str]:
    """The labels of a repairable diagram's blocks with a mixture life and
    imperfect repair (none for a non-repairable diagram)."""
    from backend.services import rbd_mixture, rbd_repair_quality

    if not (graph or {}).get("repairable"):
        return []
    out = []
    for node in graph.get("nodes") or []:
        if not isinstance(node, dict) or node.get("type") != "component":
            continue
        data = node.get("data") or {}
        if data.get("state") in ("working", "failed"):
            continue
        if rbd_mixture.is_mixture(data.get("model")) and rbd_repair_quality.is_imperfect(data):
            out.append(data.get("label") or node.get("id"))
    return out


def errors(graph: dict) -> list[str]:
    """One error per such block, for Validate."""
    return [f"“{label}”: {MESSAGE[0].lower()}{MESSAGE[1:]}" for label in slow_blocks(graph)]


def refusal(graph: dict) -> Optional[str]:
    """The first such block's error, or None."""
    found = errors(graph)
    return found[0] if found else None


def check(graph: dict) -> None:
    """Raise :class:`AnalysisError` for the first such block."""
    message = refusal(graph)
    if message:
        from backend.services.rbd_analysis import AnalysisError

        raise AnalysisError(message)
