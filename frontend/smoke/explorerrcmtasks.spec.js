// Several tasks for one failure mode, and one task for several, on the
// Explorer's RCM tab (Assets › Explorer › RCM): a failure mode's decision card
// (step 3, "Proactive task or default action", edited in place) lists its tasks as cards, one per member
// task, each with plain Edit and Remove links; a dashed "+ Add another task" row asks its kind, then a
// new task or Use an existing task…, in place; the row menu's Add a task… opens that row (the decision
// dialog when there's no decision yet); a tap on "Which task is worth doing?" adopts a task linked before
// the decision; the Task cell says "+1 task" without the row changing height; the decision dialog
// (the row menu's Change the decision…) shows a shared task's interval read-only; at 400 px it all fits. Each test makes its own small plant through the API.
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
const addRow = (tasks) => tasks.getByRole("button", { name: "+ Add another task" });
const addForm = (tasks) => tasks.getByRole("group", { name: "Add another task" });
// A task card's own link: "Edit “‹task›”", "Remove “‹task›”", "Remove “‹task›” from this failure mode".
const taskLink = (tasks, name, verb, tail = "") => tasks.getByRole("button", { name: `${verb} “${name}”${tail}`, exact: true });
// The task cards (not the evidence lines under them).
const cards = (tasks) => tasks.locator(".rim-cards > li");
const names = (tasks) => tasks.locator(".rim-cards .rim-tname");
const settled = async (page) => {
  await page.waitForLoadState("networkidle", { timeout: 5_000 }).catch(() => {});
  await page.waitForTimeout(250);
};

