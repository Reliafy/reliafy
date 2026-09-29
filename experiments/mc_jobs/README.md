# Monte Carlo on Cloud Run Jobs: experiments

Groundwork for agent-priced RBD compute (#107): Phase 1 benchmarks (#110) and the Phase 2 job runner (#111). This isn't part of the app. It uses its own image, job, bucket and service account, and never touches the app's service or database.

## How it works
- **Block plan.** A spec (`specs/*.json`: compact RBD graph, mission time `t_simulation`, `N`, `seed`) is split exactly as RePyability 0.10.1's own `n_jobs` path splits it: blocks of 250 replications, seeded in turn from `SeedSequence(seed)`.
- **Tasks.** Cloud Run task *i* of *K* (`CLOUD_RUN_TASK_INDEX`/`COUNT`) runs a contiguous share of the blocks (`worker.py`) and writes its output to `gs://reliafy-mc-exp/runs/<run>/`.
- **`blocks` mode.** Every block's full tally (`tally_io.py`; RePyability's private `_Tally`). Merged in block order, this reproduces a single-machine run exactly. Use it for correctness, with modest N.
- **`grid` mode.** Each task summarises and drops each block as it finishes:
  - the net change in systems working, summed onto 2,000 equal cells over [0, T] (integers, so tasks add exactly);
  - each replication's uptime, for the mission-average availability and its interval.
  
  Memory stays flat. Use it for scale.
- **Launcher.** `launch.py` (run locally with gcloud credentials) uploads the spec, executes the job with `--tasks K`, collects the outputs, merges them and appends a row to `results.jsonl`.

## Infrastructure (reliafy-app, australia-southeast1)
- **Job** `reliafy-mc-exp`: 1 vCPU, 2 GiB, parallelism 100, no retries, 30 min task timeout.
- **Image** `…/cloud-run-source-deploy/reliafy-mc-exp:latest`, built with `gcloud builds submit --config experiments/mc_jobs/cloudbuild.yaml .` from the repo root.
- **Bucket** `gs://reliafy-mc-exp`: objects deleted after 30 days.
- **Service account** `reliafy-mc-exp@`: `storage.objectAdmin` on that bucket only.
- **Quotas (29 Sep):**
  - 200 vCPU and 400 GiB per region;
  - 100 instances;
  - 60 job runs a minute;
  - no GPU (L4) allocation listed for Sydney.

## Results so far (29–30 Sep 2026)
Instrument-air availability sample: repairable, 2-out-of-3 compressors, standby dryer, T = 600,000 h, about 34 system failures per replication.

**Exactness (`blocks`, N = 2,000):**
- 1, 4 and 8 cloud tasks give an identical result, to the last bit of every event time.
- Against a Mac, the headline numbers match exactly, but event times differ in the last bits (macOS vs Linux maths libraries). Reproducibility holds within the platform, so job records should note the platform.

**Scaling (`grid`, N = 200,000):**

| K tasks | wall (launch→merged) | first task starts | import | compute (slowest) | CPU-s total | est. USD |
|---|---|---|---|---|---|---|
| 1 (N=20k) | 154 s | 26 s (cold) | 8.5 s | 115 s | 113 | 0.004 |
| 10 | 151 s | 9–11 s | 8.2 s | 128 s | 1,180 | 0.037 |
| 20 | 87 s | 10–12 s | 7.2 s | 65 s | 1,081 | 0.038 |
| 50 | 51 s | 10–14 s | 7.7 s | 27 s | 1,070 | 0.043 |
| 100 | 48 s | 9–12 s | 8.5 s | 15 s | 1,092 | 0.049 |

**Takeaways:**
- **Throughput:** about 170–190 replications per vCPU-second on this diagram, roughly 2.4× slower per core than an M-series Mac.
- **Parallelism buys time, not cost.** CPU-seconds stay flat at about 1,100 whatever K is. Cost rises only with per-task overhead: +30% from K = 10 to 100, for a 3× faster result.
- **Floor of about 45 s per job.** That's roughly 10 s to schedule and start a task, about 8 s of Python imports, and the collect-and-merge. The ≤ 30 s "inline" tier therefore can't use Jobs: it runs in the service, or in a warm worker.
- **Cost:** about US$0.19 per million replications of this diagram, from estimated list prices (instance time from process start). Check the Sydney price sheet before quoting.
- **Precision:** A = 0.999686 with a 95% half-width under 5e-7, against the structure-function long-run value of 0.999682. The gap is larger than the interval. Expected if the standby dryer (dependence) breaks the independence the formula assumes; worth confirming.

## Start-up: where the ~8 s goes (30 Sep)
First pass: don't import Reliafy at all (the launcher pickles the built RBD, about 9 KB), use Cloud Storage over the standard library (`gcs.py`) instead of `google-cloud-storage`, and slim the image (225 → 124 MB, pinned, no matplotlib).

