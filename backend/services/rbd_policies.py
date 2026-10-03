"""Diagram-level settings of a repairable RBD on RePyability 0.11 (#156,
#157): repair crews, maintenance groups, standby groups, and the PFDavg and
SIL band of a safety function.

Graph format (all optional; a diagram without any of them is built exactly as
before)::

    graph["repair_crews"] = {"crews": 2}       # at most 2 jobs at once (#89, #90)
    graph["maintenance_groups"] = {            # opportunistic maintenance (#108)
        "north pumps": {"setup_cost": 2000,    #   charged once per group stop
                        "system_down": false}, #   every system outage is a stop
    }
    graph["safety_function"] = true            # report PFDavg and its SIL band
    graph["target_sil"] = 2                    #   (optional) the SIL it must meet

    # A standby node in a repairable diagram (#91): a duty unit plus spares,
    # identical units each repaired on its own (a job for the crews).
    node.data = {"model": {...}, "repair": {...}, "spares": 2,
                 "dormancy": 0,                # 0 cold, 1 hot, between warm
                 "startProb": 0.98,            # cold: the switch succeeds
                 "repair_one_at_a_time": true, # its own repairer: one unit at a time
                 "costs": {...}, "crew_priority": 1}

Block fields (preventive, inspection, maintenance group, crew priority) are
in :mod:`backend.services.rbd_maintenance`.

RePyability 0.11 gives a diagram one pool of crews: every component (and each
unit of a standby group) is a job for it, in order of ``crew_priority`` and
then of when it fell due. A standby group repaired one unit at a time is its
own sub-diagram with one crew, so it doesn't wait for the diagram's crews.
"""

from __future__ import annotations

from typing import Any, Optional

import numpy as np

from backend.services import rbd_maintenance as rm
from backend.services.rbd_analysis import AnalysisError, _f

#: The most repair crews a diagram can name (more than any block count we draw).
MAX_CREWS = 1000
#: SIL bands for a low-demand safety function (IEC 61508-1 table 2):
#: (SIL, lowest PFDavg, highest PFDavg), the band including its lower end.
SIL_BANDS = ((4, 1e-5, 1e-4), (3, 1e-4, 1e-3), (2, 1e-3, 1e-2), (1, 1e-2, 1e-1))
GROUP_KEYS = ("setup_cost", "system_down")
_STANDBY_EXTRAS = ("preventive", "inspection", "maintenance_group")


def _whole(value) -> Optional[int]:
    if isinstance(value, bool):
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return int(x) if np.isfinite(x) and x == int(x) else None


# ---------------------------------------------------------------------------
# Repair crews (#156)
# ---------------------------------------------------------------------------
def repair_crews(graph: dict) -> Optional[int]:
    """The number of repair crews, or None for as many as are needed."""
    raw = graph.get("repair_crews")
    if isinstance(raw, dict):
        raw = raw.get("crews")
    if raw is None or raw is False or (isinstance(raw, str) and not raw.strip()):
        return None
    n = _whole(raw)
    if n is None or not 1 <= n <= MAX_CREWS:
        raise AnalysisError(
            "The number of repair crews must be a whole number, 1 or more (leave it blank for as "
            "many as are needed).")
    return n


# ---------------------------------------------------------------------------
# Maintenance groups (#108)
# ---------------------------------------------------------------------------
def group_options(graph: dict) -> dict:
    """The diagram's maintenance-group options, validated: ``{name:
    {"setup_cost": float, "system_down": bool}}``."""
    raw = graph.get("maintenance_groups")
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise AnalysisError("The diagram's maintenance groups must be an object of group names.")
    out: dict[str, dict] = {}
    for name, options in raw.items():
        where = f"Maintenance group “{name}”"
        options = options or {}
        if not isinstance(options, dict):
            raise AnalysisError(f"{where}: its options must be an object (setup_cost, system_down).")
        unknown = set(options) - set(GROUP_KEYS)
        if unknown:
            raise AnalysisError(
                f"{where}: unknown option(s) {', '.join(sorted(map(str, unknown)))} — use "
                f"{', '.join(GROUP_KEYS)}.")
        setup = rm._number(options.get("setup_cost"), "set-up cost", str(name))
        down = options.get("system_down", False)
        if down is None:
            down = False
        if not isinstance(down, bool):
            raise AnalysisError(f"{where}: system_down must be true or false.")
        out[str(name).strip()] = {"setup_cost": setup or 0.0, "system_down": down}
    return out


