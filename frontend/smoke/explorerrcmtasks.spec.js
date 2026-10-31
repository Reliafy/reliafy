// Several tasks for one failure mode, and one task for several, on the
// Explorer's RCM tab (Operate › Assets › Explorer › RCM): the failure mode's
// details list its tasks (the decision's own first) with Add another task…,
// Edit…, Remove and Use an existing task…; the row menu's Add a task… opens
// the details on the add form; the Task cell says "+1 task"
// without the row changing height; the decision dialog shows a shared task's
// interval read-only; at 400 px it all fits. Each test makes its own small
// plant through the API.
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
    data: { consequence: "operational", decision: { outcome: "on_condition", task: `Weekly pH check ${tag}`, interval: 1, interval_unit: "weeks" } },
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
const tasksOf = (page) => panel(page).getByRole("region", { name: "Tasks" });
const overflow = (page) => page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
const settled = async (page) => {
  await page.waitForLoadState("networkidle", { timeout: 5_000 }).catch(() => {});
  await page.waitForTimeout(250);
};

test("a failure mode's details list its tasks; add another, link an existing one, edit, remove; the cell says +1 task", async ({ page, request, problems }) => {
  const tag = `t${Date.now()}`;
  const p = await plant(request, tag);
  await page.setViewportSize({ width: 1280, height: 800 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pool.id}&tab=rcm`);
  const acidRow = trow(page, `^Failure mode: Acid under-dosed ${tag}`);
  await expect(acidRow).toBeVisible();
  await acidRow.locator(".tp-nm").click();
  await settled(page);
  const heightBefore = (await acidRow.boundingBox()).height;

  // Its details (a double-click on its name): one task, the decision's.
  await acidRow.locator(".tp-nm").dblclick();
  let dlg = panel(page);
  await expect(dlg).toBeVisible();
  let tasks = tasksOf(page);
  await expect(tasks.getByRole("listitem")).toHaveCount(1);
  await expect(tasks).toContainText(`Weekly pH check ${tag}`);
  await expect(tasks).toContainText("every 1 week");

  // Add another task: the hint asks what it catches (an operational consequence); saved once.
  await tasks.getByRole("button", { name: "Add another task…" }).click();
  await expect(tasks.getByText(/What does this task catch that/)).toBeVisible();
  await expect(tasks.getByRole("textbox", { name: "Task" })).toBeFocused();
  await tasks.getByRole("textbox", { name: "Task" }).fill(`Replace the acid pump ${tag}`);
  await tasks.getByRole("spinbutton", { name: "Interval" }).fill("24");
  await tasks.getByRole("combobox", { name: "Interval unit" }).selectOption("months");
  await tasks.getByRole("combobox", { name: "Kind of task" }).selectOption("fixed_interval");
  await tasks.getByRole("textbox", { name: "Instructions (optional)" }).fill("Swap the pump head.");
  let writes = 0;
  page.on("request", (r) => { if (r.method() === "POST" && r.url().includes(`/failure-modes/${p.acid.id}/tasks`)) writes += 1; });
  await tasks.getByRole("button", { name: "Add task" }).dblclick();
  await expect(tasks.getByRole("listitem")).toHaveCount(2);
  expect(writes).toBe(1);
  const item = (name) => tasks.getByRole("listitem").filter({ hasText: name });
  await expect(tasks.getByRole("listitem").nth(0)).toContainText("the decision's own");
  await expect(item(`Replace the acid pump ${tag}`)).toContainText("every 24 months · Fixed-interval");
  await expect(item(`Replace the acid pump ${tag}`)).toContainText("Swap the pump head.");
  await expect(dlg.getByRole("heading", { name: "Tasks (2)" })).toBeVisible();

  // Link an existing task on the position: it serves this mode too.
  await tasks.getByRole("button", { name: "Use an existing task…" }).click();
  const pick = tasks.getByRole("combobox", { name: "Existing task" });
  await expect(pick).toBeVisible();
  await expect(pick.locator("option")).toContainText([/Choose a task/, new RegExp(`Backwash the filter ${tag} · every 1 month`)]);
  await pick.selectOption({ label: await pick.locator("option").nth(1).textContent() });
  await tasks.getByRole("button", { name: "Link task" }).click();
  await expect(tasks.getByRole("listitem")).toHaveCount(3);
  await expect(dlg.getByRole("heading", { name: "Tasks (3)" })).toBeVisible();

  // Edit the second task: a plain change, kept.
  await tasks.getByRole("button", { name: `Edit Replace the acid pump ${tag}` }).click();
  await tasks.getByRole("spinbutton", { name: "Interval" }).fill("36");
  await tasks.getByRole("button", { name: "Save task" }).click();
  await expect(item(`Replace the acid pump ${tag}`)).toContainText("every 36 months");

  // Remove the linked task: it serves only this mode, so it is retired (after asking).
  await tasks.getByRole("button", { name: `Remove Backwash the filter ${tag}` }).click();
  const ask = page.getByRole("alertdialog", { name: "Remove this task?" });
  await expect(ask).toContainText("serves only this failure mode, so it is retired");
  await ask.getByRole("button", { name: "Retire the task" }).click();
  await expect(tasks.getByRole("listitem")).toHaveCount(2);
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

test("one task for several modes: shared, read-only in the decision dialog, unlinked (not retired) on Remove", async ({ page, request, problems }) => {
  const tag = `s${Date.now()}`;
  const p = await plant(request, tag);
  // The pool's weekly check also covers the chlorinator cell's salinity (a position inside the pool).
  await postOk(request, `${M}/tasks/${p.own}/failure-modes/${p.salt.id}`, {});
  await page.setViewportSize({ width: 1280, height: 800 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.cell.id}&tab=rcm`);
  const saltRow = trow(page, `^Failure mode: Salinity low ${tag}`);
  await expect(saltRow).toBeVisible();
  // Add a task… in the row menu opens the details on the add form.
  await saltRow.locator(".tp-nm").click();
  await page.keyboard.press("Shift+F10");
  await page.getByRole("menu").getByRole("menuitem", { name: "Add a task…" }).click();
  const dlg = panel(page);
  await expect(dlg).toBeVisible();
  const tasks = tasksOf(page);
  await expect(tasks.getByRole("textbox", { name: "Task" })).toBeFocused();
  await expect(tasks.getByText(/What does this task catch/)).toHaveCount(0); // no consequence set: no hint
  await tasks.getByRole("button", { name: "Cancel" }).click();
  await expect(tasks.getByRole("listitem")).toHaveCount(1);
  await expect(tasks.getByRole("listitem").first()).toContainText("shared with 1 other failure mode");
  // Decide… with that task: the decision dialog shows its interval read-only and says why.
  await dlg.getByRole("button", { name: "Decide…" }).click();
  const decide = page.getByRole("dialog", { name: /^Decision/ });
  await decide.getByRole("button", { name: "Hidden" }).click();
  await decide.getByRole("button", { name: /Failure-finding/ }).click();
  await decide.getByRole("button", { name: "Apply" }).click();
  await expect(decide).toHaveCount(0);
  await expect(dlg.getByRole("region", { name: "Decision" })).toContainText("Failure-finding");
  await dlg.getByRole("button", { name: "Change the decision…" }).click();
  await expect(decide.getByRole("spinbutton", { name: /^Interval/ })).toHaveAttribute("readonly", "");
  await expect(decide.getByText(/also serves 1 other failure mode, so its name and interval are changed on the task/)).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(decide).toHaveCount(0);
  // Remove: unlinked, not retired; the pool's mode keeps it.
  await tasks.getByRole("button", { name: `Remove Weekly pH check ${tag}` }).click();
  const ask = page.getByRole("alertdialog", { name: "Remove this task?" });
  await expect(ask).toContainText("also serves 1 other failure mode, so it stays with them");
  await ask.getByRole("button", { name: "Remove from this failure mode" }).click();
  await expect(tasks.getByRole("listitem")).toHaveCount(0);
  await expect(tasks).toContainText("The decision schedules work, but no task does it yet");
  const rcm = await (await request.get(`${M}/rcm`)).json();
  const acid = rcm.positions.find((x) => x.id === p.pool.id).functions[0].failures[0].modes.find((x) => x.id === p.acid.id);
  expect(acid.decision.tasks.map((t) => t.id)).toEqual([p.own]);
  await expectHealthy(page, problems, { label: "rcm shared task" });
});

test("at 400 px the Tasks section and its forms fit the sheet", async ({ page, request, problems }) => {
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
  await expect(tasks.getByRole("listitem")).toHaveCount(2);
  await expect(tasks.getByRole("textbox", { name: "Task" })).toBeVisible();
  expect(await overflow(page)).toBe(0);
  const box = await dlg.boundingBox();
  expect(box.x + box.width).toBeLessThanOrEqual(400.5);
  await tasks.getByRole("button", { name: "Cancel" }).click();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect(await overflow(page)).toBe(0);
  await expectHealthy(page, problems, { label: "rcm tasks phone" });
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
