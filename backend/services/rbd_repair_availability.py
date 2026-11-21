"""Availability with repairs for any block diagram (Nov 2026).

A non-repairable diagram answers "will it last the mission?". Engineers who repair what fails also
ask "how much of the time is it up?". This module answers that for a diagram as it is drawn
(the RBD Calculator, a mission's diagram, a diagram built from the asset tree) without the user
having to rebuild it as a repairable diagram first:

* each block keeps its life model; its repair time is a mean time to repair (MTTR) taken from,
  in this order: a time typed for this calculation, the block's own repair-time model, the
  outages recorded against the diagram (its outage history), or the maintainability prediction
  of the position the block stands for. Each block says which. A block with none is listed, and
  nothing is worked out until it has one: a repair time is never guessed;
* with only a mean known, the repair time is taken as exponential with that mean. The long-run
  availability of a block repaired on its own depends on the mean alone (MTBF / (MTBF + MTTR)),
  so only the figures over a period lean on that choice;
* redundancy stays redundancy: parallel paths, k-of-n votes and standby groups are kept, a
  parallel (or series) block of n units becomes n blocks each repaired on its own, and
  sub-systems are expanded into their blocks. The diagram's repair crews and a standby group's
  spares are kept where the diagram has them;
* RePyability does the maths, through :mod:`backend.services.rbd_analysis` (the same repairable
  build and exact figures the repairable Calculator uses): the long-run availability, and over
  the period the mean availability, expected downtime and failures, with each block's part in
  the downtime (its criticality: the share of the system's unavailability it takes part in).

Inherent availability counts repairs only. Where blocks carry planned work (a block's own
preventive replacement or proof test, or the tasks of the position it stands for, read from the
tree as the repairable Calculator reads them) the achieved availability counts that downtime
too, beside the inherent figure.

Pure: it takes the graph, the repair times and a model resolver and returns plain JSON, so the
REST route and the MCP tool give the same answer.
"""

from __future__ import annotations

import copy
import math
from typing import Any, Callable, Optional

from backend.services.rbd_analysis import AnalysisError
from backend.units import normalize_unit, unit_factor, unit_in_text

#: Where a block's repair time came from, in the order they're used.
SOURCES = ("typed", "block", "recorded", "prediction")
SOURCE_WORDS = {
    "typed": "typed here",
    "block": "set on the block",
    "recorded": "recorded outages",
    "prediction": "maintainability prediction",
}
#: Keys of a non-repairable diagram a repairable copy leaves behind (its missions).
_DROP = ("phases", "missions", "mission_name", "mission_of", "network", "evaluate_at")
#: How many blocks the drivers list names.
TOP_DRIVERS = 5
#: The rule every result states: these figures carry no bound.
NO_BOUND = ("No bound: worked out exactly from each block's model at its point values, so the uncertainty "
            "in a fitted model isn't carried into it.")
EXP_NOTE = ("Each repair time is taken as exponential with its mean. The long-run figure depends on the "
            "means alone; the figures over the period lean a little on that choice.")
HOURS_PER_YEAR = 8766.0


class RepairTimeError(ValueError):
    """A repair time that can't be used, in words."""


def repair_unit(graph: dict) -> str:
    """The unit repair times are given in: hours when the diagram's clock is a time (days, hours,
    years …), else the diagram's own unit (cycles, km …)."""
    unit = (graph or {}).get("unit") or ""
    if normalize_unit(unit) in ("hour",) or unit_factor("hour", unit) is not None:
        return "hours"
    return unit or "time units"


def _to_diagram(value: float, graph: dict) -> float:
    """A repair time in :func:`repair_unit` to the diagram's unit."""
    f = unit_factor("hour", (graph or {}).get("unit") or "")
    return value * f if f is not None else value


def _to_repair_unit(value: Optional[float], graph: dict) -> Optional[float]:
    if value is None:
        return None
    f = unit_factor("hour", (graph or {}).get("unit") or "")
    return value / f if f is not None else value


def default_period(graph: dict) -> tuple[Optional[float], str]:
    """(length in the diagram's unit, basis): a mission's length where the diagram has phases,
    else a year where its clock is a time, else None (the analysis's own horizon)."""
    phases = (graph or {}).get("phases") or []
    total = sum(float(p.get("duration") or 0) for p in phases if isinstance(p, dict))
    if total > 0:
        return total, "mission"
    f = unit_factor("year", (graph or {}).get("unit") or "")
    if normalize_unit((graph or {}).get("unit") or "") == "year":
        return 1.0, "year"
    if f is not None:
        return f, "year"
    return None, "horizon"


