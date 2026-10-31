// The server is running the code it should: routes that must exist, asked
// without signing in. With sign-in on, a signed-in route answers 401; a 404
// means the server doesn't have the route — an old build left serving (as on
// 15 Oct). In single-user mode (no sign-in) the route answers, so anything
// but the framework's own "no such route" will do.
//
// Add a route here when a release depends on it, newest first; a POST is sent
// with an empty JSON body, so nothing is created.
import { test, expect } from "@playwright/test";

const SIGNED_IN = [
  // The Explorer's "Add the sample truck" (once: smoke/seed.js added it, so this adds nothing).
  ["POST", "/api/maintenance/sample-truck"],
  // A dataset's measurements part (docs/datasets.md): add, paste, remove, split, life data for readings alone.
  ["PUT", "/api/datasets/smoke/measurements"],
  ["PUT", "/api/datasets/smoke/measurements/paste"],
  ["DELETE", "/api/datasets/smoke/measurements"],
  ["POST", "/api/datasets/smoke/split"],
  ["PUT", "/api/datasets/smoke/life"],
  ["POST", "/api/alt/models/smoke/diagnostics"], // the accelerated life page's Diagnostics checks
  ["GET", "/api/me/roles"], // what the user does: the menu's order and Home's cards
  ["GET", "/api/public-links"], // Reports: every shared link
  ["POST", "/api/maintenance/documents/upload"], // PDFs kept in maintenance
  ["GET", "/api/maintenance/documents/smoke/file"],
  ["POST", "/api/test-planning/sequential"], // Test planning
  ["POST", "/api/test-planning/life"],
  ["POST", "/api/test-planning/accelerated"],
  ["POST", "/api/test-planning/comparison"],
  ["POST", "/api/test-planning/simulate"],
  ["POST", "/api/strategy/calendar-replacement"], // replacement over a shutdown calendar
  ["POST", "/api/strategy/calendar-next"],
  ["POST", "/api/maintenance/photos/smoke/move"], // a photo on several places
  ["GET", "/api/maintenance/parts/levels"], // #435
  ["POST", "/api/maintenance/parts/import-bom"], // #435
  ["GET", "/api/maintenance/classes/forecast"], // #407
  ["POST", "/api/maintenance/graph/query"], // #423
  ["GET", "/api/maintenance/graph/schema"], // #423
  ["GET", "/api/maintenance/graph/design"], // the Data model page
  ["GET", "/api/maintenance/conditions"], // #428
  ["GET", "/api/maintenance/rcm"], // the RCM in the Explorer's tree
  ["GET", "/api/maintenance/positions/smoke/rcm"], // a position's RCM
  ["PUT", "/api/maintenance/failure-modes/smoke/decision"],
  ["GET", "/api/maintenance/tasks/smoke/measurement"], // what a task by use counts (its dialog, a move's question)
  ["GET", "/api/maintenance/overview"],
  ["GET", "/api/maintenance/tree"], // the asset tree pane
  ["GET", "/api/maintenance/places"], // Assets: the top-level places
  ["GET", "/api/maintenance/work-orders"],
  ["GET", "/api/rbd-runs"],
  ["POST", "/api/rbds/import"],
  ["GET", "/api/rbds"],
  ["GET", "/api/maintenance/rcm/options"], // the decision dialog's vocabulary
  ["GET", "/api/fleet/fleets"],
  ["GET", "/api/strategy/analyses"],
  ["GET", "/api/models"],
  ["GET", "/api/joint/models"],
  ["GET", "/api/datasets"],
  ["GET", "/api/me"],
  ["GET", "/api/v1/tools"], // every MCP tool action over REST
  ["POST", "/api/v1/list/models"],
  ["POST", "/api/v1/maintenance/photos"],
];

// Public: these answer anyone.
const PUBLIC = ["/api/health", "/api/config", "/api/distributions", "/api/v1/openapi.json"];

let auth;
test.beforeAll(async ({ request }) => {
  const res = await request.get("/api/config");
  expect(res.ok(), "/api/config").toBeTruthy();
  ({ auth } = await res.json());
});

test("deployed site has sign-in on", async () => {
  test.skip(!process.env.SMOKE_BASE_URL, "local runs are single-user");
  expect(auth).toBe(true);
});

test("public API routes answer", async ({ request }) => {
  for (const path of PUBLIC) {
    const res = await request.get(path);
    expect(res.status(), path).toBe(200);
  }
});

// The framework's own answer for a path or method it has no route for. (A
// route that exists but is switched off here says "Not found." instead.)
async function noRoute(res) {
  if (res.status() === 405) return true;
  if (res.status() !== 404) return false;
  return (await res.json().catch(() => ({}))).detail === "Not Found";
}

test("signed-in API routes exist", async ({ request }) => {
  const wrong = [];
  for (const [method, path] of SIGNED_IN) {
    const res = await request.fetch(path, { method, ...(method === "POST" ? { data: {} } : {}) });
    if (auth ? res.status() !== 401 : await noRoute(res)) wrong.push(`${method} ${path}: ${res.status()}`);
  }
  expect(wrong, auth ? "expected 401 (signed out) from each" : "expected each route to exist").toEqual([]);
});

test("an unknown API route is a 404", async ({ request }) => {
  // The control for the check above: the server does answer 404 for a route it lacks.
  const res = await request.get("/api/no-such-route-smoke");
  expect(res.status()).toBe(404);
  expect(await noRoute(res)).toBe(true);
});
