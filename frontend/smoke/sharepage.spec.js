// Share pages and guides with sign-in off (tst, the self-hosted single-user
// app): a public link opens the shared page itself, never the workspace
// behind it, without "Create free account" (there are no accounts to make);
// a report shows every kind it can hold; and /guides opens the guides.
import { test, expect, open, expectHealthy } from "./health.js";

const CSV = ["hours,failed", ...[1830, 2210, 2620, 2980, 3390, 3910, 4380].map((h) => `${h},0`),
  "4500,1", "4500,1", "4500,1"].join("\n");

async function linkTo(request, collection, artifact_id) {
  const res = await request.post("/api/public-links", { data: { collection, artifact_id } });
  expect(res.ok(), `link: ${await res.text()}`).toBeTruthy();
  return (await res.json()).token;
}

let modelToken;
let reportToken;
test.beforeAll(async ({ request }) => {
  const res = await request.post("/api/models", {
    multipart: {
      name: "Smoke share — booster pump seals", distribution: "weibull", x: "hours", c: "failed", unit: "Hours",
      file: { name: "seals.csv", mimeType: "text/csv", buffer: Buffer.from(CSV) },
    },
  });
  expect(res.ok(), `fit: ${await res.text()}`).toBeTruthy();
  const model = await res.json();
  modelToken = await linkTo(request, "models", model.id);
  // smoke/seed.js saves a fault tree and a reliability prediction (no shared sample of either).
  const firstId = async (path, key) => (await (await request.get(path)).json())[key][0].id;
  const treeId = await firstId("/api/fault-trees", "fault_trees");
  const predictionId = await firstId("/api/predictions", "predictions");
  const report = await request.post("/api/reports", {
    data: {
      title: "Smoke share — November review", author: "Smoke test",
      sections: [
        { collection: "models", artifact_id: model.id, note: "The seals wear out." },
        { collection: "alt_models", artifact_id: "sample-alt-fluid" },
        { collection: "fault_trees", artifact_id: treeId },
        { collection: "reliability_predictions", artifact_id: predictionId },
      ],
    },
  });
  expect(report.ok(), `report: ${await report.text()}`).toBeTruthy();
  reportToken = await linkTo(request, "reports", (await report.json()).id);
});

const bare = async (page) => {
  // The share page only: no app menu, no account prompt, kept out of search.
  await expect(page.locator(".share-bar")).toBeVisible();
  await expect(page.locator(".sidebar, nav.side-nav, #main-content")).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Create free account" })).toHaveCount(0);
  await expect(page.locator('meta[name="robots"][content="noindex"]')).toHaveCount(1);
};

test("a shared model opens its page, answer first", async ({ page, problems }) => {
  await open(page, `/p/${modelToken}`);
  expect(new URL(page.url()).pathname).toBe(`/p/${modelToken}`);
  await expect(page.getByRole("heading", { name: "Smoke share — booster pump seals" })).toBeVisible();
  await expect(page.getByTestId("plain-answer")).toHaveText(/^One in ten is expected to have failed by about [\d,]+ hours/);
  await bare(page);
  await expectHealthy(page, problems, { label: "/p/<model>", root: "#root", chart: true });
});

test("a shared report opens with every kind it holds", async ({ page, problems }) => {
  await open(page, `/p/${reportToken}`);
  await expect(page.getByRole("heading", { name: "Smoke share — November review" })).toBeVisible();
  for (const kind of ["Non-repairable model", "Accelerated life model", "Fault tree", "Reliability prediction"]) {
    await expect(page.locator(".report-section-kind", { hasText: kind })).toBeVisible();
  }
  await expect(page.locator(".report-section .share-plain").first()).toHaveText(/^One in ten/);
  await expect(page.getByText(/the top event has a/i)).toBeVisible();
  await expect(page.getByText("This item is no longer available.")).toHaveCount(0);
  await bare(page);
  await expectHealthy(page, problems, { label: "/p/<report>", root: "#root" });
});

test("the guides open with sign-in off", async ({ page, problems }) => {
  await open(page, "/guides");
  expect(new URL(page.url()).pathname).toBe("/guides");
  await expect(page.getByRole("heading", { name: "How to do it in Reliafy" })).toBeVisible();
  await expectHealthy(page, problems, { label: "/guides", root: "#root" });
  await open(page, "/guides/share-your-work");
  expect(new URL(page.url()).pathname).toBe("/guides/share-your-work");
  await expect(page.locator(".guide-head h1, .guide h1").first()).toBeVisible();
  await expect(page.getByRole("link", { name: "Open the app" })).toBeVisible();
  await expectHealthy(page, problems, { label: "/guides/share-your-work", root: "#root" });
});
