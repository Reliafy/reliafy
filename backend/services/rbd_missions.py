"""Missions on an RBD: named phased missions over the one diagram (Derryn, 9 Nov 2026: "Missions
are RBDs, so they belong to positions").

A diagram can be flown, driven or run in more than one way: a survey drone has a corridor
inspection and a survey grid, each a mission through its own phases (take-off, transit, survey,
landing) over the same blocks. A mission is stored **on its RBD**, so the diagram stays the one
source of truth for the blocks a mission's phases switch off, the vote nodes they change, and the
covariates they set::

    graph["missions"] = [
      {"id": "a1b2c3d4", "name": "Corridor inspection",
       "phases": [{"name": "Take-off", "duration": 0.05, "votes": {"k1": 4},
                   "values": {"Air temperature": 35},            # set once for the phase
                   "block_values": {"m3": {"temp_C": 50}}},      # one block's own, over it
                  {"name": "Transit", "duration": 0.4, "not_needed": ["cam"]}]},
    ]

A mission can also have an RBD of its own (one RBD per mission, built from what's inside its
position): that diagram carries ``graph["mission_of"] = {"position_id": …}`` and its own mission
(``phases``, named by ``mission_name``) is the mission, kept even before it has phases. The
position finds it by that key; it isn't one of the position's models, so it never becomes the
model a parent's block takes. Deleting that mission deletes its RBD.

``graph["phases"]`` (the builder's "Phased mission…", #160) is the diagram's own mission and
stays where it is: it reads as one more mission (id ``mission``, named by ``mission_name`` or
"Mission"), so diagrams saved before missions keep working unchanged. A position has the
missions of the RBDs linked to it; nothing is inherited from a parent position.

Each phase's covariates reach the blocks whose covariates were left open at their positions
(:mod:`.covariate_binding`: NSWC-11, accelerated life and proportional-hazards models). For a
phase, its values are the diagram's Use and Environment values and its block values are each
block's own, so the usual order holds: fixed at the position, then the block's own (this phase's,
then the diagram's), then the phase's value, then the diagram's, then a default. A block whose
values differ between phases follows them along the mission's clock with its age carried on
(standard phased-mission analysis: the same parts age across the whole mission): an NSWC-11 rate
by the time spent at each rate, an accelerated life model by cumulative exposure, a
proportional-hazards model by its hazard at each phase's values (both SurPyval's step schedules).
A phase missing a value waits: the mission is worked out up to it and says which blocks need what.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from backend.services import covariate_binding as cb
from backend.services import rbd_phases
from backend.services.rbd_analysis import AnalysisError

#: The diagram's own mission (``graph["phases"]``) read as one of its missions.
LEGACY_ID = "mission"
LEGACY_NAME = "Mission"
MAX_MISSIONS = 20
MAX_NAME = 80
_ID = re.compile(r"^[A-Za-z0-9_-]{1,40}$")


class MissionError(ValueError):
    """A mission that can't be read or saved (user-facing text)."""


# ---- the stored shape ------------------------------------------------------------------------

def _name(raw, what: str = "A mission") -> str:
    name = " ".join(str(raw or "").split())[:MAX_NAME]
    if not name:
        raise MissionError(f"{what} needs a name.")
    return name


def _phases(raw, where: str) -> list[dict]:
    try:
        return rbd_phases.parse_phases(raw or [])
    except rbd_phases.PhaseError as exc:
        raise MissionError(f"{where}: {exc}") from None


