// A section header's help link (ui/HelpLink, the design system's Help link):
// it names what it does ("Take the tour" starts the walkthrough), sits after
// the purpose while there's room, and on a phone wraps to its own line with
// its icon flush under the purpose text — no stray indent, nothing sideways.
import { test, expect, open, expectHealthy } from "./health.js";

const header = (page) => page.locator(".page-header.section-header");

test("the Models header's help link says what it does and starts the tour", async ({ page, problems }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await open(page, "/models");
  await expectHealthy(page, problems);
  const link = header(page).getByRole("button", { name: "Take the tour" });
  await expect(link).toBeVisible();
  await expect(header(page).getByText("Show me how")).toHaveCount(0);
  // The purpose wraps to at most two lines rather than being cut on one.
  const purpose = header(page).locator(".sh-purpose-text");
  const lines = await purpose.evaluate((el) => Math.round(el.getBoundingClientRect().height / parseFloat(getComputedStyle(el).lineHeight)));
  expect(lines).toBeLessThanOrEqual(2);
  await link.click();
  await expect(page.locator(".wt-callout")).toBeVisible({ timeout: 15_000 });
});

test("at 400 px the help link sits on its own line, lined up with the purpose", async ({ page, problems }) => {
  await page.setViewportSize({ width: 400, height: 860 });
  await open(page, "/models");
  await expectHealthy(page, problems);
  const link = header(page).getByRole("button", { name: "Take the tour" });
  await expect(link).toBeVisible();
  const [text, icon] = await Promise.all([
    header(page).locator(".sh-purpose-text").boundingBox(),
    link.locator("svg").boundingBox(),
  ]);
  expect(Math.abs(icon.x - text.x)).toBeLessThanOrEqual(2);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(400);
});
