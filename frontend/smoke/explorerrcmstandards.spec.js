// A function's performance standards as a list, on the Explorer's RCM tab
// (Operate › Assets › Explorer › RCM): the function's dialog lists them under
// Performance standards with Add standard, Edit…, Remove and the arrows; a
// function's one text shows as the first item and becomes the list's first
// when a second joins it; Split into standards… proposes a line per part and
// writes them on Confirm; the functional failure's dialog picks which standard
// it Breaches; the table's standard cell shows the list on one line; at
// 400 px it all fits. Each test makes its own small plant through the API.
//
// With SMOKE_SHOTS_DIR set, it also saves screenshots of the function dialog
// with its standards list at 1280 and 400 px (for the pull request).
import { test, expect, open, expectHealthy, postOk } from "./health.js";

const M = "/api/maintenance";
const SHOTS = process.env.SMOKE_SHOTS_DIR || "";

async function plant(request, tag, standard = "pH 7.2-7.8; Total alkalinity 80-120 ppm; given the filter pump runs") {
  const post = (path, data) => postOk(request, path, data);
  const pool = await post(`${M}/positions`, { name: `Std pool ${tag}` });
  const fn = await post(`${M}/positions/${pool.id}/functions`, { text: `Keep the water balanced ${tag}`, standard });
  const ff = await post(`${M}/functions/${fn.id}/failures`, { text: `pH above 7.8 ${tag}` });
  await post(`${M}/positions/${pool.id}/failure-modes`, { text: `Acid under-dosed ${tag}`, functional_failure_id: ff.id });
  return { pool, fn, ff };
}

const table = (page) => page.getByRole("treegrid", { name: /and their RCM/ });
const trow = (page, name) => table(page).getByRole("row", { name: new RegExp(name) });
const dialog = (page, name) => page.getByRole("dialog", { name, exact: true });
const standardsOf = (page) => dialog(page, "Function").getByRole("region", { name: "Performance standards" });
const overflow = (page) => page.evaluate(() => document.documentElement.scrollWidth - innerWidth);

