"""How well a repair restores a repairable block (#68): imperfect repair by
Kijima's virtual age, and replacement at the N-th failure.

RePyability 0.11 added both to a ``RepairableRBD`` component spec (its #109)::

    {"reliability": ..., "repairability": ...,
     "repair": {"model": "kijima1" | "kijima2", "q": 0.5},
     "replace_after": 3}

A repair after the unit has run ``x`` since the last takes its virtual age
from ``v`` to ``v + q x`` (Kijima I) or ``q (v + x)`` (Kijima II); its next
life is drawn given that age. ``q = 0`` renews it (perfect repair, the
default) and ``q = 1`` leaves it as old as it was (minimal repair).
``replace_after`` replaces the unit, as new, at the N-th failure since it was
renewed; a repair is then charged only its repair cost, a replacement its
repair and replacement costs. RePyability needs ``q`` above 0 for it.

The block holds it as::

    node.data["repair_quality"] = {"model": "kijima1" | "kijima2",
                                   "q": 0.5,
                                   "replace_after": 3}      # optional

Absent (or ``{"model": "perfect"}``) is perfect repair, as before.

What the engine does with it: the simulations follow such a block; the
exact long-run values and the values over time refuse it (a repair doesn't
renew it), except a minimal repair (``q = 1``) in no time with no
replacement, maintenance or tests. Reliafy then gives the simulated figures,
and says why there are no exact ones (the engine's reason). A standby group,
a block replaced on condition, and a common-cause group's member can't be
repaired imperfectly (as in RePyability).
"""

from __future__ import annotations

import math
from typing import Optional

from backend.services.rbd_analysis import AnalysisError

KEY = "repair_quality"
MODELS = ("kijima1", "kijima2")
PERFECT = "perfect"
NAMES = {"kijima1": "Kijima I", "kijima2": "Kijima II"}
MAX_REPLACE_AFTER = 1000


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def parse(data: dict, label: str) -> Optional[dict]:
    """The block's repair quality, checked: ``{"model", "q", "replace_after"?}``,
    or None for perfect repair. Raises :class:`AnalysisError`."""
    raw = data.get(KEY)
    if raw in (None, "", {}):
        return None
    if not isinstance(raw, dict):
        raise AnalysisError(f"“{label}”: its repair quality must be an object of model, q and replace_after.")
    unknown = set(raw) - {"model", "q", "replace_after"}
    if unknown:
        raise AnalysisError(f"“{label}”: unknown repair-quality setting(s) {', '.join(sorted(map(str, unknown)))} "
                            "— use model, q and replace_after.")
    model = raw.get("model") or PERFECT
    if model == PERFECT:
        if raw.get("replace_after") not in (None, ""):
            raise AnalysisError(f"“{label}”: replacement at the N-th failure needs imperfect repair (Kijima I or "
                                "II with q above 0) — a perfect repair already renews it.")
        return None
    if model not in MODELS:
        raise AnalysisError(f"“{label}”: the repair-quality model must be perfect, kijima1 or kijima2 "
                            f"(got {model!r}).")
    q = raw.get("q")
    try:
        q = float(q)
    except (TypeError, ValueError):
        raise AnalysisError(f"“{label}”: the restoration factor q must be a number from 0 (as good as new) "
                            "to 1 (as bad as old).") from None
    if isinstance(raw.get("q"), bool) or not math.isfinite(q) or not 0.0 <= q <= 1.0:
        raise AnalysisError(f"“{label}”: the restoration factor q must be from 0 (as good as new) to 1 (as bad "
                            "as old).")
    out: dict = {"model": model, "q": q}
    limit = raw.get("replace_after")
    if limit not in (None, ""):
        if isinstance(limit, bool):
            limit = None
        try:
            number = float(limit)
        except (TypeError, ValueError):
            number = float("nan")
        if not math.isfinite(number) or number != int(number) or not 1 <= number <= MAX_REPLACE_AFTER:
            raise AnalysisError(f"“{label}”: replace at the N-th failure needs a whole number N from 1 to "
                                f"{MAX_REPLACE_AFTER:,}.")
        if q == 0.0:
            raise AnalysisError(f"“{label}”: replacement at the N-th failure needs q above 0 — with q = 0 every "
                                "repair already renews it.")
        out["replace_after"] = int(number)
    return out


def spec_entries(data: dict, label: str) -> dict:
    """The block's RePyability component-spec keys: ``repair`` and
    ``replace_after`` (empty for perfect repair)."""
    quality = parse(data, label)
    if quality is None:
        return {}
    out: dict = {"repair": {"model": quality["model"], "q": quality["q"]}}
    if "replace_after" in quality:
        out["replace_after"] = quality["replace_after"]
    return out


def is_imperfect(data: dict) -> bool:
    raw = data.get(KEY)
    return isinstance(raw, dict) and (raw.get("model") or PERFECT) != PERFECT


def errors(data: dict, label: str, ntype: str = "component") -> list[str]:
    """What stops this block's repair quality (the Validate step's errors)."""
    try:
        quality = parse(data, label)
    except AnalysisError as exc:
        return [str(exc)]
    if quality is None:
        return []
    out = []
    if ntype == "standby":
        out.append(f"“{label}”: a standby group's units are repaired as good as new — imperfect repair applies to "
                   "a single block (as in RePyability).")
    if (data.get("preventive") or {}).get("policy") == "condition":
        out.append(f"“{label}”: a block replaced on condition is repaired as good as new — choose age or block "
                   "replacement, or perfect repair.")
    return out


def describe(data: dict) -> Optional[str]:
    """"Kijima I, q = 0.5, replaced at the 3rd failure", or None."""
    raw = data.get(KEY)
    if not is_imperfect(data):
        return None
    try:
        q = float(raw.get("q"))
    except (TypeError, ValueError):
        return NAMES.get(raw.get("model"), str(raw.get("model")))
    text = f"{NAMES.get(raw.get('model'), raw.get('model'))}, q = {q:g}"
    limit = raw.get("replace_after")
    if isinstance(limit, (int, float)) and not isinstance(limit, bool) and limit >= 1:
        text += f", replaced at the {_ordinal(int(limit))} failure"
    return text


def labels_with(graph: dict) -> list[str]:
    """The labels of the blocks repaired imperfectly."""
    return [(n.get("data") or {}).get("label") or n.get("id") for n in graph.get("nodes") or []
            if n.get("type") == "component" and is_imperfect(n.get("data") or {})]


def script_entries(data: dict, label: str) -> list[str]:
    """The spec entries "Download as Python" writes for it."""
    entries = spec_entries(data, label)
    out = []
    if "repair" in entries:
        r = entries["repair"]
        out.append(f'"repair": {{"model": {r["model"]!r}, "q": {r["q"]!r}}}')
    if "replace_after" in entries:
        out.append(f'"replace_after": {entries["replace_after"]}')
    return out


def from_document(spec: dict) -> Optional[dict]:
    """A block's repair quality from a RePyability component spec (its
    ``repair`` and ``replace_after``), or None when it has neither or they
    can't be read."""
    repair = spec.get("repair")
    if not isinstance(repair, dict) or repair.get("model") not in MODELS:
        return None
    try:
        q = float(repair.get("q"))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(q) or not 0.0 <= q <= 1.0:
        return None
    out: dict = {"model": repair["model"], "q": q}
    limit = spec.get("replace_after")
    if isinstance(limit, (int, float)) and not isinstance(limit, bool) and float(limit) == int(limit) \
            and 1 <= limit <= MAX_REPLACE_AFTER and q > 0:
        out["replace_after"] = int(limit)
    return out
