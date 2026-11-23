// The quick forecast tool as a sentence (Decisions › Forecasts: Spares, Hours and Cost forecast;
// forecast plan step 1, Nov 2026): one page, three views over the same inputs, nothing saved, and
// the answer follows as you type (no Forecast button). Hours: greasing every 50 h at 12 h a week is
// 12 times, 2.4 h, certain. Costs: add a part that fails (the sample bearing model) and its cost if
// it fails. Spares: the parts it uses, and when. At 400 px nothing scrolls sideways.
//
// With SMOKE_SHOTS_DIR set, it saves screenshots (for the pull request).
import { test, expect, open, expectHealthy } from "./health.js";
import { choose } from "./select.js";

const SHOTS = process.env.SMOKE_SHOTS_DIR || "";
const shot = async (page, name) => {
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: true });
};
const sideways = (page) => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);

for (const width of [1440, 400]) {
  test(`work on a schedule and a part that fails, live, not saved (${width} px)`, async ({ page, problems }) => {
    await page.setViewportSize({ width, height: 900 });
    await open(page, "/forecasts/hours");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Hours forecast");
    await expect(page.getByText("Scratch pad: not saved")).toBeVisible();
    await expect(page.getByRole("button", { name: "Forecast", exact: true })).toHaveCount(0);
    await choose(page.getByRole("combobox", { name: "How it runs" }), "week");
    await page.getByLabel("Hours it runs").fill("12");
    await page.getByLabel("What the work is").fill("Grease deck spindles");
    await page.getByLabel("Every").fill("50");
    await page.getByLabel("Hours each time").fill("0.2");
    const answer = page.locator(".ft-result .rs-sentence");
    await expect(answer).toHaveText("12 times in the next 12 months: 2.4 h.", { timeout: 30_000 });
    await expect(page.locator(".ft-result .rs-note")).toContainText("Certain: a schedule, no chance involved.");
    await expect(page.locator(".ft-lines")).toContainText("Grease deck spindles");
    await shot(page, `forecast-tool-hours-${width}`);
    if (width <= 400) expect(await sideways(page)).toBeLessThanOrEqual(0);

    // Costs: the same inputs; the cost each time, then a part that fails.
    const views = page.getByRole("radiogroup", { name: "Show" });
    await views.getByRole("radio", { name: "Costs" }).click();
    await expect(page).toHaveURL(/\/forecasts\/costs$/);
    await expect(page.getByLabel("Every")).toHaveValue("50");
    await page.getByLabel("Cost each time").fill("18");
    await expect(answer).toContainText("12 times in the next 12 months", { timeout: 30_000 });
    await page.getByRole("button", { name: "A part that fails" }).click();
    await page.getByRole("combobox", { name: /: saved model$/ }).click();
    await page.getByRole("option", { name: /^Bearing life — Weibull \(sample\)/ }).click();
    await page.getByLabel("How old it is now").fill("500");
    await page.getByLabel("Cost if it fails").fill("900");
    await expect(answer).toContainText("expected in the next 12 months", { timeout: 30_000 });
    await expect(page.getByText("Likely range (90% two-sided)").first()).toBeVisible();
    await expect(page.locator(".ft-lines")).toContainText("failures");
    await shot(page, `forecast-tool-costs-${width}`);
    if (width <= 400) expect(await sideways(page)).toBeLessThanOrEqual(0);

    // Spares: the replacement parts with their range, and when each is likely used.
    await views.getByRole("radio", { name: "Spares" }).click();
    await expect(page).toHaveURL(/\/forecasts\/spares$/);
    await expect(answer).toContainText("replacement part", { timeout: 30_000 });
    await expect(page.getByRole("region", { name: "Not counted" })).toContainText("no spares each time");
    await shot(page, `forecast-tool-spares-${width}`);
    if (width <= 400) expect(await sideways(page)).toBeLessThanOrEqual(0);
    await expectHealthy(page, problems, { label: `forecast tool ${width}` });
  });
}
