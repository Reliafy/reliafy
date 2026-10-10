"""Undirected networks: two-terminal reliability (#160).

Pipelines, power grids and communication links are undirected: what matters
is whether two points (the terminals) stay connected by some path of working
elements, whichever way it runs. A reliability block diagram is directed, so a
network is a diagram mode of its own. The builder draws it on the same
canvas: a diagram with a ``"network"`` setting is read as a network::

    "network": {"source": "input", "target": "output"}

* each **block** is a network node that can fail, with its life model (a
  pipe segment or a line that can fail is drawn as a block between the
  points it joins);
* each **connection** is a link that works both ways and never fails itself
  (its direction on the canvas is ignored);
* the **terminals** are two of the diagram's nodes: Input and Output by
  default (they never fail), or any two blocks.

RePyability's ``Network`` works the connection's reliability out exactly from
a decision diagram built link by link (it grows with the network's width, not
its number of paths), with each element's Birnbaum importance; where that
diagram would be too large it is simulated, and the result says so. Vote
nodes, repeated blocks and common-cause groups have no meaning in such a
network and are refused in plain words, as is a repairable diagram.
"""

from __future__ import annotations

import warnings
from typing import Any, Callable, Optional

import numpy as np

from backend.services.rbd_analysis import AnalysisError

#: Simulated networks when the exact decision diagram is too large, and the
#: seed (the same figures every time for the same diagram).
SIM_NETWORKS = 20_000
SIM_SEED = 1
#: Points on the reliability curve.
GRID_POINTS = 120
#: The prefix of the links' names (each connection is a link of its own).
_LINK = "link~"

#: What every block-diagram analysis says of a network (they don't apply).
NETWORK_ONLY = ("This diagram is a network (undirected links between two terminals): its result is the chance "
                "its two terminals stay connected, which the builder's Calculator tab and analyze_rbd give. "
                "Block-diagram analyses don't apply to it.")


class NetworkError(ValueError):
    """A ``network`` setting that can't be read (user-facing text)."""


# ---------------------------------------------------------------------------
# The setting
# ---------------------------------------------------------------------------
def is_network(graph) -> bool:
    return isinstance(graph, dict) and isinstance(graph.get("network"), dict)


def parse_network(raw) -> dict:
    """``{"source", "target"}`` (Input and Output by default). Raises
    :class:`NetworkError`."""
    if raw is True:
        raw = {}
    if not isinstance(raw, dict):
        raise NetworkError("network must be an object {source, target} naming the two terminals.")
    out = {}
    for key, default in (("source", "input"), ("target", "output")):
        value = raw.get(key)
        if value is None or value == "":
            value = default
        if not isinstance(value, (str, int)) or isinstance(value, bool):
            raise NetworkError(f"network {key} must be a node id.")
        out[key] = str(value).strip() or default
    if out["source"] == out["target"]:
        raise NetworkError("the network's two terminals must be two different nodes.")
    return out


def carry(graph: dict, out: dict) -> None:
    """Copy a graph's network setting, cleaned, into ``out``. Raises
    :class:`backend.services.rbd_graph.GraphError`."""
    from backend.services.rbd_graph import GraphError

    raw = graph.get("network")
    if raw is None or raw is False:
        return
    if graph.get("repairable"):
        raise GraphError("a network is analysed for reliability, not availability: it can't be repairable.")
    try:
        out["network"] = parse_network(raw)
    except NetworkError as exc:
        raise GraphError(str(exc)) from None


def apply_set(graph: dict, op: dict) -> list[str]:
    """edit_rbd's ``set`` of ``network`` (true, {source, target}, or false):
    what was done, in words. Raises
    :class:`backend.services.rbd_graph.GraphError`."""
    from backend.services.rbd_graph import GraphError

    raw = op.get("network")
    if raw is None:
        return []
    if raw is False:
        if graph.pop("network", None) is None:
            return []
        return ["back to a block diagram (no longer a network)"]
    if graph.get("repairable"):
        raise GraphError("a network is analysed for reliability: set repairable false too.")
    try:
        spec = parse_network(raw)
    except NetworkError as exc:
        raise GraphError(str(exc)) from None
    ids = {str(n.get("id")) for n in graph.get("nodes") or [] if isinstance(n, dict)}
    for key in ("source", "target"):
        if spec[key] not in ids:
            raise GraphError(f"the network's terminal '{spec[key]}' isn't a node of the diagram.")
    graph["network"] = spec
    kept = " (its phases are kept but don't apply to a network)" if graph.get("phases") else ""
    return [f"read as an undirected network between {spec['source']} and {spec['target']}{kept}"]


