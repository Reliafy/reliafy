"""Phased missions on a non-repairable diagram (#160).

A mission (take-off, cruise, landing) runs through phases in order, each with
its own duration and its own needs: a block that only matters in some phases,
or a vote node that needs more of its inputs in one phase than another. The
blocks are the same physical components throughout: one that fails in a phase
stays failed in the later ones, so the mission's reliability is not the
product of the phases'. RePyability's ``PhasedMission`` takes exactly this:
one ``NonRepairableRBD`` per phase over the same components, and works the
mission out exactly with a decision diagram over each component's life split
into one segment per phase (Esary and Ziehms), or by simulation where that
diagram would be too large.

A diagram holds its phases as::

    "phases": [
      {"name": "Take-off", "duration": 0.1,
       "not_needed": ["c3"],         # blocks this phase doesn't need
       "votes": {"k1": 2}},          # a vote node's required count in this phase
      {"name": "Cruise", "duration": 5}
    ]

Each phase's diagram is the drawn diagram with:

* every block in ``not_needed`` replaced by a perfectly reliable stand-in of
  its own (under a name of its own, so the block's real life still runs
  through the phase: a block that isn't needed now can still fail, and is
  then failed in a later phase that needs it). A repeated block's copies go
  with it;
* each vote node's required count taken from ``votes`` where given.

Blocks pinned working or failed are perfectly reliable or failed throughout.
What the engine has no place for is refused in plain words rather than
approximated: common-cause groups (a phased mission doesn't model them), a
repairable diagram, and a stress level per phase (every block keeps one life
model through the mission).
"""

from __future__ import annotations

import math
import warnings
from typing import Any, Callable, Optional

from backend.services import rbd_repeats
from backend.services.rbd_analysis import AnalysisError

#: The most phases a mission may have.
MAX_PHASES = 50
#: Phase names are kept to this many characters.
MAX_NAME = 80
#: Simulated missions when the exact decision diagram is too large, and the
#: seed (the same figures every time for the same diagram).
SIM_MISSIONS = 20_000
SIM_SEED = 1
SIM_CONFIDENCE = 0.95

STRESS_NOTE = ("Each block keeps one life model through the whole mission: a stress level per phase isn't "
               "modelled.")


class PhaseError(ValueError):
    """A ``phases`` setting that can't be read (user-facing text)."""


# ---------------------------------------------------------------------------
# The setting
# ---------------------------------------------------------------------------
def _ids(value, where: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise PhaseError(f"{where}: not_needed must be a list of block ids.")
    out = []
    for v in value:
        if not isinstance(v, (str, int)) or isinstance(v, bool) or str(v).strip() == "":
            raise PhaseError(f"{where}: not_needed must be a list of block ids.")
        out.append(str(v).strip())
    return list(dict.fromkeys(out))


def _votes(value, where: str) -> dict[str, int]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise PhaseError(f"{where}: votes must map a vote node's id to the number of inputs it needs.")
    out = {}
    for key, n in value.items():
        if isinstance(n, bool):
            raise PhaseError(f"{where}: votes for '{key}' must be a whole number of at least 1.")
        try:
            number = float(n)
        except (TypeError, ValueError):
            raise PhaseError(f"{where}: votes for '{key}' must be a whole number of at least 1.") from None
        if not math.isfinite(number) or number != int(number) or number < 1:
            raise PhaseError(f"{where}: votes for '{key}' must be a whole number of at least 1.")
        out[str(key)] = int(number)
    return out


def parse_phases(raw) -> list[dict]:
    """The phases in their clean stored shape. Raises :class:`PhaseError`."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise PhaseError("phases must be a list of {name, duration}.")
    if len(raw) > MAX_PHASES:
        raise PhaseError(f"a mission can have at most {MAX_PHASES} phases (got {len(raw)}).")
    out, names = [], set()
    for i, phase in enumerate(raw):
        where = f"phase {i + 1}"
        if not isinstance(phase, dict):
            raise PhaseError(f"{where} must be an object with a name and a duration.")
        name = str(phase.get("name") or "").strip()[:MAX_NAME]
        if not name:
            raise PhaseError(f"{where} needs a name.")
        where = f"phase “{name}”"
        if name.casefold() in names:
            raise PhaseError(f"two phases are named “{name}”: give each phase its own name.")
        names.add(name.casefold())
        duration = phase.get("duration")
        try:
            value = float(duration)
        except (TypeError, ValueError):
            value = float("nan")
        if isinstance(duration, bool) or not math.isfinite(value) or value < 0:
            raise PhaseError(f"{where}: the duration must be a number of at least 0.")
        clean = {"name": name, "duration": value}
        not_needed = _ids(phase.get("not_needed"), where)
        if not_needed:
            clean["not_needed"] = not_needed
        votes = _votes(phase.get("votes"), where)
        if votes:
            clean["votes"] = votes
        out.append(clean)
    return out


def carry(graph: dict, out: dict) -> None:
    """Copy a graph's phases, cleaned, into ``out`` (a normalised or compact
    graph). Raises :class:`backend.services.rbd_graph.GraphError` for a
    setting that can't be read."""
    from backend.services.rbd_graph import GraphError

    if not graph.get("phases"):
        return
    try:
        phases = parse_phases(graph["phases"])
    except PhaseError as exc:
        raise GraphError(str(exc)) from None
    if phases:
        out["phases"] = phases