def maintenance_groups(graph: dict, members: dict) -> Optional[dict]:
    """RePyability's ``maintenance_groups`` for the groups some block is in
    (``members``: group -> block ids); options for an empty group are left
    out, as the builder may keep a group whose blocks were removed."""
    options = group_options(graph)
    out = {name: options[name] for name in members if name in options}
    return out or None


# ---------------------------------------------------------------------------
# Standby groups (#156)
# ---------------------------------------------------------------------------
def _same_model(a: Optional[dict], b: Optional[dict]) -> bool:
    if not a or not b:
        return True
    if a.get("modelId") or b.get("modelId"):
        return a.get("modelId") == b.get("modelId")
    pa = {p.get("name"): p.get("value") for p in a.get("params") or []}
    pb = {p.get("name"): p.get("value") for p in b.get("params") or []}
    return a.get("distribution_id") == b.get("distribution_id") and pa == pb


def standby_errors(data: dict, label: str) -> list[str]:
    """What stops a standby node from being a repairable standby group."""
    errors = []
    spares = _whole(data.get("spares") if data.get("spares") is not None else 1)
    if spares is None or spares < 1:
        errors.append(f"“{label}”: a standby group needs a whole number of spares, 1 or more.")
    if data.get("instant_repair"):
        errors.append(
            f"“{label}”: a standby group's units need a repair time — repaired instantly, a spare "
            "would never be needed.")
    if not _same_model(data.get("model"), data.get("standbyModel")):
        errors.append(
            f"“{label}”: in a repairable diagram a standby group's units are identical — remove the "
            "spares' own life model (each unit fails and is repaired by the block's models).")
    for key in _STANDBY_EXTRAS:
        if data.get(key) not in (None, "", {}):
            what = {"preventive": "scheduled replacement", "inspection": "proof tests",
                    "maintenance_group": "a maintenance group"}[key]
            errors.append(f"“{label}”: a standby group takes no {what} (as in RePyability).")
    if data.get("repair_one_at_a_time") and (data.get("costs") or {}):
        errors.append(
            f"“{label}”: a standby group repaired one unit at a time is its own sub-diagram, whose "
            "costs RePyability doesn't count in the diagram's — remove its costs, or let the "
            "diagram's repair crews repair it.")
    return errors


def standby_spec(data: dict, label: str, reliability, repair) -> dict:
    """The block's RePyability component spec as a standby group: ``1 +
    spares`` identical units, one operating."""
    from backend.services.rbd_analysis import _standby_dormancy

    errors = standby_errors(data, label)
    if errors:
        raise AnalysisError(errors[0])
    dormancy = _standby_dormancy(data, label)
    switching = 1.0
    if dormancy == 0.0 and data.get("startProb") not in (None, ""):
        switching = rm._probability(data.get("startProb"), "switch-in probability", label)
    spec: dict[str, Any] = {
        "reliability": reliability,
        "repairability": repair,
        "standby": {
            "units": 1 + _whole(data.get("spares") if data.get("spares") is not None else 1),
            "k": 1,
            "dormancy_factor": dormancy,
            "switching_probability": switching,
        },
    }
    spec.update(rm.block_costs(data, label))
    priority = rm.crew_priority(data, label)
    if priority is not None:
        spec["priority"] = priority
    return spec


