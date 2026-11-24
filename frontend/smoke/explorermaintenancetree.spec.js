// The Explorer's Maintenance tab is one tree-table (Derryn, 22 Nov 2026: no sub-tabs). A work
// package is a row at the lowest point all its tasks meet (worked out from its tasks, so a package
// made on the asset's top holding only the engine's tasks sits at the engine): one row with nothing
// under it, its tasks listed in its details (they show under their own positions only). A
// double-click opens its details across the table. No forecast rows (Derryn, 23 Nov 2026): Next due is a column, a package's next
// visit in it and a level's soonest beneath it, sorted from its header; Open in › on a package opens
// the left menu's forecast tool filled in from it. At 400 px nothing scrolls sideways. Each test makes its own small plant through the API.
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

test("packages sit where their tasks meet; Next due by row and by level, sorted; Open in › from a package", async ({ page, request, problems }) => {
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
  // No task under it (no double up): its tasks show under their own positions only, marked Packaged.
  // Only its tasks' extras together (labour, parts, cost a visit) may hang under it.
  await expect(page.locator(`[id^="tp-mpref:"]`)).toHaveCount(0);
  await expect(page.locator(`[id="tp-MT:${p.oil.id}"]`).locator(".mt-pkg-link")).toHaveText(`Monthly service ${tag}`);
  await expect(page.locator(`[id="tp-MT:${p.oil.id}"]`)).toHaveCount(1);

  // A double-click opens its details across the table (the columns give way), its tasks listed
  // there; a task's name picks it in the tree. Back to table (or Esc) puts the table back.
  await svc.locator(".tp-nm").dblclick();
  const side = page.getByRole("complementary", { name: `Monthly service ${tag}` });
  await expect(side).toHaveClass(/is-expanded/);
  await expect(page.getByRole("columnheader", { name: "Interval" })).toHaveCount(0);
  await shot(page, "package-details-wide-1440");
  await side.getByRole("button", { name: "Back to table" }).click();
  await expect(page.getByRole("columnheader", { name: "Interval" })).toBeVisible();
  await expect(side).not.toHaveClass(/is-expanded/);
  await shot(page, "package-row-and-details-1440");
  await side.getByRole("button", { name: `Change the oil ${tag}`, exact: true }).click();
  await expect.poll(() => new URL(page.url()).searchParams.get("mtask")).toBe(p.oil.id);
  await expect(page.locator(`[id="tp-MT:${p.oil.id}"]`)).toBeVisible();
  await page.keyboard.press("Escape");

  // A package opens beside the table, saying where it sits.
  await eng.locator(".tp-nm").click();
  await expect.poll(() => new URL(page.url()).searchParams.get("mpkg")).toBe(p.engineOnly.id);
  await expect(page.getByRole("complementary", { name: `Engine checks ${tag}` })).toContainText(`Shown at Engine ${tag}, where its task is.`);

  // No Forecast rows: under a task are only its extras (its labour, parts and a typed cost). A
  // package's Next due is its next visit (a date); the mower's is the soonest beneath it.
  await expect(page.locator(`[id^="tp-MF:"]`)).toHaveCount(0);
  const date = /^\d{1,2} \w{3} \d{4}/;
  await expect(svc.locator(".mt-c-due")).toHaveText(date);
  await expect(page.locator(`[id="tp-${p.top.id}"] .mt-c-due`)).toHaveText(date);
  // A task with no record of when it was last done: a dash, saying why.
  await expect(page.locator(`[id="tp-MT:${p.oil.id}"] .mt-c-due span`)).toHaveAttribute("title", /No record|visit of/);
  // Next due sorts from its header: soonest first, then latest, then the tree's order.
  const head = page.locator('[role="columnheader"]', { has: page.getByRole("button", { name: /^Next due: sort/ }) });
  const sortBy = head.getByRole("button", { name: /^Next due: sort/ });
  await sortBy.click();
  await expect(head).toHaveAttribute("aria-sort", "ascending");
  await sortBy.click();
  await expect(head).toHaveAttribute("aria-sort", "descending");
  await sortBy.click();
  await expect(head).toHaveAttribute("aria-sort", "none");
  await shot(page, "maintenance-tree-next-due-1440");

  // Open in › Cost forecast on a package: the tool, filled in from its tasks' positions.
  await svc.locator(".tp-nm").click({ button: "right" });
  await page.getByRole("menu").getByRole("menuitem", { name: /^Open in/ }).click();
  await page.getByRole("menuitem", { name: "Cost forecast" }).click();
  await expect(page).toHaveURL(new RegExp(`/forecasts/costs\\?from=package%3A${p.service.id}`));
  await expect(page.locator(".ft-from")).toContainText(`Monthly service ${tag}`);
  await expectHealthy(page, problems, { label: "maintenance tree" });
});

test("the Maintenance tree at 400 px: a package with its next visit, nothing scrolls sideways", async ({ page, request, problems }) => {
  const tag = `u${Date.now()}`;
  const p = await mower(request, tag);
  await page.setViewportSize({ width: 400, height: 860 });
  await open(page, `/asset-register/explorer?arrange=positions&root=${p.top.id}&sel=${p.top.id}&tab=maintenance`);
  const svc = page.locator(`[id="tp-MP:${p.service.id}"]`);
  await expect(svc).toBeVisible();
  await expect(svc).toContainText(/Next \d+ \w+ \d{4}/);
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
  // Open in › keeps its place in the menu; Add to package… is under More ›.
  await page.getByRole("menu").getByRole("menuitem", { name: /^More/ }).click();
  await page.getByRole("menuitem", { name: "Add to package…" }).click();
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