def parse_missions(raw) -> list[dict]:
    """``graph["missions"]`` in its clean stored shape. Raises :class:`MissionError`."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise MissionError("missions must be a list of {id, name, phases}.")
    if len(raw) > MAX_MISSIONS:
        raise MissionError(f"a diagram can have at most {MAX_MISSIONS} missions.")
    out, ids, names = [], {LEGACY_ID}, set()
    for i, m in enumerate(raw):
        if not isinstance(m, dict):
            raise MissionError(f"mission {i + 1} must be an object with an id, a name and phases.")
        mid = str(m.get("id") or "")
        if not _ID.match(mid) or mid in ids:
            raise MissionError(f"mission {i + 1} needs an id of its own (letters, digits, - and _).")
        ids.add(mid)
        name = _name(m.get("name"), f"Mission {i + 1}")
        if name.casefold() in names:
            raise MissionError(f"two missions are named “{name}”: give each its own name.")
        names.add(name.casefold())
        out.append({"id": mid, "name": name, "phases": _phases(m.get("phases"), f"mission “{name}”")})
    return out


def carry(graph: dict, out: dict) -> None:
    """Copy a graph's missions and its own mission's name, cleaned, into ``out`` (a normalised or
    compact graph). Raises :class:`MissionError`."""
    missions = parse_missions(graph.get("missions"))
    if missions:
        out["missions"] = missions
    owner = mission_of(graph)
    if owner:
        out["mission_of"] = owner
    if graph.get("mission_name") and (graph.get("phases") or owner):
        out["mission_name"] = _name(graph["mission_name"])


def mission_of(graph: dict) -> Optional[dict]:
    """The position a mission's own RBD belongs to ({position_id}), or None for any other diagram."""
    raw = (graph or {}).get("mission_of")
    if not isinstance(raw, dict):
        return None
    pid = str(raw.get("position_id") or "").strip()
    return {"position_id": pid[:80]} if pid else None


def missions_of(graph: dict) -> list[dict]:
    """Every mission of a diagram: its own (``phases``) first, then its named ones. Each {id, name,
    phases, own (the diagram's own)}; a setting that can't be read is left out."""
    graph = graph or {}
    out = []
    if graph.get("phases") or mission_of(graph):
        try:
            phases = rbd_phases.parse_phases(graph.get("phases"))
        except rbd_phases.PhaseError:
            phases = None
        if phases or (phases is not None and mission_of(graph)):
            name = " ".join(str(graph.get("mission_name") or "").split())[:MAX_NAME] or LEGACY_NAME
            out.append({"id": LEGACY_ID, "name": name, "phases": phases, "own": True})
    try:
        named = parse_missions(graph.get("missions"))
    except MissionError:
        named = []
    out.extend({**m, "own": False} for m in named)
    return out


def find(graph: dict, mission_id: str) -> Optional[dict]:
    return next((m for m in missions_of(graph) if m["id"] == mission_id), None)


def _new_id(graph: dict) -> str:
    taken = {m["id"] for m in missions_of(graph)} | {LEGACY_ID}
    while True:
        mid = secrets.token_hex(4)
        if mid not in taken:
            return mid


def save(graph: dict, mission_id: Optional[str] = None, name: Optional[str] = None,
         phases: Optional[list] = None) -> tuple[dict, dict]:
    """A new mission (no ``mission_id``) or changes to one: ``(graph, mission)``, the graph a new
    dict. A new one is named "Mission N" unless named. The diagram's own mission keeps living in
    ``phases`` (its name in ``mission_name``); giving it no phases removes it. Raises
    :class:`MissionError`."""
    graph = dict(graph or {})
    if graph.get("repairable"):
        raise MissionError("Missions are flown on a non-repairable diagram: in a repairable one failed blocks "
                           "are repaired, which a mission doesn't model. Make the diagram non-repairable first.")
    if graph.get("network"):
        raise MissionError("A network has no missions: missions are flown on a block diagram.")
    named = parse_missions(graph.get("missions"))
    others = {m["name"].casefold() for m in missions_of(graph) if m["id"] != mission_id}
    if name is not None:
        name = _name(name)
        if name.casefold() in others:
            raise MissionError(f"There's already a mission named “{name}”: give this one its own name.")
    if mission_id == LEGACY_ID:
        if not graph.get("phases") and not mission_of(graph):
            raise MissionError("This diagram has no mission of its own.")
        if phases is not None:
            clean = _phases(phases, "the mission")
            if clean:
                graph["phases"] = clean
            elif mission_of(graph):  # a mission's own RBD keeps its mission with no phases
                graph.pop("phases", None)
            else:
                graph.pop("phases", None)
                graph.pop("mission_name", None)
                return graph, {"id": LEGACY_ID, "name": LEGACY_NAME, "phases": [], "own": True}
        if name is not None:
            if name == LEGACY_NAME:
                graph.pop("mission_name", None)
            else:
                graph["mission_name"] = name
        return graph, find(graph, LEGACY_ID)
    if mission_id is None and mission_of(graph):
        raise MissionError("This RBD is one mission's own. Add a new mission on its position: it gets an RBD "
                           "of its own.")
    if mission_id is None:
        if len(missions_of(graph)) >= MAX_MISSIONS:
            raise MissionError(f"A diagram can have at most {MAX_MISSIONS} missions.")
        if name is None:
            k = len(missions_of(graph)) + 1
            while f"mission {k}" in others:
                k += 1
            name = f"Mission {k}"
        mission = {"id": _new_id(graph), "name": name,
                   "phases": _phases(phases, f"mission “{name}”") if phases is not None else []}
        graph["missions"] = [*named, mission]
        return graph, {**mission, "own": False}
    at = next((i for i, m in enumerate(named) if m["id"] == mission_id), None)
    if at is None:
        raise MissionError("That mission isn't on this diagram (deleted?).")
    mission = dict(named[at])
    if name is not None:
        mission["name"] = name
    if phases is not None:
        mission["phases"] = _phases(phases, f"mission “{mission['name']}”")
    named[at] = mission
    graph["missions"] = named
    return graph, {**mission, "own": False}


