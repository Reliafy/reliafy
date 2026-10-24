// The Explorer's tabs (Operate › Assets › Explorer). Summary: the tree (positions)
// with the page about the row picked beside it. RCM: the tree and the RCM are
// one table: the same tree is its first column, each position's functions ›
// functional failures › failure modes nested in it, the RCM's columns beside
// every row; adding from a row's menu (right-click, ⋯, Shift+F10) grows the
// tree; the selected row stays put
// across the tabs; it fits the window; the keyboard; the tree's ⋯ menu (Arrange
// by, the levels, Show only, Reset); full screen.
// Each test makes its own small plant through the API.
import { test, expect, open, expectHealthy } from "./health.js";

const M = "/api/maintenance";

async function plant(request, tag) {
  const post = async (path, data) => {
    const res = await request.post(path, { data });
    expect(res.ok(), `${path}: ${res.status()} ${await res.text()}`).toBeTruthy();
    return res.json();
  };
  const top = await post(`${M}/positions`, {
    name: `Rcm plant ${tag}`,
    description: "A long description about the plant. ".repeat(20),
  });
  const pump = await post(`${M}/positions`, { name: `Rcm pump ${tag}`, parent_id: top.id });
  const motor = await post(`${M}/positions`, { name: `Rcm motor ${tag}`, parent_id: pump.id });
  // Several functions, each with several functional failures, each with several modes.
  const fns = [];
  for (const f of ["Pump water", "Contain the water"]) {
    const fn = await post(`${M}/positions/${pump.id}/functions`, { text: `${f} ${tag}` });
    fns.push(fn);
    for (const x of ["No flow", "Low flow"]) {
      const ff = await post(`${M}/functions/${fn.id}/failures`, { text: `${x} ${f} ${tag}` });
      for (const mo of ["Bearing seizes", "Seal leaks"]) {
        await post(`${M}/positions/${pump.id}/failure-modes`, { text: `${mo} ${x} ${f} ${tag}`, functional_failure_id: ff.id });
      }
    }
  }
  const mode = await post(`${M}/positions/${pump.id}/failure-modes`, { text: `Coupling fails ${tag}` }); // under none
  const res = await request.put(`${M}/failure-modes/${mode.id}/decision`, {
    data: { consequence: "operational", decision: { outcome: "rtf", rtf_basis: "random", evidence: { type: "model", id: "sample-model-bearings-weibull" } } },
  });
  expect(res.ok()).toBeTruthy();
  await post(`${M}/positions/${pump.id}/fit`, { new_item: { name: `Rcm unit ${tag}`, serial: `RU-${tag}` } });
  return { top, pump, motor, fns, mode };
}

const table = (page) => page.getByRole("treegrid", { name: /and their RCM/ });
const tree = (page) => page.getByRole("tree", { name: "Positions" });
const trow = (page, name) => table(page).getByRole("row", { name: new RegExp(name) });
// Picked by its tree cell (a click mid-row could land on a cell's own button).
const pickRow = (page, name) => trow(page, name).locator(".tt-tree, .tt-l1").first().click();
const treeitem = (page, name) => page.getByRole("treeitem", { name: new RegExp(`^${name}`) });
const overflow = (page) => page.evaluate(() => {
  const el = document.documentElement;
  return { down: el.scrollHeight - innerHeight, side: el.scrollWidth - innerWidth };
});
const topOf = async (locator) => Math.round((await locator.boundingBox()).y);
// A row's place in the tree's own scroll area (the area itself starts higher on
// the RCM tab, whose controls are two slim rows).
const placeOf = async (page, locator) => (await topOf(locator)) - (await topOf(page.locator(".tp-scroll")));
// The tree's ⋯ menu: its button, and the menu once open.
const menuButton = (page) => page.getByRole("button", { name: /^Tree options/ });
const treeMenu = (page) => page.getByRole("menu", { name: "Tree options" });
async function openTreeMenu(page) {
  if (!(await treeMenu(page).isVisible())) await menuButton(page).click();
  await expect(treeMenu(page)).toBeVisible();
  return treeMenu(page);
}

