# Compute service runbook (`reliafy-compute`)

Heavy analyses (availability simulations) run on a second Cloud Run service,
`reliafy-compute`, behind a Cloud Tasks queue (#146). The web service
(`reliafy`) stays responsive on its single vCPU, and the free quick
simulations (#147) run there too.

Nothing in this file has been run. Every command below is a **one-time setup
step or a deploy step for Derryn to run**, in order.

## How it fits together

```
browser / MCP ──► reliafy (web, Mongo)                    reliafy-compute (no Mongo)
                   │ 1. job record in rbd_jobs               ▲      │
                   │ 2. Cloud Tasks task, named <job id> ────┘      │ 3. runs the simulation
                   │    OIDC token as the web SA,                   │
                   │    audience = compute URL                      │
                   ◄────────────────────────────────────────────────┘
                     4. POST /internal/compute/callback, with an ID token
                        of the compute SA (audience = callback URL)
                     5. web verifies the token, stores the result
                        (and the diagram's saved availability result)
browser polls GET /api/rbd-jobs/<id>; MCP waits up to 20 s, then get_job.
```

- **Same image, different command.** `reliafy-compute` runs the web's image
  digest with `uvicorn backend.compute_app:app`, so the two services' maths
  can't drift.
- **Stateless.** The compute service has no `MONGODB_URI`, no secrets and no
  user data beyond the self-contained diagram in each task.
- **Private.** It's deployed with `--no-allow-unauthenticated`. Only the web
  service account holds `roles/run.invoker` on it.
- **Max 1 instance, concurrency 2, 2 vCPU.** `COMPUTE_WORKERS=2` runs the two
  concurrent jobs in separate worker processes. The queue dispatches at most
  2 at a time, so Cloud Run never has to refuse one.
- **Retries.** If the callback fails, compute answers 5xx and Cloud Tasks
  retries the task. A re-run is safe because results are seeded and the
  callback is idempotent.
- **Abandoned jobs.** A job still queued after `RBD_JOB_STALE_S` (40 min, more
  than the queue's 30 min retry window) is reported failed and its free run
  is refunded.
- **Unset `COMPUTE_QUEUE`** (self-hosted, dev, tests, or a rollback) makes the
  web app run everything in-process, synchronously, as it did before.

### What runs where

| Runs on `reliafy-compute` | Stays on the web service |
|---|---|
| Availability simulations of repairable diagrams: full (Pro) runs and free quick runs, from the app, the REST API and MCP | Everything else: non-repairable reliability, validation, fitting, exports, strategy, and the exact steady-state figures |
| | Repairable diagrams with a block whose model is a proportional-hazards / regression or non-parametric saved model, or a load-sharing / sub-system block. These need a re-fit from saved data, which can't be sent; the repairable analysis rejects most of them anyway. See `backend/services/compute_core.py` |
| | The sample diagram's precomputed result at startup, and `backend/scripts/backfill_availability_cache.py` |

When RePyability 0.11 lands (#148), its exact availability-over-time and
mission curves should go to compute too, as another `kind` in
`compute_core.run`.

## Settings

Web service (`reliafy`):

| Variable | Value |
|---|---|
| `COMPUTE_URL` | The compute service URL, e.g. `https://reliafy-compute-….a.run.app` (no trailing slash) |
| `COMPUTE_QUEUE` | `projects/reliafy-app/locations/australia-southeast1/queues/reliafy-compute` |
| `COMPUTE_CALLBACK_URL` | The web service's **run.app** URL + `/internal/compute/callback` |
| `COMPUTE_INVOKER_SA` | The web service's service account (Cloud Tasks signs the task as this account) |
| `COMPUTE_SA` | `reliafy-compute@reliafy-app.iam.gserviceaccount.com`: the only identity whose callbacks are accepted |
| optional | `FREE_SIM_SECONDS` (3), `FREE_SIMS_PER_DAY` (50), `FREE_SIM_MAX_REPLICATIONS` (2000), `MCP_JOB_WAIT_S` (20), `MCP_FREE_QUICK_SIMS` (false; leave off) |

Compute service (`reliafy-compute`): `COMPUTE_WORKERS=2` and
`COMPUTE_CALLBACK_URL` (same value as on the web; it wins over the URL in the
task), plus `MPLBACKEND=Agg`, which is already in the image. **Never** set
`MONGODB_URI` or any secret here.

## One-time setup

Run steps 1–7 once, after the branch has been merged and deployed to
`reliafy` as usual. With no `COMPUTE_*` variables set, that deploy still runs
everything in-process.

### 0. Variables for this shell

```sh
PROJECT=reliafy-app
REGION=australia-southeast1
PROJECT_NUMBER=$(gcloud projects describe $PROJECT --format='value(projectNumber)')

# The web service's account. An empty value means the default compute account.
WEB_SA=$(gcloud run services describe reliafy --region $REGION --project $PROJECT \
  --format='value(spec.template.spec.serviceAccountName)')
WEB_SA=${WEB_SA:-$PROJECT_NUMBER-compute@developer.gserviceaccount.com}
COMPUTE_SA=reliafy-compute@$PROJECT.iam.gserviceaccount.com
TASKS_AGENT=service-$PROJECT_NUMBER@gcp-sa-cloudtasks.iam.gserviceaccount.com

WEB_URL=$(gcloud run services describe reliafy --region $REGION --project $PROJECT --format='value(status.url)')
QUEUE=projects/$PROJECT/locations/$REGION/queues/reliafy-compute
echo "$WEB_SA  $WEB_URL"
```

### 1. Enable Cloud Tasks

It isn't enabled on the project yet (checked 3 Oct 2026):

```sh
gcloud services enable cloudtasks.googleapis.com --project $PROJECT
# Make sure the Cloud Tasks service agent exists (no-op if it does):
gcloud beta services identity create --service=cloudtasks.googleapis.com --project $PROJECT
```

The Cloud Tasks service agent (`$TASKS_AGENT`) is what mints each task's OIDC
token. On projects that enabled the API after 19 March 2019, it gets
`roles/cloudtasks.serviceAgent` automatically. Check it:

```sh
gcloud projects get-iam-policy $PROJECT --flatten='bindings[].members' \
  --filter="bindings.members:$TASKS_AGENT" --format='value(bindings.role)'
# Expect roles/cloudtasks.serviceAgent. If it's missing:
# gcloud projects add-iam-policy-binding $PROJECT \
#   --member serviceAccount:$TASKS_AGENT --role roles/cloudtasks.serviceAgent
```

### 2. The compute service's own account

It needs no project roles: it only mints ID tokens for itself, from the
metadata server, to call back.

```sh
gcloud iam service-accounts create reliafy-compute --project $PROJECT \
  --display-name "Reliafy compute service (no data access)"
```

### 3. Deploy `reliafy-compute` from the live web image

First check that the web service's traffic is on its latest revision. Traffic
was once left pinned to an old revision.

```sh
gcloud run services describe reliafy --region $REGION --project $PROJECT --format='value(status.traffic)'
# Expect: {'latestRevision': True, 'percent': 100, 'revisionName': 'reliafy-000NN-xxx'}

REV=$(gcloud run services describe reliafy --region $REGION --project $PROJECT \
  --format='value(status.latestReadyRevisionName)')
IMAGE=$(gcloud run revisions describe $REV --region $REGION --project $PROJECT \
  --format='value(status.imageDigest)')
echo $IMAGE   # …/cloud-run-source-deploy/reliafy@sha256:…

gcloud run deploy reliafy-compute --project $PROJECT --region $REGION \
  --image "$IMAGE" \
  --command uvicorn \
  --args=backend.compute_app:app,--host,0.0.0.0,--port,8080 \
  --service-account $COMPUTE_SA \
  --no-allow-unauthenticated \
  --max-instances 1 --min-instances 0 \
  --cpu 2 --memory 2Gi --concurrency 2 --timeout 300 \
  --set-env-vars "COMPUTE_WORKERS=2,COMPUTE_CALLBACK_URL=$WEB_URL/internal/compute/callback"

COMPUTE_URL=$(gcloud run services describe reliafy-compute --region $REGION --project $PROJECT \
  --format='value(status.url)')
```

About these flags:
- `--args=` with the `=` sign keeps gcloud from reading `--host` and `--port`
  as its own flags. The list is comma-separated.
- `--command` replaces the image's `sh -c "uvicorn backend.main:app …"`. Port
  8080 is Cloud Run's default `PORT`.

### 4. The queue

```sh
gcloud tasks queues create reliafy-compute --project $PROJECT --location $REGION \
  --max-concurrent-dispatches 2 \
  --max-dispatches-per-second 2 \
  --max-attempts 10 \
  --min-backoff 1s --max-backoff 30s --max-doublings 5 \
  --max-retry-duration 1800s
```

- `--max-concurrent-dispatches 2` matches 1 instance × concurrency 2. If you
  raise either, raise this too.
- Each task's dispatch deadline is set per task to 290 s
  (`COMPUTE_DISPATCH_DEADLINE_S`), just under the service's 300 s timeout.

### 5. IAM

```sh
# The web SA may invoke the private compute service. The task's OIDC token is
# signed as the web SA.
gcloud run services add-iam-policy-binding reliafy-compute --project $PROJECT --region $REGION \
  --member serviceAccount:$WEB_SA --role roles/run.invoker

# The web SA may add tasks to the queue.
gcloud tasks queues add-iam-policy-binding reliafy-compute --project $PROJECT --location $REGION \
  --member serviceAccount:$WEB_SA --role roles/cloudtasks.enqueuer

# Creating a task whose OIDC token is signed as the web SA requires actAs
# (iam.serviceAccounts.actAs) on that account.
gcloud iam service-accounts add-iam-policy-binding $WEB_SA --project $PROJECT \
  --member serviceAccount:$WEB_SA --role roles/iam.serviceAccountUser

# The Cloud Tasks service agent mints the token as the web SA. The Cloud Tasks
# docs ("Create HTTP target tasks") grant it Service Account User on that account.
gcloud iam service-accounts add-iam-policy-binding $WEB_SA --project $PROJECT \
  --member serviceAccount:$TASKS_AGENT --role roles/iam.serviceAccountUser
```

The compute SA needs nothing. The web service doesn't grant it anything
either: the web checks its ID token itself (signature, audience = callback
URL, `email` = `COMPUTE_SA`).

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
gcloud run services update reliafy --project $PROJECT --region $REGION \
  --update-env-vars "COMPUTE_URL=$COMPUTE_URL,COMPUTE_QUEUE=$QUEUE,COMPUTE_CALLBACK_URL=$WEB_URL/internal/compute/callback,COMPUTE_INVOKER_SA=$WEB_SA,COMPUTE_SA=$COMPUTE_SA"
```

### 7. Verify

```sh
# Both services serve their latest revision (see the traffic-pin incident).
for s in reliafy reliafy-compute; do
  gcloud run services describe $s --region $REGION --project $PROJECT --format='value(status.traffic)'
done
# Expect latestRevision True, 100 percent, for each.

# Compute is private: anonymous calls are refused …
curl -s -o /dev/null -w '%{http_code}\n' $COMPUTE_URL/healthz            # 403
# … and an authorised one works (your account is project owner):
curl -s -H "Authorization: Bearer $(gcloud auth print-identity-token)" $COMPUTE_URL/healthz
# {"ok":true,"repyability_version":"0.10.1"}

# The callback refuses anything without the compute SA's token.
curl -s -o /dev/null -w '%{http_code}\n' -X POST -H 'Content-Type: application/json' \
  -d '{"job_id":"x","status":"done"}' $WEB_URL/internal/compute/callback  # 401

# Both run the same image digest.
for s in reliafy reliafy-compute; do
  r=$(gcloud run services describe $s --region $REGION --project $PROJECT --format='value(status.latestReadyRevisionName)')
  gcloud run revisions describe $r --region $REGION --project $PROJECT --format='value(status.imageDigest)'
done
```

End to end:
1. **Pro.** In the app as a Pro user, open a repairable diagram, change a
   parameter and Calculate. Expect "Queued — you're next…" or "Running the
   simulation…", then the result.
2. **Free.** As a free user, "Run quick simulation (free, ~3 s)" should show
   "Quick estimate", the replications run and the ± precision.
3. **Queue drained.** Check the queue is empty and compute logged the job:
   ```sh
   gcloud tasks list --queue reliafy-compute --location $REGION --project $PROJECT
   gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="reliafy-compute"' \
     --project $PROJECT --limit 20 --freshness 10m
   ```
4. **Logs.** In the web logs, look for "Rejected compute callback" (token or
   config wrong) and "Enqueue of job … failed" (IAM wrong).
5. **MCP.** On a Pro account, analyze_rbd on an unsaved-result repairable
   diagram either answers within 20 s or returns a `job_id`. Then get_job
   returns it.

### Rollback

Remove the queue setting. The web app goes back to running simulations
in-process (nothing else changes):

```sh
gcloud run services update reliafy --project $PROJECT --region $REGION --remove-env-vars COMPUTE_QUEUE
```

## Every future deploy: both services from one digest

1. Deploy the web service as now, from a clean worktree of `origin/main`:
   `gcloud run deploy reliafy --source . --region $REGION --project $PROJECT`.
2. Check its traffic is 100% on the latest revision (step 7's loop).
3. Deploy compute from the digest just built. `gcloud run deploy` with only
   `--image` keeps the service's command, args, account, limits and
   variables:
   ```sh
   REV=$(gcloud run services describe reliafy --region $REGION --project $PROJECT \
     --format='value(status.latestReadyRevisionName)')
   IMAGE=$(gcloud run revisions describe $REV --region $REGION --project $PROJECT \
     --format='value(status.imageDigest)')
   gcloud run deploy reliafy-compute --image "$IMAGE" --region $REGION --project $PROJECT
   ```
4. Run step 7's checks: traffic on both, and the same digest on both.

Between steps 1 and 3, compute runs the previous image for a minute. That's
harmless unless the release changes the request format in
`backend/services/compute_core.py`. In that case, deploy the web with
`--no-traffic`, deploy compute from the new digest, then
`gcloud run services update-traffic reliafy --to-latest`.

## Operating notes

- **Cold start.** Compute scales to zero. The first job after idle waits for
  the container (about 7 s) plus the worker processes' imports (a few
  seconds). The app shows it as "Running the simulation…".
- **Capacity.** One instance runs two jobs at a time. More are queued, and
  the app shows "Queued — N ahead of you…". Revisit `--max-instances` at the
  first paid user and again at 10 (Derryn, 3 Oct).
- **Jobs.** The `rbd_jobs` documents (with their results) are kept 7 days
  after they finish (`RBD_JOB_TTL_DAYS`), then removed by a TTL index. Free
  quick runs per user per day are in `free_sim_usage` (TTL as well).
- **Task size.** Cloud Tasks caps a task at 1 MB. A diagram too large for
  that is refused with a message; none is near it.
