// The Explorer's FME(C)A tab (Operate › Assets › Explorer › FME(C)A): the
// tree and the FMEA worksheet are one table, each position's functions with
// their failure modes right under them and the worksheet's columns beside
// each (cause, effects, S, O, D, RPN, AP, the action); a score edited in
// place changes the RPN and action priority the server sends back; the
// chips; a position picked shows its criticality matrix; the same records
// on the RCM tab, a mode written here under "No functional failure yet"
// until it's assigned; nothing scrolls sideways at 400 px; the print view.
// Each test makes its own small plant through the API.
import { test, expect, open, expectHealthy } from "./health.js";

const M = "/api/maintenance";
const SHOTS = process.env.SMOKE_SHOTS_DIR || "";
const shot = async (page, name) => {
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}.png` });
};

// A plant with one function that has two failure modes directly under it
// (no functional failure) and one under a functional failure, scored.
async function plant(request, tag) {
  const post = async (path, data) => {
    const res = await request.post(path, { data });
    expect(res.ok(), `${path}: ${res.status()} ${await res.text()}`).toBeTruthy();
    return res.json();
  };
  const patch = async (path, data) => {
    const res = await request.patch(path, { data });
    expect(res.ok(), `${path}: ${res.status()} ${await res.text()}`).toBeTruthy();
    return res.json();
  };
  const top = await post(`${M}/positions`, { name: `Fmea plant ${tag}` });
  const pump = await post(`${M}/positions`, { name: `Fmea pump ${tag}`, parent_id: top.id });
  const fn = await post(`${M}/positions/${pump.id}/functions`, { text: `Pump water ${tag}` });
  const direct = await post(`${M}/positions/${pump.id}/failure-modes`, { text: `Bearing seizes ${tag}`, function_id: fn.id });
  const direct2 = await post(`${M}/positions/${pump.id}/failure-modes`, { text: `Seal leaks ${tag}`, function_id: fn.id });
  const ff = await post(`${M}/functions/${fn.id}/failures`, { text: `No flow ${tag}` });
  const under = await post(`${M}/positions/${pump.id}/failure-modes`, { text: `Impeller worn ${tag}`, functional_failure_id: ff.id });
  await patch(`${M}/failure-modes/${direct.id}`, {
    cause: "Dust past the seal", effect_local: "Shaft locks", effect_next: "No flow", effects: "Line stops", detection_method: "Vibration trend",
    severity: 9, occurrence: 4, detection: 6, action: "Fit a sealed bearing", action_owner: "Mech lead", action_due: "2026-12-01", action_status: "open",
    failure_rate: 8e-5, time_unit: "hours", rate_source: "data", mode_ratio: 0.5, loss_probability: 1, operating_time: 100, severity_class: "I",
  });
  await patch(`${M}/failure-modes/${direct2.id}`, { severity: 5, occurrence: 6, detection: 2, cause: "Seal face worn" });
  return { top, pump, fn, ff, direct, direct2, under };
}

const table = (page) => page.getByRole("treegrid", { name: /and their FME\(C\)A/ });
const trow = (page, name) => table(page).getByRole("row", { name: new RegExp(name) });
const pickRow = (page, name) => trow(page, name).locator(".tt-tree, .tt-l1").first().click();
const overflow = (page) => page.evaluate(() => {
  const el = document.documentElement;
  return { down: el.scrollHeight - innerHeight, side: el.scrollWidth - innerWidth };
});
const menuButton = (page) => page.getByRole("button", { name: /^Tree options/ });
const treeMenu = (page) => page.getByRole("menu", { name: "Tree options" });
async function openTreeMenu(page) {
  if (!(await treeMenu(page).isVisible())) await menuButton(page).click();
  await expect(treeMenu(page)).toBeVisible();
  return treeMenu(page);
}
// A cell of a row by its column's header text: the cell at that column's index.
async function cellOf(page, rowName, header) {
  const heads = table(page).getByRole("columnheader");
  const names = await heads.allInnerTexts();
  const i = names.findIndex((n) => n.trim().replace(/[▲▼]$/, "").trim() === header);
  expect(i, `column ${header} among ${names.join(", ")}`).toBeGreaterThan(0);
  return trow(page, rowName).getByRole("gridcell").nth(i - 1);
}

test("FME(C)A: the worksheet on the tree; a score edited in place changes the RPN and AP; the chips; the matrix", async ({ page, request, problems }) => {
  const tag = `f${Date.now()}`;
  const p = await plant(request, tag);
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pump.id}&tab=fmea`);
  await expect(table(page)).toBeVisible();
  await expect(page).toHaveURL(/tab=fmea/);
  // The worksheet's columns, in order (at 1440 px the usual set leaves the local and next
  // higher effects and the owner to the Columns menu); the function's modes right under it
  // (no functional failure level).
  const heads = (await table(page).getByRole("columnheader").allInnerTexts()).map((t) => t.trim());
  expect(heads.slice(0, 13)).toEqual(["Function or failure mode", "Functional failure", "Cause", "End effect", "Detection method", "S", "O", "D", "RPN", "AP",
    "Recommended action", "Due", "Status"]);
  await page.getByRole("button", { name: "Columns" }).click();
  await expect(page.getByRole("group", { name: "Columns to show" }).getByRole("checkbox", { name: "Local effect" })).not.toBeChecked();
  await expect(page.getByRole("group", { name: "Columns to show" }).getByRole("checkbox", { name: "Mode criticality (Cm)" })).not.toBeChecked();
  await page.keyboard.press("Escape");
  const fn = trow(page, `^Function: Pump water ${tag}`);
  await expect(fn).toBeVisible();
  const mode = trow(page, `^Failure mode: Bearing seizes ${tag}`);
  await expect(mode).toBeVisible();
  await expect(trow(page, `^Failure mode: Impeller worn ${tag}`)).toBeVisible();
  await expect(page.getByText(`No flow ${tag}`).first()).toBeVisible(); // the Functional failure column, read-only
  await expect(trow(page, "^Functional failure:")).toHaveCount(0); // not a level of this tree
  // The scored mode: S 9, RPN 216, AP High; the function rolls up.
  await expect(await cellOf(page, `^Failure mode: Bearing seizes ${tag}`, "RPN")).toHaveText("216");
  await expect(await cellOf(page, `^Failure mode: Bearing seizes ${tag}`, "AP")).toHaveText("High");
  await expect(await cellOf(page, `^Function: Pump water ${tag}`, "Cause")).toHaveText("2 of 3 scored");
  await expect(await cellOf(page, `^Function: Pump water ${tag}`, "AP")).toHaveText("1 high · 1 medium");
  await expect(await cellOf(page, `^Function: Pump water ${tag}`, "RPN")).toHaveText("216");
  await shot(page, "fmea-table-1440");
  // Edit S in place: 11 is refused in the server's words; 1 is kept, and the
  // RPN and AP come back changed from the server (9×4×6=216 High → 1×4×6=24 Low).
  // A click picks the row (its details open beside the table, which narrows); then the S cell, brought into view, is double-clicked.
  await pickRow(page, `^Failure mode: Bearing seizes ${tag}`);
  await expect(page.getByRole("complementary", { name: "Details" })).toBeVisible();
  const s = await cellOf(page, `^Failure mode: Bearing seizes ${tag}`, "S");
  await s.scrollIntoViewIfNeeded();
  await s.dblclick();
  const box = page.getByRole("textbox", { name: new RegExp(`^S of Bearing seizes ${tag}`) }).or(page.getByRole("spinbutton", { name: new RegExp(`^S of Bearing seizes ${tag}`) }));
  await expect(box).toBeFocused();
  await box.fill("11");
  await box.press("Enter");
  await expect(page.getByRole("alert")).toContainText("Severity is a whole number from 1");
  await box.fill("1");
  await box.press("Enter");
  await expect(await cellOf(page, `^Failure mode: Bearing seizes ${tag}`, "RPN")).toHaveText("24");
  await expect(await cellOf(page, `^Failure mode: Bearing seizes ${tag}`, "AP")).toHaveText("Low");
  await expect(await cellOf(page, `^Function: Pump water ${tag}`, "AP")).toHaveText("1 medium");
  const saved = await (await request.get(`${M}/positions/${p.pump.id}/rcm?scope=this`)).json();
  const direct = saved.positions[0].functions[0].modes.find((m) => m.id === p.direct.id);
  expect(direct.severity).toBe(1);
  expect(direct.rpn).toBe(24);
  expect(direct.ap).toBe("L");
  // The chips: Medium priority keeps the one medium mode and the way down to it.
  const menu = await openTreeMenu(page);
  await menu.getByRole("menuitemcheckbox", { name: "Medium priority" }).click();
  await expect(menu.getByRole("menuitemcheckbox", { name: "High priority" })).toBeVisible();
  await expect(menu.getByRole("menuitemcheckbox", { name: "Needs a decision" })).toHaveCount(0); // the RCM tab's own
  await page.keyboard.press("Escape");
  await expect(trow(page, `^Failure mode: Seal leaks ${tag}`)).toBeVisible();
  await expect(trow(page, `^Failure mode: Bearing seizes ${tag}`)).toHaveCount(0);
  await expect(trow(page, `^Failure mode: Impeller worn ${tag}`)).toHaveCount(0);
  await expect(page.locator(".tt-top .tp-status")).toContainText("Medium priority");
  const menu2 = await openTreeMenu(page);
  await menu2.getByRole("menuitemcheckbox", { name: "Medium priority" }).click();
  await page.keyboard.press("Escape");
  await expect(trow(page, `^Failure mode: Bearing seizes ${tag}`)).toBeVisible();
  // A column header sorts the modes under the function: RPN highest first.
  await table(page).getByRole("button", { name: /^RPN: sort highest first/ }).click();
  const order = await table(page).getByRole("row").filter({ hasText: /Failure mode:/ }).allInnerTexts();
  expect(order[0]).toContain(`Seal leaks ${tag}`); // 60 before 24, blanks last
  expect(order[2]).toContain(`Impeller worn ${tag}`);
  await table(page).getByRole("button", { name: /^RPN: sort lowest first/ }).click();
  await table(page).getByRole("button", { name: /^RPN: sort: back/ }).click();
  // The mode's details: the FME(C)A group with the live preview, and Criticality.
  await pickRow(page, `^Failure mode: Bearing seizes ${tag}`);
  const details = page.getByRole("complementary", { name: "Details" });
  await expect(details).toBeVisible();
  await expect(details.getByRole("heading", { name: "FME(C)A" })).toBeVisible();
  await expect(details.getByRole("heading", { name: "Criticality" })).toBeVisible();
  const sev = details.getByRole("spinbutton", { name: "Severity (S)" });
  await expect(sev).toHaveValue("1");
  await sev.fill("9");
  await expect(details.getByRole("status")).toContainText("RPN 216");
  await expect(details.getByRole("status")).toContainText("High");
  await sev.press("Enter");
  await expect(await cellOf(page, `^Failure mode: Bearing seizes ${tag}`, "RPN")).toHaveText("216");
  await expect(details.getByText("0.004").first()).toBeVisible(); // Cm = 1 × 0.5 × 8e-5 × 100 (the value, and the working under it)
  await shot(page, "fmea-details-1440");
  // The position picked: its criticality matrix beside the table.
  await pickRow(page, `^Fmea pump ${tag}`);
  await expect(details.getByRole("heading", { name: "Criticality matrix" })).toBeVisible();
  await expect(details.getByRole("table", { name: /Criticality matrix/ })).toBeVisible();
  await expect(details.getByText("2 of 3 scored").first()).toBeVisible(); // the chip, and the Cr card's own count
  await expect(details.getByRole("heading", { name: "Item criticality (Cr)" })).toBeVisible();
  await shot(page, "fmea-matrix-1440");
  // A function's menu adds a failure mode directly under it, typed in place in its details.
  await trow(page, `^Function: Pump water ${tag}`).locator(".tt-tree").first().click({ button: "right" });
  await page.getByRole("menu", { name: new RegExp(`^Actions for Function: Pump water ${tag}`) }).getByRole("menuitem", { name: "Add failure mode", exact: true }).click();
  const box2 = details.getByRole("textbox", { name: "New failure mode" });
  await expect(box2).toBeFocused();
  await box2.fill(`Coupling slips ${tag}`);
  await box2.press("Enter");
  await expect(trow(page, `^Failure mode: Coupling slips ${tag}`)).toBeVisible();
  const after = await (await request.get(`${M}/positions/${p.pump.id}/rcm?scope=this`)).json();
  expect(after.positions[0].functions[0].modes.map((m) => m.text)).toContain(`Coupling slips ${tag}`);
  await expectHealthy(page, problems, { label: "fmea tab" });
});

