# Deploy behaviour: open tabs and new builds

Each image build has one build id. The Dockerfile bakes it into the frontend
(`VITE_BUILD_ID`, a timestamp and random suffix unless `--build-arg BUILD_ID=<git sha>`
is passed) and writes it to `frontend/dist/build-id.txt`. The server sends it as
`X-Reliafy-Build` on every `/api/*` response and in `/api/health` (`build`).
`RELIAFY_BUILD_ID` overrides the file. With no id (local dev, tst, a plain
`npm run build`) no header is sent and the browser check is off.

In the browser, `frontend/src/buildCheck.js` compares the header with the bundle's id
(`api.js` reports each response). On a mismatch:

- nothing unsaved: the page reloads at the next route change (never mid-request or
  mid-typing);
- unsaved work (`useUnsavedSignal` / `useUnsavedRef`: the Explorer panes, the RBD
  builder, the operating context draft): a slim bar offers Reload;
- a reload is remembered per build id in `sessionStorage`, so a stale cache can't loop.

New screens with editable drafts should call `useUnsavedSignal(key, dirty)`.
The bar reuses the existing banner style (`verify-banner`).
