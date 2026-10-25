// The Explorer's row menu on the Summary tab (Operate › Assets › Explorer):
// right-click a row, its ⋯ button, or Shift+F10. New position inside (the +
// button's dialog, "Inside" set to the row), Rename…, Move to… (a picker of
// the new parent: never the row itself or anything inside it; the row shown
// in its new place and kept picked), Retire… (a confirm naming it; greyed with
// the reason when something is fitted, positions are inside or work is open),
// and Pin this branch as before. A refusal from the server shows its reason
// in the dialog. Locations: new inside, rename, move. The RCM tab keeps its
// own menu. At 400 px the ⋯ opens it and nothing scrolls sideways.
// Each test makes its own small plant through the API.
//
// With SMOKE_SHOTS_DIR set, it also saves screenshots there (for the pull request).
import { test, expect, open, expectHealthy } from "./health.js";

const M = "/api/maintenance";
const SHOTS = process.env.SMOKE_SHOTS_DIR || "";
const shot = async (page, name) => {
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}.png` });
};

// `small`: the locations and two positions only (fewer changes: the smoke
// suite runs near the server's limit of changes a minute).
async function plant(request, tag, { small = false } = {}) {
  const post = async (path, data) => {
    const res = await request.post(path, { data });
    expect(res.ok(), `${path}: ${res.status()} ${await res.text()}`).toBeTruthy();
    return res.json();
  };
  const site = await post(`${M}/locations`, { name: `Menu site ${tag}` });
  const shed = await post(`${M}/locations`, { name: `Menu shed ${tag}`, parent_id: site.id });
  const store = await post(`${M}/locations`, { name: `Menu store ${tag}`, parent_id: site.id });
  const pool = await post(`${M}/positions`, { name: `Menu pool ${tag}`, location_id: site.id });
  const circ = await post(`${M}/positions`, { name: `Menu circulation ${tag}`, parent_id: pool.id });
  if (small) return { site, shed, store, pool, circ };
  const pump = await post(`${M}/positions`, { name: `Menu pump ${tag}`, parent_id: circ.id });
  const valve = await post(`${M}/positions`, { name: `Menu valve ${tag}`, parent_id: circ.id });
  const heat = await post(`${M}/positions`, { name: `Menu heating ${tag}`, parent_id: pool.id });
  const skim = await post(`${M}/positions`, { name: `Menu skimmer ${tag}`, parent_id: circ.id });
  await post(`${M}/positions/${pump.id}/fit`, { new_item: { name: `Menu unit ${tag}`, serial: `MU-${tag}` } });
  await post(`${M}/work-orders`, { position_id: valve.id, title: `Menu valve check ${tag}` });
  return { site, shed, store, pool, circ, pump, valve, heat, skim };
}

const row = (page, name) => page.getByRole("treeitem", { name: new RegExp(`^${name}`) });
const rowMenu = (page, name) => page.getByRole("menu", { name: new RegExp(`^Actions for ${name}`) });
const query = (page) => new URL(page.url()).searchParams;
async function menuOf(page, name) {
  await row(page, name).locator(".tp-nm").click({ button: "right" });
  const menu = rowMenu(page, name);
  await expect(menu).toBeVisible();
  return menu;
}

test("Summary row menu: new inside, rename, move to…, retire, pin; the server's refusals in words", async ({ page, request, problems }) => {
  const tag = `m${Date.now()}`;
  const p = await plant(request, tag);
  await page.setViewportSize({ width: 1280, height: 720 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.skim.id}`); // the way down to it opens
  await expect(row(page, `Menu skimmer ${tag}`)).toHaveAttribute("aria-selected", "true");

  // The menu: the changes, then Pin this branch, then Retire (greyed: positions are inside it).
  let menu = await menuOf(page, `Menu circulation ${tag}`);
  await expect(menu.getByRole("menuitem")).toHaveText(["New position inside", "Rename…", "Move to…", "Pin this branch", /^Retire…/]);
  await expect(menu.getByRole("menuitem", { name: "New position inside" })).toBeFocused();
  const retire = menu.getByRole("menuitem", { name: "Retire…" });
  await expect(retire).toHaveAttribute("aria-disabled", "true");
  await expect(retire).toHaveAccessibleDescription("3 positions are inside it. Move or retire them first.");
  await shot(page, "rowmenu-1-summary-row-menu-1280");
  await retire.click({ force: true }); // greyed: nothing happens, the menu stays
  await expect(menu).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(menu).toHaveCount(0);
  await expect(row(page, `Menu circulation ${tag}`)).toBeFocused();

  // Fitted, open work: greyed with the reason too.
  menu = await menuOf(page, `Menu pump ${tag}`);
  await expect(menu.getByRole("menuitem", { name: "Retire…" })).toHaveAccessibleDescription(/Something is fitted here/);
  await page.keyboard.press("Escape");
  menu = await menuOf(page, `Menu valve ${tag}`);
  await expect(menu.getByRole("menuitem", { name: "Retire…" })).toHaveAccessibleDescription(/open work orders/);
  await page.keyboard.press("Escape");

  // New position inside: the + button's dialog, Inside set to the row; the new row is picked inside it.
  menu = await menuOf(page, `Menu heating ${tag}`);
  await menu.getByRole("menuitem", { name: "New position inside" }).click();
  let dialog = page.getByRole("dialog", { name: "New position" });
  await expect(dialog.getByRole("combobox").first()).toHaveValue(p.heat.id);
  await dialog.getByRole("textbox").first().fill(`Menu heater ${tag}`);
  await dialog.getByRole("button", { name: "Create position" }).click();
  await expect(dialog).toHaveCount(0);
  await expect(row(page, `Menu heater ${tag}`)).toHaveAttribute("aria-selected", "true");
  await expect(row(page, `Menu heater ${tag}`)).toHaveAttribute("aria-level", "3");

  // Rename… (Shift+F10 from the row): the dialog, the row renamed and still picked.
  await row(page, `Menu skimmer ${tag}`).click();
  await row(page, `Menu skimmer ${tag}`).press("Shift+F10");
  menu = rowMenu(page, `Menu skimmer ${tag}`);
  await menu.getByRole("menuitem", { name: "Rename…" }).click();
  dialog = page.getByRole("dialog", { name: "Rename this position" });
  await expect(dialog.getByRole("textbox")).toHaveValue(`Menu skimmer ${tag}`);
  await dialog.getByRole("textbox").fill(`Menu skimmer box ${tag}`);
  // Sent once: a double-click while the server is slow sends one change; the button says so meanwhile.
  let renames = 0;
  await page.route(`**${M}/positions/${p.skim.id}`, async (route) => {
    if (route.request().method() !== "PATCH") return route.fallback();
    renames += 1;
    await new Promise((done) => setTimeout(done, 600));
    return route.continue();
  });
  await dialog.getByRole("button", { name: "Rename" }).dblclick();
  await expect(dialog.getByRole("button", { name: "Renaming…" })).toBeDisabled();
  await expect(dialog).toHaveCount(0);
  expect(renames).toBe(1);
  await page.unroute(`**${M}/positions/${p.skim.id}`);
  await expect(row(page, `Menu skimmer box ${tag}`)).toHaveAttribute("aria-selected", "true");
  await expect(page.locator(".tt-headslot")).toContainText(`Renamed it “Menu skimmer box ${tag}”.`);

  // Move to…: never the row itself or anything inside it; moved, shown in its new place, still picked.
  menu = await menuOf(page, `Menu circulation ${tag}`);
  await menu.getByRole("menuitem", { name: "Move to…" }).click();
  dialog = page.getByRole("dialog", { name: `Move “Menu circulation ${tag}”` });
  const picker = dialog.getByRole("combobox");
  const options = await picker.locator("option").allTextContents();
  expect(options.some((o) => o.includes(`Menu pump ${tag}`))).toBe(false);
  expect(options.some((o) => o.trim() === `Menu circulation ${tag}`)).toBe(false);
  expect(options.some((o) => o.includes(`Menu pool ${tag} (where it is now)`))).toBe(true);
  await expect(dialog.getByRole("button", { name: "Move" })).toBeDisabled(); // where it is now: nothing to do
  await picker.selectOption(p.heat.id);
  await expect(dialog.getByRole("button", { name: "Move" })).toBeEnabled();
  await shot(page, "rowmenu-2-move-to-picker-1280");
  await dialog.getByRole("button", { name: "Move" }).click();
  await expect(dialog).toHaveCount(0);
  const moved = row(page, `Menu circulation ${tag}`);
  await expect(moved).toHaveAttribute("aria-selected", "true");
  await expect(moved).toHaveAttribute("aria-level", "3");
  await expect(row(page, `Menu pump ${tag}`)).toHaveAttribute("aria-level", "4"); // what's inside came with it
  await expect(page.locator(".tt-headslot")).toContainText(`Moved it inside “Menu heating ${tag}”.`);
  await expect(page.locator(".tt-headslot").getByRole("button", { name: `Menu heating ${tag}` })).toBeVisible();

  // The server refuses a move: its reason, in the dialog, which stays open.
  await page.route(`**${M}/positions/${p.heat.id}`, (route) => (route.request().method() === "PATCH"
    ? route.fulfill({ status: 422, json: { detail: "A position can't sit inside itself." } }) : route.fallback()));
  menu = await menuOf(page, `Menu heating ${tag}`);
  await menu.getByRole("menuitem", { name: "Move to…" }).click();
  dialog = page.getByRole("dialog", { name: `Move “Menu heating ${tag}”` });
  await dialog.getByRole("combobox").selectOption(""); // the top level
  await expect(dialog.getByRole("button", { name: "Move" })).toBeEnabled();
  await dialog.getByRole("button", { name: "Move" }).click();
  await expect(dialog).toContainText("A position can't sit inside itself.");
  await dialog.getByRole("button", { name: "Cancel" }).click();
  await page.unroute(`**${M}/positions/${p.heat.id}`);

  // Retire…: a confirm naming it; gone, the row it was inside picked.
  menu = await menuOf(page, `Menu heater ${tag}`);
  await menu.getByRole("menuitem", { name: "Retire…" }).click();
  dialog = page.getByRole("dialog", { name: `Retire “Menu heater ${tag}”?` });
  await expect(dialog).toContainText("Its history stays");
  await dialog.getByRole("button", { name: "Retire position" }).click();
  await expect(dialog).toHaveCount(0);
  await expect(row(page, `Menu heater ${tag}`)).toHaveCount(0);
  await expect(row(page, `Menu heating ${tag}`)).toHaveAttribute("aria-selected", "true");

  // The server refuses a retire (work opened since the tree was read): its reason and what to do.
  await page.route(`**${M}/positions/${p.skim.id}/retire`, (route) => route.fulfill({
    status: 422, json: { detail: "It has open work orders. Close or cancel them first." } }));
  menu = await menuOf(page, `Menu skimmer box ${tag}`);
  await menu.getByRole("menuitem", { name: "Retire…" }).click();
  dialog = page.getByRole("dialog", { name: `Retire “Menu skimmer box ${tag}”?` });
  await dialog.getByRole("button", { name: "Retire position" }).click();
  await expect(dialog).toContainText("It has open work orders. Close or cancel them first.");
  await dialog.getByRole("button", { name: "Cancel" }).click();
  await expect(row(page, `Menu skimmer box ${tag}`)).toBeVisible();

  // Pin this branch still works from the same menu.
  menu = await menuOf(page, `Menu heating ${tag}`);
  await menu.getByRole("menuitem", { name: "Pin this branch" }).click();
  await expect.poll(() => query(page).get("pin")).toBe(p.heat.id);

  // The RCM tab keeps its own menu (no Rename… or Move to… there).
  await page.getByRole("tab", { name: "RCM" }).click();
  const trow = page.getByRole("row", { name: new RegExp(`^Menu heating ${tag}`) });
  await trow.locator(".tt-tree").click({ button: "right" });
  await expect(rowMenu(page, `Menu heating ${tag}`).getByRole("menuitem")).toHaveText(["Add function", "Import worksheet…", "Export CSV", "Show whole tree"]);
  await page.keyboard.press("Escape");
  // The refusals above were made up here (a 422 each): the browser logs them.
  problems.splice(0, problems.length, ...problems.filter((x) => !/status of 422/.test(x)));
  await expectHealthy(page, problems, { label: "summary row menu", root: ".tx" });
});

