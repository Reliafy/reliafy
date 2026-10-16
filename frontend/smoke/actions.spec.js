// The main path through the app: fit a model to a sample dataset and save it.
// (Calculating an RBD is in rbd.spec.js.)
import { test, expect, open, expectHealthy } from "./health.js";

test("fit and save a Weibull model from a sample dataset", async ({ page, problems }) => {
  await open(page, "/datasets/d/sample-ds-bearings");
  await page.getByRole("button", { name: "Fit a model" }).click();
  await expect(page).toHaveURL(/\/modelling\/new\?dataset=sample-ds-bearings/);
  await page.getByRole("button", { name: "Next" }).click();
  await page.getByRole("button", { name: "Fit Weibull" }).click();
  await expect(page.getByText("Shape β").first()).toBeVisible({ timeout: 30_000 });
  await expectHealthy(page, problems, { label: "fitted model", chart: true });

  await page.getByRole("button", { name: "Save model" }).click();
  await page.waitForURL(/\/modelling\/m\/[0-9a-f]{32}$/, { timeout: 30_000 });
  await expect(page.getByRole("heading", { name: /Weibull/ })).toBeVisible();
  await expectHealthy(page, problems, { label: "saved model", chart: true });
});

// #31: a class with a fitted model and a spare with a lead time shows how many to
// hold, and the chance a typed stock runs out (smoke/seed.js makes the class).
test("a class's spares stock levels and the what-if", async ({ page, problems }) => {
  await open(page, `/maintenance/classes/${encodeURIComponent("Smoke test pump")}`);
  const stocking = page.getByTestId("spares-stocking");
  await expect(stocking.getByRole("heading", { name: "Stock to hold" })).toBeVisible({ timeout: 30_000 });
  const row = stocking.getByRole("row", { name: /SMOKE-PUMP/ });
  await expect(row).toContainText("60 days lead time at 95%");
  await expect(page.getByTestId("spares-summary")).toContainText(/^Hold \d+: a 95% chance of no stock-out/);
  await page.getByLabel("If we hold").fill("0");
  await expect(page.getByTestId("spares-whatif")).toContainText("chance of running out over the lead time");
  await stocking.getByLabel("Service level").selectOption("0.99");
  await expect(row).toContainText("at 99%");
  await expectHealthy(page, problems, { label: "class stock levels", chart: true });
});

// #434, the first run: a CSV saved without a header row. Its first row is
// all numbers, so it's read as data (col 1, col 2) and said so; the column of
// decimals can't be made the count; the fit is saved, with its data, in one
// click.
const HEADERLESS = [
  "300,544966.3125", "410,612000.5", "520,701234.25", "655,802000.75",
  "720,810000.5", "845,905000.25", "990,1010000.5", "1100,1200000.75",
].join("\n") + "\n";

async function uploadAndFit(page) {
  await open(page, "/modelling/new?mode=data");
  await page.locator('input[type="file"]').setInputFiles({
    name: "raw.csv", mimeType: "text/csv", buffer: Buffer.from(HEADERLESS),
  });
  await expect(page.getByText("Your first row looks like data, so we've treated it as data.")).toBeVisible();
  await expect(page.getByText(/raw\.csv · 8 rows · 2 columns/)).toBeVisible();
  await expect(page.getByText(/col 1 \(time to failure\)/)).toBeVisible();

  // The column of decimals is offered as a count only with the reason, and can't be picked.
  await page.getByRole("combobox", { name: "What “col 2” is" }).click();
  const count = page.getByRole("option", { name: /^Count/ });
  await expect(count).toBeDisabled();
  await expect(count).toContainText("has decimals");
  await expect(page.getByRole("option", { name: "Ignore this column" })).toBeVisible();
  await page.keyboard.press("Escape");

  await page.getByRole("button", { name: "Next" }).click();
  await page.getByRole("button", { name: "Fit Weibull" }).click();
  await expect(page.getByText("Shape β").first()).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("This fit isn't saved yet.")).toBeVisible();
}

async function expectSavedWithData(page) {
  await page.waitForURL(/\/modelling\/m\/[0-9a-f]{32}$/, { timeout: 30_000 });
  await expect(page.getByRole("heading", { name: /Weibull/ })).toBeVisible();
  const id = page.url().split("/").pop();
  const model = await (await page.request.get(`/api/models/${id}`)).json();
  const dataset = await (await page.request.get(`/api/datasets/${model.dataset_id}`)).json();
  expect(dataset.n_rows).toBe(8); // the first row is kept
  expect(dataset.columns.map((c) => c.name)).toEqual(["col 1", "col 2"]);
}

test("a headerless CSV is detected, fitted and saved with its data in one click", async ({ page, problems }) => {
  await uploadAndFit(page);
  await expectHealthy(page, problems, { label: "fitted headerless CSV", chart: true });
  await page.getByRole("button", { name: "Save this model and its data" }).click();
  await expectSavedWithData(page);
  await expectHealthy(page, problems, { label: "saved model", chart: true });
});

test("a fit left unsaved is offered for saving on the next visit to Modelling", async ({ page, problems }) => {
  await uploadAndFit(page);
  await open(page, "/modelling");
  await expect(page.getByText("You left a fit without saving it")).toBeVisible();
  await page.getByRole("button", { name: "Save it and its data" }).click();
  await expectSavedWithData(page);
  // Saved: no reminder now.
  await open(page, "/modelling");
  await expect(page.getByText("You left a fit without saving it")).toHaveCount(0);
  await expectHealthy(page, problems, { label: "modelling home" });
});

// The Admin page's Plan tab: the sample plan smoke/seed.js stores renders its
// prose and draws its Gantt chart as an SVG. Mermaid loads only when the tab
// opens, and on a phone the chart scrolls inside its own box, not the page.
test("the Admin page's Plan tab draws the plan's Gantt chart", async ({ page, problems }) => {
  const scripts = [];
  page.on("request", (req) => req.resourceType() === "script" && scripts.push(req.url()));
  await open(page, "/admin");
  expect(scripts.filter((u) => /mermaid/i.test(u)), "mermaid loaded before the Plan tab opened").toEqual([]);

  await page.getByRole("tab", { name: "Plan" }).click();
  await expect(page).toHaveURL(/\/admin\?tab=plan$/);
  await expect(page.getByRole("heading", { name: "Example plan", level: 1 })).toBeVisible();
  await expect(page.getByTestId("plan-updated")).toContainText(/Updated .* from smoke\/seed\.js/);
  const chart = page.locator(".admin-plan-chart svg").first();
  await expect(chart).toBeVisible({ timeout: 30_000 });
  await expect(chart.getByText("Task one")).toBeVisible();
  await expect(chart.getByText("Task two")).toBeVisible();
  expect(scripts.some((u) => /mermaid/i.test(u)), "mermaid's chunk loaded").toBe(true);
  await expectHealthy(page, problems, { label: "admin plan" });

  await page.setViewportSize({ width: 400, height: 800 });
  await page.getByRole("button", { name: "Refresh" }).click();
  await expect(page.locator(".admin-plan-chart svg").first()).toBeVisible({ timeout: 30_000 });
  const widths = await page.evaluate(() => {
    const box = document.querySelector(".admin-plan-chart");
    return { page: document.documentElement.scrollWidth, view: window.innerWidth, chart: box.scrollWidth, box: box.clientWidth };
  });
  expect(widths.page, "the page scrolls sideways at 400 px").toBeLessThanOrEqual(widths.view);
  expect(widths.chart, "the Gantt chart keeps its width and scrolls in its box").toBeGreaterThan(widths.box);
  expect(problems, "admin plan at 400 px").toEqual([]);
});
