// The asset tree pane (Operate › Assets › Explorer): open and close, the
// levels, the filter that keeps the path to a match, the panel for the row
// picked, the Locations, Items and Flat arrangements, the old Positions,
// Items and Locations addresses, and the phone's slide to the panel and back.
// Each test makes its own small plant through the API.
import { test, expect, open, expectHealthy } from "./health.js";

const M = "/api/maintenance";

async function plant(request, tag) {
  const post = async (path, data) => {
    const res = await request.post(path, { data });
    expect(res.ok(), `${path}: ${res.status()}`).toBeTruthy();
    return res.json();
  };
  const site = await post(`${M}/locations`, { name: `Tree site ${tag}` });
  const top = await post(`${M}/positions`, { name: `Tree plant ${tag}`, location_id: site.id });
  const line = await post(`${M}/positions`, { name: `Tree line ${tag}`, parent_id: top.id });
  const motor = await post(`${M}/positions`, { name: `Tree motor ${tag}`, parent_id: line.id, position_class: "Electric motor" });
  const seal = await post(`${M}/positions`, { name: `Tree seal ${tag}`, parent_id: motor.id, position_class: "Mechanical seal" });
  await post(`${M}/positions/${motor.id}/tasks`, { name: "Grease", interval: 1, unit: "months", last_done: "2020-01-01" });
  await post(`${M}/work-orders`, { position_id: seal.id, title: `Tree leak ${tag}` });
  // A unit fitted to the line (it has no tasks to restart), and a spare kept at the site.
  await post(`${M}/positions/${line.id}/fit`, { new_item: { name: `Tree unit ${tag}`, serial: `TU-${tag}` } });
  const fitted = (await (await request.get(`${M}/positions/${line.id}`)).json()).fitted.item;
  const spare = await post(`${M}/items`, { name: `Tree spare ${tag}`, serial: `SP-${tag}` });
  await post(`${M}/items/${spare.id}/place`, { location_id: site.id });
  return { site, top, line, motor, seal, fitted, spare };
}

const row = (page, name) => page.getByRole("treeitem", { name: new RegExp(`^${name}`) });
// The tree's ⋯ menu (Arrange by, the levels, Show only), opened.
async function treeMenu(page) {
  const menu = page.getByRole("menu", { name: "Tree options" });
  if (!(await menu.isVisible())) await page.getByRole("button", { name: /^Tree options/ }).click();
  await expect(menu).toBeVisible();
  return menu;
}
// Pick from it, and close it (Esc puts the focus back on its button).
async function fromTreeMenu(page, role, name) {
  const menu = await treeMenu(page);
  await menu.getByRole(role, { name, exact: true }).click();
  await page.keyboard.press("Escape");
  await expect(menu).toHaveCount(0);
}

