// A position is a position at every depth (Derryn, 23 Nov 2026): a place opened on its own shows
// its positions under the positions above them (House > Climate control > the bedroom's air
// conditioner > its filter), and those higher rows get the whole position menu, enabled, on the
// Maintenance and RCM tabs as everywhere, never a menu of greyed items. Focus › is two sections
// under small labels, What and Depth; the arrow keys pass over the labels. At 400 px the ⋯ menu
// opens the same, the submenu in place.
//
// With SMOKE_SHOTS_DIR set, it also saves screenshots there (for the pull request).
import { test, expect, open, expectHealthy, postOk } from "./health.js";

const M = "/api/maintenance";
const SHOTS = process.env.SMOKE_SHOTS_DIR || "";
const shot = async (page, name) => {
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}.png` });
};
const GENERAL = ["Open", "Rename…", "Move to…", "Focus", "Pin this branch", "Copy link"];
const row = (page, name) => page.locator(".tp-row", { has: page.locator(".tp-nm", { hasText: name }) }).first();
const sideways = (page) => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
async function shape(menu) {
  return menu.evaluate((el) => [...el.children].map((c) => (c.getAttribute("role") === "separator" ? "———"
    : (c.dataset.label || c.textContent || "").trim())).filter(Boolean));
}

async function house(request, tag) {
  const post = (path, data) => postOk(request, path, data);
  const bedroom = await post(`${M}/locations`, { name: `Bedroom ${tag}` });
  const top = await post(`${M}/positions`, { name: `House ${tag}` });
  const climate = await post(`${M}/positions`, { name: `Climate control ${tag}`, parent_id: top.id });
  const ac = await post(`${M}/positions`, { name: `Air conditioner ${tag}`, parent_id: climate.id, location_id: bedroom.id });
  const filter = await post(`${M}/positions`, { name: `Filter ${tag}`, parent_id: ac.id });
  const clean = await post(`${M}/positions/${ac.id}/tasks`, { name: `Clean the coils ${tag}`, interval: 6, unit: "months" });
  const swap = await post(`${M}/positions/${filter.id}/tasks`, { name: `Swap the filter ${tag}`, interval: 3, unit: "months" });
  await post(`${M}/packages`, { name: `Service visit ${tag}`, position_id: ac.id, every: 6, unit: "months", tasks: [clean.id, swap.id] });
  const fn = await post(`${M}/positions/${ac.id}/functions`, { text: `Cool the room ${tag}` });
  const ff = await post(`${M}/functions/${fn.id}/failures`, { text: `No cooling ${tag}` });
  await post(`${M}/positions/${ac.id}/failure-modes`, { text: `Refrigerant leak ${tag}`, functional_failure_id: ff.id });
  return { bedroom, top, climate, ac, filter };
}

async function expectPositionMenu(menu) {
  const s = await shape(menu);
  expect(s.slice(0, 6)).toEqual(GENERAL);
  expect(s.at(-1)).toBe("Delete…");
  // Every general item that applies can be used: none says it's a heading.
  await expect(menu).not.toContainText("A heading for the rows");
  for (const name of ["Open", "Rename…", "Focus", "Pin this branch", "Copy link", "Delete…"]) {
    await expect(menu.getByRole("menuitem", { name, exact: true })).not.toHaveAttribute("aria-disabled", "true");
  }
  return s;
}

test("a higher position gets the whole position menu on Maintenance and RCM; Focus › in What and Depth", async ({ page, request, problems }) => {
  const tag = `h${Date.now()}`;
  const h = await house(request, tag);
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, `/asset-register/explorer?arrange=positions&root=${h.bedroom.id}&tab=maintenance`);
  await expect(row(page, `House ${tag}`)).toBeVisible();

  // Maintenance: House (two levels above the place's position) has a position's menu.
  await row(page, `House ${tag}`).locator(".tp-nm").click({ button: "right" });
  let menu = page.getByRole("menu").first();
  await expect(menu).toBeVisible();
  const s = await expectPositionMenu(menu);
  expect(s).toEqual(expect.arrayContaining(["Add task…", "Open in", "Package the tasks…"]));
  await shot(page, "maintenance-top-position-menu-1440");

  // Focus ›: What (tasks, packages), a line, Depth (as deep as House goes: 4); the labels aren't items.
  await menu.getByRole("menuitem", { name: "Focus", exact: true }).hover();
  let sub = page.getByRole("menu", { name: "Focus", exact: true });
  await expect(sub.locator(".row-menu-heading")).toHaveText(["What", "Depth"]);
  await expect(sub.getByRole("menuitem")).toHaveText(["Focus tasks", "Focus packages", "1 level", "2 levels", "3 levels", "4 levels"]);
  await shot(page, "maintenance-focus-submenu-1440");
  // The keyboard passes over the labels and the line.
  await menu.getByRole("menuitem", { name: "Focus", exact: true }).focus();
  await page.keyboard.press("ArrowRight");
  await expect(sub.getByRole("menuitem", { name: "Focus tasks" })).toBeFocused();
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("ArrowDown");
  await expect(sub.getByRole("menuitem", { name: "1 level" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("menu")).toHaveCount(0);
  await expect(row(page, `Climate control ${tag}`)).toBeVisible();

  // Focus packages: the way down to the package opened, the package itself a leaf.
  await row(page, `House ${tag}`).locator(".tp-nm").click({ button: "right" });
  await page.getByRole("menu").first().getByRole("menuitem", { name: "Focus", exact: true }).hover();
  await page.getByRole("menu", { name: "Focus", exact: true }).getByRole("menuitem", { name: "Focus packages" }).click();
  await expect(row(page, `Service visit ${tag}`)).toBeVisible();

  // RCM: the same menu on House; Focus › names the RCM's kinds.
  await open(page, `/asset-register/explorer?arrange=positions&root=${h.bedroom.id}&tab=rcm`);
  await expect(row(page, `House ${tag}`)).toBeVisible();
  await row(page, `House ${tag}`).locator(".tp-nm").click({ button: "right" });
  menu = page.getByRole("menu").first();
  await expectPositionMenu(menu);
  await shot(page, "rcm-top-position-menu-1440");
  await menu.getByRole("menuitem", { name: "Focus", exact: true }).hover();
  sub = page.getByRole("menu", { name: "Focus", exact: true });
  await expect(sub.locator(".row-menu-heading")).toHaveText(["What", "Depth"]);
  await expect(sub.getByRole("menuitem", { name: "Focus functions" })).toBeVisible();
  await expect(sub.getByRole("menuitem", { name: "Focus failure modes" })).toBeVisible();
  await shot(page, "rcm-focus-submenu-1440");
  await sub.getByRole("menuitem", { name: "Focus functions" }).click();
  await expect(page.getByRole("row", { name: new RegExp(`^Function: Cool the room ${tag}`) })).toBeVisible();
  await expect(page.getByRole("row", { name: new RegExp(`^Function: Cool the room ${tag}`) })).toHaveAttribute("aria-expanded", "false");
  await expectHealthy(page, problems, { label: "higher position menus", root: ".tx" });
});

test("at 400 px: the ⋯ menu on a higher position is the whole menu, Focus › opens in place with its labels", async ({ page, request, problems }) => {
  const tag = `p${Date.now()}`;
  const h = await house(request, tag);
  await page.setViewportSize({ width: 400, height: 860 });
  for (const tab of ["maintenance", "rcm"]) {
    await open(page, `/asset-register/explorer?arrange=positions&root=${h.bedroom.id}&tab=${tab}`);
    await expect(row(page, `House ${tag}`)).toBeVisible();
    await row(page, `House ${tag}`).getByRole("button", { name: /^Actions for / }).click();
    const menu = page.getByRole("menu").first();
    await expectPositionMenu(menu);
    const mb = await menu.boundingBox();
    expect(mb.x + mb.width).toBeLessThanOrEqual(400);
    await shot(page, `${tab}-top-position-menu-400`);
    await menu.getByRole("menuitem", { name: "Focus", exact: true }).click();
    const group = menu.getByRole("group", { name: "Focus", exact: true });
    await expect(group.locator(".row-menu-heading")).toHaveText(["What", "Depth"]);
    await shot(page, `${tab}-focus-submenu-400`);
    expect(await sideways(page)).toBe(0);
    await page.keyboard.press("Escape");
    await page.keyboard.press("Escape");
  }
  await expectHealthy(page, problems, { label: "higher position menus at 400 px" });
});