def remove(graph: dict, mission_id: str) -> dict:
    """The graph without that mission. Raises :class:`MissionError`."""
    graph = dict(graph or {})
    if mission_id == LEGACY_ID:
        if mission_of(graph):
            raise MissionError("This RBD is the mission's own: delete the mission to delete its RBD with it.")
        if not graph.get("phases"):
            raise MissionError("This diagram has no mission of its own.")
        graph.pop("phases", None)
        graph.pop("mission_name", None)
        return graph
    named = parse_missions(graph.get("missions"))
    kept = [m for m in named if m["id"] != mission_id]
    if len(kept) == len(named):
        raise MissionError("That mission isn't on this diagram (deleted?).")
    if kept:
        graph["missions"] = kept
    else:
        graph.pop("missions", None)
    return graph


# ---- a mission in a list, and whether its last result still holds ---------------------------

def signature(graph: dict, phases: list) -> str:
    """What a mission's result depends on, hashed: the blocks and their models, the wiring, the
    unit, the diagram's values and the mission's phases (a saved model refitted since isn't seen)."""
    nodes = [{"id": n.get("id"), "type": n.get("type"), "data": n.get("data")} for n in (graph or {}).get("nodes") or []]
    edges = sorted((str(e.get("source")), str(e.get("target"))) for e in (graph or {}).get("edges") or [])
    body = {"nodes": nodes, "edges": edges, "unit": (graph or {}).get("unit") or "",
            "conditions": (graph or {}).get("conditions") or [], "ccf": (graph or {}).get("ccf_groups") or [],
            "phases": phases}
    return hashlib.sha1(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()[:20]


def duration(phases: list) -> float:
    return float(sum(float(p.get("duration") or 0) for p in phases or []))


def summary(graph: dict, mission: dict, results: Optional[dict] = None) -> dict:
    """A mission as a row of a list: {id, name, own, phases (how many), phase_names, phase_durations
    (each phase's own length, in the same order), duration (all of them added up), unit, result (its
    last calculation, while it still holds: reliability, method, complete, at)}."""
    phases = mission.get("phases") or []
    out = {"id": mission["id"], "name": mission["name"], "own": bool(mission.get("own")),
           "phases": len(phases), "phase_names": [p["name"] for p in phases],
           "phase_durations": [float(p.get("duration") or 0) for p in phases],
           "duration": duration(phases), "unit": (graph or {}).get("unit") or ""}
    got = (results or {}).get(mission["id"])
    if isinstance(got, dict) and got.get("signature") == signature(graph, phases):
        out["result"] = {k: got.get(k) for k in ("reliability", "method", "complete", "at", "through")}
        if got.get("placeholders"):  # the blocks it rests on a placeholder for, and the figure without them
            out["result"]["placeholders"] = list(got["placeholders"])
            out["result"]["without_placeholders"] = got.get("without_placeholders")
    return out


def result_record(graph: dict, phases: list, result: dict) -> dict:
    """What's kept of a calculation on the RBD (``mission_results.<id>``) for the lists."""
    out = {"signature": signature(graph, phases), "reliability": result.get("reliability"),
           "method": result.get("method"), "complete": not result.get("needs"),
           "through": result.get("through"), "at": datetime.now(timezone.utc).isoformat()}
    if result.get("placeholders"):
        out["placeholders"] = [p["label"] for p in result["placeholders"]]
        out["without_placeholders"] = (result.get("without_placeholders") or {}).get("reliability")
    return out


# ---- the covariates a mission's phases can set ------------------------------------------------

def _inputs_cache(inputs_for: Callable[[dict], list]) -> Callable[[dict], list]:
    seen: dict = {}

    def get(binding: dict) -> list:
        key = json.dumps(binding, sort_keys=True, default=str)
        if key not in seen:
            try:
                seen[key] = inputs_for(binding)
            except cb.BindingError as exc:
                seen[key] = exc
        if isinstance(seen[key], Exception):
            raise seen[key]
        return seen[key]

    return get


def _norm(text) -> str:
    return cb._norm(text)


def gather(graph: dict, inputs_for: Callable[[dict], list]) -> dict:
    """Every Use and Environment covariate a mission's phases can set: the inputs left open at the
    positions of the diagram's bound blocks, one row per covariate however many blocks it feeds.
    {rows: [{name, role, unit, kind, choices, limits, help, symbol, diagram (the diagram's own value,
    or None), blocks: [{id, label, key, own (the block's own value, or None), default}]}],
    problems: [{id, label, problem}]}. Rows go Use first, then Environment, each A–Z; design
    covariates are fixed at the position and never appear."""
    conditions = (graph or {}).get("conditions") or []
    rows: dict = {}
    problems = []
    for n in (graph or {}).get("nodes") or []:
        data = n.get("data") or {}
        model = data.get("model") or {}
        if model.get("kind") != "bound":
            continue
        nid = n.get("id")
        label = data.get("label") or nid
        binding = model.get("binding") or {}
        try:
            inputs = inputs_for(binding)
        except cb.BindingError as exc:
            problems.append({"id": nid, "label": label, "problem": str(exc)})
            continue
        fixed = binding.get("fixed") or {}
        own = data.get("covariate_values") or {}
        mapping = data.get("covariate_map") or {}
        for inp in inputs:
            key = inp["key"]
            if key in fixed or inp.get("role") == "design":
                continue
            c = cb.match_condition(inp, conditions, mapping.get(key))
            name = c["name"] if c else (mapping.get(key) or inp.get("label") or key)
            gk = (_norm(name), cb._unit(inp.get("unit")), inp.get("role") or "use")
            row = rows.get(gk)
            if row is None:
                row = rows[gk] = {
                    "name": name, "role": inp.get("role") or "use", "unit": inp.get("unit") or "",
                    "kind": inp.get("kind") or "number", "choices": inp.get("choices"),
                    "limits": inp.get("limits") or [], "help": inp.get("help") or "", "symbol": inp.get("symbol"),
                    "diagram": c.get("value") if c else None, "blocks": []}
            value = own.get(key)
            row["blocks"].append({"id": nid, "label": label, "key": key,
                                  "own": None if value in (None, "") else value, "default": inp.get("default")})
    order = {"use": 0, "environment": 1}
    out = sorted(rows.values(), key=lambda r: (order.get(r["role"], 2), r["name"].casefold()))
    return {"rows": out, "problems": problems}


def _phase_value(phase: dict, name: str):
    values = phase.get("values") or {}
    want = _norm(name)
    return next((v for k, v in values.items() if _norm(k) == want), None)


def phase_rows(rows: list[dict], phase: dict) -> list[dict]:
    """``rows`` for one phase: each with the phase's value (``value``), and each block with this
    phase's own value for it (``override``), the value it uses and where that comes from
    (``used``, ``source``: override, own, phase, diagram, default), or ``missing``; a row's
    ``missing`` lists the blocks still without a value."""
    out = []
    block_values = phase.get("block_values") or {}
    for row in rows:
        value = _phase_value(phase, row["name"])
        blocks, missing = [], []
        for b in row["blocks"]:
            override = (block_values.get(b["id"]) or {}).get(b["key"])
            if override is not None:
                used, source = override, "override"
            elif b["own"] is not None:
                used, source = b["own"], "own"
            elif value is not None:
                used, source = value, "phase"
            elif row.get("diagram") not in (None, ""):
                used, source = row["diagram"], "diagram"
            elif b.get("default") is not None:
                used, source = b["default"], "default"
            else:
                used, source = None, None
            blocks.append({**b, "override": override, "used": used, "source": source, "missing": source is None})
            if source is None:
                missing.append(b["label"])
        out.append({**row, "value": value, "blocks": blocks, "missing": missing})
    return out


def phase_graph(graph: dict, phase: dict, rows: list[dict]) -> dict:
    """The diagram as one phase sees it: the phase's values as the diagram's Use and Environment
    values (over the diagram's own), and each block's values for the phase over its own."""
    conditions = [dict(c) for c in (graph or {}).get("conditions") or [] if isinstance(c, dict)]
    for row in rows:
        value = _phase_value(phase, row["name"])
        if value is None:
            continue
        hit = next((c for c in conditions if _norm(c.get("name")) == _norm(row["name"])), None)
        if hit is not None:
            hit["value"] = value
        else:
            conditions.append({"name": row["name"], "role": row["role"], "unit": row["unit"], "value": value})
    block_values = phase.get("block_values") or {}
    nodes = []
    for n in (graph or {}).get("nodes") or []:
        own = block_values.get(n.get("id"))
        if own:
            data = dict(n.get("data") or {})
            data["covariate_values"] = {**(data.get("covariate_values") or {}), **own}
            n = {**n, "data": data}
        nodes.append(n)
    return {**(graph or {}), "nodes": nodes, "conditions": conditions}


# ---- one diagram for the whole mission -------------------------------------------------------

def _same(a, b) -> bool:
    return json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)


