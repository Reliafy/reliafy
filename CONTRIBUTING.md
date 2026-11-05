# Contributing to Reliafy

Thanks for your interest! Bug reports, fixes, and features are all welcome.

## Dev setup

Backend (Python 3.11):

```
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt pytest pillow-heif
AUTH_DISABLED=true uvicorn backend.main:app --port 8000 --reload
```

Frontend (Node 22):

```
cd frontend
npm install
npm run dev   # hot reload, proxies /api to :8000
```

`AUTH_DISABLED=true` (backend) and `VITE_AUTH_DISABLED=true` (already set in
`frontend/.env.development`) run everything in single-user mode with zero
external services — no Firebase, no MongoDB (an in-memory simulator is used),
no keys.

## Tests

```
pytest backend/tests
```

Please add or extend tests for behaviour you change, and run them locally
before opening a PR. CI (the backend suite, the frontend build and tests, and
the browser smoke suite) runs on the `dev` → `main` release PR.

### Browser smoke tests

`frontend/smoke` opens every page of the app in a browser (Playwright) and
fails on a crash ("Something went wrong"), an uncaught error, a console error,
a missing chart, or a route that bounces elsewhere. Pages are found from the
router (`AppShell.jsx`, `App.jsx`), so a new page is covered automatically; a
new page with an id (`/things/:id`) needs one line in `DETAIL_IDS`
(`frontend/smoke/routes.js`) saying which API lists its ids.

```
cd frontend
npx playwright install chromium                  # once
SMOKE_PYTHON=../venv/bin/python npm run smoke    # build, start the backend, run
npm run smoke -- --headed -g "/systems"          # watch one part
npm run smoke -- --base-url https://reliafy.com  # a deployed site, signed out
```

The local run builds an auth-disabled frontend into `frontend/dist`, starts the
backend from `SMOKE_PYTHON` on port 8765 (`SMOKE_PORT`) with the samples
seeded, and adds a few Maintenance records and an RBD run through the API.
`--no-build` reuses the last build; `node smoke/serve.mjs` starts the same
backend on its own. The BlockSim import test needs ReliaSoft's examples
(`python backend/scripts/fetch_rbd_import_fixtures.py`) and skips without them.

With `--base-url` (or `SMOKE_BASE_URL`) the run is read-only: the public pages
(one of each kind from the sitemap), the sign-in gate, and the API's routes
(`frontend/smoke/api.spec.js`: a signed-out request must get 401, not 404 —
add a route there when a release depends on it). The page's own analytics and
error reports are not sent. `SMOKE_SHARE_TOKEN` adds a check of a real share
link.

## Pull requests

- Branch from `dev` and open PRs into `dev`; keep PRs focused on one change.
- Match the style of the surrounding code.
- Cloud-only code (billing, the metered assistant, Firebase auth) must stay
  **dormant by default**: it only activates via env configuration, and the
  open-source single-user experience must keep working with no env at all.

## Reporting security issues

Please don't open public issues for vulnerabilities — see
[SECURITY.md](SECURITY.md).
