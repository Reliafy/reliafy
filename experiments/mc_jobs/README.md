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

## Next experiments
1. Cut import time: import only what the worker needs, not `backend.services.rbd_analysis`'s whole tree.
2. 2 or 4 vCPU per task, running blocks in processes: less per-task overhead for the same speed?
3. Larger and harder diagrams (benchmark generator, #110), and rare-event cases.
4. The same work inline in a Cloud Run service, to set the inline/Jobs boundary.
5. Merge on the server (the future `get_job`) instead of the launcher.
