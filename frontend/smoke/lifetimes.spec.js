// A dataset's Lifetimes view: one line per unit, read the way a fit reads the
// dataset. A status column read the wrong way round shows at a glance (every
// unit failed), and Change redraws the lines with the change before it's saved.
import { test, expect, open, expectHealthy } from "./health.js";

const SHEET = ["Tag,Hours,Failed", ...Array.from({ length: 12 }, (_, k) => `U-${k + 1},${(k + 1) * 100},${k % 3 === 0 ? 0 : 1}`)]
  .join("\n") + "\n";

test("the dataset page draws each unit's lifetime, and Change redraws it", async ({ page, problems, request }) => {
  // Saved with the 0/1 column read as SurPyval reads it (0 = failed): 4 failed, 8 still running.
  const res = await request.post("/api/datasets/paste", {
    data: { name: "Lifetimes smoke", content: SHEET, reading: { x: "Hours", c: "Failed", i: "", unit: "Hours", not_used: ["Tag"] } },
  });
  expect(res.ok()).toBeTruthy();
  const { id } = await res.json();
  await open(page, `/data/${id}`);
  const view = page.getByRole("region", { name: "Lifetimes" });
  await expect(view.getByTestId("lifetimes-summary")).toHaveText("12 units: 4 failed, 8 still running");
  await expect(view.locator(".js-plotly-plot")).toBeVisible();
  await expectHealthy(page, problems, { label: "lifetimes" });

  // Change opens the reading's editor; the view says it's drawn with the change.
  await view.getByRole("button", { name: "Change how it's read" }).click();
  await expect(page.getByRole("region", { name: "Change how the columns are read" })).toBeVisible();
  await expect(view.getByText("With your changes, not saved yet:")).toBeVisible();

  // Many units: an even sample, with Show all.
  const many = ["Hours,Failed", ...Array.from({ length: 450 }, (_, k) => `${k + 1},${k % 2}`)].join("\n") + "\n";
  const big = await (await request.post("/api/datasets/paste", {
    data: { name: "Lifetimes many", content: many, reading: { x: "Hours", c: "Failed", unit: "Hours" } },
  })).json();
  await open(page, `/data/${big.id}`);
  const v2 = page.getByRole("region", { name: "Lifetimes" });
  await expect(v2.getByText(/Showing 200 of 450 lines/)).toBeVisible();
  await v2.getByRole("button", { name: "Show all" }).click();
  await expect(v2.getByRole("button", { name: "Show a sample" })).toBeVisible();
  await expectHealthy(page, problems, { label: "lifetimes, all lines" });
});

test("a repairable dataset draws one line per system with its failures", async ({ page, problems }) => {
  await open(page, "/data/sample-ds-compressor-events");
  const view = page.getByRole("region", { name: "Lifetimes" });
  await expect(view.getByTestId("lifetimes-summary")).toHaveText("4 systems · 30 failures");
  await expectHealthy(page, problems, { label: "repairable lifetimes" });
});