def _steps(starts: list[float], values: list) -> list[tuple[float, Any]]:
    """(time, value) from each phase's start, a phase of no length giving way to the next and a
    value the same as the one before it folded in."""
    out: list = []
    for t, v in zip(starts, values):
        if out and out[-1][0] == t:
            out[-1] = (t, v)
        elif not out or not _same(out[-1][1], v):
            out.append((t, v))
    return out


def combine(bound: list[dict], covs: list[Optional[dict]], starts: list[float]) -> tuple[dict, dict, frozenset]:
    """One diagram for the whole mission from each phase's bound diagram: a block whose model is
    the same in every phase as it is; one whose covariates change by phase as its model along the
    mission's clock. ``(graph, covariates, the blocks that change)``. Raises AnalysisError for a
    block whose kind can't change by phase."""
    first = bound[0]
    by_phase = [{n.get("id"): n for n in g.get("nodes") or []} for g in bound]
    merged_covs = dict(covs[0] or {})
    varying = set()
    nodes = []
    for n in first.get("nodes") or []:
        nid = n.get("id")
        datas = [(p.get(nid) or n).get("data") or {} for p in by_phase]
        models = [d.get("model") for d in datas]
        values = [(c or {}).get(nid) for c in covs]
        if all(_same(m, models[0]) for m in models) and all(_same(v, values[0]) for v in values):
            nodes.append(n)
            continue
        varying.add(nid)
        label = datas[0].get("label") or nid
        m0 = models[0] or {}
        data = dict(datas[0])
        if m0.get("kind") == "alt_stress":
            steps = _steps(starts, [m.get("stress") for m in models])
            data["model"] = {**m0, "steps": [{"t": t, "stress": s} for t, s in steps]}
        elif m0.get("kind") == "regression":
            rows = [dict(v or {}) for v in values]
            schedules = {}
            for key in rows[0]:
                track = _steps(starts, [r.get(key) for r in rows])
                if len(track) > 1:
                    schedules[key] = {"table": [{"t": t, "value": v} for t, v in track]}
            data["covariate_schedules"] = schedules
            merged_covs[nid] = rows[0]
        elif m0.get("distribution_id") == "exponential":
            rates = [float(((m or {}).get("params") or [{}])[0].get("value") or 0.0) for m in models]
            steps = _steps(starts, rates)
            data["model"] = {"kind": "phase_rates", "name": "Exponential", "steps": [{"t": t, "rate": r} for t, r in steps]}
        else:
            raise AnalysisError(f"{label}: its covariates can't change from phase to phase in this kind of block.")
        nodes.append({**n, "data": data})
    return {**first, "nodes": nodes}, merged_covs, frozenset(varying)


