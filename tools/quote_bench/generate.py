"""Random repairable RBDs for the runtime experiment (#286).

Each design draws a set of *factors* (size, architecture, life and repair
models, maintenance, crews, common cause, horizon, replications) and builds
the diagram in the persisted builder shape that ``compute_core`` runs. The
factors and the features a quote could see before running are kept beside
the graph so the timings can be modelled on them.

Architecture: a chain of *stages* between input and output. A stage is a
single block (a component, an n-unit parallel block, or a standby block) or a
group of 2–4 parallel branches of 1–3 blocks each, optionally voted k-of-n by
a vote node, optionally meshed by a bridge edge between two branches.
Consecutive stages are fully connected, which is exactly their series
composition. (Repeated blocks are refused in repairable diagrams, so none.)
"""

from __future__ import annotations

import json
import math

import numpy as np

#: Median block MTBF; horizons are drawn relative to it.
MTBF = 1000.0


def _exp(rate):
    return {"source": "params", "distribution": "Exponential", "distribution_id": "exponential",
            "params": [{"name": "failure_rate", "value": rate}]}


def _weibull(alpha, beta):
    return {"source": "params", "distribution": "Weibull", "distribution_id": "weibull",
            "params": [{"name": "alpha", "value": alpha}, {"name": "beta", "value": beta}]}


def _lognormal(mu, sigma):
    return {"source": "params", "distribution": "Lognormal", "distribution_id": "lognormal",
            "params": [{"name": "mu", "value": mu}, {"name": "sigma", "value": sigma}]}


def _loguniform(rng, lo, hi):
    return float(math.exp(rng.uniform(math.log(lo), math.log(hi))))


def draw_factors(rng: np.random.Generator) -> dict:
    """One design point: every factor of the experiment."""
    return {
        "n_stages": int(round(_loguniform(rng, 1, 80))),
        "p_parallel": float(rng.uniform(0, 0.8)),
        "max_branches": int(rng.integers(2, 5)),
        "max_branch_len": int(rng.integers(1, 4)),
        "p_vote": float(rng.uniform(0, 0.6)),
        "p_bridge": float(rng.choice([0.0, 0.0, rng.uniform(0, 0.6)])),
        "p_units": 0.0,                                      # n-unit blocks are refused in repairable diagrams
        "p_standby": float(rng.uniform(0, 0.3)),
        "n_repeats": 0,                                      # repairable diagrams refuse repeats
        "mtbf_spread": _loguniform(rng, 1.0, 30.0),           # blocks' MTBFs span ×/÷ this
        "horizon_ratio": _loguniform(rng, 0.05, 100.0),       # horizon / median MTBF
        "p_nonexp_life": float(rng.choice([0.0, rng.uniform(0, 1)])),
        "mttr": _loguniform(rng, 0.5, 200.0),
        "p_nonexp_repair": float(rng.uniform(0, 1)),
        "p_instant_repair": float(rng.choice([0.0, rng.uniform(0, 0.3)])),
        "crews": int(rng.choice([0, 0, 0, 1, 2, 3])),        # 0: unlimited
        "n_ccf": int(rng.choice([0, 0, 1, 2])),
        "p_preventive": float(rng.choice([0.0, rng.uniform(0, 0.5)])),
        "p_inspection": float(rng.choice([0.0, rng.uniform(0, 0.3)])),
        "costs": bool(rng.random() < 0.5),
        "n_simulations": 2 * int(round(_loguniform(rng, 50, 25_000))),
        "seed": int(rng.integers(0, 2**31)),
    }


