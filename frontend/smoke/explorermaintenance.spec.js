// The Explorer's Maintenance tab (Operate › Assets › Explorer, ?tab=maintenance): every
// maintenance task on the picked position, from its RCM or added directly, with where it came
// from, how often, its package, next due and what it costs each time ("Include what's inside"
// adds the tasks below). Add task (the bar's button, the row menu's first item) opens a form in
// the panel beside the tree, never a dialog; a task opens there too, its cost typed or from its
// LSA at trade rates. The RCM reads each task's cost: a failure mode's task shows it in its
// details, and the P-F calculator starts from it. At 400 px the table scrolls inside its card and
// nothing scrolls the page sideways. Each test makes its own small plant through the API.
//
// With SMOKE_SHOTS_DIR set, it saves screenshots (for the pull request).
import { test, expect, open, expectHealthy, postOk } from "./health.js";
import { headMenu } from "./explorer.js";

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
const panel = (page) => page.locator(".pk-panel");
const rows = (page) => panel(page).locator(".pk-trow");
const row = (page, name) => rows(page).filter({ hasText: name });
const sideways = (page) => page.evaluate(() => document.documentElement.scrollWidth - innerWidth);

test("Maintenance: every task here with where it came from and its cost; add one, cost one, the RCM reads it", async ({ page, request, problems }) => {
  const tag = `m${Date.now()}`;
  const p = await plant(request, tag);
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pump.id}`);
  await page.getByRole("tab", { name: "Maintenance" }).click();
  await expect.poll(() => query(page).get("tab")).toBe("maintenance");
  // The position's own tasks: from the RCM (its failure mode) and added directly (and why).
  await expect(rows(page)).toHaveCount(2);
  await expect(panel(page).getByRole("columnheader")).toHaveText(["Task", "From", "Interval", "Cost each time", "Next due", "Package", "Kind"]);
  await expect(row(page, `Check the seal ${tag}`)).toContainText(`RCM: Seal leaks ${tag}`);
  await expect(row(page, `Check the seal ${tag}`)).toContainText("$45");
  await expect(row(page, `Inspect the guard ${tag}`)).toContainText("Added directly: law, regulation or standard (AS 4024)");
  await expect(row(page, `Inspect the guard ${tag}`)).toContainText("Not set");
  // What's inside too: the motor's task, with the Position column.
  await panel(page).getByRole("checkbox", { name: "Include what's inside" }).check();
  await expect(rows(page)).toHaveCount(3);
  await expect(panel(page).getByRole("columnheader").first()).toHaveText("Position");
  await expect.poll(() => query(page).get("below")).toBe("1");
  await shot(page, "maintenance-tab-desktop");
  await panel(page).getByRole("checkbox", { name: "Include what's inside" }).uncheck();
  await expect(rows(page)).toHaveCount(2);

  // The heading's "…": Add task…, Columns…, Trade rates…, Export CSV.
  await expect((await headMenu(page)).locator(".ovm-menu .ovm-item")).toHaveText(["Add task…", "Columns…", "Trade rates…", "Export CSV", "Open the full page"]);
  await page.keyboard.press("Escape");

  // Add task: a form in the panel beside the tree, never a dialog.
  await panel(page).getByRole("button", { name: "Add task" }).click();
  await expect.poll(() => query(page).get("addtask")).toBe(p.pump.id);
  const form = panel(page).getByRole("form", { name: "Add a task" });
  await expect(form).toBeVisible();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await form.getByRole("textbox", { name: /Task: the action only/ }).fill(`Replace the impeller ${tag}`);
  await form.getByRole("group", { name: "How often" }).getByRole("spinbutton", { name: "How many" }).fill("24");
  await form.getByRole("combobox", { name: "Why it's done (optional)" }).selectOption("oem");
  await form.getByRole("textbox", { name: "Reference (optional)" }).fill("Pump manual 7.2");
  await form.getByRole("checkbox", { name: `Seal leaks ${tag}` }).check();
  await form.getByRole("spinbutton", { name: /Cost each time/ }).fill("1250");
  await shot(page, "maintenance-add-task-desktop");
  await form.getByRole("button", { name: "Add task" }).click();
  await expect(rows(page)).toHaveCount(3);
  await expect(row(page, `Replace the impeller ${tag}`)).toContainText(`Added directly: maker's recommendation (Pump manual 7.2) · prevents Seal leaks ${tag}`);
  await expect(row(page, `Replace the impeller ${tag}`)).toContainText("$1,250");
  await expect(panel(page)).toContainText(`Added Replace the impeller ${tag}.`);

  // Open the statutory task and type its cost: the table says so.
  await row(page, `Inspect the guard ${tag}`).getByRole("button", { name: `Inspect the guard ${tag}` }).click();
  const edit = panel(page).getByRole("form", { name: `Task: Inspect the guard ${tag}` });
  await expect(edit).toContainText("Not set yet");
  await edit.getByRole("spinbutton", { name: /Cost each time/ }).fill("60");
  await edit.getByRole("button", { name: "Save" }).click();
  await expect(row(page, `Inspect the guard ${tag}`)).toContainText("$60");
  await shot(page, "maintenance-tab-costs-desktop");
  // The RCM task's pane: its cost from its LSA, and the RCM tab named for its reason and modes.
  await row(page, `Check the seal ${tag}`).getByRole("button", { name: `Check the seal ${tag}` }).click();
  const rcmTask = panel(page).getByRole("form", { name: `Task: Check the seal ${tag}` });
  await expect(rcmTask).toContainText("$45 each time. From its LSA: labour $45.");
  await expect(rcmTask.getByRole("link", { name: "RCM tab" })).toBeVisible();
  await rcmTask.getByRole("button", { name: "Cancel" }).click();
  // The foot adds them up.
  await expect(panel(page).getByRole("region", { name: "What the tasks cost" })).toContainText("$1,355 each time for them all.");
  await expectHealthy(page, problems, { label: "maintenance tab" });

  // The row menu's first item on this tab: Add task….
  await page.getByRole("treeitem", { name: new RegExp(`^Maint motor ${tag}`) }).locator(".tp-nm").click({ button: "right" });
  const menu = page.getByRole("menu", { name: new RegExp(`^Actions for Maint motor ${tag}`) });
  await expect(menu.getByRole("menuitem").first()).toHaveText("Add task…");
  await menu.getByRole("menuitem", { name: "Add task…" }).click();
  await expect.poll(() => query(page).get("addtask")).toBe(p.motor.id);
  await expect(panel(page).getByRole("form", { name: "Add a task" })).toContainText(`Add a task to Maint motor ${tag}`);

  // The RCM reads the cost: the P-F calculator starts from the task's $45.
  const inputs = await (await request.get(`${M}/failure-modes/${p.mode.id}/interval-inputs?task_id=${p.check}`)).json();
  expect(inputs.task_cost.amount).toBe(45);
  // The pump picked, then the RCM tab: it opens the pump down to its failure modes.
  await page.getByRole("treeitem", { name: new RegExp(`^Maint pump ${tag}`) }).locator(".tp-nm").click();
  await page.getByRole("tab", { name: "RCM" }).click();
  const modeRow = page.getByRole("treegrid", { name: /and their RCM/ }).getByRole("row", { name: new RegExp(`^Failure mode: Seal leaks ${tag}`) });
  await modeRow.locator(".tp-nm").dblclick();
  const details = page.getByRole("complementary", { name: "Details" });
  const costs = details.getByRole("group", { name: "What the tasks cost" });
  await expect(costs).toContainText(`Check the seal ${tag}: $45 each time (from its LSA).`);
  await expect(costs).toContainText(`Replace the impeller ${tag}: $1,250 each time (typed on the task).`);
  await costs.scrollIntoViewIfNeeded();
  await shot(page, "maintenance-rcm-costs-desktop");
  await expectHealthy(page, problems, { label: "rcm reads the task costs" });
});