def needs_message(needs: list[dict]) -> str:
    """'Set the covariates these blocks need first: Take-off: Pump A needs Temperature (…).'"""
    parts = [f"{n['phase']}: {'; '.join(n['lines'])}" for n in needs]
    return "Set the covariates these blocks need first: " + " · ".join(parts) + "."


def analyze(db, owner_id, graph: dict, phases, covariates: Optional[dict] = None,
            inputs_for: Optional[Callable[[dict], list]] = None, weakest: bool = True) -> dict:
    """A mission over ``graph``: rbd_phases.analyze_phases's result (the chance of completing it,
    each phase's failure probability, reliability at its end and weakest block), its phases' values
    reaching the blocks. A phase still missing a value: the mission is worked out up to it,
    ``reliability`` is None and ``through`` says how far it got ({phase, reliability}), each waiting
    phase is a row with ``waiting`` true, and ``needs`` says which blocks need what in each phase."""
    from backend.services import rbds as rbds_service

    try:
        clean = rbd_phases.parse_phases(phases or [])
    except rbd_phases.PhaseError as exc:
        raise AnalysisError(f"The mission's phases can't be read: {exc}") from None
    if not clean:
        raise AnalysisError("The mission has no phases yet. Add its phases, each with a name and a duration.")
    if graph.get("repairable"):
        raise AnalysisError("A phased mission is analysed on a non-repairable diagram: in a repairable one failed "
                            "blocks are repaired, which a phased mission doesn't model.")
    inputs_for = _inputs_cache(inputs_for or (lambda b: cb.inputs_of(b, db, owner_id)))
    rows = gather(graph, inputs_for)["rows"]
    starts, t = [], 0.0
    for p in clean:
        starts.append(t)
        t += float(p["duration"])
    bound, covs, needs = [], [], []
    for p in clean:
        g, c, lines = cb.bind_graph(phase_graph(graph, p, rows), inputs_for, covariates)
        if lines:
            needs.append({"phase": p["name"], "lines": lines})
        if needs:
            continue
        bound.append(g)
        covs.append(c)
    gap = len(bound)
    if gap == 0:
        return {"unit": (graph.get("unit") or "").strip(), "method": None, "reliability": None,
                "unreliability": None, "duration": duration(clean), "riskiest": None, "through": None,
                "phases": [_waiting(p, s) for p, s in zip(clean, starts)], "needs": needs, "notes": []}
    merged, merged_covs, varying = combine(bound, covs, starts[:gap])
    both = sorted({b for p in clean[:gap] for b in p.get("standby", [])} & varying)
    if both:
        labels = {n.get("id"): (n.get("data") or {}).get("label") or n.get("id") for n in graph.get("nodes") or []}
        raise AnalysisError(f"{', '.join(labels.get(b, b) for b in both)}: its covariates change from phase to phase, "
                            "so it can't also stand by in a phase. Set it Working or Not needed there, or give it the "
                            "same values in every phase.")
    resolve_subsystem, resolve_model = rbds_service.resolvers(db, owner_id)
    out = rbd_phases.analyze_phases(merged, resolve_subsystem, resolve_model, merged_covs or None,
                                    phases=clean[:gap], varying=varying, weakest=weakest)
    out["duration"] = duration(clean)
    if gap < len(clean):
        last = out["phases"][-1]
        out["through"] = {"phase": last["name"], "reliability": last["reliability_at_end"]}
        out["reliability"] = out["unreliability"] = out["riskiest"] = None
        out["without_placeholders"] = None
        out.pop("interval", None)
        out["phases"] += [_waiting(p, s) for p, s in zip(clean[gap:], starts[gap:])]
        out["needs"] = needs
    else:
        out["through"] = None
    return out