test("Locations: a location's menu has new inside, rename and move; at 400 px the ⋯ opens the menu", async ({ page, request, problems }) => {
  const tag = `l${Date.now()}`;
  const p = await plant(request, tag, { small: true });
  await page.setViewportSize({ width: 1280, height: 720 });
  await open(page, `/asset-register/explorer?arrange=locations&sel=${p.shed.id}`);
  let menu = await menuOf(page, `Menu shed ${tag}`);
  await expect(menu.getByRole("menuitem")).toHaveText(["New location inside", "Rename…", "Move to…", "Pin this branch"]);
  await menu.getByRole("menuitem", { name: "Move to…" }).click();
  const dialog = page.getByRole("dialog", { name: `Move “Menu shed ${tag}”` });
  await dialog.getByRole("combobox").selectOption(p.store.id);
  await dialog.getByRole("button", { name: "Move" }).click();
  await expect(dialog).toHaveCount(0);
  await expect(row(page, `Menu shed ${tag}`)).toHaveAttribute("aria-selected", "true");
  await expect(row(page, `Menu shed ${tag}`)).toHaveAttribute("aria-level", "3");
  menu = await menuOf(page, `Menu shed ${tag}`);
  await menu.getByRole("menuitem", { name: "New location inside" }).click();
  const create = page.getByRole("dialog", { name: "New location" });
  await expect(create.getByRole("combobox")).toHaveValue(p.shed.id);
  await create.getByRole("button", { name: "Cancel" }).click();

  // A phone: the ⋯ button opens the same menu; nothing scrolls sideways.
  await page.setViewportSize({ width: 400, height: 860 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pool.id}`);
  const more = row(page, `Menu circulation ${tag}`).getByRole("button", { name: "Actions", exact: true });
  await more.click();
  menu = rowMenu(page, `Menu circulation ${tag}`);
  await expect(menu.getByRole("menuitem", { name: "Move to…" })).toBeVisible();
  const box = await menu.boundingBox();
  expect(box.x + box.width).toBeLessThanOrEqual(400);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(400);
  await shot(page, "rowmenu-3-phone-400-row-menu");
  await menu.getByRole("menuitem", { name: "Rename…" }).click();
  await expect(page.getByRole("dialog", { name: "Rename this position" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(400);
  await shot(page, "rowmenu-4-phone-400-rename");
  await page.keyboard.press("Escape");
  await expectHealthy(page, problems, { label: "row menu locations and phone", root: ".tx" });
});
