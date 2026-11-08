// Several tasks for one failure mode, and one task for several, on the
// Explorer's RCM tab (Assets › Explorer › RCM). Each task is a row of the tree,
// under every failure mode it serves (the fifth level); its own details change it:
// its name, how often (Change, Calculate…), what's done when found, instructions,
// its evidence, the failure modes it serves and its logistics, and Remove or Retire
// at its foot. A failure mode's step 3 ("Proactive task or default action") lists its
// tasks as plain links to their rows, with a dashed "Add a task" row that asks its kind,
// then a new task or an existing one ("New task · Existing task"), in place; the new
// task's row is picked once saved. The row menu's Add a task… opens that row (the
// decision dialog when there's no decision yet); a tap on "Which task is worth doing?"
// adopts a task linked before the decision; the mode's Task cell says "+1 task"
// without the row changing height; the decision dialog (the row menu's Change the
// decision…) shows a shared task's interval read-only; at 400 px it all fits. Each
// test makes its own small plant through the API.
//
// With SMOKE_SHOTS_DIR set, it also saves screenshots of the details with
// several tasks and of the table rows, at 1280 and 400 px (for the pull request).
import { test, expect, open, expectHealthy, postOk } from "./health.js";

const M = "/api/maintenance";
const SHOTS = process.env.SMOKE_SHOTS_DIR || "";

async function plant(request, tag) {
  const post = (path, data) => postOk(request, path, data);
  const pool = await post(`${M}/positions`, { name: `Tasks pool ${tag}` });
  const cell = await post(`${M}/positions`, { name: `Tasks cell ${tag}`, parent_id: pool.id });
  const fn = await post(`${M}/positions/${pool.id}/functions`, { text: `Keep the water balanced ${tag}`, standard: "pH 7.2-7.8" });
  const ff = await post(`${M}/functions/${fn.id}/failures`, { text: `pH above 7.8 ${tag}` });
  const acid = await post(`${M}/positions/${pool.id}/failure-modes`, { text: `Acid under-dosed ${tag}`, functional_failure_id: ff.id });
  const cya = await post(`${M}/positions/${pool.id}/failure-modes`, { text: `Stabiliser low ${tag}`, functional_failure_id: ff.id });
  const salt = await post(`${M}/positions/${cell.id}/failure-modes`, { text: `Salinity low ${tag}` });
  const res = await request.put(`${M}/failure-modes/${acid.id}/decision`, {
    // Hidden and safety: the RCM decision diagram allows every kind of second task there.
    data: { hidden: true, consequence: "safety", decision: { outcome: "on_condition", task: `Weekly pH check ${tag}`, interval: 1, interval_unit: "weeks" } },
  });
  expect(res.ok()).toBeTruthy();
  const own = (await res.json()).decision.task_id;
  await post(`${M}/positions/${pool.id}/tasks`, { name: `Backwash the filter ${tag}`, interval: 1, unit: "months" });
  return { pool, cell, fn, ff, acid, cya, salt, own };
}

const table = (page) => page.getByRole("treegrid", { name: /and their RCM/ });
const trow = (page, name) => table(page).getByRole("row", { name: new RegExp(name) });
const dialog = (page, name) => page.getByRole("dialog", { name, exact: true });
const panel = (page) => page.getByRole("complementary", { name: "Details" });
const tasksOf = (page) => panel(page).getByRole("region", { name: "Proactive task or default action" });
const chipsOf = (page) => panel(page).locator(".rw-chips-row");
const overflow = (page) => page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
// Step 3's dashed add row, and the form it opens in place.
const addRow = (tasks) => tasks.getByRole("button", { name: "Add a task", exact: true });
const addForm = (tasks) => tasks.getByRole("group", { name: "Add a task" });
// Step 3's list of the decision's tasks: one line each, the name a link to the task's row.
const listOf = (tasks) => tasks.getByRole("list", { name: "The decision's tasks" });
const lines = (tasks) => listOf(tasks).getByRole("listitem");
const goTask = (tasks, name) => listOf(tasks).getByRole("button", { name, exact: true });
// The task's own details (its row picked): the kind, the title, its sections.
const kindOf = (page) => panel(page).locator(".rw-panel-kind");
const titleOf = (page) => panel(page).locator(".rw-panel-title");
const section = (page, name) => panel(page).getByRole("region", { name, exact: true });
const settled = async (page) => {
  await page.waitForLoadState("networkidle", { timeout: 5_000 }).catch(() => {});
  await page.waitForTimeout(250);
};
// Back to the failure mode from a task's details: its name in Serves.
const toMode = async (page, name) => {
  await section(page, "Serves").getByRole("button", { name, exact: true }).click();
  await expect(kindOf(page)).toHaveText("Failure mode");
};