def blocks_of(graph: dict) -> list[dict]:
    """The blocks a repair time is for: component, standby and n-unit blocks ({id, label, type})."""
    out = []
    for n in (graph or {}).get("nodes") or []:
        if not isinstance(n, dict) or n.get("type") not in ("component", "standby", "series", "parallel"):
            continue
        data = n.get("data") or {}
        if data.get("repeat_of"):
            continue
        out.append({"id": str(n.get("id")), "label": data.get("label") or str(n.get("id")), "type": n.get("type"),
                    "data": data})
    return out


def _spec_mean(spec: Any, resolve_model) -> Optional[float]:
    """The mean of a block's own repair-time model (diagram unit), or None."""
    from backend.services.rbd_analysis import _build_distribution

    if not isinstance(spec, dict):
        return None
    try:
        dist = _build_distribution(spec, "its repair time", resolve_model, None)
        mean = float(dist.mean())
    except Exception:  # noqa: BLE001 - an unreadable repair model: not a source
        return None
    return mean if math.isfinite(mean) and mean > 0 else None


def exp_repair(mean: float) -> dict:
    """An exponential repair-time model with this mean (diagram unit)."""
    return {"source": "params", "distribution": "Exponential", "distribution_id": "exponential",
            "params": [{"name": "failure_rate", "value": 1.0 / float(mean)}]}


def parse_typed(raw) -> dict:
    """``{block id: repair time}`` typed for this calculation (in :func:`repair_unit`)."""
    if raw in (None, ""):
        return {}
    if not isinstance(raw, dict):
        raise RepairTimeError("repairs is {block id: mean time to repair}, e.g. {\"cv-02\": 12}.")
    out = {}
    for k, v in raw.items():
        if v in (None, ""):
            continue
        try:
            x = float(v)
        except (TypeError, ValueError):
            raise RepairTimeError(f"The repair time for {k} must be a number.") from None
        if not math.isfinite(x) or x <= 0:
            raise RepairTimeError(f"The repair time for {k} must be more than 0.")
        out[str(k)] = x
    return out


def repair_rows(graph: dict, resolve_model=None, typed: Optional[dict] = None, recorded: Optional[dict] = None,
                predictions: Optional[dict] = None) -> list[dict]:
    """Each block's repair time and where it came from: [{id, label, mttr (repair unit), source,
    source_words, detail, pinned}]. ``recorded``: {block id: {mean (diagram unit), count, name}};
    ``predictions``: {block id: {hours, name, position}}. A block pinned working or failed needs none."""
    typed = typed or {}
    recorded = recorded or {}
    predictions = predictions or {}
    rows = []
    for b in blocks_of(graph):
        data = b["data"]
        row: dict[str, Any] = {"id": b["id"], "label": b["label"], "mttr": None, "source": None,
                               "source_words": None, "detail": None, "pinned": data.get("state") in ("working", "failed")}
        own = None if data.get("instant_repair") else _spec_mean(data.get("repair"), resolve_model)
        if b["id"] in typed:
            row.update(mttr=typed[b["id"]], source="typed")
        elif data.get("instant_repair"):
            row.update(mttr=0.0, source="block", detail="repaired at once")
        elif own is not None:
            row.update(mttr=_to_repair_unit(own, graph), source="block")
        elif b["id"] in recorded and recorded[b["id"]].get("mean"):
            r = recorded[b["id"]]
            n = int(r.get("count") or 0)
            row.update(mttr=_to_repair_unit(float(r["mean"]), graph), source="recorded",
                       detail=f"the mean of {n} repair{'s' if n != 1 else ''} in {r.get('name') or 'its outage history'}")
        elif b["id"] in predictions and predictions[b["id"]].get("hours"):
            p = predictions[b["id"]]
            hours = float(p["hours"])
            value = hours if repair_unit(graph) == "hours" else None
            if value is not None:
                row.update(mttr=value, source="prediction",
                           detail=f"Mct of “{p.get('name') or 'its prediction'}” for {p.get('position') or 'its position'}")
        if row["source"]:
            row["source_words"] = SOURCE_WORDS[row["source"]]
        if row["mttr"] is not None:
            row["mttr"] = float(f"{row['mttr']:.6g}")
        rows.append(row)
    return rows


