"""Run the runtime experiment: design points ``--start`` .. ``--start + --n``,
each timed in its own process (run_one.py), ``--workers`` at a time. Appends
one JSON line per design point to ``--out`` (resumable: indices already in it
are skipped).

    python -m tools.quote_bench.run --n 600 --workers 3 --cap 60 --out runs.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

from tools.quote_bench.generate import design

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))


def _one(index: int, cap: float, master_seed: int, machine: dict) -> dict:
    d = design(index, master_seed)
    req = json.dumps({"graph": d["graph"], "options": d["options"], "cap_s": cap})
    try:
        proc = subprocess.run([sys.executable, os.path.join(HERE, "run_one.py")], input=req,
                              capture_output=True, text=True, timeout=cap * 2 + 120, cwd=ROOT)
        line = (proc.stdout.strip().splitlines() or [""])[-1]
        res = json.loads(line) if line.startswith("{") else {
            "status": "error", "error": (proc.stderr or "no output")[-300:]}
    except subprocess.TimeoutExpired:
        res = {"status": "censored", "seconds": cap, "killed": True}
    return {"index": index, "master_seed": master_seed, **machine,
            "factors": d["factors"], "features": d["features"], "result": res}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=1)
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--cap", type=float, default=60.0)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--machine", default=platform.node())
    ap.add_argument("--out", default="runs.jsonl")
    a = ap.parse_args()
    done = set()
    if os.path.exists(a.out):
        with open(a.out) as fh:
            done = {json.loads(line)["index"] for line in fh if line.strip()}
    todo = [i for i in range(a.start, a.start + a.n) if i not in done]
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=ROOT).stdout.strip()
    machine = {"machine": a.machine, "workers": a.workers, "cpus": os.cpu_count(), "commit": commit}
    print(f"{len(todo)} to run, {len(done)} already in {a.out}", flush=True)
    with ThreadPoolExecutor(a.workers) as pool, open(a.out, "a") as fh:
        futs = [pool.submit(_one, i, a.cap, a.seed, machine) for i in todo]
        for k, fut in enumerate(as_completed(futs), 1):
            row = fut.result()
            fh.write(json.dumps(row, default=str) + "\n")
            fh.flush()
            r = row["result"]
            print(f"[{k}/{len(todo)}] #{row['index']} {r.get('status'):8} {r.get('seconds') or 0:7.2f}s "
                  f"blocks={row['features']['n_blocks']} sims={row['features']['n_simulations']} "
                  f"{r.get('error', '')[:120]}", flush=True)


if __name__ == "__main__":
    main()
