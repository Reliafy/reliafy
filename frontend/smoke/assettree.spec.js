// The asset tree pane (Assets › Explorer): open and close, the
// levels, the filter that keeps the path to a match, the panel for the row
// picked, the Locations, Items and Flat arrangements, the old Positions,
// Items and Locations addresses, and the phone's slide to the panel and back.
// Each test makes its own small plant through the API.
import { test, expect, open, expectHealthy } from "./health.js";
import { details, headMenu } from "./explorer.js";

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
// The tree's ⋯ menu beside the filter box (the levels, Show only), opened.
async function treeMenu(page) {
  const menu = page.getByRole("menu", { name: "Tree options" });
  if (!(await menu.isVisible())) await page.getByRole("button", { name: /^Tree options/ }).click();
  await expect(menu).toBeVisible();
  return menu;
}
// The Positions / Locations switch in the pane's heading.
const arrangeSwitch = (page) => page.getByRole("radiogroup", { name: "Arrange by" });
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
  const panel = details(page);
  await expect(panel.getByRole("heading", { name: `Tree plant ${tag}` })).toBeVisible();
  await expect(panel.getByText("1 overdue inside")).toBeVisible();
  await expect(panel.getByText("1 open work order inside")).toBeVisible();
  // The heading's two controls, the "…" and Full screen; Open the full page is in the "…".
  await expect(page.locator(".tt-headslot .tt-actions > *")).toHaveCount(2);
  await expect(page.locator(".tt-headslot .tt-actions").getByRole("button", { name: "Full screen", exact: true })).toBeVisible();
  await expect((await headMenu(page)).getByRole("link", { name: "Open the full page" })).toHaveAttribute("href", `/asset-register/positions/${p.top.id}`);
  await page.keyboard.press("Escape");

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
  await expect(details(page).getByRole("heading", { name: `Tree motor ${tag}` })).toBeVisible();
});

