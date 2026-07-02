# Contributing to Reliafy

Thanks for your interest! Bug reports, fixes, and features are all welcome.

## Dev setup

Backend (Python 3.11):

```
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt pytest
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

Please add or extend tests for behaviour you change. CI runs the backend test
suite and a frontend production build on every PR.

## Pull requests

- Branch from `main`; keep PRs focused on one change.
- Match the style of the surrounding code.
- Cloud-only code (billing, the metered assistant, Firebase auth) must stay
  **dormant by default**: it only activates via env configuration, and the
  open-source single-user experience must keep working with no env at all.

## Reporting security issues

Please don't open public issues for vulnerabilities — see
[SECURITY.md](SECURITY.md).