test("Maintenance at 400 px: the table scrolls in its card, Add task fits, nothing scrolls sideways", async ({ page, request, problems }) => {
  const tag = `n${Date.now()}`;
  const p = await plant(request, tag);
  await page.setViewportSize({ width: 400, height: 860 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pump.id}&tab=maintenance`);
  // On a phone the panel is its own screen: tap the row to open it.
  await page.getByRole("treeitem", { name: new RegExp(`^Maint pump ${tag}`) }).locator(".tp-nm").click();
  await expect(rows(page)).toHaveCount(2);
  expect(await sideways(page)).toBeLessThanOrEqual(0);
  await shot(page, "maintenance-tab-phone");
  await panel(page).getByRole("button", { name: "Add task" }).click();
  const form = panel(page).getByRole("form", { name: "Add a task" });
  await expect(form).toBeVisible();
  expect(await sideways(page)).toBeLessThanOrEqual(0);
  await shot(page, "maintenance-add-task-phone");
  await form.getByRole("button", { name: "Cancel" }).click();
  await row(page, `Check the seal ${tag}`).getByRole("button", { name: `Check the seal ${tag}` }).click();
  await expect(panel(page).getByRole("form", { name: `Task: Check the seal ${tag}` })).toContainText("$45 each time");
  expect(await sideways(page)).toBeLessThanOrEqual(0);
  await shot(page, "maintenance-task-phone");
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pump.id}&tab=rcm`);
  const modeRow = page.getByRole("treegrid", { name: /and their RCM/ }).getByRole("row", { name: new RegExp(`^Failure mode: Seal leaks ${tag}`) });
  await modeRow.locator(".tp-nm").dblclick();
  const costs = page.getByRole("complementary", { name: "Details" }).getByRole("group", { name: "What the tasks cost" });
  await expect(costs).toContainText(`Check the seal ${tag}: $45 each time`);
  await costs.scrollIntoViewIfNeeded();
  expect(await sideways(page)).toBeLessThanOrEqual(0);
  await shot(page, "maintenance-rcm-costs-phone");
  await expectHealthy(page, problems, { label: "maintenance phone" });
});