def standby_component(nid, data: dict, label: str, reliability, repair):
    """A standby node of a repairable diagram: the group's spec, or, repaired
    one unit at a time, a one-node sub-diagram with a single crew."""
    from repyability import RepairableRBD

    spec = standby_spec(data, label, reliability, repair)
    if not data.get("repair_one_at_a_time"):
        return spec
    spec.pop("priority", None)  # its own crew: no queue with the diagram's jobs
    return RepairableRBD([("in", nid), (nid, "out")], {nid: spec}, repair_crews=1)


# ---------------------------------------------------------------------------
# Safety functions: PFDavg and SIL (#136)
# ---------------------------------------------------------------------------
def target_sil(graph: dict) -> Optional[int]:
    raw = graph.get("target_sil")
    if raw in (None, "", False):
        return None
    n = _whole(raw)
    if n is None or not 1 <= n <= 4:
        raise AnalysisError("The target SIL must be 1, 2, 3 or 4.")
    return n


def sil_band(pfd: Optional[float]) -> Optional[int]:
    """The SIL a low-demand PFDavg falls in (4 also below its band), or None
    (PFDavg of 0.1 or more: no SIL)."""
    if pfd is None or not np.isfinite(pfd):
        return None
    for sil, low, high in SIL_BANDS:
        if pfd < high and (pfd >= low or sil == 4):
            return sil
    return None


def _route_basis(rbd) -> tuple[str, str]:
    try:
        route = rbd.analysis_routes()["mean_unavailability"]
        return route.route, route.reason
    except Exception:  # noqa: BLE001
        return "exact", ""


def safety_summary(graph: dict, rbd, resolve_model, overrides: dict, steady, res,
                   t_sim: float) -> Optional[dict]:
    """PFDavg of a diagram marked as a safety function: its long-run
    unavailability (the mean over the proof-test cycle), with its common-cause
    groups (#136) where RePyability's chain covers them, and the SIL band."""
    if not graph.get("safety_function"):
        return None
    from backend.services import rbd_analysis as ra

    groups = [g for g in graph.get("ccf_groups") or [] if len(g.get("members") or []) >= 2]
    out: dict[str, Any] = {"target_sil": target_sil(graph), "common_cause": None}
    pfd = basis = reason = None
    if groups:
        note = None
        try:
            twin = ra._build_repairable_rbd(graph, resolve_model, with_ccf=True)[0]
            with np.errstate(all="ignore"):
                pfd = float(twin.mean_unavailability(**overrides))
            basis, reason = _route_basis(twin)
        except (NotImplementedError, ValueError, AnalysisError) as exc:
            note = str(exc)
        out["common_cause"] = {"groups": len(groups), "included": pfd is not None, "note": note}
    if pfd is None and steady is not None:
        try:
            with np.errstate(all="ignore"):
                pfd = float(rbd.mean_unavailability(**overrides))
            basis, reason = _route_basis(rbd)
        except (NotImplementedError, ValueError):
            pfd = None
    if pfd is None and res is not None and getattr(res, "n_simulations", 0) and t_sim:
        pfd = 1.0 - float(res.system_uptime) / (res.n_simulations * t_sim)
        basis, reason = "simulated", "The simulated window's mean unavailability."
    tested = rm.maintained_blocks(graph)
    tests = [(n.get("data") or {}).get("inspection") or {} for n in tested]
    out.update(
        pfd_avg=ra._f(pfd) if pfd is not None else None,
        basis=basis,
        reason=reason,
        sil=sil_band(pfd),
        proof_tested_blocks=sum(1 for t in tests if t),
        staggered=any(t.get("offset") not in (None, "", 0) for t in tests),
        imperfect_tests=any(t.get("coverage") not in (None, "") and float(t["coverage"]) < 1
                            for t in tests),
    )
    if out["target_sil"] is not None:
        out["meets_target"] = out["sil"] is not None and out["sil"] >= out["target_sil"]
    return out


