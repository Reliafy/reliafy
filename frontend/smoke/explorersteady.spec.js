// Switching the Explorer's tabs (Summary ↔ RCM) moves nothing in the page's
// frame but what's meant to change: the pane, the tree's title, + and ⋯, the
// search box, the counts, the tree's column header and scroll area, every row
// on screen up to the row picked (the RCM tab adds rows under positions, so
// rows below it may go down), the panel's heading and its tabs all stay within
// 1 px, the tree's scroll comes back exactly each time a tab comes back, no
// frame in between flashes (a part that jumps and comes back, or no rows
// drawn), and the focus stays on the tab picked.
// By click, by the arrow keys, and by the browser's Back and Forward; for a
// position with RCM rows and one with none; opened on either tab.
// Each test makes its own small plant through the API.
import { test, expect, open, expectHealthy, postOk } from "./health.js";
import { flashes, frameOf, movedBetween, watchFrames } from "./explorer.js";

const M = "/api/maintenance";

async function plant(request, tag) {
  const post = (path, data) => postOk(request, path, data);
  const top = await post(`${M}/positions`, { name: `Steady plant ${tag}` });
  const units = [];
  for (let u = 1; u <= 6; u += 1) {
    const unit = await post(`${M}/positions`, { name: `Steady unit ${u} ${tag}`, parent_id: top.id });
    units.push(unit);
    for (let k = 1; k <= 3; k += 1) await post(`${M}/positions`, { name: `Steady unit ${u} part ${k} ${tag}`, parent_id: unit.id });
  }
  // Unit 4: functions, functional failures and failure modes (RCM rows).
  const pump = units[3];
  for (const f of ["Pump water", "Contain the water"]) {
    const fn = await post(`${M}/positions/${pump.id}/functions`, { text: `${f} ${tag}` });
    for (const x of ["No flow", "Low flow"]) {
      const ff = await post(`${M}/functions/${fn.id}/failures`, { text: `${x} ${f} ${tag}` });
      await post(`${M}/positions/${pump.id}/failure-modes`, { text: `Seal leaks ${x} ${f} ${tag}`, functional_failure_id: ff.id });
    }
  }
  await post(`${M}/positions/${pump.id}/fit`, { new_item: { name: `Steady item ${tag}`, serial: `ST-${tag}` } });
  return { top, pump, empty: units[1] };
}

const tab = (page, name) => page.getByRole("tab", { name, exact: true });
const settled = async (page) => {
  await page.waitForLoadState("networkidle", { timeout: 5_000 }).catch(() => {});
  await page.waitForTimeout(250);
};

// One switch: the frame before and after, the frames in between, the focus.
async function check(page, label, go, { wantTab, focusTab = true, rows = true, scrolls = {} } = {}) {
  const before = await frameOf(page);
  const stop = await watchFrames(page);
  await go();
  await expect(tab(page, wantTab)).toHaveAttribute("aria-selected", "true");
  const frames = await stop();
  await settled(page);
  const after = await frameOf(page);
  const moved = movedBetween(before, after);
  const shown = rows ? moved : moved.filter((m) => !m.startsWith("row "));
  expect(shown, `${label}: what moved`).toEqual([]);
  expect(flashes(frames), `${label}: flashes`).toEqual([]);
  if (focusTab) await expect(tab(page, wantTab), `${label}: the focus stays on the tab`).toBeFocused();
  // Each tab comes back to the same scroll it had.
  const scroll = (scrolls[wantTab] ??= after.scrollTop);
  expect(Math.abs(after.scrollTop - scroll), `${label}: the tree's scroll on ${wantTab} (${after.scrollTop}, was ${scroll})`).toBeLessThanOrEqual(1);
}