test("a failure mode's tasks are rows of the tree; add one, use an existing one, change it in its details, remove it; the cell says +1 task", async ({ page, request, problems }) => {
  const tag = `t${Date.now()}`;
  const p = await plant(request, tag);
  await page.setViewportSize({ width: 1280, height: 800 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pool.id}&tab=rcm`);
  const acidRow = trow(page, `^Failure mode: Acid under-dosed ${tag}`);
  await expect(acidRow).toBeVisible();
  await acidRow.locator(".tp-nm").click();
  await settled(page);
  const heightBefore = (await acidRow.boundingBox()).height;
  // The failure mode opens to its task: the fifth level of the tree.
  await expect(acidRow).toHaveAttribute("aria-expanded", "false");
  await acidRow.locator(".tp-chev").click();
  const checkRow = trow(page, `^Task: Weekly pH check ${tag}`);
  await expect(checkRow).toBeVisible();
  await expect(checkRow.getByRole("gridcell").filter({ hasText: /^On condition$/ })).toHaveCount(1); // Decision: its kind
  await expect(checkRow).toContainText("every 1 week"); // Task: how often
  expect((await checkRow.boundingBox()).height).toBe(heightBefore);

  // The mode's details (a double-click on its name): step 3 lists its task as a link; no cards.
  await acidRow.locator(".tp-nm").dblclick();
  await expect(panel(page)).toBeVisible();
  let tasks = tasksOf(page);
  await expect(chipsOf(page)).toContainText("On condition");
  // Step 3 is a yes or no; the task carries its own kind, a small chip with the worth-doing test as its tooltip.
  await expect(lines(tasks)).toHaveCount(1);
  await expect(lines(tasks).first()).toContainText(`Weekly pH check ${tag}`);
  await expect(lines(tasks).first()).toContainText("every 1 week");
  const kindChip = tasks.getByRole("combobox", { name: `Kind of “Weekly pH check ${tag}”` });
  await expect(kindChip).toHaveValue("on_condition");
  await expect(kindChip).toHaveAttribute("title", /^First choice: /);
  await expect(tasks.locator(".rim-cards")).toHaveCount(0);
  await expect(tasks.getByRole("radiogroup", { name: "Which task is worth doing?" }).getByRole("radio", { name: /Task\(s\) worth doing/ }))
    .toHaveAttribute("aria-checked", "true");

  // The link picks the task's row: its own details, the way up ending at the failure mode.
  await goTask(tasks, `Weekly pH check ${tag}`).click();
  await expect(kindOf(page)).toHaveText("Task");
  await expect(titleOf(page)).toHaveText(`Weekly pH check ${tag}`);
  await expect(checkRow).toHaveAttribute("aria-selected", "true");
  await expect(panel(page).getByRole("navigation", { name: "Inside" })).toContainText(`Acid under-dosed ${tag}`);
  await expect(chipsOf(page)).toContainText("On condition");
  await expect(chipsOf(page)).toContainText("every 1 week");
  await expect(panel(page).locator(".psec-title")).toHaveText(["Kind and interval", "Then, if found", "Instructions", "Evidence for this task", "Serves", "Logistics"]);
  // Its kind is a small chip here too, changed on the task.
  await expect(section(page, "Kind and interval").getByRole("combobox", { name: `Kind of “Weekly pH check ${tag}”` })).toHaveValue("on_condition");
  // What's done when the check finds it: kept on Enter, and quietly after the row's name.
  const found = section(page, "Then, if found").getByRole("textbox", { name: "Then, if found:" });
  await expect(found).toHaveAttribute("placeholder", "Say what's done when the check finds it");
  await found.fill(`Dose acid by hand ${tag}`);
  await found.press("Enter");
  await expect(section(page, "Then, if found").getByRole("status")).toHaveText("✓ Saved");
  await expect(checkRow.locator(".tp-found")).toHaveText(`Then, if found: Dose acid by hand ${tag}`);
  await expect(section(page, "Serves").getByRole("listitem")).toHaveCount(1);
  await expect(section(page, "Logistics")).toContainText("No labour, tools or method set yet.");
  await expect(section(page, "Logistics").getByRole("link", { name: "Open in LSA" })).toHaveAttribute("href", new RegExp(`tab=lsa&task=${p.own}`));

  // Add a task (from the mode's step 3): in place, its kind first (every kind, on condition again too:
  // one kind may come more than once; it starts on one the decision doesn't have), then its name and how
  // often. No interval yet: it says so, and nothing is sent. Saved, its row is picked.
  await toMode(page, `Acid under-dosed ${tag}`);
  tasks = tasksOf(page);
  await addRow(tasks).click();
  let add = addForm(tasks);
  await expect(add).toBeVisible();
  const kinds = add.getByRole("radiogroup", { name: "Kind of task" });
  await expect(kinds.getByRole("radio")).toHaveText([/On condition/, /Fixed interval/, /Failure finding/, /Redesign/]);
  await expect(kinds.getByRole("radio", { name: /Fixed interval/ })).toHaveAttribute("aria-checked", "true");
  await expect(add.getByText(/What does this catch that/)).toHaveCount(0);
  let writes = 0;
  page.on("request", (r) => { if (r.method() === "PUT" && r.url().includes(`/failure-modes/${p.acid.id}/decision`)) writes += 1; });
  const name = add.getByRole("textbox", { name: "Task" });
  await name.fill(`Replace the acid pump ${tag}`);
  await name.press("Enter");
  await expect(add.getByText("Enter how often: an interval above 0.")).toBeVisible();
  expect(writes).toBe(0);
  await add.getByRole("spinbutton", { name: "Interval" }).fill("24");
  await add.getByRole("combobox", { name: "Interval unit" }).selectOption("months");
  await add.getByRole("spinbutton", { name: "Interval" }).press("Enter");
  expect(writes).toBe(1);
  await expect(dialog(page, "Add a task")).toHaveCount(0); // never a dialog
  await expect(kindOf(page)).toHaveText("Task");
  await expect(titleOf(page)).toHaveText(`Replace the acid pump ${tag}`);
  await expect(chipsOf(page)).toContainText("Fixed interval");
  await expect(chipsOf(page)).toContainText("every 24 months");
  const pumpRow = trow(page, `^Task: Replace the acid pump ${tag}`);
  await expect(pumpRow).toHaveAttribute("aria-selected", "true");
  // A fixed-interval task has no "Then, if found".
  await expect(section(page, "Then, if found")).toHaveCount(0);
  // Its instructions, kept when you leave the field.
  const inst = section(page, "Instructions").getByRole("textbox", { name: "Instructions" });
  await inst.fill("Swap the pump head.");
  await inst.blur();
  await expect(section(page, "Instructions").getByRole("status")).toHaveText("✓ Saved");
  // Change how often, in place.
  await section(page, "Kind and interval").getByRole("button", { name: `Change how often “Replace the acid pump ${tag}” is done` }).click();
  await section(page, "Kind and interval").getByRole("spinbutton", { name: "Interval" }).fill("36");
  await section(page, "Kind and interval").getByRole("button", { name: "Save", exact: true }).click();
  await expect(section(page, "Kind and interval")).toContainText("every 36 months");
  // Its name, a click on the title: kept on Enter (the row follows).
  await titleOf(page).getByRole("button").click();
  const box = panel(page).getByRole("textbox", { name: "Task" });
  await box.fill(`Replace the dosing pump ${tag}`);
  await box.press("Enter");
  await expect(titleOf(page)).toHaveText(`Replace the dosing pump ${tag}`);
  await expect(trow(page, `^Task: Replace the dosing pump ${tag}`)).toBeVisible();

  // Use an existing task on the position: every kind still offered, starting on the one the decision
  // doesn't have yet (failure finding), then the picker. Linked, its row is picked.
  await toMode(page, `Acid under-dosed ${tag}`);
  tasks = tasksOf(page);
  await expect(chipsOf(page)).toContainText("On condition + Fixed interval");
  await expect(lines(tasks)).toHaveCount(2);
  await expect(lines(tasks).nth(0)).toContainText(`Weekly pH check ${tag}`);
  await expect(lines(tasks).nth(0)).toContainText("every 1 week");
  await expect(lines(tasks).nth(1)).toContainText(`Replace the dosing pump ${tag}`);
  await expect(lines(tasks).nth(1)).toContainText("every 36 months");
  await expect(tasks.getByRole("combobox", { name: `Kind of “Weekly pH check ${tag}”` })).toHaveValue("on_condition");
  await expect(tasks.getByRole("combobox", { name: `Kind of “Replace the dosing pump ${tag}”` })).toHaveValue("fixed_interval");
  // One line per task, the columns aligned: kind, name, how often (no "Then, if found" here).
  const tops = await lines(tasks).evaluateAll((els) => els.map((li) => [...li.children].map((c) => Math.round(c.getBoundingClientRect().left))));
  expect(tops[0].slice(0, 3)).toEqual(tops[1].slice(0, 3));
  for (const li of await lines(tasks).all()) expect((await li.boundingBox()).height).toBeLessThan(40);
  await expect(lines(tasks).first()).not.toContainText("Then, if found");
  await addRow(tasks).click();
  add = addForm(tasks);
  await expect(add.getByRole("radiogroup", { name: "Kind of task" }).getByRole("radio"))
    .toHaveText([/On condition/, /Fixed interval/, /Failure finding/, /Redesign/]);
  await expect(add.getByRole("radiogroup", { name: "Kind of task" }).getByRole("radio", { name: /Failure finding/ }))
    .toHaveAttribute("aria-checked", "true");
  await add.getByRole("radiogroup", { name: "New or existing task" }).getByRole("radio", { name: "Existing task" }).click();
  const pick = add.getByRole("combobox", { name: "Existing task" });
  await expect(pick).toBeVisible();
  await expect(pick.locator("option")).toContainText([/Choose a task/, new RegExp(`Backwash the filter ${tag} · every 1 month`)]);
  await pick.selectOption({ label: await pick.locator("option").nth(1).textContent() });
  await add.getByRole("button", { name: "Link task" }).click();
  await expect(titleOf(page)).toHaveText(`Backwash the filter ${tag}`);
  await expect(chipsOf(page)).toContainText("Failure finding");
  await expect(section(page, "Then, if failed").getByRole("textbox", { name: "Then, if failed:" })).toBeVisible();

  // Remove the linked task: it serves only this mode, so it is retired (after asking), and its member
  // comes off the decision with it; the failure mode is picked again, its other two tasks kept.
  await panel(page).getByRole("button", { name: "Retire the task", exact: true }).click();
  const ask = page.getByRole("alertdialog", { name: "Remove this task?" });
  await expect(ask).toContainText("serves only this failure mode, so it is retired");
  await ask.getByRole("button", { name: "Retire the task" }).click();
  await expect(kindOf(page)).toHaveText("Failure mode");
  tasks = tasksOf(page);
  await expect(lines(tasks)).toHaveCount(2);
  await expect(trow(page, `^Task: Backwash the filter ${tag}`)).toHaveCount(0);
  await expect(chipsOf(page)).toContainText("On condition + Fixed interval");

  // A second task of one kind (Derryn, 9 Nov 2026): an annual fixed-interval deep clean beside the pump swap.
  await addRow(tasks).click();
  add = addForm(tasks);
  await add.getByRole("radiogroup", { name: "Kind of task" }).getByRole("radio", { name: /Fixed interval/ }).click();
  await add.getByRole("textbox", { name: "Task" }).fill(`Deep clean ${tag}`);
  await add.getByRole("spinbutton", { name: "Interval" }).fill("12");
  await add.getByRole("combobox", { name: "Interval unit" }).selectOption("months");
  await add.getByRole("spinbutton", { name: "Interval" }).press("Enter");
  await expect(titleOf(page)).toHaveText(`Deep clean ${tag}`);
  // Its row menu: Open… and Retire the task… (it serves only this mode).
  await trow(page, `^Task: Deep clean ${tag}`).locator(".tp-nm").click();
  await page.keyboard.press("Shift+F10");
  await expect(page.getByRole("menu").getByRole("menuitem").filter({ hasText: /Open…|Retire the task…/ })).toHaveCount(2);
  await page.getByRole("menu").getByRole("menuitem", { name: "Retire the task…" }).click();
  await page.getByRole("alertdialog", { name: "Remove this task?" }).getByRole("button", { name: "Retire the task" }).click();
  await expect(trow(page, `^Task: Deep clean ${tag}`)).toHaveCount(0);
  await panel(page).getByRole("button", { name: "Back to table" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  // Beside the table again: each task row's Decision and Task cells (its kind; how often).
  const dosing = trow(page, `^Task: Replace the dosing pump ${tag}`);
  await expect(dosing).toContainText("Fixed interval");
  await expect(dosing).toContainText("every 36 months");

  // The table: the mode's own task and "+1 task", the row no taller; the tooltip lists both.
  await expect(acidRow).toContainText(`Weekly pH check ${tag}`);
  await expect(acidRow).toContainText("+1 task");
  expect((await acidRow.boundingBox()).height).toBe(heightBefore);
  const cell = acidRow.locator(".rw-task");
  expect(await cell.getAttribute("title")).toContain(`Replace the dosing pump ${tag} · every 36 months`);

  // The server agrees.
  const rcm = await (await request.get(`${M}/rcm`)).json();
  const mode = rcm.positions.find((x) => x.id === p.pool.id).functions[0].failures[0].modes.find((x) => x.id === p.acid.id);
  expect(mode.decision.tasks.map((t) => [t.name, t.interval, t.unit, t.instructions])).toEqual([
    [`Weekly pH check ${tag}`, 1, "weeks", ""], [`Replace the dosing pump ${tag}`, 36, "months", "Swap the pump head."]]);
  expect(mode.decision.outcomes[0].on_found).toBe(`Dose acid by hand ${tag}`);
  await expectHealthy(page, problems, { label: "rcm tasks rows" });
});

test("one task for several modes: a row under each, adopted by a tap, read-only in the decision dialog, unlinked (not retired) from Serves", async ({ page, request, problems }) => {
  const tag = `s${Date.now()}`;
  const p = await plant(request, tag);
  // The pool's weekly check also covers the chlorinator cell's salinity (a position inside the pool).
  await postOk(request, `${M}/tasks/${p.own}/failure-modes/${p.salt.id}`, {});
  await page.setViewportSize({ width: 1280, height: 800 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.cell.id}&tab=rcm`);
  const saltRow = trow(page, `^Failure mode: Salinity low ${tag}`);
  await expect(saltRow).toBeVisible();
  // Add a task… in the row menu, with no decision yet: the decision dialog (the task is its decision).
  await saltRow.locator(".tp-nm").click();
  await page.keyboard.press("Shift+F10");
  await page.getByRole("menu").getByRole("menuitem", { name: "Add a task…" }).click();
  const decide = page.getByRole("dialog", { name: /^Decision/ });
  await expect(decide).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(decide).toHaveCount(0);
  // Its details: no decision yet (nothing chosen, the chips waiting for step 2, and why; no Decide…), the
  // task linked before it listed under its own heading, no add row.
  await saltRow.locator(".tp-nm").dblclick();
  const dlg = panel(page);
  await expect(dlg).toBeVisible();
  const tasks = tasksOf(page);
  const which = tasks.getByRole("radiogroup", { name: "Which task is worth doing?" });
  await expect(which.getByRole("radio", { checked: true })).toHaveCount(0);
  await expect(which.getByRole("radio", { name: /Task\(s\) worth doing/ })).toBeDisabled();
  await expect(tasks).toContainText("Answer step 2 first: what's worth doing depends on the consequence.");
  await expect(tasks.getByRole("button", { name: "Decide…" })).toHaveCount(0);
  await expect(tasks.getByRole("heading", { name: "Tasks linked before the decision" })).toBeVisible();
  const before = tasks.getByRole("list", { name: "Tasks linked before the decision" }).getByRole("listitem");
  await expect(before).toHaveCount(1);
  await expect(before.first()).toContainText("Shared with 1"); // a chip at the line's right, not a sentence
  await expect(tasks.getByRole("button", { name: /^Add a task/ })).toHaveCount(0);
  // Step 2 answered (hidden, operational): one tap on "Task(s) worth doing" decides, adopting that task
  // as the kind it is (on condition); its kind chip then makes it failure finding (offered: it's hidden).
  await dlg.getByRole("radiogroup", { name: "Hidden failure?" }).getByRole("radio", { name: "Hidden" }).click();
  await dlg.getByRole("radiogroup", { name: "Consequence category" }).getByRole("radio", { name: "Operational", exact: true }).click();
  await expect(which.getByRole("radio", { name: /Task\(s\) worth doing/ })).toBeEnabled();
  await which.getByRole("radio", { name: /Task\(s\) worth doing/ }).click();
  await expect(which.getByRole("radio", { name: /Task\(s\) worth doing/ })).toHaveAttribute("aria-checked", "true");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(chipsOf(page)).toContainText("On condition");
  const sharedKind = tasks.getByRole("combobox", { name: `Kind of “Weekly pH check ${tag}”` });
  await expect(sharedKind.locator("option")).toHaveText(["On condition", "Fixed interval", "Failure finding"]);
  await sharedKind.selectOption("failure_finding");
  await expect(chipsOf(page)).toContainText("Failure finding");
  await expect(lines(tasks)).toHaveCount(1);
  await expect(lines(tasks).first()).toContainText(`Weekly pH check ${tag}`);
  await expect(tasks.getByRole("combobox", { name: `Kind of “Weekly pH check ${tag}”` })).toHaveValue("failure_finding");
  await expect(tasks.getByRole("heading", { name: "Tasks linked before the decision" })).toHaveCount(0);
  // The row menu's Change the decision… (the panel never opens the dialog): the shared interval read-only, and why.
  await saltRow.locator(".tp-nm").click();
  await page.keyboard.press("Shift+F10");
  await page.getByRole("menu").getByRole("menuitem", { name: "Change the decision…" }).click();
  await expect(decide.getByRole("spinbutton", { name: /^Interval/ })).toHaveAttribute("readonly", "");
  await expect(decide.getByText(/also serves 1 other failure mode, so its name and interval are changed on the task/)).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(decide).toHaveCount(0);
  // Its row under the salinity mode: Serves lists both modes, each a link; the pool's is a level up.
  await saltRow.locator(".tp-nm").dblclick();
  await goTask(tasksOf(page), `Weekly pH check ${tag}`).click();
  await expect(kindOf(page)).toHaveText("Task");
  await expect(chipsOf(page)).toContainText("Shared with 1");
  const serves = section(page, "Serves");
  await expect(serves.getByRole("listitem")).toHaveCount(2);
  await expect(serves).toContainText(`Salinity low ${tag}`);
  await expect(serves).toContainText(`Acid under-dosed ${tag}`);
  // Remove from this failure mode: unlinked, not retired; the pool's mode keeps it.
  await serves.getByRole("button", { name: "Remove from this failure mode" }).click();
  const ask = page.getByRole("alertdialog", { name: "Remove this task?" });
  await expect(ask).toContainText("also serves 1 other failure mode, so it stays with them");
  await ask.getByRole("button", { name: "Remove from this failure mode" }).click();
  // Back on the salinity mode, alone now: the decision's task form in place (name and interval in row 1,
  // what's done when it's found in row 2), New task or Existing task at its top.
  await expect(kindOf(page)).toHaveText("Failure mode");
  await expect(lines(tasksOf(page))).toHaveCount(0);
  const empty = tasksOf(page).getByRole("group", { name: "The decision's task" });
  await expect(empty).not.toContainText("no task does it yet");
  await expect(empty.locator(".rim-r1 .rim-trole")).toHaveText("Check it still works:");
  await expect(empty.locator(".rim-r1").getByRole("textbox", { name: "Task" })).toBeVisible();
  await expect(empty.locator(".rim-r1").getByRole("spinbutton", { name: "Interval" })).toBeVisible();
  await expect(empty.locator(".rim-r2").getByRole("textbox", { name: "Then, if failed:" })).toBeVisible();
  await expect(empty.getByRole("radiogroup", { name: "New or existing task" }).getByRole("radio", { name: "New task" }))
    .toHaveAttribute("aria-checked", "true");
  await empty.getByRole("radio", { name: "Existing task" }).click();
  await expect(empty.locator(".rim-r1").getByRole("combobox", { name: "Existing task" })).toBeVisible();
  const rcm = await (await request.get(`${M}/rcm`)).json();
  const acid = rcm.positions.find((x) => x.id === p.pool.id).functions[0].failures[0].modes.find((x) => x.id === p.acid.id);
  expect(acid.decision.tasks.map((t) => t.id)).toEqual([p.own]);
  await expectHealthy(page, problems, { label: "rcm shared task" });
});

