// The one details panel on the Explorer's RCM tab (Assets ›
// Explorer › RCM). A click on a row shows its details beside the table; a
// double-click on its name (not on a data cell, which edits in place, nor the
// chevron), Open… first in its row menu, or Expand in the panel spreads them
// across the table, the tree column kept on the left: another row picked there
// shows in the panel. Back to table and Esc return; the focus goes into the
// heading and back to the row. Everything the old dialog had is here, kept as
// you go: a function's performance standards (its working in its notes), a standard's limit
// fields, a failure's status, links and failure modes, a failure mode's
// decision and its several tasks. At every level what's inside it comes first,
// then its own fields, then the quieter things (the checkable
// limit, where it sits, notes). At 400 px it is the sheet and nothing
// scrolls sideways. Each test makes its own small plant through the API and
// pins it (?pin=), so its rows start at the top of the tree.
//
// With SMOKE_SHOTS_DIR set, it also saves screenshots at 1280 and 400 px
// (side by side, a function with several performance standards expanded, a
// failure mode with several tasks expanded) for the pull request.
import { test, expect, open, expectHealthy, postOk } from "./health.js";

const M = "/api/maintenance";
const SHOTS = process.env.SMOKE_SHOTS_DIR || "";

async function plant(request, tag) {
  const post = (path, data) => postOk(request, path, data);
  const top = await post(`${M}/positions`, { name: `Panel plant ${tag}` });
  const pump = await post(`${M}/positions`, { name: `Panel pump ${tag}`, parent_id: top.id });
  const fn = await post(`${M}/positions/${pump.id}/functions`, { text: `Pump water ${tag}`, standard: `At least 10 L/s ${tag}` });
  await post(`${M}/functions/${fn.id}/standards`, { text: `At 3 bar ${tag}`, parameter: "Pressure", comparator: ">=", value: "3", unit: "bar" });
  const { standards } = await (await request.get(`${M}/functions/${fn.id}`)).json();
  const ff = await post(`${M}/functions/${fn.id}/failures`, { text: `No flow ${tag}`, standard_id: standards[0].id });
  const mode = await post(`${M}/positions/${pump.id}/failure-modes`, { text: `Bearing seizes ${tag}`, functional_failure_id: ff.id });
  const seal = await post(`${M}/positions/${pump.id}/failure-modes`, { text: `Seal leaks ${tag}`, functional_failure_id: ff.id });
  const res = await request.put(`${M}/failure-modes/${seal.id}/decision`, {
    data: { consequence: "operational", decision: { outcome: "on_condition", task: `Check the seal ${tag}`, interval: 1, interval_unit: "months" } },
  });
  expect(res.ok()).toBeTruthy();
  await post(`${M}/failure-modes/${seal.id}/tasks`, { name: `Replace the seal ${tag}`, interval: 24, unit: "months", outcome: "fixed_interval" });
  return { top, pump, fn, standards, ff, mode, seal };
}

const url = (p) => `/asset-register/explorer?arrange=positions&sel=${p.pump.id}&pin=${p.top.id}&tab=rcm`;
const table = (page) => page.getByRole("treegrid", { name: /and their RCM/ });
const trow = (page, name) => table(page).getByRole("row", { name: new RegExp(name) });
const panel = (page) => page.getByRole("complementary", { name: "Details" });
const heads = (page) => table(page).getByRole("columnheader");
const overflow = (page) => page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
const isExpanded = (page) => panel(page).evaluate((el) => el.classList.contains("is-expanded"));
const settled = async (page) => {
  await page.waitForLoadState("networkidle", { timeout: 5_000 }).catch(() => {});
  await page.waitForTimeout(250);
};
const rcmOf = async (request, p) => (await (await request.get(`${M}/rcm`)).json()).positions.find((x) => x.id === p.pump.id);