def summary(graph: dict) -> str:
    """The network in one line (for the MCP tools' structure summary)."""
    spec = parse_network(graph.get("network") or {})
    labels = {n.get("id"): (n.get("data") or {}).get("label") or n.get("id")
              for n in graph.get("nodes") or [] if isinstance(n, dict)}
    blocks = sum(1 for n in graph.get("nodes") or [] if isinstance(n, dict)
                 and n.get("type") not in ("input", "output"))
    links = len(_links(graph))
    return (f"Network (undirected) between {labels.get(spec['source'], spec['source'])} and "
            f"{labels.get(spec['target'], spec['target'])}: {blocks} block{'s' if blocks != 1 else ''}, "
            f"{links} link{'s' if links != 1 else ''}.")


def _links(graph: dict) -> list[tuple[str, str]]:
    """The connections as undirected links, each pair once (a connection
    drawn both ways is one link)."""
    seen, out = set(), []
    for e in graph.get("edges") or []:
        if not isinstance(e, dict):
            continue
        a, b = e.get("source"), e.get("target")
        if a is None or b is None or a == b:
            continue
        key = frozenset((str(a), str(b)))
        if key in seen:
            continue
        seen.add(key)
        out.append((str(a), str(b)))
    return out


# ---------------------------------------------------------------------------
# The network
# ---------------------------------------------------------------------------
def build_network(
    graph: dict,
    resolve_subsystem: Optional[Callable[[str], dict]] = None,
    resolve_model=None,
    covariates: Optional[dict] = None,
):
    """``(Network, terminals, labels, models, notes)``: RePyability's network
    for the diagram, its terminals, each node's label and each block's model
    by id, and notes on what was left out. Raises :class:`AnalysisError` in plain words."""
    from repyability import Network
    from repyability.rbd.helper_classes import PerfectReliability, PerfectUnreliability

    from backend.services import rbd_analysis as ra
    from backend.services import rbd_repeats

    try:
        spec = parse_network(graph.get("network") or {})
    except NetworkError as exc:
        raise AnalysisError(f"The network's setting can't be read: {exc}") from None
    if graph.get("repairable"):
        raise AnalysisError("A network is analysed for reliability: make the diagram non-repairable.")
    ra._check_limits(graph)
    ccf = [g for g in graph.get("ccf_groups") or [] if isinstance(g, dict) and len(g.get("members") or []) >= 2]
    if ccf:
        raise AnalysisError("A network doesn't model common-cause groups. Remove the diagram's common-cause "
                            "groups to analyse it as a network.")
    nodes = [n for n in graph.get("nodes") or [] if isinstance(n, dict)]
    by_id = {str(n.get("id")): n for n in nodes}
    links = _links(graph)
    linked = {x for pair in links for x in pair}
    labels: dict[str, str] = {}
    models: dict[str, Any] = {}
    notes: list[str] = []
    unlinked: list[str] = []
    for node in nodes:
        nid = str(node.get("id"))
        ntype = node.get("type")
        data = node.get("data") or {}
        label = data.get("label") or ("Input" if ntype == "input" else "Output" if ntype == "output" else nid)
        labels[nid] = label
        if ntype in ("input", "output"):
            continue
        if ntype == "knode":
            raise AnalysisError(f"“{label}” is a vote node, which has no meaning in a network (any working path "
                                "joins the terminals). Remove it and connect its branches directly.")
        if rbd_repeats.repeat_of(node) is not None:
            raise AnalysisError(f"“{label}” is a repeated block, which a network can't hold: each block is one "
                                "place in the network. Remove the copy and connect the block itself.")
        if nid not in linked:
            unlinked.append(label)
            continue
        state = data.get("state")
        if state == "working":
            models[nid] = PerfectReliability
            continue
        if state == "failed":
            models[nid] = PerfectUnreliability
            continue
        model, _ = ra._node_reliability(node, resolve_subsystem, set(), resolve_model, covariates)
        models[nid] = model
    for key in ("source", "target"):
        nid = spec[key]
        if nid not in by_id:
            raise AnalysisError(f"The network's {'first' if key == 'source' else 'second'} terminal ('{nid}') isn't "
                                "in the diagram. Choose two of its nodes as the terminals.")
        if nid not in linked:
            raise AnalysisError(f"The terminal “{labels.get(nid, nid)}” isn't connected to anything yet. Connect "
                                "it into the network.")
    if not models and not links:
        raise AnalysisError("The network has no blocks yet. Add blocks and connect them between the terminals.")
    if unlinked:
        notes.append(f"Not connected to anything, so left out: {', '.join(unlinked)}.")
    link_models = {f"{_LINK}{i + 1}": (a, b, PerfectReliability) for i, (a, b) in enumerate(links)}
    try:
        network = Network(link_models, spec["source"], spec["target"], nodes=models)
    except ValueError as exc:
        raise AnalysisError(f"The network can't be built: {exc}") from None
    return network, spec, labels, models, notes


