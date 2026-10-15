// The backend the smoke tests run against (#123): single-user mode serving the
// built frontend (frontend/dist, an auth-disabled build), the in-memory
// database simulator with the samples seeded, and Maintenance on, its log in
// that same in-memory database so every start is fresh.
//
// The environment is built from scratch, so nothing from the shell (a real
// MONGODB_URI, mail or payment keys) reaches this server.
//
//   node smoke/serve.mjs            # from frontend/; SMOKE_PORT (8765), SMOKE_PYTHON (python3)
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

const repo = fileURLToPath(new URL("../..", import.meta.url));
const port = process.env.SMOKE_PORT || "8765";
const python = process.env.SMOKE_PYTHON || "python3";

const keep = ["PATH", "HOME", "LANG", "TMPDIR", "SYSTEMROOT", "VIRTUAL_ENV"];
const env = Object.fromEntries(keep.filter((k) => process.env[k]).map((k) => [k, process.env[k]]));
Object.assign(env, {
  AUTH_DISABLED: "true",
  MAINTENANCE_ENABLED: "true",
  MAINTENANCE_STORE: "mongo",
  // The single-user mode's fixed user, made an operator so /admin is tested too.
  ADMIN_EMAILS: "dev@local",
  PUSH_ERROR_ALERTS: "false",
  MPLBACKEND: "Agg",
  PYTHONUNBUFFERED: "1",
});

// A long keep-alive: with uvicorn's 5 s default, a test reusing an idle
// connection can meet the server closing it (ECONNRESET).
const uvicorn = ["-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", port, "--timeout-keep-alive", "120"];
const server = spawn(python, uvicorn, {
  cwd: repo,
  env,
  stdio: "inherit",
});
server.on("exit", (code) => process.exit(code ?? 1));
for (const signal of ["SIGINT", "SIGTERM"]) process.on(signal, () => server.kill(signal));