def _expand_units(graph: dict) -> tuple[dict, dict]:
    """``(graph, {new id: original id})``: every n-unit block (series or parallel, n units of one
    model) as n component blocks, each repaired on its own; parallel ones feed a 1-of-n junction so
    a k-of-n vote after it still counts one input."""
    nodes = [copy.deepcopy(n) for n in graph.get("nodes") or [] if isinstance(n, dict)]
    edges = [{"source": e.get("source"), "target": e.get("target")} for e in graph.get("edges") or []
             if isinstance(e, dict) and e.get("source") and e.get("target")]
    origin: dict = {}
    out_nodes = []
    for n in nodes:
        ntype = n.get("type")
        if ntype not in ("series", "parallel"):
            out_nodes.append(n)
            continue
        data = n.get("data") or {}
        nid = n["id"]
        count = max(int(data.get("n") or 1), 1)
        label = data.get("label") or nid
        unit_data = {k: v for k, v in data.items() if k not in ("n", "k")}
        ids = [f"{nid}#{i + 1}" for i in range(count)]
        for i, uid in enumerate(ids):
            out_nodes.append({"id": uid, "type": "component",
                              "data": {**copy.deepcopy(unit_data), "label": f"{label} (unit {i + 1})"}})
            origin[uid] = nid
        preds = [e["source"] for e in edges if e["target"] == nid]
        succs = [e["target"] for e in edges if e["source"] == nid]
        edges = [e for e in edges if nid not in (e["source"], e["target"])]
        if ntype == "series":
            chain = list(zip(ids, ids[1:]))
            edges += [{"source": a, "target": b} for a, b in chain]
            edges += [{"source": p, "target": ids[0]} for p in preds]
            edges += [{"source": ids[-1], "target": s} for s in succs]
        else:
            jid = f"{nid}#out"
            out_nodes.append({"id": jid, "type": "knode", "data": {"label": f"Out of {label}", "n": 1, "k": count}})
            origin[jid] = nid
            edges += [{"source": p, "target": u} for p in preds for u in ids]
            edges += [{"source": u, "target": jid} for u in ids]
            edges += [{"source": jid, "target": s} for s in succs]
    return {**graph, "nodes": out_nodes, "edges": edges}, origin


def _refuse_unsupported(graph: dict) -> None:
    for n in graph.get("nodes") or []:
        if isinstance(n, dict) and n.get("type") == "loadshare":
            label = (n.get("data") or {}).get("label") or n.get("id")
            raise AnalysisError(f"“{label}” shares its load between its units, and availability with repairs "
                                "isn't worked out for a load-sharing block. Draw its units as a parallel or "
                                "k-of-n block to get the availability.")


def repairable_copy(graph: dict, rows: list[dict], resolve_subsystem: Optional[Callable] = None
                    ) -> tuple[dict, dict, list[str]]:
    """``(repairable graph, {block id in it: original block id}, notes)``: the diagram with each
    block given its repair time, sub-systems expanded and n-unit blocks split into their units.
    Raises :class:`AnalysisError` for a block a repairable diagram can't take."""
    from backend.services import rbd_flatten

    notes: list[str] = []
    g = {k: v for k, v in copy.deepcopy(graph or {}).items() if k not in _DROP}
    if any(n.get("type") == "subsystem" for n in g.get("nodes") or [] if isinstance(n, dict)):
        if resolve_subsystem is None:
            raise AnalysisError("This diagram has sub-systems, which can't be read here.")
        try:
            g, expanded = rbd_flatten.expand(g, resolve_subsystem)
        except rbd_flatten.FlattenError as exc:
            raise AnalysisError(str(exc)) from None
        if expanded:
            notes.append(f"Sub-systems expanded into their blocks: {', '.join(expanded[:6])}"
                         f"{' …' if len(expanded) > 6 else ''}.")
    _refuse_unsupported(g)
    by_id = {r["id"]: r for r in rows}
    g, origin = _expand_units(g)
    if origin:
        notes.append("Each unit of a block of several is repaired on its own.")
    for n in g.get("nodes") or []:
        if not isinstance(n, dict) or n.get("type") not in ("component", "standby"):
            continue
        src = origin.get(n["id"], n["id"])
        row = by_id.get(str(src))
        data = n.setdefault("data", {})
        if row is None or data.get("state") in ("working", "failed"):
            continue
        if row["source"] == "block":
            continue  # its own repair model (or repaired at once), as drawn
        if row["mttr"] is not None:
            data.pop("instant_repair", None)
            data["repair"] = exp_repair(_to_diagram(row["mttr"], graph))
    g["repairable"] = True
    return g, {**{r["id"]: r["id"] for r in rows}, **origin}, notes