test("RCM: the tree and the RCM are one table; Summary: the tree and the page; the row stays put", async ({ page, request, problems }) => {
  const tag = `t${Date.now()}`;
  const p = await plant(request, tag);
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pump.id}`);
  // Summary: the tree (positions only) and the page beside it.
  await expect(tree(page)).toBeVisible();
  await expect(table(page)).toHaveCount(0);
  await expect(page.getByRole("region", { name: "Details" }).getByRole("heading", { name: `Rcm pump ${tag}` })).toBeVisible();
  await expect(page.getByText(`Pump water ${tag}`)).toHaveCount(0);
  const before = await placeOf(page, treeitem(page, `Rcm pump ${tag}`));

  await page.getByRole("tab", { name: "RCM" }).click();
  await expect(page).toHaveURL(/tab=rcm/);
  // One table: no tree of its own beside it, the positions and their RCM in the same rows.
  await expect(table(page)).toBeVisible();
  await expect(page.getByRole("tree")).toHaveCount(0);
  await expect(table(page).getByRole("columnheader", { name: "Decision" })).toBeVisible();
  await expect(trow(page, `^Rcm plant ${tag}`)).toBeVisible();
  const pumpRow = trow(page, `^Rcm pump ${tag}`);
  await expect(pumpRow).toHaveAttribute("aria-selected", "true");
  expect(await placeOf(page, pumpRow)).toBe(before); // the selected row didn't move in the tree
  // Its functions, failures and modes, nested under it (several of each).
  await expect(trow(page, `^Function: Pump water ${tag}`)).toBeVisible();
  await expect(trow(page, `^Function: Contain the water ${tag}`)).toBeVisible();
  await expect(trow(page, `Functional failure: Low flow Pump water ${tag}`)).toBeVisible();
  await expect(trow(page, `Failure mode: Seal leaks Low flow Pump water ${tag}`)).toBeVisible();
  await trow(page, `^Function: Pump water ${tag}`).locator(".tp-chev").click(); // close two: the rest comes into view
  await trow(page, `^Function: Contain the water ${tag}`).locator(".tp-chev").click();
  await expect(trow(page, "Not under a functional failure").first()).toBeVisible();
  await expect(trow(page, `Coupling fails ${tag}`).getByText("Contradicted")).toBeVisible();
  // RCM is by position: the other arrangements wait for Summary (the counts and the menu say so).
  await expect(page.locator(".tt-top .tp-status")).toContainText("RCM is by position");
  const menu = await openTreeMenu(page);
  await expect(menu.getByRole("menuitemradio", { name: "Locations" })).toHaveCount(0);
  await expect(menu).toContainText("RCM is by position");
  await page.keyboard.press("Escape");
  await expect(menu).toHaveCount(0);

  await page.getByRole("tab", { name: "Summary" }).click();
  await expect(tree(page)).toBeVisible();
  await expect(page.getByText(`Pump water ${tag}`)).toHaveCount(0);
  await expect(treeitem(page, `Rcm pump ${tag}`)).toHaveAttribute("aria-selected", "true");
  expect(await placeOf(page, treeitem(page, `Rcm pump ${tag}`))).toBe(before);
  // The plant's long description: two lines, and More opens the whole of it.
  await treeitem(page, `Rcm plant ${tag}`).click();
  await page.getByRole("region", { name: "Details" }).getByRole("button", { name: /More/ }).click();
  await expect(page.getByRole("dialog", { name: "Description" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expectHealthy(page, problems, { label: "explorer one table" });
});

// The dialog that asks for a new row's words, answered.
async function ask(page, title, text) {
  const d = page.getByRole("dialog", { name: title });
  await d.getByRole("textbox").fill(text);
  await d.getByRole("button", { name: title.replace(/^Add an? /, "Add ") }).click();
}
const rowMenu = (page, name) => page.getByRole("menu", { name: new RegExp(`^Actions for ${name}`) });
// Right-click a row on its tree cell, and pick from its menu.
async function fromMenu(page, rowName, menuName, item) {
  await trow(page, rowName).locator(".tt-tree, .tt-l1").first().click({ button: "right" });
  await rowMenu(page, menuName).getByRole("menuitem", { name: item, exact: true }).click();
}

test("adding from each row's menu grows the tree: a function, its failures and modes", async ({ page, request, problems }) => {
  const tag = `g${Date.now()}`;
  const p = await plant(request, tag);
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.motor.id}&tab=rcm`);
  // No "Add …" rows in the table: the motor's own row says how to start (Add function, or a row's menu).
  await expect(table(page)).toBeVisible();
  await expect(table(page).getByText(/^Add a (function|functional failure|failure mode)$/)).toHaveCount(0);
  await expect(trow(page, `^Rcm motor ${tag}`).locator(".tt-empty-hint"))
    .toHaveText("No functions yet. Press Add function, or right-click a row to add inside it.");
  await expect(page.locator(".tt-top")).not.toContainText("No functions yet");
  // The heading's Add function adds to the position picked.
  await page.locator(".tt-headslot").getByRole("button", { name: "Add function", exact: true }).click();
  await ask(page, "Add a function", `Turn the shaft ${tag}`);
  const fn = trow(page, `^Function: Turn the shaft ${tag}`);
  await expect(fn).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("complementary", { name: "Details" })).toBeVisible();
  await expect(table(page).locator(".tt-empty-hint")).toHaveCount(0);
  // Right-click the position: Add function.
  await fromMenu(page, `^Rcm motor ${tag}`, `Rcm motor ${tag}`, "Add function");
  await ask(page, "Add a function", `Stay cool ${tag}`);
  await expect(trow(page, `^Function: Stay cool ${tag}`)).toHaveAttribute("aria-selected", "true");
  // Right-click a function: Add functional failure; the new row opens under it, picked.
  await fromMenu(page, `^Function: Turn the shaft ${tag}`, `Function: Turn the shaft ${tag}`, "Add functional failure");
  await ask(page, "Add a functional failure", `Shaft stops ${tag}`);
  const ff = trow(page, `^Functional failure: Shaft stops ${tag}`);
  await expect(ff).toHaveAttribute("aria-selected", "true");
  await expect(fn).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByText("Added the functional failure.")).toBeVisible();
  // Right-click the functional failure: Add failure mode (twice).
  for (const m of ["Winding burnt", "Bearing worn"]) {
    await fromMenu(page, `^Functional failure: Shaft stops ${tag}`, `Functional failure: Shaft stops ${tag}`, "Add failure mode");
    await ask(page, "Add a failure mode", `${m} ${tag}`);
    await expect(trow(page, `^Failure mode: ${m} ${tag}`)).toHaveAttribute("aria-selected", "true");
  }
  await expect(ff).toHaveAttribute("aria-expanded", "true");
  const sheet = await (await request.get(`${M}/positions/${p.motor.id}/rcm?scope=this`)).json();
  expect(sheet.positions[0].functions.map((f) => f.text)).toEqual([`Turn the shaft ${tag}`, `Stay cool ${tag}`]);
  expect(sheet.positions[0].functions[0].failures[0].modes.map((m) => m.text)).toEqual([`Winding burnt ${tag}`, `Bearing worn ${tag}`]);
  // A failure mode's menu: decide, edit, delete; Delete asks first.
  await fromMenu(page, `^Failure mode: Bearing worn ${tag}`, `Failure mode: Bearing worn ${tag}`, "Delete failure mode");
  await page.getByRole("alertdialog", { name: "Delete this failure mode?" }).getByRole("button", { name: "Delete failure mode" }).click();
  await expect(trow(page, `^Failure mode: Bearing worn ${tag}`)).toHaveCount(0);
  await expectHealthy(page, problems, { label: "tree grows" });
});