test("the tree pane: open, close, levels, filter, and the panel for the row picked", async ({ page, request, problems }) => {
  const tag = `a${Date.now()}`;
  const p = await plant(request, tag);
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.top.id}`);
  await expect(page.getByRole("heading", { name: "Explorer", exact: true })).toBeVisible();
  const tree = page.getByRole("tree", { name: "Positions" });
  await expect(tree).toBeVisible();

  // Picked from the address: the panel shows it, with what's inside rolled up.
  const top = row(page, `Tree plant ${tag}`);
  await expect(top).toHaveAttribute("aria-selected", "true");
  const panel = page.getByRole("region", { name: "Details" });
  await expect(panel.getByRole("heading", { name: `Tree plant ${tag}` })).toBeVisible();
  await expect(panel.getByText("1 overdue inside")).toBeVisible();
  await expect(panel.getByText("1 open work order inside")).toBeVisible();
  await expect(panel.getByRole("link", { name: "Open the full page" })).toHaveAttribute("href", `/asset-register/positions/${p.top.id}`);

  // Open and close with the arrow keys, and the levels.
  await top.focus();
  await expect(top).toHaveAttribute("aria-expanded", "true"); // the tops start open
  await page.keyboard.press("ArrowLeft");
  await expect(top).toHaveAttribute("aria-expanded", "false");
  await expect(row(page, `Tree line ${tag}`)).toHaveCount(0);
  await page.keyboard.press("ArrowRight");
  await expect(top).toHaveAttribute("aria-expanded", "true");
  await page.keyboard.press("ArrowRight");
  await expect(row(page, `Tree line ${tag}`)).toBeFocused();
  await expect(row(page, `Tree line ${tag}`)).toHaveAttribute("aria-expanded", "false");
  await page.keyboard.press("ArrowLeft");
  await expect(top).toBeFocused();
  await fromTreeMenu(page, "menuitemradio", "Open everything");
  await expect(row(page, `Tree seal ${tag}`)).toBeVisible();
  await expect(row(page, `Tree seal ${tag}`)).toHaveAttribute("aria-level", "4");
  await fromTreeMenu(page, "menuitemradio", "Open to level 1");
  await expect(row(page, `Tree line ${tag}`)).toHaveCount(0);

  // The filter keeps the path down to a match.
  await page.getByLabel("Filter the tree").fill(`Tree seal ${tag}`);
  await expect(page.getByText("1 match, shown with what they're inside")).toBeVisible();
  for (const name of ["plant", "line", "motor", "seal"]) await expect(row(page, `Tree ${name} ${tag}`)).toBeVisible();
  await row(page, `Tree seal ${tag}`).click();
  await expect(panel.getByRole("heading", { name: `Tree seal ${tag}` })).toBeVisible();
  await expect(panel.getByRole("button", { name: `Tree motor ${tag}` })).toBeVisible(); // the breadcrumb
  await expect(panel.getByRole("link", { name: new RegExp(`Tree leak ${tag}`) })).toBeVisible();
  await page.getByLabel("Filter the tree").fill("");

  // A breadcrumb, then a row in "Directly inside", picks that row in the tree.
  await panel.getByRole("button", { name: `Tree line ${tag}` }).click();
  await expect(panel.getByRole("heading", { name: `Tree line ${tag}` })).toBeVisible();
  await panel.getByRole("button", { name: `Tree motor ${tag}` }).click();
  await expect(panel.getByRole("heading", { name: `Tree motor ${tag}` })).toBeVisible();
  await expect(panel.getByText("1 overdue task")).toBeVisible();
  await expect(row(page, `Tree motor ${tag}`)).toHaveAttribute("aria-selected", "true");
  await expectHealthy(page, problems, { label: "the tree pane" });

  // Remembered: the menu's address comes back to the same arrangement and row.
  await open(page, "/asset-register/explorer");
  await expect(page).toHaveURL(/\/asset-register\/explorer\?arrange=positions$/);
  await expect(row(page, `Tree motor ${tag}`)).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("region", { name: "Details" }).getByRole("heading", { name: `Tree motor ${tag}` })).toBeVisible();
});

test("arranged by locations, by items and flat, and the menu follows", async ({ page, request, problems }) => {
  const tag = `b${Date.now()}`;
  const p = await plant(request, tag);
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.line.id}`);
  await expect(page.locator(".side-subitem.active")).toHaveText("Explorer");
  await fromTreeMenu(page, "menuitemradio", "Locations");
  await expect(page).toHaveURL(/\/asset-register\/explorer\?arrange=locations$/);
  await expect(page.getByRole("tree", { name: "Locations" })).toBeVisible();
  await expect(page.locator(".side-subitem.active")).toHaveText("Explorer");
  // The position picked stays picked, shown inside its location.
  await expect(row(page, `Tree line ${tag}`)).toHaveAttribute("aria-selected", "true");
  await expect(row(page, `Tree site ${tag}`)).toHaveAttribute("aria-expanded", "true");
  await row(page, `Tree site ${tag}`).click();
  const panel = page.getByRole("region", { name: "Details" });
  await expect(panel.getByRole("heading", { name: `Tree site ${tag}` })).toBeVisible();
  await expect(panel.getByRole("link", { name: "Open the full page" })).toHaveAttribute("href", `/asset-register/locations/${p.site.id}`);
  await expectHealthy(page, problems, { label: "arranged by locations" });

  // The spare kept at the site is a row under it.
  await expect(row(page, `Tree spare ${tag}`)).toBeVisible();
  await expectHealthy(page, problems, { label: "arranged by locations" });

  await fromTreeMenu(page, "menuitemradio", "Flat");
  await expect(page).toHaveURL(/\/asset-register\/explorer\?arrange=flat$/);
  await expect(page.locator(".side-subitem.active")).toHaveText("Explorer");
  await expectHealthy(page, problems, { label: "flat" });

  // By items: the line picked becomes the unit fitted there.
  await row(page, `Tree line ${tag}`).click();
  await fromTreeMenu(page, "menuitemradio", "Items");
  await expect(page).toHaveURL(/\/asset-register\/explorer\?arrange=items$/);
  await expect(page.getByRole("tree", { name: "Items" })).toBeVisible();
  const unit = row(page, `Tree unit ${tag}`);
  await expect(unit).toHaveAttribute("aria-selected", "true");
  await expect(panel.getByRole("heading", { name: `Tree unit ${tag}` })).toBeVisible();
  await expect(panel.getByRole("link", { name: `Tree line ${tag}`, exact: true })).toHaveAttribute("href", `/asset-register/positions/${p.line.id}`);
  // Found by serial, spares included; opened on its own page.
  await page.getByLabel("Filter the tree").fill(`SP-${tag}`);
  await expect(page.getByText("1 match, shown with what they're inside")).toBeVisible();
  await row(page, `Tree spare ${tag}`).click();
  await expect(panel.getByText("Placed at")).toBeVisible();
  const full = panel.getByRole("link", { name: "Open the full page" });
  await expect(full).toHaveAttribute("href", `/asset-register/items/${p.spare.id}`);
  await full.click();
  await expect(page.getByRole("heading", { name: `Tree spare ${tag}` })).toBeVisible();
  await expect(page.locator(".side-subitem.active")).toHaveText("Explorer");
  // Its breadcrumb goes back to the Explorer, by items, with it picked.
  await page.getByRole("navigation", { name: "Breadcrumb" }).getByRole("link", { name: "Explorer", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/asset-register/explorer\\?arrange=items&sel=${p.spare.id}$`));
  await expect(row(page, `Tree spare ${tag}`)).toHaveAttribute("aria-selected", "true");
  await expectHealthy(page, problems, { label: "by items" });
});

test("a new item from the Explorer, and the old addresses land on it", async ({ page, request, problems }) => {
  const tag = `d${Date.now()}`;
  const p = await plant(request, tag);
  await open(page, "/asset-register/explorer?arrange=items");
  await page.getByRole("button", { name: "New item" }).click();
  const dialog = page.getByRole("dialog", { name: "New item" });
  await dialog.getByLabel("Name").fill(`Tree new spare ${tag}`);
  await dialog.getByLabel("Serial number (optional)").fill(`NS-${tag}`);
  await dialog.getByLabel("Where it is").selectOption({ label: `Tree site ${tag}` });
  await dialog.getByRole("button", { name: "Create" }).click();
  await expect(dialog).toHaveCount(0);
  const made = row(page, `Tree new spare ${tag}`);
  await expect(made).toHaveAttribute("aria-selected", "true");
  const panel = page.getByRole("region", { name: "Details" });
  await expect(panel.getByRole("link", { name: `Tree site ${tag}` })).toBeVisible();
  await expectHealthy(page, problems, { label: "a new item" });

  // The old Positions, Items and Locations pages, with what their addresses carried.
  for (const [from, want] of [
    [`/asset-register/positions?sel=${p.line.id}`, `/asset-register/explorer?arrange=positions&sel=${p.line.id}`],
    ["/asset-register/positions?arrange=flat", "/asset-register/explorer?arrange=flat"],
    ["/asset-register/items", "/asset-register/explorer?arrange=items"],
    [`/asset-register/locations?sel=${p.site.id}`, `/asset-register/explorer?arrange=locations&sel=${p.site.id}`],
    ["/maintenance/items", "/asset-register/explorer?arrange=items"],
  ]) {
    await open(page, from);
    await expect.poll(() => { const u = new URL(page.url()); return u.pathname + u.search; }, { message: from }).toBe(want);
    await expect(page.locator(".side-subitem.active")).toHaveText("Explorer");
  }
  await expect(row(page, `Tree spare ${tag}`)).toBeVisible();
  await expectHealthy(page, problems, { label: "old addresses" });
});

test("on a phone: the tree, then the panel, and back", async ({ page, request, problems }) => {
  const tag = `c${Date.now()}`;
  const p = await plant(request, tag);
  await page.setViewportSize({ width: 400, height: 860 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.top.id}`);
  const panel = page.getByRole("region", { name: "Details" });
  await expect(page.getByRole("tree", { name: "Positions" })).toBeVisible();
  await expect(panel.getByRole("heading", { name: `Tree plant ${tag}` })).toHaveCount(0);
  await row(page, `Tree plant ${tag}`).locator(".tp-nm").click();
  await expect(panel.getByRole("heading", { name: `Tree plant ${tag}` })).toBeVisible();
  await expect(page.getByRole("tree")).toBeHidden();
  const wide = await page.evaluate(() => document.documentElement.scrollWidth);
  expect(wide, "the page scrolls sideways").toBeLessThanOrEqual(400);
  await page.goBack();
  await expect(page.getByRole("tree", { name: "Positions" })).toBeVisible();
  await expect(row(page, `Tree plant ${tag}`)).toBeVisible();
  // The arrow closes and opens a row without leaving the tree.
  await row(page, `Tree plant ${tag}`).locator(".tp-chev").click();
  await expect(row(page, `Tree line ${tag}`)).toHaveCount(0);
  await row(page, `Tree plant ${tag}`).locator(".tp-chev").click();
  await expect(row(page, `Tree line ${tag}`)).toBeVisible();
  await expect(page.getByRole("tree")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(400);
  // The tree's ⋯ menu: on screen, big enough to tap, and a filter in it works.
  const menu = await treeMenu(page);
  const mbox = await menu.boundingBox();
  expect(mbox.x).toBeGreaterThanOrEqual(0);
  expect(mbox.x + mbox.width).toBeLessThanOrEqual(400);
  const overdue = menu.getByRole("menuitemcheckbox", { name: "Overdue" });
  expect((await overdue.boundingBox()).height).toBeGreaterThanOrEqual(36);
  await overdue.click();
  await expect(overdue).toHaveAttribute("aria-checked", "true");
  await expect(row(page, `Tree motor ${tag}`)).toBeVisible(); // under level 2: the filter opened the way to it
  await expect(page.getByText(/shown with what they're inside · Showing only Overdue$/)).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(400);
  await menu.getByRole("menuitem", { name: "Reset to the usual view" }).click();
  await menu.getByRole("menuitem", { name: "Done" }).click();
  await expect(menu).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Tree options", exact: true })).toBeFocused();
  await expectHealthy(page, problems, { label: "the tree on a phone" });
});

// ---- a position's operating context on the Summary tab ------------------------------------
// The empty state, adding, editing (and cancelling), clearing, the six-line clamp
// with More / Less, a phone, and that items and the RCM tab don't get the card.
const CTX_PROMPT = "How is it used? Describe the load, the environment and the hours it runs.";

async function ctxPlant(request, tag) {
  const post = async (path, data) => {
    const res = await request.post(path, { data });
    expect(res.ok(), `${path}: ${res.status()}`).toBeTruthy();
    return res.json();
  };
  const pump = await post(`${M}/positions`, { name: `Ctx pump ${tag}`, description: "Centrifugal pump, 50 L/s" });
  await post(`${M}/positions/${pump.id}/fit`, { new_item: { name: `Ctx unit ${tag}`, serial: `CU-${tag}` } });
  const fitted = (await (await request.get(`${M}/positions/${pump.id}`)).json()).fitted.item;
  return { pump, fitted };
}

const contextOf = async (request, id) => (await (await request.get(`${M}/positions/${id}`)).json()).operating_context;

test("add, edit, cancel and clear a position's operating context", async ({ page, request, problems }) => {
  const tag = `o${Date.now()}`;
  const p = await ctxPlant(request, tag);
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pump.id}`);
  const panel = page.getByRole("region", { name: "Details" });
  await expect(panel.getByRole("heading", { name: `Ctx pump ${tag}` })).toBeVisible();
  // The description stays the grey line under the name.
  await expect(panel.locator(".td-desc")).toHaveText("Centrifugal pump, 50 L/s");
  const card = panel.getByRole("region", { name: "Operating context" });
  await expect(card.getByRole("heading", { name: "Operating context" })).toBeVisible();
  await expect(card.getByText(CTX_PROMPT)).toBeVisible();
  await expect(card).not.toContainText(/duty/i);

  // Add: in place, Save, "Saved.", kept with its line breaks.
  await card.getByRole("button", { name: "Add", exact: true }).click();
  const box = card.getByRole("textbox", { name: "Operating context" });
  await expect(box).toBeFocused();
  await box.fill("Runs 20 hours a day.\nSalt air; summers to 35 °C.");
  await card.getByRole("button", { name: "Save", exact: true }).click();
  await expect(card.getByRole("status")).toHaveText("Saved.");
  await expect(card.locator(".td-ctx-text")).toHaveText("Runs 20 hours a day.\nSalt air; summers to 35 °C.");
  await expect.poll(() => contextOf(request, p.pump.id)).toBe("Runs 20 hours a day.\nSalt air; summers to 35 °C.");
  await expect(panel.locator(".td-desc")).toHaveText("Centrifugal pump, 50 L/s");

  // Edit, then Cancel (and Esc): nothing changes.
  await card.getByRole("button", { name: /^Edit/ }).click();
  await box.fill("Something else");
  await card.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(card.locator(".td-ctx-text")).toHaveText("Runs 20 hours a day.\nSalt air; summers to 35 °C.");
  await card.getByRole("button", { name: /^Edit/ }).click();
  await box.fill("Something else again");
  await box.press("Escape");
  await expect(card.getByRole("textbox")).toHaveCount(0);
  await expect(card.getByRole("button", { name: /^Edit/ })).toBeFocused();
  expect(await contextOf(request, p.pump.id)).toBe("Runs 20 hours a day.\nSalt air; summers to 35 °C.");

  // Edit and save; still there after a reload.
  await card.getByRole("button", { name: /^Edit/ }).click();
  await box.fill("Standby pump; started weekly for an hour.");
  await card.getByRole("button", { name: "Save", exact: true }).click();
  await expect(card.getByRole("status")).toHaveText("Saved.");
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pump.id}`);
  await expect(card.locator(".td-ctx-text")).toHaveText("Standby pump; started weekly for an hour.");

  // Long text: clamped, More shows it all, Less folds it again.
  await card.getByRole("button", { name: /^Edit/ }).click();
  await box.fill(Array.from({ length: 12 }, (_, i) => `Line ${i + 1} about the load and the site.`).join("\n"));
  await card.getByRole("button", { name: "Save", exact: true }).click();
  const more = card.getByRole("button", { name: /^More/ });
  await expect(more).toBeVisible();
  const clamped = (await card.locator(".td-ctx-text").boundingBox()).height;
  await more.click();
  await expect(card.getByRole("button", { name: /^Less/ })).toHaveAttribute("aria-expanded", "true");
  expect((await card.locator(".td-ctx-text").boundingBox()).height).toBeGreaterThan(clamped * 1.5);
  await card.getByRole("button", { name: /^Less/ }).click();
  await expect(more).toBeVisible();

  // Clear: back to the empty state.
  await card.getByRole("button", { name: /^Edit/ }).click();
  await box.fill("");
  await card.getByRole("button", { name: "Save", exact: true }).click();
  await expect(card.getByRole("status")).toHaveText("Cleared.");
  await expect(card.getByText(CTX_PROMPT)).toBeVisible();
  await expect.poll(() => contextOf(request, p.pump.id)).toBe("");
  await expectHealthy(page, problems, { label: "the operating context card" });
});