def apply_set(graph: dict, op: dict) -> list[str]:
    """edit_rbd's ``set`` of ``phases`` ([] clears them): what was done, in
    words. Raises :class:`backend.services.rbd_graph.GraphError`."""
    from backend.services.rbd_graph import GraphError

    if op.get("phases") is None:
        return []
    try:
        phases = parse_phases(op["phases"])
    except PhaseError as exc:
        raise GraphError(str(exc)) from None
    if not phases:
        graph.pop("phases", None)
        return ["phased mission cleared"]
    if graph.get("repairable"):
        raise GraphError("phases apply to a non-repairable diagram — set repairable false too.")
    if graph.get("network"):
        raise GraphError("a network has no phases — set network false too.")
    graph["phases"] = phases
    return [f"phased mission set ({', '.join(p['name'] for p in phases)})"]


def has_phases(graph: dict) -> bool:
    return bool(isinstance(graph, dict) and graph.get("phases"))


def validation_warnings(graph: dict) -> list[str]:
    """Problems with a diagram's phases that the builder's check reports as
    warnings (the diagram itself is still valid): a malformed setting, blocks
    that are no longer in the diagram, or a vote count its wiring can't meet."""
    if not has_phases(graph):
        return []
    try:
        phases = parse_phases(graph.get("phases"))
    except PhaseError as exc:
        return [f"Phased mission: {exc}"]
    if graph.get("repairable"):
        return ["Phased mission: phases apply to a non-repairable diagram; this one is repairable, so its "
                "phases aren't analysed."]
    nodes = {n.get("id"): n for n in graph.get("nodes") or [] if isinstance(n, dict)}
    feeding: dict = {}
    for e in graph.get("edges") or []:
        if isinstance(e, dict) and e.get("target") is not None:
            feeding[e["target"]] = feeding.get(e["target"], 0) + 1
    out = []
    for phase in phases:
        gone = [b for b in phase.get("not_needed", []) if b not in nodes]
        if gone:
            out.append(f"Phase “{phase['name']}” lists blocks that aren't in the diagram any more "
                       f"({', '.join(gone)}); they're ignored.")
        for nid, n in (phase.get("votes") or {}).items():
            node = nodes.get(nid)
            if node is None or node.get("type") != "knode":
                out.append(f"Phase “{phase['name']}” sets a vote count for '{nid}', which isn't a vote node; "
                           "it's ignored.")
            elif n > feeding.get(nid, 0):
                label = (node.get("data") or {}).get("label") or "vote node"
                out.append(f"Phase “{phase['name']}”: the {label} ({nid}) needs {n} working inputs but only "
                           f"{feeding.get(nid, 0)} feed it.")
    return out


