# Content pipeline runbook

The content plan (#343, calendar #344) runs with one human step a month: the
founder reviews and merges a pull request (#367). Everything after the merge
and the next deploy happens on its own, on its date.

**Status:** the code is in this branch. None of the setup below has been done
yet: no secret, no scheduler job, no settings, and the Zap still watches
`/whats-new/feed.xml`.

## How it fits together

```
 15th, 08:00 Brisbane          GitHub Actions: content-draft.yml
   calendar.yml + what shipped
   + library releases          ──► Claude Code drafts next month
                                   └─► one PR "Content for <Month>"
 founder reviews, edits, merges ──► approval of every item, email included
 deploy (before the first date) ──► content baked into the image

 on each item's date, 10:00 Brisbane (00:00 UTC), no rebuild:
   blog post / update page      served prerendered; joins /sitemap.xml
   /social/feed.xml item         ──► Zapier ──► Reliafy LinkedIn page
   What's new with send: auto    ──► Cloud Scheduler ──► /internal/content/run
                                     test copy Friday before, list on the day
 1st of the month, 10:00          the same job emails the content report
```

### What's in the repo

| What | Where | Notes |
|---|---|---|
| Calendar | `.github/content/calendar.yml` | Slots to Jan 2027: date, type, title. Tested by `backend/tests/test_content_calendar.py`. |
| Drafting instructions | `.github/content/draft-prompt.md` | What Claude reads and writes, the house style, the no-invented-figures rule. |
| Drafting job | `.github/workflows/content-draft.yml` | 15th and by hand. Gathers what shipped and the library releases for Claude, who has no network. |
| Blog posts | `frontend/src/content/blog/YYYY-MM-DD-<slug>.md` | Optional `linkedin: \|` block: the exact LinkedIn announcement. |
| What's new | `frontend/src/content/updates/YYYY-MM-DD-<slug>.md` | `send: auto` = the job emails it. Optional `linkedin: \|`. |
| Short LinkedIn posts | `frontend/src/content/social/YYYY-MM-DD-<slug>.md` | `date`, optional `link` (a Reliafy URL or site path) and `image`; the body is the post. Never on the website. |
| Feeds | `backend/routers/feeds.py`, `frontend/src/contentFeed.js` | Built into `dist/feeds.json`, served date-filtered. |
| Date gate | `backend/services/content_gate.py` | Prerendered pages and sitemap entries held until their date. |
| Scheduled job | `backend/services/content_jobs.py`, `backend/routers/content_jobs.py` | Auto-send and the monthly report. |
| Report | `backend/services/content_report.py` | Also on the admin page: "Content report (monthly)". |

A short post, a `linkedin:` block, a `send:` value and every committed content
file are checked by `frontend/src/contentFeed.test.js` (in CI).

### Library releases

Each batch announces new versions of SurPyval and RePyability, the
open-source libraries Reliafy is built on, on the Reliafy LinkedIn page. The
drafting job lists every version released in the last 45 days: GitHub
Releases (with their notes), and tags with no Release (SurPyval's older
releases), pointing to the library's changelog. For each library with a version
not yet announced, Claude drafts one short post,
`social/<date>-<library>-<version>.md` (`surpyval-0-24`), dated in the month,
ending "Release notes: <url>". A post for a version, or for a later one, means
it was announced, so the window's overlap doesn't post twice. The
`link` field takes only Reliafy pages, so the release notes are in the text.
Delete the file in review to skip a release.

### Pages and the sitemap

The build prerenders every blog post and update, future-dated ones too, and
lists them all in the sitemap. `dist/content.json` names each dated page with
its date. Until the date (UTC), the server answers the page's path exactly as
for an unknown path (the app shell, which says "Post not found") and
`/sitemap.xml` leaves it out. From 00:00 UTC (10:00 Brisbane) on the date,
search engines get the full HTML. `feeds.json`, `content.json` and the
prerendered files' own `/static/...` paths are never served.

### Feeds

| Feed | Contents | Who reads it |
|---|---|---|
| `/social/feed.xml` | Short posts, plus an announcement of each blog post and update (from 2026-10-12) on its date. Text = `linkedin:` or else title + summary. | **The LinkedIn Zap, and only it.** |
| `/blog/feed.xml` | Blog posts | RSS readers |
| `/whats-new/feed.xml` | Updates | RSS readers |

Every item enters its feed on its date (UTC), per request. A short post that
links to a page not live yet is held until that page is. Guids never change
(`/social/<file>`, `<page>#linkedin`, or the page URL), so Zapier doesn't
repost.

### Tags (UTM)

| Where | Tags |
|---|---|
| LinkedIn feed links | `utm_source=linkedin&utm_medium=social&utm_campaign=<slug>` (the short post's or the page's) |
| RSS feed links | `utm_source=rss&utm_medium=feed&utm_campaign=<slug>` |
| Update emails | `utm_source=email&utm_medium=update&utm_campaign=<update slug>` (#269; `medium=update` keeps the Email campaigns card's split from lifecycle emails) |
| Lifecycle emails | `utm_source=email&utm_medium=lifecycle&utm_campaign=welcome\|day3` |

Only links to reliafy.com are tagged; unsubscribe links never are. No URL
carries anything about a person.

### What's new auto-send

For an update with `send: auto`, dated D, `POST /internal/content/run`:

- from **10:00 Brisbane on the Friday before D** (caught up over the weekend if
  missed) sends one **test copy** to each operator address
  (`CONTENT_OPERATOR_EMAILS`, default `ADMIN_EMAILS`), subject starting
  `[Test]`, unsubscribe link inert;
- from **10:00 Brisbane on D**, for up to three days, sends it to the list
  through the same path as `backend/scripts/send_update.py`: the
  `update_sends` log (one row per update and user), opt-outs, test domains,
  and `UPDATE_EMAIL_EXCLUDE`. A run sends for at most `UPDATE_AUTO_SECONDS`
  (240 s), half a second apart, then stops; the next run continues. When a
  run finishes with nothing failed the update is marked done and never sent
  again, so later sign-ups don't get it. A Pushover note follows each send.

It refuses (HTTP 503) when SMTP isn't configured, and does nothing for updates
while `UPDATE_AUTO_SEND` isn't `true`. Each step is claimed in the
`content_jobs` collection (`update-test:<slug>`, `update-send:<slug>`) with a
30-minute lease, so overlapping calls can't both send. `?dry_run=true` reports
what it would do and sends and records nothing.

The CLI still works for a manual send. It shares the send log, so the two
never email anyone twice.

### Monthly report

From 10:00 Brisbane on the 1st (caught up to the 7th), the job emails the
operators last month's report, once (`report:<YYYY-MM>`): views and visitors
per blog post and update, tagged landings by source and campaign, sign-ups
(attributed to the tagged link and the first post their visit saw before
signing up, by the daily visitor hash), update emails sent, and
unsubscribes. The admin page shows the same tables for any of the last four
months. Analytics are kept 90 days.

## One-time setup

Run the gcloud blocks in one shell, in order.

### 0. Variables

```sh
PROJECT=reliafy-app
REGION=australia-southeast1
WEB_URL=$(gcloud run services describe reliafy --region "$REGION" --project "$PROJECT" \
  --format='value(status.url)')
RUN_URL=$WEB_URL/internal/content/run
CRON_SA=reliafy-content-cron@$PROJECT.iam.gserviceaccount.com
printf '%s\n' "endpoint: $RUN_URL" "scheduler SA: $CRON_SA"
```

`RUN_URL` must be the `https://…run.app/internal/content/run` URL.

### 1. The `ANTHROPIC_API_KEY` repository secret (founder)

The drafting job's only secret. Create a key in the Anthropic Console (a
workspace with a monthly spend limit of about US$25 is a sensible cap), then:

```sh
gh secret set ANTHROPIC_API_KEY -R Reliafy/reliafy   # paste the key when asked
```

Then run the job once by hand: Actions → Content draft → Run workflow (leave
the month empty for next month). Expect a pull request "Content for <Month>"
in 15-40 minutes.

Pull requests opened with the workflow's token don't start CI. To run CI on
the drafts, push any commit to the branch or close and reopen the PR.

### 2. The scheduler's service account

No roles; it only signs the token the service checks.

```sh
gcloud iam service-accounts create reliafy-content-cron --project "$PROJECT" \
  --display-name "Reliafy content pipeline (Cloud Scheduler)"
gcloud iam service-accounts add-iam-policy-binding "$CRON_SA" --project "$PROJECT" \
  --member "user:$(gcloud config get-value account)" --role roles/iam.serviceAccountUser
```

### 3. Settings on the web service

`UPDATE_EMAIL_EXCLUDE` is comma-separated, so this uses `;` as gcloud's
delimiter between variables (`^;^`; not `@`, which the service account and
addresses contain). Put the real addresses in place of the placeholders; never
commit them.

```sh
gcloud run services update reliafy --project "$PROJECT" --region "$REGION" \
  --update-env-vars "^;^CONTENT_CRON_AUDIENCE=$RUN_URL;CONTENT_CRON_SA=$CRON_SA;UPDATE_EMAIL_EXCLUDE=<address>,<address>"
```

| Variable | Value |
|---|---|
| `CONTENT_CRON_AUDIENCE` | `RUN_URL`. Unset: the endpoint refuses every call (401). |
| `CONTENT_CRON_SA` | The scheduler's service account. Unset: 401. |
| `UPDATE_EMAIL_EXCLUDE` | Addresses the automatic send skips, comma-separated. |
| `UPDATE_AUTO_SEND` | `true` to send `send: auto` updates. Default off: step 5. |
| `CONTENT_OPERATOR_EMAILS` | Optional: who gets test copies and the report. Default `ADMIN_EMAILS`. |
| `UPDATE_AUTO_SECONDS` | Optional: seconds one run may send for. Default 240. |

SMTP (`SMTP_HOST`, `EMAIL_FROM`, …) and Pushover are already configured.
Check traffic follows the new revision:

```sh
gcloud run services describe reliafy --region "$REGION" --project "$PROJECT" \
  --format='value(status.traffic)'   # latestRevision True, 100 percent
gcloud run services describe reliafy --region "$REGION" --project "$PROJECT" \
  --format='value(spec.template.spec.timeoutSeconds)'   # should be 300 or more
```

### 4. The Cloud Scheduler job

Hourly from 10:05 to 17:05 Brisbane, every day: the first run does the day's
work, the rest retry a failure or continue a long send. Repeat calls are
harmless.

```sh
gcloud scheduler jobs create http reliafy-content-run \
  --project "$PROJECT" --location "$REGION" \
  --schedule "5 10-17 * * *" --time-zone "Australia/Brisbane" \
  --uri "$RUN_URL" --http-method POST \
  --oidc-service-account-email "$CRON_SA" --oidc-token-audience "$RUN_URL" \
  --attempt-deadline 600s \
  --description "Reliafy content pipeline: What's new auto-send, monthly report (#367)"
```

Check it:

```sh
curl -s -o /dev/null -w '%{http_code}\n' -X POST "$RUN_URL"   # 401: anonymous calls refused
# A dry run as the scheduler (needs roles/iam.serviceAccountTokenCreator on the SA):
TOKEN=$(gcloud auth print-identity-token --impersonate-service-account "$CRON_SA" --audiences "$RUN_URL")
curl -s -X POST -H "Authorization: Bearer $TOKEN" "$RUN_URL?dry_run=true"
gcloud scheduler jobs run reliafy-content-run --project "$PROJECT" --location "$REGION"
```

### 5. Switch the auto-send on

After the first drafted What's new is merged and deployed:

```sh
gcloud run services update reliafy --project "$PROJECT" --region "$REGION" \
  --update-env-vars "UPDATE_AUTO_SEND=true"
```

Check traffic follows the new revision, as in step 3.

### 6. Point the LinkedIn Zap at `/social/feed.xml`

In Zapier, open the RSS → LinkedIn Company Update Zap:

1. Trigger (RSS by Zapier, New Item in Feed): change the feed URL from
   `https://reliafy.com/whats-new/feed.xml` to
   `https://reliafy.com/social/feed.xml`.
2. Action (LinkedIn, Create Company Update): map the post text to the item's
   **Description** and the link to its **Link**. Don't add the title: the
   description already holds the whole post.
3. Publish. Zapier normally treats the items already in the feed when the
   Zap is published as seen; check the Zap's history after its first poll.

Keep `/whats-new/feed.xml` and `/blog/feed.xml` as they are, for RSS readers.
Announcements start on 12 Oct 2026; earlier posts went out through the old
feed and aren't in the new one. Switch before 2 Nov, so November's What's
new is posted once, from the new feed.

## Approving a month

1. The PR "Content for <Month>" arrives around the 15th with a checklist:
   one box per item, every `[CHECK: …]` figure, the topic chosen for any
   "to be chosen" slot.
2. Edit on the branch: wording, dates, `linkedin:` text, short posts. Resolve
   every `[CHECK: …]`. Delete anything you don't want.
3. **Merge = approval.** Every item then goes out on its date, the What's new
   email included.
4. **Deploy** before the month's first date. Content is baked into the image:
   an item that isn't deployed by its date goes out at the next deploy (its
   page and feed item), and an email isn't sent at all if the deploy comes more
   than three days after its date.
5. On the Friday before the What's new, read the test copy. To stop it, see
   below.

## Stopping it

| To stop | Do |
|---|---|
| One post, page or short post | Before its date: delete or re-date the file, merge, deploy. |
| One What's new email | Remove `send: auto` from the update, merge, deploy. Or, at once: `UPDATE_AUTO_SEND=false` (below). |
| All automatic emails, at once | `gcloud run services update reliafy --project "$PROJECT" --region "$REGION" --update-env-vars UPDATE_AUTO_SEND=false` |
| The scheduled job (emails and report) | `gcloud scheduler jobs pause reliafy-content-run --project "$PROJECT" --location "$REGION"` (`resume` to restart) |
| LinkedIn posting | Turn the Zap off in Zapier. |
| Monthly drafting | `gh workflow disable content-draft.yml -R Reliafy/reliafy`, or delete the `ANTHROPIC_API_KEY` secret. |

A send already running finishes its current run (at most `UPDATE_AUTO_SECONDS`).

## Operating notes

- **What the job did:** Cloud Logging, logger `backend.services.content_jobs`
  (one line per step), and the `content_jobs` collection: `status` is
  `running`, `done`, `partial` or `failed`, with counts. Recipients are in
  `update_sends`, as for the CLI.
- **A partial send** (failures or out of time) is continued by the next
  hourly run, for up to three days after the date.
- **Cost:** the drafting run uses the Anthropic API, roughly US$5-20 a month.
  The scheduler job and the extra requests cost cents.
