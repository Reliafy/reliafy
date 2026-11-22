// An accelerated life model: is it safe to extrapolate? The life-stress chart
// draws the median or B10 life with its one-sided lower bound, the mean life
// (MTTF) at the use stress has its two-sided range, and Diagnostics' first
// check is the common-shape test in plain words with its statistic.
import { test, expect, open, expectHealthy } from "./health.js";

const MODEL = "/models/alt/sample-alt-fluid";

test("Life-stress: median or B10 with its lower bound, and the MTTF at the use stress", async ({ page, problems }) => {
  await open(page, MODEL);
  const shown = page.getByRole("radiogroup", { name: "Life shown" });
  await expect(shown).toBeVisible({ timeout: 20_000 });
  await expect(shown.getByRole("radio", { name: "Median" })).toHaveAttribute("aria-checked", "true");
  await expect(page.locator(".plot-container .ytitle").first()).toHaveText(/^Median life/);
  await expect(page.getByText(/90% lower bound \(one-sided\)/).first()).toBeVisible();
  await shown.getByRole("radio", { name: "B10" }).click();
  await expect(page.locator(".plot-container .ytitle").first()).toHaveText(/^B10 life/);
  await shown.getByRole("radio", { name: "Characteristic" }).click();
  await expect(page.locator(".plot-container .ytitle").first()).toHaveText(/^Characteristic life/);
  const mttf = page.locator(".gofr", { hasText: "Mean life (MTTF)" });
  await expect(mttf).toContainText(/two-sided/);
  await expectHealthy(page, problems, { label: "ALT life-stress", chart: true });
});

test("Diagnostics: the common-shape test in plain words, with its statistic", async ({ page, problems }) => {
  await open(page, `${MODEL}?tab=diag`);
  const card = page.getByRole("region", { name: "Is the failure mechanism the same at every stress?" });
  await expect(card).toContainText(/The shapes (are consistent|differ) \(p [=<] /, { timeout: 20_000 });
  await expect(card).toContainText(/Likelihood-ratio statistic [\d.]+ on \d+ degrees? of freedom/);
  await expect(card).not.toContainText(/\b(Yes|Perhaps not|No):/);
  await expectHealthy(page, problems, { label: "ALT diagnostics", chart: true });
});
