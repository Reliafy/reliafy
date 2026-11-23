// A task's Forecast row opens its forecast details (Derryn, 23 Nov 2026: "the details page for a
// forecast should have this information. I should be able to set a horizon and see the counts
// grouped by day, month, etc. and a paginated list of when next"; and "work in calendar or
// operating hours (with or without a duty)"). Open a weekly task's Forecast across the table, 12
// months by month is 12 rows, page through When next; a task by hours with no duty opens on
// Operating hours, and is dated at 24 h a day with a note saying so. At 400 px it's a sheet and nothing scrolls sideways.
import { test, expect, open, expectHealthy, postOk } from "./health.js";

const M = "/api/maintenance";
const SHOTS = process.env.SMOKE_SHOTS_DIR || "";
const shot = async (page, name) => {
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: false });
};
const sideways = (page) => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);

async function plant(request, tag) {
  const post = (path, data) => postOk(request, path, data);
  const top = await post(`${M}/positions`, { name: `Conveyor ${tag}` });
  const walk = await post(`${M}/positions/${top.id}/tasks`, { name: `Belt walk ${tag}`, interval: 1, unit: "weeks" });
  const res = await request.patch(`${M}/tasks/${walk.id}`, { data: { cost: 40 } });
  expect(res.ok(), await res.text()).toBeTruthy();
  const idlers = await post(`${M}/positions/${top.id}/tasks`, { name: `Inspect idlers ${tag}`, interval: 250, unit: "hours" });
  return { top, walk, idlers };
}

test("a task's Forecast: 12 months by month is 12 rows, When next pages 20 at a time; by hours with no duty", async ({ page, request, problems }) => {
  const tag = `f${Date.now()}`;
  const p = await plant(request, tag);
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, `/asset-register/explorer?arrange=positions&root=${p.top.id}&sel=${p.top.id}&tab=maintenance`);
  await page.locator(`[id="tp-MT:${p.walk.id}"]`).locator(".tp-chev").click();
  const fc = page.locator(`[id="tp-MF:MT:${p.walk.id}"]`);
  await expect(fc).toContainText(/times a year · \$[\d,]+ a year/);
  // A double-click: the details across the table, the tree kept.
  await fc.locator(".tp-nm").dblclick();
  const side = page.getByRole("complementary", { name: `Forecast · Belt walk ${tag}` });
  await expect(side).toBeVisible();
  await expect(side).toHaveClass(/is-expanded/);
  await expect(side.getByRole("radiogroup", { name: "Basis" }).getByRole("radio", { name: "Calendar" })).toHaveAttribute("aria-checked", "true");
  await side.getByRole("radiogroup", { name: "Horizon" }).getByRole("radio", { name: "12 months" }).click();
  await side.getByRole("radiogroup", { name: "Group by" }).getByRole("radio", { name: "Month" }).click();
  const rows = side.locator(".fcd-table tbody tr");
  await expect(rows).toHaveCount(12);
  await expect(side.locator(".fcd-bar")).toHaveCount(12);
  await expect(side.locator(".fcd-table tfoot")).toContainText("In all");
  // When next: 20 a page, Next and Previous.
  const next = side.getByRole("region", { name: "When next" });
  await expect(next.locator("li")).toHaveCount(20);
  await expect(next).toContainText(/1–20 of \d+/);
  await next.getByRole("button", { name: "Next" }).click();
  await expect(next).toContainText(/21–40 of \d+/);
  await next.getByRole("button", { name: "Previous" }).click();
  await expect(next).toContainText(/1–20 of \d+/);
  // Group by week: one row a week.
  await side.getByRole("radiogroup", { name: "Group by" }).getByRole("radio", { name: "Week" }).click();
  await expect.poll(() => rows.count()).toBeGreaterThan(45);
  await side.getByRole("radiogroup", { name: "Group by" }).getByRole("radio", { name: "Month" }).click();
  await expect(rows).toHaveCount(12);
  await shot(page, "forecast-details-1440");
  // Esc: back to the table beside the details.
  await page.keyboard.press("Escape");
  await expect(side).not.toHaveClass(/is-expanded/);

  // A task by hours, no duty: dated at 24 h a day in the tree; its details open on Operating hours.
  await page.locator(`[id="tp-MT:${p.idlers.id}"]`).locator(".tp-chev").click();
  const hfc = page.locator(`[id="tp-MF:MT:${p.idlers.id}"]`);
  await expect(hfc).toContainText(/next \d+ \w+ \d{4} · \d+ times a year/);
  await hfc.locator(".tp-nm").dblclick();
  const hside = page.getByRole("complementary", { name: `Forecast · Inspect idlers ${tag}` });
  await expect(hside.getByRole("radiogroup", { name: "Basis" }).getByRole("radio", { name: "Operating hours" })).toHaveAttribute("aria-checked", "true");
  await expect(hside.locator(".fcd-table tbody tr")).toHaveCount(10);
  await expect(hside.getByRole("region", { name: "When next" })).toContainText("in 250 h");
  const note = hside.getByRole("note");
  await expect(note).toContainText("No duty or readings: assuming it runs all the time (24 h a day)");
  await expect(note.getByRole("link", { name: "Set a duty in Operations" })).toHaveAttribute("href", /tab=operations.*plan=|plan=.*tab=operations/);
  // The calendar view of the same task: dated through the same 24 h a day.
  await hside.getByRole("radiogroup", { name: "Basis" }).getByRole("radio", { name: "Calendar" }).click();
  await expect(hside.locator(".fcd-table tbody tr")).toHaveCount(12);
  await expect(hside.getByRole("region", { name: "When next" })).not.toContainText("Nothing falls due");
  await shot(page, "forecast-details-hours-1440");
  await expectHealthy(page, problems, { label: "forecast details" });
});

test("the forecast details at 400 px: a sheet, the table scrolls in its card, nothing sideways", async ({ page, request, problems }) => {
  const tag = `g${Date.now()}`;
  const p = await plant(request, tag);
  await page.setViewportSize({ width: 400, height: 860 });
  await open(page, `/asset-register/explorer?arrange=positions&root=${p.top.id}&sel=${p.top.id}&tab=maintenance`);
  await page.locator(`[id="tp-MT:${p.walk.id}"]`).locator(".tp-chev").click();
  await page.locator(`[id="tp-MF:MT:${p.walk.id}"]`).locator(".tp-nm").click();
  const side = page.getByRole("complementary", { name: `Forecast · Belt walk ${tag}` });
  await expect(side).toBeVisible();
  await expect(side).toHaveClass(/sheet/);
  await expect(side.locator(".fcd-table tbody tr")).toHaveCount(12);
  const scroll = side.locator(".fc-scroll");
  expect(await scroll.evaluate((el) => el.scrollWidth > el.clientWidth)).toBe(true);
  await shot(page, "forecast-details-400");
  expect(await sideways(page)).toBeLessThanOrEqual(0);
  await expectHealthy(page, problems, { label: "forecast details 400" });
});