def _waiting(phase: dict, start: float) -> dict:
    return {"name": phase["name"], "duration": phase["duration"], "start": start,
            "end": start + float(phase["duration"]), "waiting": True}


# ---- a mission in full, for its pane and the tools --------------------------------------------

def detail(db, owner_id, graph: dict, mission: dict, inputs_for: Optional[Callable] = None) -> dict:
    """A mission with what its phases can set: {mission, unit, blocks (those a phase can do
    without; ``placeholder`` true for one with no model, a placeholder standing in), votes (vote nodes, the inputs feeding each and the count drawn), covariates (the rows
    of :func:`gather`), problems, phases: [{name, covariates: phase_rows, needs (block labels)}]}."""
    inputs_for = _inputs_cache(inputs_for or (lambda b: cb.inputs_of(b, db, owner_id)))
    got = gather(graph, inputs_for)
    nodes = (graph or {}).get("nodes") or []
    feeding: dict = {}
    for e in (graph or {}).get("edges") or []:
        feeding[e.get("target")] = feeding.get(e.get("target"), 0) + 1
    guessed = set(rbd_phases.placeholder_ids(graph or {}))
    blocks = [{"id": n.get("id"), "label": (n.get("data") or {}).get("label") or n.get("id"),
               "placeholder": n.get("id") in guessed}
              for n in nodes if n.get("type") not in ("input", "output", "knode")
              and not (n.get("data") or {}).get("repeat_of")]
    votes = [{"id": n.get("id"), "label": (n.get("data") or {}).get("label") or "Vote node",
              "n": max(int((n.get("data") or {}).get("n") or 1), 1), "inputs": feeding.get(n.get("id"), 0)}
             for n in nodes if n.get("type") == "knode"]
    phases = []
    for p in mission.get("phases") or []:
        rows = phase_rows(got["rows"], p)
        phases.append({"name": p["name"], "covariates": rows,
                       "needs": sorted({b for r in rows for b in r["missing"]})})
    return {"mission": mission, "unit": (graph or {}).get("unit") or "", "blocks": blocks, "votes": votes,
            "covariates": got["rows"], "problems": got["problems"], "phases": phases}