test("the Summary: facts, work as rows, what's inside sorted, and the row's own changes", async ({ page, request, problems }) => {
  const tag = `s${Date.now()}`;
  const p = await plant(request, tag);
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.line.id}`);
  const panel = details(page);
  await expect(panel.getByRole("heading", { name: `Tree line ${tag}` })).toBeVisible();

  // Facts: a label/value card; the item fitted links to its page.
  const facts = panel.getByRole("region", { name: "Facts" });
  await expect(facts.getByRole("link", { name: `Tree unit ${tag}` })).toHaveAttribute("href", `/asset-register/items/${p.fitted.id}`);
  await expect(facts).toContainText(`Serial TU-${tag}`);

  // Directly inside: rows with their counts as chips; a row picks it in the tree.
  const inside = panel.getByRole("region", { name: "Directly inside" });
  await expect(inside.getByRole("button", { name: `Tree motor ${tag}` })).toBeVisible();
  await expect(inside.getByText("1 overdue")).toBeVisible();
  await expect(inside.getByRole("button", { name: "New position inside" })).toBeVisible();

  // The row's own changes at the foot.
  await expect(panel.getByRole("button", { name: "Rename…" })).toBeVisible();

  // The motor: its task as a row with an Overdue chip; Delete… offered (a delete takes the item out).
  await inside.getByRole("button", { name: `Tree motor ${tag}` }).click();
  await expect(panel.getByRole("heading", { name: `Tree motor ${tag}` })).toBeVisible();
  const work = panel.getByRole("region", { name: "Work" });
  await expect(work.getByText("Grease")).toBeVisible();
  await expect(work.getByText("Overdue", { exact: true })).toBeVisible();
  await expect(panel.getByRole("button", { name: /^Delete…/ })).toBeEnabled();
  await expectHealthy(page, problems, { label: "the Summary tab" });
});

test("arranged by locations with the switch, and back by positions from the keyboard", async ({ page, request, problems }) => {
  const tag = `b${Date.now()}`;
  const p = await plant(request, tag);
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.line.id}`);
  await expect(page.locator(".side-item.active")).toHaveText("Assets");
  // The heading: Positions / Locations (the one on shown) and «; no + button. The
  // ⋯ menu sits beside the filter box and has no Arrange by.
  const sw = arrangeSwitch(page);
  await expect(sw.getByRole("radio", { name: "Positions" })).toHaveAttribute("aria-checked", "true");
  await expect(sw.getByRole("radio", { name: "Locations" })).toHaveAttribute("aria-checked", "false");
  await expect(page.locator(".tp-title-row").getByRole("button", { name: /^New / })).toHaveCount(0);
  await expect(page.locator(".tp-search-row").getByRole("button", { name: /^Tree options/ })).toBeVisible();
  const menu = await treeMenu(page);
  await expect(menu.getByRole("menuitemradio", { name: "Locations" })).toHaveCount(0);
  await expect(menu.getByRole("menuitem", { name: "Classes" })).toHaveCount(0);
  await page.keyboard.press("Escape");

  await sw.getByRole("radio", { name: "Locations" }).click();
  await expect(page).toHaveURL(/\/asset-register\/explorer\?arrange=locations$/);
  await expect(page.getByRole("tree", { name: "Locations" })).toBeVisible();
  await expect(sw.getByRole("radio", { name: "Locations" })).toHaveAttribute("aria-checked", "true");
  await expect(page.locator(".side-item.active")).toHaveText("Assets");
  // The position picked stays picked, shown inside its location.
  await expect(row(page, `Tree line ${tag}`)).toHaveAttribute("aria-selected", "true");
  await expect(row(page, `Tree site ${tag}`)).toHaveAttribute("aria-expanded", "true");
  await row(page, `Tree site ${tag}`).click();
  const panel = details(page);
  await expect(panel.getByRole("heading", { name: `Tree site ${tag}` })).toBeVisible();
  await expect((await headMenu(page)).getByRole("link", { name: "Open the full page" })).toHaveAttribute("href", `/asset-register/locations/${p.site.id}`);
  await page.keyboard.press("Escape");
  await expectHealthy(page, problems, { label: "arranged by locations" });

  // The spare kept at the site is a row under it; found by serial; opened on its own page.
  await expect(row(page, `Tree spare ${tag}`)).toBeVisible();
  await page.getByLabel("Filter the tree").fill(`SP-${tag}`);
  await expect(page.getByText("1 match, shown with what they're inside")).toBeVisible();
  await row(page, `Tree spare ${tag}`).click();
  await expect(panel.getByText("Placed at")).toBeVisible();
  const full = (await headMenu(page)).getByRole("link", { name: "Open the full page" });
  await expect(full).toHaveAttribute("href", `/asset-register/items/${p.spare.id}`);
  await full.click();
  await expect(page.getByRole("heading", { name: `Tree spare ${tag}` })).toBeVisible();
  // Its breadcrumb goes back to the Explorer, by locations (where it's kept), with it picked.
  await page.getByRole("navigation", { name: "Breadcrumb" }).getByRole("link", { name: "Explorer", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/asset-register/explorer\\?arrange=locations&sel=${p.spare.id}$`));
  await expect(row(page, `Tree spare ${tag}`)).toHaveAttribute("aria-selected", "true");
  await expectHealthy(page, problems, { label: "a spare by locations" });

  // From the keyboard: Tab reaches the radio that's on; ← chooses Positions, the focus stays on it.
  await row(page, `Tree site ${tag}`).click();
  await arrangeSwitch(page).getByRole("radio", { name: "Locations" }).focus();
  await page.keyboard.press("ArrowLeft");
  await expect(page).toHaveURL(/arrange=positions/);
  await expect(page.getByRole("tree", { name: "Positions" })).toBeVisible();
  await expect(arrangeSwitch(page).getByRole("radio", { name: "Positions" })).toBeFocused();
  await expect(arrangeSwitch(page).getByRole("radio", { name: "Positions" })).toHaveAttribute("aria-checked", "true");
  await expectHealthy(page, problems, { label: "back by positions" });
});

test("adding at the top level from the tree's last row, and the old addresses land", async ({ page, request, problems }) => {
  const tag = `d${Date.now()}`;
  const p = await plant(request, tag);
  // Positions: the last row adds a position at the top level, whatever row is picked.
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.line.id}`);
  const add = page.getByRole("button", { name: "New position", exact: true });
  await add.scrollIntoViewIfNeeded();
  await add.click();
  const pdialog = page.getByRole("dialog", { name: "New position" });
  await expect(pdialog).toBeVisible();
  await pdialog.getByRole("button", { name: "Cancel" }).click();
  // Locations: the same for a location, its Inside empty (top level).
  await arrangeSwitch(page).getByRole("radio", { name: "Locations" }).click();
  await row(page, `Tree site ${tag}`).click();
  await page.getByRole("button", { name: "New location", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "New location" });
  await expect(dialog.getByRole("combobox")).toHaveValue("");
  await dialog.getByLabel("Name").fill(`Tree new place ${tag}`);
  await dialog.getByRole("button", { name: "Create" }).click();
  await expect(dialog).toHaveCount(0);
  const made = row(page, `Tree new place ${tag}`);
  await expect(made).toHaveAttribute("aria-selected", "true");
  await expect(made).toHaveAttribute("aria-level", "1");
  // Filtering: no add row (what's added might not match).
  await page.getByLabel("Filter the tree").fill(tag);
  await expect(page.getByRole("button", { name: "New location", exact: true })).toHaveCount(0);
  await expectHealthy(page, problems, { label: "adding at the top level" });

  // The old Positions, Items and Locations pages, with what their addresses carried
  // (Items and Flat are gone: the Items page, and by positions).
  for (const [from, want, entry] of [
    [`/asset-register/positions?sel=${p.line.id}`, `/asset-register/explorer?arrange=positions&sel=${p.line.id}`, "Assets"],
    ["/asset-register/positions?arrange=flat", "/asset-register/explorer?arrange=positions", "Assets"],
    ["/asset-register/explorer?arrange=items", "/asset-register/explorer?arrange=positions", "Assets"],
    ["/asset-register/items", "/items", "Items"],
    [`/asset-register/locations?sel=${p.site.id}`, `/asset-register/explorer?arrange=locations&sel=${p.site.id}`, "Assets"],
    ["/maintenance/items", "/items", "Items"],
  ]) {
    await open(page, from);
    await expect.poll(() => { const u = new URL(page.url()); return u.pathname + u.search; }, { message: from }).toBe(want);
    await expect(page.locator(".side-item.active")).toHaveText(entry);
  }
  await expectHealthy(page, problems, { label: "old addresses" });
});