test("a click shows the details beside the table; a double-click on the name spreads them across it, the tree kept", async ({ page, request, problems }) => {
  const tag = `x${Date.now()}`;
  const p = await plant(request, tag);
  await page.setViewportSize({ width: 1280, height: 800 });
  await open(page, url(p));
  const fnRow = trow(page, `^Function: Pump water ${tag}`);
  const stdRow = trow(page, `^Performance standard: At 3 bar ${tag}`);
  const ffRow = trow(page, `^Functional failure: No flow ${tag}`);
  const modeRow = trow(page, `^Failure mode: Bearing seizes ${tag}`);
  await expect(modeRow).toBeVisible();
  const columns = await heads(page).count();
  expect(columns).toBeGreaterThan(2);

  // A click: beside the table, at its usual width; the arrow keys move and the panel follows.
  await ffRow.locator(".tp-nm").click();
  await expect(panel(page).getByRole("heading", { name: `No flow ${tag}` })).toBeVisible();
  expect(await isExpanded(page)).toBe(false);
  expect((await panel(page).boundingBox()).width).toBeLessThan(400);
  await expect(heads(page)).toHaveCount(columns);
  await page.keyboard.press("ArrowDown");
  await expect(panel(page).getByRole("heading", { name: `Bearing seizes ${tag}` })).toBeVisible();

  // A double-click on the function's name: across the table, the tree column alone beside it, the focus in its heading.
  await fnRow.locator(".tp-nm").dblclick();
  await expect(panel(page).getByRole("heading", { name: `Pump water ${tag}` })).toBeFocused();
  expect(await isExpanded(page)).toBe(true);
  await expect(heads(page)).toHaveCount(1);
  expect((await panel(page).boundingBox()).width).toBeGreaterThan(700);
  expect(await overflow(page)).toBe(0);
  const fnPanel = panel(page);
  // The title is the description: a click edits it in place.
  await fnPanel.locator(".rw-title-btn").click();
  await expect(fnPanel.getByRole("textbox", { name: /^Description/ })).toHaveValue(`Pump water ${tag}`);
  await page.keyboard.press("Escape");
  await expect(fnPanel.getByRole("heading", { name: `Pump water ${tag}` })).toBeFocused();
  const list = fnPanel.getByRole("region", { name: "Performance standards" });
  await expect(list).toContainText(`At least 10 L/s ${tag}`);
  await expect(list).toContainText(`At 3 bar ${tag}`);
  // No notes yet: the hint is the quiet Add notes' tooltip (and shows in the box).
  await expect(fnPanel.getByRole("region", { name: "Notes and rationale" }).getByRole("button", { name: "Add notes" }))
    .toHaveAttribute("title", /Why these limits: the working/);
  await expect(fnPanel.getByRole("region", { name: "Functional failures" }).getByRole("button", { name: `No flow ${tag}` })).toBeVisible();

  // Another row picked in the tree: the panel shows it, still across the table.
  await stdRow.locator(".tp-nm").click();
  await expect(panel(page).getByRole("heading", { name: `At 3 bar ${tag}` })).toBeVisible();
  expect(await isExpanded(page)).toBe(true);
  // A standard's limit fields (folded: Edit… on its one line opens them), each kept as you leave it.
  await expect(panel(page).locator(".rw-checkable")).toContainText("Checkable: Pressure at least 3 bar");
  await panel(page).getByRole("button", { name: "Edit the checkable limit" }).click();
  await expect(panel(page).getByRole("textbox", { name: "Parameter", exact: true })).toHaveValue("Pressure");
  await expect(panel(page).getByRole("combobox", { name: "Comparator" })).toHaveValue(">=");
  await panel(page).getByRole("textbox", { name: "When it applies", exact: true }).fill("while the pump runs");
  await panel(page).getByRole("textbox", { name: "Source", exact: true }).fill("the pump's data sheet");
  await panel(page).getByRole("textbox", { name: "Source", exact: true }).press("Enter");
  await expect.poll(async () => {
    const fn = (await rcmOf(request, p)).functions[0];
    const st = fn.standards.find((x) => x.text === `At 3 bar ${tag}`);
    return [st.when, st.source];
  }).toEqual(["while the pump runs", "the pump's data sheet"]);
  await panel(page).getByRole("combobox", { name: "Comparator" }).selectOption(">");
  await expect.poll(async () => (await rcmOf(request, p)).functions[0].standards.find((x) => x.text === `At 3 bar ${tag}`).comparator).toBe(">");

  // A functional failure: its status in words, its links, its failure modes; one shown from the list.
  await ffRow.locator(".tp-nm").click();
  await expect(panel(page).getByText("1 of its 2 failure modes still needs a decision.")).toBeVisible();
  await expect(panel(page).getByRole("region", { name: "Caused by" })).toBeVisible();
  await expect(panel(page).getByRole("region", { name: "Causes" })).toBeVisible();
  await panel(page).getByRole("region", { name: "Failure modes" }).getByRole("button", { name: `Bearing seizes ${tag}` }).click();
  await expect(panel(page).getByRole("heading", { name: `Bearing seizes ${tag}` })).toBeVisible();
  expect(await isExpanded(page)).toBe(true);

  // A failure mode: kept as you go; a refused value stays with its reason and nothing is sent.
  let writes = 0;
  page.on("request", (r) => { if (r.method() !== "GET" && r.url().includes(`/failure-modes/${p.mode.id}`)) writes += 1; });
  await panel(page).locator(".rw-title-btn").click();
  const desc = panel(page).getByRole("textbox", { name: /^Description/ });
  await desc.fill("   ");
  await desc.blur();
  await expect(panel(page).getByRole("alert")).toHaveText("Every failure mode needs a description.");
  expect(writes).toBe(0);
  await desc.fill(`Bearing seizes early ${tag}`);
  await desc.blur();
  await panel(page).getByRole("textbox", { name: /^Failure effects/ }).fill("Pump stops; no flow to the tank");
  await panel(page).getByRole("textbox", { name: /^Failure effects/ }).blur();
  // The two RCM questions: one tap on a chip each, the chosen one ticked; "✓ Saved" by its label.
  const evident = panel(page).getByRole("radiogroup", { name: "Hidden failure?" });
  await evident.getByRole("radio", { name: "Hidden" }).click();
  await expect(evident.getByRole("radio", { name: "Hidden" })).toHaveAttribute("aria-checked", "true");
  await expect(panel(page).getByRole("status").filter({ hasText: "✓ Saved" }).first()).toBeVisible();
  const consequence = panel(page).getByRole("radiogroup", { name: "Consequence category" });
  await consequence.getByRole("radio", { name: "Operational", exact: true }).click();
  await expect(consequence.getByRole("radio", { name: "Operational", exact: true })).toHaveAttribute("aria-checked", "true");
  await expect.poll(async () => {
    const m = (await rcmOf(request, p)).functions[0].failures[0].modes.find((x) => x.id === p.mode.id);
    return [m.text, m.effects, m.hidden, m.consequence];
  }).toEqual([`Bearing seizes early ${tag}`, "Pump stops; no flow to the tank", true, "operational"]);
  // Step 3, no decision: a yes or no with nothing chosen, open now step 2 is answered; no Decide…,
  // no tasks listed, no add row, no ⋯. "Task(s) worth doing" opens the first task's row, its kind
  // first (failure finding offered: the failure is hidden); nothing is saved until the task is.
  const todo = panel(page).getByRole("region", { name: "Proactive task or default action" });
  const which = todo.getByRole("radiogroup", { name: "Which task is worth doing?" });
  await expect(which.getByRole("radio")).toHaveText([/Task\(s\) worth doing/, /No task is worth doing/]);
  await expect(which.getByRole("radio", { checked: true })).toHaveCount(0);
  await expect(which.getByRole("radio", { name: /Task\(s\) worth doing/ })).toBeEnabled();
  let firstPuts = 0;
  const countPut = (q) => { if (q.method() === "PUT" && q.url().includes(`/failure-modes/${p.mode.id}/decision`)) firstPuts += 1; };
  page.on("request", countPut);
  await which.getByRole("radio", { name: /Task\(s\) worth doing/ }).click();
  const firstTask = todo.getByRole("group", { name: "The decision's task" });
  await expect(firstTask.getByRole("radiogroup", { name: "Kind of task" }).getByRole("radio"))
    .toHaveText([/On condition/, /Fixed interval/, /Failure finding/]);
  await page.waitForTimeout(300);
  expect(firstPuts).toBe(0);
  page.off("request", countPut);
  await firstTask.getByRole("button", { name: "Cancel" }).click(); // taken back: as it was
  await expect(which.getByRole("radio", { checked: true })).toHaveCount(0);
  await expect(todo.getByRole("button", { name: "Decide…" })).toHaveCount(0);
  await expect(todo.locator(".rim-cards > li")).toHaveCount(0);
  await expect(todo.getByRole("list", { name: "The decision's tasks" })).toHaveCount(0);
  await expect(todo.getByRole("button", { name: /^Actions for/ })).toHaveCount(0);
  await expect(panel(page).getByRole("button", { name: /^Add (another|a) task/ })).toHaveCount(0);
  await expect(panel(page).getByRole("button", { name: "Save" })).toHaveCount(0); // no Save or Cancel: kept as you go

  // Esc: back to the table, the focus on the row; Expand and Back to table do the same by button.
  const saved = trow(page, `^Failure mode: Bearing seizes early ${tag}`);
  await panel(page).getByRole("heading", { level: 2 }).focus();
  await page.keyboard.press("Escape");
  await expect(saved).toBeFocused();
  expect(await isExpanded(page)).toBe(false);
  await expect(heads(page)).toHaveCount(columns);
  await panel(page).getByRole("button", { name: "Expand the details" }).click();
  await expect(panel(page).getByRole("heading", { name: `Bearing seizes early ${tag}` })).toBeFocused();
  await expect(heads(page)).toHaveCount(1);
  await panel(page).getByRole("button", { name: "Back to table" }).click();
  await expect(saved).toBeFocused();
  await expect(heads(page)).toHaveCount(columns);

  // A data cell still edits in place on a double-click, and doesn't expand.
  await saved.getByRole("gridcell").first().dblclick();
  await expect(table(page).getByRole("textbox", { name: /^Failure effects of/ })).toBeFocused();
  await page.keyboard.press("Escape");
  expect(await isExpanded(page)).toBe(false);

  // The chevron: a double-click opens or closes the row once, and doesn't expand.
  const was = await fnRow.getAttribute("aria-expanded");
  await fnRow.locator(".tp-chev").dblclick();
  await expect(fnRow).toHaveAttribute("aria-expanded", was === "true" ? "false" : "true");
  expect(await isExpanded(page)).toBe(false);
  await fnRow.locator(".tp-chev").click();
  await expect(fnRow).toHaveAttribute("aria-expanded", was);

  // Closed, then a click: beside the table again.
  await panel(page).getByRole("button", { name: "Close the details" }).click();
  await expect(panel(page)).toHaveCount(0);
  await saved.locator(".tp-nm").click();
  await expect(panel(page)).toBeVisible();
  expect(await isExpanded(page)).toBe(false);
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expectHealthy(page, problems, { label: "rcm panel" });
});

