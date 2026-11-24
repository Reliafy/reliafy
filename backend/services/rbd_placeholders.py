"""How much of a diagram rests on placeholders, counted through every level of nesting.

A placeholder is a block whose model is a guessed life standing in for none
(``data.model.placeholder``: "Build from what's inside" puts one where a position
has no model). A sub-system block is a diagram of its own, so its blocks are
counted too: a diagram of six sub-systems whose 27 blocks are all placeholders
is 27 of 27 basic blocks resting on placeholders, never "1 placeholder".

* A basic block is any block that isn't a sub-system, a vote, a junction or the
  input or output. A standby or load-sharing block counts once.
* A sub-system block whose basic blocks are all placeholders is itself a
  placeholder: it is never "a block with a model" (missions, weakest block).
  One with some placeholders inside is partly placeholders.

Reads the graphs only; never changes them. Why: the rule is "never invent
failure data silently", and an undercount says less than the truth.
"""

from __future__ import annotations

from typing import Callable, Optional

#: How deep sub-systems are followed (a guard: nesting this deep doesn't happen in practice).
MAX_DEPTH = 8
#: How many names a sentence lists before "and N more".
SHOWN = 8

_NOT_BLOCKS = ("input", "output", "knode", "junction")


def _sub_id(node: dict) -> Optional[str]:
    d = node.get("data") or {}
    ref = d.get("rbd") if isinstance(d.get("rbd"), dict) else None
    sub = (ref or {}).get("id") or node.get("subsystem_rbd_id")
    return str(sub) if sub else None


def _label(node: dict) -> str:
    d = node.get("data") or {}
    return str(d.get("label") or node.get("label") or node.get("id") or "a block")


#: Blocks whose life is a model on the block (a load-sharing block names its saved model).
_MODEL_BLOCKS = ("component", "series", "parallel", "standby")


def _is_placeholder(node: dict) -> bool:
    """A block on a placeholder life, or on no life model at all (then the diagram isn't worked out
    until it has one). A block pinned Working or Failed needs none."""
    d = node.get("data") or {}
    model = d.get("model") if isinstance(d.get("model"), dict) else node.get("model")
    if isinstance(model, dict) and model.get("placeholder"):
        return True
    if node.get("type") not in _MODEL_BLOCKS or d.get("state") in ("working", "failed") or d.get("repeat_of"):
        return False
    if node.get("type") == "standby":
        from backend.services import rbd_standby

        return not rbd_standby.model_paths(d) and not isinstance(node.get("model"), dict)
    return not (isinstance(model, dict) and model)


def tally(graph: dict, resolve_subsystem: Optional[Callable[[str], Optional[dict]]] = None,
          _seen: frozenset = frozenset(), _depth: int = 0) -> dict:
    """``{basic, placeholders, names, by_node}`` for ``graph``.

    ``basic``: how many basic blocks the diagram has, sub-systems opened up;
    ``placeholders``: how many of them are placeholders; ``names``: those, as
    paths ("Propulsion › Motor 1"); ``by_node``: for each top-level block
    {basic, placeholders, label, subsystem}. A sub-system that can't be opened
    (deleted, or a loop) counts as one basic block that isn't a placeholder:
    nothing is claimed about what can't be read."""
    basic = placeholders = 0
    names: list[str] = []
    by_node: dict[str, dict] = {}
    for n in (graph or {}).get("nodes") or []:
        if not isinstance(n, dict) or n.get("type") in _NOT_BLOCKS:
            continue
        nid = n.get("id")
        label = _label(n)
        sub = _sub_id(n)
        if sub and resolve_subsystem is not None and sub not in _seen and _depth < MAX_DEPTH:
            try:
                sub_graph = resolve_subsystem(sub)
            except Exception:  # noqa: BLE001 - a count never fails a read
                sub_graph = None
            if sub_graph:
                inner = tally(sub_graph, resolve_subsystem, _seen | {sub}, _depth + 1)
                row = {"basic": inner["basic"], "placeholders": inner["placeholders"], "label": label,
                       "subsystem": True}
                names += [f"{label} › {x}" for x in inner["names"]]
            else:
                row = {"basic": 1, "placeholders": 0, "label": label, "subsystem": True}
        elif sub:
            row = {"basic": 1, "placeholders": 0, "label": label, "subsystem": True}
        else:
            ph = _is_placeholder(n)
            row = {"basic": 1, "placeholders": 1 if ph else 0, "label": label, "subsystem": False}
            if ph:
                names.append(label)
        by_node[str(nid)] = row
        basic += row["basic"]
        placeholders += row["placeholders"]
    return {"basic": basic, "placeholders": placeholders, "names": names, "by_node": by_node}


def all_placeholder_ids(t: dict) -> list[str]:
    """The top-level blocks resting wholly on placeholders (a placeholder block, or a
    sub-system whose basic blocks are all placeholders)."""
    return [nid for nid, r in t["by_node"].items() if r["basic"] > 0 and r["placeholders"] == r["basic"]]


def partly_placeholder_ids(t: dict) -> list[str]:
    """The top-level sub-systems with some, but not all, of their basic blocks placeholders."""
    return [nid for nid, r in t["by_node"].items() if 0 < r["placeholders"] < r["basic"]]


def nested(t: dict) -> bool:
    """Whether any placeholder sits inside a sub-system (the count then says "basic blocks")."""
    return any(r["subsystem"] and r["placeholders"] for r in t["by_node"].values())


def mostly(t: dict) -> bool:
    """Whether most of the diagram's basic blocks are placeholders (half or more): the
    warning is then made prominent (the answer rests mostly on invented lives)."""
    return t["basic"] > 0 and t["placeholders"] * 2 >= t["basic"]


def summary(t: dict) -> Optional[dict]:
    """What a read carries: {basic, placeholders, names (the first few), more, mostly,
    words} or None when nothing is a placeholder."""
    if not t["placeholders"]:
        return None
    return {"basic": t["basic"], "placeholders": t["placeholders"], "names": t["names"][:SHOWN],
            "more": max(0, len(t["names"]) - SHOWN), "mostly": mostly(t), "nested": nested(t), "words": words(t)}


def words(t: dict) -> str:
    """"27 of 27 basic blocks are placeholders" (or "1 of 12 basic blocks is a placeholder")."""
    ph, basic = t["placeholders"], t["basic"]
    if basic == 1:
        return "its one block has no real life model yet" if ph else ""
    what = "basic blocks" if t.get("by_node") is None or nested(t) else "blocks"
    return f"{ph:,} of {basic:,} {what} {'has' if ph == 1 else 'have'} no real life model yet"


def names_text(t: dict) -> str:
    """The placeholder names for a sentence: the first few, then "and N more"."""
    shown = t["names"][:SHOWN]
    more = len(t["names"]) - len(shown)
    return ", ".join(shown) + (f" and {more} more" if more > 0 else "")
