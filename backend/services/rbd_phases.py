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
      {"name": "Cruise", "duration": 5,
       "values": {"Temperature": 15},          # Use / Environment values for the phase
       "block_values": {"c2": {"temp_C": 40}}} # one block's own, over the phase's
    ]

A diagram can hold more missions over the same blocks (``missions``: each with
an id, a name and phases like these; :mod:`.rbd_missions`); ``phases`` itself
is the diagram's own mission, as it always was.

Each phase's diagram is the drawn diagram with:

* every block in ``not_needed`` replaced by a perfectly reliable stand-in of
  its own (under a name of its own, so the block's real life still runs
  through the phase: a block that isn't needed now can still fail, and is
  then failed in a later phase that needs it). A repeated block's copies go
  with it;
* each vote node's required count taken from ``votes`` where given.

A block can also be on ``standby`` in a phase (``"standby": ["c2"]``): there,
ready, but not running. RePyability's standby groups are one block holding its
spares, not a setting per phase, so a block on standby is modelled as not
exposed in that phase: its clock stops for the phase (it neither ages nor
fails in it) and the phase's diagram keeps it, working if it was still working
when the phase began. Its age carries on when it next runs. The result says so
(``STANDBY_NOTE``). A block whose covariates change by phase can't also stand
by (its life is already a function of the mission's clock).

Blocks pinned working or failed are perfectly reliable or failed throughout.
Covariates set per phase (``values``, ``block_values``) reach the blocks whose
covariates were left open at their positions (:mod:`.covariate_binding`): such
a block's life then follows its phases' values along the mission's clock, its
age carried from one phase into the next (:mod:`.rbd_missions`). What the
engine has no place for is refused in plain words rather than approximated:
common-cause groups (a phased mission doesn't model them) and a repairable
diagram.
"""

from __future__ import annotations

import math
import warnings
from typing import Any, Callable, Optional

import numpy as np

from backend.errors import client_message
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

STRESS_NOTE = ("Each block keeps one non-repairable model through the whole mission, ageing from the start of the "
               "first phase to the end of the last.")
#: When some blocks' covariates change from phase to phase.
PHASE_VALUES_NOTE = ("Blocks whose covariates change from phase to phase carry their age into each phase: a block "
                     "wears faster in a harsher phase, and that wear stays with it for the rest of the mission.")
#: With covariate schedules (#52): those blocks follow their schedule through
#: the phases (it is a function of mission time); the others keep one model.
SCHEDULE_NOTE = ("Blocks with a covariate schedule follow it through the mission, so their stress changes "
                 "with time as the schedule says; the other blocks keep one non-repairable model throughout.")


#: What "not needed" and "standby" mean, for the result.
NOT_NEEDED_NOTE = ("Not needed: the phase works without the block. Its clock keeps running, so if it fails then, a "
                   "later phase that needs it finds it failed.")
#: Why a mission's chance has no bound, or what its range is (stated on every result).
NO_BOUND_NOTE = ("No bound: the mission is worked out exactly from each block's model at its point values, so "
                 "the uncertainty in a fitted model isn't carried into it (and figures typed in have none to carry).")
SIM_RANGE_NOTE = ("The range is the simulation's own precision ({n:,} missions), not the uncertainty in the blocks' "
                  "models, which isn't carried into a mission.")
STANDBY_NOTE = ("Standby: the block is there but not running, so it neither ages nor fails in that phase; it counts "
                "as working if it was still working when the phase began, and its age carries on when it next runs. "
                "Switching over is taken as perfect, and a standby block's running time after it takes over within "
                "the phase isn't counted.")


class PhaseError(ValueError):
    """A ``phases`` setting that can't be read (user-facing text)."""


# ---------------------------------------------------------------------------
# The setting
# ---------------------------------------------------------------------------
def _ids(value, where: str, field: str = "not_needed") -> list[str]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise PhaseError(f"{where}: {field} must be a list of block ids.")
    out = []
    for v in value:
        if not isinstance(v, (str, int)) or isinstance(v, bool) or str(v).strip() == "":
            raise PhaseError(f"{where}: {field} must be a list of block ids.")
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


#: The most covariate values a phase may set (its own, and per block).
MAX_VALUES = 200


def _value(v, what: str):
    """One covariate value: a finite number, or a choice's code (text). None for blank."""
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float, str)):
        raise PhaseError(f"{what} must be a number (or a choice).")
    if isinstance(v, str):
        text = v.strip()[:MAX_NAME]
        try:
            number = float(text)
        except ValueError:
            return text
        v = number
    v = float(v)
    if not math.isfinite(v):
        raise PhaseError(f"{what} must be a finite number.")
    return v


