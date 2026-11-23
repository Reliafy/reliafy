"""A mission's two first answers (the Explorer's Missions tab, 23 Nov 2026).

A mission is its phases (rbd_missions.py: each phase's length, the blocks it needs, its
covariates, constant or following a schedule). Over the whole phased mission this gives:

* **the chance of completing it**: the chance the system gets through every phase without a
  system failure, from the state its blocks start in (new, or as today: each block's item at its
  age now). It is the mission's own calculation (``rbd_missions.analyze``, RePyability's phased
  mission), the same figure the phases show. Its bound is 90% one-sided (a lower bound on a
  chance of success, the rule for lives): from the fitted blocks' uncertainty, drawn as the RBD's
  band draws it (``rbd_uncertainty``) for a mission of one phase; a plain life model's mission
  keeps its own (``rbd_missions.simple_bound``); a mission of several phases has none yet (said);
* **the failures to expect during it**: the part (block) failures over the mission's length when
  each failed block is replaced at once with a like new one, and how many of them take the system
  down, worked out exactly by RePyability (``RepairableRBD.expected_events``) where it can be, with a 90% two-sided range of outcomes
  (the 5th to 95th percentile of simulated missions, RePyability's ``simulate_timelines``: a
  simulation, so Pro). Covariates that change over the mission (by phase, or on a schedule) take
  the simulation for the figure too. Phases that switch blocks on or off, stand them by or change
  a vote have no figure yet (said).

Blocks with no model (or a placeholder for one) stop both answers, and are named: nothing is
worked out on a guess. Planned maintenance isn't counted yet; the answers say so.

RePyability computes every number; this module gathers the mission and labels the answers.
"""

from __future__ import annotations

import copy
from datetime import date, timedelta
from typing import Optional

import numpy as np

from backend.services import rbd_missions
from backend.services.rbd_analysis import AnalysisError

#: The one-sided level of the chance's bound, and the two-sided level of the failures' range.
BOUND_LEVEL = 0.90
RANGE_LEVEL = 0.90
#: Simulated missions for the failures' range (seeded, so the same mission gives the same range).
SIM_RUNS = 2000
SIM_SEED = 20261123
#: What a phase can set that changes the diagram itself (not only the blocks' covariates).
_STRUCTURAL = ("not_needed", "standby", "guaranteed", "dormancy", "start_probability", "models", "votes")
PLAN_NOTE = ("Planned maintenance isn't counted yet: the blocks run from the state they start in, and a failed "
             "one is replaced with a like new one.")


def _fmt(v: float) -> str:
    from backend.services.strategy import fmt_num

    return fmt_num(v)


def clock_for(m, position_id: Optional[str], setup: Optional[dict]):
    """The calendar a mission's running time meets the dates through: its own duty, or the
    position's (Operations: its own or from above; all the time with none)."""
    from backend.services import running_clock

    cal = (setup or {}).get("calendar") or {"linked": True}
    if not cal.get("linked"):
        h, d = float(cal["hours_per_day"]), int(cal["days_per_week"])
        return running_clock.Clock(h * d / 7.0, "duty", d == 7, f"its own duty: {_fmt(h)} h a day, {d} days a week")
    if m is None:
        return running_clock.CONTINUOUS
    return running_clock.for_position(m, position_id)


def running_length(length: dict, unit: str, clock) -> float:
    """A length as entered (hours of running; days, months or years on the calendar) in the RBD's
    unit, through ``clock``. Raises AnalysisError where they don't meet (a diagram in cycles)."""
    from backend.services import running_clock

    v, u = float(length["value"]), length["unit"]
    if running_clock._key(u) == running_clock._key(unit or "hours") or (
            u == "hours" and running_clock.is_running_hours(unit or "hours")):
        return v
    if u == "hours":
        conv = running_clock.conversion("hours", unit or "hours", None)
    else:
        conv = running_clock.conversion(u[:-1], unit or "hours", clock)
    if conv is None:
        raise AnalysisError(f"A length in {u} doesn't convert to this RBD's unit ({unit or 'none'}): "
                            "give the length in the RBD's own unit through its phases.")
    return v * float(conv["factor"])


