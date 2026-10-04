""""Download as Python" for repairable blocks with costs, instant repair and
maintenance (#99, #100): the RePyability component specs, the system downtime
cost, and the cost report — so the script reproduces the app's cost rate,
total cost of ownership and simulated window cost, and still runs when the
exact long-run values don't exist (limited repair crews for wear-out
lives, say).

A diagram without any of these exports exactly as before: every hook below
expands to the original text.
"""

from __future__ import annotations

from typing import Optional

from backend.services import rbd_analysis
from backend.services import rbd_maintenance as rm
from backend.services.rbd_analysis import AnalysisError


def uses_extras(graph: dict) -> bool:
    """Whether any block (or the diagram) carries costs or maintenance, or
    the diagram has repair crews, maintenance groups, standby groups or a
    safety function (#156, #157): anything whose exact values may not exist."""
    if (graph.get("costs") or {}).get("downtime_rate") or (graph.get("costs") or {}).get("horizon"):
        return True
    if any(graph.get(k) for k in ("repair_crews", "maintenance_groups", "safety_function")):
        return True
    return any(
        rm.has_extras(n.get("data") or {}) or n.get("type") == "standby"
        for n in graph.get("nodes") or []
        if n.get("type") in ("component", "standby")
    )


def _duration(script, raw, label: str, var: str) -> str:
    """The expression for a maintenance/test duration."""
    from backend.services.rbd_export import _num

    if rm._blank(raw) or raw == "instant":
        return '"instant"'
    if isinstance(raw, dict):
        return script.dist(raw, label, var)
    value = float(raw)
    if not value:
        return '"instant"'
    script.uses_surv = True
    return f"surv.ExactEventTime.from_params({_num(value)})"


def _cost(script, value) -> str:
    """The expression for a validated cost: a number, or a range drawn
    uniformly at each action (surpyval's ``Uniform``)."""
    from backend.services.rbd_export import _num

    if isinstance(value, float):
        return _num(value)
    low, high = (float(p) for p in value.params)
    script.uses_surv = True
    return f"surv.Uniform.from_params([{_num(low)}, {_num(high)}])"


def component(script, data: dict, label: str, var: str, life: str, repair: str) -> None:
    """Emit ``var = {...}``: a RePyability component spec with the block's
    costs and maintenance (``repair`` is its repair model's variable, or
    ``'"instant"'``)."""
    from backend.services.rbd_export import _lit, _num

    L = script.lines
    try:
        costs = rm.block_costs(data, label)
        pm = rm.preventive_spec(data, label) if data.get("preventive") else None
        test = rm.inspection_spec(data, label) if data.get("inspection") else None
    except AnalysisError as exc:
        script.missing(var, str(exc), label)
        return
    entries: list[str] = [f'"reliability": {life}', f'"repairability": {repair}']
    entries += [f"{_lit(k)}: {_cost(script, v)}" for k, v in costs.items()]
    for key, spec, raw in (("preventive", pm, data.get("preventive")),
                           ("inspection", test, data.get("inspection"))):
        if not spec:
            continue
        duration = _duration(script, (raw or {}).get("duration"), f"{label} ({key} duration)",
                             script.names.make(f"{var}_{key}_time"))
        parts = [f'"interval": {_num(spec["interval"])}']
        if key == "preventive":
            parts.append(f'"policy": {_lit(spec["policy"])}')
        parts.append(f'"duration": {duration}')
        if spec.get("cost") is not None:
            parts.append(f'"cost": {_cost(script, spec["cost"])}')
        # Condition-based replacement, opportunistic renewal (#157), staggered
        # and imperfect proof tests (#136).
        for extra in ("threshold", "opportunity", "offset", "coverage", "full_test"):
            if spec.get(extra) is not None:
                parts.append(f'"{extra}": {_num(spec[extra])}')
        if spec.get("inspection_cost") is not None:
            parts.append(f'"inspection_cost": {_cost(script, spec["inspection_cost"])}')
        entries.append(f'"{key}": {{' + ", ".join(parts) + "}")
    try:
        group = rm.maintenance_group(data, label)
        priority = rm.crew_priority(data, label)
    except AnalysisError as exc:
        script.missing(var, str(exc), label)
        return
    if group is not None:
        entries.append(f'"group": {_lit(group)}')
    if priority is not None:
        entries.append(f'"priority": {_num(priority)}')
    if data.get("inspection"):
        L.append("# Hidden failures: found only at the proof tests below.")
    if (pm or {}).get("policy") == "condition":
        L.append("# Replaced on condition: inspected every interval, replaced when more likely")
        L.append("# than the threshold to fail before the next inspection.")
    _emit(script, var, entries)