test("at 400 px the decision's tasks, the Add a task form and a task's own sheet fit", async ({ page, request, problems }) => {
  const tag = `p${Date.now()}`;
  const p = await plant(request, tag);
  await postOk(request, `${M}/failure-modes/${p.acid.id}/tasks`, { name: `Replace the acid pump ${tag}`, interval: 24, unit: "months" });
  await page.setViewportSize({ width: 400, height: 860 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pool.id}&tab=rcm`);
  const row = trow(page, `^Failure mode: Acid under-dosed ${tag}`);
  await expect(row).toContainText("+1 task");
  await row.getByRole("button", { name: "Actions", exact: true }).click();
  await page.getByRole("menu").getByRole("menuitem", { name: "Add a task…" }).click();
  const dlg = panel(page);
  await expect(dlg).toBeVisible();
  const tasks = tasksOf(page);
  await expect(lines(tasks)).toHaveCount(2);
  const add = addForm(tasks);
  await expect(add.getByRole("textbox", { name: "Task" })).toBeVisible();
  await expect(add.getByRole("spinbutton", { name: "Interval" })).toBeVisible();
  expect(await overflow(page)).toBe(0);
  const box = await add.boundingBox();
  expect(box.x + box.width).toBeLessThanOrEqual(400.5);
  const iv = await add.getByRole("combobox", { name: "Interval unit" }).boundingBox();
  expect(iv.x + iv.width).toBeLessThanOrEqual(400.5);
  // The chip rows wrap inside the sheet.
  const chipBox = await tasks.getByRole("radiogroup", { name: "Which task is worth doing?" }).boundingBox();
  expect(chipBox.x + chipBox.width).toBeLessThanOrEqual(400.5);
  await page.keyboard.press("Escape"); // the form closes, the sheet stays
  await expect(add).toHaveCount(0);
  await expect(dlg).toBeVisible();
  await expect(lines(tasks)).toHaveCount(2);
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect(await overflow(page)).toBe(0);
  // A task from the list: its own details, as a sheet like the others, nothing sideways.
  await goTask(tasks, `Weekly pH check ${tag}`).click();
  await expect(kindOf(page)).toHaveText("Task");
  await expect(panel(page)).toHaveClass(/sheet/);
  await expect(section(page, "Kind and interval")).toContainText("every 1 week");
  expect(await overflow(page)).toBe(0);
  for (const name of ["Kind and interval", "Then, if found", "Serves", "Logistics"]) {
    const b = await section(page, name).boundingBox();
    expect(b.x + b.width).toBeLessThanOrEqual(400.5);
  }
  // Its row in the tree, with the kind and interval on its second line.
  await expect(trow(page, `^Task: Weekly pH check ${tag}`).locator(".tt-l2")).toContainText("On condition · every 1 week");
  await expectHealthy(page, problems, { label: "rcm tasks phone" });
});

test("Calculate… in an on-condition task's details: the P-F interval alone, costs behind Show costs on a safety mode, Use writes the interval and the why", async ({ page, request, problems }) => {
  const tag = `c${Date.now()}`;
  const p = await plant(request, tag);
  await page.setViewportSize({ width: 1280, height: 800 });
  // The task's row, by its address (sel=T:<mode>:<task>).
  await open(page, `/asset-register/explorer?arrange=positions&sel=T:${p.acid.id}:${p.own}&tab=rcm`);
  const row = trow(page, `^Task: Weekly pH check ${tag}`);
  await expect(row).toBeVisible();
  await expect(row).toHaveAttribute("aria-selected", "true");
  await row.locator(".tp-nm").dblclick();
  await expect(kindOf(page)).toHaveText("Task");
  const kind = section(page, "Kind and interval");
  await expect(kind).toContainText("every 1 week");
  await kind.getByRole("button", { name: `Calculate how often to do “Weekly pH check ${tag}”` }).click();
  const calc = dialog(page, "Work out the check interval");
  await expect(calc).toBeVisible();
  // What it works out, in words, before any number.
  await expect(calc.locator(".ivc-what")).toContainText("The time from that first sign to the failure is the P-F interval.");
  // A safety failure: the costs wait behind "Show costs"; the P-F interval alone gives the answer.
  await expect(calc.getByText("the task must make the risk tolerable whatever it costs", { exact: false })).toBeVisible();
  await expect(calc.getByRole("spinbutton", { name: "Cost of a check ($)" })).toHaveCount(0);
  await calc.getByRole("spinbutton", { name: "P-F interval" }).fill("10");
  await calc.getByRole("combobox", { name: "P-F interval unit" }).selectOption("weeks");
  await expect(calc.getByText("Assumed: every check finds a warning that's there.", { exact: false })).toBeVisible();
  await calc.getByRole("button", { name: "Work it out" }).click();
  await expect(calc.locator(".ivc-answer")).toHaveText("Check every 5 weeks: half the P-F interval of 10 weeks.");
  await expect(calc.locator(".ivc-result")).toContainText("Costs only matter for whether the check pays for itself, not for the P-F interval.");
  // With the costs: the cheapest interval too, never in place of the P-F answer.
  await calc.getByRole("button", { name: "Show costs" }).click();
  await calc.getByRole("spinbutton", { name: "Failures a year, if nothing is done" }).fill("0.5");
  await calc.getByRole("spinbutton", { name: "Cost of a check ($)" }).fill("20");
  await calc.getByRole("spinbutton", { name: "Cost when found ($)" }).fill("200");
  await calc.getByRole("spinbutton", { name: "Cost of a failure ($)" }).fill("2000");
  await calc.getByRole("button", { name: "Work it out" }).click();
  await expect(calc.locator(".ivc-answer")).toContainText("The cheapest interval is 2 months");
  await expect(calc.getByRole("button", { name: "Use the cheapest, 2 months" })).toBeVisible();
  await expect(calc.locator(".ivc-facts")).toContainText("Half the P-F interval");
  await calc.getByRole("button", { name: "Use 5 weeks" }).click();
  await expect(calc).toHaveCount(0);
  await expect(kind).toContainText("every 5 weeks");
  // The calculation linked as the decision's evidence (the task's, a plain decision's one task).
  await expect(section(page, "Evidence for this task")).toContainText("Supported");
  await expect.poll(async () => {
    const rcm = await (await request.get(`${M}/rcm`)).json();
    const mode = rcm.positions.find((x) => x.id === p.pool.id).functions[0].failures[0].modes.find((x) => x.id === p.acid.id);
    return [mode.notes?.includes("P-F 10 weeks, onset 0.5/year, inspection $20, found $200, failure $2,000 → 5 weeks (half the P-F interval)"),
      mode.decision.evidence?.type, mode.decision.status];
  }).toEqual([true, "strategy_analysis", "supported"]);
  // The why at the end of the failure mode's notes and rationale.
  await toMode(page, `Acid under-dosed ${tag}`);
  await expect(panel(page)).toContainText("Interval from the P-F calculator (");
  await panel(page).getByRole("button", { name: "Back to table" }).click();
  await expect(row).toContainText("every 5 weeks");
  await expectHealthy(page, problems, { label: "rcm interval calculator" });
});

test("screenshots of a failure mode with several tasks and the table rows (SMOKE_SHOTS_DIR)", async ({ page, request }) => {
  test.skip(!SHOTS, "only when saving screenshots");
  const tag = `shot`;
  const p = await plant(request, tag);
  await postOk(request, `${M}/failure-modes/${p.acid.id}/tasks`, {
    name: "Replace the acid pump at its rated life", interval: 24, unit: "months", outcome: "fixed_interval",
    instructions: "Swap the pump head; prime the line.",
  });
  await postOk(request, `${M}/tasks/${p.own}/failure-modes/${p.cya.id}`, {});
  for (const [w, h] of [[1280, 800], [400, 860]]) {
    await page.setViewportSize({ width: w, height: h });
    await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pool.id}&tab=rcm`);
    const row = trow(page, `^Failure mode: Acid under-dosed ${tag}`).first();
    await expect(row).toContainText("+1 task");
    await row.locator(".tp-chev").click();
    await page.waitForTimeout(300);
    await page.screenshot({ path: `${SHOTS}/rcm-tasks-rows-${w}.png` });
    if (w > 600) await row.locator(".tp-nm").dblclick();
    else {
      await row.getByRole("button", { name: "Actions", exact: true }).click();
      await page.getByRole("menuitem", { name: "Open…" }).click();
    }
    await expect(panel(page)).toBeVisible();
    await tasksOf(page).scrollIntoViewIfNeeded();
    await page.waitForTimeout(300);
    await page.screenshot({ path: `${SHOTS}/rcm-tasks-panel-${w}.png` });
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog")).toHaveCount(0);
  }
});