# ---------------------------------------------------------------------------
# The mission
# ---------------------------------------------------------------------------
def _stand_in(nid: str, j: int) -> str:
    """The name of block ``nid``'s perfectly reliable stand-in in phase ``j``."""
    return f"{nid}~phase{j + 1}"


def build_mission(
    graph: dict,
    resolve_subsystem: Optional[Callable[[str], dict]] = None,
    resolve_model=None,
    covariates: Optional[dict] = None,
):
    """``(PhasedMission, phases, labels)`` for a diagram with phases. Raises
    :class:`AnalysisError` in plain words for what a phased mission can't
    take."""
    from repyability import PhasedMission
    from repyability.rbd.helper_classes import PerfectReliability, PerfectUnreliability
    from repyability.rbd.non_repairable_rbd import NonRepairableRBD

    from backend.services import rbd_analysis as ra

    try:
        phases = parse_phases(graph.get("phases"))
    except PhaseError as exc:
        raise AnalysisError(f"The diagram's phases can't be read: {exc}") from None
    if not phases:
        raise AnalysisError("The diagram has no phases yet. Add the mission's phases (each with a name and a "
                            "duration) under ⋯ → Phased mission.")
    if graph.get("repairable"):
        raise AnalysisError("A phased mission is analysed on a non-repairable diagram: in a repairable one "
                            "failed blocks are repaired, which a phased mission doesn't model.")
    if graph.get("network"):
        raise AnalysisError("A phased mission is analysed on a block diagram, not a network.")
    ccf = [g for g in graph.get("ccf_groups") or [] if isinstance(g, dict) and len(g.get("members") or []) >= 2]
    if ccf:
        raise AnalysisError("A phased mission doesn't model common-cause groups, so it can't be analysed with "
                            "them. Remove the diagram's common-cause groups to analyse the mission.")

    rbd, labels, node_types, reliabilities, working, broken, _ = ra._build_rbd(
        graph, resolve_subsystem, None, resolve_model, covariates)
    nodes = graph.get("nodes") or []
    edges = [(e["source"], e["target"]) for e in graph.get("edges") or [] if e.get("source") and e.get("target")]
    feeding: dict = {}
    for _, t in edges:
        feeding[t] = feeding.get(t, 0) + 1
    node_ids = {n.get("id") for n in nodes}
    io = {"input_node": "input" if "input" in node_ids else None,
          "output_node": "output" if "output" in node_ids else None}
    k = {n.get("id"): max(int((n.get("data") or {}).get("n") or 1), 1) for n in nodes if n.get("type") == "knode"}
    repeats, _ = rbd_repeats.find_repeats(nodes)
    copies: dict = {}
    for copy, original in repeats.items():
        copies.setdefault(original, []).append(copy)

    base = dict(reliabilities)
    # Blocks pinned working or failed stay so through the mission (a copy
    # names its original, so it follows).
    for nid in working:
        base[nid] = PerfectReliability
    for nid in broken:
        base[nid] = PerfectUnreliability

    built = []
    for j, phase in enumerate(phases):
        rel = dict(base)
        kk = dict(k)
        for nid, n in (phase.get("votes") or {}).items():
            if nid not in k:
                continue
            if n > feeding.get(nid, 0):
                raise AnalysisError(
                    f"Phase “{phase['name']}”: the vote node “{labels.get(nid, nid)}” needs {n} working inputs "
                    f"but only {feeding.get(nid, 0)} feed it.")
            kk[nid] = n
        stand: set = set()
        for nid in phase.get("not_needed", []):
            original = repeats.get(nid, nid)
            if original not in rel or node_types.get(original) == "knode":
                continue
            stand.add(original)
            stand.update(copies.get(original, []))
        rename = {nid: _stand_in(nid, j) for nid in stand}
        for nid in stand:
            del rel[nid]
            rel[rename[nid]] = PerfectReliability
        phase_edges = [(rename.get(a, a), rename.get(b, b)) for a, b in edges]
        try:
            diagram = NonRepairableRBD(phase_edges, rel, k=kk, on_infeasible_rbd="raise", **io)
        except ValueError as exc:
            raise AnalysisError(f"Phase “{phase['name']}” isn't a valid diagram: "
                                f"{ra._repyability_message(exc)}.") from None
        built.append((phase["name"], phase["duration"], diagram))
    try:
        mission = PhasedMission(built)
    except ValueError as exc:
        raise AnalysisError(f"The mission can't be built: {exc}") from None
    return mission, phases, labels