def _emit(script, var: str, entries: list[str]) -> None:
    L = script.lines
    if any("surv.Uniform.from_params(" in e for e in entries):
        L.append("# A cost given as a range is drawn uniformly afresh at each action.")
    L.append(f"{var} = {{")
    L.extend(f"    {e}," for e in entries)
    L.append("}")


def standby(script, nid, data: dict, label: str, var: str, life: str, repair: str) -> None:
    """Emit a standby group (#156): ``var = {...}`` with a ``"standby"`` spec,
    or, repaired one unit at a time, a one-node RepairableRBD with one crew."""
    from backend.services import rbd_policies
    from backend.services.rbd_export import _lit, _num

    try:
        spec = rbd_policies.standby_spec(data, label, life, repair)
    except AnalysisError as exc:
        script.missing(var, str(exc), label)
        return
    group = spec.pop("standby")
    entries = [f'"reliability": {life}', f'"repairability": {repair}']
    entries += [f"{_lit(k)}: {_cost(script, v) if k != 'priority' else _num(v)}"
                for k, v in spec.items() if k not in ("reliability", "repairability")]
    entries.append('"standby": {' + ", ".join(f'"{k}": {_num(v)}' for k, v in group.items()) + "}")
    L = script.lines
    L.append(f"# A standby group: {group['units']} identical units, one operating; each failed unit is")
    if not data.get("repair_one_at_a_time"):
        L.append("# repaired on its own (a job for the repair crews).")
        _emit(script, var, entries)
        return
    L.append("# repaired by the group's own repairer, one unit at a time: a sub-diagram")
    L.append("# with one repair crew.")
    entries = [e for e in entries if not e.startswith('"priority"')]
    spec_var = script.names.make(f"{var}_units")
    _emit(script, spec_var, entries)
    L.append(f"{var} = RepairableRBD([('in', {_lit(nid)}), ({_lit(nid)}, 'out')], "
             f"{{{_lit(nid)}: {spec_var}}}, repair_crews=1)")


def rbd_kwargs(graph: dict) -> list[str]:
    """Extra ``RepairableRBD(...)`` arguments: the system downtime cost, the
    repair crews and the maintenance groups' options."""
    from backend.services import rbd_policies
    from backend.services.rbd_export import _num

    try:
        rate = rm.downtime_cost_rate(graph)
    except AnalysisError:
        rate = 0.0
    out = [f"downtime_cost_rate={_num(rate)}"] if rate else []
    try:
        crews = rbd_policies.repair_crews(graph)
    except AnalysisError:
        crews = None
    if crews is not None:
        out.append(f"repair_crews={crews}")
    groups = maintenance_groups(graph)
    if groups:
        out.append("maintenance_groups=MAINTENANCE_GROUPS")
    return out


def maintenance_groups(graph: dict) -> dict:
    """The maintenance groups' options for the groups some block is in."""
    from backend.services import rbd_policies

    members: dict[str, list] = {}
    for n in graph.get("nodes") or []:
        if n.get("type") != "component":
            continue
        try:
            group = rm.maintenance_group(n.get("data") or {}, n.get("id"))
        except AnalysisError:
            group = None
        if group is not None:
            members.setdefault(group, []).append(n.get("id"))
    try:
        return rbd_policies.maintenance_groups(graph, members) or {}
    except AnalysisError:
        return {}


def diagram_lines(graph: dict) -> list[str]:
    """``MAINTENANCE_GROUPS = {...}`` when the diagram has group options."""
    from backend.services.rbd_export import _lit, _num

    groups = maintenance_groups(graph)
    if not groups:
        return []
    out = ["# Maintenance groups: a set-up cost charged once per stop of the group, at",
           "# which members old enough (their opportunity age) are renewed too.",
           "MAINTENANCE_GROUPS = {"]
    for name, options in groups.items():
        out.append(f"    {_lit(name)}: {{\"setup_cost\": {_num(options['setup_cost'])}, "
                   f"\"system_down\": {options['system_down']!r}}},")
    out.append("}")
    return out


def constants(graph: dict) -> list[str]:
    """The ownership horizon the total cost is taken over."""
    from backend.services.rbd_export import _num

    try:
        horizon = rm.diagram_costs(graph)["horizon"]
    except AnalysisError:
        horizon = None
    return [
        "# How long the system is owned, for the total cost of ownership (None:",
        "# the simulated window, as in Reliafy).",
        f"HORIZON = {_num(horizon) if horizon else None}",
    ]