# ---- the missions on positions (the Explorer's Missions tab) ---------------------------------

def position_missions(m, db, owners, hidden=frozenset(), position_ids=None) -> list[dict]:
    """For each RBD linked to a position (its own, never a parent's): {position_id, link_id,
    in_use, rbd: {id, name, unit, repairable, network, mission_rbd} (None for one that's gone),
    missions: [summary]}; then each mission's own RBD (``mission_of``) as a row of its position
    with no link (``link_id`` None) and that one mission."""
    from backend.services import rbds as rbds_service

    def brief(rbd, graph) -> dict:
        return {"id": rbd.id, "name": rbd.name, "unit": graph.get("unit") or "",
                "repairable": bool(graph.get("repairable")), "network": bool(graph.get("network")),
                "mission_rbd": bool(mission_of(graph))}

    out = []
    for link in m.all_position_models(position_ids):
        if link.get("model_type") != "rbd":
            continue
        rbd = rbds_service.get_rbd(db, link.get("model_id"), owners) if link.get("model_id") else None
        row = {"position_id": link["position_id"], "link_id": link["id"], "in_use": bool(link.get("in_use")),
               "rbd": None, "missions": []}
        if rbd is not None and rbd.id not in hidden:
            graph = rbd.graph or {}
            doc = db.rbds.find_one({"_id": rbd.id}, {"mission_results": 1}) or {}
            row["rbd"] = brief(rbd, graph)
            row["missions"] = [summary(graph, x, doc.get("mission_results") or {}) for x in missions_of(graph)]
        out.append(row)
    live = {p["id"] for p in m.s.nodes(m.org, "Position") if not p.get("retired")}
    wanted = live & set(position_ids) if position_ids is not None else live
    if not wanted:
        return out
    from backend.services.access import owner_in

    query = {"graph.mission_of.position_id": {"$in": sorted(wanted)}, "owner_id": {"$in": owner_in(owners)}}
    for doc in db.rbds.find(query).sort("created_at", 1):
        if doc["_id"] in hidden:
            continue
        rbd = rbds_service.get_rbd(db, doc["_id"], owners)
        if rbd is None:
            continue
        graph = rbd.graph or {}
        out.append({"position_id": mission_of(graph)["position_id"], "link_id": None, "in_use": False,
                    "rbd": brief(rbd, graph),
                    "missions": [summary(graph, x, doc.get("mission_results") or {}) for x in missions_of(graph)]})
    return out


def own_missions(m, db, owners, position_id: str) -> list[dict]:
    """The missions on one position (every RBD of its own, and each mission's own RBD), as
    summaries: for naming a new one."""
    return [x for row in position_missions(m, db, owners, position_ids=[position_id]) for x in row["missions"]]
