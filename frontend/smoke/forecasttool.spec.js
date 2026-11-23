// The quick forecast tool (Decisions › Forecasts: Spares, Hours and Cost forecast; redesigned Nov 2026 after
// Derryn's "this screen doesn't look very good. Also there is no calculate button!"). One inputs card on a
// grid, Calculate bottom right; results only after Calculate, marked stale when the inputs change; nothing
// blocks silently: Calculate says what's missing beside the field and goes there. Three views share the
// inputs and the result. At 400 px the fields stack and nothing scrolls sideways.
//
// With SMOKE_SHOTS_DIR set, it saves screenshots (for the pull request).
import { test, expect, open, expectHealthy } from "./health.js";
import { choose } from "./select.js";

const SHOTS = process.env.SMOKE_SHOTS_DIR || "";
const shot = async (page, name) => {
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: true });
};
const sideways = (page) => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
const label = (page, text) => page.getByLabel(text, { exact: true });

for (const width of [1440, 400]) {
  test(`typed parameters: blocked, then Calculate, then stale (${width} px)`, async ({ page, problems }) => {
    await page.setViewportSize({ width, height: 1000 });
    await open(page, "/forecasts/spares");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Spares forecast");
    await expect(page.getByText("Set the inputs and press")).toBeVisible();
    const calc = page.getByRole("button", { name: "Calculate", exact: true });
    await expect(calc).toBeEnabled();
    // Nothing filled in: Calculate says what's missing beside the fields, and goes to the first.
    await calc.click();
    const life = page.locator("#ft-life");
    await expect(life).toContainText("Pick a saved model, or type the distribution's parameters.");
    await expect(page.locator(".field.has-error", { hasText: "Age now" })).toContainText("Enter how old it is now");
    await shot(page, `after-blocked-${width}`);
    // The owner's case: Weibull scale 100, shape 2.2, 23 old, in the default unit (hours).
    await life.getByRole("radio", { name: "Type parameters" }).click();
    await label(page, "Scale α (hours)").fill("100");
    await label(page, "Shape β").fill("2.2");
    await label(page, "Age now").fill("23");
    await expect(page.getByRole("combobox", { name: "Unit" })).toHaveAttribute("data-value", "hours");
    await calc.click();
    const answer = page.locator(".ft-result .rs-sentence");
    await expect(answer).toContainText("replacement part", { timeout: 30_000 });
    await shot(page, `after-typed-${width}`);
    if (width <= 400) expect(await sideways(page)).toBeLessThanOrEqual(0);
    // An input changes: the answer stays, marked stale, until Calculate again (Enter in a field calculates).
    await label(page, "Age now").fill("50");
    await expect(page.locator(".ft-stale")).toHaveText("Inputs changed: Calculate again.");
    await label(page, "Age now").press("Enter");
    await expect(page.locator(".ft-stale")).toHaveCount(0, { timeout: 30_000 });
    // Another view: the same inputs and the same result, shown for that view.
    await page.getByRole("radiogroup", { name: "Show" }).getByRole("radio", { name: "Costs" }).click();
    await expect(page).toHaveURL(/\/forecasts\/costs$/);
    await expect(label(page, "Age now")).toHaveValue("50");
    await expect(answer).toContainText("No costs given");
    await expectHealthy(page, problems, { label: `forecast tool typed ${width}` });
  });

  test(`a saved model and work on a schedule (${width} px)`, async ({ page, problems }) => {
    await page.setViewportSize({ width, height: 1000 });
    await open(page, "/forecasts/costs");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Cost forecast");
    const calc = page.getByRole("button", { name: "Calculate", exact: true });
    // Work on a schedule alone: no model needed.
    await choose(page.getByRole("combobox", { name: "Running" }), "week");
    await label(page, "Hours a week").fill("12");
    await label(page, "What's done").fill("Grease deck spindles");
    await label(page, "Every").fill("50");
    await page.getByLabel(/^Cost each time/).first().fill("18");
    await calc.click();
    const answer = page.locator(".ft-result .rs-sentence");
    await expect(answer).toHaveText("12 times in the next 12 months: $216.", { timeout: 30_000 });
    await shot(page, `after-schedule-${width}`);
    // Add a part that fails, from a saved model: its unit comes with it, read-only.
    await page.getByRole("button", { name: "Add a part that fails" }).click();
    await page.getByRole("combobox", { name: "Model" }).click();
    await page.getByRole("option", { name: /^Bearing life — Weibull/ }).click();
    await expect(page.locator(".ft-fixed")).toContainText("(the model's)");
    await label(page, "Age now").fill("500");
    await page.getByLabel(/^Cost if it fails/).first().fill("900");
    await calc.click();
    await expect(answer).toContainText("expected in the next 12 months", { timeout: 30_000 });
    await expect(page.locator(".ft-lines")).toContainText("failures");
    await shot(page, `after-saved-${width}`);
    if (width <= 400) expect(await sideways(page)).toBeLessThanOrEqual(0);
    // Supporting work: its worth, and the what-if "not done".
    await choose(page.getByRole("combobox", { name: "What it does to the part" }), "supports");
    await label(page, "If it isn't done: failure rate ×").fill("2");
    await choose(page.getByRole("combobox", { name: "What if it's" }), "drop");
    await calc.click();
    await expect(page.locator(".ft-worth")).toContainText("Worth: avoids about", { timeout: 30_000 });
    await expect(page.locator(".ft-whatif-line")).toContainText("Not done:");
    await expectHealthy(page, problems, { label: `forecast tool saved ${width}` });
  });
}
