// New dataset › Type it in: five lives typed as text (SurPyval's notation),
// read back live as they are typed, saved as an ordinary dataset and fitted
// with a Weibull; the dataset page's "Show as text" gives the same text back.
// With SMOKE_SHOTS_DIR set, it also saves screenshots there (desktop and 400 px, for the pull request).
import { test, expect, open, expectHealthy } from "./health.js";

const SHOTS = process.env.SMOKE_SHOTS_DIR || "";
const shots = async (page, name) => {
  if (!SHOTS) return;
  await page.screenshot({ path: `${SHOTS}/${name}-1280.png` });
  const size = page.viewportSize();
  await page.setViewportSize({ width: 400, height: 860 });
  await page.screenshot({ path: `${SHOTS}/${name}-400.png`, fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(400);
  await page.setViewportSize(size);
};

test("type five lives in, create the dataset and fit a Weibull", async ({ page, problems }) => {
  await open(page, "/data");
  await page.getByRole("button", { name: "New dataset" }).first().click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("button", { name: "Type it in" }).click();
  await expect(dialog.getByRole("radio", { name: "Type it in" })).toHaveAttribute("aria-checked", "true");
  const name = `Typed seals ${Date.now()}`;
  await dialog.getByLabel("Dataset name").fill(name);
  const lives = dialog.getByRole("textbox", { name: "Lives", exact: true });
  // A mistake says where, in SurPyval's words.
  await lives.fill("120, 31O");
  await expect(dialog.getByRole("alert")).toContainText("Entry 2");
  await lives.fill("120, 310, [400, 450], 620, 1000+");
  await expect(dialog.getByText("5 units: 3 failed, 1 in a window 400–450, 1 still running at 1,000")).toBeVisible();
  // The lifetimes, drawn as the dataset's page will draw them, redrawn as the text changes.
  const lifetimes = dialog.getByTestId("lifetimes-summary");
  await expect(lifetimes).toContainText("Not saved yet");
  await expect(lifetimes).toContainText("5 units");
  await expect(dialog.locator(".lt .js-plotly-plot, .lt svg").first()).toBeVisible();
  await lives.fill("120, 310, [400, 450], 620, 1000+, 1100+");
  await expect(lifetimes).toContainText("6 units");
  await lives.fill("120, 310, [400, 450], 620, 1000+");
  await expect(lifetimes).toContainText("5 units");
  const create = dialog.getByRole("button", { name: "Create dataset" });
  await expect(create).toBeDisabled(); // no unit yet
  await dialog.getByRole("combobox", { name: "Unit of the times" }).fill("hours");
  await expect(create).toBeEnabled();
  await dialog.getByText("What can I type?").click();
  await expect(dialog.getByText("still running at 1000 (hasn't failed yet)")).toBeVisible();
  await expectHealthy(page, problems, { label: "typed lives" });
  await shots(page, "type-it-in");
  await create.click();

  await expect(page).toHaveURL(/\/data\/[0-9a-f]{32}$/, { timeout: 30_000 });
  await expect(page.getByRole("heading", { name })).toBeVisible();
  await page.getByRole("button", { name: "Show as text" }).click();
  await expect(page.getByRole("textbox", { name: "The data as text" })).toHaveValue("120, 310, [400, 450], 620, 1000+");
  await expectHealthy(page, problems, { label: "typed dataset" });
  await shots(page, "show-as-text");

  await page.getByRole("button", { name: "Fit a model" }).click();
  await expect(page.locator('[data-wt="reading-summary"]')).toContainText("xl");
  await page.getByRole("button", { name: "Fit Weibull" }).click();
  await expect(page.getByText("Shape β").first()).toBeVisible({ timeout: 30_000 });
  await expectHealthy(page, problems, { label: "fit of typed lives", chart: true });
});