test("on a phone: the tree, then the panel, and back", async ({ page, request, problems }) => {
  const tag = `c${Date.now()}`;
  const p = await plant(request, tag);
  await page.setViewportSize({ width: 400, height: 860 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.top.id}`);
  const panel = details(page);
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
  // The heading: the switch and its 44 px targets; the search line: the box and ⋯ (44 px).
  for (const name of ["Positions", "Locations"]) {
    const b = await arrangeSwitch(page).getByRole("radio", { name }).boundingBox();
    expect(b.height).toBeGreaterThanOrEqual(44);
    expect(b.x + b.width).toBeLessThanOrEqual(400);
  }
  const dots = await page.getByRole("button", { name: /^Tree options/ }).boundingBox();
  expect(dots.height).toBeGreaterThanOrEqual(44);
  expect(dots.width).toBeGreaterThanOrEqual(44);
  expect(dots.x + dots.width).toBeLessThanOrEqual(400);
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
  const panel = details(page);
  await expect(panel.getByRole("heading", { name: `Ctx pump ${tag}` })).toBeVisible();
  // The description stays the grey line under the name.
  await expect(panel.locator(".td-desc")).toHaveText("Centrifugal pump, 50 L/s");
  const card = panel.getByRole("region", { name: "Operating context" });
  await expect(card.getByRole("heading", { name: "Operating context" })).toBeVisible();
  await expect(card.getByText(CTX_PROMPT)).toBeVisible();
  await expect(card).not.toContainText(/duty/i);

  // Add: in place (the add row ending the section), Save, "✓ Saved", kept with its line breaks.
  await card.getByRole("button", { name: "Add the operating context", exact: true }).click();
  const box = card.getByRole("textbox", { name: "Operating context" });
  await expect(box).toBeFocused();
  await box.fill("Runs 20 hours a day.\nSalt air; summers to 35 °C.");
  await card.getByRole("button", { name: "Save", exact: true }).click();
  await expect(card.getByRole("status")).toHaveText("✓ Saved");
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
  await expect(card.getByRole("status")).toHaveText("✓ Saved");
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pump.id}`);
  await expect(card.locator(".td-ctx-text")).toHaveText("Standby pump; started weekly for an hour.");

  // Long text: clamped, Show all shows it all, Show less folds it again.
  await card.getByRole("button", { name: /^Edit/ }).click();
  await box.fill(Array.from({ length: 12 }, (_, i) => `Line ${i + 1} about the load and the site.`).join("\n"));
  await card.getByRole("button", { name: "Save", exact: true }).click();
  const more = card.getByRole("button", { name: /^Show all/ });
  await expect(more).toBeVisible();
  const clamped = (await card.locator(".td-ctx-text").boundingBox()).height;
  await more.click();
  await expect(card.getByRole("button", { name: /^Show less/ })).toHaveAttribute("aria-expanded", "true");
  expect((await card.locator(".td-ctx-text").boundingBox()).height).toBeGreaterThan(clamped * 1.5);
  await card.getByRole("button", { name: /^Show less/ }).click();
  await expect(more).toBeVisible();

  // Clear: back to the empty state.
  await card.getByRole("button", { name: /^Edit/ }).click();
  await box.fill("");
  await card.getByRole("button", { name: "Save", exact: true }).click();
  await expect(card.getByRole("status")).toHaveText("✓ Cleared");
  await expect(card.getByText(CTX_PROMPT)).toBeVisible();
  await expect.poll(() => contextOf(request, p.pump.id)).toBe("");
  await expectHealthy(page, problems, { label: "the operating context card" });
});

