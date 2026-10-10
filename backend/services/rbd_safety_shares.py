"""Where a safety function's PFDavg comes from (#298): each element's share,
and the common-cause groups'.

RePyability 0.13 has no breakdown of the PFDavg itself that splits out the
common-cause term. It has two exact long-run measures that answer the
question between them, on the same diagram the PFDavg was worked out on
(with its common-cause groups wherever the PFDavg has them):

* **Share of PFDavg** — ``RepairableRBD.fussell_vesely``: the share of the
  long-run unavailability (the PFDavg) in which the element's minimal cut
  sets have failed. A common cause fails its members together, so it sits
  in each member's share and has none of its own; and the members of a
  redundant pair are both in its cut set, so the shares add up to more than
  100%.
* **Share of dangerous failures** — ``RepairableRBD.barlow_proschan_importance``:
  each element's share of the function's failures in the long run, with a
  cause that strikes a common-cause group's members together counted for the
  group (under the tuple of its members). These add up to 100%.

Each is left out, with the reason, where RePyability refuses it.
"""

from __future__ import annotations

import math
from typing import Any, Optional

import numpy as np

#: Said beside the shares when a group's common cause is in the PFDavg.
COMMON_CAUSE_IN_MEMBERS = ("The common-cause part of the PFDavg isn't split out: each member's share of the "
                           "PFDavg includes it. Its share of the dangerous failures is on its own row.")
_GATE_TYPES = ("knode", "input", "output")


def _f(value) -> Optional[float]:
    try:
        v = float(np.asarray(value, dtype=float).reshape(-1)[0])
    except (TypeError, ValueError, IndexError):
        return None
    return v if math.isfinite(v) else None


def _measure(rbd, method: str, overrides: dict) -> tuple[Optional[dict], Optional[str]]:
    from backend.services.rbd_analysis import plain_reason

    try:
        with np.errstate(all="ignore"):
            return dict(getattr(rbd, method)(**overrides)), None
    except (NotImplementedError, ValueError) as exc:
        return None, plain_reason(str(exc))


def pfd_shares(rbd, graph: dict, overrides: Optional[dict] = None) -> Optional[dict]:
    """The elements' and common-cause groups' shares of a safety function's
    PFDavg and of its dangerous failures, from ``rbd`` (the RepairableRBD the
    PFDavg came from), largest share of the PFDavg first. None when
    RePyability gives neither measure."""
    overrides = {k: v for k, v in (overrides or {}).items() if k in ("working_nodes", "broken_nodes") and v}
    nodes = {n.get("id"): n for n in graph.get("nodes") or []}
    labels = {nid: (n.get("data") or {}).get("label") or str(nid) for nid, n in nodes.items()}
    skip = {nid for nid, n in nodes.items() if n.get("type") in _GATE_TYPES}
    fv, fv_reason = _measure(rbd, "fussell_vesely", overrides)
    bp, bp_reason = _measure(rbd, "barlow_proschan_importance", overrides)
    if fv is None and bp is None:
        return None

    elements: list[dict[str, Any]] = []
    for nid in rbd.components:
        if nid in skip or nid not in nodes:
            continue
        elements.append({
            "id": str(nid),
            "label": labels.get(nid, str(nid)),
            "pfd_share": _f(fv.get(nid)) if fv is not None else None,
            "failure_share": _f(bp.get(nid)) if bp is not None else None,
        })
    groups = []
    for key, value in (bp or {}).items():
        if isinstance(key, tuple):
            members = [str(m) for m in key]
            groups.append({
                "members": members,
                "label": " + ".join(labels.get(m, m) for m in key),
                "pfd_share": None,
                "failure_share": _f(value),
            })
    elements.sort(key=lambda r: (-(r["pfd_share"] if r["pfd_share"] is not None else -1),
                                 -(r["failure_share"] or 0)))
    out: dict[str, Any] = {"elements": elements, "common_cause": groups}
    if groups:
        out["common_cause_note"] = COMMON_CAUSE_IN_MEMBERS
    if fv is None:
        out["pfd_share_reason"] = fv_reason
    if bp is None:
        out["failure_share_reason"] = bp_reason
    return out