def _reachable(network, spec) -> bool:
    """Whether some path of links joins the terminals at all."""
    adjacent: dict = {}
    for a, b in network.links.values():
        adjacent.setdefault(a, set()).add(b)
        adjacent.setdefault(b, set()).add(a)
    seen, stack = {spec["source"]}, [spec["source"]]
    while stack:
        for nxt in adjacent.get(stack.pop(), ()):
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return spec["target"] in seen


def _clean(values) -> list:
    arr = np.asarray(values, dtype=float).ravel()
    return [float(v) if np.isfinite(v) else None for v in arr]


def analyze_network(
    graph: dict,
    t: Optional[float] = None,
    t_max: Optional[float] = None,
    at_times=None,
    resolve_subsystem: Optional[Callable[[str], dict]] = None,
    resolve_model=None,
    covariates: Optional[dict] = None,
) -> dict:
    """The terminals' connection reliability over time, at ``t`` (by
    default where it falls to about 90%, as the calculator reads
    importance), the mean time until they're parted, and each block's
    Birnbaum importance at ``t``. Exact by decision diagram; simulated where
    that is too large (the result says which)."""
    from backend.services import rbd_analysis as ra

    network, spec, labels, models, notes = build_network(graph, resolve_subsystem, resolve_model, covariates)
    if not _reachable(network, spec):
        raise AnalysisError(f"No path of connections joins “{labels.get(spec['source'])}” to "
                            f"“{labels.get(spec['target'])}” yet. Connect them through the blocks.")
    method = "exact"
    sim = {}

    def sf(x):
        if method == "exact":
            return np.asarray(network.sf(x), dtype=float)
        return np.asarray(network.sf(x, method="simulate", mc_samples=SIM_NETWORKS, seed=SIM_SEED), dtype=float)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        grid = ra._time_grid(models, t_max)
        try:
            if not (t_max is not None and np.isfinite(t_max) and t_max > 0) and models:
                grid_end = ra._system_horizon(network, float(grid[-1]))
            else:
                grid_end = float(grid[-1])
            grid = np.linspace(0.0, grid_end, GRID_POINTS)
            curve = sf(grid)
        except NotImplementedError:
            method = "simulated"
            sim = {"n_samples": SIM_NETWORKS}
            grid = np.linspace(0.0, float(grid[-1]), GRID_POINTS)
            curve = sf(grid)
        if t is None or not np.isfinite(t) or t < 0:
            i = int(np.argmin(np.abs(curve - 0.9)))
            if not 0.0 < curve[i] < 1.0:
                i = len(grid) // 2
            t_at = float(grid[i])
            t_given = False
        else:
            t_at = float(t)
            t_given = True
        r_at = float(np.atleast_1d(sf(np.array([t_at])))[0])
        mttf = None
        mttf_note = None
        if method == "exact":
            try:
                mean = float(network.mean())
                mttf = mean if np.isfinite(mean) else None
                if mttf is None:
                    mttf_note = ("The terminals never part in some networks (a block that never fails), so "
                                 "there's no mean time until they do.")
            except (ValueError, NotImplementedError, ArithmeticError) as exc:
                mttf_note = f"No mean time until the terminals part: {exc}"
        importance = []
        if method == "exact":
            try:
                measure = network.birnbaum_importance(t_at)
            except NotImplementedError:
                measure = {}
            for nid in models:
                value = float(np.atleast_1d(measure.get(nid, 0.0))[0])
                rel = float(np.atleast_1d(np.asarray(models[nid].sf(np.array([t_at])), dtype=float))[0])
                importance.append({"id": nid, "label": labels.get(nid, nid), "birnbaum": abs(value) + 0.0,
                                   "reliability": rel})
            importance.sort(key=lambda r: -r["birnbaum"])
        else:
            notes.append("The importance of each block needs the exact calculation, which is too large for this "
                         "network.")
        at = None
        if at_times is not None and len(at_times):
            at_t = np.asarray([float(v) for v in at_times], dtype=float)
            at = {"t": at_t.tolist(), "sf": _clean(sf(at_t))}
    if mttf_note:
        notes.append(mttf_note)
    out = {
        "unit": (graph.get("unit") or "").strip(),
        "method": method,
        "source": {"id": spec["source"], "label": labels.get(spec["source"], spec["source"])},
        "target": {"id": spec["target"], "label": labels.get(spec["target"], spec["target"])},
        "t": t_at,
        "t_given": t_given,
        "reliability": r_at,
        "unreliability": 1.0 - r_at,
        "mttf": mttf,
        "curve": {"t": _clean(grid), "sf": _clean(curve)},
        "importance": importance,
        "n_blocks": len(models),
        "n_links": len(network.links),
        "notes": notes,
    }
    if at is not None:
        out["at"] = at
    if sim:
        out["simulation"] = sim
        out["method_reason"] = (f"The network is too large to work out exactly, so it was simulated "
                                f"({SIM_NETWORKS:,} networks).")
    return out


