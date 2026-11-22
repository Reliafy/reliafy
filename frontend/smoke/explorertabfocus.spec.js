// Focus tasks in a tab's tree-table (Assets › Explorer, the Maintenance tab's tasks): right-click a
// level, Focus tasks, and that level opens at every level below it (all its tasks show) while every
// other branch closes, still on show. The tree column's header says "Focused: <name>" with Clear
// focus, which puts back what was open before. Nothing is pinned and the address doesn't change.
// At 400 px the same from the row's ⋯, the pill under the search box, nothing scrolling sideways.
// Each test makes its own small plant through the API.
//
// With SMOKE_SHOTS_DIR set, it also saves screenshots there (for the pull request).
import { test, expect, open, expectHealthy, postOk } from "./health.js";

const M = "/api/maintenance";
const SHOTS = process.env.SMOKE_SHOTS_DIR || "";
const shot = async (page, name) => {
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}.png` });
};

async function plant(request, tag) {
  const post = (path, data) => postOk(request, path, data);
  const top = await post(`${M}/positions`, { name: `Focus plant ${tag}` });
  const lineA = await post(`${M}/positions`, { name: `Focus line A ${tag}`, parent_id: top.id });
  const pumpA = await post(`${M}/positions`, { name: `Focus pump A ${tag}`, parent_id: lineA.id });
  const sealA = await post(`${M}/positions`, { name: `Focus seal A ${tag}`, parent_id: pumpA.id });
  const lineB = await post(`${M}/positions`, { name: `Focus line B ${tag}`, parent_id: top.id });
  const pumpB = await post(`${M}/positions`, { name: `Focus pump B ${tag}`, parent_id: lineB.id });
  await post(`${M}/positions/${pumpA.id}/tasks`, { name: `Grease pump A ${tag}`, interval: 3, unit: "months", source: "oem" });
  await post(`${M}/positions/${sealA.id}/tasks`, { name: `Check seal A ${tag}`, interval: 1, unit: "months", source: "oem" });
  await post(`${M}/positions/${pumpB.id}/tasks`, { name: `Grease pump B ${tag}`, interval: 3, unit: "months", source: "oem" });
  return { top, lineA, pumpA, sealA, lineB, pumpB };
}

const nameRow = (page, text) => page.locator(".tp-row", { has: page.locator(".tp-nm", { hasText: text }) });
const trow = (page, name) => page.getByRole("row", { name: new RegExp(`^${name}`) });
const rowMenu = (page, name) => page.getByRole("menu", { name: new RegExp(`^Actions for ${name}`) });
const sideways = (page) => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);

async function openEverything(page) {
  await page.getByRole("button", { name: /^Tree options/ }).click();
  await page.getByRole("menu", { name: "Tree options" }).getByRole("menuitemradio", { name: "Open everything" }).click();
  if (await page.getByRole("menu", { name: "Tree options" }).isVisible()) await page.keyboard.press("Escape");
}

test("the tasks tab: Focus tasks on a mid-level position opens only its branch, every task in it; Clear focus puts it back", async ({ page, request, problems }) => {
  const tag = `f${Date.now()}`;
  const p = await plant(request, tag);
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, `/asset-register/explorer?arrange=positions&root=${p.top.id}&sel=${p.top.id}&tab=maintenance`);
  await expect(page.getByRole("columnheader").first()).toBeVisible();
  await openEverything(page);
  await expect(nameRow(page, `Grease pump B ${tag}`)).toBeVisible();
  await expect(nameRow(page, `Check seal A ${tag}`)).toBeVisible();
  const url = page.url();

  // The level's menu: Focus tasks, then Focus tasks › levels, then Pin this branch.
  await nameRow(page, `Focus line A ${tag}`).locator(".tp-nm").click({ button: "right" });
  const menu = rowMenu(page, `Focus line A ${tag}`);
  await expect(menu.getByRole("menuitem", { name: "Focus tasks", exact: true }).first()).toBeVisible();
  await expect(menu.getByRole("menuitem", { name: "Focus to a depth", exact: true })).toHaveAttribute("aria-haspopup", "menu");
  await expect(menu.getByRole("menuitem", { name: "Pin this branch" })).toBeVisible();
  await shot(page, "tabfocus-1-menu-1440");
  await menu.getByRole("menuitem", { name: "Focus tasks", exact: true }).first().click();

  // Only line A's branch open, down to every task; line B closed but still on show.
  await expect(nameRow(page, `Grease pump A ${tag}`)).toBeVisible();
  await expect(nameRow(page, `Check seal A ${tag}`)).toBeVisible();
  await expect(trow(page, `Focus line B ${tag}`)).toHaveAttribute("aria-expanded", "false");
  await expect(nameRow(page, `Grease pump B ${tag}`)).toHaveCount(0);
  await expect(nameRow(page, `Focus pump B ${tag}`)).toHaveCount(0);
  // It says so, with the way back; nothing pinned, the address as it was.
  const pill = page.locator(".tt-head").getByRole("group", { name: "Focus" });
  await expect(pill).toContainText(`Focused: Focus line A ${tag}`);
  await expect(page.locator(".tt-head").getByRole("group", { name: "Pinned branch" })).toHaveCount(0);
  // The row is picked (?sel=), but nothing is pinned.
  expect(new URL(page.url()).searchParams.get("pin")).toBeNull();
  expect(new URL(page.url()).searchParams.get("root")).toBe(new URL(url).searchParams.get("root"));
  await shot(page, "tabfocus-2-focused-1440");

  // Clear focus: everything open again, as it was before.
  await pill.getByRole("button", { name: "Clear focus" }).click();
  await expect(pill).toHaveCount(0);
  await expect(nameRow(page, `Grease pump B ${tag}`)).toBeVisible();
  await expect(nameRow(page, `Check seal A ${tag}`)).toBeVisible();
  await expectHealthy(page, problems, { label: "focus on the tasks tab", root: ".tx" });
});

test("at 400 px: Focus tasks from the row's ⋯; the pill under the search box; Clear focus from the tree's ⋯", async ({ page, request, problems }) => {
  const tag = `p${Date.now()}`;
  const p = await plant(request, tag);
  await page.setViewportSize({ width: 400, height: 860 });
  await open(page, `/asset-register/explorer?arrange=positions&root=${p.top.id}&sel=${p.top.id}&tab=maintenance`);
  await expect(nameRow(page, `Focus line A ${tag}`)).toBeVisible();
  await openEverything(page);
  await expect(nameRow(page, `Grease pump B ${tag}`)).toBeVisible();
  await nameRow(page, `Focus line A ${tag}`).getByRole("button", { name: /^Actions for / }).click();
  await rowMenu(page, `Focus line A ${tag}`).getByRole("menuitem", { name: "Focus tasks", exact: true }).first().click();
  await expect(nameRow(page, `Check seal A ${tag}`)).toBeVisible();
  await expect(nameRow(page, `Grease pump B ${tag}`)).toHaveCount(0);
  await expect(page.getByRole("group", { name: "Focus" })).toContainText(`Focused: Focus line A ${tag}`);
  expect(await sideways(page)).toBeLessThanOrEqual(0);
  await shot(page, "tabfocus-3-focused-400");
  // The tree's ⋯ menu offers Clear focus too.
  await page.getByRole("button", { name: /^Tree options/ }).click();
  await page.getByRole("menu", { name: "Tree options" }).getByRole("menuitem", { name: "Clear focus" }).click();
  await expect(page.getByRole("group", { name: "Focus" })).toHaveCount(0);
  await expect(nameRow(page, `Grease pump B ${tag}`)).toBeVisible();
  await expectHealthy(page, problems, { label: "focus on the tasks tab at 400 px", root: ".tx" });
});