test("the function's one text splits into a list on confirm; add, edit, reorder, remove; the failure picks what it breaches", async ({ page, request, problems }) => {
  const tag = `s${Date.now()}`;
  const p = await plant(request, tag);
  await page.setViewportSize({ width: 1280, height: 800 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pool.id}&tab=rcm`);
  const fnRow = trow(page, `^Function: Keep the water balanced ${tag}`);
  await expect(fnRow).toBeVisible();
  await fnRow.locator(".tp-nm").dblclick();
  const dlg = dialog(page, "Function");
  await expect(dlg).toBeVisible();
  const list = standardsOf(page);
  // The one text, as the first (and only) item; the split helper offered.
  await expect(list.getByRole("listitem")).toHaveCount(1);
  await expect(list).toContainText("pH 7.2-7.8; Total alkalinity 80-120 ppm; given the filter pump runs");
  await list.getByRole("button", { name: "Split into standards…" }).click();
  const lines = list.getByRole("listitem").filter({ has: page.getByRole("textbox") });
  await expect(lines).toHaveCount(3);
  await expect(list.getByRole("textbox", { name: "Line 1" })).toHaveValue("pH 7.2-7.8");
  // The "given …" clause: a condition of the standard before it. Nothing written yet.
  await list.getByRole("combobox", { name: "Line 3 is" }).selectOption("when");
  const beforeSplit = await (await request.get(`${M}/functions/${p.fn.id}`)).json();
  expect(beforeSplit.standards).toEqual([]);
  await list.getByRole("button", { name: "Confirm: 2 standards" }).click();
  await expect(list.getByRole("listitem")).toHaveCount(2);
  await expect(list.getByRole("listitem").nth(1)).toContainText("Total alkalinity 80-120 ppm");
  await expect(list.getByRole("listitem").nth(1)).toContainText("given the filter pump runs");
  await expect(list).toContainText("2 standards have no functional failure yet.");
  let fn = await (await request.get(`${M}/functions/${p.fn.id}`)).json();
  expect(fn.standards.map((st) => [st.text, st.when])).toEqual([["pH 7.2-7.8", null], ["Total alkalinity 80-120 ppm", "given the filter pump runs"]]);
  expect(fn.standard).toBe("pH 7.2-7.8; Total alkalinity 80-120 ppm");
  expect(fn.legacy_standard).toBe("pH 7.2-7.8; Total alkalinity 80-120 ppm; given the filter pump runs"); // the text itself stays

  // Add a third, with its structured limit folded under Limit…; saved once.
  await list.getByRole("button", { name: "Add standard" }).click();
  await list.getByRole("textbox", { name: "Standard" }).fill(`Calcium hardness 200-400 ppm ${tag}`);
  await list.getByRole("button", { name: "Limit…" }).click();
  await list.getByRole("textbox", { name: "Parameter" }).fill("Calcium hardness");
  await list.getByRole("combobox", { name: "Comparator" }).selectOption("between");
  await list.getByRole("textbox", { name: "Value" }).fill("200-400");
  await list.getByRole("textbox", { name: "Unit" }).fill("ppm");
  await list.getByRole("textbox", { name: "Source (optional)" }).fill("E25 manual");
  let writes = 0;
  page.on("request", (r) => { if (r.method() === "POST" && r.url().includes(`/functions/${p.fn.id}/standards`)) writes += 1; });
  await list.getByRole("button", { name: "Add standard", exact: true }).last().dblclick();
  await expect(list.getByRole("listitem")).toHaveCount(3);
  expect(writes).toBe(1);
  await expect(list.getByRole("listitem").nth(2)).toContainText("Calcium hardness between 200-400 ppm · E25 manual");
  // Move it to the top; edit the text; the table's cell shows the list on one line.
  await list.getByRole("button", { name: `Move Calcium hardness 200-400 ppm ${tag} up` }).click();
  await list.getByRole("button", { name: `Move Calcium hardness 200-400 ppm ${tag} up` }).click();
  await expect(list.getByRole("listitem").nth(0)).toContainText("Calcium hardness");
  await list.getByRole("button", { name: "Edit pH 7.2-7.8" }).click();
  await list.getByRole("textbox", { name: "Standard" }).fill("pH 7.4-7.6");
  await list.getByRole("button", { name: "Save standard" }).click();
  await expect(list).toContainText("pH 7.4-7.6");
  // Remove one, after asking.
  await list.getByRole("button", { name: "Remove Total alkalinity 80-120 ppm" }).click();
  await page.getByRole("alertdialog", { name: "Remove this standard?" }).getByRole("button", { name: "Remove standard" }).click();
  await expect(list.getByRole("listitem")).toHaveCount(2);
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);

  // The functional failure: which standard it breaches.
  const ffRow = trow(page, `^Functional failure: pH above 7.8 ${tag}`);
  await ffRow.locator(".tp-nm").dblclick();
  const fdlg = dialog(page, "Functional failure");
  await expect(fdlg).toBeVisible();
  const breaches = fdlg.getByRole("combobox", { name: "Breaches" });
  await expect(breaches).toHaveValue("");
  await breaches.selectOption({ label: "pH 7.4-7.6" });
  await expect(breaches).not.toHaveValue("");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  fn = await (await request.get(`${M}/functions/${p.fn.id}`)).json();
  expect(fn.standards.map((st) => [st.text, st.failures])).toEqual([[`Calcium hardness 200-400 ppm ${tag}`, 0], ["pH 7.4-7.6", 1]]);
  expect(fn.failures[0].standard.text).toBe("pH 7.4-7.6");
  // The hint follows: one standard still has no failure; the dialog says so.
  await fnRow.locator(".tp-nm").dblclick();
  await expect(standardsOf(page)).toContainText("1 standard has no functional failure yet.");
  await page.keyboard.press("Escape");
  // The standard column (shown from the Columns menu) has the list on one line.
  await page.getByRole("button", { name: "Columns" }).click();
  await page.getByRole("checkbox", { name: /Performance standard/ }).check();
  await page.keyboard.press("Escape");
  await expect(fnRow).toContainText(`Calcium hardness 200-400 ppm ${tag}; pH 7.4-7.6`);
  await expectHealthy(page, problems, { label: "rcm standards dialog" });
});

test("the Details panel edits the list too, and a second standard keeps the one text as the first", async ({ page, request, problems }) => {
  const tag = `d${Date.now()}`;
  const p = await plant(request, tag, "At least 50 L/s");
  await page.setViewportSize({ width: 1280, height: 800 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pool.id}&tab=rcm`);
  const fnRow = trow(page, `^Function: Keep the water balanced ${tag}`);
  await fnRow.locator(".tp-nm").click();
  await page.keyboard.press("Enter");
  const details = page.getByRole("complementary", { name: "Details" });
  const list = details.getByRole("region", { name: "Performance standards" });
  await expect(list.getByRole("listitem")).toHaveCount(1);
  await expect(list.getByRole("button", { name: "Split into standards…" })).toHaveCount(0); // one text, no ';': nothing to split
  await list.getByRole("button", { name: "Add standard" }).click();
  await list.getByRole("textbox", { name: "Standard" }).fill("At 4 bar");
  await list.getByRole("button", { name: "Add standard", exact: true }).last().click();
  await expect(list.getByRole("listitem")).toHaveCount(2);
  await expect(list.getByRole("listitem").nth(0)).toContainText("At least 50 L/s");
  const fn = await (await request.get(`${M}/functions/${p.fn.id}`)).json();
  expect(fn.standards.map((st) => st.text)).toEqual(["At least 50 L/s", "At 4 bar"]);
  await expectHealthy(page, problems, { label: "rcm standards details" });
});