class _Builder:
    def __init__(self, f: dict, rng: np.random.Generator):
        self.f, self.rng = f, rng
        self.nodes: list[dict] = [
            {"id": "input", "type": "input", "position": {"x": 0, "y": 0}, "data": {"label": "Input"}},
            {"id": "output", "type": "output", "position": {"x": 0, "y": 0}, "data": {"label": "Output"}},
        ]
        self.edges: list[tuple[str, str]] = []
        self.components: list[str] = []   # plain components (repeatable, CCF-able)
        self.mtbfs: dict[str, float] = {}  # per node, per unit
        self.units: dict[str, int] = {}
        self.parallel_firsts: list[list[str]] = []  # first blocks of a group's branches
        self.n = 0
        self.n_bridges = 0

    def _id(self, prefix):
        self.n += 1
        return f"{prefix}{self.n}"

    def _life(self, mtbf):
        r = self.rng
        if r.random() >= self.f["p_nonexp_life"]:
            return _exp(1.0 / mtbf)
        if r.random() < 0.5:
            beta = r.uniform(0.7, 3.5)
            return _weibull(mtbf / math.gamma(1 + 1 / beta), beta)
        sigma = r.uniform(0.3, 1.2)
        return _lognormal(math.log(mtbf) - sigma**2 / 2, sigma)

    def _repair(self):
        r, mttr = self.rng, self.f["mttr"] * _loguniform(self.rng, 0.3, 3.0)
        if r.random() < self.f["p_nonexp_repair"]:
            sigma = r.uniform(0.2, 1.0)
            return _lognormal(math.log(mttr) - sigma**2 / 2, sigma)
        return _exp(1.0 / mttr)

    def _data(self, label, standby=False):
        f, r = self.f, self.rng
        mtbf = MTBF * _loguniform(r, 1 / f["mtbf_spread"], f["mtbf_spread"])
        data = {"label": label, "model": self._life(mtbf)}
        if not standby and r.random() < f["p_instant_repair"]:
            data["instant_repair"] = True
        else:
            data["repair"] = self._repair()
        if standby:
            pass                       # a standby group takes no tests or replacements
        elif r.random() < f["p_preventive"]:
            data["preventive"] = {"policy": "age", "interval": round(mtbf * r.uniform(0.3, 1.0), 1),
                                  "duration": round(r.uniform(0, 8), 2)}
        elif r.random() < f["p_inspection"]:
            data["inspection"] = {"interval": round(mtbf * r.uniform(0.2, 2.0), 1), "duration": 0}
        if f["costs"]:
            data["costs"] = {"repair": 500, "replace": 5000}
        return data, mtbf

    def block(self, kind="component"):
        nid = self._id("b")
        data, mtbf = self._data(nid, standby=kind == "standby")
        units = 1
        if kind == "units":
            units = int(self.rng.integers(2, 5))
            data["n"] = units
            ntype = "parallel"
        elif kind == "standby":
            units = 1 + int(self.rng.integers(1, 3))
            data.update(spares=units - 1, dormancy=float(self.rng.choice([0.0, 0.3, 1.0])))
            ntype = "standby"
        else:
            ntype = "component"
            self.components.append(nid)
        self.nodes.append({"id": nid, "type": ntype, "position": {"x": 0, "y": 0}, "data": data})
        self.mtbfs[nid], self.units[nid] = mtbf, units
        return nid

    def stage(self, prev: list[str]) -> list[str]:
        f, r = self.f, self.rng
        if r.random() >= f["p_parallel"]:
            u = r.random()
            kind = "units" if u < f["p_units"] else "standby" if u < f["p_units"] + f["p_standby"] else "component"
            nid = self.block(kind)
            self.edges += [(p, nid) for p in prev]
            return [nid]
        n_br = int(r.integers(2, f["max_branches"] + 1))
        branches = []
        for _ in range(n_br):
            chain = [self.block() for _ in range(int(r.integers(1, f["max_branch_len"] + 1)))]
            self.edges += [(p, chain[0]) for p in prev]
            self.edges += list(zip(chain, chain[1:]))
            branches.append(chain)
        self.parallel_firsts.append([b[0] for b in branches])
        long = [b for b in branches if len(b) >= 2]
        if len(long) >= 2 and r.random() < f["p_bridge"]:
            self.edges.append((long[0][0], long[1][1]))   # a bridge: meshed, not series-parallel
            self.n_bridges += 1
        ends = [b[-1] for b in branches]
        if n_br >= 3 and r.random() < f["p_vote"]:
            vote = self._id("v")
            need = int(r.integers(2, n_br))
            self.nodes.append({"id": vote, "type": "knode", "position": {"x": 0, "y": 0},
                               "data": {"label": f"{need}oo{n_br}", "n": need, "k": n_br}})
            self.edges += [(e, vote) for e in ends]
            return [vote]
        return ends

    def build(self) -> dict:
        f, r = self.f, self.rng
        prev = ["input"]
        for _ in range(f["n_stages"]):
            prev = self.stage(prev)
        # Repeated components: the same component again, in series, later on.
        for _ in range(min(f["n_repeats"], len(self.components))):
            of = self.components[int(r.integers(len(self.components)))]
            nid = self._id("r")
            self.nodes.append({"id": nid, "type": "component", "position": {"x": 0, "y": 0},
                               "data": {"label": nid, "repeat_of": of}})
            self.edges += [(p, nid) for p in prev]
            prev = [nid]
        self.edges += [(p, "output") for p in prev]
        graph = {
            "repairable": True, "unit": "hours", "nodes": self.nodes,
            "edges": [{"id": f"e{i}", "source": a, "target": b} for i, (a, b) in enumerate(self.edges)],
        }
        groups = [g for g in self.parallel_firsts if len(g) >= 2][: f["n_ccf"]]
        if groups:
            # A group's members are identical components: the first one's
            # models and maintenance, copied.
            by_id = {n["id"]: n for n in self.nodes}
            for g in groups:
                first = by_id[g[0]]["data"]
                for m in g[1:]:
                    by_id[m]["data"] = {**json.loads(json.dumps(first)), "label": m}
                    self.mtbfs[m] = self.mtbfs[g[0]]
            graph["ccf_groups"] = [{"id": f"ccf-{i}", "members": g, "beta": round(float(r.uniform(0.02, 0.2)), 3)}
                                   for i, g in enumerate(groups)]
        if f["crews"]:
            graph["repair_crews"] = {"crews": f["crews"]}
        if f["costs"]:
            graph["costs"] = {"downtime_rate": 100, "horizon": round(MTBF * f["horizon_ratio"], 1)}
        return graph

    def features(self, graph: dict) -> dict:
        """What a quote can see without running anything."""
        f = self.f
        horizon = MTBF * f["horizon_ratio"]
        types = [n["type"] for n in graph["nodes"]]
        data = [n["data"] for n in graph["nodes"]]
        blocks = [n for n in graph["nodes"] if n["type"] in ("component", "parallel", "standby")
                  and not n["data"].get("repeat_of")]
        nonexp = sum(1 for n in blocks if n["data"]["model"]["distribution_id"] != "exponential")
        out_deg: dict[str, int] = {}
        for e in graph["edges"]:
            out_deg[e["source"]] = out_deg.get(e["source"], 0) + 1
        return {
            "n_blocks": len(blocks),
            "n_units": sum(self.units.values()),
            "n_edges": len(graph["edges"]),
            "n_branch_points": sum(1 for d in out_deg.values() if d > 1),
            "n_vote": types.count("knode"),
            "n_standby": types.count("standby"),
            "n_unit_blocks": types.count("parallel"),
            "n_repeats": sum(1 for d in data if d.get("repeat_of")),
            "n_ccf_groups": len(graph.get("ccf_groups") or []),
            "n_bridges": self.n_bridges,
            "crews": f["crews"],
            "frac_nonexp_life": nonexp / max(len(blocks), 1),
            "n_preventive": sum(1 for d in data if d.get("preventive")),
            "n_inspection": sum(1 for d in data if d.get("inspection")),
            "n_instant": sum(1 for d in data if d.get("instant_repair")),
            "costs": int(f["costs"]),
            "horizon": horizon,
            # Expected failures of one replication, all units together.
            "events_per_rep": sum(self.units[n] * horizon / m for n, m in self.mtbfs.items()),
            "n_simulations": f["n_simulations"],
        }


def design(index: int, master_seed: int = 2026) -> dict:
    """Design point ``index``: factors, graph, features and run options."""
    rng = np.random.default_rng([master_seed, index])
    f = draw_factors(rng)
    b = _Builder(f, rng)
    graph = b.build()
    feats = b.features(graph)
    options = {"n_simulations": f["n_simulations"], "t_simulation": feats["horizon"], "seed": f["seed"]}
    return {"index": index, "factors": f, "features": feats, "graph": graph, "options": options}