def analyze_for_owner(db, graph: dict, owner_id, t=None, t_max=None, at_times=None,
                      covariates: Optional[dict] = None) -> dict:
    """:func:`analyze_network` with sub-systems and saved models resolved in
    the caller's scope, exactly as ``rbds.analyze_graph`` resolves them."""
    from backend.services import models as models_service
    from backend.services import rbds as rbds_service

    def resolve_subsystem(sub_id: str) -> dict | None:
        sub = rbds_service.get_rbd(db, sub_id, owner_id)
        return sub.graph if sub is not None else None

    def resolve_model(model_id: str) -> dict | None:
        return models_service.get_live_model(db, model_id, owner_id)

    return analyze_network(graph, t=t, t_max=t_max, at_times=at_times, resolve_subsystem=resolve_subsystem,
                           resolve_model=resolve_model, covariates=covariates)


def validate(graph: dict, resolve_subsystem: Optional[Callable[[str], dict]] = None) -> dict:
    """The builder's check for a network, in ``validate_graph``'s shape."""
    errors: list[str] = []
    warnings_: list[str] = []
    blocks = [n for n in graph.get("nodes") or [] if isinstance(n, dict) and n.get("type") not in ("input", "output")]
    if not blocks:
        return {"valid": False, "analytic": False, "can_calculate": False, "network": True,
                "errors": ["The network has no blocks yet. Add blocks and connect them between the terminals."],
                "warnings": [], "non_analytic_nodes": {}, "empty": "no_blocks"}
    try:
        network, spec, labels, _, notes = build_network(graph, resolve_subsystem)
        warnings_.extend(notes)
        if not _reachable(network, spec):
            errors.append(f"No path of connections joins “{labels.get(spec['source'])}” to "
                          f"“{labels.get(spec['target'])}” yet. Connect them through the blocks.")
    except AnalysisError as exc:
        errors.append(str(exc))
    valid = not errors
    return {"valid": valid, "analytic": valid, "can_calculate": valid, "network": True,
            "errors": errors, "warnings": warnings_, "non_analytic_nodes": {}}