# ---------------------------------------------------------------------------
# How the long-run values are found, and the crews' share of the work
# ---------------------------------------------------------------------------
def long_run_method(rbd, labels: dict) -> Optional[dict]:
    """How RePyability 0.11 finds the long-run values (``analysis_routes``):
    exactly, numerically, by simulation or not at all, why, and the blocks
    that decide it."""
    try:
        route = rbd.analysis_routes()["mean_availability"]
    except Exception:  # noqa: BLE001
        return None
    return {"route": route.route, "reason": route.reason,
            "blocks": [labels.get(n, str(n)) for n in route.nodes or ()]}


def crews_summary(rbd, graph: dict, labels: dict, gate_ids: set) -> Optional[dict]:
    """The repair crews and the jobs they share, for the result."""
    crews = rbd.repair_crews
    if crews is None:
        return None
    jobs = [k for k in rbd._crew_served() if getattr(k, "node", k) not in gate_ids]
    owners = {getattr(k, "node", k) for k in jobs}
    priority = {labels.get(n, str(n)): p for n, p in rbd._priority.items() if p}
    own = [labels.get(n["id"], n["id"]) for n in graph.get("nodes") or []
           if n.get("type") == "standby" and (n.get("data") or {}).get("repair_one_at_a_time")]
    return {"crews": crews, "jobs": len(jobs), "blocks": len(owners),
            "limited": crews < len(jobs), "priorities": priority, "own_repairer": own}


def result_extras(rbd, graph: dict, resolve_model, labels: dict, gate_ids: set, overrides: dict,
                  steady, res, t_sim: float) -> dict:
    """What an availability result adds for #156/#157: how the long-run
    values were found, the repair crews, and a safety function's PFDavg."""
    out: dict[str, Any] = {}
    method = long_run_method(rbd, labels)
    if method is not None:
        out["long_run_method"] = method
    crews = crews_summary(rbd, graph, labels, gate_ids)
    if crews is not None:
        out["repair_crews"] = crews
    safety = safety_summary(graph, rbd, resolve_model, overrides, steady, res, t_sim)
    if safety is not None:
        out["safety"] = safety
    renewals = getattr(res, "opportunistic_renewals", None) if res is not None else None
    if renewals and getattr(res, "n_simulations", 0):
        out["opportunistic_renewals"] = {
            labels.get(n, str(n)): _f(v / res.n_simulations) for n, v in renewals.items()}
    return out


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def validation_errors(graph: dict) -> list[str]:
    """Problems with a repairable diagram's crews, groups, standby groups and
    safety settings (the Validate step reports them before Calculate)."""
    errors: list[str] = []
    for check in (repair_crews, group_options, target_sil):
        try:
            check(graph)
        except AnalysisError as exc:
            errors.append(str(exc))
    for node in graph.get("nodes") or []:
        if node.get("type") != "standby":
            continue
        data = node.get("data") or {}
        label = data.get("label") or node.get("id")
        errors.extend(standby_errors(data, label))
        try:
            rm.block_costs(data, label)
            rm.crew_priority(data, label)
        except AnalysisError as exc:
            errors.append(str(exc))
    return errors


def validation_warnings(graph: dict) -> list[str]:
    """Notes on settings that won't change the analysis as drawn."""
    warnings: list[str] = []
    try:
        options = group_options(graph)
    except AnalysisError:
        options = {}
    used = {(n.get("data") or {}).get("maintenance_group") for n in graph.get("nodes") or []}
    for name in options:
        if name not in used:
            warnings.append(f"Maintenance group “{name}” has no blocks, so its set-up cost is never charged.")
    if graph.get("ccf_groups") and not graph.get("safety_function"):
        warnings.append(
            "Common-cause groups enter a repairable diagram only through a safety function's "
            "PFDavg — mark the diagram as a safety function, or they are ignored.")
    elif graph.get("ccf_groups"):
        warnings.append(
            "Common-cause groups enter the safety function's PFDavg (RePyability needs their "
            "members' lives to be exponential); the availability figures and simulation leave "
            "them out.")
    return warnings