test("RCM: a mode written on the FME(C)A tab shows under \"No functional failure yet\"; assigning it keeps its id", async ({ page, request, problems }) => {
  const tag = `n${Date.now()}`;
  const p = await plant(request, tag);
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pump.id}&tab=rcm`);
  const rcm = page.getByRole("treegrid", { name: /and their RCM/ });
  await expect(rcm).toBeVisible();
  const group = rcm.getByRole("row", { name: /No functional failure yet: No functional failure yet/ });
  await expect(group).toBeVisible();
  await expect(group).toContainText("finish the RCM");
  await expect(rcm.getByRole("row", { name: new RegExp(`^Failure mode: Bearing seizes ${tag}`) })).toBeVisible();
  // The same record: its row has the mode's id on both tabs.
  await expect(page.locator(`#tp-${p.direct.id}`)).toBeVisible();
  await shot(page, "rcm-nofail-1440");
  // Assign to a functional failure…: both direct modes go under "No flow".
  await group.locator(".tt-tree").first().click({ button: "right" });
  await page.getByRole("menu", { name: /^Actions for No functional failure yet/ }).getByRole("menuitem", { name: "Assign to a functional failure…" }).click();
  const dlg = page.getByRole("dialog", { name: "Assign to a functional failure" });
  await expect(dlg).toBeVisible();
  await expect(dlg.getByRole("combobox")).toHaveValue(p.ff.id);
  await dlg.getByRole("button", { name: "Assign" }).click();
  await expect(dlg).toHaveCount(0);
  await expect(group).toHaveCount(0);
  await expect(page.locator(`#tp-${p.direct.id}`)).toBeVisible();
  const saved = await (await request.get(`${M}/positions/${p.pump.id}/rcm?scope=this`)).json();
  const fn = saved.positions[0].functions[0];
  expect(fn.modes || []).toEqual([]);
  const moved = fn.failures[0].modes.find((m) => m.id === p.direct.id);
  expect(moved).toBeTruthy();
  expect(moved.severity).toBe(9); // the scores stayed with it
  expect(moved.ap).toBe("H");
  // Back on the FME(C)A tab the Functional failure column names it now.
  await page.getByRole("tab", { name: "FME(C)A" }).click();
  await expect(table(page)).toBeVisible();
  await expect(await cellOf(page, `^Failure mode: Bearing seizes ${tag}`, "Functional failure")).toHaveText(`No flow ${tag}`);
  await expectHealthy(page, problems, { label: "rcm nofail" });
});

