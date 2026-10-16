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