test("items don't get the card, and the RCM tab doesn't show it", async ({ page, request, problems }) => {
  const tag = `i${Date.now()}`;
  const p = await ctxPlant(request, tag);
  await request.patch(`${M}/positions/${p.pump.id}`, { data: { operating_context: `Dusty; runs on demand ${tag}.` } });
  // An item's row: one with no home yet, under Locations.
  const loose = await (await request.post(`${M}/items`, { data: { name: `Ctx loose ${tag}` } })).json();
  await open(page, `/asset-register/explorer?arrange=locations&sel=${loose.id}`);
  const panel = details(page);
  await expect(panel.getByRole("heading", { name: `Ctx loose ${tag}` })).toBeVisible();
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
  await card.getByRole("button", { name: "Add the operating context", exact: true }).click();
  await card.getByRole("textbox", { name: "Operating context" }).fill("Outdoors, wet season flooding; 12 hours a day.");
  const save = card.getByRole("button", { name: "Save", exact: true });
  expect((await save.boundingBox()).height).toBeGreaterThanOrEqual(36);
  expect(await page.evaluate(() => document.documentElement.scrollWidth), "the page scrolls sideways").toBeLessThanOrEqual(400);
  await save.click();
  await expect(card.getByRole("status")).toHaveText("✓ Saved");
  await expect(card.locator(".td-ctx-text")).toHaveText("Outdoors, wet season flooding; 12 hours a day.");
  expect(await page.evaluate(() => document.documentElement.scrollWidth), "the page scrolls sideways").toBeLessThanOrEqual(400);
  await page.goBack();
  await expect(page.getByRole("tree", { name: "Positions" })).toBeVisible();
  await expectHealthy(page, problems, { label: "the operating context card on a phone" });
});
