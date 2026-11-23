// The quick forecast tool (Decisions › Forecasts: Spares, Hours and Cost forecast; Derryn, 23 Nov
// 2026): one page, three views over the same inputs, nothing saved. Pick the sample bearing model,
// eight units at 500 h running 16 h a day, forecast; switch to Labour hours and Costs without
// losing the inputs, each asking for the figure it needs. At 400 px nothing scrolls sideways.
//
// With SMOKE_SHOTS_DIR set, it saves screenshots (for the pull request).
import { test, expect, open, expectHealthy } from "./health.js";

const SHOTS = process.env.SMOKE_SHOTS_DIR || "";
const shot = async (page, name) => {
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: true });
};
const sideways = (page) => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);

for (const width of [1440, 400]) {
  test(`spares, hours and costs from one set of inputs, not saved (${width} px)`, async ({ page, problems }) => {
    await page.setViewportSize({ width, height: 900 });
    await open(page, "/forecasts/spares");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Spares forecast");
    await expect(page.getByText("Scratch pad: not saved")).toBeVisible();
    await page.getByRole("combobox", { name: /: saved model$/ }).click();
    await page.getByRole("option", { name: /^Bearing life — Weibull \(sample\)/ }).click();
    await page.getByLabel("Units").fill("8");
    await page.getByLabel(/^Age now/).fill("500");
    await page.getByLabel("Hours a unit runs a day").fill("16");
    const run = page.getByRole("button", { name: "Forecast", exact: true });
    await expect(run).toBeEnabled({ timeout: 15_000 });
    await run.click();
    const answer = page.locator(".ft-result .rs-sentence");
    await expect(answer).toContainText(/spares used in the next 12 months/, { timeout: 30_000 });
    await expect(page.getByRole("region", { name: "When next" })).toContainText("Spare 1");
    await expect(page.getByText("Likely range (90% two-sided)").first()).toBeVisible();
    await shot(page, `forecast-tool-spares-${width}`);
    if (width <= 400) expect(await sideways(page)).toBeLessThanOrEqual(0);

    // Labour hours: the same inputs; it asks for the hours a failure takes.
    const views = page.getByRole("radiogroup", { name: "Show" });
    await views.getByRole("radio", { name: "Labour hours" }).click();
    await expect(page).toHaveURL(/\/forecasts\/hours$/);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Hours forecast");
    await expect(page.getByLabel("Units")).toHaveValue("8");
    await expect(page.locator(".ft-need")).toContainText("hours a failure takes");
    await page.getByLabel("Hours a failure takes to put right").fill("4");
    await run.click();
    await expect(answer).toContainText(/h of maintenance in the next 12 months/, { timeout: 30_000 });
    await shot(page, `forecast-tool-hours-${width}`);
    if (width <= 400) expect(await sideways(page)).toBeLessThanOrEqual(0);

    // Costs: planned, corrective and spares.
    await views.getByRole("radio", { name: "Costs" }).click();
    await expect(page).toHaveURL(/\/forecasts\/costs$/);
    await page.getByLabel(/^Cost of a failure/).fill("2000");
    await page.getByLabel(/^Cost of a spare/).fill("300");
    await run.click();
    await expect(answer).toContainText(/to maintain them in the next 12 months/, { timeout: 30_000 });
    await expect(page.locator(".ft-result table")).toContainText("Corrective");
    await shot(page, `forecast-tool-costs-${width}`);
    if (width <= 400) expect(await sideways(page)).toBeLessThanOrEqual(0);
    await expectHealthy(page, problems, { label: `forecast tool ${width}` });
  });
}
