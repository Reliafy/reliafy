// "Isolate" in the Explorer (Operate › Assets › Explorer): a row's menu
// (Isolate › with 1, 2 or 3 levels open, or everything open; from the mouse
// and from the keyboard) shows only that row and what's inside it, opened
// exactly that far below it; the notice in the tree's column header (no row of
// its own: "Isolated: <name> · <levels> · Show everything"), its levels list,
// Esc, "Show everything" in the ⋯ menu, Reset; the levels, search and counts
// on the branch; a crumb above it isolates that row instead; Back; the RCM tab
// (a function isolated, the Summary tab showing its position); old ?pin=
// links; a row outside the branch, or an isolated row that's gone; the RCM
// tab's menus without the moves on a wide screen (they stay for the keyboard
// and on a phone); nothing moves on screen; 400 px (the isolated row itself
// carries the mark, the levels and the ✕).
// Each test makes its own small plant through the API.
//
// The names start "Works" so they sort after the other specs' plants ("Rcm",
// "Tree"), which share the server and expect their rows near the top.
// With SMOKE_SHOTS_DIR set, it also saves screenshots there (for the pull request).
import { test, expect, open, expectHealthy } from "./health.js";
import { details } from "./explorer.js";

const M = "/api/maintenance";
const SHOTS = process.env.SMOKE_SHOTS_DIR || "";
const shot = async (page, name) => {
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}.png` });
};

async function plant(request, tag) {
  const post = async (path, data) => {
    const res = await request.post(path, { data });
    expect(res.ok(), `${path}: ${res.status()} ${await res.text()}`).toBeTruthy();
    return res.json();
  };
  const site = await post(`${M}/locations`, { name: `Works site ${tag}` });
  const top = await post(`${M}/positions`, { name: `Works plant ${tag}`, location_id: site.id });
  const lineA = await post(`${M}/positions`, { name: `Works line A ${tag}`, parent_id: top.id });
  const pumpA = await post(`${M}/positions`, { name: `Works pump A ${tag}`, parent_id: lineA.id });
  const sealA = await post(`${M}/positions`, { name: `Works seal A ${tag}`, parent_id: pumpA.id });
  const lineB = await post(`${M}/positions`, { name: `Works line B ${tag}`, parent_id: top.id });
  const pumpB = await post(`${M}/positions`, { name: `Works pump B ${tag}`, parent_id: lineB.id });
  const other = await post(`${M}/positions`, { name: `Works other ${tag}` });
  const fn = await post(`${M}/positions/${pumpA.id}/functions`, { text: `Pump water ${tag}` });
  const ff = await post(`${M}/functions/${fn.id}/failures`, { text: `No flow ${tag}` });
  await post(`${M}/positions/${pumpA.id}/failure-modes`, { text: `Seal leaks ${tag}`, functional_failure_id: ff.id });
  return { site, top, lineA, pumpA, sealA, lineB, pumpB, other, fn, ff };
}

// On a phone the isolated row's name starts "Isolated: ".
const row = (page, name) => page.getByRole("treeitem", { name: new RegExp(`^(Isolated: )?${name}`) });
// The notice: in the tree's column header, on both tabs (a wide screen).
const bar = (page) => page.locator(".tt-head").getByRole("group", { name: "Isolated branch" });
const levels = (page) => bar(page).getByRole("combobox", { name: /^Levels open below/ });
const panel = details;
const rowMenu = (page, name) => page.getByRole("menu", { name: new RegExp(`^Actions for ${name}`) });
const query = (page) => new URL(page.url()).searchParams;
const spoken = (page) => page.locator(".sr-only[role='status']");
async function treeMenu(page) {
  const menu = page.getByRole("menu", { name: "Tree options" });
  if (!(await menu.isVisible())) await page.getByRole("button", { name: /^Tree options/ }).click();
  await expect(menu).toBeVisible();
  return menu;
}
async function fromTreeMenu(page, role, name) {
  const menu = await treeMenu(page);
  await menu.getByRole(role, { name, exact: true }).click();
  if (await menu.isVisible()) await page.keyboard.press("Escape");
  await expect(menu).toHaveCount(0);
}
// Right-click a row, then Isolate › the level asked for (the submenu opens beside the menu).
async function isolate(page, target, label) {
  await target.click({ button: "right" });
  const menu = page.getByRole("menu").first();
  await menu.getByRole("menuitem", { name: "Isolate", exact: true }).hover();
  const sub = page.getByRole("menu", { name: "Isolate" });
  await expect(sub).toBeVisible();
  await sub.getByRole("menuitem", { name: label }).or(sub.getByRole("menuitemradio", { name: label })).click();
  await expect(page.getByRole("menu")).toHaveCount(0);
}

test("isolate from a row's menu at 1, 2, 3 levels and everything; the notice changes it; Esc and Show everything leave", async ({ page, request, problems }) => {
  const tag = `i${Date.now()}`;
  const p = await plant(request, tag);
  await page.setViewportSize({ width: 1280, height: 720 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.top.id}`);
  await expect(row(page, `Works plant ${tag}`)).toHaveAttribute("aria-level", "1");
  const treeTop = (await page.locator(".tp-scroll").boundingBox()).y;
  const headBox = await page.locator(".tt-head").boundingBox();

  // The menu: Isolate › (a submenu with the four levels), after the changes, before Retire.
  await row(page, `Works plant ${tag}`).locator(".tp-nm").click({ button: "right" });
  const menu = rowMenu(page, `Works plant ${tag}`);
  await expect(menu.getByRole("menuitem")).toHaveText(["New position inside", "Rename…", "Move to…", "Isolate", /^Retire…/]);
  await expect(menu.getByRole("menuitem", { name: "Isolate" })).toHaveAttribute("aria-haspopup", "menu");
  await menu.getByRole("menuitem", { name: "Isolate" }).hover();
  const sub = page.getByRole("menu", { name: "Isolate" });
  await expect(sub.getByRole("menuitem")).toHaveText(["With 1 level open", "With 2 levels open", "With 3 levels open", "With everything open"]);
  // Beside the menu, not over it.
  const mb = await menu.boundingBox();
  const sb = await sub.boundingBox();
  expect(sb.x).toBeGreaterThanOrEqual(mb.x + mb.width - 10);
  await shot(page, "1-row-menu-isolate-submenu-1280");
  await sub.getByRole("menuitem", { name: "With 1 level open" }).click();
  await expect.poll(() => query(page).get("isolate")).toBe(p.top.id);
  expect(query(page).get("depth")).toBe("1");

  // 1 level: the plant and what's directly inside it, closed.
  await expect(bar(page)).toContainText(`Isolated: Works plant ${tag}`);
  await expect(bar(page).locator(".tt-pinned-nm")).toHaveAttribute("title", `Isolated: Works plant ${tag}, 1 level open`);
  await expect(levels(page)).toHaveValue("1");
  await expect(row(page, `Works plant ${tag}`)).toHaveAttribute("aria-expanded", "true");
  await expect(row(page, `Works line A ${tag}`)).toHaveAttribute("aria-expanded", "false");
  await expect(row(page, `Works pump A ${tag}`)).toHaveCount(0);
  await expect(row(page, `Works other ${tag}`)).toHaveCount(0);
  await expect(spoken(page)).toContainText(`Isolated Works plant ${tag}, 1 level open.`);
  // No row of its own: the tree and its header stay exactly where they were.
  expect((await page.locator(".tp-scroll").boundingBox()).y).toBe(treeTop);
  expect(await page.locator(".tt-head").boundingBox()).toEqual(headBox);
  await shot(page, "2-isolated-1-level-1280");

  // The notice's list: 2 levels (pumps show, seals don't); the address follows.
  await levels(page).selectOption("2");
  await expect.poll(() => query(page).get("depth")).toBe("2");
  await expect(row(page, `Works pump A ${tag}`)).toHaveAttribute("aria-expanded", "false");
  await expect(row(page, `Works seal A ${tag}`)).toHaveCount(0);
  await shot(page, "3-isolated-2-levels-1280");

  // The menu again: the level ticked; 3 levels open everything here.
  await row(page, `Works plant ${tag}`).locator(".tp-nm").click({ button: "right" });
  await expect(rowMenu(page, `Works plant ${tag}`).getByRole("menuitem")).toHaveText(["New position inside", "Rename…", "Move to…", "Isolate", "Show everything", /^Retire…/]);
  await rowMenu(page, `Works plant ${tag}`).getByRole("menuitem", { name: "Isolate" }).hover();
  await expect(sub.getByRole("menuitemradio", { name: "With 2 levels open" })).toHaveAttribute("aria-checked", "true");
  await sub.getByRole("menuitemradio", { name: "With 3 levels open" }).click();
  await expect.poll(() => query(page).get("depth")).toBe("3");
  await expect(row(page, `Works seal A ${tag}`)).toBeVisible();
  // Everything open.
  await isolate(page, row(page, `Works line A ${tag}`).locator(".tp-nm"), "With everything open");
  await expect.poll(() => query(page).get("isolate")).toBe(p.lineA.id);
  expect(query(page).get("depth")).toBe("all");
  await expect(levels(page)).toHaveValue("all");
  await expect(row(page, `Works seal A ${tag}`)).toHaveAttribute("aria-level", "3");
  await expect(row(page, `Works line B ${tag}`)).toHaveCount(0);
  await expect(page.locator(".tp-status")).toHaveText("3 positions");

  // By hand after: still isolated.
  await row(page, `Works pump A ${tag}`).locator(".tp-chev").click();
  await expect(row(page, `Works seal A ${tag}`)).toHaveCount(0);
  await expect(bar(page)).toBeVisible();
  // The search looks inside the branch only.
  await page.getByLabel("Filter the tree").fill("Works pump");
  await expect(page.getByText("1 match, shown with what they're inside")).toBeVisible();
  await page.getByLabel("Filter the tree").fill("");

  // Esc in the tree leaves it, and says so.
  await row(page, `Works pump A ${tag}`).click();
  await row(page, `Works pump A ${tag}`).press("Escape");
  await expect(bar(page)).toHaveCount(0);
  await expect.poll(() => query(page).get("isolate")).toBe(null);
  await expect(spoken(page)).toContainText("Showing everything.");
  await expect(row(page, `Works plant ${tag}`)).toBeVisible();
  // Back: isolated again, at the depth it had.
  await page.goBack();
  await expect.poll(() => query(page).get("isolate")).toBe(p.lineA.id);
  await expect(bar(page)).toContainText(`Works line A ${tag}`);
  // The notice's Show everything.
  await bar(page).getByRole("button", { name: "Show everything" }).click();
  await expect(bar(page)).toHaveCount(0);
  // "Show everything" at the top of the ⋯ menu.
  await isolate(page, row(page, `Works plant ${tag}`).locator(".tp-nm"), "With 2 levels open");
  const opts = await treeMenu(page);
  await expect(opts.getByRole("menuitem").first()).toHaveText("Show everything");
  await opts.getByRole("menuitem", { name: "Show everything" }).click();
  await expect(bar(page)).toHaveCount(0);

  // From the keyboard: Shift+F10, → into Isolate, ↓, Enter.
  await row(page, `Works line B ${tag}`).click();
  await row(page, `Works line B ${tag}`).press("Shift+F10");
  const kmenu = rowMenu(page, `Works line B ${tag}`);
  await kmenu.getByRole("menuitem", { name: "Isolate" }).focus();
  await page.keyboard.press("ArrowRight");
  await expect(sub.getByRole("menuitem", { name: "With 1 level open" })).toBeFocused();
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("ArrowLeft"); // back to Isolate
  await expect(kmenu.getByRole("menuitem", { name: "Isolate" })).toBeFocused();
  await page.keyboard.press("Enter");
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("Enter");
  await expect.poll(() => query(page).get("isolate")).toBe(p.lineB.id);
  expect(query(page).get("depth")).toBe("2");
  await expect(row(page, `Works line B ${tag}`)).toBeFocused();

  // The panel heading's Isolate (2 levels), and a crumb above it isolates that row instead.
  await row(page, `Works pump B ${tag}`).click();
  await panel(page).getByRole("button", { name: `Works plant ${tag}` }).click();
  await expect.poll(() => query(page).get("isolate")).toBe(p.top.id);
  await expect(row(page, `Works line A ${tag}`)).toBeVisible();
  const btn = panel(page).getByRole("button", { name: "Isolate this branch" });
  await expect(btn).toHaveAttribute("aria-pressed", "true");
  await btn.click();
  await expect(bar(page)).toHaveCount(0);
  // Reset to the usual view leaves it too.
  await isolate(page, row(page, `Works line A ${tag}`).locator(".tp-nm"), "With 1 level open");
  await expect(page.getByRole("button", { name: /^Tree options: \d changed/ })).toBeVisible();
  await fromTreeMenu(page, "menuitem", "Reset to the usual view");
  await expect(bar(page)).toHaveCount(0);
  await expectHealthy(page, problems, { label: "isolated branch", root: ".tx" });
});

