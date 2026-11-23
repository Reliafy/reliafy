// Home reads everything it shows in one request (GET /api/home/summary), not
// one per list: on a slow server fourteen reads queued behind each other. One
// part failing shows that section's error, with Try again, and the rest draws.
import { test, expect, open, expectHealthy } from "./health.js";

// What Home used to read itself, each on its own (and the first-run check read
// the lists again for a workspace with nothing of its own).
const OLD_READS = [
  "/api/models", "/api/alt/models", "/api/recurrent/models", "/api/degradation/models", "/api/joint/models",
  "/api/datasets", "/api/rbds", "/api/fleet/fleets", "/api/fleet/tracked", "/api/strategy/analyses",
  "/api/changes", "/api/maintenance/overview", "/api/maintenance/rcm",
];

test("Home reads what it shows in one request", async ({ page, problems }) => {
  const reads = [];
  page.on("request", (req) => {
    const url = new URL(req.url());
    if (url.pathname.startsWith("/api/")) reads.push(url.pathname);
  });
  await open(page, "/");
  await expectHealthy(page, problems, { label: "/" });
  expect(reads.filter((p) => p === "/api/home/summary")).toHaveLength(1);
  expect(reads.filter((p) => OLD_READS.includes(p)), "Home reading a list on its own").toEqual([]);
  // The whole page: the deployment's settings, the frame's (one bootstrap), Home's
  // summary. Usage beacons (POST /api/metrics/event) aren't reads.
  const pageReads = reads.filter((p) => p !== "/api/metrics/event");
  expect(pageReads.sort(), "the page's reads").toEqual(["/api/config", "/api/home/summary", "/api/me/bootstrap"]);
  // The sections drawn from it.
  await expect(page.locator("[data-card='home-attention']")).toBeVisible();
});

test("a part of Home that fails shows its error and the rest still draws", async ({ page, problems }) => {
  await page.route("**/api/home/summary", async (route) => {
    const res = await route.fetch();
    const body = await res.json();
    delete body.sections.changes;
    body.errors = { ...body.errors, changes: "Couldn't load what changed." };
    await route.fulfill({ response: res, json: body });
  });
  await open(page, "/");
  await expect(page.getByText("Couldn't load what changed.")).toBeVisible();
  await expect(page.locator("[data-card='home-changes']").getByRole("button", { name: /try again/i })).toBeVisible();
  // "Needs attention" reads what changed too, so it says it couldn't load: never "Nothing needs you".
  await expect(page.getByText("Nothing needs you right now.")).toHaveCount(0);
  await expectHealthy(page, problems, { label: "/ with What changed failing" });
});