- **Result:** imports went from about 8.2 s to 7.1 s. Image size made no difference.
- **Cloud import profile** (`python -X importtime` in the container): about 1,900 modules and 4.5 s of import work, plus cold file reads.

| Package | Import time | Pulled in by |
|---|---|---|
| SciPy | 1.74 s | SurPyval: scipy.stats, which brings signal, ndimage, linalg… |
| pandas | 0.63 s | SurPyval, formulaic |
| NumPy | 0.52 s | needed |
| networkx | 0.41 s | RePyability (graph) |
| formulaic + narwhals | 0.30 s | SurPyval (regression only) |
| SurPyval + RePyability | 0.27 s | |

Locally the same imports take about 1.1 s: the cloud vCPU is slower and its disk is cold.

**What's left is in the libraries' import graphs** (both maintained by Derryn):
- **SurPyval:** import nonparametric, regression (formulaic/pandas), `scipy.stats` and `scipy.integrate` lazily (PEP 562 `__getattr__`, or imports inside functions). Parametric sf/qf needs only NumPy and `scipy.special`. Likely saving: about 2.5–3 s of the 4.5.
- **RePyability:** keep networkx (the RBD needs it). Lazy-import `non_repairable`, fitting helpers and tqdm where only simulation is needed.
- **The architectural answer to the ~45 s floor is warm workers,** not faster imports: a small pool that has already imported, pulling jobs off a queue (Cloud Run worker pools, or a min-instance service). It costs idle time, and Reliafy runs no min-instances today by choice. Jobs stay the batch tier.

## Plan: several cores per task
Why: per-task overhead (start, imports, the output upload) is paid once per task, not per core, and an 8-vCPU task imports once for 8 cores.

1. **Cores.** Read the real CPU allowance with `len(os.sched_getaffinity(0))` or the cgroup `cpu.max`; `os.cpu_count()` may report the host.
2. **Fork after loading.** The parent imports, unpickles the RBD and plans the blocks, then forks P workers with an explicit `multiprocessing.get_context("fork")`. The default changes to forkserver in Python 3.14. Set `OMP_NUM_THREADS=1` so NumPy/BLAS threads don't fight the processes.
3. **Work.** Each worker takes a strided or contiguous share of the task's blocks and returns only its grid deltas, uptimes and scalars (small, over the pipe). The parent merges in block order, so the result stays bit-exact.
4. **Job size.** `--cpu 2|4|8` with memory at 1 GiB per vCPU or more (8 vCPU needs at least 4 GiB).
5. **Experiment:** the same 200k replications at the same 100-vCPU budget, 100×1 vs 50×2 vs 25×4 vs 13×8. Measure wall time, cost, and per-core throughput (shared caches and memory bandwidth).
6. **Expected:** lower cost (the task-seconds minus CPU-seconds gap shrinks), similar wall time, fewer instances against the 100-instance quota, and room to use the full 200-vCPU quota.

The same code gives the app's inline tier multi-core simulation if the service ever gets more than 1 vCPU.

## Plan: faster per core (RePyability)
Profile: 500 replications, 264k events, about 5 µs per event, all Python overhead with no single hotspot.

| Change (in `repairable_rbd.py`) | Share of time now | Expected |
|---|---|---|
| Heap entries as `(time, seq, event)` tuples instead of `@dataclass(order=True)` `Event` ordering: 1.25M Python `__lt__` calls per 500 replications become C comparisons | ~15% (heap push/pop + `__lt__`) | −10–15% |
| Skip the structure check when an event can't change the system state (coherent systems: a repair while the system is up, or a failure while it's down). Most repairs happen while the system is up | ~17% (`is_system_working`) | −8% |
| Evaluate structure on an integer bitmask of component states against precomputed cut-set masks | part of the above | −5% |
| Draw each component's next several failure and repair times in one vectorised `ppf` call and pop from a list (per-draw call overhead in `_NodeStream.draw`/`_follow_up`) | ~30% (`_follow_up` incl. draws) | −10–15% |
| Build the per-replication timeline and status durations (`combined_timeline`, `time_at_status`) with NumPy | ~8% | −5% |

Together that's maybe 1.5–2× per core with no change in results (the same draws in the same order: check the fingerprints). Beyond that is the vectorised engine (RePyability #114: replications in lockstep as arrays), which is where 10×+ lives.

## Next experiments
1. Cut import time further: lazy imports in SurPyval/RePyability (above).
2. 2 or 4 vCPU per task, running blocks in processes: less per-task overhead for the same speed?
3. Larger and harder diagrams (benchmark generator, #110), and rare-event cases.
4. The same work inline in a Cloud Run service, to set the inline/Jobs boundary.
5. Merge on the server (the future `get_job`) instead of the launcher.
