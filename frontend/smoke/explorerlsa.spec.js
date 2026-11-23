// What was the Explorer's LSA tab is part of the Maintenance tab's one table now (Derryn, 22 Nov
// 2026: no sub-tabs on Maintenance). A task's What it needs (its LSA: labour, tools, spares,
// method) is a section of its details panel (folded; ?mtask=…&needs=1
// opens it), saved with the task's Save; the old ?tab=lsa&task= address opens it there. Package the tasks…
// on a level drafts packages from its tasks, in the table area, and the packages then sit at the
// meeting point of their tasks. The RCM's Cost and needs links to What it needs and back. A product's
// design has What it needs too (no packaging there), and its links stay on the product's page.
// At 400 px nothing scrolls sideways. Each test makes its own small plant through the API.
import { test, expect, open, expectHealthy, postOk } from "./health.js";

const M = "/api/maintenance";
const SHOTS = process.env.SMOKE_SHOTS_DIR || "";
const shot = async (page, name) => {
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}.png` });
};
const query = (page) => new URL(page.url()).searchParams;
const nameRow = (page, text) => page.locator(".tp-row", { has: page.locator(".tp-nm", { hasText: text }) });
const side = (page) => page.locator(".mt-task-panel");
const sideways = (page) => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);

async function plant(request, tag) {
  const post = (path, data) => postOk(request, path, data);
  const pool = await post(`${M}/positions`, { name: `Package pool ${tag}` });
  const pump = await post(`${M}/positions`, { name: `Package pump ${tag}`, parent_id: pool.id });
  for (const [name, interval, unit] of [["Skim", 1, "weeks"], ["Test water", 1, "weeks"], ["Clean cell", 1, "months"]]) {
    await post(`${M}/positions/${pump.id}/tasks`, { name: `${name} ${tag}`, interval, unit });
  }
  return { pool, pump };
}

// Package the tasks…, then Make: each trade's visit holds tasks on different positions (the short
// one on the battery, its layer's on the alternator), every draft is made, and each package sits
// where its tasks are.
test("Package the tasks… on a level makes every draft; each package sits where its tasks meet", async ({ page, request, problems }) => {
  const tag = `g${Date.now()}`;
  const post = (path, data) => postOk(request, path, data);
  const set = await post(`${M}/positions`, { name: `Genset ${tag}` });
  const battery = await post(`${M}/positions`, { name: `Battery ${tag}`, parent_id: set.id });
  const alternator = await post(`${M}/positions`, { name: `Alternator ${tag}`, parent_id: set.id });
  await post(`${M}/positions/${battery.id}/tasks`, { name: `Test battery ${tag}`, interval: 3, unit: "months", trade: "Electrician" });
  await post(`${M}/positions/${alternator.id}/tasks`, { name: `Load bank test ${tag}`, interval: 6, unit: "months", trade: "Electrician" });
  await page.setViewportSize({ width: 1280, height: 800 });
  await open(page, `/asset-register/explorer?arrange=positions&root=${set.id}&sel=${set.id}&tab=maintenance`);
  await expect(nameRow(page, `Battery ${tag}`)).toBeVisible();
  await nameRow(page, `Genset ${tag}`).first().locator(".tp-nm").click({ button: "right" });
  await page.getByRole("menu").getByRole("menuitem", { name: "Package the tasks…" }).click();
  const packaging = page.locator(".pk-packaging");
  await expect(packaging.locator(".pk-prow")).toHaveCount(2);
  await shot(page, "lsa-package-drafts");
  await packaging.getByRole("button", { name: "Make 2 packages" }).click();
  await expect(page.getByText("Made 2 packages.")).toBeVisible();
  const made = await (await request.get(`${M}/packages?position_id=${set.id}`)).json();
  expect(made.packages).toHaveLength(2);
  // The packages are rows: one at the battery, one at the alternator (where each one's task is).
  await nameRow(page, `Battery ${tag}`).locator(".tp-chev").click();
  await nameRow(page, `Alternator ${tag}`).locator(".tp-chev").click();
  const pkgRows = page.locator('[id^="tp-MP:"]');
  await expect(pkgRows).toHaveCount(2);
  await shot(page, "lsa-package-made");
  await expectHealthy(page, problems, { label: "Package the tasks, made" });
});

test("Next due follows a task's first due date (start)", async ({ page, request, problems }) => {
  const tag = `s${Date.now()}`;
  const pool = await postOk(request, `${M}/positions`, { name: `Start pool ${tag}` });
  const year = new Date().getFullYear() + 1;
  await postOk(request, `${M}/positions/${pool.id}/tasks`,
    { name: `Raise the acid dose for summer ${tag}`, interval: 12, unit: "months", start: `${year}-10-01` });
  await page.setViewportSize({ width: 1280, height: 800 });
  await open(page, `/asset-register/explorer?arrange=positions&root=${pool.id}&sel=${pool.id}&tab=lsa`); // the old address
  await expect.poll(() => query(page).get("tab")).toBe("maintenance");
  await expect(nameRow(page, `Raise the acid dose for summer ${tag}`)).toContainText(new RegExp(`Oct.*${year}|${year}.*Oct`));
  await expectHealthy(page, problems, { label: "lsa start", root: ".tx" });
});

test("What it needs is a section of the task's details: add a labour line and a tool, then Save", async ({ page, request, problems }) => {
  const tag = `l${Date.now()}`;
  const p = await plant(request, tag);
  const tasks = await (await request.get(`${M}/task-table?position_id=${p.pump.id}`)).json();
  const test = tasks.tasks.find((t) => t.name === `Test water ${tag}`);
  await page.setViewportSize({ width: 1280, height: 800 });
  await open(page, `/asset-register/explorer?arrange=positions&root=${p.pool.id}&sel=${p.pump.id}&tab=maintenance`);
  await nameRow(page, `Test water ${tag}`).first().locator(".tp-nm").click({ button: "right" });
  const menu = page.getByRole("menu");
  await expect(menu.getByRole("menuitem", { name: "What it needs…" })).toHaveCount(0); // no entry of its own
  await menu.getByRole("menuitem", { name: "Open", exact: true }).click();
  const needs = side(page).getByRole("region", { name: "What it needs" });
  await expect(needs).toBeVisible();
  // Labour is a fold-out of its own (Derryn, 23 Nov 2026), folded until asked for; the rest is What it needs.
  await expect(side(page).getByRole("region", { name: "Labour" })).toHaveCount(0);
  await side(page).getByRole("button", { name: /^Labour/ }).click();
  await needs.getByRole("button", { name: /^Show what/ }).click();
  const labour = side(page).getByRole("region", { name: "Labour" });
  await labour.getByRole("button", { name: "+ Add labour" }).click();
  await labour.getByRole("textbox", { name: "Trade, line 1" }).fill("Pool technician");
  await labour.getByRole("spinbutton", { name: "Hours each, line 1" }).fill("0.5");
  const tools = side(page).getByRole("region", { name: "Tools and instruments" });
  await tools.getByRole("button", { name: "+ Add a tool" }).click();
  await tools.getByRole("textbox", { name: "Tool, line 1" }).fill("Photometer");
  await shot(page, "lsa-task-desktop");
  await expect(side(page).getByRole("button", { name: "Save" })).toHaveCount(1); // the footer's, the only one
  await side(page).getByRole("button", { name: "Save" }).click();
  await expect.poll(() => query(page).get("mtask")).toBeNull();
  // The old address opens the task with the section open, and what was saved is there.
  await open(page, `/asset-register/explorer?arrange=positions&root=${p.pool.id}&sel=${p.pump.id}&tab=maintenance&mtask=${test.id}&needs=1`);
  await expect(side(page).getByRole("button", { name: /^Labour/ })).toContainText("0.5 h Pool technician");
  await expect(side(page).getByRole("textbox", { name: "Tool, line 1" })).toHaveValue("Photometer");
  await expect(side(page).getByRole("link", { name: "What it needs (LSA)" })).toHaveCount(0);
  await expectHealthy(page, problems, { label: "lsa task", root: ".tx" });
});
test("a task's LSA and its row on the RCM tab link to each other: Serves → the task's row, What it needs → back", async ({ page, request, problems }) => {
  const tag = `k${Date.now()}`;
  const post = (path, data) => postOk(request, path, data);
  const pump = await post(`${M}/positions`, { name: `Package link pump ${tag}` });
  const fn = await post(`${M}/positions/${pump.id}/functions`, { text: `Move water ${tag}` });
  const ff = await post(`${M}/functions/${fn.id}/failures`, { text: `No flow ${tag}` });
  const fm = await post(`${M}/positions/${pump.id}/failure-modes`, { text: `Impeller clogs ${tag}`, functional_failure_id: ff.id });
  const res = await request.put(`${M}/failure-modes/${fm.id}/decision`, {
    data: { consequence: "operational", decision: { outcome: "on_condition", task: `Look in the basket ${tag}`, interval: 1, interval_unit: "weeks" } },
  });
  expect(res.ok()).toBeTruthy();
  const taskId = (await res.json()).decision.task_id;
  await page.setViewportSize({ width: 1280, height: 800 });
  // The old address of a task's LSA opens it beside the Maintenance tab's table.
  await open(page, `/asset-register/explorer?arrange=positions&sel=${pump.id}&tab=lsa&task=${taskId}`);
  await expect.poll(() => [query(page).get("tab"), query(page).get("mtask"), query(page).get("needs")]).toEqual(["maintenance", taskId, "1"]);
  const serves = side(page).locator(".lsa-modes");
  await expect(serves).toContainText(`Impeller clogs ${tag}`);
  await serves.getByRole("link", { name: `Impeller clogs ${tag}` }).click();
  await expect.poll(() => query(page).get("tab")).toBe("rcm");
  const table = page.getByRole("treegrid", { name: /and their RCM/ });
  const taskRow = table.getByRole("row", { name: new RegExp(`^Task: Look in the basket ${tag}`) });
  await expect(taskRow).toHaveAttribute("aria-selected", "true");
  // Its details: Cost and needs, with What it needs back to the task's LSA.
  await taskRow.locator(".tp-nm").dblclick();
  const logistics = page.getByRole("complementary", { name: "Details" }).getByRole("region", { name: "Cost and needs" });
  await expect(logistics.getByRole("button", { name: /^Labour/ })).toBeVisible();
  await logistics.getByRole("link", { name: "What it needs" }).click();
  await expect.poll(() => [query(page).get("tab"), query(page).get("mtask"), query(page).get("needs")]).toEqual(["maintenance", taskId, "1"]);
  await expect(side(page).getByRole("heading", { name: `Look in the basket ${tag}` })).toBeVisible();
  await expectHealthy(page, problems, { label: "lsa and rcm task links", root: ".tx" });
});

test("a product's design: What it needs on its tasks, no packaging or forecasts; its links stay on the product's page", async ({ page, request, problems }) => {
  const tag = `d${Date.now()}`;
  const post = (path, data) => postOk(request, path, data);
  const product = await post(`${M}/products`, { name: `LSA drone ${tag}`, part_number: `LD-${tag}` });
  const motor = await post(`${M}/positions`, { name: `Motor ${tag}`, parent_id: product.id });
  const fn = await post(`${M}/positions/${motor.id}/functions`, { text: `Turn the propeller ${tag}` });
  const ff = await post(`${M}/functions/${fn.id}/failures`, { text: `No thrust ${tag}` });
  const fm = await post(`${M}/positions/${motor.id}/failure-modes`, { text: `Bearing wears ${tag}`, functional_failure_id: ff.id });
  const res = await request.put(`${M}/failure-modes/${fm.id}/decision`, {
    data: { consequence: "operational", decision: { outcome: "on_condition", task: `Spin the motor by hand ${tag}`, interval: 1, interval_unit: "months" } },
  });
  expect(res.ok()).toBeTruthy();
  const taskId = (await res.json()).decision.task_id;
  await page.setViewportSize({ width: 1280, height: 800 });
  await open(page, `/products/${product.id}?view=lsa&sel=${motor.id}`); // the old address
  await expect(page).toHaveURL(new RegExp(`/products/${product.id}\\?.*view=maintenance`));
  const task = nameRow(page, `Spin the motor by hand ${tag}`);
  await expect(task).toBeVisible();
  // No Forecast row under a design's task (no due dates there), and no Package… in its menu.
  await expect(page.locator('[id^="tp-MF:"]')).toHaveCount(0);
  await task.locator(".tp-nm").click({ button: "right" });
  const menu = page.getByRole("menu");
  await expect(menu.getByRole("menuitem", { name: "Package…" })).toHaveCount(0);
  await expect(menu.getByRole("menuitem", { name: /^Open in/ })).toHaveCount(0);
  await menu.getByRole("menuitem", { name: "Open", exact: true }).click();
  await expect.poll(() => query(page).get("mtask")).toBe(taskId);
  await side(page).getByRole("button", { name: /^Labour/ }).click();
  const labour = side(page).getByRole("region", { name: "Labour" });
  await labour.getByRole("button", { name: "+ Add labour" }).click();
  await labour.getByRole("textbox", { name: "Trade, line 1" }).fill("Drone technician");
  await labour.getByRole("spinbutton", { name: "Hours each, line 1" }).fill("0.25");
  await shot(page, "lsa-design-task");
  // Serves (in What it needs): the task's row on the design's RCM tab, still on the product's page.
  await side(page).getByRole("region", { name: "What it needs" }).getByRole("button", { name: /^Show what/ }).click();
  await side(page).locator(".lsa-modes").getByRole("link", { name: `Bearing wears ${tag}` }).click();
  await expect(page).toHaveURL(new RegExp(`/products/${product.id}\\?.*view=rcm`));
  await expectHealthy(page, problems, { label: "design lsa", root: ".tx" });
});

test("What it needs at 400 px: the task's LSA fits, nothing scrolls sideways", async ({ page, request }) => {
  const tag = `m${Date.now()}`;
  const p = await plant(request, tag);
  const tasks = await (await request.get(`${M}/task-table?position_id=${p.pump.id}`)).json();
  const skim = tasks.tasks.find((t) => t.name === `Skim ${tag}`);
  await page.setViewportSize({ width: 400, height: 860 });
  await open(page, `/asset-register/explorer?arrange=positions&root=${p.pool.id}&sel=${p.pump.id}&tab=maintenance&mtask=${skim.id}&needs=1`);
  await expect(side(page).getByRole("region", { name: "What it needs" })).toBeVisible();
  await side(page).getByRole("button", { name: /^Labour/ }).click();
  await side(page).getByRole("region", { name: "Labour" }).getByRole("button", { name: "+ Add labour" }).click();
  await side(page).getByRole("region", { name: "Tools and instruments" }).getByRole("button", { name: "+ Add a tool" }).click();
  await shot(page, "lsa-task-phone");
  expect(await sideways(page)).toBeLessThanOrEqual(0);
});