test("a row's menu: Shift+F10 and the Menu key, the arrows, Esc, the ⋯ button; fields keep the browser's menu", async ({ page, request, problems }) => {
  const tag = `m${Date.now()}`;
  const p = await plant(request, tag);
  await page.setViewportSize({ width: 1280, height: 720 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pump.id}&tab=rcm`);
  const fnName = `Function: Pump water ${tag}`;
  const fn = trow(page, `^${fnName}`);
  await trow(page, `^Rcm pump ${tag}`).focus();
  await page.keyboard.press("ArrowDown");
  await expect(fn).toBeFocused();
  // Shift+F10: the menu, its first item focused; the arrows move; Esc closes and the row has the focus back.
  await page.keyboard.press("Shift+F10");
  const menu = rowMenu(page, fnName);
  await expect(menu).toBeVisible();
  await expect(menu.getByRole("menuitem")).toHaveText(["Add functional failure", "Edit description", "Delete function"]);
  await expect(menu.getByRole("menuitem", { name: "Add functional failure" })).toBeFocused();
  await page.keyboard.press("ArrowDown");
  await expect(menu.getByRole("menuitem", { name: "Edit description" })).toBeFocused();
  await page.keyboard.press("ArrowUp");
  await page.keyboard.press("ArrowUp"); // round to the last
  await expect(menu.getByRole("menuitem", { name: "Delete function" })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(menu).toHaveCount(0);
  await expect(fn).toBeFocused();
  // The Menu key; Enter chooses: Edit description edits the name in place.
  await page.keyboard.press("ContextMenu");
  await expect(menu).toBeVisible();
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("Enter");
  const editor = table(page).getByRole("textbox", { name: `Function, failure or mode of Pump water ${tag}` });
  await expect(editor).toBeFocused();
  // Right-click in the field: the browser's own menu, not the row's.
  await editor.click({ button: "right" });
  await expect(page.getByRole("menu")).toHaveCount(0);
  await page.keyboard.press("Escape");
  await expect(editor).toHaveCount(0);
  // The ⋯ button: hidden until the row is hovered; it opens the same menu.
  const mode = trow(page, `^Failure mode: Bearing seizes No flow Pump water ${tag}`);
  const more = mode.getByRole("button", { name: "Actions", exact: true });
  await expect(more).toHaveCSS("opacity", "0");
  await mode.hover();
  await expect(more).toHaveCSS("opacity", "1");
  await more.click();
  await rowMenu(page, "Failure mode: Bearing seizes").getByRole("menuitem", { name: "Decide…" }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  // A click outside closes it, and so does a scroll.
  await fn.locator(".tt-tree").click({ button: "right" });
  await expect(menu).toBeVisible();
  await page.locator(".tt-headslot .td-title").click();
  await expect(menu).toHaveCount(0);
  await fn.locator(".tt-tree").click({ button: "right" });
  await expect(menu).toBeVisible();
  await page.locator(".tp-scroll").evaluate((el) => { el.scrollTop += 60; });
  await expect(menu).toHaveCount(0);
  // Near the window's right edge it stays on screen.
  await page.locator(".tp-scroll").evaluate((el) => { el.scrollTop = 0; });
  const box = await fn.boundingBox();
  await page.mouse.click(Math.min(1276, box.x + box.width - 2), box.y + box.height / 2, { button: "right" });
  const mbox = await menu.boundingBox();
  expect(mbox.x + mbox.width).toBeLessThanOrEqual(1280 - 7);
  expect(mbox.y + mbox.height).toBeLessThanOrEqual(720);
  await page.keyboard.press("Escape");
  // The heading of failure modes under no functional failure has no menu: the browser's stays.
  await expect(trow(page, "Not under a functional failure").first().getByRole("button", { name: "Actions", exact: true })).toHaveCount(0);
  await expectHealthy(page, problems, { label: "row menu keyboard", root: ".tx" });
});

test("a row's menu in full screen: it opens inside it, and Esc closes the menu before full screen", async ({ page, request, problems }) => {
  await page.addInitScript(() => {
    for (const k of ["requestFullscreen", "webkitRequestFullscreen"]) {
      delete Element.prototype[k];
      delete HTMLElement.prototype[k];
    }
    for (const k of ["exitFullscreen", "webkitExitFullscreen"]) delete Document.prototype[k];
  });
  const tag = `x${Date.now()}`;
  const p = await plant(request, tag);
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pump.id}&tab=rcm`);
  await page.locator("body").click({ position: { x: 5, y: 300 } });
  await page.keyboard.press("f");
  await expect(page.locator(".tx.is-full")).toBeVisible();
  const fnName = `Function: Pump water ${tag}`;
  await trow(page, `^${fnName}`).locator(".tt-tree").click({ button: "right" });
  const menu = rowMenu(page, fnName);
  await expect(menu).toBeVisible();
  expect(await page.evaluate(() => document.querySelector(".tx.is-full").contains(document.querySelector("[role=menu]")))).toBe(true);
  await page.keyboard.press("Escape");
  await expect(menu).toHaveCount(0);
  await expect(page.locator(".tx.is-full")).toBeVisible();
  await expectHealthy(page, problems, { label: "row menu full screen", root: ".tx" });
});