test("the RCM tab: isolate a function; Summary shows its position; no moves in the mouse menus, still from the keyboard", async ({ page, request, problems }) => {
  const tag = `r${Date.now()}`;
  const p = await plant(request, tag);
  await page.setViewportSize({ width: 1280, height: 720 });
  await open(page, `/asset-register/explorer?arrange=positions&tab=rcm&sel=${p.pumpA.id}&isolate=${p.lineA.id}&depth=all`);
  const table = page.getByRole("treegrid", { name: /and their RCM/ });
  const trow = (name) => table.getByRole("row", { name: new RegExp(name) });
  await expect(bar(page)).toContainText(`Isolated: Works line A ${tag}`);
  await expect(table.getByRole("columnheader", { name: "Position › function, standard, failure or mode" })).toBeVisible();
  const fnRow = trow(`^Function: Pump water ${tag}`);
  await expect(fnRow).toBeVisible();
  await expect(trow(`Failure mode: Seal leaks ${tag}`)).toBeVisible();
  await expect(trow(`^Works plant ${tag}`)).toHaveCount(0);

  // A function's menu with the mouse: no Move to… / Move up / Move down (drag does them).
  await fnRow.locator(".tt-tree").click({ button: "right" });
  const fmenu = rowMenu(page, `Function: Pump water ${tag}`);
  await expect(fmenu.getByRole("menuitem")).toHaveText(["Open…", "Add a standard…", "Add functional failure", "Edit description", "Isolate", "Delete function"]);
  await shot(page, "4-rcm-function-menu-no-moves-1280");
  await page.keyboard.press("Escape");
  // Its ⋯ button: the same.
  await fnRow.hover();
  await fnRow.getByRole("button", { name: "Actions", exact: true }).click();
  await expect(fmenu.getByRole("menuitem", { name: /^Move/ })).toHaveCount(0);
  await page.keyboard.press("Escape");
  // A failure mode's, with the mouse: no Move to… nor Move a task….
  await trow(`Failure mode: Seal leaks ${tag}`).locator(".tt-tree").click({ button: "right" });
  await expect(page.getByRole("menu").getByRole("menuitem", { name: /^Move/ })).toHaveCount(0);
  await expect(page.getByRole("menu").getByRole("menuitem", { name: "Isolate", exact: true })).toBeVisible(); // a leaf: just Isolate
  await page.keyboard.press("Escape");
  // From the keyboard (Shift+F10): the moves are there, so the keyboard can still move it.
  await fnRow.locator(".tt-tree").click();
  await fnRow.press("Shift+F10");
  await expect(fmenu.getByRole("menuitem")).toHaveText(["Open…", "Add a standard…", "Add functional failure", "Edit description", "Move to another position…", "Move up", "Move down", "Isolate", "Delete function"]);
  await page.keyboard.press("Escape");

  // Isolate the function, 1 level: its functional failure shows, closed.
  await isolate(page, fnRow.locator(".tt-tree"), "With 1 level open");
  await expect.poll(() => query(page).get("isolate")).toBe(p.fn.id);
  await expect(bar(page)).toContainText(`Isolated: Pump water ${tag}`);
  await expect(fnRow).toHaveAttribute("aria-level", "1");
  await expect(trow(`^Functional failure: No flow ${tag}`)).toHaveAttribute("aria-expanded", "false");
  await expect(trow(`Failure mode: Seal leaks ${tag}`)).toHaveCount(0);
  await expect(trow(`^Works pump A ${tag}`)).toHaveCount(0);
  await expect(page.locator(".tt-top .tp-status")).toHaveText("2 rows inside this function · RCM is by position");
  await shot(page, "5-rcm-function-isolated-1280");
  // Switching tabs moves nothing: the tree and its header stay put.
  const before = { tree: await page.locator(".tp-scroll").boundingBox(), head: await page.locator(".tt-head").boundingBox() };
  await page.getByRole("tab", { name: "Summary" }).click();
  await expect(page.getByRole("tree", { name: "Positions" })).toBeVisible();
  // Summary has no functions: its position is isolated; the address keeps the function.
  await expect(bar(page)).toContainText(`Isolated: Works pump A ${tag}`);
  expect(query(page).get("isolate")).toBe(p.fn.id);
  expect((await page.locator(".tp-scroll").boundingBox()).y).toBe(before.tree.y);
  expect((await page.locator(".tt-head").boundingBox()).y).toBe(before.head.y);
  await page.getByRole("tab", { name: "RCM" }).click();
  await expect(bar(page)).toContainText(`Isolated: Pump water ${tag}`);
  expect((await page.locator(".tp-scroll").boundingBox()).y).toBe(before.tree.y);
  await expectHealthy(page, problems, { label: "isolated RCM tab", root: ".tx" });
});