test("a failure mode's decision lists its tasks; add another, use an existing one, edit, remove; the cell says +1 task", async ({ page, request, problems }) => {
  const tag = `t${Date.now()}`;
  const p = await plant(request, tag);
  await page.setViewportSize({ width: 1280, height: 800 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pool.id}&tab=rcm`);
  const acidRow = trow(page, `^Failure mode: Acid under-dosed ${tag}`);
  await expect(acidRow).toBeVisible();
  await acidRow.locator(".tp-nm").click();
  await settled(page);
  const heightBefore = (await acidRow.boundingBox()).height;

  // Its details (a double-click on its name): the decision in words with its task, one line.
  await acidRow.locator(".tp-nm").dblclick();
  let dlg = panel(page);
  await expect(dlg).toBeVisible();
  let tasks = tasksOf(page);
  await expect(chipsOf(page)).toContainText("On condition");
  await expect(cards(tasks)).toHaveCount(1);
  // Each card leads with what it's for (Derryn, 9 Nov 2026): a check, then what's done when it finds it.
  await expect(names(tasks)).toHaveText([`Check: Weekly pH check ${tag} · every 1 week`]);
  const found = tasks.getByRole("textbox", { name: "Then, if found:" });
  await expect(found).toHaveAttribute("placeholder", "Say what's done when the check finds it");
  await found.fill(`Dose acid by hand ${tag}`);
  await found.press("Enter");
  await expect(cards(tasks).first().getByRole("status")).toHaveText("✓ Saved");
  await expect(tasks.getByRole("textbox", { name: "Then, if found:" })).toHaveValue(`Dose acid by hand ${tag}`);
  await expect(tasks.getByRole("region", { name: "Tasks" })).toHaveCount(0);
  // No ⋯ and no Change…: the choice is the chip row, the task's own links are on its card.
  await expect(tasks.getByRole("button", { name: /^Actions for/ })).toHaveCount(0);
  await expect(tasks.getByRole("radiogroup", { name: "Which task is worth doing?" }).getByRole("radio", { name: /On condition/ }))
    .toHaveAttribute("aria-checked", "true");

  // Add another task: in place, its kind first (on condition is taken), then its name
  // and how often (no "what does it catch" hint: a safety consequence may combine tasks). No interval yet: it says so.
  await addRow(tasks).click();
  let add = addForm(tasks);
  await expect(add).toBeVisible();
  const kinds = add.getByRole("radiogroup", { name: "Kind of task" });
  await expect(kinds.getByRole("radio")).toHaveText([/Fixed interval/, /Failure finding/, /Redesign/]);
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
  await expect(add).toHaveCount(0);
  expect(writes).toBe(1);
  await expect(dialog(page, "Add another task")).toHaveCount(0); // never a dialog
  await expect(cards(tasks)).toHaveCount(2);
  await expect(chipsOf(page)).toContainText("On condition + Fixed interval");
  const item = (name) => cards(tasks).filter({ hasText: name });
  await expect(item(`Replace the acid pump ${tag}`)).toContainText(`Do: Replace the acid pump ${tag}`);
  // The check keeps what's done when it finds it.
  await expect(tasks.getByRole("textbox", { name: "Then, if found:" })).toHaveValue(`Dose acid by hand ${tag}`);
  await expect(item(`Replace the acid pump ${tag}`)).toContainText("every 24 months");
  // Its instructions: its card's Edit, as for any other task.
  await taskLink(tasks, `Replace the acid pump ${tag}`, "Edit").click();
  await tasks.getByRole("textbox", { name: "Instructions" }).fill("Swap the pump head.");
  await tasks.getByRole("button", { name: "Save task" }).click();
  await expect(item(`Replace the acid pump ${tag}`)).toContainText("Swap the pump head.");

  // Use an existing task on the position: the one kind left (failure finding), then the picker.
  await addRow(tasks).click();
  add = addForm(tasks);
  await expect(add.getByRole("radiogroup", { name: "Kind of task" }).getByRole("radio")).toHaveText([/Failure finding/]);
  await add.getByRole("button", { name: "Use an existing task…" }).click();
  const pick = add.getByRole("combobox", { name: "Existing task" });
  await expect(pick).toBeVisible();
  await expect(pick.locator("option")).toContainText([/Choose a task/, new RegExp(`Backwash the filter ${tag} · every 1 month`)]);
  await pick.selectOption({ label: await pick.locator("option").nth(1).textContent() });
  await add.getByRole("button", { name: "Link task" }).click();
  await expect(add).toHaveCount(0);
  await expect(cards(tasks)).toHaveCount(3);
  await expect(item(`Backwash the filter ${tag}`)).toContainText("Check it still works: ");
  await expect(item(`Backwash the filter ${tag}`).getByRole("textbox", { name: "Then, if failed:" })).toBeVisible();
  // No kind left to add: no add row.
  await expect(addRow(tasks)).toHaveCount(0);

  // Edit the second task: a plain change, kept.
  await taskLink(tasks, `Replace the acid pump ${tag}`, "Edit").click();
  await tasks.getByRole("spinbutton", { name: "Interval" }).fill("36");
  await tasks.getByRole("button", { name: "Save task" }).click();
  await expect(item(`Replace the acid pump ${tag}`)).toContainText("every 36 months");

  // Remove the linked task: it serves only this mode, so it is retired (after asking); its member stays, with no task now.
  await taskLink(tasks, `Backwash the filter ${tag}`, "Remove").click();
  const ask = page.getByRole("alertdialog", { name: "Remove this task?" });
  await expect(ask).toContainText("serves only this failure mode, so it is retired");
  await ask.getByRole("button", { name: "Retire the task" }).click();
  await expect(item(`Backwash the filter ${tag}`)).toHaveCount(0);
  await expect(cards(tasks).filter({ hasText: "Check it still works: no task now" })).toHaveCount(1);
  await expect(cards(tasks)).toHaveCount(3);
  await panel(page).getByRole("button", { name: "Back to table" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);

  // The table: the decision's own task and "+1 task", the row no taller; the tooltip lists both.
  await expect(acidRow).toContainText(`Weekly pH check ${tag}`);
  await expect(acidRow).toContainText("+1 task");
  expect((await acidRow.boundingBox()).height).toBe(heightBefore);
  const cell = acidRow.locator(".rw-task");
  expect(await cell.getAttribute("title")).toContain(`Replace the acid pump ${tag} · every 36 months`);

  // The server agrees.
  const rcm = await (await request.get(`${M}/rcm`)).json();
  const mode = rcm.positions.find((x) => x.id === p.pool.id).functions[0].failures[0].modes.find((x) => x.id === p.acid.id);
  expect(mode.decision.tasks.map((t) => [t.name, t.interval, t.unit])).toEqual([[`Weekly pH check ${tag}`, 1, "weeks"], [`Replace the acid pump ${tag}`, 36, "months"]]);
  await expectHealthy(page, problems, { label: "rcm tasks dialog" });
});

test("one task for several modes: adopted by a tap, read-only in the decision dialog, unlinked (not retired) on Remove", async ({ page, request, problems }) => {
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
  // task linked before it as a card under its own heading, no add row.
  await saltRow.locator(".tp-nm").dblclick();
  const dlg = panel(page);
  await expect(dlg).toBeVisible();
  const tasks = tasksOf(page);
  const which = tasks.getByRole("radiogroup", { name: "Which task is worth doing?" });
  await expect(which.getByRole("radio", { checked: true })).toHaveCount(0);
  await expect(which.getByRole("radio", { name: /On condition/ })).toBeDisabled();
  await expect(tasks).toContainText("Answer step 2 first: what's worth doing depends on the consequence.");
  await expect(tasks.getByRole("button", { name: "Decide…" })).toHaveCount(0);
  await expect(tasks.getByRole("heading", { name: "Tasks linked before the decision" })).toBeVisible();
  await expect(cards(tasks)).toHaveCount(1);
  await expect(cards(tasks).first()).toContainText(/shared with 1 other failure mode/i);
  await expect(tasks.getByRole("button", { name: /^\+ Add another task/ })).toHaveCount(0);
  // Step 2 answered (hidden, operational): failure finding is offered; one tap decides, adopting that task.
  await dlg.getByRole("radiogroup", { name: "Hidden failure?" }).getByRole("radio", { name: "Hidden" }).click();
  await dlg.getByRole("radiogroup", { name: "Consequence category" }).getByRole("radio", { name: "Operational", exact: true }).click();
  await expect(which.getByRole("radio", { name: /Failure finding/ })).toBeEnabled();
  await which.getByRole("radio", { name: /Failure finding/ }).click();
  await expect(which.getByRole("radio", { name: /Failure finding/ })).toHaveAttribute("aria-checked", "true");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(chipsOf(page)).toContainText("Failure finding");
  await expect(cards(tasks)).toHaveCount(1);
  await expect(cards(tasks).first()).toContainText(`Weekly pH check ${tag} · every 1 week`);
  await expect(tasks.getByRole("heading", { name: "Tasks linked before the decision" })).toHaveCount(0);
  // The row menu's Change the decision… (the panel never opens the dialog): the shared interval read-only, and why.
  await saltRow.locator(".tp-nm").click();
  await page.keyboard.press("Shift+F10");
  await page.getByRole("menu").getByRole("menuitem", { name: "Change the decision…" }).click();
  await expect(decide.getByRole("spinbutton", { name: /^Interval/ })).toHaveAttribute("readonly", "");
  await expect(decide.getByText(/also serves 1 other failure mode, so its name and interval are changed on the task/)).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(decide).toHaveCount(0);
  // Remove: unlinked, not retired; the pool's mode keeps it.
  await taskLink(tasks, `Weekly pH check ${tag}`, "Remove", " from this failure mode").click();
  const ask = page.getByRole("alertdialog", { name: "Remove this task?" });
  await expect(ask).toContainText("also serves 1 other failure mode, so it stays with them");
  await ask.getByRole("button", { name: "Remove from this failure mode" }).click();
  // The decision alone now: the task form in its place, its name and interval asked for.
  await expect(cards(tasks)).toHaveCount(0);
  await expect(tasks).toContainText("The decision schedules work, but no task does it yet");
  await expect(tasks.getByRole("textbox", { name: "Task" })).toBeVisible();
  await expect(tasks.getByRole("spinbutton", { name: "Interval" })).toBeVisible();
  const rcm = await (await request.get(`${M}/rcm`)).json();
  const acid = rcm.positions.find((x) => x.id === p.pool.id).functions[0].failures[0].modes.find((x) => x.id === p.acid.id);
  expect(acid.decision.tasks.map((t) => t.id)).toEqual([p.own]);
  await expectHealthy(page, problems, { label: "rcm shared task" });
});

test("at 400 px the decision's tasks and the Add another task form fit", async ({ page, request, problems }) => {
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
  await expect(cards(tasks)).toHaveCount(2);
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
  await expect(cards(tasks)).toHaveCount(2);
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect(await overflow(page)).toBe(0);
  await expectHealthy(page, problems, { label: "rcm tasks phone" });
});

;

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