test("at 400 px each row shows its ⋯: a tap opens the menu, and adding works", async ({ page, request, problems }) => {
  const tag = `q${Date.now()}`;
  const p = await plant(request, tag);
  await page.setViewportSize({ width: 400, height: 860 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pump.id}&tab=rcm`);
  await expect(table(page)).toBeVisible();
  const fnName = `Function: Contain the water ${tag}`;
  const more = trow(page, `^${fnName}`).getByRole("button", { name: "Actions", exact: true });
  await expect(more).toHaveCSS("opacity", "1");
  const size = await more.boundingBox();
  expect(Math.min(size.width, size.height)).toBeGreaterThanOrEqual(32);
  await more.click();
  const menu = rowMenu(page, fnName);
  // On a phone the details panel edits the description: no Edit description here.
  await expect(menu.getByRole("menuitem")).toHaveText(["Add functional failure", "Delete function"]);
  const mbox = await menu.boundingBox();
  expect(mbox.x).toBeGreaterThanOrEqual(0);
  expect(mbox.x + mbox.width).toBeLessThanOrEqual(400);
  expect((await overflow(page)).side).toBe(0);
  await menu.getByRole("menuitem", { name: "Add functional failure" }).click();
  await ask(page, "Add a functional failure", `Leaks out ${tag}`);
  await expect(trow(page, `^Functional failure: Leaks out ${tag}`)).toHaveAttribute("aria-selected", "true");
  expect((await overflow(page)).side).toBe(0);
  await expectHealthy(page, problems, { label: "row menu at 400 px", root: ".tx" });
});

test("keyboard: walk from a position into its functions and modes, Enter for the details", async ({ page, request, problems }) => {
  const tag = `k${Date.now()}`;
  const p = await plant(request, tag);
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pump.id}&tab=rcm`);
  const pumpRow = trow(page, `^Rcm pump ${tag}`);
  await pumpRow.focus();
  await page.keyboard.press("ArrowDown");
  await expect(trow(page, `^Function: Pump water ${tag}`)).toHaveAttribute("aria-selected", "true");
  await page.keyboard.press("ArrowLeft"); // close it
  await expect(trow(page, `Functional failure: No flow Pump water ${tag}`)).toHaveCount(0);
  await page.keyboard.press("ArrowRight"); // open it
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("ArrowDown");
  await expect(trow(page, `Failure mode: Bearing seizes No flow Pump water ${tag}`)).toHaveAttribute("aria-selected", "true");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("complementary", { name: "Details" })).toBeVisible();
  await expectHealthy(page, problems, { label: "keyboard" });
});