def _values(raw, where: str) -> dict:
    """A phase's Use and Environment values, set once for the phase: {covariate name: value}."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise PhaseError(f"{where}: values maps a covariate's name to its value in this phase.")
    if len(raw) > MAX_VALUES:
        raise PhaseError(f"{where}: at most {MAX_VALUES} values.")
    out = {}
    for key, v in raw.items():
        name = " ".join(str(key or "").split())[:MAX_NAME]
        if not name:
            raise PhaseError(f"{where}: a value needs the covariate's name.")
        value = _value(v, f"{where}: {name}")
        if value is not None:
            out[name] = value
    return out


def _block_values(raw, where: str) -> dict:
    """A phase's values for single blocks, over the phase's own: {block id: {input key: value}}."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise PhaseError(f"{where}: block_values maps a block's id to its own values in this phase.")
    out = {}
    for nid, vals in raw.items():
        if not isinstance(vals, dict):
            raise PhaseError(f"{where}: block_values for '{nid}' must map an input to its value.")
        got = {}
        for key, v in vals.items():
            value = _value(v, f"{where}: {key} of block '{nid}'")
            if value is not None and str(key).strip():
                got[str(key).strip()] = value
        if got:
            out[str(nid)] = got
    if sum(len(v) for v in out.values()) > MAX_VALUES:
        raise PhaseError(f"{where}: at most {MAX_VALUES} block values.")
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
        standby = _ids(phase.get("standby"), where, "standby")
        both = [b for b in standby if b in not_needed]
        if both:
            raise PhaseError(f"{where}: a block is either on standby or not needed, not both ({', '.join(both)}).")
        if standby:
            clean["standby"] = standby
        votes = _votes(phase.get("votes"), where)
        if votes:
            clean["votes"] = votes
        values = _values(phase.get("values"), where)
        if values:
            clean["values"] = values
        block_values = _block_values(phase.get("block_values"), where)
        if block_values:
            clean["block_values"] = block_values
        out.append(clean)
    return out


def carry(graph: dict, out: dict) -> None:
    """Copy a graph's phases, cleaned, into ``out`` (a normalised or compact
    graph). Raises :class:`backend.services.rbd_graph.GraphError` for a
    setting that can't be read."""
    from backend.services.rbd_graph import GraphError

    from backend.services import rbd_missions

    if graph.get("phases"):
        try:
            phases = parse_phases(graph["phases"])
        except PhaseError as exc:
            raise GraphError(str(exc)) from None
        if phases:
            out["phases"] = phases
    try:
        rbd_missions.carry(graph, out)
    except rbd_missions.MissionError as exc:
        raise GraphError(str(exc)) from None


def apply_set(graph: dict, op: dict) -> list[str]:
    """change rbd_edit's ``set`` of ``phases`` ([] clears them): what was done, in
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
    """Has the diagram's own phased mission (``phases``)."""
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
        return [f"Phased mission: {client_message(exc)}"]
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
        gone = [b for b in [*phase.get("not_needed", []), *phase.get("standby", [])] if b not in nodes]
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