test("old pin links still open isolated; a row outside the branch shows everything; one that's gone quietly goes", async ({ page, request, problems }) => {
  const tag = `o${Date.now()}`;
  const p = await plant(request, tag);
  await page.setViewportSize({ width: 1280, height: 720 });
  // ?pin=: isolated, what's open as it was (the levels list says "Levels" until one is picked).
  await open(page, `/asset-register/explorer?arrange=positions&pin=${p.lineA.id}&sel=${p.lineA.id}`);
  await expect(bar(page)).toContainText(`Isolated: Works line A ${tag}`);
  await expect(levels(page)).toHaveValue("");
  await expect(row(page, `Works line A ${tag}`)).toHaveAttribute("aria-expanded", "true");
  await expect(row(page, `Works plant ${tag}`)).toHaveCount(0);
  await levels(page).selectOption("1");
  await expect.poll(() => query(page).get("depth")).toBe("1");
  expect(query(page).get("isolate")).toBe(p.lineA.id);
  expect(query(page).get("pin")).toBe(null);
  await expect(row(page, `Works pump A ${tag}`)).toHaveAttribute("aria-expanded", "false");

  // ?sel= outside the isolated branch: everything, the row picked, and a note.
  await open(page, `/asset-register/explorer?arrange=positions&isolate=${p.lineA.id}&depth=2&sel=${p.other.id}`);
  await expect(page.locator(".tt-head").getByRole("status")).toHaveText("Showing everything again");
  await expect(bar(page)).toHaveCount(0);
  await expect(row(page, `Works other ${tag}`)).toHaveAttribute("aria-selected", "true");
  expect(query(page).get("isolate")).toBe(null);
  // An isolated row that isn't there (retired, deleted): no isolation, no note.
  await open(page, `/asset-register/explorer?arrange=positions&isolate=not-a-position-${tag}&depth=2`);
  await expect.poll(() => query(page).get("isolate")).toBe(null);
  await expect(page.getByRole("tree", { name: "Positions" })).toBeVisible();
  await expect(page.getByText("Showing everything again")).toHaveCount(0);
  // Flat can't isolate: it goes, and its rows' menus have no Isolate.
  await open(page, `/asset-register/explorer?arrange=flat&isolate=${p.lineA.id}&sel=${p.lineA.id}`);
  await expect.poll(() => query(page).get("isolate")).toBe(null);
  await row(page, `Works line A ${tag}`).locator(".tp-nm").click({ button: "right" });
  await expect(rowMenu(page, `Works line A ${tag}`).getByRole("menuitem", { name: "Rename…" })).toBeVisible();
  await expect(rowMenu(page, `Works line A ${tag}`).getByRole("menuitem", { name: "Isolate" })).toHaveCount(0);
  await page.keyboard.press("Escape");
  // Locations: isolate the site; its positions show inside it.
  await open(page, `/asset-register/explorer?arrange=locations&sel=${p.site.id}`);
  await isolate(page, row(page, `Works site ${tag}`).locator(".tp-nm"), "With everything open");
  await expect(bar(page)).toContainText(`Works site ${tag}`);
  await expect(row(page, `Works plant ${tag}`)).toBeVisible();
  await expect(page.locator(".tp-status")).toHaveText(/^1 location · 6 positions$/);
  await expectHealthy(page, problems, { label: "isolate: old links, outside and gone", root: ".tx" });
});