test("at 400 px the standards list and its forms fit the sheet", async ({ page, request, problems }) => {
  const tag = `p${Date.now()}`;
  const p = await plant(request, tag);
  await postOk(request, `${M}/functions/${p.fn.id}/standards`, { text: "Calcium hardness 200-400 ppm" });
  await page.setViewportSize({ width: 400, height: 860 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pool.id}&tab=rcm`);
  const fnRow = trow(page, `^Function: Keep the water balanced ${tag}`);
  await fnRow.getByRole("button", { name: "Actions", exact: true }).click();
  await page.getByRole("menu").getByRole("menuitem", { name: "Open…" }).click();
  const dlg = dialog(page, "Function");
  await expect(dlg).toBeVisible();
  const list = standardsOf(page);
  await expect(list.getByRole("listitem")).toHaveCount(2);
  await list.getByRole("button", { name: "Add standard" }).click();
  await list.getByRole("button", { name: "Limit…" }).click();
  expect(await overflow(page)).toBe(0);
  const box = await dlg.boundingBox();
  expect(box.x + box.width).toBeLessThanOrEqual(400.5);
  await list.getByRole("button", { name: "Cancel" }).click();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect(await overflow(page)).toBe(0);
  await expectHealthy(page, problems, { label: "rcm standards phone" });
});

test("screenshots of the function dialog's standards list (SMOKE_SHOTS_DIR)", async ({ page, request }) => {
  test.skip(!SHOTS, "only when saving screenshots");
  const tag = "shot";
  const p = await plant(request, tag, "pH 7.2-7.8");
  await postOk(request, `${M}/functions/${p.fn.id}/standards`, {
    text: "Total alkalinity 80-120 ppm", parameter: "Total alkalinity", comparator: "between", value: "80-120", unit: "ppm", source: "E25 manual",
  });
  await postOk(request, `${M}/functions/${p.fn.id}/standards`, { text: "Calcium hardness 200-400 ppm", when: "while the pool is in use" });
  const fn = await (await request.get(`${M}/functions/${p.fn.id}`)).json();
  await request.patch(`${M}/functional-failures/${p.ff.id}`, { data: { standard_id: fn.standards[0].id } });
  for (const [w, h] of [[1280, 800], [400, 860]]) {
    await page.setViewportSize({ width: w, height: h });
    await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pool.id}&tab=rcm`);
    const row = trow(page, `^Function: Keep the water balanced ${tag}`).first();
    if (w > 600) await row.locator(".tp-nm").dblclick();
    else {
      await row.getByRole("button", { name: "Actions", exact: true }).click();
      await page.getByRole("menuitem", { name: "Open…" }).click();
    }
    await expect(dialog(page, "Function")).toBeVisible();
    await standardsOf(page).scrollIntoViewIfNeeded();
    await page.waitForTimeout(300);
    await page.screenshot({ path: `${SHOTS}/rcm-standards-dialog-${w}.png` });
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog")).toHaveCount(0);
  }
});