def calendar_span(total: float, unit: str, clock, start: str, today: str) -> dict:
    """When the mission ends on the calendar: {start, end, days, words} (None end where its running
    time can't be put on the calendar)."""
    from backend.services import running_clock

    first = date.fromisoformat(today if start == "now" else start)
    per = running_clock.days_in(unit or "hours", clock)
    out = {"start": first.isoformat(), "end": None, "days": None, "clock": clock.to_dict()}
    if per is None:
        return out
    days = total * per
    out["days"] = days
    out["end"] = (first + timedelta(days=days)).isoformat()
    return out


def today_state(m, position_id: str, graph: dict) -> tuple[Optional[dict], list[str]]:
    """Each block's item at its age now ({block id: {"age": t}}), for a mission started "as today",
    and the notes: the blocks with no age to read start new, and say so."""
    from backend.maintenance import rbd_tree_plan

    unit = graph.get("unit") or ""
    blocks = [n for n in graph.get("nodes") or [] if isinstance(n, dict) and n.get("type") == "component"
              and not (n.get("data") or {}).get("repeat_of")]
    if m is None:
        return None, ["Today's ages can't be read here, so every block starts new."]
    mapped = rbd_tree_plan.block_positions(m, position_id, blocks)
    state, new = {}, []
    for b in blocks:
        label = (b.get("data") or {}).get("label") or b.get("id")
        pos = mapped.get(b["id"])
        got = rbd_tree_plan.block_age(m, pos, unit) if pos else {"reason": "it stands for no position"}
        if got.get("age") is not None and float(got["age"]) > 0:
            state[b["id"]] = {"age": float(got["age"])}
        else:
            new.append(label)
    notes = []
    if new:
        notes.append(f"Starts new (no age to read): {', '.join(new[:8])}{'…' if len(new) > 8 else ''}.")
    return (state or None), notes


def plan_of(m, position_id: str, graph: dict) -> list[dict]:
    """The current maintenance plan on the mission's blocks, read only: [{block, task, every}]."""
    from backend.maintenance import rbd_tree_plan

    if m is None:
        return []
    blocks = [n for n in graph.get("nodes") or [] if isinstance(n, dict) and n.get("type") == "component"]
    out = []
    for bid, pos in rbd_tree_plan.block_positions(m, position_id, blocks).items():
        for t in m._tasks_on(pos["id"]):
            view = m._task_view(t)
            every = view.get("interval")
            out.append({"position": pos.get("name"), "task": view.get("name") or t.get("name"),
                        "every": f"every {_fmt(float(every))} {view.get('unit') or ''}".strip() if every else None})
    return out[:50]


def _structural(phases: list) -> bool:
    return any(p.get(k) for p in phases for k in _STRUCTURAL)


def _twin(merged: dict, covs: dict) -> dict:
    """The mission's diagram as a repairable one whose failed blocks are replaced at once, like new:
    each block's covariates (constant ones too) on the mission's clock."""
    g = copy.deepcopy(merged)
    g["repairable"] = True
    for k in ("phases", "missions", "mission_name", rbd_missions.START_KEY, rbd_missions.SETUP_KEY):
        g.pop(k, None)
    for n in g.get("nodes") or []:
        if n.get("type") != "component":
            continue
        data = n.setdefault("data", {})
        data["instant_repair"] = True
        values = (covs or {}).get(n.get("id"))
        if values and (data.get("model") or {}).get("kind") == "regression":
            sched = dict(data.get("covariate_schedules") or {})
            for key, v in values.items():
                sched.setdefault(key, {"table": [{"t": 0.0, "value": v}]})
            data["covariate_schedules"] = sched
    return g