class _Paused:
    """A block's life with its clock stopped while it stands by: at mission time ``t`` it has run
    ``t`` less the time spent on standby before ``t``, so R(t) = R₀(running time). Standby phases
    (``paused``: [(start, end)] of the mission's clock) neither age it nor fail it."""

    def __init__(self, base, paused):
        self.base = base
        self.dist = getattr(base, "dist", None)
        spans = sorted((float(a), float(b)) for a, b in paused if b > a)
        merged: list = []
        for a, b in spans:
            if merged and a <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], b))
            else:
                merged.append((a, b))
        self.paused = merged

    def running(self, x) -> np.ndarray:
        """The time the block has run by mission time ``x``."""
        x = np.atleast_1d(np.asarray(x, dtype=float))
        out = x.copy()
        for a, b in self.paused:
            out -= np.clip(x - a, 0.0, b - a)
        return np.maximum(out, 0.0)

    def sf(self, x) -> np.ndarray:
        return np.ravel(np.asarray(self.base.sf(self.running(x)), dtype=float))

    def ff(self, x) -> np.ndarray:
        return np.ravel(np.asarray(self.base.ff(self.running(x)), dtype=float))

    def random(self, size) -> np.ndarray:
        """A life drawn in running time, put on the mission's clock: each standby span that starts
        before the block has run out adds its length."""
        life = np.ravel(np.asarray(self.base.random(size), dtype=float))
        out = life.copy()
        done = 0.0  # standby time before each span
        for a, b in self.paused:
            out = np.where(life > a - done, out + (b - a), out)
            done += b - a
        return out

    def cs(self, x, X) -> np.ndarray:
        from backend.services.rbd_analysis import conditional_survival

        return conditional_survival(self, x, X)


def _standby_spans(phases: list[dict], repeats: dict) -> dict:
    """{block id: [(start, end)]}: the stretches of the mission's clock each block stands by in
    (a repeated block's copy names its original)."""
    out: dict = {}
    start = 0.0
    for phase in phases:
        end = start + float(phase["duration"])
        for nid in phase.get("standby", []):
            out.setdefault(repeats.get(nid, nid), []).append((start, end))
        start = end
    return out


def has_standby(phases) -> bool:
    return any(p.get("standby") for p in phases or [])


def _refuse(graph: dict) -> None:
    """What a phased mission can't be worked out on, in plain words (AnalysisError)."""
    if graph.get("repairable"):
        raise AnalysisError("A phased mission is analysed on a non-repairable diagram: in a repairable one "
                            "failed blocks are repaired, which a phased mission doesn't model.")
    if graph.get("network"):
        raise AnalysisError("A phased mission is analysed on a block diagram, not a network.")
    ccf = [g for g in graph.get("ccf_groups") or [] if isinstance(g, dict) and len(g.get("members") or []) >= 2]
    if ccf:
        raise AnalysisError("A phased mission doesn't model common-cause groups, so it can't be analysed with "
                            "them. Remove the diagram's common-cause groups to analyse the mission.")


