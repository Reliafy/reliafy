"""One Cloud Run Jobs task: run this task's share of an experiment's blocks.

Env: ``BUCKET``, ``RUN_ID``, ``MODE`` (``blocks`` | ``grid``), and Cloud Run's
``CLOUD_RUN_TASK_INDEX`` / ``CLOUD_RUN_TASK_COUNT``. Reads ``spec.json`` and
the launcher's pickled RBD (``rbd.pkl``) from ``gs://BUCKET/runs/RUN_ID/``
and writes ``task-NNNNN.json`` beside them.

- ``blocks``: every block's full tally, for the exact comparison with a
  single-machine run (use modest N: a block's trace is ~0.5 MB).
- ``grid``: the task's blocks summarised as they finish, the availability
  trace snapped onto ``GRID`` equal cells over [0, T] (integer counts, so
  tasks still add exactly), plus each replication's uptime. For scale.

Imports are timed one by one (``imports`` in the output): start-up is most of
a small job's cost.
"""

import time

PROCESS_START = time.time()
_marks = {}


def _mark(name):
    _marks[name] = time.time()


import json  # noqa: E402
import os  # noqa: E402
import pickle  # noqa: E402

import gcs  # noqa: E402  (standard library only)

_mark("stdlib")
import numpy as np  # noqa: E402

_mark("numpy")
import blocks as blk  # noqa: E402  (repyability, surpyval, scipy, pandas)

_mark("repyability")
import tally_io  # noqa: E402

_mark("ready")

GRID = 2000


def gridded(tally, t_simulation: float) -> np.ndarray:
    """The tally's net-change-in-working counts, summed per grid cell."""
    times = np.fromiter(tally.changes.keys(), dtype=float, count=len(tally.changes))
    deltas = np.fromiter(tally.changes.values(), dtype=np.int64, count=len(tally.changes))
    edges = np.linspace(0.0, t_simulation, GRID + 1)
    cells = np.clip(np.searchsorted(edges, times, side="right") - 1, 0, GRID - 1)
    return np.bincount(cells, weights=deltas, minlength=GRID).astype(np.int64)


def main() -> None:
    index = int(os.environ.get("CLOUD_RUN_TASK_INDEX", "0"))
    count = int(os.environ.get("CLOUD_RUN_TASK_COUNT", "1"))
    run_id, mode = os.environ["RUN_ID"], os.environ.get("MODE", "grid")
    t0 = time.time()
    bucket = gcs.Bucket(os.environ["BUCKET"])
    spec = json.loads(bucket.get(f"runs/{run_id}/spec.json"))
    built = pickle.loads(bucket.get(f"runs/{run_id}/rbd.pkl"))
    loaded = time.time()

    T = float(spec["t_simulation"])
    plan = blk.plan_blocks(spec["N"], spec["seed"])
    indices = blk.share(len(plan), index, count)
    payload = {"task": index, "count": count, "mode": mode,
               "replications": sum(plan[i][0] for i in indices)}
    wall0, cpu0 = time.perf_counter(), time.process_time()
    if mode == "blocks":
        payload["blocks"] = [[i, tally_io.to_dict(t)] for i, t in blk.iter_blocks(built, T, plan, indices)]
    else:
        # Summarise each block as it finishes and drop its trace.
        deltas, uptimes = np.zeros(GRID, dtype=np.int64), []
        n = failures = 0
        uptime = 0.0
        for _, t in blk.iter_blocks(built, T, plan, indices):
            deltas += gridded(t, T)
            uptimes.extend(t.uptimes)
            n, failures, uptime = n + t.n, failures + t.system_failures, uptime + t.system_uptime
        payload["summary"] = {"n": n, "system_uptime": uptime, "system_failures": failures,
                              "uptimes": uptimes, "grid": GRID, "t_simulation": T,
                              "deltas": deltas.tolist()}
    compute_s, cpu_s = time.perf_counter() - wall0, time.process_time() - cpu0

    prev, imports = PROCESS_START, {}
    for name, when in _marks.items():
        imports[name] = round(when - prev, 3)
        prev = when
    payload["timing"] = {
        "process_start_unix": PROCESS_START, "import_s": _marks["ready"] - PROCESS_START,
        "imports": imports, "spec_load_s": loaded - t0, "compute_s": compute_s, "cpu_s": cpu_s,
        "finished_unix": time.time(), "cpus": os.cpu_count(),
    }
    bucket.put(f"runs/{run_id}/task-{index:05d}.json", json.dumps(payload).encode())
    print(json.dumps({"task": index, "replications": payload["replications"], **payload["timing"]}))


if __name__ == "__main__":
    main()