# Hooks in the repairable main(): (original text, replacement with extras).
_EXACT = '''    # Exact long-run figures (independent blocks; Birnbaum/Vesely formula).
    with np.errstate(all="ignore"):
        availability = float(rbd.mean_availability(**overrides))
        mean_up = float(rbd.mean_up_time(**overrides))
        mean_down = float(rbd.mean_down_time(**overrides))
        frequency = float(rbd.system_failure_frequency(**overrides))
        birnbaum = rbd.birnbaum_importance(**overrides)
'''
_EXACT_OR_NOT = '''    # Exact long-run figures (independent blocks; Birnbaum/Vesely formula).
    # Some diagrams (limited repair crews for wear-out lives, say) have
    # none: the simulation gives them.
    try:
        with np.errstate(all="ignore"):
            availability = float(rbd.mean_availability(**overrides))
            mean_up = float(rbd.mean_up_time(**overrides))
            mean_down = float(rbd.mean_down_time(**overrides))
            frequency = float(rbd.system_failure_frequency(**overrides))
            birnbaum = rbd.birnbaum_importance(**overrides)
    except NotImplementedError:
        availability = mean_up = mean_down = frequency = float("nan")
        birnbaum = {n: float("nan") for n in LABELS}
'''
_TOLERANCE = '''    tolerance = availability_tolerance(1.0 - availability)
'''
_TOLERANCE_OR_PILOT = '''    tolerance = availability_tolerance(
        1.0 - availability if np.isfinite(availability) else pilot_unavailability(overrides))
'''
_NODES = '''    node_availability = rbd.node_availability()
'''
_NODES_OR_NOT = '''    try:
        node_availability = rbd.node_availability()
    except NotImplementedError:
        node_availability = {n: float("nan") for n in blocks}
'''
_RERUN = '''    if availability < 1.0 and not sim.system_downtime > 0 and sim.n_simulations < max_n:
'''
_RERUN_NAN = '''    if not availability >= 1.0 and not sim.system_downtime > 0 and sim.n_simulations < max_n:
'''
_SAVE = '''    save_results(results)
'''
_SAVE_COSTS = '''    if rbd.has_costs or rbd.acquisition_cost:
        results["costs"] = report_costs(sim, overrides)
    save_results(results)
'''

_HELPERS = '''
def pilot_unavailability(overrides):
    """A quick simulated unavailability (as Reliafy sets the precision target
    when there is no exact value)."""
    run = dict(t_simulation=T_SIMULATION, method="c", seed=1, control_variate=False, conditional=False)
    try:
        pilot = rbd.availability(mc_samples=PILOT_SIMS, antithetic=True, **run, **overrides)
    except NotImplementedError:
        pilot = rbd.availability(mc_samples=PILOT_SIMS, **run, **overrides)
    return 1.0 - pilot.system_uptime / (pilot.n_simulations * T_SIMULATION)


def report_costs(sim, overrides):
    """The long-run cost rate (exact where RePyability has it), the total cost
    of ownership over HORIZON, and the simulated cost of the window."""
    unit = f" per {UNIT.rstrip('s')}" if UNIT else " per unit time"
    try:
        with np.errstate(all="ignore"):
            rate, basis = float(rbd.expected_cost_rate(**overrides)), "exact"
    except NotImplementedError:
        rate = sim.cost.cost_rate if sim.cost is not None else float("nan")
        basis = "simulation"
    horizon = HORIZON if HORIZON else T_SIMULATION
    total = rbd.acquisition_cost + rate * horizon
    print(f"\\nLong-run cost rate ({basis}): {rate:,.6g}{unit}")
    print(f"Total cost of ownership over {horizon:,.6g}: {total:,.6g} "
          f"(purchase {rbd.acquisition_cost:,.6g} + running {rate * horizon:,.6g})")
    out = {"cost_rate": rate, "cost_rate_basis": basis, "horizon": horizon,
           "acquisition_cost": rbd.acquisition_cost, "total_cost": total}
    if sim.cost is not None:
        cost = sim.cost
        window = cost.mean_interval(CONFIDENCE)
        p10, p50, p90 = (cost.percentile(q) for q in (10, 50, 90))
        print(f"  simulated cost of the window: {cost.mean:,.6g} ({CONFIDENCE:.0%} CI "
              f"{window.lower:,.6g} to {window.upper:,.6g}); P10 {p10:,.6g}, "
              f"P50 {p50:,.6g}, P90 {p90:,.6g}")
        for category, value in cost.by_category.items():
            if value:
                print(f"    {category.replace('_', ' ')}: {value:,.6g}")
        # The window's mean cost, exact where RePyability works it out (as
        # in Reliafy); the interval and percentiles stay the simulation's.
        # Above EXACT_WINDOW_MEAN_MAX_BLOCKS blocks Reliafy reports the
        # simulated mean (the exact one takes too long), and so does this.
        mean, mean_basis = (window_mean(overrides, "expected_cost") if rbd.has_costs
                            else (None, "simulation"))
        if mean is not None:
            print(f"  expected cost of the window ({mean_basis}): {mean:,.6g}")
        elif N_BLOCKS > EXACT_WINDOW_MEAN_MAX_BLOCKS:
            print(f"  (the simulated mean cost stands, as in Reliafy: {N_BLOCKS} blocks is "
                  f"more than the {EXACT_WINDOW_MEAN_MAX_BLOCKS} its exact window mean is computed for)")
        out["simulated"] = {
            "mean": cost.mean if mean is None else mean, "mean_basis": mean_basis,
            "simulated_mean": cost.mean, "lower": window.lower, "upper": window.upper,
            "percentiles": {"10": p10, "50": p50, "90": p90},
            "by_category": dict(cost.by_category),
        }
    return out
'''


