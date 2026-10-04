# Compute service runbook (`reliafy-compute`)

Availability simulations run on a second Cloud Run service, `reliafy-compute`,
behind a Cloud Tasks queue (#146). The web service (`reliafy`) stays
responsive on its single vCPU. The free quick simulations (#147) run there
too.

**Status (4 Oct 2026):** none of the Google Cloud resources below exist yet.
The code is in PR #149. Until the setup below is done, `COMPUTE_QUEUE` is
unset and the web service runs every simulation in-process, exactly as it
does today, with the free quick runs included.

Every command below is a **one-time setup step or a deploy step**, to be run
in order **after PR #149 is merged and deployed to `reliafy`** as usual. Each
block is copy-pasteable into one zsh/bash shell. Step 0 sets the variables
that every later block uses, so run it first in the same shell. Every
`gcloud` command names `--project` and `--region`/`--location` explicitly.

## How it fits together

```
browser / MCP ──► reliafy (web, Mongo)                    reliafy-compute (no Mongo)
                   │ 0. exact figures, in-process (free)      ▲      │
                   │ 1. job record in rbd_jobs                 │      │
                   │ 2. Cloud Tasks task, named <job id> ──────┘      │ 3. runs the simulation
                   │    OIDC token as the web SA,                     │
                   │    audience = compute URL                        │
                   ◄──────────────────────────────────────────────────┘
                     4. POST /internal/compute/callback, with an ID token
                        of the compute SA (audience = callback URL)
                     5. web verifies the token, stores the result
                        (and the diagram's saved availability result)
browser polls GET /api/rbd-jobs/<id>; MCP waits up to 20 s, then get_job.
```

- **What the user sees.** The exact figures (#154) are computed on the web,
  as now, and come back straight away. A queued simulation answers `202` with
  those figures plus `job: {job_id, status, queue_position}`. The app shows
  "Queued — you're next…" or "Running the simulation…" where the simulation's
  results go. A finished job's `result` is the whole availability payload:
  the simulation with the exact figures beside it (`rbd_jobs.availability_out`).
- **Same image, different command.** `reliafy-compute` runs the web's image
  digest with `uvicorn backend.compute_app:app`. It runs the same function as
  the in-process path, `rbd_analysis.analyze_availability`, with RePyability
  0.12 (`Dockerfile`: `RePyability.git@v0.12`, `--no-deps`; SurPyval `v0.22`
  in `requirements.txt`).
- **Same seed, same result.** In RePyability 0.12 each simulation's draws are
  seeded from the run's seed and the simulation's index alone, whatever the
  engine. So a job gives the in-process result to the last bit.
  `backend/tests/test_compute_service.py` checks this, through the whole app
  too. The one exception is a run whose size depends on the clock: a Pro run
  that the 20 s budget stops before its precision target, or a free quick run.
  Compute's faster CPU may fit more replications. The result is still exactly
  the fixed run of the count it reports.
- **Stateless.** The compute service has no `MONGODB_URI`, no secrets and no
  user data beyond the self-contained diagram in each task. Saved-model ids
  ride along on blocks, but compute never resolves them.
- **Private.** It's deployed with `--no-allow-unauthenticated`. Only the web
  service account holds `roles/run.invoker` on it.
- **Max 1 instance, concurrency 2, 2 vCPU, no minimum instances.**
  `COMPUTE_WORKERS=2` runs the two concurrent jobs in separate worker
  processes (forkserver). The queue dispatches at most 2 at a time, so Cloud
  Run never has to refuse one.
- **Retries.** If the callback fails, compute answers 5xx and Cloud Tasks
  retries the task. A re-run is safe because results are seeded and the
  callback is idempotent.
- **Abandoned jobs.** A job still queued after `RBD_JOB_STALE_S` (40 min, more
  than the queue's 30 min retry window) is reported failed, and its free run
  is refunded.
- **Unset `COMPUTE_QUEUE`** (self-hosted, dev, tests, or a rollback) makes the
  web app run everything in-process, synchronously, as it did before.

### What runs where

| Runs on `reliafy-compute` | Stays on the web service |
|---|---|
| Availability (and cost) simulations of repairable diagrams: full Pro runs and free quick runs, from the app, the REST API and MCP, from new or from a current state | The exact figures: long-run values, A(t), the window's expected failures, downtime and cost (#154), and everything non-repairable |
| | Repairable diagrams with a block on a proportional-hazards / regression or non-parametric saved model, or a load-sharing / sub-system block. These need saved data, which can't be sent. RePyability 0.12 refuses a Kaplan–Meier block anyway, and in-process the user hears it at once. See `backend/services/compute_core.py` |
| | "Compare with…" (`rbd_compare`), the cheapest design (`rbd_design`), and the cost endpoints' own simulations |
| | The sample diagram's precomputed result at startup, and `backend/scripts/backfill_availability_cache.py` |

**Job kinds.** `compute_core.RUNNERS` maps a job kind to what compute runs.
`availability` is the only kind today. Another analysis joins in three steps:
a request builder in `compute_core`, a runner in `RUNNERS`, and a `KIND_…` in
`rbd_jobs`. #240's next failure from the current state needs no kind of its
own: `analyze_availability` runs it whenever a current state is given, so it
comes back inside the `availability` job, from the same seed (in a free quick
run it keeps to the quick run's time budget). The likely next kind is **a large
diagram's exact figures over time** (`exact=true`). These can take a minute.

**Faster engine (#243).** The Mojo-accelerated RePyability engine (#243) is
planned for compute. It's a private package, installed in Cloud Build with a
read-only credential. Two things in this file change when it lands:
- Compute's image becomes the web digest plus one layer, not the same digest.
  The "Every future deploy" steps below then build that layer from the web
  digest.
- The engine matches RePyability "to rounding, or bit-for-bit in its exact
  mode". Running it in exact mode keeps the same-seed guarantee and its test.
  Otherwise the test needs a tolerance. **This needs a decision.**

Without the package, RePyability's `engine="auto"` behaves exactly as today.

## Settings

Web service (`reliafy`), set in step 6:

| Variable | Value |
|---|---|
| `COMPUTE_URL` | The compute service URL, e.g. `https://reliafy-compute-….a.run.app` (no trailing slash) |
| `COMPUTE_QUEUE` | `projects/reliafy-app/locations/australia-southeast1/queues/reliafy-compute` |
| `COMPUTE_CALLBACK_URL` | The web service's **run.app** URL + `/internal/compute/callback` |
| `COMPUTE_INVOKER_SA` | The web service's service account (Cloud Tasks signs the task as this account) |
| `COMPUTE_SA` | `reliafy-compute@reliafy-app.iam.gserviceaccount.com`: the only identity whose callbacks are accepted |
| optional | `FREE_SIM_SECONDS` (3), `FREE_SIMS_PER_DAY` (50), `FREE_SIM_MAX_REPLICATIONS` (2000), `MCP_JOB_WAIT_S` (20), `COMPUTE_DISPATCH_DEADLINE_S` (290), `RBD_JOB_STALE_S` (2400), `RBD_JOB_TTL_DAYS` (7), `MCP_FREE_QUICK_SIMS` (false; **leave off**: no simulations over MCP on Free) |

Compute service (`reliafy-compute`), set in step 3:
- `COMPUTE_WORKERS=2`.
- `COMPUTE_CALLBACK_URL`, the same value as on the web. It wins over the URL
  in the task.
- `MPLBACKEND=Agg` is already in the image.

**Never** set `MONGODB_URI` or any secret on the compute service.

The free quick runs need no setting: they're on by default (3 s, 50 a day,
refunded on failure, labelled "Quick estimate", app only). They run
in-process until step 6.

## One-time setup

### 0. Variables for this shell

```sh
PROJECT=reliafy-app
REGION=australia-southeast1
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')

# The web service's account. An empty value means the default compute account.
WEB_SA=$(gcloud run services describe reliafy --region "$REGION" --project "$PROJECT" \
  --format='value(spec.template.spec.serviceAccountName)')
WEB_SA=${WEB_SA:-$PROJECT_NUMBER-compute@developer.gserviceaccount.com}
COMPUTE_SA=reliafy-compute@$PROJECT.iam.gserviceaccount.com
TASKS_AGENT=service-$PROJECT_NUMBER@gcp-sa-cloudtasks.iam.gserviceaccount.com

WEB_URL=$(gcloud run services describe reliafy --region "$REGION" --project "$PROJECT" \
  --format='value(status.url)')
CALLBACK_URL=$WEB_URL/internal/compute/callback
QUEUE=projects/$PROJECT/locations/$REGION/queues/reliafy-compute

printf '%s\n' "project number: $PROJECT_NUMBER" "web SA: $WEB_SA" "callback: $CALLBACK_URL" "queue: $QUEUE"
```

Check the four lines it prints. None may be empty, and the callback must be
an `https://…run.app/internal/compute/callback` URL.

### 1. Enable Cloud Tasks

It wasn't enabled on the project as of 3 Oct 2026. `services enable` makes no
change if it already is.

```sh
gcloud services enable cloudtasks.googleapis.com --project "$PROJECT"
# Make sure the Cloud Tasks service agent exists (makes no change if it does):
gcloud beta services identity create --service=cloudtasks.googleapis.com --project "$PROJECT"
```

The Cloud Tasks service agent (`$TASKS_AGENT`) mints each task's OIDC token.
Projects that enabled the API after 19 March 2019 give it
`roles/cloudtasks.serviceAgent` automatically. Check it:

```sh
gcloud projects get-iam-policy "$PROJECT" --flatten='bindings[].members' \
  --filter="bindings.members:$TASKS_AGENT" --format='value(bindings.role)'
# Expect roles/cloudtasks.serviceAgent. Only if it's missing:
# gcloud projects add-iam-policy-binding "$PROJECT" \
#   --member "serviceAccount:$TASKS_AGENT" --role roles/cloudtasks.serviceAgent
```

### 2. The compute service's own account

The account needs no project roles. It only mints ID tokens for itself, from
the metadata server, to call back.

```sh
gcloud iam service-accounts create reliafy-compute --project "$PROJECT" \
  --display-name "Reliafy compute service (no data access)"
```

### 3. Deploy `reliafy-compute` from the live web image

First, the web service's traffic must be 100% on its latest revision. Traffic
was once left pinned to an old revision.

```sh
gcloud run services describe reliafy --region "$REGION" --project "$PROJECT" --format='value(status.traffic)'
# Expect: {'latestRevision': True, 'percent': 100, 'revisionName': 'reliafy-000NN-xxx'}
# If not: gcloud run services update-traffic reliafy --to-latest --region "$REGION" --project "$PROJECT"
```

Then deploy compute from that revision's **image digest**, not a tag:

```sh
REV=$(gcloud run services describe reliafy --region "$REGION" --project "$PROJECT" \
  --format='value(status.latestReadyRevisionName)')
IMAGE=$(gcloud run revisions describe "$REV" --region "$REGION" --project "$PROJECT" \
  --format='value(status.imageDigest)')
echo "$IMAGE"   # …/cloud-run-source-deploy/reliafy@sha256:… (must contain @sha256:)

gcloud run deploy reliafy-compute --project "$PROJECT" --region "$REGION" \
  --image "$IMAGE" \
  --command uvicorn \
  --args=backend.compute_app:app,--host,0.0.0.0,--port,8080 \
  --service-account "$COMPUTE_SA" \
  --no-allow-unauthenticated \
  --max-instances 1 --min-instances 0 \
  --cpu 2 --memory 2Gi --concurrency 2 --timeout 300 \
  --set-env-vars "COMPUTE_WORKERS=2,COMPUTE_CALLBACK_URL=$CALLBACK_URL"

COMPUTE_URL=$(gcloud run services describe reliafy-compute --region "$REGION" --project "$PROJECT" \
  --format='value(status.url)')
echo "$COMPUTE_URL"
```

About these flags:
- **`--args=`.** The `=` sign keeps gcloud from reading `--host` and `--port`
  as its own flags. The list is comma-separated.
- **`--command`.** It replaces the image's `sh -c "uvicorn backend.main:app …"`.
  Port 8080 is Cloud Run's default `PORT`.
- **`--timeout 300`.** Each task's dispatch deadline is 290 s
  (`COMPUTE_DISPATCH_DEADLINE_S`), just under it. A Pro run's own budget is
  20 s, and a run with a window the user chose is shortened past 200 s.

### 4. The queue

```sh
gcloud tasks queues create reliafy-compute --project "$PROJECT" --location "$REGION" \
  --max-concurrent-dispatches 2 \
  --max-dispatches-per-second 2 \
  --max-attempts 10 \
  --min-backoff 1s --max-backoff 30s --max-doublings 5 \
  --max-retry-duration 1800s
```

`--max-concurrent-dispatches 2` matches 1 instance × concurrency 2. If you
raise either, raise this too.

### 5. IAM

```sh
# The web SA may invoke the private compute service. The task's OIDC token is
# signed as the web SA.
gcloud run services add-iam-policy-binding reliafy-compute --project "$PROJECT" --region "$REGION" \
  --member "serviceAccount:$WEB_SA" --role roles/run.invoker

# The web SA may add tasks to the queue.
gcloud tasks queues add-iam-policy-binding reliafy-compute --project "$PROJECT" --location "$REGION" \
  --member "serviceAccount:$WEB_SA" --role roles/cloudtasks.enqueuer

# Creating a task whose OIDC token is signed as the web SA requires actAs
# (iam.serviceAccounts.actAs) on that account.
gcloud iam service-accounts add-iam-policy-binding "$WEB_SA" --project "$PROJECT" \
  --member "serviceAccount:$WEB_SA" --role roles/iam.serviceAccountUser

# The Cloud Tasks service agent mints the token as the web SA. The Cloud Tasks
# docs ("Create HTTP target tasks") grant it Service Account User on that account.
gcloud iam service-accounts add-iam-policy-binding "$WEB_SA" --project "$PROJECT" \
  --member "serviceAccount:$TASKS_AGENT" --role roles/iam.serviceAccountUser
```

The compute SA needs nothing. The web service doesn't grant it anything
either: the web checks the ID token itself (its signature, audience = the
callback URL, and `email` = `COMPUTE_SA`).

The full list:

| Who | Role | On |
|---|---|---|
| web SA | `roles/run.invoker` | service `reliafy-compute` |
| web SA | `roles/cloudtasks.enqueuer` | queue `reliafy-compute` |
| web SA | `roles/iam.serviceAccountUser` | the web SA itself |
| Cloud Tasks service agent | `roles/iam.serviceAccountUser` | the web SA |
| Cloud Tasks service agent | `roles/cloudtasks.serviceAgent` | the project (automatic; checked in step 1) |
| compute SA | none | |

The web service still runs as the default compute account, which has broad
project roles. A dedicated, least-privilege web account is a separate
clean-up.

### 6. Switch the web service to the queue

```sh
gcloud run services update reliafy --project "$PROJECT" --region "$REGION" \
  --update-env-vars "COMPUTE_URL=$COMPUTE_URL,COMPUTE_QUEUE=$QUEUE,COMPUTE_CALLBACK_URL=$CALLBACK_URL,COMPUTE_INVOKER_SA=$WEB_SA,COMPUTE_SA=$COMPUTE_SA"
```

This makes a new revision. Check that traffic follows it, as in step 7.

### 7. Verify

```sh
# Both services serve their latest revision (see the traffic-pin incident).
for s in reliafy reliafy-compute; do
  gcloud run services describe "$s" --region "$REGION" --project "$PROJECT" --format='value(status.traffic)'
done
# Expect latestRevision True, 100 percent, for each.

# Compute is private: anonymous calls are refused …
# (/health, not /healthz: Cloud Run reserves paths ending in "z" and answers
# /healthz with its own 404, before the service sees it.)
curl -s -o /dev/null -w '%{http_code}\n' "$COMPUTE_URL/health"             # 403
# … and an authorised one works (your account is project owner):
curl -s -H "Authorization: Bearer $(gcloud auth print-identity-token)" "$COMPUTE_URL/health"
# {"ok":true,"repyability_version":"0.12"}

# The callback refuses anything without the compute SA's token.
curl -s -o /dev/null -w '%{http_code}\n' -X POST -H 'Content-Type: application/json' \
  -d '{"job_id":"x","status":"done"}' "$CALLBACK_URL"                       # 401

# Both run the same image digest.
for s in reliafy reliafy-compute; do
  r=$(gcloud run services describe "$s" --region "$REGION" --project "$PROJECT" \
    --format='value(status.latestReadyRevisionName)')
  gcloud run revisions describe "$r" --region "$REGION" --project "$PROJECT" --format='value(status.imageDigest)'
done
# Expect the same …@sha256:… twice.
```

End to end:
1. **Pro.** In the app as a Pro user, open a repairable diagram, change a
   parameter and Calculate. The exact figures show at once. Where the
   simulation's results go, expect "Queued — you're next…" or "Running the
   simulation…", then the simulation.
2. **Free.** As a free user, Calculate shows the exact figures. "Run quick
   simulation (free, ~3 s)" should then show "Quick estimate", the
   replications run, and the precision note.
3. **Queue drained.** Check the queue is empty and compute logged the job:
   ```sh
   gcloud tasks list --queue reliafy-compute --location "$REGION" --project "$PROJECT"
   gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="reliafy-compute"' \
     --project "$PROJECT" --limit 20 --freshness 10m
   ```
4. **Logs.** In the web logs, look for "Rejected compute callback" (the token
   or the config is wrong) and "Enqueue of job … failed" (the IAM is wrong).
5. **MCP.** On a Pro account, analyze_rbd on a repairable diagram with no
   saved result returns the exact figures. Its `simulation` is either the
   result (within 20 s) or `{available: false, status: "queued", job_id}`;
   get_job then returns the result.

### Rollback

Remove the queue setting. The web app goes back to running simulations
in-process (nothing else changes):

```sh
gcloud run services update reliafy --project "$PROJECT" --region "$REGION" --remove-env-vars COMPUTE_QUEUE
```

## Every future deploy: both services from one digest

Set the step 0 variables first.

1. Deploy the web service as now, from a clean worktree of `origin/main`:
   ```sh
   gcloud run deploy reliafy --source . --region "$REGION" --project "$PROJECT"
   ```
2. Check its traffic is 100% on the latest revision (step 7's first loop).
3. Deploy compute from the digest just built. `gcloud run deploy` with only
   `--image` keeps the service's command, args, account, limits and
   variables:
   ```sh
   REV=$(gcloud run services describe reliafy --region "$REGION" --project "$PROJECT" \
     --format='value(status.latestReadyRevisionName)')
   IMAGE=$(gcloud run revisions describe "$REV" --region "$REGION" --project "$PROJECT" \
     --format='value(status.imageDigest)')
   gcloud run deploy reliafy-compute --image "$IMAGE" --region "$REGION" --project "$PROJECT"
   ```
4. Run step 7's checks: traffic on both, the same digest on both, and
   `/health` reporting the RePyability version the Dockerfile pins (0.12 now).

Between steps 1 and 3, compute runs the previous image for a minute. That's
harmless unless the release changes the request format in
`backend/services/compute_core.py` or the RePyability pin. In that case,
deploy the web with `--no-traffic`, deploy compute from the new digest, then
send traffic to the web's latest revision:

```sh
gcloud run services update-traffic reliafy --to-latest --region "$REGION" --project "$PROJECT"
```

Once #243 lands, step 3 deploys compute's own image: the web digest plus the
engine layer, built in Cloud Build. That image's notes go here then.

## Operating notes

- **Cold start.** Compute scales to zero. The first job after idle waits for
  the container (about 7 s), plus the worker processes' imports (a few
  seconds). The app shows it as "Running the simulation…".
- **Capacity.** One instance runs two jobs at a time. More are queued, and
  the app shows "Queued — N ahead of you…". Revisit `--max-instances` at the
  first paid user and again at 10 (Derryn, 3 Oct).
- **Jobs.** The `rbd_jobs` documents (with their results) are kept 7 days
  after they finish (`RBD_JOB_TTL_DAYS`), then removed by a TTL index. Each
  job also keeps the exact figures it was asked with (`context`), so its
  finished view is the whole payload. A run from a current state is its own
  job and is never stored on the diagram. Free quick runs per user per day
  are in `free_sim_usage` (TTL as well).
- **Task size.** Cloud Tasks caps a task at 1 MB. A diagram too large for
  that is refused with a message; none is near it.
