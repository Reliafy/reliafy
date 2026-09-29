"""Availability simulation split into seeded blocks, for Cloud Run Jobs.

A spec is ``{"graph": <compact RBD graph>, "t_simulation": T, "N": replications,
"seed": int}``. It's split exactly as RePyability's own ``n_jobs`` path does:
``N`` into blocks of ``PARALLEL_BLOCK`` replications, the blocks seeded in
turn from ``SeedSequence(seed)``. Task ``i`` of ``K`` runs a contiguous share
of the blocks; merging every block's tally in block order reproduces
``rbd.availability(T, N, seed=seed, method="c", n_jobs=1)`` exactly.
"""

from __future__ import annotations

import hashlib
import json

import numpy as np
from repyability.rbd.repairable_rbd import _Tally

import blocks as blk
from backend.services.rbd_analysis import _build_repairable_rbd

METHOD = blk.METHOD


def build(spec: dict):
    """(rbd, working_nodes, broken_nodes) for a spec's graph (inline params only)."""
    rbd, _labels, _gates, working, broken = _build_repairable_rbd(spec["graph"], None)
    return rbd, set(working or ()), set(broken or ())


def plan_blocks(spec: dict) -> list[tuple[int, int]]:
    return blk.plan_blocks(spec["N"], spec["seed"])


share = blk.share


def iter_blocks(spec: dict, indices):
    yield from blk.iter_blocks(build(spec), spec["t_simulation"], plan_blocks(spec), indices)


def run_blocks(spec: dict, indices) -> list[tuple[int, _Tally]]:
    return list(iter_blocks(spec, indices))


def merge(rbd, tallies: list[_Tally]) -> _Tally:
    total = _Tally(rbd.costs)
    for t in tallies:
        total.merge(t)
    return total


def result(spec: dict, tally: _Tally):
    """The AvailabilityResult of a merged tally (as ``availability`` builds it)."""
    rbd, working, broken = build(spec)
    initial_status = {c: c not in broken for c in rbd.components}
    initial_up = bool(rbd.is_system_working(initial_status, METHOD))
    return rbd._availability_result(tally, float(spec["t_simulation"]), initial_up, False)


def reference(spec: dict):
    """The single-machine run the distributed one must match."""
    rbd, working, broken = build(spec)
    return rbd.availability(t_simulation=float(spec["t_simulation"]), N=spec["N"], seed=spec["seed"],
                            method=METHOD, working_nodes=working, broken_nodes=broken, n_jobs=1)


def summary(res) -> dict:
    """Headline numbers plus a fingerprint of the full curve, for exact comparison."""
    timeline = np.asarray(res.timeline, dtype=float)
    avail = np.asarray(res.availability, dtype=float)
    digest = hashlib.sha256(timeline.tobytes() + avail.tobytes()
                            + np.asarray(res.uptimes, dtype=float).tobytes()).hexdigest()[:16]
    T = float(res.time_simulated_to)
    return {
        "n": int(res.n_simulations),
        "mean_availability": float(np.mean(res.uptimes)) / T if T else None,
        "system_failures": int(res.system_failures),
        "system_uptime": float(res.system_uptime),
        "curve_points": int(timeline.size),
        "fingerprint": digest,
    }


def load(path: str) -> dict:
    with open(path) as f:
        return json.load(f)
