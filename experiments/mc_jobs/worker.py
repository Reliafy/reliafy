"""One Cloud Run Jobs task: run this task's share of an experiment's blocks.

Env: ``BUCKET``, ``RUN_ID``, ``MODE`` (``blocks`` | ``grid``), and Cloud Run's
``CLOUD_RUN_TASK_INDEX`` / ``CLOUD_RUN_TASK_COUNT``. Reads
``gs://BUCKET/runs/RUN_ID/spec.json`` and writes ``task-NNNNN.json`` beside it.

- ``blocks``: every block's full tally, for the exact comparison with a
  single-machine run (use modest N: a block's trace is ~0.5 MB).
- ``grid``: the task's blocks merged, its availability trace snapped onto
  ``GRID`` equal cells over [0, T] (integer counts, so tasks still add
  exactly), plus each replication's uptime. For the scaling runs.
"""

import time

PROCESS_START = time.time()  # before the heavy imports, to time them

import json  # noqa: E402
import os  # noqa: E402

import numpy as np  # noqa: E402
from google.cloud import storage  # noqa: E402

import sim  # noqa: E402
import tally_io  # noqa: E402

GRID = 2000


def gridded(tally, t_simulation: float) -> np.ndarray:
    """The tally's net-change-in-working counts, summed per grid cell."""
    times = np.fromiter(tally.changes.keys(), dtype=float, count=len(tally.changes))
    deltas = np.fromiter(tally.changes.values(), dtype=np.int64, count=len(tally.changes))
    edges = np.linspace(0.0, t_simulation, GRID + 1)
    cells = np.clip(np.searchsorted(edges, times, side="right") - 1, 0, GRID - 1)
    return np.bincount(cells, weights=deltas, minlength=GRID).astype(np.int64)


def main() -> None:
    imported = time.time()
    index = int(os.environ.get("CLOUD_RUN_TASK_INDEX", "0"))
    count = int(os.environ.get("CLOUD_RUN_TASK_COUNT", "1"))
    run_id, mode = os.environ["RUN_ID"], os.environ.get("MODE", "grid")
    bucket = storage.Client().bucket(os.environ["BUCKET"])
    spec = json.loads(bucket.blob(f"runs/{run_id}/spec.json").download_as_text())
    loaded = time.time()

    blocks = sim.plan_blocks(spec)
    indices = sim.share(len(blocks), index, count)
    payload = {"task": index, "count": count, "mode": mode,
               "replications": sum(blocks[i][0] for i in indices)}
    wall0, cpu0 = time.perf_counter(), time.process_time()
    if mode == "blocks":
        payload["blocks"] = [[i, tally_io.to_dict(t)] for i, t in sim.iter_blocks(spec, indices)]
    else:
        # Summarise each block as it finishes and drop its trace.
        T = float(spec["t_simulation"])
        deltas, uptimes = np.zeros(GRID, dtype=np.int64), []
        n = failures = 0
        uptime = 0.0
        for _, t in sim.iter_blocks(spec, indices):
            deltas += gridded(t, T)
            uptimes.extend(t.uptimes)
            n, failures, uptime = n + t.n, failures + t.system_failures, uptime + t.system_uptime
        payload["summary"] = {"n": n, "system_uptime": uptime, "system_failures": failures,
                              "uptimes": uptimes, "grid": GRID, "t_simulation": T,
                              "deltas": deltas.tolist()}
    compute_s, cpu_s = time.perf_counter() - wall0, time.process_time() - cpu0
    payload["timing"] = {
        "process_start_unix": PROCESS_START, "import_s": imported - PROCESS_START,
        "spec_load_s": loaded - imported, "compute_s": compute_s, "cpu_s": cpu_s,
        "finished_unix": time.time(), "cpus": os.cpu_count(),
    }
    bucket.blob(f"runs/{run_id}/task-{index:05d}.json").upload_from_string(
        json.dumps(payload), content_type="application/json")
    print(json.dumps({"task": index, "replications": payload["replications"], **payload["timing"]}))


if __name__ == "__main__":
    main()