def expected_failures(twin: dict, resolve_model, length: float, state: Optional[dict], simulate: bool) -> dict:
    """{expected, system, method, range: {lower, upper, level, side} | None, note}: the part failures
    over ``length`` with each failed block replaced at once with a like new one (``system``: how
    many of them take the system down). Exact where RePyability is (``expected_events``); the range
    (and the figure where it isn't exact) from ``SIM_RUNS`` seeded simulations, when ``simulate``."""
    from backend.errors import client_message
    from backend.services import rbd_analysis as ra

    out = {"expected": None, "system": None, "method": None, "range": None, "note": None}
    try:
        rbd, labels, _, working, broken = ra._build_repairable_rbd(twin, resolve_model, state=state)
    except (AnalysisError, NotImplementedError, ValueError) as exc:
        out["note"] = f"Not worked out: {client_message(exc)}"
        return out
    node_states = ra._node_states(state, labels)
    kw = {"state": node_states} if node_states else {}
    held = {"working_nodes": working or None, "broken_nodes": broken or None}
    scheduled = any((n.get("data") or {}).get("covariate_schedules") for n in twin.get("nodes") or [])
    if not scheduled:
        try:
            with np.errstate(all="ignore"):
                ev = rbd.expected_events(float(length), **held, **kw)
            out.update(expected=float(sum(float(np.sum(v)) for v in ev.node_failures.values())),
                       system=float(np.sum(ev.system_failures)), method="exact")
        except (AnalysisError, NotImplementedError, ValueError, TypeError):
            pass
    if not simulate:
        out["pro"] = True
        out["note"] = ("The 90% range comes from a simulation, which is Pro." if out["expected"] is not None else
                       "This mission's figure comes from a simulation (its covariates change over it, or there's no "
                       "exact route), which is Pro.")
        return out
    try:
        runs = rbd.simulate_timelines(float(length), mc_samples=SIM_RUNS, seed=SIM_SEED, **held, **kw)
        counts = sum(np.asarray(tl.failures, dtype=float) for tl in runs.components.values())
        system = np.asarray(runs.system.failures, dtype=float)
    except (AnalysisError, NotImplementedError, ValueError) as exc:
        out["note"] = f"The range couldn't be simulated: {client_message(exc)}"
        return out
    tail = 50.0 * (1.0 - RANGE_LEVEL)
    lo, hi = np.percentile(counts, [tail, 100.0 - tail], method="inverted_cdf")
    # p_any: the share of simulated missions with one failure or more, so a range of 0 to 0 can be
    # said plainly ("about 1 in 43 has a failure").
    out["range"] = {"lower": float(lo), "upper": float(hi), "level": RANGE_LEVEL, "side": "two-sided",
                    "runs": int(np.size(counts)), "p_any": float(np.mean(counts > 0))}
    if out["expected"] is None:
        out.update(expected=float(np.mean(counts)), system=float(np.mean(system)), method="simulated")
    return out


def _single_phase_bound(db, owner_id, got: dict, length: float, state: Optional[dict]) -> Optional[dict]:
    """The 90% one-sided lower bound on a one-phase mission's chance, from the fitted blocks'
    uncertainty (the RBD's band: its 10th percentile over the draws), or None."""
    from backend.services import rbd_analysis as ra
    from backend.services import rbds as rbds_service

    if len(got["bound"]) != 1:
        return None
    resolve_subsystem, resolve_model = rbds_service.resolvers(db, owner_id)
    level = 1.0 - 2.0 * (1.0 - BOUND_LEVEL)  # the two-sided band whose lower end is the one-sided bound
    res = ra.analyze(got["bound"][0], resolve_subsystem, covariates=got["covs"][0] or None,
                     resolve_model=resolve_model, at_times=[length], band={"level": level, "times": [length]},
                     current_state=state)
    rows = (((res.get("band") or {}).get("targets") or {}).get("reliability") or [])
    if not rows or rows[0].get("lower") is None:
        return None
    if not (res.get("band") or {}).get("uncertain"):
        return None  # nothing fitted to draw: no bound to give
    return {"lower": float(rows[0]["lower"]), "confidence": BOUND_LEVEL, "side": "lower"}


def blocked_by(graph: dict, phases: list) -> list[dict]:
    """The blocks some phase needs that have no model, or only a placeholder for one: [{id, label,
    why}]. Both answers wait for them (nothing is worked out on a guess)."""
    from backend.services import rbd_analysis as ra
    from backend.services import rbd_phases

    try:
        parsed = rbd_phases.parse_phases(phases or [])
    except rbd_phases.PhaseError:
        parsed = []
    never = set.intersection(*(set(p.get("not_needed", [])) for p in parsed)) if parsed else set()
    labels = {n.get("id"): (n.get("data") or {}).get("label") or n.get("id") for n in graph.get("nodes") or []}
    out = [{"id": b["id"], "label": b.get("label") or labels.get(b["id"]), "why": "no model"}
           for b in ra.blocks_needing_models(graph) if b["id"] not in never]
    seen = {b["id"] for b in out}
    out += [{"id": i, "label": labels.get(i, i), "why": "a placeholder"}
            for i in rbd_phases.placeholder_ids(graph) if i not in never and i not in seen]
    return out


