// The History tab's Ranking (FRACAS): a fleet of two units, one failing more; Reports ·
// Ranking switches the view; the ranking puts the unit with more failures first, with its
// count, rate range and a plain sentence (no verdict words); Group by Failure mode and Rank
// by Failure rate re-rank; Open in › Failure reports filters the list to that mode; a unit
// with nothing in the window says so. At 400 px nothing scrolls the page sideways.
// With SMOKE_SHOTS_DIR set, it also saves screenshots there.
import { test, expect, open, expectHealthy, postOk } from "./health.js";
import { pickTab } from "./explorer.js";
import { choose } from "./select.js";

const M = "/api/maintenance";
const SHOTS = process.env.SMOKE_SHOTS_DIR || "";
const shot = async (page, name) => {
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: true });
};

function daysAgo(n) {
  const d = new Date(Date.now() - n * 86_400_000);
  return d.toISOString().slice(0, 10);
}

async function fleet(request, tag) {
  const post = (path, data) => postOk(request, path, data);
  const top = await post(`${M}/positions`, { name: `Rank fleet ${tag}` });
  const a = await post(`${M}/positions`, { name: `Rank unit A ${tag}`, parent_id: top.id });
  const b = await post(`${M}/positions`, { name: `Rank unit B ${tag}`, parent_id: top.id });
  for (const [unit, n, mode] of [[a, 6, "Seal worn"], [b, 1, "Seal worn"], [a, 1, "Bearing seized"]]) {
    for (let k = 0; k < n; k += 1) {
      await post(`${M}/failure-reports`, { position_id: unit.id, title: `${mode} ${k}`, occurred_on: daysAgo(20 + 30 * k),
        failure_mode_text: mode });
    }
  }
  return { top, a, b };
}

test("Failure ranking: switch views, rank by unit and mode, open the reports behind a row", async ({ page, request, problems }) => {
  const tag = `k${Date.now()}`;
  const f = await fleet(request, tag);
  await page.setViewportSize({ width: 1680, height: 1000 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${f.top.id}&root=${f.top.id}`);
  await pickTab(page, "History");
  const panel = page.locator(".fr-panel").first();
  const views = panel.getByRole("radiogroup", { name: "Failure reports or ranking" });
  await expect(views).toBeVisible();
  await views.getByRole("radio", { name: "Ranking" }).click();
  const table = panel.locator(".fr-rank-table");
  await expect(table).toBeVisible();
  // Unit A first: 7 failures; the sentence says what it means, never a verdict.
  const first = table.locator("tbody").first();
  await expect(first).toContainText(`Rank unit A ${tag}`);
  await expect(first.locator("td").nth(2)).toHaveText("7");
  await expect(first).toContainText("would be expected at the rate of everything here pooled");
  // Nothing clipped at 1680 px: the table fits its card.
  expect(await table.evaluate((t) => t.scrollWidth <= t.parentElement.clientWidth + 1)).toBe(true);
  await expect(panel).not.toContainText(/bad actor|deteriorating/i);
  await expect(panel.locator(".fr-rank-answer")).toContainText("8 failures in the last 12 months");
  await expect(panel.getByRole("button", { name: "Export CSV" })).toBeVisible();
  await shot(page, "ranking-desktop");

  // By failure mode, by rate: Seal worn has the most failures and leads.
  await choose(panel.getByRole("combobox", { name: "Group by" }), "Failure mode");
  await choose(panel.getByRole("combobox", { name: "Rank by" }), "Failure rate");
  await expect(table.locator("thead")).toContainText("Failure mode");
  await expect(table.locator("tbody tr").first()).toContainText("Seal worn");

  // Open in › Failure reports: the list, filtered to that mode, every stage.
  await table.locator("tbody tr").first().getByRole("button", { name: /^Actions for Seal worn/ }).click();
  await page.getByRole("menuitem", { name: "Open in" }).click();
  await page.getByRole("menuitem", { name: "Failure reports" }).click();
  await expect(views.getByRole("radio", { name: "Reports" })).toHaveAttribute("aria-checked", "true");
  await expect(panel.getByRole("list", { name: "Failure reports" }).locator("li")).toHaveCount(7);
  await expectHealthy(page, problems);

  // A dates window with nothing in it: the empty state.
  await views.getByRole("radio", { name: "Ranking" }).click();
  await choose(panel.getByRole("combobox", { name: "Time window" }), "Dates");
  await panel.getByLabel("Until").fill("2001-01-01");
  await panel.getByLabel("Until").press("Enter");
  await expect(panel).toContainText("No failures recorded in this window");

  // At 400 px: the table scrolls in its card, the page doesn't.
  // At 400 px, the row opened on its own screen.
  await page.setViewportSize({ width: 400, height: 860 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${f.top.id}&root=${f.top.id}&tab=reports`);
  const fleetRow = page.getByRole("treeitem", { name: new RegExp(`^Rank fleet ${tag}`) });
  if (!(await page.locator(".fr-panel").count())) await fleetRow.locator(".tp-nm").click();
  await page.locator(".fr-panel").first().getByRole("radio", { name: "Ranking" }).click();
  await expect(page.locator(".fr-rank-table")).toBeVisible();
  const wide = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(wide).toBeLessThanOrEqual(1);
  await shot(page, "ranking-phone");
  expect(problems).toEqual([]);
});