def build_mission(
    graph: dict,
    resolve_subsystem: Optional[Callable[[str], dict]] = None,
    resolve_model=None,
    covariates: Optional[dict] = None,
    phases: Optional[list] = None,
    perfect: frozenset = frozenset(),
    built: Optional[tuple] = None,
):
    """``(PhasedMission, phases, labels, notes)`` for a diagram with phases
    (``phases``: these instead of the diagram's own); ``notes`` are the
    covariate schedules' warnings (#52). ``perfect``: blocks held perfectly
    reliable throughout (what a block costs the mission). ``built``: the
    diagram's blocks already built (``_build_rbd``'s result), so holding one
    block perfect doesn't build every model again. Raises
    :class:`AnalysisError` in plain words for what a phased mission can't
    take."""
    from repyability import PhasedMission
    from repyability.rbd.helper_classes import PerfectReliability, PerfectUnreliability
    from repyability.rbd.non_repairable_rbd import NonRepairableRBD

    from backend.services import rbd_analysis as ra

    try:
        phases = parse_phases(graph.get("phases") if phases is None else phases)
    except PhaseError as exc:
        raise AnalysisError(f"The mission's phases can't be read: {exc}") from None
    if not phases:
        raise AnalysisError("The mission has no phases yet. Add its phases, each with a name and a duration.")
    _refuse(graph)

    if built is None:
        built = ra._build_rbd(graph, resolve_subsystem, None, resolve_model, covariates)
    rbd, labels, node_types, reliabilities, working, broken, _ = built
    from backend.services import rbd_tvc

    notes = rbd_tvc.notes_of(reliabilities)
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
    for nid in perfect:
        if nid in base:
            base[nid] = PerfectReliability
    # Blocks on standby in some phases: their clocks stop there (one model through the mission,
    # so every phase's diagram shares it).
    for nid, spans in _standby_spans(phases, repeats).items():
        model = base.get(nid)
        if model is None or isinstance(model, str) or model is PerfectReliability or model is PerfectUnreliability \
                or node_types.get(nid) == "knode":
            continue
        base[nid] = _Paused(model, spans)

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
    return mission, phases, labels, notes


def _plain_unit(graph: dict) -> str:
    return (graph.get("unit") or "").strip()


#: The most blocks whose part in each phase's failures is worked out (one
#: mission per block): beyond it the weakest block per phase isn't given.
MAX_WEAKEST_BLOCKS = 60


def analyze_phases(
    graph: dict,
    resolve_subsystem: Optional[Callable[[str], dict]] = None,
    resolve_model=None,
    covariates: Optional[dict] = None,
    phases: Optional[list] = None,
    varying: frozenset = frozenset(),
    weakest: bool = False,
) -> dict:
    """The mission's reliability, each phase's chance of being where the
    mission fails, the reliability at the end of each phase, and the riskiest
    phase. Exact where the decision diagram fits; otherwise simulated (with
    an interval), and the result says which. ``phases``: these instead of the
    diagram's own; ``varying``: the blocks whose covariates change by phase
    (for the notes); ``weakest``: add each phase's weakest block (exact
    missions only)."""
    from backend.services import rbd_analysis as ra

    _refuse(graph)
    built = ra._build_rbd(graph, resolve_subsystem, None, resolve_model, covariates)
    mission, phases, labels, schedule_notes = build_mission(graph, resolve_subsystem, resolve_model, covariates,
                                                            phases=phases, built=built)
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
        sb = [labels.get(n, n) for n in phase.get("standby", []) if n in labels]
        if sb:
            row["standby"] = sb
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
        "notes": ([SCHEDULE_NOTE, *schedule_notes] if any((n.get("data") or {}).get("covariate_schedules")
                                                          for n in graph.get("nodes") or [] if n.get("id") not in varying)
                  else [] if varying else [STRESS_NOTE]) + ([PHASE_VALUES_NOTE, *schedule_notes] if varying else []),
    }
    if any(p.get("not_needed") for p in phases):
        out["notes"].append(NOT_NEEDED_NOTE)
    if has_standby(phases):
        out["notes"].append(STANDBY_NOTE)
    if interval is not None:
        out["interval"] = interval
        out["bound_note"] = SIM_RANGE_NOTE.format(n=interval["n_samples"])
    else:
        out["bound_note"] = NO_BOUND_NOTE
    if reason:
        out["method_reason"] = reason
    guessed = _add_placeholders(out, graph, resolve_subsystem, resolve_model, covariates, phases, built, labels)
    if weakest:
        _add_weakest(out, graph, resolve_subsystem, resolve_model, covariates, phases, built, labels,
                     skip=frozenset(guessed))
    return out


