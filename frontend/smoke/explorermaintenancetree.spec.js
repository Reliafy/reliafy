// The Explorer's Maintenance tab is one tree-table (Derryn, 22 Nov 2026: no sub-tabs). A work
// package is a row at the lowest point all its tasks meet (worked out from its tasks, so a package
// made on the asset's top holding only the engine's tasks sits at the engine), with its tasks
// listed under it; each task and each package has a Forecast row whose lines say when it's next
// due, each month's count, labour, parts and cost. Open in its menu opens the level's
// Forecast… in the table area, with the spares for the year under it. At 400 px nothing scrolls
// sideways. Each test makes its own small plant through the API.
import { test, expect, open, expectHealthy, postOk } from "./health.js";

const M = "/api/maintenance";
const SHOTS = process.env.SMOKE_SHOTS_DIR || "";
const shot = async (page, name) => {
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}.png` });
};
const nameRow = (page, text) => page.locator(".tp-row", { has: page.locator(".tp-nm", { hasText: text }) });
const sideways = (page) => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);

async function mower(request, tag) {
  const post = (path, data) => postOk(request, path, data);
  const top = await post(`${M}/positions`, { name: `Mower ${tag}` });
  const engine = await post(`${M}/positions`, { name: `Engine ${tag}`, parent_id: top.id });
  const deck = await post(`${M}/positions`, { name: `Deck ${tag}`, parent_id: top.id });
  const oil = await post(`${M}/positions/${engine.id}/tasks`, { name: `Change the oil ${tag}`, interval: 1, unit: "months" });
  const res = await request.patch(`${M}/tasks/${oil.id}`, { data: { cost: 80 } });
  expect(res.ok(), await res.text()).toBeTruthy();
  const plug = await post(`${M}/positions/${engine.id}/tasks`, { name: `Check the plugs ${tag}`, interval: 1, unit: "months" });
  const blade = await post(`${M}/positions/${deck.id}/tasks`, { name: `Sharpen the blades ${tag}`, interval: 1, unit: "months" });
  await post(`${M}/positions/${deck.id}/tasks`, { name: `Clean under the deck ${tag}`, interval: 1, unit: "months" });
  // Both made on the mower's top: the first holds engine and deck tasks, the second the engine's alone.
  const service = await post(`${M}/packages`, { name: `Monthly service ${tag}`, position_id: top.id, every: 1, unit: "months", tasks: [oil.id, blade.id] });
  const engineOnly = await post(`${M}/packages`, { name: `Engine checks ${tag}`, position_id: top.id, every: 1, unit: "months", tasks: [plug.id] });
  return { top, engine, deck, oil, service, engineOnly };
}

test("packages sit where their tasks meet; Forecast rows under a task and a package; the full forecast with spares", async ({ page, request, problems }) => {
  const tag = `t${Date.now()}`;
  const p = await mower(request, tag);
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, `/asset-register/explorer?arrange=positions&root=${p.top.id}&sel=${p.top.id}&tab=maintenance`);
  // No inner views on the tab.
  await expect(page.getByRole("radiogroup", { name: "Maintenance: what to show" })).toHaveCount(0);
  const svc = page.locator(`[id="tp-MP:${p.service.id}"]`);
  const eng = page.locator(`[id="tp-MP:${p.engineOnly.id}"]`);
  // Engine and deck tasks meet at the mower: its package is a row right under it.
  await expect(svc).toBeVisible();
  await expect(svc).toHaveAttribute("aria-level", "2");
  // The engine-only package was made on the mower, but sits at the engine.
  await expect(eng).toHaveCount(0);
  await nameRow(page, `Engine ${tag}`).locator(".tp-chev").click();
  await expect(eng).toBeVisible();
  await expect(eng).toHaveAttribute("aria-level", "3");
  // Its tasks are listed under it, and stay under their own positions, marked Packaged.
  await svc.locator(".tp-chev").click();
  await expect(page.locator(`[id^="tp-mpref:${p.service.id}:"]`)).toHaveCount(2);
  await expect(page.locator(`[id="tp-MT:${p.oil.id}"]`).locator(".mt-pkg-link")).toHaveText(`Monthly service ${tag}`);

  // A package opens beside the table, saying where it sits.
  await eng.locator(".tp-nm").click();
  await expect.poll(() => new URL(page.url()).searchParams.get("mpkg")).toBe(p.engineOnly.id);
  await expect(page.getByRole("complementary", { name: `Engine checks ${tag}` })).toContainText(`Shown at Engine ${tag}, where its task is.`);

  // A task's Forecast: next due, each month, parts and the total.
  await page.locator(`[id="tp-MT:${p.oil.id}"]`).locator(".tp-chev").click();
  const fc = page.locator(`[id="tp-MF:MT:${p.oil.id}"]`);
  await fc.locator(".tp-chev").click();
  await expect(fc).toContainText(/times to \d+ \w+ \d{4}/);
  await expect(fc).toContainText("$");
  await expect(page.locator(`[id="tp-MF:MT:${p.oil.id}:next"]`)).toContainText("Next due");
  // A package's Forecast adds up its tasks.
  const pfc = page.locator(`[id="tp-MF:MP:${p.service.id}"]`);
  await pfc.locator(".tp-chev").click();
  await expect(pfc).toContainText(/tasks to \d+ \w+ \d{4}/);
  await shot(page, "maintenance-tree-forecasts-1440");

  // Open (the full forecast): the level's Forecast… in the table area, with the spares for the year.
  await fc.locator(".tp-nm").click({ button: "right" });
  await page.getByRole("menu").getByRole("menuitem", { name: "Open", exact: true }).click();
  await expect.poll(() => new URL(page.url()).searchParams.get("forecast")).toBe(p.engine.id);
  await expect(page.locator("section.fc-view").first()).toBeVisible();
  await expect(page.getByRole("region", { name: "Spares for the year" }).first()).toBeVisible();
  await shot(page, "maintenance-tree-full-forecast-1440");
  await expectHealthy(page, problems, { label: "maintenance tree" });
});

test("the Maintenance tree at 400 px: a package and a Forecast row, nothing scrolls sideways", async ({ page, request, problems }) => {
  const tag = `u${Date.now()}`;
  const p = await mower(request, tag);
  await page.setViewportSize({ width: 400, height: 860 });
  await open(page, `/asset-register/explorer?arrange=positions&root=${p.top.id}&sel=${p.top.id}&tab=maintenance`);
  const svc = page.locator(`[id="tp-MP:${p.service.id}"]`);
  await expect(svc).toBeVisible();
  await svc.locator(".tp-chev").click();
  await page.locator(`[id="tp-MF:MP:${p.service.id}"]`).locator(".tp-chev").click();
  await expect(page.locator(`[id="tp-MF:MP:${p.service.id}"]`)).toContainText(/tasks to \d+ \w+ \d{4}/);
  await expect(page.locator(`[id="tp-MF:MP:${p.service.id}:next"]`)).toContainText("Next visit");
  await shot(page, "maintenance-tree-400");
  expect(await sideways(page)).toBeLessThanOrEqual(0);
  await expectHealthy(page, problems, { label: "maintenance tree 400" });
});

test("Add to package… takes a task from another branch of the asset; the package moves up to where its tasks meet", async ({ page, request, problems }) => {
  const tag = `v${Date.now()}`;
  const p = await mower(request, tag);
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, `/asset-register/explorer?arrange=positions&root=${p.top.id}&sel=${p.top.id}&tab=maintenance`);
  const eng = page.locator(`[id="tp-MP:${p.engineOnly.id}"]`);
  await nameRow(page, `Deck ${tag}`).locator(".tp-chev").click();
  await nameRow(page, `Clean under the deck ${tag}`).locator(".tp-nm").click({ button: "right" });
  await page.getByRole("menu").getByRole("menuitem", { name: "Add to package…" }).click();
  const pane = page.locator("section.table-pane");
  // The engine's package is on the same asset: it can take the deck's task.
  const pick = pane.getByRole("radio", { name: new RegExp(`Engine checks ${tag}`) });
  await expect(pick).toBeEnabled();
  await pick.check();
  await pane.getByRole("button", { name: "Add", exact: true }).click();
  await expect(nameRow(page, `Clean under the deck ${tag}`).first().locator(".mt-pkg-link")).toHaveText(`Engine checks ${tag}`);
  // Its tasks now meet at the mower: the package is a row right under it.
  await expect(eng).toHaveAttribute("aria-level", "2");
  const got = await (await request.get(`${M}/packages/${p.engineOnly.id}`)).json();
  expect(got.subject.id).toBe(p.top.id);
  await expectHealthy(page, problems, { label: "package moves up" });
});