test("items don't get the card, and the RCM tab doesn't show it", async ({ page, request, problems }) => {
  const tag = `i${Date.now()}`;
  const p = await ctxPlant(request, tag);
  await request.patch(`${M}/positions/${p.pump.id}`, { data: { operating_context: `Dusty; runs on demand ${tag}.` } });
  await open(page, `/asset-register/explorer?arrange=items&sel=${p.fitted.id}`);
  const panel = page.getByRole("region", { name: "Details" });
  await expect(panel.getByRole("heading", { name: `Ctx unit ${tag}` })).toBeVisible();
  await expect(panel.getByRole("region", { name: "Operating context" })).toHaveCount(0);

  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pump.id}`);
  await expect(panel.getByRole("region", { name: "Operating context" }).getByText(`Dusty; runs on demand ${tag}.`)).toBeVisible();
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pump.id}&tab=rcm`);
  await expect(page.getByRole("treegrid", { name: /and their RCM/ })).toBeVisible();
  await expect(page.getByText(`Dusty; runs on demand ${tag}.`)).toHaveCount(0);
  await expect(page.getByRole("region", { name: "Operating context" })).toHaveCount(0);
  await expectHealthy(page, problems, { label: "items and the RCM tab" });
});

test("on a phone: the card fits and edits in place", async ({ page, request, problems }) => {
  const tag = `p${Date.now()}`;
  const p = await ctxPlant(request, tag);
  await page.setViewportSize({ width: 400, height: 860 });
  await open(page, `/asset-register/explorer?arrange=positions`);
  await page.getByRole("treeitem", { name: new RegExp(`^Ctx pump ${tag}`) }).locator(".tp-nm").click();
  const card = page.getByRole("region", { name: "Details" }).getByRole("region", { name: "Operating context" });
  await card.getByRole("button", { name: "Add", exact: true }).click();
  await card.getByRole("textbox", { name: "Operating context" }).fill("Outdoors, wet season flooding; 12 hours a day.");
  const save = card.getByRole("button", { name: "Save", exact: true });
  expect((await save.boundingBox()).height).toBeGreaterThanOrEqual(36);
  expect(await page.evaluate(() => document.documentElement.scrollWidth), "the page scrolls sideways").toBeLessThanOrEqual(400);
  await save.click();
  await expect(card.getByRole("status")).toHaveText("Saved.");
  await expect(card.locator(".td-ctx-text")).toHaveText("Outdoors, wet season flooding; 12 hours a day.");
  expect(await page.evaluate(() => document.documentElement.scrollWidth), "the page scrolls sideways").toBeLessThanOrEqual(400);
  await page.goBack();
  await expect(page.getByRole("tree", { name: "Positions" })).toBeVisible();
  await expectHealthy(page, problems, { label: "the operating context card on a phone" });
});
