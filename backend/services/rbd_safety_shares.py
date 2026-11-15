"""Where a safety function's PFDavg comes from (#298): each element's share,
and the common-cause groups'.

Two exact long-run measures, on the same diagram the PFDavg was worked out
on (with its common-cause groups wherever the PFDavg has them):

* **Share of PFDavg** — ``RepairableRBD.pfd_breakdown`` (RePyability 0.17):
  the PFDavg split into each component's share and each common-cause group's,
  adding up to the PFDavg. The common-cause share is what the PFDavg would
  fall by if the groups' shared causes never struck; the rest is shared among
  the components, a redundant pair splitting its coincident downtime half
  and half. (Before 0.17 the app showed Fussell–Vesely here, which gives each
  member of a redundant pair the pair's whole overlap and the common cause
  inside each member's share, so the shares added up to more than 100%.)
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
            result = getattr(rbd, method)(**overrides)
    except (NotImplementedError, ValueError) as exc:
        return None, plain_reason(str(exc))
    if method == "pfd_breakdown":
        # Each component's and each group's share as a fraction of the PFDavg.
        result = getattr(result, "fractions", result)
    return dict(result), None


def pfd_shares(rbd, graph: dict, overrides: Optional[dict] = None) -> Optional[dict]:
    """The elements' and common-cause groups' shares of a safety function's
    PFDavg and of its dangerous failures, from ``rbd`` (the RepairableRBD the
    PFDavg came from), largest share of the PFDavg first. None when
    RePyability gives neither measure."""
    overrides = {k: v for k, v in (overrides or {}).items() if k in ("working_nodes", "broken_nodes") and v}
    nodes = {n.get("id"): n for n in graph.get("nodes") or []}
    labels = {nid: (n.get("data") or {}).get("label") or str(nid) for nid, n in nodes.items()}
    skip = {nid for nid, n in nodes.items() if n.get("type") in _GATE_TYPES}
    pfd, pfd_reason = _measure(rbd, "pfd_breakdown", overrides)
    bp, bp_reason = _measure(rbd, "barlow_proschan_importance", overrides)
    if pfd is None and bp is None:
        return None

    elements: list[dict[str, Any]] = []
    for nid in rbd.components:
        if nid in skip or nid not in nodes:
            continue
        elements.append({
            "id": str(nid),
            "label": labels.get(nid, str(nid)),
            "pfd_share": _f(pfd.get(nid)) if pfd is not None else None,
            "failure_share": _f(bp.get(nid)) if bp is not None else None,
        })
    # A group is keyed by the tuple of its members in both measures; matched
    # as a set, so the two needn't list them in the same order.
    by_members: dict[frozenset, dict[str, Any]] = {}
    for measure, field in ((bp, "failure_share"), (pfd, "pfd_share")):
        for key, value in (measure or {}).items():
            if not isinstance(key, tuple):
                continue
            row = by_members.setdefault(frozenset(key), {
                "members": [str(m) for m in key],
                "label": " + ".join(labels.get(m, str(m)) for m in key),
                "pfd_share": None,
                "failure_share": None,
            })
            row[field] = _f(value)
    groups = list(by_members.values())
    elements.sort(key=lambda r: (-(r["pfd_share"] if r["pfd_share"] is not None else -1),
                                 -(r["failure_share"] or 0)))
    out: dict[str, Any] = {"elements": elements, "common_cause": groups}
    if pfd is None:
        out["pfd_share_reason"] = pfd_reason
    if bp is None:
        out["failure_share_reason"] = bp_reason
    return out