def _period_words(length: Optional[float], unit: str, basis: str) -> str:
    if length is None:
        return "until it settles"
    if basis == "year":
        return "a year"
    if basis == "mission":
        return f"the mission ({length:,.4g} {unit_in_text(unit)})".replace(" )", ")")
    return f"{length:,.4g} {unit_in_text(unit)}".strip()


def _pct(v: Optional[float]) -> Optional[str]:
    """As the app shows a mission's reliability (rbdMission.js reliabilityPercent): three
    figures below 99%, else enough decimals to tell 99.7% from 99.97%."""
    if v is None or not math.isfinite(v):
        return None
    q = 1.0 - v
    if q <= 0:
        return "100%"
    if v < 0.99:
        return f"{float(f'{v * 100:.3g}'):g}%"
    decimals = min(8, max(1, math.ceil(-math.log10(q * 100)) + 1))
    return f"{v * 100:.{decimals}f}%"


def _down_words(downtime: Optional[float], graph: dict) -> Optional[str]:
    """System downtime over the period in words: hours where the clock is a time."""
    if downtime is None or not math.isfinite(downtime):
        return None
    hours = _to_repair_unit(downtime, graph) if repair_unit(graph) == "hours" else None
    if hours is not None:
        if hours >= 48 and hours / 24 >= 10:
            return f"about {hours:,.0f} hours ({hours / 24:,.3g} days) down"
        return f"about {hours:,.3g} hours down"
    return f"about {downtime:,.3g} {unit_in_text(graph.get('unit') or '')} down".replace("  ", " ")


def _figures(rgraph: dict, resolve_model, period: Optional[float]) -> dict:
    """The long-run and period figures of a repairable graph (RePyability, exactly)."""
    from backend.services import rbd_analysis as ra

    base = ra.analyze_availability(rgraph, resolve_model=resolve_model, t_simulation=period, simulate=False)
    exact = ra.exact_availability(rgraph, resolve_model=resolve_model, horizon=period)
    out = {
        "steady_state": base.get("steady_state_availability"),
        "mean_up_time": base.get("mean_up_time"),
        "mean_down_time": base.get("mean_down_time"),
        "failure_frequency": base.get("failure_frequency"),
        "long_run_method": (base.get("figures_basis") or {}).get("mean_up_time"),
        "window": exact.get("window"),
        "exact_status": exact.get("status"),
        "exact_message": exact.get("message"),
        "period_availability": exact.get("mission_availability"),
        "downtime": exact.get("downtime"),
        "expected_failures": exact.get("expected_failures"),
        "planned_outages": exact.get("planned_outages"),
        "method": (exact.get("method") or {}).get("mission_availability"),
        "_importance": base.get("importance") or {},
        "_per_node": exact.get("per_node") or [],
    }
    return out


def _drivers(fig: dict, origin: dict, labels: dict) -> list[dict]:
    """Each original block's part in the system's downtime, largest first: its units' criticality
    (the largest of them), scaled so the shares add to 100%."""
    crit: dict = {}
    for nid, row in (fig.get("_importance") or {}).items():
        src = origin.get(nid, nid)
        c = row.get("unavailability_criticality")
        if c is None or not math.isfinite(c):
            continue
        crit[src] = max(crit.get(src, 0.0), float(c))
    own: dict = {}
    for row in fig.get("_per_node") or []:
        src = origin.get(row["id"], row["id"])
        if row.get("downtime") is not None:
            own[src] = own.get(src, 0.0) + float(row["downtime"])
    total = sum(crit.values())
    if total <= 0:
        return []
    out = [{"id": str(k), "label": labels.get(k, str(k)), "share": v / total, "own_downtime": own.get(k)}
           for k, v in crit.items() if v > 0]
    out.sort(key=lambda r: (-r["share"], r["label"]))
    return out


