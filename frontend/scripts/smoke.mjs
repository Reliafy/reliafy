// Browser smoke tests (#123), one command (run from frontend/):
//
//   npm run smoke                          build an auth-disabled frontend, start the
//                                          backend (smoke/serve.mjs), run the app suite
//   npm run smoke -- --headed              the same, watching the browser
//   npm run smoke -- --no-build            reuse the build already in frontend/dist
//   npm run smoke -- --base-url <url>      a deployed site instead, signed out and
//                                          read-only (or set SMOKE_BASE_URL)
//
// Anything else goes to `playwright test` (-g "/systems", --debug, --ui, a spec file).
// The backend runs on SMOKE_PORT (8765) with SMOKE_PYTHON (python3): a Python
// with the backend's requirements installed. The report: npx playwright show-report.
import { spawnSync } from "node:child_process";

const args = process.argv.slice(2);
const take = (flag) => {
  const i = args.indexOf(flag);
  if (i < 0) return false;
  const [, value] = args.splice(i, flag === "--base-url" ? 2 : 1);
  return value ?? true;
};
const baseUrl = take("--base-url") || process.env.SMOKE_BASE_URL;
const noBuild = take("--no-build");
const env = { ...process.env };
if (baseUrl) env.SMOKE_BASE_URL = baseUrl;

const run = (cmd, cmdArgs, extraEnv = {}) =>
  spawnSync(cmd, cmdArgs, { stdio: "inherit", env: { ...env, ...extraEnv }, shell: process.platform === "win32" });

if (!baseUrl && !noBuild) {
  // Single-user build: no sign-in, so every page is reachable.
  const build = run("npx", ["vite", "build", "--logLevel", "error"], { VITE_AUTH_DISABLED: "true" });
  if (build.status !== 0) process.exit(build.status ?? 1);
}
process.exit(run("npx", ["playwright", "test", ...args]).status ?? 1);