def _candidates(graph: dict, built: tuple) -> list[str]:
    """The blocks that can fail: every component the diagram built a model for (not its vote
    nodes, junctions, repeated copies, or blocks pinned working or failed)."""
    _, _, node_types, reliabilities, working, broken, _ = built
    repeats, _ = rbd_repeats.find_repeats(graph.get("nodes") or [])
    out = []
    for n in graph.get("nodes") or []:
        nid = n.get("id")
        if (nid not in reliabilities or nid in repeats or nid in working or nid in broken
                or node_types.get(nid) in ("knode", "input", "output")):
            continue
        out.append(nid)
    return out


PLACEHOLDER_NOTE = ("{names} {have} no model: a placeholder life stands in, so the result is not a real figure "
                    "until {they} {have} one.")
WEAKEST_PLACEHOLDER_NOTE = ("The weakest block in each phase is the weakest of the blocks with a model: a block "
                            "with a placeholder isn't ranked.")


def placeholder_ids(graph: dict) -> list[str]:
    """The blocks whose model is a placeholder (a guessed life standing in for none)."""
    return [n.get("id") for n in graph.get("nodes") or []
            if isinstance((n.get("data") or {}).get("model"), dict) and n["data"]["model"].get("placeholder")]


def _add_placeholders(out: dict, graph: dict, resolve_subsystem, resolve_model, covariates, phases, built,
                      labels) -> list[str]:
    """Say which blocks the result rests on a placeholder for, and what it is without them.

    ``placeholders``: the blocks with a placeholder model that some phase needs ({id, label});
    ``placeholders_left_out``: those no phase needs (Not needed throughout: they don't touch the
    result); ``blocks``: how many blocks can fail; ``without_placeholders``: the mission with
    every placeholder block never failing ({reliability, unreliability}; None where that can't be
    worked out exactly). Returns the placeholder ids that count."""
    blocks = _candidates(graph, built)
    out["blocks"] = len(blocks)
    guessed = [nid for nid in placeholder_ids(graph) if nid in set(blocks)]
    never = set.intersection(*(set(p.get("not_needed", [])) for p in phases)) if phases else set()
    counted = [nid for nid in guessed if nid not in never]
    out["placeholders"] = [{"id": nid, "label": labels.get(nid, nid)} for nid in counted]
    out["placeholders_left_out"] = [{"id": nid, "label": labels.get(nid, nid)} for nid in guessed if nid in never]
    out["without_placeholders"] = None
    if not counted:
        return counted
    # With no block left that has a model, "without them" would be a certain 100%: not a figure.
    if len(guessed) < len(blocks) and out["method"] == "exact":
        try:
            mission, _, _, _ = build_mission(graph, resolve_subsystem, resolve_model, covariates, phases=phases,
                                             perfect=frozenset(counted), built=built)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                r = float(mission.reliability())
            out["without_placeholders"] = {"reliability": r, "unreliability": 1.0 - r}
        except (AnalysisError, NotImplementedError, ValueError):
            pass
    return counted


def placeholder_note(result: dict) -> Optional[str]:
    """The sentence that goes with a result resting on placeholders, or None."""
    names = [p["label"] for p in result.get("placeholders") or []]
    if not names:
        return None
    one = len(names) == 1
    text = PLACEHOLDER_NOTE.format(names=", ".join(names), have="has" if one else "have", they="it" if one else "they")
    without = (result.get("without_placeholders") or {}).get("reliability")
    if without is not None and result.get("reliability") is not None:
        text += f" With {'that block' if one else 'those blocks'} left out, the mission's reliability is {without:.4g}."
    return text


