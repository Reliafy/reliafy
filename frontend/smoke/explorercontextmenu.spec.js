// Right-click in the Explorer, the product tree and the lists that lead to them (the menu standard,
// Derryn, 23 Nov 2026): every row kind and every area opens the app's menu, never the browser's
// (the contextmenu event is cancelled and a menu shows); a row's menu starts Open · Rename… · Move
// to… · Focus · Pin this branch · Copy link, and its red Delete…, Retire…, Unlink… or Remove from…
// is last, after a line. A field being typed in keeps the browser's own menu.
//
// With SMOKE_SHOTS_DIR set, it also saves screenshots there (for the pull request).
import { test, expect, open, postOk } from "./health.js";
import { phoneTree } from "./explorer.js";

const M = "/api/maintenance";
const SHOTS = process.env.SMOKE_SHOTS_DIR || "";
const shot = async (page, name) => {
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}.png` });
};
const GENERAL = ["Open", "Rename…", "Move to…", "Focus", "Pin this branch", "Copy link"];

// Whether the last right-click was cancelled (the browser's menu kept away), read after React's
// handlers ran (a listener on the window, bubbling, runs last).
async function watchContextMenu(page) {
  await page.evaluate(() => {
    window.__ctx = null;
    window.addEventListener("contextmenu", (e) => { window.__ctx = e.defaultPrevented; });
  });
}
async function rightClick(page, target, opts = {}) {
  await page.evaluate(() => { window.__ctx = null; });
  await target.click({ button: "right", ...opts });
  await expect.poll(() => page.evaluate(() => window.__ctx), { message: "the browser's own menu was kept away" }).toBe(true);
  const menu = page.getByRole("menu").first();
  await expect(menu).toBeVisible();
  return menu;
}
// The menu's top level: labels and lines, in order.
async function shape(menu) {
  return menu.evaluate((el) => [...el.children].map((c) => (c.getAttribute("role") === "separator" ? "———"
    : (c.dataset.label || c.textContent || "").trim())).filter(Boolean));
}
async function expectStandard(menu, last) {
  const s = await shape(menu);
  expect(s.slice(0, 6)).toEqual(GENERAL);
  if (last) {
    expect(s.at(-1)).toBe(last);
    expect(s.at(-2)).toBe("———");
    await expect(menu.locator(":scope > .ovm-item").last()).toHaveClass(/danger/);
  }
  expect(s.filter((x) => x !== "———").length).toBeLessThanOrEqual(10);
}

test("right-click opens the app's menu on every row kind and area, never the browser's", async ({ page, request, problems }) => {
  const tag = `c${Date.now()}`;
  const site = await postOk(request, `${M}/locations`, { name: `Ctx site ${tag}` });
  const pump = await postOk(request, `${M}/positions`, { name: `Ctx pump ${tag}`, location_id: site.id });
  const motor = await postOk(request, `${M}/positions`, { name: `Ctx motor ${tag}`, parent_id: pump.id });
  await postOk(request, `${M}/positions/${motor.id}/tasks`, { name: `Ctx grease ${tag}`, interval: 1, unit: "months", trade: "Fitter" });
  await postOk(request, `${M}/positions/${motor.id}/models`, { model_id: "sample-model-bearings-weibull" });
  await postOk(request, `${M}/positions/${pump.id}/functions`, { text: `Ctx pump water ${tag}` });
  await page.setViewportSize({ width: 1440, height: 900 });
  const row = (name) => page.locator(".tp-row", { hasText: name }).first();
  const esc = async () => {
    await page.keyboard.press("Escape");
    await expect(page.getByRole("menu")).toHaveCount(0);
  };

  // Summary: a position (Delete… last), its column header and the space under the rows.
  await open(page, `/asset-register/explorer?arrange=positions&sel=${motor.id}`);
  await watchContextMenu(page);
  let menu = await rightClick(page, row(`Ctx pump ${tag}`).locator(".tp-nm"));
  await expectStandard(menu, "Delete…");
  await shot(page, "ctx-summary-position");
  await esc();
  menu = await rightClick(page, page.locator(".tp-scroll").first(), { position: { x: 40, y: 600 } });
  await esc();
  menu = await rightClick(page, page.locator(".tt-head").first());
  await expect(menu.getByRole("menuitem", { name: "Open to a level" })).toBeVisible();
  await esc();
  // The panel's tab strip and its body: the menu of the row the panel is about.
  menu = await rightClick(page, page.locator(".tt-tabslot").first());
  await expectStandard(menu, "Delete…");
  await esc();
  menu = await rightClick(page, page.locator(".tx-detail, .tt-main").first().getByRole("heading").first());
  await esc();
  // A field keeps the browser's menu (copy and paste).
  await page.evaluate(() => { window.__ctx = null; });
  await page.getByRole("searchbox").or(page.locator(".tp-filter input")).first().click({ button: "right" });
  expect(await page.evaluate(() => window.__ctx)).toBe(false);
  await page.keyboard.press("Escape");

  // Locations: a place. Classes: the "No class" group row (no red item).
  await open(page, `/asset-register/explorer?arrange=locations&sel=${site.id}`);
  await watchContextMenu(page);
  menu = await rightClick(page, row(`Ctx site ${tag}`).locator(".tp-nm"));
  await expectStandard(menu, "Delete…");
  await esc();
  await open(page, `/asset-register/explorer?arrange=classes&sel=${motor.id}`);
  await watchContextMenu(page);
  menu = await rightClick(page, page.locator(".tp-row.grp, .tp-row", { hasText: "No class" }).first());
  expect((await shape(menu)).slice(0, 6)).toEqual(GENERAL);
  await expect(menu.locator(".danger")).toHaveCount(0);
  await esc();

  // Maintenance: a position (Delete…), a task (Retire…).
  await open(page, `/asset-register/explorer?arrange=positions&sel=${motor.id}&tab=maintenance`);
  await watchContextMenu(page);
  menu = await rightClick(page, row(`Ctx motor ${tag}`).locator(".tp-nm"));
  await expectStandard(menu, "Delete…");
  await esc();
  menu = await rightClick(page, row(`Ctx grease ${tag}`).locator(".tp-nm"));
  await expectStandard(menu, "Retire…");
  await shot(page, "ctx-maintenance-task");
  await esc();
  // The panel heading's ⋯: the same general section as the row's own.
  await page.locator(".tt-headslot .ovm-trigger").click();
  await expectStandard(page.getByRole("menu").first(), null);
  await esc();

  // Models: a position (Delete…), a model (Unlink…).
  await open(page, `/asset-register/explorer?arrange=positions&sel=${motor.id}&tab=models`);
  await watchContextMenu(page);
  menu = await rightClick(page, row(`Ctx motor ${tag}`).locator(".tp-nm"));
  await expectStandard(menu, "Delete…");
  await esc();
  menu = await rightClick(page, page.locator(".tp-row[data-key^='L']").first().locator(".tp-nm"));
  await expectStandard(menu, "Unlink…");
  await shot(page, "ctx-models-model");
  await esc();

  // RCM: a function (Delete…); Monitoring: a position (its adds in Add ›).
  await open(page, `/asset-register/explorer?arrange=positions&sel=${pump.id}&tab=rcm`);
  await watchContextMenu(page);
  menu = await rightClick(page, row(`Ctx pump water ${tag}`).locator(".tp-nm"));
  await expectStandard(menu, "Delete…");
  await esc();
  await open(page, `/asset-register/explorer?arrange=positions&sel=${pump.id}&tab=measurements`);
  await watchContextMenu(page);
  menu = await rightClick(page, row(`Ctx pump ${tag}`).locator(".tp-nm"));
  await expectStandard(menu, "Delete…");
  await expect(menu.getByRole("menuitem", { name: "Add", exact: true })).toHaveAttribute("aria-haspopup", "menu");
  await esc();

  // The lists that lead into the trees: Assets and Products rows open their ⋯ menu.
  await open(page, "/asset-register");
  await watchContextMenu(page);
  menu = await rightClick(page, page.locator("tr.lib-row", { hasText: `Ctx site ${tag}` }).first());
  await expect(menu.getByRole("menuitem", { name: "Open" })).toBeVisible();
  await expect(menu.locator(".ovm-item").last()).toHaveText("Delete…");
  await esc();
  await open(page, "/products");
  await watchContextMenu(page);
  menu = await rightClick(page, page.locator("tr.lib-row").first());
  await expect(menu.locator(".ovm-item").last()).toHaveClass(/danger/);
  await esc();

  // Type to jump: "C" moves to Copy link.
  await open(page, `/asset-register/explorer?arrange=positions&sel=${motor.id}`);
  await watchContextMenu(page);
  menu = await rightClick(page, row(`Ctx pump ${tag}`).locator(".tp-nm"));
  await page.keyboard.press("c");
  await expect(menu.getByRole("menuitem", { name: "Copy link" })).toBeFocused();
  await esc();
  await expect(row(`Ctx pump ${tag}`)).toBeFocused();
  expect(problems).toEqual([]);
});

test("a long press on a phone opens the row's menu and lifting the finger keeps it open", async ({ browser, request }) => {
  const tag = `l${Date.now()}`;
  const site = await postOk(request, `${M}/locations`, { name: `Press site ${tag}` });
  const pump = await postOk(request, `${M}/positions`, { name: `Press pump ${tag}`, location_id: site.id });
  const ctx = await browser.newContext({ viewport: { width: 400, height: 860 }, hasTouch: true, isMobile: true });
  const page = await ctx.newPage();
  await open(page, `/asset-register/explorer?arrange=positions&sel=${pump.id}`);
  await phoneTree(page);
  const target = page.locator(".tp-row", { hasText: `Press pump ${tag}` }).first().locator(".tp-nm");
  await expect(target).toBeVisible();
  const box = await target.boundingBox();
  const cdp = await ctx.newCDPSession(page);
  const point = { x: box.x + 10, y: box.y + box.height / 2 };
  await cdp.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [point] });
  await page.waitForTimeout(700);
  await expect(page.getByRole("menu").first()).toBeVisible();
  await cdp.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
  await page.waitForTimeout(400);
  await expect(page.getByRole("menu").first()).toBeVisible();
  const callout = await target.evaluate((el) => getComputedStyle(el.closest(".tp-row")).webkitTouchCallout || getComputedStyle(el.closest(".tp-row")).getPropertyValue("-webkit-touch-callout"));
  expect(["none", ""]).toContain(callout);
  await shot(page, "ctx-phone-after-lift");
  await ctx.close();
});
