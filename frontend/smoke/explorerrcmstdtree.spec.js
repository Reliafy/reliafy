// Performance standards as a level of the RCM tree, on the Explorer's RCM tab
// (Operate › Assets › Explorer › RCM): position › function › standard ›
// functional failure › failure mode. Each standard is a row under its
// function, the functional failures that breach it nested under it; the ones
// that breach none sit under a muted "No standard" row; a function's one
// text (no list) shows as one standard row with every failure under it; a
// function with no standard has its failures right under it. The row menus
// add a standard, add a failure under a standard, change a failure's
// standard, move a standard up or down, edit its text in place and remove it
// (its failures go back to the function); double-click opens the Standard
// dialog with its limit fields. Switching tabs moves nothing in the frame.
// At 400 px it all fits. Each test makes its own small plant through the API
// and pins it (?pin=), so its rows start at the top of the tree whatever else
// the shared workspace holds (rows below the fold aren't drawn).
//
// With SMOKE_SHOTS_DIR set, it also saves screenshots at 1280 and 400 px: the
// sample truck, and a function with three standards (for the pull request).
import { test, expect, open, expectHealthy, postOk } from "./health.js";
import { frameOf, movedBetween } from "./explorer.js";

const M = "/api/maintenance";
const SHOTS = process.env.SMOKE_SHOTS_DIR || "";

// A pool with three functions: one with a list of three standards (two
// failures breach the first, one breaches none), one with its one text (no
// list) and one failure, one with no standard and one failure.
async function plant(request, tag) {
  const post = (path, data) => postOk(request, path, data);
  const pool = await post(`${M}/positions`, { name: `Std tree pool ${tag}` });
  const balance = await post(`${M}/positions/${pool.id}/functions`, { text: `Keep the water balanced ${tag}`, standard: `pH 7.2-7.8 ${tag}` });
  // A second standard turns the one text into the list's first item; a third with its limit.
  await post(`${M}/functions/${balance.id}/standards`, { text: `Total alkalinity 80-120 ppm ${tag}` });
  await post(`${M}/functions/${balance.id}/standards`, {
    text: `Calcium hardness 200-400 ppm ${tag}`, parameter: "Calcium hardness", comparator: "between", value: "200-400", unit: "ppm", source: "E25 manual",
  });
  const fn = await (await request.get(`${M}/functions/${balance.id}`)).json();
  const [ph, ta, ca] = fn.standards;
  const high = await post(`${M}/functions/${balance.id}/failures`, { text: `pH above 7.8 ${tag}`, standard_id: ph.id });
  const low = await post(`${M}/functions/${balance.id}/failures`, { text: `pH below 7.2 ${tag}`, standard_id: ph.id });
  const scale = await post(`${M}/functions/${balance.id}/failures`, { text: `Water scale-forming ${tag}` });
  await post(`${M}/positions/${pool.id}/failure-modes`, { text: `Acid under-dosed ${tag}`, functional_failure_id: high.id });
  await post(`${M}/positions/${pool.id}/failure-modes`, { text: `Acid over-dosed ${tag}`, functional_failure_id: low.id });
  await post(`${M}/positions/${pool.id}/failure-modes`, { text: `Hardness too high ${tag}`, functional_failure_id: scale.id });
  const sanitise = await post(`${M}/positions/${pool.id}/functions`, { text: `Keep the water sanitised ${tag}`, standard: `FC 1-3 ppm; CC under 0.5 ppm ${tag}` });
  const fc = await post(`${M}/functions/${sanitise.id}/failures`, { text: `FC below 1 ppm ${tag}` });
  await post(`${M}/positions/${pool.id}/failure-modes`, { text: `Chlorinator cell scaled ${tag}`, functional_failure_id: fc.id });
  const circulate = await post(`${M}/positions/${pool.id}/functions`, { text: `Circulate the water ${tag}` });
  const flow = await post(`${M}/functions/${circulate.id}/failures`, { text: `No flow ${tag}` });
  return { pool, balance, sanitise, circulate, standards: { ph, ta, ca }, failures: { high, low, scale, fc, flow } };
}

