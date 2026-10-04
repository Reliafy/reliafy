"""The repairable ``analyze_rbd`` answer an agent reads (#184, #185, #186).

The MCP server lays an availability payload out (``_availability_summary``)
and this module finishes it so it says plainly what it holds:

* a diagram whose figures only the simulation gives, asked with no
  simulation, answers ``available: false`` with the reason and
  ``needs_simulation`` — not ``available: true`` and a page of nulls (#184);
* a headline ``availability`` with its basis (exact or simulation) and, for a
  simulation, its interval (#186);
* a reason shared by several refused routes is given once, in
  ``exact.refused`` (#186); the routes keep their ``route`` and point to it;
* an importance table with nothing computed becomes ``{}`` and one
  ``importance_note`` (#186);
* common-cause groups the availability figures leave out are said beside
  them and in ``warnings`` (#185).

Fields are only added (or emptied where they held only nulls), never renamed,
so existing clients keep working.
"""

from __future__ import annotations

import re
from typing import Optional

#: Figures a simulation-only diagram can't give without the simulation.
_FIGURES = ("steady_state_availability", "unavailability", "mean_up_time", "mean_down_time",
            "failure_frequency", "figures_basis", "importance", "t_simulation")
_SEE_REFUSED = "Refused: see exact.refused for why."
_SIMULATE = ("Call analyze_rbd with simulate=true to run it (or export_rbd_python to run it locally), or change "
             "what makes it simulation-only.")


def has_figures(payload: dict) -> bool:
    """Whether a payload holds any figure: a simulation, the exact long-run
    availability, or the figures over time (computed, or on request)."""
    exact = payload.get("exact") or {}
    return bool(payload.get("has_simulation")) or payload.get("steady_state_availability") is not None \
        or exact.get("status") in ("ok", "on_request")


def _blocker(payload: dict) -> Optional[str]:
    """Why the exact figures aren't there, once."""
    method = payload.get("long_run_method") or {}
    if method.get("route") == "refused" and method.get("reason"):
        return method["reason"]
    routes = (payload.get("exact") or {}).get("routes") or {}
    for key in ("mean_availability", "point_availability", "expected_events"):
        r = routes.get(key) or {}
        if r.get("route") == "refused" and r.get("reason"):
            return r["reason"]
    return None


def _collapse_routes(out: dict) -> None:
    """``exact.refused``: each reason shared by refused routes, once, with the
    routes it refuses; those routes (and ``exact.message`` and
    ``long_run_method.reason`` when they only repeat it) point to it."""
    exact = out.get("exact")
    if not isinstance(exact, dict) or not isinstance(exact.get("routes"), dict):
        return
    groups: dict[str, list[str]] = {}
    for key, r in exact["routes"].items():
        if r.get("route") == "refused" and r.get("reason"):
            groups.setdefault(r["reason"], []).append(key)
    if not groups:
        return
    exact["refused"] = [{"reason": reason, "routes": keys} for reason, keys in groups.items()]
    for keys in groups.values():
        for key in keys:
            exact["routes"][key] = {**exact["routes"][key], "reason": _SEE_REFUSED}
    message = exact.get("message")
    if isinstance(message, str):
        for reason in groups:
            if reason in message and message.strip() != reason.strip():
                exact["message"] = message.replace(reason, "").strip() + " (Why: exact.refused.)"
                break
    method = out.get("long_run_method")
    if isinstance(method, dict) and method.get("reason") in groups:
        out["long_run_method"] = {**method, "reason": _SEE_REFUSED}


def _empty_importance(importance) -> bool:
    if not isinstance(importance, dict) or not importance:
        return False
    for row in importance.values():
        if not isinstance(row, dict):
            return False
        if any(v is not None for k, v in row.items() if k not in ("label", "pinned")):
            return False
    return True


def _headline(out: dict, payload: dict) -> Optional[dict]:
    """``availability``: the one figure to quote, and what it is."""
    steady = payload.get("steady_state_availability")
    if steady is not None:
        method = (payload.get("long_run_method") or {}).get("route")
        return {"value": steady, "basis": "exact",
                "method": method if method in ("exact", "numerical") else "exact",
                "what": "the long-run (steady-state) availability"}
    precision = payload.get("precision") or {}
    if payload.get("has_simulation") and precision.get("window_availability") is not None:
        # RePyability 0.12: the window's mean is exact where it can be (the
        # interval stays the simulation's).
        window_basis = precision.get("window_availability_basis") or "simulation"
        exact_window = window_basis in ("exact", "numerical")
        return {"value": precision["window_availability"], "basis": "exact" if exact_window else "simulation",
                **({"method": window_basis} if exact_window else {}),
                "lower": precision.get("lower"), "upper": precision.get("upper"),
                "confidence": precision.get("confidence"),
                "what": (f"the mean availability over the simulated window of {payload.get('t_simulation'):g} "
                         f"{payload.get('unit') or ''}".rstrip() if payload.get("t_simulation") else
                         "the mean availability over the simulated window")}
    exact = payload.get("exact") or {}
    if exact.get("status") == "ok" and exact.get("mission_availability") is not None:
        return {"value": exact["mission_availability"], "basis": "exact",
                "method": (exact.get("method") or {}).get("mission_availability"),
                "what": f"the mean availability over the window of {exact.get('window'):g} "
                        f"{exact.get('unit') or ''}".rstrip()}
    return None


def finish(out: dict, payload: dict) -> dict:
    """The repairable ``analyze_rbd`` answer, finished (see the module
    docstring). ``out`` is the MCP layout of ``payload``, with the head
    fields and ``simulation``; returns the answer to send."""
    out = dict(out)
    if isinstance(out.get("exact"), dict):
        out["exact"] = dict(out["exact"])
        if isinstance(out["exact"].get("routes"), dict):
            out["exact"]["routes"] = {k: dict(v) for k, v in out["exact"]["routes"].items()}

    # #185: common-cause groups the figures leave out, beside them and as a warning.
    common = payload.get("common_cause")
    if common:
        out["common_cause"] = common
        if common.get("note"):
            out["warnings"] = [*(out.get("warnings") or []), common["note"]]

    # #184: nothing computed — say so at the top, without the empty figures.
    if not has_figures(payload):
        blocker = re.sub(r"\s*Simulate (?:the system|it|them)\.\s*$", "", _blocker(payload) or "")
        out["available"] = False
        out["needs_simulation"] = True
        out["code"] = "needs_simulation"
        out["reason"] = ("This diagram's figures need the simulation, which wasn't run (simulate=false, and no "
                         "saved result matches the diagram as it is now). " + (f"{blocker} " if blocker else "")
                         + _SIMULATE)
        for key in _FIGURES:
            out.pop(key, None)
        _collapse_routes(out)
        return out

    # #186: one reason once; no table of nulls; the headline figure.
    _collapse_routes(out)
    if _empty_importance(out.get("importance")):
        out["importance"] = {}
        out["importance_note"] = (
            "Importance measures need the exact long-run values, which this diagram doesn't have (see "
            "long_run_method)" + ("; the simulation's criticality indices (criticality) rank the blocks instead."
                                  if out.get("criticality") else
                                  "; run the simulation (simulate=true) for its criticality indices."))
    headline = _headline(out, payload)
    if headline is not None:
        if common:
            headline["common_cause_included"] = False
            if common.get("availability_with_common_cause") is not None:
                headline["with_common_cause"] = common["availability_with_common_cause"]
        out["availability"] = headline
    return out
