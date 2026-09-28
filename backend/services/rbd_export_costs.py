""""Download as Python" for repairable blocks with costs, instant repair and
maintenance (#99, #100): the RePyability component specs, the system downtime
cost, and the cost report — so the script reproduces the app's cost rate,
total cost of ownership and simulated window cost, and still runs when the
exact long-run values don't exist (block replacement, timed proof tests).

A diagram without any of these exports exactly as before: every hook below
expands to the original text.
"""

from __future__ import annotations

from backend.services import rbd_analysis
from backend.services import rbd_maintenance as rm
from backend.services.rbd_analysis import AnalysisError


def uses_extras(graph: dict) -> bool:
    """Whether any block (or the diagram) carries costs or maintenance."""
    if (graph.get("costs") or {}).get("downtime_rate") or (graph.get("costs") or {}).get("horizon"):
        return True
    return any(
        rm.has_extras(n.get("data") or {})
        for n in graph.get("nodes") or []
        if n.get("type") == "component"
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
    entries += [f"{_lit(k)}: {_num(v)}" for k, v in costs.items()]
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
        if spec.get("cost"):
            parts.append(f'"cost": {_num(spec["cost"])}')
        entries.append(f'"{key}": {{' + ", ".join(parts) + "}")
    if data.get("inspection"):
        L.append("# Hidden failures: found only at the proof tests below.")
    L.append(f"{var} = {{")
    L.extend(f"    {e}," for e in entries)
    L.append("}")


def rbd_kwargs(graph: dict) -> list[str]:
    """Extra ``RepairableRBD(...)`` arguments: the system downtime cost."""
    from backend.services.rbd_export import _num

    try:
        rate = rm.downtime_cost_rate(graph)
    except AnalysisError:
        rate = 0.0
    return [f"downtime_cost_rate={_num(rate)}"] if rate else []


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
    # Block replacement and proof tests other than an exponential life with
    # instant tests and repairs have none: the simulation gives them.
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
    run = dict(t_simulation=T_SIMULATION, method="c", seed=1)
    try:
        pilot = rbd.availability(N=PILOT_SIMS, antithetic=True, **run, **overrides)
    except NotImplementedError:
        pilot = rbd.availability(N=PILOT_SIMS, **run, **overrides)
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
        out["simulated"] = {
            "mean": cost.mean, "lower": window.lower, "upper": window.upper,
            "percentiles": {"10": p10, "50": p50, "90": p90},
            "by_category": dict(cost.by_category),
        }
    return out
'''


def main_source(template: str, graph: dict) -> str:
    """The repairable ``main()`` (and helpers): unchanged for a diagram without
    costs or maintenance."""
    if not uses_extras(graph):
        return template
    out = template
    for old, new in ((_EXACT, _EXACT_OR_NOT), (_TOLERANCE, _TOLERANCE_OR_PILOT),
                     (_NODES, _NODES_OR_NOT), (_SAVE, _SAVE_COSTS), (_RERUN, _RERUN_NAN)):
        assert out.count(old) == 1, old
        out = out.replace(old, new)
    marker = "\ndef main():"
    return out.replace(marker, _HELPERS.rstrip("\n") + "\n\n" + marker, 1)


def pilot_constant() -> list[str]:
    return [f"PILOT_SIMS = {5 * rbd_analysis._AVAIL_PILOT_SIMS}"]