def answers(db, owner_id, graph: dict, mission: dict, *, m=None, position_id: Optional[str] = None,
            today: Optional[str] = None, simulate: bool = False, age_now: Optional[dict] = None) -> dict:
    """The mission's two answers, what it assumed, its calendar and its plan. Raises AnalysisError
    (``blocks`` set for blocks with no model)."""
    from backend.services import rbd_phases
    from backend.services import rbds as rbds_service

    setup = rbd_missions.setup_of(graph) or {"start": "now", "calendar": {"linked": True}, "from": "new"}
    phases = mission.get("phases") or []
    unit = graph.get("unit") or ""
    blocked = blocked_by(graph, phases)
    if blocked:
        return {"mission": {"id": mission["id"], "name": mission["name"]}, "unit": unit, "setup": setup,
                "blocked": blocked, "length": rbd_missions.duration(phases), "phases": len(phases)}
    notes: list[str] = []
    state = None
    simple = rbd_missions.is_simple(graph, mission)
    if setup["from"] == "today" and not simple and position_id:
        state, more = today_state(m, position_id, graph)
        notes += more
    chance = rbd_missions.analyze(db, owner_id, graph, phases, current_state=state, age_now=age_now, weakest=False)
    total = float(chance.get("duration") or rbd_missions.duration(phases))
    bound = chance.get("lower_bound")
    got = rbd_missions.bind(db, owner_id, graph, phases)
    if not bound and chance.get("reliability") is not None and chance.get("method") == "exact" and not simple \
            and len(got["phases"]) == 1 and not _structural(got["phases"]):
        try:
            bound = _single_phase_bound(db, owner_id, got, total, state)
        except (AnalysisError, ValueError):
            bound = None
    if bound:
        bound_note = (f"The bound is {round(BOUND_LEVEL * 100)}% one-sided: at least this chance, from the fitted "
                      "models' uncertainty.")
    elif len(got["phases"]) > 1:
        bound_note = "No bound yet for a mission of several phases: the figure is the fitted models' own."
    else:
        bound_note = chance.get("bound_note") or "No bound: no block has a fitted model's uncertainty to draw from."
    # The failures to expect: the whole mission on one clock, when its phases don't change the diagram.
    if chance.get("reliability") is None:
        fails = {"expected": None, "method": None, "range": None,
                 "note": "Waiting for the values the phases need (above)."}
    elif _structural(got["phases"]):
        fails = {"expected": None, "method": None, "range": None,
                 "note": ("Not worked out yet for a mission whose phases switch blocks off, stand them by or change "
                          "a vote: only the chance of completing it is.")}
    else:
        merged, merged_covs, _ = rbd_missions.combine(got["bound"], got["covs"], got["step_starts"])
        _, resolve_model = rbds_service.resolvers(db, owner_id)
        start_state = state
        if simple and chance.get("start", {}).get("age"):
            node = rbd_missions.simple_block(graph)
            start_state = {node["id"]: {"age": float(chance["start"]["age"])}}
        fails = expected_failures(_twin(merged, merged_covs), resolve_model, total, start_state, simulate)
    clock = clock_for(m, position_id, setup)
    span = calendar_span(total, unit, clock, setup["start"], today or date.today().isoformat())
    if not (setup.get("calendar") or {}).get("linked"):
        span["clock"]["text"] = clock.plan  # "its own duty: 8 h a day, 5 days a week"
    return {
        "mission": {"id": mission["id"], "name": mission["name"]},
        "unit": unit, "length": total, "phases": len(got["phases"]), "setup": setup, "calendar": span,
        "chance": {"value": chance.get("reliability"), "lower_bound": bound, "bound_note": bound_note,
                   "method": chance.get("method"), "start": chance.get("start")},
        "failures": fails,
        "plan": plan_of(m, position_id, graph) if position_id else [],
        "assumed": [*notes, *(chance.get("notes") or [])[:4], PLAN_NOTE],
        "series_warning": chance.get("series_warning"),
    }