def _plain_unit(graph: dict) -> str:
    return (graph.get("unit") or "").strip()


def analyze_phases(
    graph: dict,
    resolve_subsystem: Optional[Callable[[str], dict]] = None,
    resolve_model=None,
    covariates: Optional[dict] = None,
) -> dict:
    """The mission's reliability, each phase's chance of being where the
    mission fails, the reliability at the end of each phase, and the riskiest
    phase. Exact where the decision diagram fits; otherwise simulated (with
    an interval), and the result says which."""
    mission, phases, labels = build_mission(graph, resolve_subsystem, resolve_model, covariates)
    interval = None
    reason = None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            reliability = float(mission.reliability())
            unreliability = float(mission.unreliability())
            failing = mission.phase_failure_probabilities()
        method = "exact"
    except NotImplementedError:
        reason = ("The mission is too large to work out exactly, so it was simulated "
                  f"({SIM_MISSIONS:,} missions).")
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                ci = mission.reliability_interval(SIM_MISSIONS, seed=SIM_SEED, confidence=SIM_CONFIDENCE)
                failing = mission.phase_failure_probabilities("simulate", mc_samples=SIM_MISSIONS, seed=SIM_SEED)
        except (NotImplementedError, AttributeError, TypeError) as exc:
            raise AnalysisError("The mission is too large to work out exactly, and one of its blocks can't be "
                                f"simulated ({exc}).") from None
        reliability = float(ci.estimate)
        unreliability = 1.0 - reliability
        interval = {"lower": float(ci.lower), "upper": float(ci.upper), "confidence": float(ci.confidence),
                    "n_samples": int(ci.n_samples)}
        method = "simulated"

    rows = []
    start = 0.0
    reached = 1.0  # the chance the mission reaches the phase's start
    for phase, engine_phase in zip(phases, mission.phases):
        fail = float(max(failing.get(phase["name"], 0.0), 0.0))
        row = {
            "name": phase["name"],
            "duration": phase["duration"],
            "start": start,
            "end": float(engine_phase.end),
            "failure_probability": fail,
            # The share of the mission's failures that happen in this phase.
            "share": fail / unreliability if unreliability > 0 else 0.0,
            # Given the mission reached the phase, the chance it fails in it.
            "conditional_failure": fail / reached if reached > 0 else None,
            "reliability_at_end": float(min(max(reached - fail, 0.0), 1.0)),
        }
        nn = [labels.get(n, n) for n in phase.get("not_needed", []) if n in labels]
        if nn:
            row["not_needed"] = nn
        votes = [{"id": n, "label": labels.get(n, n), "n": v} for n, v in (phase.get("votes") or {}).items()
                 if n in labels]
        if votes:
            row["votes"] = votes
        rows.append(row)
        reached = row["reliability_at_end"]
        start = float(engine_phase.end)
    riskiest = max(rows, key=lambda r: r["failure_probability"]) if unreliability > 0 else None
    out = {
        "unit": _plain_unit(graph),
        "method": method,
        "reliability": reliability,
        "unreliability": unreliability,
        "duration": float(mission.duration),
        "phases": rows,
        "riskiest": ({"name": riskiest["name"], "failure_probability": riskiest["failure_probability"],
                      "share": riskiest["share"]} if riskiest else None),
        "notes": [STRESS_NOTE],
    }
    if interval is not None:
        out["interval"] = interval
    if reason:
        out["method_reason"] = reason
    return out


