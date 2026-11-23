// The Explorer's Maintenance tab (Operate › Assets › Explorer, ?tab=maintenance): a tree-table, like
// the Modelling and Missions tabs. Under each position hang its own maintenance tasks (from its RCM or
// added directly) with when it's next due (only when known), how often, what each costs, its package,
// where it came from and its kind; each level's roll-up counts the tasks at and below it. No
// forecasts in the tree: a position's Open in › opens the left menu's forecast tool filled in from
// it (Derryn, 23 Nov 2026); a task opens beside the table.
// The RCM reads each task's cost. At 400 px nothing scrolls the page sideways. Each test makes its
// own small plant through the API.
//
// With SMOKE_SHOTS_DIR set, it saves screenshots (for the pull request).
import { test, expect, open, expectHealthy, postOk } from "./health.js";

const M = "/api/maintenance";
const SHOTS = process.env.SMOKE_SHOTS_DIR || "";
const shot = async (page, name) => {
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}.png` });
};

async function plant(request, tag) {
  const post = (path, data) => postOk(request, path, data);
  const pump = await post(`${M}/positions`, { name: `Maint pump ${tag}` });
  const motor = await post(`${M}/positions`, { name: `Maint motor ${tag}`, parent_id: pump.id });
  const fn = await post(`${M}/positions/${pump.id}/functions`, { text: `Pump water ${tag}`, standard: "50 L/s" });
  const ff = await post(`${M}/functions/${fn.id}/failures`, { text: `No flow ${tag}` });
  const mode = await post(`${M}/positions/${pump.id}/failure-modes`, { text: `Seal leaks ${tag}`, functional_failure_id: ff.id });
  const res = await request.put(`${M}/failure-modes/${mode.id}/decision`, {
    data: { consequence: "operational", hidden: false, decision: { outcome: "on_condition", task: `Check the seal ${tag}`, interval: 1, interval_unit: "months" } },
  });
  expect(res.ok()).toBeTruthy();
  const check = (await res.json()).decision.task_id;
  // Its LSA: half an hour of a fitter, at the fitter's rate.
  expect((await request.patch(`${M}/tasks/${check}`, { data: { resources: { labour: [{ trade: `Fitter ${tag}`, people: 1, hours: 0.5 }] } } })).ok()).toBeTruthy();
  expect((await request.put(`${M}/trade-rates`, { data: { trade: `Fitter ${tag}`, rate: 90 } })).ok()).toBeTruthy();
  await post(`${M}/positions/${pump.id}/tasks`, { name: `Inspect the guard ${tag}`, interval: 12, unit: "months", source: "statutory", reference: "AS 4024" });
  await post(`${M}/positions/${motor.id}/tasks`, { name: `Grease the bearings ${tag}`, interval: 3, unit: "months", source: "oem" });
  return { pump, motor, mode, check };
}

const query = (page) => new URL(page.url()).searchParams;
const nameRow = (page, text) => page.locator(".tp-row", { has: page.locator(".tp-nm", { hasText: text }) });
const side = (page) => page.locator(".tt-side");
const sideways = (page) => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);

test("Maintenance: the tasks in the tree with a roll-up at each level; open one, add one, Open in › a forecast", async ({ page, request, problems }) => {
  const tag = `m${Date.now()}`;
  const p = await plant(request, tag);
  // Another asset: none of it may show while the pump is open.
  const other = await postOk(request, `${M}/positions`, { name: `Other asset ${tag}` });
  await postOk(request, `${M}/positions/${other.id}/tasks`, { name: `Not ours ${tag}`, interval: 1, unit: "weeks" });
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, `/asset-register/explorer?arrange=positions&root=${p.pump.id}&sel=${p.pump.id}&tab=maintenance`);
  // Each task under its own position; the motor's under the motor.
  await expect(nameRow(page, `Check the seal ${tag}`)).toBeVisible();
  await expect(nameRow(page, `Inspect the guard ${tag}`)).toBeVisible();
  await expect(nameRow(page, `Not ours ${tag}`)).toHaveCount(0);
  const motor = nameRow(page, `Maint motor ${tag}`);
  await expect(motor).toContainText("1 task here");
  if (!(await nameRow(page, `Grease the bearings ${tag}`).isVisible())) await motor.locator(".tp-chev").click();
  await expect(nameRow(page, `Grease the bearings ${tag}`)).toBeVisible();
  // The level's roll-up: its own and everything below it.
  await expect(page.locator(".mt-rollup")).toHaveText("2 here · 3 tasks at and below");
  // With work management off (SMOKE_WORK_MANAGEMENT=off) the column still reads Next due here.
  await expect(page.getByRole("columnheader")).toHaveText([/Position, and its tasks/, "Next due", "Interval", "Cost each time", "Trade", "Packaged", "From", "Kind"]);
  // No record of when it was last done: Next due is a dash saying why, never a date from today.
  const due = nameRow(page, `Inspect the guard ${tag}`).locator(".mt-c-due span");
  await expect(due).toHaveText("—");
  await expect(due).toHaveAttribute("title", "No record of when this was last done");
  await expect(nameRow(page, `Check the seal ${tag}`)).toContainText("$45");
  await expect(nameRow(page, `Inspect the guard ${tag}`)).toContainText("Added directly: law, regulation or standard (AS 4024)");
  await expect(nameRow(page, `Inspect the guard ${tag}`)).toContainText("Not set");
  await shot(page, "maintenance-tree-desktop");

  // A task opened: its form beside the table; the cost typed shows in the row.
  await nameRow(page, `Inspect the guard ${tag}`).locator(".tp-nm").click();
  const edit = side(page).getByRole("form", { name: `Task: Inspect the guard ${tag}` });
  await expect(edit).toContainText("Not set yet");
  await edit.getByRole("spinbutton", { name: /Cost each time/ }).fill("60");
  await edit.getByRole("button", { name: "Save" }).click();
  await expect(nameRow(page, `Inspect the guard ${tag}`)).toContainText("$60");
  await shot(page, "maintenance-task-desktop");

  // Add task… on the motor (its row menu): a form beside the table, never a dialog.
  await motor.locator(".tp-nm").click({ button: "right" });
  const menu = page.getByRole("menu", { name: new RegExp(`^Actions for Maint motor ${tag}`) });
  // The general section first (Open … Copy link), then the tab's add leads the middle.
  await expect(menu.getByRole("menuitem").first()).toHaveText("Open");
  await expect(menu.getByRole("menuitem").nth(6)).toHaveText("Add task…");
  await expect(menu.getByRole("menuitem", { name: /^Open in/ })).toBeVisible();
  await expect(menu.getByRole("menuitem", { name: "Forecast…" })).toHaveCount(0);
  await expect(menu.getByRole("menuitem", { name: /Spares for the year/ })).toHaveCount(0);
  await menu.getByRole("menuitem", { name: "Add task…" }).click();
  await expect.poll(() => query(page).get("addtask")).toBe(p.motor.id);
  const form = side(page).getByRole("form", { name: "Add a task" });
  await expect(form).toContainText(`Add a task to Maint motor ${tag}`);
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await form.getByRole("textbox", { name: /Task: the action only/ }).fill(`Check the coupling ${tag}`);
  await form.getByRole("group", { name: "How often" }).getByRole("spinbutton", { name: "How many" }).fill("6");
  await form.getByRole("button", { name: "Add task" }).click();
  await expect(nameRow(page, `Check the coupling ${tag}`)).toBeVisible();
  await expect(motor).toContainText("2 tasks here");

  // Open in › Spares forecast on the motor: the left menu's tool, filled in from it, saying where from.
  await motor.locator(".tp-nm").click({ button: "right" });
  const again = page.getByRole("menu", { name: new RegExp(`^Actions for Maint motor ${tag}`) });
  await again.getByRole("menuitem", { name: /^Open in/ }).click();
  await expect(page.getByRole("menuitem", { name: "Hours forecast" })).toBeVisible();
  await shot(page, "maintenance-open-in-desktop");
  await page.getByRole("menuitem", { name: "Spares forecast" }).click();
  await expect(page).toHaveURL(new RegExp(`/forecasts/spares\\?from=position%3A${p.motor.id}`));
  await expect(page.locator(".ft-from")).toContainText(`Maint motor ${tag}`);
  await expect(page.locator(".ft-from a")).toHaveAttribute("href", new RegExp(`sel=${p.motor.id}`));
  await expectHealthy(page, problems, { label: "maintenance tab" });

  // The RCM reads the cost: the P-F calculator starts from the task's $45.
  const inputs = await (await request.get(`${M}/failure-modes/${p.mode.id}/interval-inputs?task_id=${p.check}`)).json();
  expect(inputs.task_cost.amount).toBe(45);
});

test("Maintenance at 400 px: the tree of tasks, a task opened, an old forecast address; nothing scrolls sideways", async ({ page, request, problems }) => {
  const tag = `n${Date.now()}`;
  const p = await plant(request, tag);
  await page.setViewportSize({ width: 400, height: 860 });
  await open(page, `/asset-register/explorer?arrange=positions&root=${p.pump.id}&sel=${p.pump.id}&tab=maintenance`);
  await expect(nameRow(page, `Check the seal ${tag}`)).toBeVisible();
  await expect(nameRow(page, `Check the seal ${tag}`)).toContainText("$45");
  expect(await sideways(page)).toBeLessThanOrEqual(0);
  await shot(page, "maintenance-tree-phone");
  await nameRow(page, `Check the seal ${tag}`).locator(".tp-nm").click();
  await expect(side(page).getByRole("form", { name: `Task: Check the seal ${tag}` })).toContainText("$45 each time");
  // When the item is replaced: restart or keep, the default said with why (a task on its own restarts).
  await expect(side(page).getByRole("combobox", { name: "When the item is replaced" })).toContainText("Restart the schedule");
  expect(await sideways(page)).toBeLessThanOrEqual(0);
  await shot(page, "maintenance-task-phone");
  // Open in from a task's ⋯ on a phone: Select keeps its place, so the tools are under More › (in place).
  await open(page, `/asset-register/explorer?arrange=positions&root=${p.pump.id}&sel=${p.pump.id}&tab=maintenance`);
  await nameRow(page, `Check the seal ${tag}`).getByRole("button", { name: /^Actions for/ }).click();
  await page.getByRole("menu").first().getByRole("menuitem", { name: /^More/ }).click();
  await expect(page.getByRole("menuitem", { name: "Cost forecast" })).toBeVisible();
  expect(await sideways(page)).toBeLessThanOrEqual(0);
  await shot(page, "maintenance-open-in-phone");
  await page.keyboard.press("Escape");
  // An old Forecast… address opens the spares forecast, filled in from the pump.
  await open(page, `/asset-register/explorer?arrange=positions&root=${p.pump.id}&sel=${p.pump.id}&tab=maintenance&forecast=${p.pump.id}`);
  await expect(page).toHaveURL(/\/forecasts\/spares\?from=position/);
  await expect(page.locator(".ft-from")).toContainText(`Maint pump ${tag}`);
  expect(await sideways(page)).toBeLessThanOrEqual(0);
  await expectHealthy(page, problems, { label: "maintenance phone" });
});
