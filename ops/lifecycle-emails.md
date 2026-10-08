# Lifecycle emails runbook (welcome + day 3)

Two emails to new accounts (#272), both **off until `LIFECYCLE_EMAILS=true`**:

- **Welcome**: sent on a new account's first sign-in with a verified email
  (`backend/auth.py` `upsert_user`). Google sign-ins are verified straight
  away. Email/password accounts are verified once the user follows Firebase's
  link, so their welcome goes on the first sign-in after that. Accounts more
  than 3 days old never get one, so switching the feature on doesn't greet
  everyone who signs in that week. No scheduler needed.
- **Day 3**: a daily run sends it to verified accounts 3 to 7 days old. The run
  is `POST /internal/lifecycle/day3`, called by Cloud Scheduler with an OIDC
  token.

Both emails respect the product-update opt-out and its one-click unsubscribe,
skip test domains (`example.com`, `reliafy.test`, `local`), and go to each
user at most once. The send log is the `lifecycle_emails` collection, with
`_id` = `<kind>:<uid>`. A failed send is retried, up to 3 attempts in all.
Links carry `utm_source=email&utm_medium=lifecycle&utm_campaign=welcome|day3`.
The operator dashboard's "Email campaigns" card shows what each email brought
in. The copy is in `backend/services/lifecycle_emails.py`.

**Status:** none of the resources below exist yet. Nothing here has been run.

## Settings (web service `reliafy`)

| Variable | Value |
|---|---|
| `LIFECYCLE_EMAILS` | `true` to send. Unset or `false` (the default) sends nothing; the day-3 endpoint still answers, with `"enabled": false`. |
| `LIFECYCLE_CRON_AUDIENCE` | The endpoint's run.app URL, `https://…run.app/internal/lifecycle/day3`. This is the audience of the scheduler's OIDC token. |
| `LIFECYCLE_CRON_SA` | The scheduler's service account, the only identity the endpoint accepts. |

With either of the last two unset, the endpoint answers 401 to every call.
SMTP (`SMTP_HOST`, `EMAIL_FROM`, …) must be configured too, or nothing is sent.
The emails go out from `EMAIL_FROM`'s address with the display name
"Derryn at Reliafy", and Reply-To is `hello@reliafy.com`.

## One-time setup

Run each block in the same zsh/bash shell, in order. Step 0 sets the
variables that the later blocks use.

### 0. Variables for this shell

```sh
PROJECT=reliafy-app
REGION=australia-southeast1
WEB_URL=$(gcloud run services describe reliafy --region "$REGION" --project "$PROJECT" \
  --format='value(status.url)')
DAY3_URL=$WEB_URL/internal/lifecycle/day3
CRON_SA=reliafy-lifecycle-cron@$PROJECT.iam.gserviceaccount.com

printf '%s\n' "endpoint: $DAY3_URL" "scheduler SA: $CRON_SA"
```

The endpoint must be an `https://…run.app/internal/lifecycle/day3` URL.

### 1. The scheduler's service account

The account has no roles. It only exists to sign the token the web service
checks.

```sh
gcloud iam service-accounts create reliafy-lifecycle-cron --project "$PROJECT" \
  --display-name "Reliafy lifecycle emails (Cloud Scheduler)"

# Whoever creates the job must be able to act as the account.
gcloud iam service-accounts add-iam-policy-binding "$CRON_SA" --project "$PROJECT" \
  --member "user:$(gcloud config get-value account)" --role roles/iam.serviceAccountUser
```

### 2. Tell the web service who may call it (still sending nothing)

```sh
gcloud run services update reliafy --project "$PROJECT" --region "$REGION" \
  --update-env-vars "LIFECYCLE_CRON_AUDIENCE=$DAY3_URL,LIFECYCLE_CRON_SA=$CRON_SA"
```

This makes a new revision. Check that traffic follows it:

```sh
gcloud run services describe reliafy --region "$REGION" --project "$PROJECT" --format='value(status.traffic)'
# Expect latestRevision True, 100 percent.
```

### 3. The Cloud Scheduler job

The job runs daily at 10:00 Brisbane time. It is safe to run more often: the
send log makes every email once-only.

```sh
gcloud scheduler jobs create http reliafy-lifecycle-day3 \
  --project "$PROJECT" --location "$REGION" \
  --schedule "0 10 * * *" --time-zone "Australia/Brisbane" \
  --uri "$DAY3_URL" --http-method POST \
  --oidc-service-account-email "$CRON_SA" --oidc-token-audience "$DAY3_URL" \
  --attempt-deadline 300s \
  --description "Reliafy day-3 lifecycle email (#272)"
```

Run it once by hand. With `LIFECYCLE_EMAILS` still off, it should log a 200
with `"enabled": false`:

```sh
gcloud scheduler jobs run reliafy-lifecycle-day3 --project "$PROJECT" --location "$REGION"
# An anonymous call is refused:
curl -s -o /dev/null -w '%{http_code}\n' -X POST "$DAY3_URL"   # 401
```

### 4. Switch the emails on (after Derryn approves the copy)

```sh
gcloud run services update reliafy --project "$PROJECT" --region "$REGION" \
  --update-env-vars "LIFECYCLE_EMAILS=true"
```

Check that traffic follows the new revision, as in step 2.

## Operating notes

- **Turn them off:** `--update-env-vars LIFECYCLE_EMAILS=false`. The scheduler
  can keep running; it sends nothing.
- **Pause the day-3 run only:**
  `gcloud scheduler jobs pause reliafy-lifecycle-day3 --project "$PROJECT" --location "$REGION"`.
- **What was sent:** the `lifecycle_emails` collection (`status` is `sent`,
  `failed` or `sending`, plus `attempts`, `error`, `sent_at`, and `variant` for
  day 3: `start` if nothing was saved yet, `further` otherwise). A row stuck on
  `sending` was claimed but never reported back. It is not retried, so the
  email goes at most once.
- **Day-3 window:** accounts 3 to 7 days old, so a missed day is caught up.
  Each run sends at most 200, half a second apart, and stops after 5 failures
  in a row.