const table = (page) => page.getByRole("treegrid", { name: /and their RCM/ });
const trow = (page, name) => table(page).getByRole("row", { name: new RegExp(name) });
const dialog = (page, name) => page.getByRole("dialog", { name, exact: true });
const level = async (row) => Number(await row.getAttribute("aria-level"));
const overflow = (page) => page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
const settled = async (page) => {
  await page.waitForLoadState("networkidle", { timeout: 5_000 }).catch(() => {});
  await page.waitForTimeout(250);
};
// A row's menu, by its ⋯ button (the same as a right-click).
// The row's menu: with the mouse (its ⋯), or from the keyboard (Shift+F10),
// where a wide screen's menu also has the moves a drag does.
async function menuOf(page, row, { keyboard = false } = {}) {
  if (keyboard) {
    await row.locator(".tt-tree").click();
    await row.press("Shift+F10");
  } else {
    await row.hover();
    await row.getByRole("button", { name: "Actions", exact: true }).click();
  }
  const menu = page.getByRole("menu");
  await expect(menu).toBeVisible();
  return menu;
}
const readFn = async (request, id) => (await request.get(`${M}/functions/${id}`)).json();

test("standards are a level of the tree: a list's rows, the 'No standard' row, the one text as one row, none at all", async ({ page, request, problems }) => {
  const tag = `l${Date.now()}`;
  const p = await plant(request, tag);
  await page.setViewportSize({ width: 1280, height: 900 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pool.id}&pin=${p.pool.id}&tab=rcm`);
  await expect(table(page).getByRole("columnheader", { name: "Position › function, standard, failure or mode" })).toBeVisible();
  const fnRow = trow(page, `^Function: Keep the water balanced ${tag}`);
  const ph = trow(page, `^Standard: pH 7.2-7.8 ${tag}`);
  const ta = trow(page, `^Standard: Total alkalinity 80-120 ppm ${tag}`);
  const ca = trow(page, `^Standard: Calcium hardness 200-400 ppm ${tag}`);
  const none = trow(page, `^No standard`).first();
  await expect(fnRow).toBeVisible();
  await expect(ph).toBeVisible();
  await expect(ta).toBeVisible();
  await expect(ca).toBeVisible();
  await expect(none).toBeVisible();
  // Nested: function › standard › functional failure › failure mode.
  const fnLevel = await level(fnRow);
  expect(await level(ph)).toBe(fnLevel + 1);
  expect(await level(ta)).toBe(fnLevel + 1);
  expect(await level(none)).toBe(fnLevel + 1);
  const high = trow(page, `^Functional failure: pH above 7.8 ${tag}`);
  const scale = trow(page, `^Functional failure: Water scale-forming ${tag}`);
  await expect(high).toBeVisible();
  await expect(scale).toBeVisible();
  expect(await level(high)).toBe(fnLevel + 2);
  expect(await level(scale)).toBe(fnLevel + 2);
  expect(await level(trow(page, `^Failure mode: Acid under-dosed ${tag}`))).toBe(fnLevel + 3);
  expect(await level(trow(page, `^Failure mode: Hardness too high ${tag}`))).toBe(fnLevel + 3);
  // In order: the standards, then "No standard" with the loose failure under it.
  const order = await table(page).getByRole("row").evaluateAll((rows) => rows.map((r) => r.textContent || ""));
  const at = (text) => order.findIndex((t) => t.includes(text));
  expect(at(`pH 7.2-7.8 ${tag}`)).toBeLessThan(at(`pH above 7.8 ${tag}`));
  expect(at(`pH above 7.8 ${tag}`)).toBeLessThan(at(`Total alkalinity 80-120 ppm ${tag}`));
  expect(at(`Calcium hardness 200-400 ppm ${tag}`)).toBeLessThan(at("No standard"));
  expect(at("No standard")).toBeLessThan(at(`Water scale-forming ${tag}`));
  // The quiet marker on a standard with no functional failure, and nothing on one with.
  await expect(ta.getByText("no failure yet")).toBeVisible();
  await expect(ca.getByText("no failure yet")).toBeVisible();
  await expect(ph.getByText("no failure yet")).toHaveCount(0);
  // The one text: one standard row with its failure under it, and no "No standard" row for it.
  const legacy = trow(page, `^Standard: FC 1-3 ppm; CC under 0.5 ppm ${tag}`);
  await expect(legacy).toBeVisible();
  expect(await level(legacy)).toBe(fnLevel + 1);
  expect(await level(trow(page, `^Functional failure: FC below 1 ppm ${tag}`))).toBe(fnLevel + 2);
  await expect(legacy.getByText("no failure yet")).toHaveCount(0);
  await expect(trow(page, `^No standard`)).toHaveCount(1);
  // No standard at all: the failure right under the function.
  expect(await level(trow(page, `^Functional failure: No flow ${tag}`))).toBe(fnLevel + 1);
  // The standard column (from the Columns menu): the limit in words on the standard's row.
  await page.getByRole("button", { name: "Columns" }).click();
  await page.getByRole("checkbox", { name: /Performance standard/ }).check();
  await page.keyboard.press("Escape");
  await expect(ca).toContainText("Calcium hardness between 200-400 ppm · E25 manual");
  // The level control and the filter reach the standards.
  await page.getByRole("button", { name: /^Tree options/ }).click();
  await page.getByRole("menuitemradio", { name: "Open to level 2" }).click();
  await page.keyboard.press("Escape");
  await expect(ph).toHaveCount(0);
  await fnRow.locator(".tp-chev").click();
  await expect(ph).toBeVisible();
  await expect(high).toHaveCount(0); // the standard is closed
  await ph.locator(".tp-chev").click();
  await expect(high).toBeVisible();
  // The filter reaches a standard's source (its function matches too, so its
  // whole list shows), and a failure under "No standard" keeps the way down to it.
  await page.getByRole("searchbox", { name: "Filter the tree and its RCM" }).fill("E25 manual");
  await expect(ca).toBeVisible();
  await expect(trow(page, `^Functional failure: No flow ${tag}`)).toHaveCount(0);
  await page.getByRole("searchbox", { name: "Filter the tree and its RCM" }).fill("scale-forming");
  await expect(scale).toBeVisible();
  await expect(none).toBeVisible();
  await expect(ph).toHaveCount(0);
  await page.getByRole("searchbox", { name: "Filter the tree and its RCM" }).fill("");
  await expect(ph).toBeVisible();
  // Switching tabs moves nothing in the frame (the position picked stays put); the rows come back.
  const pool = trow(page, `^Std tree pool ${tag}`);
  await pool.locator(".tt-tree").click();
  await settled(page);
  const before = await frameOf(page);
  await page.getByRole("tab", { name: "Summary" }).click();
  await expect(page.getByRole("tree", { name: "Positions" })).toBeVisible();
  await expect(ph).toHaveCount(0);
  await page.getByRole("tab", { name: "RCM" }).click();
  await expect(ph).toBeVisible();
  await settled(page);
  const after = await frameOf(page);
  expect(movedBetween(before, after)).toEqual([]);
  await expect(pool).toHaveAttribute("aria-selected", "true");
  await expectHealthy(page, problems, { label: "rcm standards tree" });
});

test("row menus: add a standard, a failure under it, change a failure's standard, move, edit in place, remove", async ({ page, request, problems }) => {
  const tag = `m${Date.now()}`;
  const p = await plant(request, tag);
  await page.setViewportSize({ width: 1280, height: 900 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pool.id}&pin=${p.pool.id}&tab=rcm`);
  const circulate = trow(page, `^Function: Circulate the water ${tag}`);
  const flow = trow(page, `^Functional failure: No flow ${tag}`);
  await expect(flow).toBeVisible();

  // A function's menu: Add a standard… (the first standard; its loose failure stays on show, under "No standard").
  let menu = await menuOf(page, circulate);
  // With the mouse there are no moves (a drag does them); Isolate › before Delete.
  await expect(menu.getByRole("menuitem")).toHaveText(["Open…", "Add a standard…", "Add functional failure", "Edit description", "Isolate", "Delete function"]);
  await menu.getByRole("menuitem", { name: "Add a standard…" }).click();
  const ask = page.getByRole("dialog", { name: "Add a performance standard" });
  await ask.getByRole("textbox").fill(`At least 50 L/s ${tag}`);
  await ask.getByRole("button", { name: "Add standard" }).click();
  const fifty = trow(page, `^Standard: At least 50 L/s ${tag}`);
  await expect(fifty).toBeVisible();
  await expect(fifty).toHaveAttribute("aria-selected", "true");
  expect(await level(fifty)).toBe((await level(circulate)) + 1);
  await expect(flow).toBeVisible();
  expect(await level(flow)).toBe((await level(circulate)) + 2); // now under "No standard"
  await expect(trow(page, `^No standard`)).toHaveCount(2);
  await expect(fifty.getByText("no failure yet")).toBeVisible();

  // A standard's menu: Add a functional failure… (it breaches this standard).
  menu = await menuOf(page, fifty);
  await expect(menu.getByRole("menuitem")).toHaveText(["Open…", "Edit text", "Add a functional failure…", "Isolate", "Remove standard"]);
  await page.keyboard.press("Escape");
  // From the keyboard: the moves too.
  menu = await menuOf(page, fifty, { keyboard: true });
  await expect(menu.getByRole("menuitem")).toHaveText(["Open…", "Edit text", "Add a functional failure…", "Move up", "Move down", "Move to another function…", "Isolate", "Remove standard"]);
  await expect(menu.getByRole("menuitem", { name: "Move up" })).toHaveAttribute("aria-disabled", "true"); // the only one
  await menu.getByRole("menuitem", { name: "Add a functional failure…" }).click();
  const askFail = page.getByRole("dialog", { name: "Add a functional failure" });
  await expect(askFail.getByText("How does it fail to meet this standard?")).toBeVisible();
  await askFail.getByRole("textbox").fill(`Low flow ${tag}`);
  await askFail.getByRole("button", { name: "Add functional failure" }).click();
  const lowFlow = trow(page, `^Functional failure: Low flow ${tag}`);
  await expect(lowFlow).toBeVisible();
  expect(await level(lowFlow)).toBe((await level(fifty)) + 1);
  await expect(fifty.getByText("no failure yet")).toHaveCount(0);
  let fn = await readFn(request, p.circulate.id);
  expect(fn.failures.map((f) => [f.text, f.standard?.text || null])).toEqual([[`No flow ${tag}`, null], [`Low flow ${tag}`, `At least 50 L/s ${tag}`]]);

  // A failure's menu: Change standard… (it moves under the standard; the "No standard" row goes).
  menu = await menuOf(page, flow);
  await menu.getByRole("menuitem", { name: "Change standard…" }).click();
  const pick = page.getByRole("dialog", { name: "Which standard does it breach?" });
  await expect(pick.getByRole("combobox", { name: "Breaches" })).toHaveValue("");
  await pick.getByRole("combobox", { name: "Breaches" }).selectOption({ label: `At least 50 L/s ${tag}` });
  await pick.getByRole("button", { name: "Save" }).click();
  await expect(pick).toHaveCount(0);
  await expect(flow).toBeVisible();
  expect(await level(flow)).toBe((await level(fifty)) + 1);
  await expect(trow(page, `^No standard`)).toHaveCount(1);
  fn = await readFn(request, p.circulate.id);
  expect(fn.failures.find((f) => f.id === p.failures.flow.id).standard.text).toBe(`At least 50 L/s ${tag}`);

  // Move down: the list's order changes, in the tree and on the server.
  const ph = trow(page, `^Standard: pH 7.2-7.8 ${tag}`);
  const ta = trow(page, `^Standard: Total alkalinity 80-120 ppm ${tag}`);
  menu = await menuOf(page, ph, { keyboard: true });
  await menu.getByRole("menuitem", { name: "Move down" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Moved." })).toBeVisible();
  fn = await readFn(request, p.balance.id);
  expect(fn.standards.map((st) => st.text)).toEqual([`Total alkalinity 80-120 ppm ${tag}`, `pH 7.2-7.8 ${tag}`, `Calcium hardness 200-400 ppm ${tag}`]);
  expect((await ta.boundingBox()).y).toBeLessThan((await ph.boundingBox()).y);
  await expect(trow(page, `^Functional failure: pH above 7.8 ${tag}`)).toBeVisible(); // its failures came with it

  // Edit text in place: the cell editor in the tree column.
  menu = await menuOf(page, ta);
  await menu.getByRole("menuitem", { name: "Edit text" }).click();
  const box = table(page).getByRole("textbox").first();
  await expect(box).toHaveValue(`Total alkalinity 80-120 ppm ${tag}`);
  await box.fill(`Total alkalinity 80-110 ppm ${tag}`);
  await box.press("Enter");
  await expect(trow(page, `^Standard: Total alkalinity 80-110 ppm ${tag}`)).toBeVisible();
  fn = await readFn(request, p.balance.id);
  expect(fn.standards[0].text).toBe(`Total alkalinity 80-110 ppm ${tag}`);

  // Remove: asked first, saying where its failures go; they move under "No standard".
  menu = await menuOf(page, ph);
  await menu.getByRole("menuitem", { name: "Remove standard" }).click();
  const confirm = page.getByRole("alertdialog", { name: "Remove this standard?" });
  await expect(confirm).toContainText("Its 2 functional failures move to the function with no standard (they breach the whole function), with their failure modes.");
  await confirm.getByRole("button", { name: "Remove standard" }).click();
  await expect(ph).toHaveCount(0);
  const high = trow(page, `^Functional failure: pH above 7.8 ${tag}`);
  await expect(high).toBeVisible();
  expect(await level(high)).toBe((await level(trow(page, `^Function: Keep the water balanced ${tag}`))) + 2);
  fn = await readFn(request, p.balance.id);
  expect(fn.standards.length).toBe(2);
  expect(fn.failures.every((f) => f.standard === null)).toBe(true);
  // The one text's row: Edit text changes the function's text; Remove clears it; no event for a standard.
  const legacy = trow(page, `^Standard: FC 1-3 ppm; CC under 0.5 ppm ${tag}`);
  menu = await menuOf(page, legacy);
  await expect(menu.getByRole("menuitem")).toHaveText(["Open…", "Edit text", "Add a functional failure…", "Isolate", "Remove standard"]);
  await menu.getByRole("menuitem", { name: "Remove standard" }).click();
  const confirm2 = page.getByRole("alertdialog", { name: "Remove this standard?" });
  await expect(confirm2).toContainText("is cleared from this function. Its functional failures stay on the function");
  await confirm2.getByRole("button", { name: "Remove standard" }).click();
  await expect(legacy).toHaveCount(0);
  const fc = trow(page, `^Functional failure: FC below 1 ppm ${tag}`);
  await expect(fc).toBeVisible();
  expect(await level(fc)).toBe((await level(trow(page, `^Function: Keep the water sanitised ${tag}`))) + 1);
  fn = await readFn(request, p.sanitise.id);
  expect([fn.standard, fn.standards]).toEqual(["", []]);
  await expectHealthy(page, problems, { label: "rcm standards tree menus" });
});

test("double-click opens the Standard dialog: text, limit fields and its failures; the one text's dialog saves the function's text", async ({ page, request, problems }) => {
  const tag = `d${Date.now()}`;
  const p = await plant(request, tag);
  await page.setViewportSize({ width: 1280, height: 900 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pool.id}&pin=${p.pool.id}&tab=rcm`);
  const ca = trow(page, `^Standard: Calcium hardness 200-400 ppm ${tag}`);
  await ca.locator(".tp-nm").dblclick();
  const dlg = dialog(page, "Standard");
  await expect(dlg).toBeVisible();
  await expect(dlg.getByText(`On Std tree pool ${tag}`)).toBeVisible();
  await expect(dlg.getByRole("button", { name: `Keep the water balanced ${tag}` })).toBeVisible(); // the way up
  await expect(dlg.getByRole("textbox", { name: /^Standard/ })).toHaveValue(`Calcium hardness 200-400 ppm ${tag}`);
  await expect(dlg.getByRole("textbox", { name: "Parameter" })).toHaveValue("Calcium hardness");
  await expect(dlg.getByRole("combobox", { name: "Comparator" })).toHaveValue("between");
  await expect(dlg.getByRole("textbox", { name: "Value" })).toHaveValue("200-400");
  await expect(dlg.getByRole("textbox", { name: "Unit" })).toHaveValue("ppm");
  await expect(dlg.getByRole("textbox", { name: "Source" })).toHaveValue("E25 manual");
  await expect(dlg.getByRole("region", { name: "Functional failures" })).toContainText("No functional failure written yet");
  // Saved once: one write with the fields that changed.
  await dlg.getByRole("textbox", { name: "When it applies" }).fill("while the pool is in use");
  await dlg.getByRole("textbox", { name: "Value" }).fill("200-350");
  let writes = 0;
  page.on("request", (r) => { if (r.method() === "PATCH" && r.url().includes(`/standards/${p.standards.ca.id}`)) writes += 1; });
  await dlg.getByRole("button", { name: "Save" }).dblclick();
  await expect(dlg).toHaveCount(0);
  expect(writes).toBe(1);
  await expect(ca).toBeFocused();
  let fn = await readFn(request, p.balance.id);
  const saved = fn.standards.find((st) => st.id === p.standards.ca.id);
  expect([saved.value, saved.when, saved.unit]).toEqual(["200-350", "while the pool is in use", "ppm"]);
  // A standard with failures lists them, and one opens from the list.
  await trow(page, `^Standard: pH 7.2-7.8 ${tag}`).locator(".tp-nm").dblclick();
  const dlg2 = dialog(page, "Standard");
  await expect(dlg2.getByRole("region", { name: "Functional failures" }).getByRole("button", { name: `pH above 7.8 ${tag}` })).toBeVisible();
  await dlg2.getByRole("region", { name: "Functional failures" }).getByRole("button", { name: `pH below 7.2 ${tag}` }).click();
  await expect(dialog(page, "Functional failure")).toBeVisible();
  await expect(dialog(page, "Functional failure").getByRole("combobox", { name: "Breaches" })).toHaveValue(p.standards.ph.id);
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  // The function's dialog still lists every functional failure, through the standards.
  await trow(page, `^Function: Keep the water balanced ${tag}`).locator(".tp-nm").dblclick();
  const fdlg = dialog(page, "Function");
  await expect(fdlg.getByRole("region", { name: "Functional failures" }).getByRole("button")).toHaveCount(3);
  await page.keyboard.press("Escape");
  // The one text's dialog: the text alone, a note instead of the limit; Save writes the function's standard.
  await trow(page, `^Standard: FC 1-3 ppm; CC under 0.5 ppm ${tag}`).locator(".tp-nm").dblclick();
  const ldlg = dialog(page, "Standard");
  await expect(ldlg).toBeVisible();
  await expect(ldlg.getByText("This is the function's one standard, as written.")).toBeVisible();
  await expect(ldlg.getByRole("textbox", { name: "Parameter" })).toHaveCount(0);
  await ldlg.getByRole("textbox", { name: /^Standard/ }).fill(`FC 1-3 ppm; CC under 0.4 ppm ${tag}`);
  await ldlg.getByRole("button", { name: "Save" }).click();
  await expect(ldlg).toHaveCount(0);
  await expect(trow(page, `^Standard: FC 1-3 ppm; CC under 0.4 ppm ${tag}`)).toBeVisible();
  fn = await readFn(request, p.sanitise.id);
  expect([fn.standard, fn.standards]).toEqual([`FC 1-3 ppm; CC under 0.4 ppm ${tag}`, []]);
  await expectHealthy(page, problems, { label: "rcm standard dialog" });
});

test("at 400 px the standard rows, their menus and the dialog fit", async ({ page, request, problems }) => {
  const tag = `p${Date.now()}`;
  const p = await plant(request, tag);
  await page.setViewportSize({ width: 400, height: 860 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pool.id}&pin=${p.pool.id}&tab=rcm`);
  const ca = trow(page, `^Standard: Calcium hardness 200-400 ppm ${tag}`);
  await expect(ca).toBeVisible();
  await expect(ca).toContainText("Calcium hardness between 200-400 ppm · E25 manual · No functional failure written yet"); // the phone's second line
  await expect(trow(page, `^Functional failure: pH above 7.8 ${tag}`)).toBeVisible();
  await expect(trow(page, `^No standard`).first()).toBeVisible();
  expect(await overflow(page)).toBe(0);
  // The menu: no in-place edit on a phone (the dialog edits the text); Open… reaches the dialog.
  await ca.getByRole("button", { name: "Actions", exact: true }).click();
  const menu = page.getByRole("menu");
  await expect(menu.getByRole("menuitem")).toHaveText(["Open…", "Add a functional failure…", "Move up", "Move down", "Move to another function…", "Isolate", "Remove standard"]);
  await menu.getByRole("menuitem", { name: "Open…" }).click();
  const dlg = dialog(page, "Standard");
  await expect(dlg).toBeVisible();
  await expect(dlg.getByRole("textbox", { name: "Parameter" })).toBeVisible();
  expect(await overflow(page)).toBe(0);
  const box = await dlg.boundingBox();
  expect(box.x + box.width).toBeLessThanOrEqual(400.5);
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect(await overflow(page)).toBe(0);
  await expectHealthy(page, problems, { label: "rcm standards tree phone" });
});

test("screenshots: the sample truck, and a function with three standards (SMOKE_SHOTS_DIR)", async ({ page, request }) => {
  test.skip(!SHOTS, "only when saving screenshots");
  const tag = "shot";
  const p = await plant(request, tag);
  const truck = await postOk(request, `${M}/sample-truck`, { again: true });
  const truckId = truck.position?.id || truck.id;
  for (const [w, h] of [[1280, 800], [400, 860]]) {
    await page.setViewportSize({ width: w, height: h });
    await open(page, `/asset-register/explorer?arrange=positions&sel=${truckId}&pin=${truckId}&tab=rcm`);
    await expect(trow(page, "^Function: Stop the vehicle").first()).toBeVisible();
    await page.waitForTimeout(300);
    await page.screenshot({ path: `${SHOTS}/rcm-standards-tree-truck-${w}.png` });
    await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pool.id}&pin=${p.pool.id}&tab=rcm`);
    await expect(trow(page, `^Standard: Calcium hardness 200-400 ppm ${tag}`).first()).toBeVisible();
    await page.waitForTimeout(300);
    await page.screenshot({ path: `${SHOTS}/rcm-standards-tree-pool-${w}.png` });
  }
});