def _has_planned(graph: dict) -> bool:
    return any(isinstance(n, dict) and ((n.get("data") or {}).get("preventive") or (n.get("data") or {}).get("inspection"))
               for n in graph.get("nodes") or [])


def _without_planned(graph: dict) -> dict:
    nodes = []
    for n in graph.get("nodes") or []:
        if isinstance(n, dict) and isinstance(n.get("data"), dict):
            n = {**n, "data": {k: v for k, v in n["data"].items()
                               if k not in ("preventive", "inspection", "maintenance_group", "tree_plan")}}
        nodes.append(n)
    return {**graph, "nodes": nodes, "maintenance_groups": {}} if graph.get("maintenance_groups") else \
        {**graph, "nodes": nodes}


def _public(fig: Optional[dict], graph: dict) -> Optional[dict]:
    if fig is None:
        return None
    out = {k: v for k, v in fig.items() if not k.startswith("_")}
    out["downtime_hours"] = _to_repair_unit(fig.get("downtime"), graph) if repair_unit(graph) == "hours" else None
    out["mean_down_time_hours"] = (_to_repair_unit(fig.get("mean_down_time"), graph)
                                   if repair_unit(graph) == "hours" else None)
    return out


def analyse(graph: dict, rows: list[dict], resolve_model=None, *, period: Optional[float] = None,
            resolve_subsystem: Optional[Callable] = None, plan_graph: Optional[Callable] = None) -> dict:
    """The availability of ``graph`` (any block diagram) with each block repaired after it fails.

    ``rows``: :func:`repair_rows`. ``period``: the window in the diagram's unit (default
    :func:`default_period`). ``plan_graph``: given the repairable graph, the same with the planned
    work read from the tree (the achieved figure); None reads only what the blocks carry.

    Returns {status: ok | needs_repairs, answer, repairs, needs, period, inherent, achieved,
    drivers, placeholders, without_placeholders, notes, bound_note, unit, repair_unit}."""
    from backend.services import rbd_graph

    unit = (graph or {}).get("unit") or ""
    basis = "given"
    if period is None:
        period, basis = default_period(graph)
    elif not (isinstance(period, (int, float)) and math.isfinite(period) and period > 0):
        raise AnalysisError("The period must be a positive number, in the diagram's time unit.")
    head: dict[str, Any] = {
        "kind": "repair_availability", "unit": unit, "repair_unit": repair_unit(graph),
        "repairs": rows, "period": {"length": period, "basis": basis, "words": _period_words(period, unit, basis)},
        "bound_note": NO_BOUND, "notes": [],
    }
    _refuse_unsupported(graph or {})
    needs = [r["label"] for r in rows if r["mttr"] is None and not r["pinned"]]
    if not rows:
        raise AnalysisError("The diagram has no blocks to work out an availability for.")
    if needs:
        some = ", ".join(needs[:6]) + (" …" if len(needs) > 6 else "")
        return {**head, "status": "needs_repairs", "needs": needs,
                "answer": (f"Give {some} a repair time (its mean time to repair, in {repair_unit(graph)}) to work "
                           "out the availability. Nothing is assumed for a block with none."),
                "inherent": None, "achieved": None, "drivers": []}
    rgraph, origin, notes = repairable_copy(graph, rows, resolve_subsystem)
    head["notes"] += notes
    labels = {r["id"]: r["label"] for r in rows}
    achieved_graph = plan_graph(rgraph) if plan_graph is not None else rgraph
    planned = _has_planned(achieved_graph)
    inherent_graph = _without_planned(rgraph) if _has_planned(rgraph) else rgraph
    inherent = _figures(inherent_graph, resolve_model, period)
    achieved = None
    achieved_note = None
    if planned:
        try:
            achieved = _figures(achieved_graph, resolve_model, period)
            if achieved.get("steady_state") is None and achieved.get("period_availability") is None:
                achieved_note = ("With its planned work, only the availability simulation gives this diagram's "
                                 "figures: make the diagram repairable and run the simulation for the achieved "
                                 "availability.")
                achieved = None
        except AnalysisError as exc:
            achieved, achieved_note = None, f"The planned work couldn't be included: {exc}"
    lead = achieved or inherent
    drivers = _drivers(lead, origin, labels)
    # Placeholder lives: said, with the figure without them (those blocks never failing).
    placeholders = rbd_graph.placeholder_labels(graph)
    without = None
    if placeholders and len(placeholders) < len([r for r in rows if not r["pinned"]]):
        ph_ids = {str(n.get("id")) for n in graph.get("nodes") or [] if isinstance(n, dict)
                  and isinstance((n.get("data") or {}).get("model"), dict) and n["data"]["model"].get("placeholder")}
        pinned = {**inherent_graph, "nodes": [
            {**n, "data": {**(n.get("data") or {}), "state": "working"}}
            if isinstance(n, dict) and origin.get(n.get("id"), n.get("id")) in ph_ids else n
            for n in inherent_graph.get("nodes") or []]}
        try:
            w = _figures(pinned, resolve_model, period)
            without = {"steady_state": w.get("steady_state"), "period_availability": w.get("period_availability")}
        except AnalysisError:
            without = None
    simulated_only = lead.get("steady_state") is None and lead.get("period_availability") is None
    out = {**head, "status": "simulation_only" if simulated_only else "ok", "needs": [],
           "inherent": _public(inherent, graph), "achieved": _public(achieved, graph),
           "achieved_note": achieved_note,
           "kind_words": "achieved: repairs and planned work" if achieved else "inherent: repairs only",
           "drivers": drivers, "placeholders": placeholders, "without_placeholders": without}
    if any(r["source"] in ("typed", "recorded", "prediction") for r in rows):
        out["notes"].append(EXP_NOTE)
    if graph.get("phases"):
        out["notes"].append("Worked out for the diagram as drawn over the mission's length: the phases' own block "
                            "settings (not needed, votes) are for its reliability.")
    out["answer"] = answer_text(out, graph)
    return out