for (const [w, h] of [[1440, 900], [1366, 768]]) {
  test(`the RCM tab fits ${w}x${h}: no page scroll, the table scrolls in its own area`, async ({ page, request, problems }) => {
    const tag = `f${w}${Date.now()}`;
    const p = await plant(request, tag);
    await page.setViewportSize({ width: w, height: h });
    await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pump.id}&tab=rcm`);
    await expect(table(page)).toBeVisible();
    expect(await overflow(page)).toEqual({ down: 0, side: 0 });
    await pickRow(page, `Failure mode: Seal leaks No flow Pump water ${tag}`);
    await expect(page.getByRole("complementary", { name: "Details" })).toBeVisible();
    expect(await overflow(page)).toEqual({ down: 0, side: 0 });
    await expectHealthy(page, problems, { label: `rcm fits ${w}`, root: ".tx" });
  });
}

test("the RCM tab's heading is two slim rows: the way up and the name, then the tabs; Columns opens over it", async ({ page, request, problems }) => {
  const tag = `h${Date.now()}`;
  const p = await plant(request, tag);
  await page.setViewportSize({ width: 1280, height: 720 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.motor.id}&tab=rcm`);
  await expect(table(page)).toBeVisible();
  const bar = page.locator(".tt-headslot");
  // The bar: the position (its way up over its name) and the actions, Add function first and the one primary.
  await expect(bar.getByRole("heading", { name: `Rcm motor ${tag}` })).toBeVisible();
  await expect(bar.getByRole("navigation", { name: "Breadcrumb" })).toContainText(`Rcm pump ${tag}`);
  for (const name of ["Columns", "Add function", "Full screen"]) {
    await expect(bar.getByRole("button", { name, exact: true })).toBeVisible();
  }
  await expect(bar.getByRole("link", { name: "Open the full page" })).toBeVisible();
  await expect(bar.locator(".tt-actions > button").first()).toHaveText("Add function");
  await expect(bar.getByRole("tab")).toHaveCount(0);
  // Under it, the tabs: below the way up and the name.
  const tabs = page.locator(".tt-tabslot");
  await expect(tabs.getByRole("tab", { name: "RCM" })).toHaveAttribute("aria-selected", "true");
  expect(await topOf(tabs.getByRole("tab", { name: "RCM" })))
    .toBeGreaterThanOrEqual(Math.round((await bar.getByRole("heading").boundingBox()).y + (await bar.getByRole("heading").boundingBox()).height));
  // No second row of tree controls: they're in the tree's ⋯ menu.
  await expect(page.locator(".tt-top").getByRole("button", { name: "Open to level 1" })).toHaveCount(0);
  await expect(page.locator(".tt-top").getByRole("button", { name: "Not analysed" })).toHaveCount(0);
  const heights = await page.evaluate(() => {
    const h = (s) => Math.round(document.querySelector(s).getBoundingClientRect().height);
    return { bar: h(".tt-bar"), all: h(".tt-top") };
  });
  expect(heights.bar).toBeLessThanOrEqual(56);
  expect(heights.all).toBeLessThanOrEqual(92);
  // The table keeps its height: at least 18 rows in view at 1280x720.
  const rows = await page.evaluate(() => {
    const sc = document.querySelector(".tp-scroll").getBoundingClientRect();
    const head = document.querySelector(".tt-head").getBoundingClientRect().height;
    return [...document.querySelectorAll(".tp-body .tp-row")].filter((r) => {
      const b = r.getBoundingClientRect();
      return b.top >= sc.top + head - 1 && b.bottom <= sc.bottom + 1;
    }).length;
  });
  expect(rows).toBeGreaterThanOrEqual(Math.min(18, await page.locator(".tp-body .tp-row").count()));
  // The way up goes up.
  await bar.getByRole("navigation", { name: "Breadcrumb" }).getByRole("button", { name: `Rcm pump ${tag}` }).click();
  await expect(trow(page, `^Rcm pump ${tag}`)).toHaveAttribute("aria-selected", "true");
  // Columns opens over the table, its last choice not cut off.
  await bar.getByRole("button", { name: "Columns" }).click();
  const list = page.getByRole("group", { name: "Columns to show" });
  await expect(list).toBeVisible();
  const reset = list.getByRole("button", { name: "Show the usual columns" });
  const box = await reset.boundingBox();
  expect(await page.evaluate(([x, y]) => !!document.elementFromPoint(x, y)?.closest(".rw-pop"),
    [box.x + box.width / 2, box.y + box.height / 2])).toBe(true);
  await list.getByRole("checkbox", { name: "Evident or hidden" }).check();
  await expect(table(page).getByRole("columnheader", { name: "Evident or hidden" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(list).toHaveCount(0);
  expect(await overflow(page)).toEqual({ down: 0, side: 0 });
  await expectHealthy(page, problems, { label: "rcm slim header", root: ".tx" });
});

test("at 400 px nothing scrolls sideways, on either tab; a mode opens as a sheet", async ({ page, request, problems }) => {
  const tag = `p${Date.now()}`;
  const p = await plant(request, tag);
  await page.setViewportSize({ width: 400, height: 860 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pump.id}`);
  expect((await overflow(page)).side).toBe(0);
  await page.getByRole("tab", { name: "RCM" }).click();
  await expect(table(page)).toBeVisible();
  expect((await overflow(page)).side).toBe(0);
  await pickRow(page, `Failure mode: Bearing seizes No flow Pump water ${tag}`);
  await expect(page.getByRole("complementary", { name: "Details" })).toBeVisible();
  expect((await overflow(page)).side).toBe(0);
  await expect(page.getByRole("button", { name: "Full screen", exact: true })).toHaveCount(0);
  await expectHealthy(page, problems, { label: "rcm at 400 px", root: ".tx" });
});

test("one search, and Show only in the tree's ⋯ menu: the RCM's text, Needs a decision, Not analysed", async ({ page, request, problems }) => {
  const tag = `c${Date.now()}`;
  const p = await plant(request, tag);
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pump.id}&tab=rcm`);
  await page.getByRole("searchbox", { name: "Filter the tree and its RCM" }).fill(`Seal leaks Low flow Contain`);
  await expect(trow(page, `Failure mode: Seal leaks Low flow Contain the water ${tag}`)).toBeVisible();
  await expect(trow(page, `Failure mode: Bearing seizes No flow Pump water ${tag}`)).toHaveCount(0);
  await page.getByRole("searchbox", { name: "Filter the tree and its RCM" }).fill("");
  const menu = await openTreeMenu(page);
  await menu.getByRole("menuitemcheckbox", { name: "Needs a decision" }).click();
  await expect(trow(page, `Failure mode: Bearing seizes No flow Pump water ${tag}`)).toBeVisible();
  await expect(trow(page, `Coupling fails ${tag}`)).toHaveCount(0); // decided
  // It stays open for the next change.
  await menu.getByRole("menuitemcheckbox", { name: "Needs a decision" }).click();
  await menu.getByRole("menuitemcheckbox", { name: "Not analysed" }).click();
  await menu.getByRole("menuitem", { name: "Done" }).click();
  await expect(menu).toHaveCount(0);
  // The plant (no function), the pump (modes with no decision) and the motor
  // (no function): counted in the plant's quiet marker.
  await expect(trow(page, `^Rcm plant ${tag}`)).toHaveAccessibleName(/3 positions not analysed yet here and inside/);
  await expect(trow(page, `^Rcm plant ${tag}`).locator(".tp-mini.rcm")).toBeVisible();
  // The RCM's own filters are for its tab only.
  await page.getByRole("tab", { name: "Summary" }).click();
  await openTreeMenu(page);
  await expect(treeMenu(page).getByRole("menuitemcheckbox", { name: "Needs a decision" })).toHaveCount(0);
  await expect(treeMenu(page).getByRole("menuitemcheckbox", { name: "Not analysed" })).toHaveAttribute("aria-checked", "true");
  await page.keyboard.press("Escape");
  await expectHealthy(page, problems, { label: "rcm chips" });
});

test("full screen: F, a dialog on top, Esc, the row and tab kept", async ({ page, request, problems }) => {
  await page.addInitScript(() => {
    // The page's own full screen (as on an iPhone): Escape leaves it, as the app handles it.
    for (const k of ["requestFullscreen", "webkitRequestFullscreen"]) {
      delete Element.prototype[k];
      delete HTMLElement.prototype[k];
    }
    for (const k of ["exitFullscreen", "webkitExitFullscreen"]) delete Document.prototype[k];
  });
  const tag = `s${Date.now()}`;
  const p = await plant(request, tag);
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pump.id}&tab=rcm`);
  await page.locator("body").click({ position: { x: 5, y: 300 } });
  await page.keyboard.press("f");
  await expect(page.getByRole("button", { name: "Exit full screen" })).toBeVisible();
  expect(await page.evaluate(() => {
    const r = document.querySelector(".tx.is-full").getBoundingClientRect();
    return [r.top, r.left, Math.round(r.width), Math.round(r.height)];
  })).toEqual([0, 0, ...(await page.evaluate(() => [innerWidth, innerHeight]))]);
  // A dialog opens on top, inside full screen.
  await pickRow(page, `Failure mode: Bearing seizes No flow Pump water ${tag}`);
  await page.getByRole("button", { name: "Decide…" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  expect(await page.evaluate(() => document.querySelector(".tx.is-full").contains(document.querySelector("[role=dialog]")))).toBe(true);
  await page.keyboard.press("Escape"); // the dialog first
  await expect(dialog).toHaveCount(0);
  await expect(page.locator(".tx.is-full")).toBeVisible();
  await page.locator(".tt-headslot .td-title").click();
  await page.keyboard.press("Escape"); // then full screen
  await expect(page.locator(".tx.is-full")).toHaveCount(0);
  await expect(trow(page, `Failure mode: Bearing seizes No flow Pump water ${tag}`)).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("tab", { name: "RCM" })).toHaveAttribute("aria-selected", "true");
  await expectHealthy(page, problems, { label: "explorer full screen", root: ".tx" });
});

test("the tree's ⋯ menu: the levels, a filter with its count on the button, Reset, and the keyboard", async ({ page, request, problems }) => {
  await page.addInitScript(() => {
    for (const k of ["requestFullscreen", "webkitRequestFullscreen"]) {
      delete Element.prototype[k];
      delete HTMLElement.prototype[k];
    }
    for (const k of ["exitFullscreen", "webkitExitFullscreen"]) delete Document.prototype[k];
  });
  const tag = `o${Date.now()}`;
  const p = await plant(request, tag);
  await page.setViewportSize({ width: 1280, height: 720 });
  for (const t of ["summary", "rcm"]) {
    await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pump.id}${t === "rcm" ? "&tab=rcm" : ""}`);
    await expect(t === "rcm" ? table(page) : tree(page)).toBeVisible();
    // The same pane on both tabs: the title, +, ⋯, the search box and the counts; the rest is in the menu.
    await expect(menuButton(page)).toHaveAccessibleName("Tree options");
    await expect(page.locator(".tp").getByRole("searchbox")).toBeVisible();
    await expect(page.getByRole("radio", { name: "Locations" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Open to level 1" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Overdue", exact: true })).toHaveCount(0);
  }

  // Summary: the keyboard opens it and walks it.
  await page.getByRole("tab", { name: "Summary" }).click();
  await expect(tree(page)).toBeVisible();
  await menuButton(page).focus();
  await page.keyboard.press("Enter");
  const menu = treeMenu(page);
  await expect(menu).toBeVisible();
  await expect(menu.getByRole("menuitemradio", { name: "Positions" })).toBeFocused(); // the first item
  await expect(menu.getByRole("menuitemradio", { name: "Positions" })).toHaveAttribute("aria-checked", "true");
  await expect(menu.getByRole("menuitemradio", { name: "Open to level 2" })).toHaveAttribute("aria-checked", "true"); // the usual
  await page.keyboard.press("ArrowRight");
  await expect(menu.getByRole("menuitemradio", { name: "Locations" })).toBeFocused();
  await page.keyboard.press("ArrowDown"); // the next row: the levels, on the checked one
  await expect(menu.getByRole("menuitemradio", { name: "Open to level 2" })).toBeFocused();
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("Enter"); // level 3
  await expect(menu).toBeVisible(); // it stays open
  await expect(menu.getByRole("menuitemradio", { name: "Open to level 3" })).toHaveAttribute("aria-checked", "true");
  await expect(treeitem(page, `Rcm motor ${tag}`)).toBeVisible(); // level 3
  await expect(menuButton(page)).toHaveAccessibleName("Tree options: 1 changed");
  await page.keyboard.press("Escape");
  await expect(menu).toHaveCount(0);
  await expect(menuButton(page)).toBeFocused();

  // Close everything from the menu, then a row opened by hand: no level is ticked.
  await openTreeMenu(page);
  await menu.getByRole("menuitemradio", { name: "Close everything" }).click();
  await expect(treeitem(page, `Rcm pump ${tag}`)).toHaveCount(0);
  await page.keyboard.press("Escape");
  await treeitem(page, `Rcm plant ${tag}`).locator(".tp-chev").click();
  await expect(treeitem(page, `Rcm pump ${tag}`)).toBeVisible();
  await expect(menuButton(page)).toHaveAccessibleName("Tree options");
  await openTreeMenu(page);
  await expect(menu.locator("[role=menuitemradio][aria-checked=true]")).toHaveText(["Positions"]);
  await expect(menu.getByRole("menuitem", { name: "Reset to the usual view" })).toHaveCount(0);

  // A filter: ticked, its count on the button and the words by the counts; a click outside closes the menu.
  await menu.getByRole("menuitemcheckbox", { name: "Not analysed" }).click();
  await expect(menu.getByRole("menuitemcheckbox", { name: "Not analysed" })).toHaveAttribute("aria-checked", "true");
  await menu.getByRole("menuitemcheckbox", { name: "Open work" }).click(); // nothing has open work
  await expect(menuButton(page)).toHaveAccessibleName("Tree options: 2 changed");
  await expect(page.locator(".tm-count")).toHaveText("2");
  await page.getByRole("heading", { name: "Explorer", exact: true }).click();
  await expect(menu).toHaveCount(0);
  await expect(page.locator(".tp-status")).toContainText("Showing only Open work and Not analysed");
  await expect(treeitem(page, `Rcm pump ${tag}`)).toHaveCount(0);
  // Reset: back to the usual view, every row back.
  await openTreeMenu(page);
  await menu.getByRole("menuitem", { name: "Reset to the usual view" }).click();
  await expect(menuButton(page)).toHaveAccessibleName("Tree options");
  await expect(page.locator(".tm-count")).toHaveCount(0);
  await expect(menu.getByRole("menuitemcheckbox", { name: "Not analysed" })).toHaveAttribute("aria-checked", "false");
  await expect(menu).toBeVisible();
  await expect(menu.locator(":focus")).toHaveCount(1); // the focus stays in the menu
  await page.keyboard.press("End");
  await expect(menu.getByRole("menuitem", { name: "Done" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(menu).toHaveCount(0);
  await expect(menuButton(page)).toBeFocused();
  await expect(treeitem(page, `Rcm pump ${tag}`)).toBeVisible();

  // An arrangement other than Positions counts too, and Reset brings Positions back.
  await openTreeMenu(page);
  await menu.getByRole("menuitemradio", { name: "Flat" }).click();
  await expect(page).toHaveURL(/arrange=flat/);
  await expect(menu).toBeVisible();
  await expect(menu.getByRole("menuitemradio", { name: "Open to level 1" })).toHaveCount(0); // no levels when flat
  await expect(menuButton(page)).toHaveAccessibleName("Tree options: 1 changed");
  await menu.getByRole("menuitem", { name: "Reset to the usual view" }).click();
  await expect(page).toHaveURL(/arrange=positions/);
  await page.keyboard.press("Escape");

  // In full screen it opens inside it, and F doesn't leave while it's open.
  await page.locator("body").click({ position: { x: 5, y: 300 } });
  await page.keyboard.press("f");
  await expect(page.locator(".tx.is-full")).toBeVisible();
  await openTreeMenu(page);
  expect(await page.evaluate(() => document.querySelector(".tx.is-full").contains(document.querySelector(".tm-menu")))).toBe(true);
  await page.keyboard.press("Escape"); // the menu first
  await expect(menu).toHaveCount(0);
  await expect(page.locator(".tx.is-full")).toBeVisible();
  await expectHealthy(page, problems, { label: "tree menu", root: ".tx" });
});