def agent_summary(result: dict) -> dict:
    """The network result for the MCP tools, compactly: the curve thinned to
    about 21 points."""
    curve = result.get("curve") or {}
    ts, sfs = curve.get("t") or [], curve.get("sf") or []
    step = max(1, len(ts) // 20)
    out: dict[str, Any] = {
        "kind": "network",
        "method": result["method"],
        "terminals": [result["source"]["label"], result["target"]["label"]],
        "time": result["t"],
        "reliability": result["reliability"],
        "mean_time_to_disconnect": result.get("mttf"),
        "importance": [{"id": r["id"], "label": r["label"], "birnbaum": r["birnbaum"]}
                       for r in result.get("importance") or []],
        "curve": [{"t": ts[i], "reliability": sfs[i]} for i in range(0, len(ts), step)],
        "notes": list(result.get("notes") or []),
    }
    if result.get("at"):
        out["reliability_at"] = [{"t": t, "reliability": r} for t, r in zip(result["at"]["t"], result["at"]["sf"])]
    if result.get("method_reason"):
        out["notes"].insert(0, result["method_reason"])
    return out


# ---------------------------------------------------------------------------
# Download as Python
# ---------------------------------------------------------------------------
PYTHON_WHAT = ("the same network calculation as Reliafy: the chance that its two terminals stay connected, "
               "R(t), the mean time until they part, and each block's Birnbaum importance.")

_NETWORK_MAIN = '''
def system_horizon(model, ceiling):
    """Where the time axis ends, exactly as Reliafy sizes it: about 15% past
    the time the connection's reliability first reaches 1%, searched on a
    log grid up to ``ceiling`` (falling back to the ceiling)."""
    probe = np.geomspace(ceiling * 1e-6, ceiling, 400)
    sf = np.asarray(model.sf(probe), dtype=float)
    if not np.all(np.isfinite(sf)) or sf[0] < 0.01:
        return ceiling
    below = np.nonzero(sf <= 0.01)[0]
    if below.size == 0:
        return ceiling
    return float(min(ceiling, probe[below[0]] * 1.15))


def save_results(results):
    """Write the numbers to $RELIAFY_RESULTS_JSON, when it is set."""
    path = os.environ.get("RELIAFY_RESULTS_JSON")
    if path:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(results, fh, indent=2)


def main():
    unit = f" {UNIT_TEXT}" if UNIT_TEXT else ""
    # Exact by decision diagram; simulated where that is too large, as in
    # Reliafy.
    try:
        t_max = system_horizon(network, T_MAX_CEILING)
        times = np.linspace(0.0, t_max, GRID_POINTS)
        sf = np.asarray(network.sf(times), dtype=float)
        exact = True
    except NotImplementedError:
        times = np.linspace(0.0, T_MAX_CEILING, GRID_POINTS)
        sf = np.asarray(network.sf(times, method="simulate",
                                   mc_samples=SIM_NETWORKS, seed=SIM_SEED))
        exact = False

    # Read out where the connection's reliability is closest to 0.9 (else
    # the middle of the time axis), as Reliafy's calculator does.
    i = int(np.argmin(np.abs(sf - 0.9)))
    if not 0.0 < sf[i] < 1.0:
        i = GRID_POINTS // 2
    t_rep = float(times[i])
    if exact:
        reliability = float(network.sf(t_rep))
    else:
        reliability = float(network.sf(t_rep, method="simulate",
                                       mc_samples=SIM_NETWORKS,
                                       seed=SIM_SEED)[0])
    print(f"{LABELS[SOURCE]} to {LABELS[TARGET]}: "
          f"{'exact' if exact else 'simulated'}")
    print(f"  R({t_rep:,.6g}{unit}) = {reliability:.6f}")

    mean = None
    importance = {}
    if exact:
        try:
            mean = float(network.mean())
            print(f"Mean time until they part: {mean:,.6g}{unit}")
        except ValueError as exc:
            print(f"No mean time until they part: {exc}")
        measure = network.birnbaum_importance(t_rep)
        print(f"\\nBirnbaum importance at t = {t_rep:,.6g}{unit}")
        for node in sorted(NODES, key=lambda n: -abs(float(measure[n]))):
            importance[node] = abs(float(measure[node]))
            print(f"  {LABELS[node][:28]:<28} {importance[node]:>12.4g}")

    results = {
        "unit": UNIT,
        "exact": exact,
        "time": t_rep,
        "reliability": reliability,
        "mean": mean,
        "importance": importance,
        "curve": {"t": times.tolist(), "sf": sf.tolist()},
    }
    save_results(results)

    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("(Install matplotlib to plot the reliability curve.)")
    else:
        fig, ax = plt.subplots()
        ax.plot(times, sf)
        ax.set_xlabel(f"Time ({UNIT})" if UNIT else "Time")
        ax.set_ylabel("P(terminals connected)")
        ax.set_ylim(0.0, 1.02)
        ax.grid(True, alpha=0.3)
        plt.show()
    return results


if __name__ == "__main__":
    main()
'''


def python_body(script, graph: dict, resolve_model, resolve_subsystem) -> str:
    """The "Download as Python" body for a network: its blocks (written as
    for a block diagram), its undirected links and terminals, and a ``main``
    that works out what the app shows."""
    from backend.services import rbd_repeats
    from backend.services.rbd_export import _default_t_max, _lit, _num, _seeded
    from backend.units import unit_in_text

    try:
        spec = parse_network(graph.get("network") or {})
    except NetworkError:
        spec = {"source": "input", "target": "output"}
    links = _links(graph)
    linked = {x for pair in links for x in pair}
    nodes = [n for n in graph.get("nodes") or [] if isinstance(n, dict)]
    labels = {str(n.get("id")): (n.get("data") or {}).get("label")
              or ("Input" if n.get("type") == "input" else "Output" if n.get("type") == "output" else n.get("id"))
              for n in nodes}
    L = script.lines
    L.append("# " + "-" * 75)
    L.append("# Blocks: the network's nodes that can fail, one life model each, built")
    L.append("# exactly as Reliafy builds them.")
    L.append("# " + "-" * 75)
    rel, working, broken, problems = [], [], [], []
    for node in nodes:
        nid = str(node.get("id"))
        ntype = node.get("type")
        if ntype in ("input", "output") or nid not in linked:
            continue
        label = labels[nid]
        if ntype == "knode":
            problems.append(f"'{label}' is a vote node, which has no meaning in a network.")
            continue
        if rbd_repeats.repeat_of(node) is not None:
            problems.append(f"'{label}' is a repeated block, which a network can't hold.")
            continue
        expr, _ = script.block(node, frozenset())
        rel.append((nid, expr))
        state = (node.get("data") or {}).get("state")
        if state == "working":
            working.append(nid)
        elif state == "failed":
            broken.append(nid)
    ccf = [g for g in graph.get("ccf_groups") or [] if isinstance(g, dict) and len(g.get("members") or []) >= 2]
    if ccf:
        problems.append("A network doesn't model common-cause groups.")
    script.imports.update({"Network", "PerfectReliability"})
    if broken:
        script.imports.add("PerfectUnreliability")
    ceiling_graph = {**graph, "nodes": [n for n in nodes if str(n.get("id")) in dict(rel)]}
    t_max = _seeded(_default_t_max, ceiling_graph, resolve_model, resolve_subsystem)
    t_max = float(t_max) if t_max and np.isfinite(t_max) and t_max > 0 else 1.0

    out = list(L)
    out += ["", "", "# " + "-" * 75, "# The network", "# " + "-" * 75]
    out.append("# Each block's life model (blocks with no connection are left out).")
    out.append("NODES = {")
    out += [f"    {_lit(nid)}: {expr}," for nid, expr in rel]
    out.append("}")
    out.append("")
    out.append("# What-if overrides: blocks pinned working (perfectly reliable) or failed in")
    out.append("# Reliafy stand in as such.")
    for nid in working:
        out.append(f"NODES[{_lit(nid)}] = PerfectReliability")
    for nid in broken:
        out.append(f"NODES[{_lit(nid)}] = PerfectUnreliability")
    out.append("")
    out.append("LABELS = {")
    out += [f"    {_lit(nid)}: {_lit(label)}," for nid, label in labels.items()
            if nid in linked]
    out.append("}")
    out.append("")
    out.append("# The connections, as undirected links that never fail themselves (the")
    out.append("# direction they were drawn in is ignored). Input and Output, when they're")
    out.append("# in the network, are points that never fail.")
    out.append("LINKS = {")
    out += [f"    {_lit(_LINK + str(i + 1))}: ({_lit(a)}, {_lit(b)}, PerfectReliability),"
            for i, (a, b) in enumerate(links)]
    out.append("}")
    out.append(f"SOURCE = {_lit(spec['source'])}")
    out.append(f"TARGET = {_lit(spec['target'])}")
    out.append("")
    if problems:
        out.append("# This diagram can't be analysed as a network (Reliafy refuses it too):")
        out.append(f"raise SystemExit({_lit(' '.join(problems))})")
        out.append("")
    out.append("network = Network(LINKS, SOURCE, TARGET, nodes=NODES)")
    out += ["", "", "# " + "-" * 75, "# The calculation", "# " + "-" * 75]
    out.append(f"UNIT = {_lit(script.unit)}")
    out.append(f"UNIT_TEXT = {_lit(unit_in_text(script.unit))}  # the unit in sentences")
    out.append("# Upper bound for the time axis: the longest-lived block's 99th-percentile")
    out.append("# life; the axis ends where the connection's reliability reaches 1%.")
    out.append(f"T_MAX_CEILING = {_num(t_max)}")
    out.append(f"GRID_POINTS = {GRID_POINTS}")
    out.append(f"SIM_NETWORKS = {SIM_NETWORKS:_}")
    out.append(f"SIM_SEED = {SIM_SEED}")
    out.append("")
    out.append("")
    out.append(_NETWORK_MAIN.strip("\n"))
    return "\n".join(out)


# ---------------------------------------------------------------------------
# RePyability JSON
# ---------------------------------------------------------------------------
#: The document type of a network (RePyability 0.13 has no JSON form for its
#: ``Network``: this one mirrors its constructor).
JSON_TYPE = "Network"


def json_core(exporter, graph: dict) -> dict:
    """A network as a document: its links, terminals and each block's
    serialised model (``repyability.rbd.serialisation.deserialise_model``
    reads one back), mirroring ``Network(links, source, target, nodes)``.
    ``exporter`` is :class:`backend.services.rbd_json._Exporter`; blocks it
    can't write are collected in its ``problems``."""
    from backend.services import rbd_json, rbd_repeats
    from backend.services import rbd_analysis as ra

    ra._check_limits(graph)
    try:
        spec = parse_network(graph.get("network") or {})
    except NetworkError as exc:
        raise rbd_json.ExportError(f"The network's setting can't be read: {exc}") from None
    if [g for g in graph.get("ccf_groups") or [] if isinstance(g, dict) and len(g.get("members") or []) >= 2]:
        raise rbd_json.ExportError("A network doesn't model common-cause groups: remove them to export it.")
    links = _links(graph)
    linked = {x for pair in links for x in pair}
    nodes = []
    for node in graph.get("nodes") or []:
        nid = str(node.get("id"))
        ntype = node.get("type")
        if ntype in ("input", "output") or nid not in linked:
            continue
        label = (node.get("data") or {}).get("label") or nid
        if ntype == "knode" or rbd_repeats.repeat_of(node) is not None:
            exporter.problems.append(f"“{label}” is a vote node or a repeated block, which a network can't hold")
            continue
        state = (node.get("data") or {}).get("state")
        if state in ("working", "failed"):
            model = {"kind": "perfect_reliability" if state == "working" else "perfect_unreliability"}
        else:
            try:
                model, _ = exporter.block(node, frozenset())
            except rbd_json._Missing as exc:
                exporter.problems.append(str(exc))
                continue
        nodes.append({"node": nid, "model": model})
    return {
        "repyability_version": rbd_json._repyability_version(),
        "type": JSON_TYPE,
        "links": [{"link": f"{_LINK}{i + 1}", "nodes": [a, b], "model": {"kind": "perfect_reliability"}}
                  for i, (a, b) in enumerate(links)],
        "source": spec["source"],
        "target": spec["target"],
        "nodes": nodes,
    }


def import_document(doc: dict, stem: str):
    """A network file Reliafy wrote, back as its diagram (the ``"reliafy"``
    part's graph, when the network part is still what Reliafy writes for
    it). Raises :class:`RbdImportError` otherwise: no other tool writes this
    form."""
    from backend.services import rbd_json
    from backend.services.rbd_import.repyability import _Saved
    from backend.services.rbd_import.types import RbdImportError

    ext = doc.get(rbd_json.EXTENSION_KEY)
    core = {k: v for k, v in doc.items() if k != rbd_json.EXTENSION_KEY}
    if isinstance(ext, dict) and ext.get("format") == rbd_json.FORMAT:
        saved = _Saved.read(ext)
        if saved is not None and is_network(saved.graph) and saved.matches(core):
            return [saved.diagram(stem)]
    raise RbdImportError("This network file was changed after Reliafy wrote it (or wasn't written by Reliafy), "
                         "so it can't be read back: Reliafy reads a network file as it wrote it.")