_SAVE_SAFETY = '''    results["long_run_method"] = long_run_method()
    results["safety"] = report_safety(sim, overrides)
'''

_SAFETY_HELPERS = '''
def long_run_method():
    """How RePyability finds the long-run values: exact, numerical, simulated
    or refused (e.g. the repair crews' Markov chain), and why."""
    route = rbd.analysis_routes()["mean_availability"]
    print(f"\\nLong-run values: {route.route} - {route.reason}")
    return {"route": route.route, "reason": route.reason}


def sil_band(pfd):
    """The SIL a low-demand PFDavg falls in (IEC 61508-1), or None."""
    for sil, low, high in SIL_BANDS:
        if pfd < high and (pfd >= low or sil == 4):
            return sil
    return None


def report_safety(sim, overrides):
    """The safety function's PFDavg: its long-run unavailability, averaged over
    the proof-test cycle, with its common-cause groups (RBD_CCF) where
    RePyability's chain covers them; else without them, else simulated."""
    pfd, basis, ccf = None, None, False
    if RBD_CCF is not None:
        try:
            pfd = float(RBD_CCF.mean_unavailability(**overrides))
            basis, ccf = RBD_CCF.analysis_routes()["mean_unavailability"].route, True
        except (NotImplementedError, ValueError) as exc:
            print(f"(Common cause left out of the PFDavg: {exc})")
    if pfd is None:
        try:
            pfd = float(rbd.mean_unavailability(**overrides))
            basis = rbd.analysis_routes()["mean_unavailability"].route
        except NotImplementedError:
            pfd = 1.0 - sim.system_uptime / (sim.n_simulations * T_SIMULATION)
            basis = "simulated"
    sil = sil_band(pfd)
    print(f"PFDavg ({basis}{', with common cause' if ccf else ''}): {pfd:.4g}"
          f" -> {'SIL ' + str(sil) if sil else 'no SIL band'}"
          + (f" (target SIL {TARGET_SIL}: {'met' if sil and sil >= TARGET_SIL else 'NOT met'})"
             if TARGET_SIL else ""))
    return {"pfd_avg": pfd, "basis": basis, "common_cause": ccf, "sil": sil, "target_sil": TARGET_SIL}
'''


def safety_constants(graph: dict, ccf_expr: Optional[str]) -> list[str]:
    """The SIL bands and target, and the twin with common cause, for a safety
    function's PFDavg (#136)."""
    from backend.services import rbd_policies

    try:
        target = rbd_policies.target_sil(graph)
    except AnalysisError:
        target = None
    bands = ", ".join(f"({s}, {lo!r}, {hi!r})" for s, lo, hi in rbd_policies.SIL_BANDS)
    return [
        "# A safety function: SIL bands of a low-demand PFDavg (IEC 61508-1), and the",
        "# SIL it must meet (None: no target).",
        f"SIL_BANDS = ({bands})",
        f"TARGET_SIL = {target}",
        "# The same diagram with its common-cause groups, for the PFDavg (RePyability's",
        "# simulation doesn't take them in, so the availability figures leave them out).",
        f"RBD_CCF = {ccf_expr or 'None'}",
    ]


def main_source(template: str, graph: dict) -> str:
    """The repairable ``main()`` (and helpers): unchanged for a diagram without
    costs or maintenance."""
    if not uses_extras(graph):
        return template
    out = template
    hooks = [(_EXACT, _EXACT_OR_NOT), (_TOLERANCE, _TOLERANCE_OR_PILOT),
             (_NODES, _NODES_OR_NOT), (_SAVE, _SAVE_COSTS), (_RERUN, _RERUN_NAN)]
    helpers = _HELPERS
    if graph.get("safety_function"):
        hooks.append((_SAVE, _SAVE_SAFETY + _SAVE))
        helpers += _SAFETY_HELPERS
    for old, new in hooks:
        assert out.count(old) == 1, old
        out = out.replace(old, new)
    marker = "\ndef main():"
    return out.replace(marker, helpers.rstrip("\n") + "\n\n" + marker, 1)


def pilot_constant() -> list[str]:
    return [f"PILOT_SIMS = {5 * rbd_analysis._AVAIL_PILOT_SIMS}"]

