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
  ["GET", "/api/extensions"], // optional extensions' pages (an empty list without any)
  // RCM studies (the standalone worksheets under Maintenance).
  ["GET", "/api/rcm/studies"],
  // The interval calculators on an RCM task card.
  ["POST", "/api/maintenance/rcm/interval/on-condition"],
  ["POST", "/api/maintenance/rcm/interval/failure-finding"],
  // Life models on positions (the Explorer's Modelling tab).
  ["GET", "/api/maintenance/position-models"],
  // Field reports (notes, photos and sound from the field).
  ["GET", "/api/maintenance/captures"],
  // The data library as models and priors (Models › Library).
  ["POST", "/api/models/from-library"],
  ["GET", "/api/library/used"],
  ["POST", "/api/models/fit-with-prior"],
  // How the Data step reads inspection rows before a fit.
  ["POST", "/api/data-reading"],
  // Reliability prediction: the parts count, the saved predictions, a product's parts list.
  ["POST", "/api/predictions/compute"],
  ["POST", "/api/predictions"],
  ["GET", "/api/predictions"],
  ["GET", "/api/predictions/smoke"],
  ["GET", "/api/predictions/from-product/smoke"],
  ["POST", "/api/v1/analyse/prediction"],
  // A device that works offline: its queued changes pushed in a batch, and a queued photo.
  ["POST", "/api/v1/maintenance/sync/push"],
  ["POST", "/api/v1/maintenance/sync/photo"],
  ["POST", "/api/v1/maintenance/sync/pack"],
  // Maintainability prediction: the calculator, the saved predictions, a product's lines.
  ["POST", "/api/maintainability/analyse"],
  ["GET", "/api/maintainability/predictions"],
  ["GET", "/api/maintainability/products/smoke/lines"],
  // "Add the Survey quadcopter" (Products; the Explorer's "Open the Survey quadcopter").
  ["POST", "/api/maintenance/sample-product"],
  // A dataset's measurements part (docs/datasets.md): add, paste, remove, split, life data for readings alone.
  ["PUT", "/api/datasets/smoke/measurements"],
  ["PUT", "/api/datasets/smoke/measurements/paste"],
  ["DELETE", "/api/datasets/smoke/measurements"],
  ["POST", "/api/datasets/smoke/split"],
  ["PUT", "/api/datasets/smoke/life"],
  ["POST", "/api/alt/models/smoke/diagnostics"], // the accelerated life page's Diagnostics checks
  ["GET", "/api/me/roles"], // what the user does: the menu's order and Home's cards
  ["GET", "/api/v1/support/replies"], // operator support replies (mounted before the generic /api/v1 routes)
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
  ["POST", "/api/rbd-jobs/smoke/cancel"], // cancel a long calculation
  ["GET", "/api/fault-trees"], // System models › Fault trees
  ["POST", "/api/fault-trees/analyse"],
  ["POST", "/api/maintenance/photos/smoke/move"], // a photo on several places
  ["GET", "/api/maintenance/parts/levels"], // #435
  ["POST", "/api/maintenance/parts/import-bom"], // #435
  ["GET", "/api/maintenance/classes/forecast"], // #407
  ["GET", "/api/maintenance/item-classes/smoke/fleet"], // the Explorer by Classes: a class's positions with risk now
  ["GET", "/api/maintenance/positions/smoke/condition"], // a position's Condition monitoring tab: its risk now
  ["POST", "/api/maintenance/graph/query"], // #423
  ["GET", "/api/maintenance/graph/schema"], // #423
  ["GET", "/api/maintenance/graph/design"], // the Data model page
  ["GET", "/api/maintenance/conditions"], // #428
  ["GET", "/api/maintenance/rcm"], // the RCM in the Explorer's tree
  ["GET", "/api/maintenance/positions/smoke/rcm"], // a position's RCM
  ["GET", "/api/maintenance/failure-reports"], // the Explorer's Failure reports tab
  ["POST", "/api/maintenance/failure-reports"],
  // Products: design trees and the items built from them (the Products and Items pages).
  ["GET", "/api/maintenance/products"],
  ["POST", "/api/maintenance/products"],
  ["GET", "/api/maintenance/products/smoke"],
  ["GET", "/api/maintenance/products/smoke/items"],
  ["POST", "/api/maintenance/products/smoke/build"],
  ["DELETE", "/api/maintenance/products/smoke/design"],
  ["PUT", "/api/maintenance/positions/smoke/design"],
  ["GET", "/api/maintenance/positions/smoke/design-rollup"],
  ["GET", "/api/maintenance/items/overview"],
  ["PUT", "/api/maintenance/failure-modes/smoke/decision"],
  ["GET", "/api/maintenance/tasks/smoke/measurement"], // what a task by use counts (its dialog, a move's question)
  ["GET", "/api/maintenance/overview"],
  ["GET", "/api/maintenance/tree"], // the asset tree pane
  ["GET", "/api/maintenance/places"], // Assets: the top-level places
  ["GET", "/api/maintenance/work-orders"],
  ["GET", "/api/maintenance/due"], // Maintenance › Orders › Due soon, by window
  ["GET", "/api/maintenance/packages"], // work packages: tasks done on one visit
  ["GET", "/api/maintenance/packages/propose"],
  ["GET", "/api/maintenance/tasks/smoke/lsa"], // a task's LSA (what it needs to be done)
  ["GET", "/api/maintenance/packages/smoke"],
  ["POST", "/api/maintenance/packages"],
  ["PATCH", "/api/maintenance/packages/smoke"],
  ["POST", "/api/maintenance/packages/smoke/tasks"],
  ["DELETE", "/api/maintenance/packages/smoke/tasks/smoke"],
  ["POST", "/api/maintenance/packages/smoke/pause"],
  ["POST", "/api/maintenance/positions/smoke/out-of-service"], // tasks not due while it's out of service
  ["POST", "/api/maintenance/items/smoke/back-in-service"],
  ["PUT", "/api/maintenance/work-orders/smoke/lines/smoke"], // a package line's mark, saved during the visit
  ["POST", "/api/maintenance/work-orders/smoke/readings"], // readings and settings taken at a work order, recorded now
  ["GET", "/api/rbd-runs"],
  ["POST", "/api/rbds/import"],
  ["GET", "/api/rbds"],
  // Covariates fixed at a position, the rest set on RBD blocks (covariate_binding.py).
  ["POST", "/api/rbds/binding-inputs"],
  ["POST", "/api/rbds/bound-blocks"],
  // Missions on an RBD and on positions (rbd_missions.py).
  ["GET", "/api/maintenance/position-missions"],
  ["POST", "/api/maintenance/positions/x/missions"],
  ["GET", "/api/rbds/x/missions"],
  ["POST", "/api/rbds/x/missions"],
  ["GET", "/api/rbds/x/missions/m"],
  ["POST", "/api/rbds/x/missions/m/calculate"],
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

// Without extensions the app has no operator page: an old /admin link is the
// server's ordinary 404 page. (Signed in, single-user runs only: a deployed
// site answers /api/extensions with 401 here.)
test("without extensions, /admin is a not-found page", async ({ request }) => {
  const res = await request.get("/api/extensions");
  test.skip(res.status() !== 200, "needs a signed-in (single-user) run");
  const { mounts } = await res.json();
  test.skip(mounts.length > 0, "an extension is installed");
  const page = await request.get("/admin");
  expect(page.status()).toBe(404);
  expect(await page.text()).toContain("Page not found");
  expect((await request.get("/api/admin/stats")).status()).toBe(404);
});