def answer_text(out: dict, graph: dict) -> str:
    """The answer first, in plain words: "Available 98.7% of the time over a year: about 114
    hours down, mostly CV-02 (41%). In the long run 98.8%."."""
    lead = out.get("achieved") or out.get("inherent") or {}
    period = (out.get("period") or {}).get("words") or ""
    pa, ss = lead.get("period_availability"), lead.get("steady_state")
    parts = []
    if pa is not None:
        text = f"Available {_pct(pa)} of the time over {period}"
        down = _down_words(lead.get("downtime"), graph)
        if down:
            text += f": {down}"
        top = (out.get("drivers") or [])[:1]
        if top:
            text += f", mostly {top[0]['label']} ({top[0]['share'] * 100:.0f}% of it)"
        parts.append(text + ".")
        if ss is not None:
            parts.append(f"In the long run {_pct(ss)}.")
    elif ss is not None:
        parts.append(f"Available {_pct(ss)} of the time in the long run"
                     + (f", mostly down for {out['drivers'][0]['label']}" if out.get("drivers") else "") + ".")
        if lead.get("exact_message"):
            parts.append("Over the period, only the availability simulation gives it.")
    else:
        reason = str(lead.get("exact_message") or "").replace(
            "The exact availability over time isn't available for this diagram, so only the simulation gives it. ", "")
        parts.append("Only a simulation can work out this diagram's availability" + (f": {reason}" if reason else ".")
                     + " Switch a copy of the diagram to repairable to run the availability simulation.")
    if out.get("achieved") and out.get("inherent"):
        ia = out["inherent"].get("period_availability")
        if ia is None:
            ia = out["inherent"].get("steady_state")
        if ia is not None:
            parts.append(f"Repairs alone (inherent): {_pct(ia)}.")
    if out.get("placeholders"):
        n = len(out["placeholders"])
        parts.append(f"Not a real figure: {n} block{'s have' if n != 1 else ' has'} no model "
                     f"({', '.join(out['placeholders'][:4])}{' …' if n > 4 else ''}), so it rests on invented lives.")
        w = out.get("without_placeholders") or {}
        wv = w.get("period_availability") if w.get("period_availability") is not None else w.get("steady_state")
        if wv is not None:
            parts.append(f"With {'it' if n == 1 else 'them'} left out: {_pct(wv)}.")
    return " ".join(parts)
