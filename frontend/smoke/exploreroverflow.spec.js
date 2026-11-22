// The Explorer's panel tabs (explorerTabs.js EXPLORER_PANEL_TABS): one flat row ordered by use,
// the tabs that don't fit folded into a last "⋯ N" tab (the shared Tabs with `overflow`). A tab's
// inner views (Monitoring: Readings · Life left) switch the body; Maintenance is one table (an old
// ?tab=lsa or ?mview= address opens it); an old address (?tab=condition) opens its tab and inner view; picking a folded tab from "⋯" swaps it into the
// row; the keyboard reaches "⋯" and its menu; at 400 px nothing scrolls sideways. The seeded depot
// conveyor (smoke/seed.js) has a task in a package and measuring points.
import { test, expect, open, expectHealthy } from "./health.js";
import { EXPLORER_PANEL_TABS } from "../src/explorerTabs.js";
import { escapeRegExp } from "./explorer.js";

const NAME = "Depot conveyor (smoke test)";
const conveyor = async (request) => {
  const d = await (await request.get("/api/maintenance/overview")).json();
  const n = (d.tree || []).find((x) => x.name === NAME);
  expect(n, "the seeded depot conveyor").toBeTruthy();
  return n.id;
};
const at = (id, extra = "") => `/asset-register/explorer?arrange=positions&root=${id}&sel=${id}${extra}`;
const bar = (page) => page.getByRole("tablist", { name: "What to show for this row" });
const ALL = ["Summary", "Maintenance", "Monitoring", "RCM", "FME(C)A", "Models", "History"];

test.skip(!EXPLORER_PANEL_TABS, "the panel tabs are switched off");

test("panel tabs: the flat row, inner views, an old address", async ({ page, request, problems }) => {
  const id = await conveyor(request);
  await page.setViewportSize({ width: 1600, height: 900 });
  await open(page, at(id));
  const tabs = bar(page);
  await expect(tabs.getByRole("tab")).toHaveText(ALL);
  await expect(tabs.getByRole("tab", { name: "Summary" })).toHaveAttribute("aria-selected", "true");

  // Maintenance: the address says ?tab=maintenance; one table, no inner views (Derryn, 22 Nov 2026).
  await tabs.getByRole("tab", { name: "Maintenance" }).click();
  await expect(page).toHaveURL(/tab=maintenance/);
  await expect(page.getByRole("radiogroup", { name: "Maintenance: what to show" })).toHaveCount(0);
  // Its package is a row of the table (where its tasks meet).
  await expect(page.locator(".tp-row", { has: page.locator(".tp-nm", { hasText: "Smoke test weekly round" }) }).first()).toBeVisible();
  await expectHealthy(page, problems, { root: ".tx" });
  // The old inner views' addresses open the one table: Packages with a package open, Forecast as Forecast….
  await open(page, at(id, "&tab=lsa&mview=packages"));
  await expect(page).toHaveURL(/tab=maintenance/);
  await expect(page).not.toHaveURL(/mview=/);
  await expect(bar(page).getByRole("tab", { name: "Maintenance" })).toHaveAttribute("aria-selected", "true");
  await open(page, at(id, "&tab=maintenance&mview=forecast"));
  await expect(page).toHaveURL(new RegExp(`forecast=${id}`));
  await expect(page.locator("section.fc-view").first()).toBeVisible();

  // An old address: ?tab=condition is Monitoring › Life left.
  await open(page, at(id, "&tab=condition"));
  await expect(bar(page).getByRole("tab", { name: "Monitoring" })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("radiogroup", { name: "Monitoring: what to show" }).getByRole("radio", { name: "Life left" }))
    .toHaveAttribute("aria-checked", "true");
  // ?tab=missions (the old Missions view) is the Models tab: missions are rows under their models.
  await open(page, at(id, "&tab=missions"));
  await expect(bar(page).getByRole("tab", { name: "Models" })).toHaveAttribute("aria-selected", "true");
});

test("panel tabs overflow: ⋯ N folds what doesn't fit; picking one swaps it in; the keyboard reaches it", async ({ page, request }) => {
  const id = await conveyor(request);
  await page.setViewportSize({ width: 1000, height: 860 });
  await open(page, at(id));
  const tabs = bar(page);
  const more = tabs.getByRole("tab", { name: /more tabs?:/ });
  await expect(more).toBeVisible();
  const shownBefore = await tabs.getByRole("tab").allTextContents();
  const n = ALL.length - (shownBefore.length - 1);
  await expect(more).toHaveText(`⋯ ${n}`);
  // Every tab is either shown or in ⋯, in order; Summary (selected) shows.
  expect(shownBefore.slice(0, -1)).toEqual(ALL.slice(0, shownBefore.length - 1));

  // Keyboard: End goes to ⋯ without selecting it, ↓ opens its menu, Esc puts the focus back.
  await tabs.getByRole("tab", { name: "Summary" }).focus();
  await page.keyboard.press("End");
  await expect(more).toBeFocused();
  await expect(tabs.getByRole("tab", { name: "Summary" })).toHaveAttribute("aria-selected", "true");
  await page.keyboard.press("ArrowDown");
  const menu = page.getByRole("menu", { name: "More tabs" });
  await expect(menu.getByRole("menuitem")).toHaveText(ALL.slice(ALL.length - n));
  await page.keyboard.press("Escape");
  await expect(menu).toBeHidden();
  await expect(more).toBeFocused();

  // Pick the last (History) from ⋯: it takes the last slot, the one it displaced goes into ⋯.
  await more.click();
  await menu.getByRole("menuitem", { name: "History" }).click();
  await expect(page).toHaveURL(/tab=reports/);
  const history = tabs.getByRole("tab", { name: "History" });
  await expect(history).toHaveAttribute("aria-selected", "true");
  await expect(history).toBeFocused();
  const shownAfter = await tabs.getByRole("tab").allTextContents();
  expect(shownAfter.at(-2)).toBe("History");
  expect(shownAfter.length).toBeLessThanOrEqual(shownBefore.length);
  await expect(tabs.getByRole("tab", { name: /more tabs?:/ })).toHaveAccessibleName(new RegExp(escapeRegExp(shownBefore.at(-2))));
});

test("panel tabs at 400 px: the row fits with ⋯, nothing scrolls sideways", async ({ page, request }) => {
  const id = await conveyor(request);
  await page.setViewportSize({ width: 400, height: 860 });
  await open(page, at(id, "&tab=maintenance"));
  // The Maintenance tab's Tasks view is a tree-table: its rows are the table's.
  await page.locator(".tp-row", { has: page.locator(".tp-nm", { hasText: NAME }) }).first().locator(".tp-nm").click();
  const tabs = page.getByRole("tablist", { name: new RegExp("^What to show for") }).first();
  await expect(tabs.getByRole("tab", { name: "Maintenance" })).toHaveAttribute("aria-selected", "true");
  await expect(tabs.getByRole("tab", { name: /more tabs?:/ })).toBeVisible();
  const sideways = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(sideways).toBeLessThanOrEqual(0);
  // Maintenance has no inner views (Monitoring and Models keep theirs).
  await expect(page.getByRole("radiogroup", { name: "Maintenance: what to show" })).toHaveCount(0);
});