test("at 400 px the FME(C)A tab is two-line rows, nothing scrolls sideways; a mode opens as a sheet; the position's matrix too", async ({ page, request, problems }) => {
  const tag = `p${Date.now()}`;
  const p = await plant(request, tag);
  await page.setViewportSize({ width: 400, height: 860 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pump.id}&tab=fmea`);
  await expect(table(page)).toBeVisible();
  expect((await overflow(page)).side).toBe(0);
  const mode = trow(page, `^Failure mode: Bearing seizes ${tag}`);
  await expect(mode.locator(".tt-l2")).toHaveText("S 9 · O 4 · D 6 · RPN 216 · High · Open");
  await expect(mode.locator(".tt-st")).toContainText("High");
  await expect(trow(page, `^Function: Pump water ${tag}`).locator(".tt-l2")).toContainText("2 of 3 scored");
  await shot(page, "fmea-phone-400");
  await pickRow(page, `^Failure mode: Bearing seizes ${tag}`);
  const details = page.getByRole("complementary", { name: "Details" });
  await expect(details).toBeVisible();
  await expect(details.getByRole("heading", { name: "FME(C)A" })).toBeVisible();
  expect((await overflow(page)).side).toBe(0);
  await details.getByRole("button", { name: "Close the details" }).click();
  await expect(details).toHaveCount(0);
  await pickRow(page, `^Fmea pump ${tag}`);
  await expect(details.getByRole("heading", { name: "Criticality matrix" })).toBeVisible();
  expect((await overflow(page)).side).toBe(0);
  await expectHealthy(page, problems, { label: "fmea at 400 px", root: ".tx" });
});

test("the print view: one plain worksheet table with the FME(C)A's columns", async ({ page, request, problems }) => {
  const tag = `w${Date.now()}`;
  const p = await plant(request, tag);
  await open(page, `/asset-register/positions/${p.top.id}/fmea`);
  const sheet = page.locator("table.fm-sheet");
  await expect(sheet).toBeVisible();
  await expect(page.getByRole("heading", { name: `Fmea plant ${tag}` })).toBeVisible();
  const heads = (await sheet.getByRole("columnheader").allInnerTexts()).map((t) => t.trim());
  expect(heads.slice(0, 6)).toEqual(["Position", "Function", "Functional failure", "Failure mode", "Cause", "Local effect"]);
  expect(heads).toContain("Action priority");
  expect(heads).toContain("Mode criticality");
  const row = sheet.getByRole("row", { name: new RegExp(`Bearing seizes ${tag}`) });
  await expect(row).toContainText("216");
  await expect(row).toContainText("High");
  await expect(row).toContainText("0.004");
  await expect(page.getByRole("button", { name: "Print" })).toBeVisible();
  await expectHealthy(page, problems, { label: "fmea print view" });
});
