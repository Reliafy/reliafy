// The one details panel on the Explorer's RCM tab (Operate › Assets ›
// Explorer › RCM). A click on a row shows its details beside the table; a
// double-click on its name (not on a data cell, which edits in place, nor the
// chevron), Open… first in its row menu, or Expand in the panel spreads them
// across the table, the tree column kept on the left: another row picked there
// shows in the panel. Back to table and Esc return; the focus goes into the
// heading and back to the row. Everything the old dialog had is here, kept as
// you go: a function's performance standards and working, a standard's limit
// fields, a failure's status, links and failure modes, a failure mode's
// decision and its several tasks. At 400 px it is the sheet and nothing
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
  await expect(fnPanel.getByRole("textbox", { name: /^Description/ })).toHaveValue(`Pump water ${tag}`);
  const list = fnPanel.getByRole("region", { name: "Performance standards" });
  await expect(list).toContainText(`At least 10 L/s ${tag}`);
  await expect(list).toContainText(`At 3 bar ${tag}`);
  await expect(fnPanel.getByRole("button", { name: "Add a working…" })).toBeVisible();
  await expect(fnPanel.getByRole("region", { name: "Functional failures" }).getByRole("button", { name: `No flow ${tag}` })).toBeVisible();

  // Another row picked in the tree: the panel shows it, still across the table.
  await stdRow.locator(".tp-nm").click();
  await expect(panel(page).getByRole("heading", { name: `At 3 bar ${tag}` })).toBeVisible();
  expect(await isExpanded(page)).toBe(true);
  // A standard's limit fields, each kept as you leave it.
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
  await expect(panel(page).getByRole("region", { name: "Caused by, on positions below" })).toBeVisible();
  await expect(panel(page).getByRole("region", { name: "Causes, on positions above" })).toBeVisible();
  await panel(page).getByRole("region", { name: "Failure modes" }).getByRole("button", { name: `Bearing seizes ${tag}` }).click();
  await expect(panel(page).getByRole("heading", { name: `Bearing seizes ${tag}` })).toBeVisible();
  expect(await isExpanded(page)).toBe(true);

  // A failure mode: kept as you go; a refused value stays with its reason and nothing is sent.
  let writes = 0;
  page.on("request", (r) => { if (r.method() !== "GET" && r.url().includes(`/failure-modes/${p.mode.id}`)) writes += 1; });
  const desc = panel(page).getByRole("textbox", { name: /^Description/ });
  await desc.fill("   ");
  await desc.blur();
  await expect(panel(page).getByRole("alert")).toHaveText("Every failure mode needs a description.");
  expect(writes).toBe(0);
  await desc.fill(`Bearing seizes early ${tag}`);
  await desc.blur();
  await panel(page).getByRole("textbox", { name: /^Failure effects/ }).fill("Pump stops; no flow to the tank");
  await panel(page).getByRole("textbox", { name: /^Failure effects/ }).blur();
  await panel(page).getByRole("combobox", { name: "Consequence" }).selectOption("hidden");
  await expect.poll(async () => {
    const m = (await rcmOf(request, p)).functions[0].failures[0].modes.find((x) => x.id === p.mode.id);
    return [m.text, m.effects, m.consequence];
  }).toEqual([`Bearing seizes early ${tag}`, "Pump stops; no flow to the tank", "hidden"]);
  await expect(panel(page).getByRole("region", { name: "Decision" })).toContainText("No decision yet.");
  await expect(panel(page).getByRole("region", { name: "Tasks" })).toBeVisible();
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

  // Add a task…: across the table, on the add form, its name box focused; the two tasks listed.
  await sealRow.locator(".tp-nm").click({ button: "right" });
  await page.getByRole("menuitem", { name: "Add a task…" }).click();
  const tasks = panel(page).getByRole("region", { name: "Tasks" });
  await expect(tasks.getByRole("textbox", { name: "Task" })).toBeFocused();
  expect(await isExpanded(page)).toBe(true);
  await expect(tasks.getByRole("listitem")).toHaveCount(2);
  await tasks.getByRole("button", { name: "Cancel" }).click();
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
  await standards.getByRole("button", { name: `Edit At 3 bar ${tag}` }).click();
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
    if (w > 600) await fnRow.locator(".tp-nm").dblclick();
    else {
      await page.getByRole("button", { name: "Close the details" }).click();
      await fnRow.getByRole("button", { name: "Actions", exact: true }).click();
      await page.getByRole("menuitem", { name: "Open…" }).click();
    }
    await settled(page);
    await page.screenshot({ path: `${SHOTS}/rcm-panel-function-${w}.png` });
    if (w > 600) await sealRow.locator(".tp-nm").click();
    else {
      await page.getByRole("button", { name: "Close the details" }).click();
      await sealRow.getByRole("button", { name: "Actions", exact: true }).click();
      await page.getByRole("menuitem", { name: "Open…" }).click();
    }
    await settled(page);
    await page.screenshot({ path: `${SHOTS}/rcm-panel-mode-${w}.png` });
  }
});