async function switchEveryWay(page, start, options = {}) {
  const [a, b] = start === "RCM" ? ["RCM", "Summary"] : ["Summary", "RCM"];
  const opts = { ...options, scrolls: { [a]: (await frameOf(page)).scrollTop } };
  await check(page, `click ${b}`, () => tab(page, b).click(), { ...opts, wantTab: b });
  await check(page, `click ${a}`, () => tab(page, a).click(), { ...opts, wantTab: a });
  // The arrow keys move along the tabs and open the next.
  await tab(page, a).focus();
  await check(page, `arrow to ${b}`, () => page.keyboard.press(b === "RCM" ? "ArrowRight" : "ArrowLeft"), { ...opts, wantTab: b });
  await check(page, `arrow to ${a}`, () => page.keyboard.press(a === "RCM" ? "ArrowRight" : "ArrowLeft"), { ...opts, wantTab: a });
  // The browser's Back and Forward, over an address that changes ?tab=.
  await page.evaluate((to) => {
    const u = new URL(location.href);
    if (to === "Summary") u.searchParams.delete("tab");
    else u.searchParams.set("tab", "rcm");
    history.pushState(history.state, "", u.toString());
    dispatchEvent(new PopStateEvent("popstate", { state: history.state }));
  }, b);
  await expect(tab(page, b)).toHaveAttribute("aria-selected", "true");
  await settled(page);
  await check(page, `Back to ${a}`, () => page.goBack(), { ...opts, wantTab: a, focusTab: false });
  await check(page, `Forward to ${b}`, () => page.goForward(), { ...opts, wantTab: b, focusTab: false });
}

test("switching tabs moves nothing: a position with RCM rows, the tree scrolled, 1280×720", async ({ page, request, problems }) => {
  await page.setViewportSize({ width: 1280, height: 720 });
  const tag = `s${Date.now()}`;
  const p = await plant(request, tag);
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pump.id}`);
  await expect(page.getByRole("treeitem", { name: new RegExp(`^Steady unit 4 ${tag}`) })).toHaveAttribute("aria-selected", "true");
  // Scroll the tree a little, so its scroll has something to keep.
  await page.locator(".tp-scroll").evaluate((el) => { el.scrollTop = Math.max(0, el.scrollTop - 45); });
  await settled(page);
  await switchEveryWay(page, "Summary");
  // The RCM tab keeps 18 or more rows on screen at 1280×720.
  await expect(tab(page, "RCM")).toHaveAttribute("aria-selected", "true");
  const onScreen = await page.locator(".tp-scroll").evaluate((el) => Math.floor((el.clientHeight - 30) / 30));
  expect(onScreen).toBeGreaterThanOrEqual(18);
  await expectHealthy(page, problems, { label: "explorer steady tabs" });
});

test("switching tabs moves nothing: a position with no RCM yet, opened on the RCM tab, 1440×800", async ({ page, request, problems }) => {
  await page.setViewportSize({ width: 1440, height: 800 });
  const tag = `e${Date.now()}`;
  const p = await plant(request, tag);
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.empty.id}&tab=rcm`);
  const row = page.getByRole("row", { name: new RegExp(`^Steady unit 2 ${tag}`) });
  await expect(row).toHaveAttribute("aria-selected", "true");
  // Opened on the RCM tab, the row picked is in view.
  const view = await page.locator(".tp-scroll").boundingBox();
  const box = await row.boundingBox();
  expect(box.y).toBeGreaterThanOrEqual(view.y);
  expect(box.y + box.height).toBeLessThanOrEqual(view.y + view.height);
  await switchEveryWay(page, "RCM");
  await expectHealthy(page, problems, { label: "explorer steady tabs, from RCM" });
});

