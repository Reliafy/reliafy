// The Explorer's grouped tabs (explorerTabs.js EXPLORER_GROUPED_TABS): Summary | Analysis ▾ |
// Operation ▾ | History ▾. A group's menu opens from the keyboard (↓) and closes with Esc, the
// focus back on its tab; an entry picked names the group's tab ("Operation: Maintenance") and its
// inner views switch the body (Tasks, What it needs, Packages); an old address (?tab=condition)
// opens its group, entry and view; at 400 px nothing scrolls sideways. The seeded depot conveyor
// (smoke/seed.js) has a task in a package and measuring points.
import { test, expect, open, expectHealthy } from "./health.js";
import { EXPLORER_GROUPED_TABS } from "../src/explorerTabs.js";

const NAME = "Depot conveyor (smoke test)";
const conveyor = async (request) => {
  const d = await (await request.get("/api/maintenance/overview")).json();
  const n = (d.tree || []).find((x) => x.name === NAME);
  expect(n, "the seeded depot conveyor").toBeTruthy();
  return n.id;
};
const at = (id, extra = "") => `/asset-register/explorer?arrange=positions&root=${id}&sel=${id}${extra}`;
const bar = (page) => page.getByRole("tablist", { name: "What to show for this row" });

test.skip(!EXPLORER_GROUPED_TABS, "grouped tabs are switched off");

test("grouped tabs: menus by keyboard, an entry and its inner views, an old address", async ({ page, request, problems }) => {
  const id = await conveyor(request);
  await open(page, at(id));
  const tabs = bar(page);
  await expect(tabs.getByRole("tab")).toHaveText([/^Summary$/, /Analysis/, /Operation/, /History/]);
  await expect(tabs.getByRole("tab", { name: "Summary" })).toHaveAttribute("aria-selected", "true");

  // Analysis by keyboard: → from Summary, ↓ opens it, Esc closes it and the focus is back.
  await tabs.getByRole("tab", { name: "Summary" }).focus();
  await page.keyboard.press("ArrowRight");
  const analysis = tabs.getByRole("tab", { name: "Analysis" });
  await expect(analysis).toBeFocused();
  await page.keyboard.press("ArrowDown");
  const menu = page.getByRole("menu", { name: "Analysis" });
  await expect(menu.getByRole("menuitemradio")).toHaveText([/RCM/, /FME\(C\)A/, /Reliability models/, /Missions/]);
  await page.keyboard.press("Escape");
  await expect(menu).toBeHidden();
  await expect(analysis).toBeFocused();

  // Operation › Maintenance: the tab names it, the address says ?tab=maintenance.
  await tabs.getByRole("tab", { name: "Operation" }).click();
  await page.getByRole("menu", { name: "Operation" }).getByRole("menuitemradio", { name: "Maintenance" }).click();
  await expect(page).toHaveURL(/tab=maintenance/);
  await expect(tabs.getByRole("tab", { name: "Operation: Maintenance" })).toHaveAttribute("aria-selected", "true");
  const views = page.getByRole("radiogroup", { name: "Maintenance: what to show" });
  await expect(views.getByRole("radio", { name: "Tasks" })).toHaveAttribute("aria-checked", "true");
  await views.getByRole("radio", { name: "What it needs" }).click();
  await expect(page).toHaveURL(/tab=lsa/);
  await views.getByRole("radio", { name: "Packages" }).click();
  await expect(page).toHaveURL(/mview=packages/);
  await expect(page.getByRole("button", { name: "Smoke test weekly round" }).first()).toBeVisible();
  await expectHealthy(page, problems, { root: ".tx" });

  // An old address: ?tab=condition is Operation › Monitoring › Risk now.
  await open(page, at(id, "&tab=condition"));
  await expect(bar(page).getByRole("tab", { name: "Operation: Monitoring" })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("radiogroup", { name: "Monitoring: what to show" }).getByRole("radio", { name: "Risk now" }))
    .toHaveAttribute("aria-checked", "true");
});

test("grouped tabs at 400 px: the row fits, nothing scrolls sideways", async ({ page, request }) => {
  const id = await conveyor(request);
  await page.setViewportSize({ width: 400, height: 860 });
  await open(page, at(id, "&tab=maintenance"));
  await page.getByRole("treeitem", { name: new RegExp(`^${NAME.replace(/[()]/g, "\\$&")}`) }).first().locator(".tp-nm").click();
  const tabs = bar(page);
  await expect(tabs.getByRole("tab", { name: "Operation: Maintenance" })).toBeVisible();
  const sideways = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(sideways).toBeLessThanOrEqual(0);
  await tabs.getByRole("tab", { name: "History" }).click();
  await expect(page.getByRole("menu", { name: "History" }).getByRole("menuitemradio", { name: "Failure reports" })).toBeVisible();
});