def analyze_for_owner(db, graph: dict, owner_id, covariates: Optional[dict] = None) -> dict:
    """:func:`analyze_phases` with sub-systems and saved models resolved in
    the caller's scope, exactly as ``rbds.analyze_graph`` resolves them."""
    from backend.services import models as models_service
    from backend.services import rbds as rbds_service

    def resolve_subsystem(sub_id: str) -> dict | None:
        sub = rbds_service.get_rbd(db, sub_id, owner_id)
        return sub.graph if sub is not None else None

    def resolve_model(model_id: str) -> dict | None:
        return models_service.get_live_model(db, model_id, owner_id)

    return analyze_phases(graph, resolve_subsystem=resolve_subsystem, resolve_model=resolve_model,
                          covariates=covariates)


def agent_summary(result: dict) -> dict:
    """The mission result for the MCP tools: the same figures, compactly."""
    out: dict[str, Any] = {
        "method": result["method"],
        "mission_reliability": result["reliability"],
        "mission_duration": result["duration"],
        "phases": [{k: r[k] for k in ("name", "duration", "end", "failure_probability", "reliability_at_end",
                                      "conditional_failure") if k in r} for r in result["phases"]],
        "riskiest_phase": (result.get("riskiest") or {}).get("name"),
        "notes": list(result.get("notes") or []),
    }
    if result.get("interval"):
        out["interval"] = result["interval"]
    if result.get("method_reason"):
        out["notes"].insert(0, result["method_reason"])
    return out


# ---------------------------------------------------------------------------
# Download as Python
# ---------------------------------------------------------------------------
_MISSION_CODE = '''
# ---------------------------------------------------------------------------
# Phased mission: the phases in order, each with its duration, the blocks it
# doesn't need (they stand in as perfectly reliable for that phase, but their
# own lives still run on) and the vote nodes whose required count differs.
# ---------------------------------------------------------------------------
PHASES = [
__PHASES__
]
SIM_MISSIONS = __SIMS__
SIM_SEED = __SEED__


def phase_diagram(index, not_needed, votes):
    """One phase's diagram over the same blocks as the whole mission."""
    reliabilities = dict(RELIABILITIES)
    for node in WORKING_NODES:
        reliabilities[node] = PerfectReliability
    for node in BROKEN_NODES:
        reliabilities[node] = PerfectUnreliability
    stand = set()
    for node in not_needed:
        stand.add(node)
        # A repeated block's copies go with it.
        stand.update(n for n, v in RELIABILITIES.items() if isinstance(v, str) and v == node)
    rename = {node: f"{node}~phase{index + 1}" for node in stand}
    for node in stand:
        del reliabilities[node]
        reliabilities[rename[node]] = PerfectReliability
    edges = [(rename.get(a, a), rename.get(b, b)) for a, b in EDGES]
    return NonRepairableRBD(
        edges,
        reliabilities,
        k={**K, **votes},
__IO__    )


mission = PhasedMission([
    (name, duration, phase_diagram(i, not_needed, votes))
    for i, (name, duration, not_needed, votes) in enumerate(PHASES)
])


def report_mission():
    """The mission's reliability and where it fails, as Reliafy reports it:
    exact, or simulated when the mission is too large to work out exactly."""
    unit = f" {UNIT_TEXT}" if UNIT_TEXT else ""
    try:
        reliability = mission.reliability()
        failing = mission.phase_failure_probabilities()
        method = "exact"
    except NotImplementedError:
        interval = mission.reliability_interval(SIM_MISSIONS, seed=SIM_SEED)
        reliability = interval.estimate
        failing = mission.phase_failure_probabilities(
            "simulate", mc_samples=SIM_MISSIONS, seed=SIM_SEED
        )
        method = f"simulated, {SIM_MISSIONS:,} missions"
    print(f"\\nPhased mission ({method}): reliability {reliability:.6f} "
          f"over {mission.duration:,.6g}{unit}")
    reached = 1.0
    rows = []
    for name, duration, _, _ in PHASES:
        fail = failing[name]
        reached = max(reached - fail, 0.0)
        rows.append((name, fail, reached))
        print(f"  {name[:28]:<28} fails in it: {fail:.4g}  "
              f"reliability at its end: {reached:.6f}")
    riskiest = max(rows, key=lambda r: r[1])
    print(f"Riskiest phase: {riskiest[0]}")
    return {"method": method, "reliability": reliability,
            "phase_failure_probabilities": failing}
'''