test("switching tabs moves nothing with a branch pinned, and a long operating context on the Summary", async ({ page, request, problems }) => {
  await page.setViewportSize({ width: 1280, height: 720 });
  const tag = `b${Date.now()}`;
  const p = await plant(request, tag);
  const res = await request.patch(`${M}/positions/${p.pump.id}`, {
    data: { operating_context: `Runs on demand in a dusty pump house, 18 hours a day ${tag}.\n`.repeat(12) },
  });
  expect(res.ok()).toBeTruthy();
  // Without a pin first: where the tree starts on each tab.
  const treeTop = {};
  for (const t of ["Summary", "RCM"]) {
    await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pump.id}${t === "RCM" ? "&tab=rcm" : ""}`);
    await expect(tab(page, t)).toHaveAttribute("aria-selected", "true");
    await settled(page);
    treeTop[t] = (await frameOf(page)).boxes.tree;
  }
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pump.id}&pin=${p.top.id}`);
  // The pin is said in the tree's column header, with no row of its own: the
  // tree starts exactly where it does without a pin.
  const pinNote = page.locator(".tt-head").getByRole("group", { name: "Pinned branch" });
  await expect(pinNote).toContainText(`Pinned: Steady plant ${tag}`);
  await expect(page.getByRole("region", { name: "Operating context" })).toBeVisible();
  expect((await frameOf(page)).boxes.tree).toEqual(treeTop.Summary);
  await switchEveryWay(page, "Summary");
  // On the RCM tab: the note in the same place, the tree where it is without a
  // pin, and 18 or more rows on screen at 1280×720.
  await expect(tab(page, "RCM")).toHaveAttribute("aria-selected", "true");
  const note = await pinNote.boundingBox();
  expect((await frameOf(page)).boxes.tree).toEqual(treeTop.RCM);
  const onScreen = await page.locator(".tp-scroll").evaluate((el) => Math.floor((el.clientHeight - 30) / 30));
  expect(onScreen).toBeGreaterThanOrEqual(18);
  await tab(page, "Summary").click();
  await settled(page);
  expect(await pinNote.boundingBox()).toEqual(note);
  // Its ✕ shows everything; the frame stays put.
  const before = await frameOf(page);
  await pinNote.getByRole("button", { name: "Show everything" }).click();
  await expect(pinNote).toHaveCount(0);
  const after = await frameOf(page);
  expect(after.boxes.tree).toEqual(before.boxes.tree);
  expect(after.boxes.column).toEqual(before.boxes.column);
  await expectHealthy(page, problems, { label: "explorer steady tabs, pinned" });
});

test("on a phone with a branch pinned, switching tabs leaves the frame where it is", async ({ page, request, problems }) => {
  await page.setViewportSize({ width: 400, height: 800 });
  const tag = `q${Date.now()}`;
  const p = await plant(request, tag);
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pump.id}&pin=${p.top.id}`);
  await expect(page.getByRole("treeitem", { name: new RegExp(`^Pinned: Steady plant ${tag}`) })).toBeVisible();
  const scrolls = { Summary: (await frameOf(page)).scrollTop };
  await check(page, "phone, pinned: to RCM", () => tab(page, "RCM").click(), { wantTab: "RCM", rows: false, scrolls });
  await check(page, "phone, pinned: to Summary", () => tab(page, "Summary").click(), { wantTab: "Summary", rows: false, scrolls });
  expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(0);
  await expectHealthy(page, problems, { label: "explorer steady tabs, phone, pinned" });
});

test("on a phone, switching tabs leaves the title, the tabs, the search box and the tree where they are", async ({ page, request, problems }) => {
  await page.setViewportSize({ width: 400, height: 800 });
  const tag = `p${Date.now()}`;
  const p = await plant(request, tag);
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pump.id}`);
  // On a phone the RCM tab's rows are two lines (the second its RCM in words),
  // so the rows themselves change; the frame round them doesn't.
  const scrolls = { Summary: (await frameOf(page)).scrollTop };
  await check(page, "phone: to RCM", () => tab(page, "RCM").click(), { wantTab: "RCM", rows: false, scrolls });
  await check(page, "phone: to Summary", () => tab(page, "Summary").click(), { wantTab: "Summary", rows: false, scrolls });
  await check(page, "phone: to RCM again", () => tab(page, "RCM").click(), { wantTab: "RCM", rows: false, scrolls });
  const side = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
  expect(side).toBeLessThanOrEqual(0);
  await expectHealthy(page, problems, { label: "explorer steady tabs, phone" });
});

