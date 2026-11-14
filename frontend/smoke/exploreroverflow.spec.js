// The Explorer's panel tabs (explorerTabs.js EXPLORER_PANEL_TABS): one flat row ordered by use,
// the tabs that don't fit folded into a last "⋯ N" tab (the shared Tabs with `overflow`). A tab's
// inner views (Maintenance: Tasks · What it needs · Packages) switch the body; an old address
// (?tab=condition) opens its tab and inner view; picking a folded tab from "⋯" swaps it into the
// row; the keyboard reaches "⋯" and its menu; at 400 px nothing scrolls sideways. The seeded depot
// conveyor (smoke/seed.js) has a task in a package and measuring points.
import { test, expect, open, expectHealthy } from "./health.js";
import { EXPLORER_PANEL_TABS } from "../src/explorerTabs.js";

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

  // Maintenance: the address says ?tab=maintenance, its inner views switch the body.
  await tabs.getByRole("tab", { name: "Maintenance" }).click();
  await expect(page).toHaveURL(/tab=maintenance/);
  const views = page.getByRole("radiogroup", { name: "Maintenance: what to show" });
  await expect(views.getByRole("radio", { name: "Tasks" })).toHaveAttribute("aria-checked", "true");
  await views.getByRole("radio", { name: "What it needs" }).click();
  await expect(page).toHaveURL(/tab=lsa/);
  await expect(tabs.getByRole("tab", { name: "Maintenance" })).toHaveAttribute("aria-selected", "true");
  await views.getByRole("radio", { name: "Packages" }).click();
  await expect(page).toHaveURL(/mview=packages/);
  await expect(page.getByRole("button", { name: "Smoke test weekly round" }).first()).toBeVisible();
  await expectHealthy(page, problems, { root: ".tx" });

  // An old address: ?tab=condition is Monitoring › Life left.
  await open(page, at(id, "&tab=condition"));
  await expect(bar(page).getByRole("tab", { name: "Monitoring" })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("radiogroup", { name: "Monitoring: what to show" }).getByRole("radio", { name: "Life left" }))
    .toHaveAttribute("aria-checked", "true");
  // ?tab=missions is Models › Missions.
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
  await expect(tabs.getByRole("tab", { name: /more tabs?:/ })).toHaveAccessibleName(new RegExp(shownBefore.at(-2).replace(/[()]/g, "\\$&")));
});

test("panel tabs at 400 px: the row fits with ⋯, nothing scrolls sideways", async ({ page, request }) => {
  const id = await conveyor(request);
  await page.setViewportSize({ width: 400, height: 860 });
  await open(page, at(id, "&tab=maintenance"));
  await page.getByRole("treeitem", { name: new RegExp(`^${NAME.replace(/[()]/g, "\\$&")}`) }).first().locator(".tp-nm").click();
  const tabs = page.getByRole("tablist", { name: new RegExp("^What to show for") }).first();
  await expect(tabs.getByRole("tab", { name: "Maintenance" })).toHaveAttribute("aria-selected", "true");
  await expect(tabs.getByRole("tab", { name: /more tabs?:/ })).toBeVisible();
  const sideways = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(sideways).toBeLessThanOrEqual(0);
  // The inner views sit on one line each.
  const radios = page.getByRole("radiogroup", { name: "Maintenance: what to show" }).getByRole("radio");
  for (const r of await radios.all()) {
    const lines = await r.evaluate((el) => {
      const range = document.createRange();
      range.selectNodeContents(el);
      return new Set([...range.getClientRects()].map((b) => Math.round(b.top))).size;
    });
    expect(lines).toBe(1);
  }
});