test("at 400 px: Isolate opens in place in the ⋯ menu; the row carries the levels and an easy-to-tap ✕; the moves stay", async ({ page, request, problems }) => {
  const tag = `w${Date.now()}`;
  const p = await plant(request, tag);
  await page.setViewportSize({ width: 400, height: 860 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.top.id}`);
  const treeTop = (await page.locator(".tp-scroll").boundingBox()).y;
  const more = row(page, `Works line A ${tag}`).getByRole("button", { name: "Actions", exact: true });
  await more.click();
  const menu = rowMenu(page, `Works line A ${tag}`);
  await menu.getByRole("menuitem", { name: "Isolate" }).click();
  await expect(menu.getByRole("menuitem", { name: "Isolate" })).toHaveAttribute("aria-expanded", "true");
  const group = menu.getByRole("group", { name: "Isolate" });
  await expect(group.getByRole("menuitem")).toHaveText(["With 1 level open", "With 2 levels open", "With 3 levels open", "With everything open"]);
  const gb = await menu.boundingBox();
  expect(gb.x + gb.width).toBeLessThanOrEqual(400);
  await shot(page, "6-phone-400px-isolate-menu");
  await group.getByRole("menuitem", { name: "With 1 level open" }).click();
  await expect.poll(() => query(page).get("isolate")).toBe(p.lineA.id);
  // No row of its own: the tree starts where it did; the isolated row says it.
  const iso = row(page, `Works line A ${tag}`);
  await expect(iso).toHaveAccessibleName(new RegExp(`^Isolated: Works line A ${tag}`));
  await expect(iso.locator(".tp-isomark")).toBeVisible();
  expect((await page.locator(".tp-scroll").boundingBox()).y).toBe(treeTop);
  await expect(row(page, `Works pump A ${tag}`)).toHaveAttribute("aria-expanded", "false");
  const lv = iso.getByRole("combobox", { name: /^Levels open below/ });
  await expect(lv).toHaveValue("1");
  expect((await lv.boundingBox()).height).toBeGreaterThanOrEqual(36);
  const x = iso.getByRole("button", { name: "Show everything" });
  const xb = await x.boundingBox();
  expect(xb.height).toBeGreaterThanOrEqual(36);
  expect(xb.width).toBeGreaterThanOrEqual(36);
  expect(xb.x + xb.width).toBeLessThanOrEqual(400);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(400);
  await lv.selectOption("2");
  await expect.poll(() => query(page).get("depth")).toBe("2");
  await expect(row(page, `Works seal A ${tag}`)).toBeVisible(); // 2 levels below the line: its pump and the pump's seal
  await shot(page, "7-phone-400px-isolated");
  // The RCM tab: the same on its two-line rows; the menus keep the moves (no dragging on a phone).
  await page.getByRole("tab", { name: "RCM" }).click();
  const trow = page.getByRole("row", { name: new RegExp(`^Isolated: Works line A ${tag}`) });
  await expect(trow.getByRole("button", { name: "Show everything" })).toBeVisible();
  const fnRow = page.getByRole("row", { name: new RegExp(`^Function: Pump water ${tag}`) });
  if (!(await fnRow.isVisible())) await page.getByRole("row", { name: new RegExp(`^Works pump A ${tag}`) }).locator(".tp-chev").click();
  await fnRow.getByRole("button", { name: "Actions", exact: true }).click();
  await expect(page.getByRole("menu").getByRole("menuitem", { name: "Move to another position…" })).toBeVisible();
  await expect(page.getByRole("menu").getByRole("menuitem", { name: "Move up" })).toBeVisible();
  await shot(page, "8-phone-400px-rcm-menu-moves");
  await page.keyboard.press("Escape");
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(400);
  await shot(page, "9-phone-400px-isolated-rcm");
  await trow.getByRole("button", { name: "Show everything" }).click();
  await expect.poll(() => query(page).get("isolate")).toBe(null);
  await expectHealthy(page, problems, { label: "isolated at 400 px", root: ".tx" });
});