// Linking a functional failure to a cause below it adds a reference row and
// nothing else: no new column, no new control in the heading, so the frame
// round the table stays where it is.
test("linking a functional failure to a cause below moves nothing in the heading or the frame", async ({ page, request, problems }) => {
  await page.setViewportSize({ width: 1280, height: 720 });
  const tag = `l${Date.now()}`;
  const p = await plant(request, tag);
  const fn = await postOk(request, `${M}/positions/${p.top.id}/functions`, { text: `Keep the plant running ${tag}` });
  await postOk(request, `${M}/functions/${fn.id}/failures`, { text: `Plant stops ${tag}` });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.top.id}&tab=rcm`);
  const higher = page.getByRole("row", { name: new RegExp(`Plant stops ${tag}`) });
  await expect(higher).toBeVisible();
  await settled(page);
  const before = await frameOf(page);
  const heading = page.locator(".tt-headslot");
  const headBefore = await heading.boundingBox();
  const colsBefore = await page.locator(".tt-head [role=columnheader]").count();

  await higher.click({ button: "right" });
  await page.getByRole("menuitem", { name: "Link to a cause…" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText(`Link a cause of “Plant stops ${tag}”`);
  await dialog.getByRole("checkbox", { name: new RegExp(`No flow Pump water ${tag}`) }).check();
  await dialog.getByRole("button", { name: "Link 1 cause" }).click();
  await expect(dialog).toHaveCount(0);
  const ref = page.getByRole("row", { name: new RegExp(`Caused by: No flow Pump water ${tag}`) });
  await expect(ref).toBeVisible();
  await settled(page);

  expect(await heading.boundingBox(), "the heading's bounding box").toEqual(headBefore);
  expect(await page.locator(".tt-head [role=columnheader]").count(), "no new column").toBe(colsBefore);
  const after = await frameOf(page);
  // Every box in the frame but the name (a "Linked 1 cause." message shows beside it, as any change's does) and the rows.
  const moved = movedBetween(before, after).filter((m) => !m.startsWith("row ") && !m.startsWith("name.") && !m.startsWith("(rows"));
  expect(moved, "what moved").toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(0);

  // The lower failure says what it causes; the reference row goes to it.
  await ref.click();
  await expect(page.getByRole("row", { name: new RegExp(`^Functional failure: No flow Pump water ${tag}`) })).toHaveAttribute("aria-selected", "true");
  await expectHealthy(page, problems, { label: "explorer rcm links" });
});

test("on a phone the picker is a sheet, and the page doesn't scroll sideways", async ({ page, request, problems }) => {
  await page.setViewportSize({ width: 400, height: 800 });
  const tag = `m${Date.now()}`;
  const p = await plant(request, tag);
  const fn = await postOk(request, `${M}/positions/${p.top.id}/functions`, { text: `Keep the plant running ${tag}` });
  await postOk(request, `${M}/functions/${fn.id}/failures`, { text: `Plant stops ${tag}` });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.top.id}&tab=rcm`);
  await page.getByRole("row", { name: new RegExp(`Plant stops ${tag}`) }).click({ button: "right" });
  await page.getByRole("menuitem", { name: "Link to a cause…" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  const box = await dialog.boundingBox();
  expect(box.width).toBeLessThanOrEqual(400);
  expect(box.y + box.height).toBeGreaterThan(790); // anchored to the bottom, as a sheet
  expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(0);
  await dialog.getByRole("button", { name: "Cancel" }).click();
  await expect(dialog).toHaveCount(0);
  await expectHealthy(page, problems, { label: "explorer rcm links, phone" });
});
