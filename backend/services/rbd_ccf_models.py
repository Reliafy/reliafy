"""A common-cause group's model (#84): the beta factor, or the Multiple
Greek Letter (MGL) model for groups of three or more.

The beta factor puts a share ``beta`` of each member's failures down to one
shared cause that fails the whole group. MGL (RePyability's ``MGL(beta,
gamma, delta, ...)``) refines it for larger groups: ``beta`` is the chance a
member's failure is shared by at least one other, ``gamma`` that a shared
failure takes at least three, ``delta`` at least four, and so on — a group
of ``m`` members needs ``m - 1`` letters, and ``MGL(beta)`` on a pair is the
beta factor. So a 2-of-3 train can lose two pumps to one cause more often
than all three.

A group holds the letters after beta in ``mgl``; without them it is a
beta-factor group, as before::

    graph["ccf_groups"] = [{"id": "ccf-1", "members": ["p1", "p2", "p3"],
                            "beta": 0.1, "mgl": [0.3], "basis": "rate"}]

RePyability takes either model wherever it takes a group: the exact
reliability and MTTF, the repairable chains and simulations, the importance
measures and the sensitivity levers (``ccf_gamma``, …).
"""

from __future__ import annotations

import math
from typing import Optional

from backend.services.rbd_analysis import AnalysisError

GREEK = ("β", "γ", "δ", "ε", "ζ", "η", "θ")
NAMES = ("beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta")


def is_mgl(group) -> bool:
    return isinstance(group, dict) and bool(group.get("mgl"))


def letters(group: dict, where: str = "A common-cause group") -> list[float]:
    """``[beta, gamma, ...]`` of an MGL group (``[beta]`` for a beta-factor
    one), each checked from 0 to 1 (beta above 0 and below 1)."""
    raw = group.get("mgl") or []
    if not isinstance(raw, list):
        raise AnalysisError(f"{where}: its MGL letters must be a list (gamma, delta, …).")
    out = [float(group.get("beta"))]
    for i, v in enumerate(raw, start=1):
        try:
            x = float(v)
        except (TypeError, ValueError):
            x = float("nan")
        if isinstance(v, bool) or not math.isfinite(x) or not 0.0 <= x <= 1.0:
            name = NAMES[i] if i < len(NAMES) else f"letter {i + 1}"
            raise AnalysisError(f"{where}: {name} must be a probability from 0 to 1.")
        out.append(x)
    return out


def group_model(group: dict, count: int, basis: str, where: str = "A common-cause group"):
    """RePyability's model of a group of ``count`` members: ``BetaFactor`` or
    ``MGL``. Raises :class:`AnalysisError` when an MGL group's letters don't
    fit its size."""
    from repyability.rbd.ccf import MGL, BetaFactor

    beta = float(group.get("beta"))
    if not is_mgl(group):
        return BetaFactor(beta, basis=basis)
    values = letters(group, where)
    if len(values) != count - 1:
        raise AnalysisError(
            f"{where}: a multiple Greek letter group of {count} members needs {count - 1} letters "
            f"({', '.join(NAMES[:count - 1])}); it has {len(values)}. Set them in the group's dialog.")
    return MGL(*values, basis=basis)


def errors(graph: dict, labels: dict) -> list[str]:
    """The Validate step's errors on the groups' MGL letters."""
    out = []
    for g in graph.get("ccf_groups") or []:
        if not is_mgl(g):
            continue
        members = list(dict.fromkeys(m for m in g.get("members") or [] if m in labels))
        where = f"Common-cause group ({', '.join(labels.get(m, str(m)) for m in members)})"
        try:
            values = letters(g, where)
        except (AnalysisError, TypeError, ValueError) as exc:
            out.append(str(exc))
            continue
        if len(members) >= 2 and len(values) != len(members) - 1:
            out.append(f"{where}: a multiple Greek letter group of {len(members)} members needs "
                       f"{len(members) - 1} letters ({', '.join(NAMES[:len(members) - 1])}); it has {len(values)}.")
    return out


def describe(group: dict) -> str:
    """"β = 0.1, γ = 0.3 (MGL)" or "β = 0.1"."""
    try:
        values = letters(group)
    except (AnalysisError, TypeError, ValueError):
        return f"β = {group.get('beta')}"
    text = ", ".join(f"{GREEK[i] if i < len(GREEK) else NAMES[i]} = {v:g}" for i, v in enumerate(values))
    return text + (" (multiple Greek letter)" if len(values) > 1 else "")


def script_expr(group: dict, basis: str) -> str:
    """The model call "Download as Python" writes for a group (the basis
    only when it isn't RePyability's default, the probability)."""
    values = letters(group)
    tail = "" if basis == "probability" else f", basis={basis!r}"
    if not is_mgl(group):
        return f"BetaFactor({values[0]!r}{tail})"
    return f"MGL({', '.join(repr(v) for v in values)}{tail})"


def document_model(group: dict, basis: str) -> dict:
    """The group's model as RePyability's ``rbd_to_dict`` writes it."""
    values = letters(group)
    if not is_mgl(group):
        out = {"kind": "beta_factor", "beta": values[0]}
    else:
        out = {"kind": "mgl", "letters": values}
    if basis != "probability":
        out["basis"] = basis
    return out


def from_document(model: dict) -> Optional[dict]:
    """``{"beta", "mgl"?}`` from a RePyability document's group model (beta
    factor or MGL), or None when it isn't one Reliafy can hold."""
    if not isinstance(model, dict):
        return None
    kind = model.get("kind")
    if kind == "beta_factor":
        values = [model.get("beta")]
    elif kind == "mgl":
        values = model.get("letters")
        if not isinstance(values, list) or not values:
            return None
    else:
        return None
    try:
        numbers = [float(v) for v in values]
    except (TypeError, ValueError):
        return None
    if any(isinstance(v, bool) for v in values) or not all(math.isfinite(x) and 0 <= x <= 1 for x in numbers):
        return None
    if not 0 < numbers[0] < 1:
        return None
    out: dict = {"beta": numbers[0]}
    if len(numbers) > 1:
        out["mgl"] = numbers[1:]
    if model.get("shocks") not in (None, "exclusive"):
        return None  # independent shocks: Reliafy's groups use exclusive ones (RePyability's default)
    return out