def _add_weakest(out: dict, graph: dict, resolve_subsystem, resolve_model, covariates, phases, built,
                 labels, skip: frozenset = frozenset()) -> None:
    """Each phase's weakest block: the one whose failures end the most missions in that phase. For
    each block, the mission is worked out again with that block never failing; the fall in the
    chance of failing in each phase is the block's part in it (those parts add up, over the phases,
    to how much the mission's reliability would rise). Exact missions only. ``skip``: blocks not
    ranked (those with a placeholder model: a guessed life is never named the weakest)."""
    rows = out["phases"]
    if out["method"] != "exact" or out["unreliability"] <= 0:
        if out["method"] != "exact":
            out["weakest_note"] = "The weakest block per phase is worked out for missions solved exactly."
        return
    blocks = [nid for nid in _candidates(graph, built) if nid not in skip]
    if skip:
        out["weakest_note"] = WEAKEST_PLACEHOLDER_NOTE
    if len(blocks) > MAX_WEAKEST_BLOCKS:
        out["weakest_note"] = (f"The weakest block per phase is worked out for up to {MAX_WEAKEST_BLOCKS} blocks; "
                               f"this diagram has {len(blocks)}.")
        return
    base = [r["failure_probability"] for r in rows]
    best: list = [None] * len(rows)
    for nid in blocks:
        try:
            mission, _, _, _ = build_mission(graph, resolve_subsystem, resolve_model, covariates, phases=phases,
                                             perfect=frozenset({nid}), built=built)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                failing = mission.phase_failure_probabilities()
        except (AnalysisError, NotImplementedError, ValueError):
            continue
        for j, phase in enumerate(phases):
            part = base[j] - float(max(failing.get(phase["name"], 0.0), 0.0))
            if part > 1e-15 and (best[j] is None or part > best[j]["part"]):
                best[j] = {"id": nid, "label": labels.get(nid, nid), "part": part,
                           "share": part / base[j] if base[j] > 0 else 0.0}
    for row, b in zip(rows, best):
        row["weakest"] = b


def analyze_for_owner(db, graph: dict, owner_id, covariates: Optional[dict] = None) -> dict:
    """The diagram's own phased mission (``phases``) for the caller: sub-systems and saved models
    resolved in their scope, as ``rbds.analyze_graph`` resolves them, and blocks whose covariates
    were left open at their positions given the phases' values (:mod:`.rbd_missions`). A phase
    still missing a value stops it, saying which blocks need what."""
    from backend.services import rbd_missions

    result = rbd_missions.analyze(db, owner_id, graph, graph.get("phases"), covariates=covariates)
    if result.get("needs"):
        raise AnalysisError(rbd_missions.needs_message(result["needs"]))
    return result


def agent_summary(result: dict) -> dict:
    """The mission result for the MCP tools: the same figures, compactly."""
    out: dict[str, Any] = {
        "method": result["method"],
        "mission_reliability": result["reliability"],
        "mission_duration": result["duration"],
        "phases": [{**{k: r[k] for k in ("name", "duration", "end", "failure_probability", "reliability_at_end",
                                         "conditional_failure", "waiting") if k in r},
                    **({"weakest_block": r["weakest"]["label"], "weakest_share": r["weakest"]["share"]}
                       if r.get("weakest") else {})} for r in result["phases"]],
        "riskiest_phase": (result.get("riskiest") or {}).get("name"),
        "notes": list(result.get("notes") or []),
    }
    if result.get("needs"):
        out["needs"] = result["needs"]
        out["through"] = result.get("through")
    if result.get("interval"):
        out["interval"] = result["interval"]
    if result.get("bound_note") and result.get("reliability") is not None:
        out["bound_note"] = result["bound_note"]
    if result.get("method_reason"):
        out["notes"].insert(0, result["method_reason"])
    note = placeholder_note(result)
    if note:
        out["placeholders"] = [p["label"] for p in result["placeholders"]]
        without = (result.get("without_placeholders") or {}).get("reliability")
        if without is not None and result.get("reliability") is not None:
            out["mission_reliability_without_placeholders"] = without
        out["notes"].insert(0, note)
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
    if has_standby(phases):
        note = ("# The diagram's phased mission isn't exported: some of its blocks stand by in\n"
                "# some phases (their clocks stop there), which this script doesn't model.")
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

