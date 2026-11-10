// The Explorer by Classes on one asset's tree, and a class's one tab. Two
// assets carry items of one item class; opened on one of them (?root=), the
// class tree, its count, "No class" and the class's fleet cover only the
// positions inside that asset, while the whole Explorer covers both. A class
// row has a tab bar with one tab, Condition monitoring: its fleet.
import { test, expect, open, expectHealthy, postOk } from "./health.js";
import { details, reveal } from "./explorer.js";

const M = "/api/maintenance";
const SHOTS = process.env.SMOKE_SHOTS_DIR || "";
const shot = async (page, name) => {
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}.png` });
};
const sideways = (page) => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
const row = (page, name) => page.getByRole("treeitem", { name: new RegExp(`^${name}`) });
const arrangeSwitch = (page) => page.getByRole("radiogroup", { name: "Arrange by" });

// One asset: a top position with `n` pump positions under it, each with an item of the class fitted.
async function asset(request, name, tag, cls, n) {
  const top = await postOk(request, `${M}/positions`, { name: `${name} ${tag}` });
  const pumps = [];
  for (let i = 1; i <= n; i += 1) {
    const pos = await postOk(request, `${M}/positions`, { name: `${name} pump ${i} ${tag}`, parent_id: top.id });
    await postOk(request, `${M}/positions/${pos.id}/fit`, { new_item: { name: `${name} pump unit ${i} ${tag}`, serial: `${name}-${i}-${tag}` } });
    const item = (await (await request.get(`${M}/positions/${pos.id}`)).json()).fitted.item;
    await postOk(request, `${M}/item-classes/assign`, { target_id: item.id, item_class_id: cls.id });
    pumps.push(pos);
  }
  return { top, pumps };
}

test("Classes on one asset's tree covers only that asset; a class opens on Condition monitoring", async ({ page, request, problems }) => {
  const tag = `c${Date.now()}`;
  const cls = await postOk(request, `${M}/item-classes`, { name: `Dosing pump ${tag}` });
  const north = await asset(request, "North", tag, cls, 2);
  const south = await asset(request, "South", tag, cls, 1);
  const clsKey = `cls:${cls.id}`;
  const classRow = row(page, `Dosing pump ${tag}`);
  const panel = details(page);

  // Every asset: the class counts the three positions, and its fleet lists them.
  await open(page, `/asset-register/explorer?arrange=classes&sel=${encodeURIComponent(clsKey)}`);
  await reveal(page, classRow);
  await expect(classRow).toHaveAttribute("aria-selected", "true");
  await expect(classRow.locator(".tp-cnt")).toHaveText("3 positions");
  await expect(page.locator(".cf-answer")).toContainText("3 positions");

  // A class has a tab bar with one tab, picked without being asked for.
  const tabs = panel.getByRole("tab");
  await expect(tabs).toHaveCount(1);
  await expect(tabs).toHaveText("Condition monitoring");
  await expect(tabs).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("region", { name: "Risk now" })).toBeVisible();

  // One asset opened: Classes is offered, and covers only what's inside it.
  await open(page, `/asset-register/explorer?arrange=positions&root=${north.top.id}`);
  const sw = arrangeSwitch(page);
  await expect(sw.getByRole("radio", { name: "Positions" })).toHaveAttribute("aria-checked", "true");
  await sw.getByRole("radio", { name: "Locations" }).click();
  await expect(page).toHaveURL(/arrange=locations/);
  await sw.getByRole("radio", { name: "Classes" }).click();
  await expect(page).toHaveURL(new RegExp(`root=${north.top.id}`));
  await expect(page).toHaveURL(/arrange=classes/);
  await expect(page.getByRole("tree", { name: "Classes" })).toBeVisible();
  await expect(classRow.locator(".tp-cnt")).toHaveText("2 positions");
  await expect(row(page, `South pump 1 ${tag}`)).toHaveCount(0);
  // "No class": the asset's own top position, and nothing from the rest of the register.
  const noClass = row(page, "No class");
  await expect(noClass).toBeVisible();
  await expect(page.getByRole("treeitem")).toHaveCount(5); // the class, its two positions, No class, the top
  await classRow.click();
  await expect(page.locator(".cf-answer")).toContainText("2 positions");
  const fleet = page.getByRole("region", { name: "Risk now" });
  await expect(fleet.getByRole("button", { name: `North pump 1 ${tag}` })).toBeVisible();
  await expect(fleet.getByRole("button", { name: `North pump 2 ${tag}` })).toBeVisible();
  await expect(fleet.getByRole("button", { name: `South pump 1 ${tag}` })).toHaveCount(0);
  await expect(fleet).toContainText("None of these positions has a condition and life model");
  await shot(page, "classes-one-asset-1440");

  // The address holds through a reload.
  await page.reload();
  await expect(sw.getByRole("radio", { name: "Classes" })).toHaveAttribute("aria-checked", "true");
  await expect(classRow.locator(".tp-cnt")).toHaveText("2 positions");
  await expect(page.locator(".cf-answer")).toContainText("2 positions");
  // From the class to one of its positions: the position's Summary, with its own tabs.
  await fleet.getByRole("button", { name: `North pump 1 ${tag}` }).click();
  await expect(row(page, `North pump 1 ${tag}`)).toHaveAttribute("aria-selected", "true");
  await expect(panel.getByRole("tab", { name: "Summary" })).toHaveAttribute("aria-selected", "true");
  await expect(panel.getByRole("tab", { name: "Condition monitoring" })).toHaveCount(0);

  // Another tab in the address: the class still shows its own, and a position walked to shows the one asked for.
  await open(page, `/asset-register/explorer?arrange=classes&root=${north.top.id}&sel=${encodeURIComponent(clsKey)}&tab=reports`);
  await expect(panel.getByRole("tab", { name: "Condition monitoring" })).toHaveAttribute("aria-selected", "true");
  await expect(page.locator(".cf-answer")).toContainText("2 positions");
  await fleet.getByRole("button", { name: `North pump 2 ${tag}` }).click();
  await expect(row(page, `North pump 2 ${tag}`)).toHaveAttribute("aria-selected", "true");
  await expect(panel.getByRole("tab", { name: "Failure reports" })).toHaveAttribute("aria-selected", "true");

  // A tree-table's tab in the address (they're by position) doesn't take the tree off the class.
  await open(page, `/asset-register/explorer?arrange=classes&root=${north.top.id}&sel=${encodeURIComponent(clsKey)}&tab=rcm`);
  await expect(sw.getByRole("radio", { name: "Classes" })).toHaveAttribute("aria-checked", "true");
  await expect(classRow).toHaveAttribute("aria-selected", "true");
  await expect(panel.getByRole("tab", { name: "Condition monitoring" })).toHaveAttribute("aria-selected", "true");
  await expect(page.locator(".cf-answer")).toContainText("2 positions");

  // Show every asset: the whole register by Classes again.
  await page.getByRole("link", { name: "Show every asset" }).click();
  await expect(page).not.toHaveURL(/root=/);
  await reveal(page, classRow);
  await expect(classRow.locator(".tp-cnt")).toHaveText("3 positions");

  await expectHealthy(page, problems, { label: "the Explorer by Classes on one asset" });
});

test("a class on a phone: its heading, its one tab and the way back fit 400 px", async ({ page, request, problems }) => {
  const tag = `p${Date.now()}`;
  const cls = await postOk(request, `${M}/item-classes`, { name: `Transfer pump ${tag}` });
  const north = await asset(request, "East", tag, cls, 2);
  await page.setViewportSize({ width: 400, height: 800 });
  await open(page, `/asset-register/explorer?arrange=classes&root=${north.top.id}`);
  await expect(arrangeSwitch(page).getByRole("radio", { name: "Classes" })).toHaveAttribute("aria-checked", "true");
  await expect.poll(() => sideways(page)).toBeLessThanOrEqual(0);
  await shot(page, "classes-one-asset-tree-400");
  await row(page, `Transfer pump ${tag}`).locator(".tp-nm").click();
  const panel = page.getByRole("region", { name: "Details" });
  await expect(panel.getByRole("heading", { name: `Transfer pump ${tag}` })).toBeVisible();
  await expect(panel.getByRole("button", { name: /Explorer/ })).toBeVisible();
  const tabs = panel.getByRole("tab");
  await expect(tabs).toHaveCount(1);
  await expect(tabs).toHaveText("Condition monitoring");
  await expect(panel.locator(".cf-answer")).toContainText("2 positions");
  await expect.poll(() => sideways(page)).toBeLessThanOrEqual(0);
  await shot(page, "class-condition-tab-400");
  // The way back: the tree again, by Classes, on the same asset.
  await panel.getByRole("button", { name: /Explorer/ }).click();
  await expect(row(page, `Transfer pump ${tag}`)).toBeVisible();
  await expect(page).toHaveURL(/arrange=classes/);
  await expectHealthy(page, problems, { label: "a class on a phone" });
});
