// The Explorer's Maintenance tab (?tab=maintenance): its columns filter to the tasks open in the
// tree, task rows are picked together (click, Ctrl/⌘-click, their boxes), and right-click ›
// Package… makes a work package from them in the table area (never a dialog); they then show in
// the Packaged column, which links to the package. Add to package… puts another task in it, on
// every Nth visit when its interval is a whole multiple of the package's. At 400 px nothing
// scrolls the page sideways. Each test makes its own small plant through the API.
//
// With SMOKE_SHOTS_DIR set, it saves screenshots (for the pull request).
import { test, expect, open, expectHealthy, postOk } from "./health.js";
import { expectChosen } from "./select.js";
import { subItem } from "./explorer.js";

const M = "/api/maintenance";
const SHOTS = process.env.SMOKE_SHOTS_DIR || "";
const shot = async (page, name) => {
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}.png` });
};
const nameRow = (page, text) => page.locator(".tp-row", { has: page.locator(".tp-nm", { hasText: text }) });
const sideways = (page) => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);

async function plant(request, tag) {
  const post = (path, data) => postOk(request, path, data);
  const pump = await post(`${M}/positions`, { name: `Pkg pump ${tag}` });
  const motor = await post(`${M}/positions`, { name: `Pkg motor ${tag}`, parent_id: pump.id });
  await post(`${M}/positions/${pump.id}/tasks`, { name: `Check the seal ${tag}`, interval: 1, unit: "months", trade: `Fitter ${tag}` });
  await post(`${M}/positions/${motor.id}/tasks`, { name: `Grease the bearings ${tag}`, interval: 1, unit: "months", trade: `Fitter ${tag}` });
  await post(`${M}/positions/${motor.id}/tasks`, { name: `Megger the windings ${tag}`, interval: 3, unit: "months", trade: `Electrician ${tag}` });
  return { pump, motor };
}

test("Maintenance tasks: filter a column, select two, Package…, they show as Packaged; Add to package…", async ({ page, request, problems }) => {
  const tag = `k${Date.now()}`;
  const p = await plant(request, tag);
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, `/asset-register/explorer?arrange=positions&root=${p.pump.id}&sel=${p.motor.id}&tab=maintenance`);
  await expect(nameRow(page, `Megger the windings ${tag}`)).toBeVisible();

  // The Trade column's filter: its values from the tasks on show, each counted.
  await page.getByRole("button", { name: /^Filter Trade/ }).click();
  const pop = page.getByRole("dialog", { name: "Filter: Trade" });
  await expect(pop.locator(".cf-item")).toHaveText([new RegExp(`Electrician ${tag}\\s*1`), new RegExp(`Fitter ${tag}\\s*2`)]);
  await pop.getByRole("checkbox", { name: `Fitter ${tag}` }).check();
  await page.keyboard.press("Escape");
  await expect(nameRow(page, `Megger the windings ${tag}`)).toHaveCount(0);
  await expect(page.getByRole("button", { name: /^Filter Trade \(1 chosen\)/ })).toBeVisible();
  // The roll-ups follow the filter; the tree's header says it's on.
  await expect(nameRow(page, `Pkg motor ${tag}`)).toContainText("1 task here");
  await expect(page.locator(".tt-filtered")).toContainText("Filtered by Trade");
  await shot(page, "tasks-filtered-desktop");

  // Select two: a click, then Ctrl-click; right-click › Package… opens in the table area.
  await nameRow(page, `Check the seal ${tag}`).locator(".tp-nm").click();
  await nameRow(page, `Grease the bearings ${tag}`).locator(".tp-nm").click({ modifiers: ["ControlOrMeta"] });
  await expect(page.locator(".tp-row.picked")).toHaveCount(2);
  // No tick boxes on the rows; the header counts the pick, with Clear.
  await expect(page.locator(".tp-row input[type=checkbox]")).toHaveCount(0);
  await expect(page.locator(".tt-selected")).toContainText("2 selected");
  await page.locator(".tt-selected").getByRole("button", { name: "Clear" }).click();
  await expect(page.locator(".tp-row.picked")).toHaveCount(0);
  await nameRow(page, `Check the seal ${tag}`).locator(".tp-nm").click();
  await page.keyboard.press("Shift+ArrowDown");
  await expect(page.locator(".tt-selected")).toContainText("2 selected");
  await nameRow(page, `Grease the bearings ${tag}`).locator(".tp-nm").click({ button: "right" });
  const menu = page.getByRole("menu");
  // Two picked: Package 2 tasks… counts them; what works on one task (Open, Optimise…, Retire…) is
  // greyed with the reason; Optimise… (greyed) and Clear the selection fold under More ›.
  await expect(menu.getByRole("menuitem")).toHaveText([/^Open.*picked/, /^Rename…/, /^Move to…/, /^Focus/, /^Pin this branch/, "Copy link",
    "Package 2 tasks…", "Add 2 tasks to a package…", "More", /^Retire…/]);
  await menu.getByRole("menuitem", { name: "Package 2 tasks…", exact: true }).click();
  const pane = page.locator("section.table-pane");
  await expect(pane).toContainText("2 tasks");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(pane.getByRole("textbox", { name: /Name/ })).toHaveValue("Monthly service");
  await shot(page, "tasks-package-desktop");
  await pane.getByRole("button", { name: "Make package" }).click();
  await expect(pane).toHaveCount(0);
  await page.locator(".tt-filtered").getByRole("button", { name: "Clear the filters" }).click();

  // Both show as Packaged, a link to the package.
  for (const name of [`Check the seal ${tag}`, `Grease the bearings ${tag}`]) {
    await expect(nameRow(page, name).locator(".mt-pkg-link")).toHaveText("Monthly service");
  }
  await expect(nameRow(page, `Megger the windings ${tag}`).locator(".mt-pkg-link")).toHaveCount(0);
  await shot(page, "tasks-packaged-desktop");

  // Add to package… on the three-monthly task: the package fits, on every 3rd visit.
  await nameRow(page, `Megger the windings ${tag}`).locator(".tp-nm").click({ button: "right" });
  // Open in › keeps its place in the menu; Add to package… is under More ›.
  await page.getByRole("menu").getByRole("menuitem", { name: /^More/ }).click();
  await page.getByRole("menuitem", { name: "Add to package…" }).click();
  await expect(pane.getByRole("radio", { name: /Monthly service/ })).toBeChecked();
  await expectChosen(pane.getByRole("combobox", { name: /on which visits/ }), "3");
  await pane.getByRole("button", { name: "Add", exact: true }).click();
  await expect(nameRow(page, `Megger the windings ${tag}`).locator(".mt-pkg-link")).toHaveText("Monthly service");

  // The Packaged link opens the package beside the table, its row (where its tasks meet) picked.
  await nameRow(page, `Check the seal ${tag}`).locator(".mt-pkg-link").click();
  await expect.poll(() => new URL(page.url()).searchParams.get("mpkg")).not.toBe(null);
  await expect(page.getByRole("complementary", { name: "Monthly service" })).toBeVisible();
  await expectHealthy(page, problems, { label: "tasks packaging" });
});

test("Maintenance tasks at 400 px: the Filter button, Select on a task's menu and tapping rows; nothing scrolls sideways", async ({ page, request, problems }) => {
  const tag = `q${Date.now()}`;
  const p = await plant(request, tag);
  await page.setViewportSize({ width: 400, height: 860 });
  await open(page, `/asset-register/explorer?arrange=positions&root=${p.pump.id}&sel=${p.motor.id}&tab=maintenance`);
  await expect(nameRow(page, `Grease the bearings ${tag}`)).toBeVisible();
  await page.getByRole("button", { name: /^Filter the tasks/ }).click();
  await expect(page.getByRole("dialog", { name: "Filter the tasks" })).toContainText("Trade");
  expect(await sideways(page)).toBeLessThanOrEqual(0);
  await shot(page, "tasks-filter-phone");
  await page.keyboard.press("Escape");
  // No row boxes: Select on the row's menu, then tap another row.
  await expect(page.locator(".tp-row input[type=checkbox]")).toHaveCount(0);
  await nameRow(page, `Grease the bearings ${tag}`).getByRole("button", { name: /^Actions for/ }).click();
  await page.getByRole("menu").getByRole("menuitem", { name: "Select", exact: true }).click();
  await nameRow(page, `Megger the windings ${tag}`).click();
  await expect(page.getByRole("status").filter({ hasText: "2 selected" })).toBeVisible();
  await expect(page.locator(".tp-row.picked")).toHaveCount(2);
  await nameRow(page, `Megger the windings ${tag}`).getByRole("button", { name: /^Actions for/ }).click();
  // Package 2 tasks… stays at the top level (a greyed item folds into More › first).
  await expect(page.getByRole("menu").first().getByRole("menuitem", { name: "Package 2 tasks…", exact: true })).toBeVisible();
  expect(await sideways(page)).toBeLessThanOrEqual(0);
  await shot(page, "tasks-menu-phone");
  await expectHealthy(page, problems, { label: "tasks packaging phone" });
});