def python_section(body: str, graph: dict, script) -> str:
    """Add the phased mission to a non-repairable "Download as Python" body:
    the phases, a diagram per phase and ``report_mission()``, run after the
    diagram's own calculation. A diagram with common-cause groups gets a
    comment instead (the app refuses those missions too)."""
    if not has_phases(graph) or graph.get("repairable") or graph.get("network"):
        return body
    try:
        phases = parse_phases(graph.get("phases"))
    except PhaseError:
        return body
    if not phases:
        return body
    from backend.services.rbd_export import _lit, _num

    tail = '\n\nif __name__ == "__main__":\n    main()'
    if not body.rstrip().endswith(tail.strip()):
        return body
    head = body.rstrip()[: -len(tail.strip())].rstrip()
    ccf = [g for g in graph.get("ccf_groups") or [] if isinstance(g, dict) and len(g.get("members") or []) >= 2]
    if ccf:
        note = ("# The diagram's phased mission isn't exported: a phased mission doesn't model\n"
                "# common-cause groups (Reliafy doesn't analyse it either).")
        return f"{head}\n\n\n{note}\n\n\nif __name__ == \"__main__\":\n    main()\n"
    ids = {n.get("id") for n in graph.get("nodes") or []}
    knodes = {n.get("id") for n in graph.get("nodes") or [] if n.get("type") == "knode"}
    repeats, _ = rbd_repeats.find_repeats(graph.get("nodes") or [])
    lines = []
    for p in phases:
        nn = sorted({repeats.get(b, b) for b in p.get("not_needed", [])
                     if b in ids and repeats.get(b, b) not in knodes})
        votes = {n: v for n, v in (p.get("votes") or {}).items() if n in knodes}
        nn_lit = "{" + ", ".join(_lit(b) for b in nn) + "}" if nn else "set()"
        votes_lit = "{" + ", ".join(f"{_lit(n)}: {v}" for n, v in votes.items()) + "}"
        lines.append(f"    ({_lit(p['name'])}, {_num(p['duration'])}, {nn_lit}, {votes_lit}),")
    io = ""
    if "input" in ids:
        io += "        input_node=\"input\",\n"
    if "output" in ids:
        io += "        output_node=\"output\",\n"
    code = (_MISSION_CODE.replace("__PHASES__", "\n".join(lines)).replace("__SIMS__", f"{SIM_MISSIONS:_}")
            .replace("__SEED__", str(SIM_SEED)).replace("__IO__", io)).strip("\n")
    script.imports.update({"PhasedMission", "PerfectReliability", "PerfectUnreliability"})
    return (f"{head}\n\n\n{code}\n\n\nif __name__ == \"__main__\":\n    results = main()\n"
            "    results[\"phased_mission\"] = report_mission()\n    save_results(results)\n")

