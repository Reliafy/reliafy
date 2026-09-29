"""The block plan and runner the worker needs, with no Reliafy imports.

The RBD arrives already built (pickled by the launcher, from the app's own
graph builder in ``sim.build``), so a task only imports RePyability.
"""

from __future__ import annotations

import numpy as np
from repyability.rbd import _montecarlo as montecarlo
from repyability.rbd.repairable_rbd import PARALLEL_BLOCK, _simulate_block

METHOD = "c"  # cut sets, as the app's analyze_availability uses


def plan_blocks(N: int, seed: int) -> list[tuple[int, int]]:
    """Every block as (size, seed), in order, exactly as _run_parallel makes them."""
    seeds = np.random.SeedSequence(seed)
    return [(size, montecarlo.block_seed(seeds)) for size in montecarlo.blocks(N, PARALLEL_BLOCK)]


def share(n_blocks: int, index: int, count: int) -> range:
    """Task ``index`` of ``count``'s contiguous block indices."""
    return range(n_blocks * index // count, n_blocks * (index + 1) // count)


def iter_blocks(built, t_simulation: float, blocks, indices):
    """(index, tally) for each block, one at a time (a block's trace is big:
    a caller that summarises and drops it keeps memory flat)."""
    rbd, working, broken = built
    for i in indices:
        size, seed = blocks[i]
        yield i, _simulate_block((rbd, float(t_simulation), working, broken, METHOD, size, seed, False))
