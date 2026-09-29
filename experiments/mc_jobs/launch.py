"""Run one experiment on Cloud Run Jobs and record what it cost and how long it took.

    python experiments/mc_jobs/launch.py specs/instrument_air.json --tasks 8 --mode blocks
    python experiments/mc_jobs/launch.py specs/instrument_air.json --tasks 32 --N 200000 --mode grid

Uploads the spec, runs the ``reliafy-mc-exp`` job with ``--tasks`` overridden,
waits, downloads every task's output and merges it:

- ``blocks``: compares the merged result with a single-machine run of the
  same spec here, which must match exactly (fingerprint).
- ``grid``: reports the mean availability with its 95% interval, and the
  exact long-run availability for context.

One JSON line per run goes to ``results.jsonl``. Uses the gcloud CLI and your
own credentials.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import pickle
import subprocess
import sys
import tempfile
import time

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parents[1])]

import sim  # noqa: E402
import tally_io  # noqa: E402

PROJECT, REGION, JOB, BUCKET = "reliafy-app", "australia-southeast1", "reliafy-mc-exp", "reliafy-mc-exp"
# Cloud Run list prices (USD, instance-based billing), for estimates only;
# check the current price sheet for australia-southeast1 before quoting.
USD_PER_VCPU_S, USD_PER_GIB_S = 0.00002400, 0.00000250


def sh(*args: str) -> str:
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("spec")
    ap.add_argument("--tasks", type=int, default=1)
    ap.add_argument("--mode", choices=["blocks", "grid"], default="grid")
    ap.add_argument("--N", type=int)
    ap.add_argument("--seed", type=int)
    ap.add_argument("--cpu", type=float, default=1.0, help="vCPU per task (for the cost estimate)")
    ap.add_argument("--memory-gib", type=float, default=2.0)
    ap.add_argument("--no-reference", action="store_true")
    a = ap.parse_args()

    spec = sim.load(str(HERE / a.spec) if not pathlib.Path(a.spec).exists() else a.spec)
    if a.N:
        spec["N"] = a.N
    if a.seed is not None:
        spec["seed"] = a.seed
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S")
    run_id = f"{spec.get('name', 'spec')}-N{spec['N']}-K{a.tasks}-{a.mode}-{stamp}"
    prefix = f"gs://{BUCKET}/runs/{run_id}"

    with tempfile.TemporaryDirectory() as tmp:
        spec_path = pathlib.Path(tmp) / "spec.json"
        spec_path.write_text(json.dumps(spec))
        # The worker gets the RBD ready-built (pickled): it then imports only
        # RePyability, not Reliafy's backend.
        pkl_path = pathlib.Path(tmp) / "rbd.pkl"
        pkl_path.write_bytes(pickle.dumps(sim.build(spec), protocol=5))
        sh("gcloud", "storage", "cp", str(spec_path), str(pkl_path), f"{prefix}/", "--project", PROJECT)

        launched = time.time()
        execution = json.loads(sh(
            "gcloud", "run", "jobs", "execute", JOB, "--region", REGION, "--project", PROJECT,
            "--tasks", str(a.tasks), "--update-env-vars", f"RUN_ID={run_id},MODE={a.mode}",
            "--wait", "--format", "json"))
        returned = time.time()

        out_dir = pathlib.Path(tmp) / "out"
        out_dir.mkdir()
        sh("gcloud", "storage", "cp", f"{prefix}/task-*.json", str(out_dir), "--project", PROJECT)
        tasks = sorted((json.loads(p.read_text()) for p in out_dir.glob("task-*.json")),
                       key=lambda t: t["task"])

    status = execution.get("status", {})
    timing = [t["timing"] for t in tasks]
    billed_s = [t["finished_unix"] - t["process_start_unix"] for t in timing]
    row = {
        "run_id": run_id, "spec": spec.get("name"), "N": spec["N"], "seed": spec["seed"],
        "tasks": a.tasks, "tasks_reported": len(tasks), "mode": a.mode, "cpu": a.cpu,
        "execution": execution.get("metadata", {}).get("name"),
        "wall_s_launch_to_done": round(returned - launched, 2),
        "exec_start": status.get("startTime"), "exec_done": status.get("completionTime"),
        "first_task_start_after_launch_s": round(min(t["process_start_unix"] for t in timing) - launched, 2),
        "last_task_start_after_launch_s": round(max(t["process_start_unix"] for t in timing) - launched, 2),
        "import_s_max": round(max(t["import_s"] for t in timing), 2),
        "imports_slowest_task": max(timing, key=lambda t: t["import_s"]).get("imports"),
        "spec_load_s_max": round(max(t["spec_load_s"] for t in timing), 2),
        "compute_s_max": round(max(t["compute_s"] for t in timing), 2),
        "compute_s_sum": round(sum(t["compute_s"] for t in timing), 2),
        "cpu_s_sum": round(sum(t["cpu_s"] for t in timing), 2),
        "task_s_sum": round(sum(billed_s), 2),
        "usd_estimate": round(sum(billed_s) * (a.cpu * USD_PER_VCPU_S + a.memory_gib * USD_PER_GIB_S), 5),
    }
    row["replications_per_cpu_s"] = round(spec["N"] / row["cpu_s_sum"], 1) if row["cpu_s_sum"] else None

    rbd, _, _ = sim.build(spec)
    if a.mode == "blocks":
        blocks = sorted((b for t in tasks for b in t["blocks"]), key=lambda b: b[0])
        merged = sim.merge(rbd, [tally_io.from_dict(d, rbd.costs) for _, d in blocks])
        row["result"] = sim.summary(sim.result(spec, merged))
        if not a.no_reference:
            t0 = time.perf_counter()
            ref = sim.summary(sim.reference(spec))
            row["reference_local_s"] = round(time.perf_counter() - t0, 2)
            row["matches_single_machine"] = row["result"] == ref
    else:
        T = float(spec["t_simulation"])
        uptimes = np.concatenate([t["summary"]["uptimes"] for t in tasks]) / T
        deltas = np.sum([t["summary"]["deltas"] for t in tasks], axis=0)
        n = int(sum(t["summary"]["n"] for t in tasks))
        working = n + np.cumsum(deltas)  # all start up (no forced-broken nodes in these specs)
        half = 1.96 * uptimes.std(ddof=1) / np.sqrt(uptimes.size)
        row["result"] = {
            "n": n, "mean_availability": float(uptimes.mean()), "ci95_half_width": float(half),
            "exact_long_run_availability": float(rbd.mean_availability(method=sim.METHOD)),
            "curve_min": float(working.min() / n), "curve_end": float(working[-1] / n),
            "system_failures": int(sum(t["summary"]["system_failures"] for t in tasks)),
        }

    with open(HERE / "results.jsonl", "a") as f:
        f.write(json.dumps(row) + "\n")
    print(json.dumps(row, indent=1))


if __name__ == "__main__":
    main()
