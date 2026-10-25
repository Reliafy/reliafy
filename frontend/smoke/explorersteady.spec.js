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
import { test, expect, open, expectHealthy } from "./health.js";
import { flashes, frameOf, movedBetween, watchFrames } from "./explorer.js";

const M = "/api/maintenance";

async function plant(request, tag) {
  const post = async (path, data) => {
    const res = await request.post(path, { data });
    expect(res.ok(), `${path}: ${res.status()} ${await res.text()}`).toBeTruthy();
    return res.json();
  };
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
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pump.id}&pin=${p.top.id}`);
  await expect(page.getByRole("group", { name: "Pinned branch" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Operating context" })).toBeVisible();
  await switchEveryWay(page, "Summary");
  // The pinned bar stays where it was, as wide as the tree.
  const bar = await page.getByRole("group", { name: "Pinned branch" }).boundingBox();
  await tab(page, "Summary").click();
  await settled(page);
  expect(await page.getByRole("group", { name: "Pinned branch" }).boundingBox()).toEqual(bar);
  await expectHealthy(page, problems, { label: "explorer steady tabs, pinned" });
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