test("Open… and Add a task… in the row menu expand the details; Enter shows them beside the table", async ({ page, request, problems }) => {
  const tag = `o${Date.now()}`;
  const p = await plant(request, tag);
  await page.setViewportSize({ width: 1280, height: 800 });
  await open(page, url(p));
  const ffRow = trow(page, `^Functional failure: No flow ${tag}`);
  const sealRow = trow(page, `^Failure mode: Seal leaks ${tag}`);
  await ffRow.locator(".tp-nm").click();
  await page.keyboard.press("Shift+F10");
  const menu = page.getByRole("menu", { name: new RegExp(`^Actions for Functional failure: No flow ${tag}`) });
  await expect(menu.getByRole("menuitem").first()).toHaveText("Open…");
  await expect(menu.getByRole("menuitem", { name: "Open…" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(panel(page).getByRole("heading", { name: `No flow ${tag}` })).toBeFocused();
  expect(await isExpanded(page)).toBe(true);
  await page.keyboard.press("Escape");
  await expect(ffRow).toBeFocused();

  // Enter on a row: its details beside the table, the focus in them.
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("ArrowDown");
  await expect(sealRow).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(panel(page).getByRole("heading", { name: `Seal leaks ${tag}` })).toBeFocused();
  expect(await isExpanded(page)).toBe(false);

  // Add a task…: across the table, "Add a task" open in place on its kind; the two tasks listed.
  await sealRow.locator(".tp-nm").click({ button: "right" });
  await page.getByRole("menuitem", { name: "Add a task…" }).click();
  const tasks = panel(page).getByRole("region", { name: "Proactive task or default action" });
  const add = tasks.getByRole("group", { name: "Add a task" });
  const listed = tasks.getByRole("list", { name: "The decision's tasks" }).getByRole("listitem");
  await expect(add).toBeVisible();
  // Focus on its kind: the one it starts on (a kind the decision doesn't have yet; every kind is offered).
  await expect(add.getByRole("radiogroup", { name: "Kind of task" }).getByRole("radio", { checked: true })).toBeFocused();
  expect(await isExpanded(page)).toBe(true);
  await expect(listed).toHaveCount(2);
  await page.keyboard.press("Escape"); // the form closes, the panel stays
  await expect(add).toHaveCount(0);
  await expect(panel(page)).toBeVisible();
  await expect(tasks.getByRole("button", { name: "Add a task", exact: true })).toBeVisible();
  await expect(listed).toHaveCount(2);
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expectHealthy(page, problems, { label: "rcm open from menu" });
});

test("at 400 px Open… shows the details sheet, which fits; no Expand", async ({ page, request, problems }) => {
  const tag = `p${Date.now()}`;
  const p = await plant(request, tag);
  await page.setViewportSize({ width: 400, height: 860 });
  await open(page, url(p));
  const fnRow = trow(page, `^Function: Pump water ${tag}`);
  await fnRow.getByRole("button", { name: "Actions", exact: true }).click();
  await page.getByRole("menu", { name: new RegExp(`^Actions for Function: Pump water ${tag}`) }).getByRole("menuitem", { name: "Open…" }).click();
  const sheet = panel(page);
  await expect(sheet.getByRole("heading", { name: `Pump water ${tag}` })).toBeVisible();
  await expect(sheet.getByRole("button", { name: "Expand the details" })).toHaveCount(0);
  await expect(sheet.getByRole("button", { name: "Back to table" })).toHaveCount(0);
  const box = await sheet.boundingBox();
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(400.5);
  expect(await overflow(page)).toBe(0);
  // A performance standard is a list item with its own save.
  const standards = sheet.getByRole("region", { name: "Performance standards" });
  await standards.getByRole("button", { name: `Actions for At 3 bar ${tag}` }).click();
  await page.getByRole("menu", { name: `Actions for At 3 bar ${tag}` }).getByRole("menuitem", { name: "Edit…" }).click();
  await standards.getByRole("textbox", { name: "Performance standard" }).fill(`At 3.5 bar ${tag}`);
  await standards.getByRole("button", { name: "Save performance standard" }).click();
  await expect(standards).toContainText(`At 3.5 bar ${tag}`);
  expect(await overflow(page)).toBe(0);
  await sheet.getByRole("button", { name: "Close the details" }).click();
  await expect(panel(page)).toHaveCount(0);
  await expectHealthy(page, problems, { label: "rcm panel phone" });
});

test("screenshots of the panel side by side and expanded (SMOKE_SHOTS_DIR)", async ({ page, request }) => {
  test.skip(!SHOTS, "only when saving screenshots");
  const tag = `s${Date.now()}`;
  const p = await plant(request, tag);
  for (const [w, h] of [[1280, 800], [400, 860]]) {
    await page.setViewportSize({ width: w, height: h });
    await open(page, url(p));
    const fnRow = trow(page, `^Function: Pump water ${tag}`);
    const sealRow = trow(page, `^Failure mode: Seal leaks ${tag}`);
    await expect(sealRow).toBeVisible();
    await sealRow.locator(".tp-nm").click();
    await settled(page);
    await page.screenshot({ path: `${SHOTS}/rcm-panel-side-${w}.png` });
    // Each level expanded (desktop) or as the sheet (400 px), the whole panel.
    const levels = [
      ["function", fnRow],
      ["standard", trow(page, `^Performance standard: At 3 bar ${tag}`)],
      ["failure", trow(page, `^Functional failure: No flow ${tag}`)],
      ["mode", sealRow],
    ];
    for (const [name, row] of levels) {
      if (w > 600) await row.locator(".tp-nm").dblclick();
      else {
        await page.getByRole("button", { name: "Close the details" }).click();
        await row.getByRole("button", { name: "Actions", exact: true }).click();
        await page.getByRole("menuitem", { name: "Open…" }).click();
      }
      await settled(page);
      await page.screenshot({ path: `${SHOTS}/rcm-panel-${name}-${w}.png` });
      // The whole panel: a tall window, so nothing is scrolled out of the shot.
      await page.setViewportSize({ width: w, height: 2400 });
      await settled(page);
      await panel(page).screenshot({ path: `${SHOTS}/rcm-panel-${name}-${w}-whole.png` });
      await page.setViewportSize({ width: w, height: h });
      if (w > 600) await panel(page).getByRole("button", { name: "Back to table" }).click();
    }
  }
});

// The panel's blocks, top to bottom: a region's name, else "own" (this
// level's fields) or "foot" (the quieter things last).
const blocks = (page) => panel(page).locator(".rw-pbody > *").evaluateAll((els) => els.map((el) => (
  el.getAttribute("aria-label") || (el.classList.contains("rw-own") ? "own" : el.classList.contains("rw-foot") ? "foot" : el.className))));

// The notes and rationale come first at every level: after the title and the status chips,
// before every block of the body (so none of the body's blocks is the notes).
const notesFirst = (page) => panel(page).evaluate((el) => {
  const after = (a, b) => !!(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);
  const h = el.querySelector("h2");
  const n = el.querySelector('section[aria-label="Notes and rationale"]');
  const chips = el.querySelector(".rw-chips-row");
  const body = el.querySelector(".rw-pbody");
  return !!(h && n && body && after(h, n) && after(n, body) && (!chips || after(chips, n))
    && !body.querySelector('section[aria-label="Notes and rationale"]'));
});

// Notes and rationale with none written: only its heading and one quiet "+ Add notes" at its
// right (no prompt sentence, no dashed add row).
const notesQuiet = async (page) => {
  const notes = panel(page).getByRole("region", { name: "Notes and rationale" });
  await expect(notes.locator(".psec-head").getByRole("button", { name: "Add notes" })).toBeVisible();
  await expect(notes.locator(".add-row")).toHaveCount(0);
  await expect(notes.locator(".rw-notes-prompt, .td-quiet")).toHaveCount(0);
  await expect(notes).not.toContainText(/Why th(is|ese)/);
  // Nothing else in it but a function's PDFs (its own row, "Attach a PDF…").
  await expect(notes).toHaveText(/^\s*Notes and rationale\s*Add notes\s*(Attach a PDF…)?\s*$/);
};

test("one order at every level: its notes under the title and chips, what's inside it, then its own, the quieter things last", async ({ page, request, problems }) => {
  const tag = `b${Date.now()}`;
  const p = await plant(request, tag);
  for (const w of [1280, 400]) {
    await page.setViewportSize({ width: w, height: 860 });
    await open(page, url(p));
    const show = async (name) => {
      const row = trow(page, name);
      if (w > 600) await row.locator(".tp-nm").click();
      else {
        if (await panel(page).count()) await panel(page).getByRole("button", { name: "Close the details" }).click();
        await row.getByRole("button", { name: "Actions", exact: true }).click();
        await page.getByRole("menuitem", { name: "Open…" }).click();
      }
    };
    await show(`^Function: Pump water ${tag}`);
    await expect(panel(page).getByRole("heading", { level: 2, name: `Pump water ${tag}` })).toBeVisible();
    expect(await blocks(page)).toEqual(["Performance standards", "Functional failures"]); // the working is in the notes
    expect(await notesFirst(page)).toBe(true);
    await notesQuiet(page);
    await show(`^Performance standard: At 3 bar ${tag}`);
    await expect(panel(page).getByRole("heading", { level: 2, name: `At 3 bar ${tag}` })).toBeVisible();
    expect(await blocks(page)).toEqual(["Functional failures", "foot"]);
    expect(await notesFirst(page)).toBe(true);
    await notesQuiet(page);
    await show(`^Functional failure: No flow ${tag}`);
    await expect(panel(page).getByRole("heading", { level: 2, name: `No flow ${tag}` })).toBeVisible();
    expect(await blocks(page)).toEqual(["Failure modes", "Caused by", "Causes"]);
    expect(await notesFirst(page)).toBe(true);
    await notesQuiet(page);
    // Its state in words heads its failure modes, said once.
    await expect(panel(page).getByRole("region", { name: "Failure modes" })).toContainText("1 of its 2 failure modes still needs a decision.");
    await show(`^Failure mode: Seal leaks ${tag}`);
    await expect(panel(page).getByRole("heading", { level: 2, name: `Seal leaks ${tag}` })).toBeVisible();
    // The FME(C)A's groups (scores, criticality) are on its own tab, not this one. Its three steps,
    // each a region, then its rationale, together one grid: what happens, how bad, what we do, why.
    // On a failure mode the notes and rationale are the grid's foot (Derryn, 9 Nov 2026), "Based
    // on:" its evidence first; no separate Evidence row.
    expect(await blocks(page)).toEqual(["Failure effects", "Failure consequences", "Proactive task or default action", "Rationale"]);
    expect(await notesFirst(page)).toBe(false);
    const rationale = panel(page).getByRole("region", { name: "Rationale" });
    const modeNotes = rationale.getByRole("region", { name: "Notes and rationale" });
    await expect(modeNotes.getByRole("group", { name: "Evidence" })).toContainText("Based on:");
    await expect(modeNotes.getByRole("group", { name: "Evidence" })).toContainText("None linked");
    await expect(modeNotes.getByRole("button", { name: "+ Add notes" })).toBeVisible();
    // One grid, "step | choice": a row per question, the step's name on the left (Derryn, 9 Nov 2026).
    await expect(panel(page).locator(".rw-sl")).toHaveText(["1 · Failure effects", "2 · Hidden failure?", "Consequence", "3 · Task worth doing?", "Tasks", "Rationale"]);
    await expect(panel(page).locator(".psec-title", { hasText: /Failure effects|Failure consequences|Proactive task/ })).toHaveCount(0);
    // Step 1 is the effects box alone: the step's title is its label (the box's name, not shown again).
    await expect(panel(page).getByRole("region", { name: "Failure effects" }).getByRole("textbox", { name: /^Failure effects/ })).toBeVisible();
    await expect(panel(page).getByRole("region", { name: "Failure effects" }).locator(".field-head")).toHaveClass(/sr-only/);
    // Step 2: the two chip rows, no help sentences (those are in the Decide dialog).
    const howBad = panel(page).getByRole("region", { name: "Failure consequences" });
    await expect(howBad.getByRole("radiogroup")).toHaveCount(2);
    await expect(howBad.locator(".field-help")).toHaveCount(0);
    // Step 3, in place, top to bottom: the chip row (the decision, chosen), its tasks as a plain list
    // (each a link to the task's row in the tree: name · kind · interval; no cards), the dashed add
    // row (a redesign may sit beside one task), then the evidence, open. No decision notes box: the
    // mode's notes and rationale are the one place. No ⋯, no Change….
    const todo = panel(page).getByRole("region", { name: "Proactive task or default action" });
    await expect(todo.locator(".rim-step")).toHaveCount(1);
    await expect(todo.getByRole("radiogroup", { name: "Which task is worth doing?" }).getByRole("radio", { name: /Task\(s\) worth doing/ }))
      .toHaveAttribute("aria-checked", "true");
    // Each task with its own kind, a small chip that changes it.
    const taskLines = todo.getByRole("list", { name: "The decision's tasks" }).getByRole("listitem");
    await expect(taskLines).toHaveCount(2);
    await expect(taskLines.nth(0)).toContainText(`Check the seal ${tag}`);
    await expect(taskLines.nth(0)).toContainText("every 1 month");
    await expect(todo.getByRole("combobox", { name: `Kind of “Check the seal ${tag}”` })).toHaveValue("on_condition");
    await expect(todo.getByRole("combobox", { name: `Kind of “Replace the seal ${tag}”` })).toHaveValue("fixed_interval");
    await expect(todo.locator(".rim-cards")).toHaveCount(0);
    await expect(todo.getByRole("textbox", { name: "Then, if found:" })).toHaveCount(0); // in the task's own details
    await expect(todo.locator(".task-choice")).not.toContainText("On condition: a check at an interval"); // no bridge line
    await expect(todo.getByRole("button", { name: /^Edit “|^Remove “/ })).toHaveCount(0);
    await expect(todo.getByRole("button", { name: /^Change…$|^Actions for/ })).toHaveCount(0);
    await expect(todo.getByRole("button", { name: "Add a task", exact: true })).toBeVisible();
    await expect(todo.getByRole("textbox", { name: /^Decision notes/ })).toHaveCount(0);
    await expect(todo.getByRole("group", { name: "Evidence" })).toHaveCount(0); // in the Rationale row
    expect(await todo.evaluate((el) => {
      const at = (sel) => [...el.querySelectorAll("*")].indexOf(el.querySelector(sel));
      return [at(".task-choice"), at(".rim-tasklist"), at(".rim-addrow")].every((v, i, a) => v >= 0 && (i === 0 || v > a[i - 1]));
    })).toBe(true);
    const labels = await panel(page).locator(".rw-pbody .field-label").allInnerTexts();
    const at = (t) => labels.findIndex((x) => x.startsWith(t));
    // No "Under" field: where a mode sits is the breadcrumb, moved by drag or the row menu.
    expect(at("Under")).toBe(-1);
    expect(await overflow(page)).toBe(0);
    // A task (the fifth level): its row picked from the list; no notes of its own, then its sections
    // in one order: what it is and how often, what's done when found, instructions, evidence, what it
    // serves, logistics; Retire (or Remove) at its foot.
    await todo.getByRole("button", { name: `Check the seal ${tag}`, exact: true }).click();
    await expect(panel(page).getByRole("heading", { level: 2, name: `Check the seal ${tag}` })).toBeVisible();
    await expect(panel(page).locator(".rw-panel-kind")).toHaveText("Task");
    expect(await blocks(page)).toEqual(["Kind and interval", "Then, if found", "Instructions", "Evidence for this task", "Serves", "Logistics"]);
    await expect(panel(page).getByRole("region", { name: "Notes and rationale" })).toHaveCount(0);
    await expect(panel(page).getByRole("region", { name: "Then, if found" }).getByRole("textbox", { name: "Then, if found:" })).toBeVisible();
    await expect(panel(page).getByRole("button", { name: "Retire the task", exact: true })).toBeVisible();
    expect(await overflow(page)).toBe(0);
  }
  await expectHealthy(page, problems, { label: "rcm panel order" });
});

// The shared form pieces (components/ui): a field says "✓ Saved" by its label
// and keeps a refused value with the reason under it (wired to the box); the
// consequence chips work from the keyboard; ⋯ opens from the keyboard; a
// limit reads back in words; a refused table cell keeps its text with the
// whole reason in a bubble under it, not a toast.
test("fields, chips, ⋯ and refusals: kept where you typed, the reason beside it", async ({ page, request, problems }) => {
  const tag = `u${Date.now()}`;
  const p = await plant(request, tag);
  await page.setViewportSize({ width: 1280, height: 900 });
  await open(page, url(p));
  await trow(page, `^Failure mode: Seal leaks ${tag}`).locator(".tp-nm").click();
  const effects = panel(page).getByRole("textbox", { name: /^Failure effects/ });
  // Its field (the label, the box, the line under it).
  const effectsField = panel(page).locator(".field").filter({ has: page.getByRole("textbox", { name: /^Failure effects/ }) });
  await effects.fill("Water on the floor");
  await effects.blur();
  // "✓ Saved" by the step's title (the field's own label is the step's).
  await expect(panel(page).getByRole("region", { name: "Failure effects" }).getByRole("status")).toHaveText("✓ Saved");

  // Refused by the server: the text stays, the reason under it, the box marked and described by it.
  await page.route(/\/api\/maintenance\/failure-modes\/[^/]+$/, (route) => (route.request().method() === "PATCH"
    ? route.fulfill({ status: 422, contentType: "application/json", body: JSON.stringify({ detail: "Refused in this test: nothing was changed." }) })
    : route.continue()));
  await effects.fill("Water everywhere");
  await effects.blur();
  const why = effectsField.getByRole("alert");
  await expect(why).toContainText("Refused in this test");
  await expect(effects).toHaveValue("Water everywhere");
  await expect(effects).toHaveAttribute("aria-invalid", "true");
  expect(await effects.getAttribute("aria-describedby")).toBe(await why.getAttribute("id"));

  // A refused cell: its text kept, the whole reason under it, no error toast.
  const cell = trow(page, `^Failure mode: Seal leaks ${tag}`).locator(".rw-c").first();
  await cell.dblclick();
  const box = table(page).getByRole("textbox", { name: /^Failure effects of/ });
  await box.fill("Puddles");
  await box.press("Enter");
  await expect(page.locator(".rw-pop-under").getByRole("alert")).toContainText("Refused in this test: nothing was changed.");
  await expect(box).toHaveValue("Puddles");
  await expect(box).toHaveAttribute("aria-invalid", "true");
  await box.press("Escape");
  await expect(page.locator(".rw-pop-under")).toHaveCount(0);
  await page.unroute(/\/api\/maintenance\/failure-modes\/[^/]+$/);

  // Consequence chips by keyboard: Tab lands on the chosen one, → chooses the next.
  const chips = panel(page).getByRole("radiogroup", { name: "Consequence category" });
  await chips.getByRole("radio", { name: "Operational", exact: true }).focus();
  await page.keyboard.press("ArrowRight");
  await expect(chips.getByRole("radio", { name: "Non-operational" })).toHaveAttribute("aria-checked", "true");
  await expect(chips.getByRole("radio", { name: "Non-operational" })).toBeFocused();
  await expect.poll(async () => (await rcmOf(request, p)).functions[0].failures[0].modes.find((m) => m.id === p.seal.id).consequence)
    .toBe("non_operational");

  // Step 3's chips by keyboard: Tab lands on the chosen one; an arrow only moves (each choice is saved,
  // so Enter or Space chooses), nothing sent. Each task is a link to its own row (where it's changed).
  const step3 = panel(page).getByRole("region", { name: "Proactive task or default action" });
  const which = step3.getByRole("radiogroup", { name: "Which task is worth doing?" });
  let decisionPuts = 0;
  page.on("request", (q) => { if (q.method() === "PUT" && q.url().includes(`/failure-modes/${p.seal.id}/decision`)) decisionPuts += 1; });
  await which.getByRole("radio", { name: /Task\(s\) worth doing/ }).focus();
  await page.keyboard.press("ArrowRight");
  await expect(which.getByRole("radio", { name: /No task is worth doing/ })).toBeFocused();
  await expect(which.getByRole("radio", { name: /No task is worth doing/ })).toHaveAttribute("aria-checked", "false");
  await expect(which.getByRole("radio", { name: /Task\(s\) worth doing/ })).toHaveAttribute("aria-checked", "true");
  await page.waitForTimeout(300);
  expect(decisionPuts).toBe(0);
  await expect(step3.getByRole("list", { name: "The decision's tasks" }).getByRole("button", { name: `Replace the seal ${tag}`, exact: true })).toBeVisible();

  // A standard's limit: comparator, value and unit as one group, read back in words.
  await trow(page, `^Performance standard: At 3 bar ${tag}`).locator(".tp-nm").click();
  await panel(page).getByRole("button", { name: "Edit the checkable limit" }).click();
  await expect(panel(page).getByRole("group", { name: "Limit" }).getByRole("combobox", { name: "Comparator" })).toHaveValue(">=");
  await expect(panel(page).locator(".reads-as")).toHaveText("Reads as: Pressure at least 3 bar");
  // A consequence cell: one tap on a chip under it; Escape drops it.
  const conseq = trow(page, `^Failure mode: Seal leaks ${tag}`).locator(".rw-c").filter({ hasText: "Non-operational" }).first();
  await conseq.dblclick();
  const pop = page.locator(".rw-pop-under").getByRole("radiogroup");
  await expect(pop.getByRole("radio", { name: "Non-operational" })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(pop).toHaveCount(0);
  await conseq.dblclick();
  await pop.getByRole("radio", { name: "Safety" }).click();
  await expect(pop).toHaveCount(0);
  await expect.poll(async () => (await rcmOf(request, p)).functions[0].failures[0].modes.find((m) => m.id === p.seal.id).consequence)
    .toBe("safety");
  expect(await overflow(page)).toBe(0);
  // The refusals above were this test's own 422s (the browser logs each one).
  problems.splice(0, problems.length, ...problems.filter((x) => !/status of 422/.test(x)));
  await expectHealthy(page, problems, { label: "rcm shared fields", root: ".tx" });
});
