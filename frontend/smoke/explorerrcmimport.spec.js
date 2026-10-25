// An FMEA / RCM worksheet imported onto a position from the Explorer's RCM tab
// (the position row's menu, or the heading's ⋯ menu): upload, columns,
// preview, "Add to <position>", and the rows on the RCM tab. Importing it again
// adds nothing. The heading's ⋯ menu also downloads the position's RCM as CSV.
// A phone: the row's ⋯ button, and the dialog fits 400 px.
// The worksheet is smoke/fixtures/rcm-worksheet.csv (invented).
import { readFileSync } from "node:fs";
import { test, expect, open, expectHealthy, postOk } from "./health.js";

const M = "/api/maintenance";
const SHOTS = process.env.SMOKE_SHOTS_DIR || "";
const shot = async (page, name) => {
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}.png` });
};
const CSV = { name: "conveyor-fmea.csv", mimeType: "text/csv",
  buffer: readFileSync(new URL("./fixtures/rcm-worksheet.csv", import.meta.url)) };
// The same rows in a workbook, under a title row: the sheet step guesses the header.
const XLSX = { name: "conveyor-fmea.xlsx", mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  buffer: readFileSync(new URL("./fixtures/rcm-worksheet.xlsx", import.meta.url)) };

const table = (page) => page.getByRole("treegrid", { name: /and their RCM/ });
const trow = (page, name) => table(page).getByRole("row", { name: new RegExp(name) });
const rowMenu = (page, name) => page.getByRole("menu", { name: new RegExp(`^Actions for ${name}`) });
const dialogFor = (page, name) => page.getByRole("dialog", { name: `Import a worksheet onto “${name}”` });

async function chooseFile(page, name, file = CSV) {
  const d = dialogFor(page, name);
  await expect(d).toBeVisible();
  await d.locator("input[type=file]").setInputFiles(file);
  return d;
}

test("import a worksheet onto a position from the RCM tab, then again: nothing more", async ({ page, request, problems }) => {
  await page.setViewportSize({ width: 1280, height: 720 });
  const tag = `i${Date.now()}`;
  const name = `Import conveyor ${tag}`;
  const pos = await postOk(request, `${M}/positions`, { name });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${pos.id}&tab=rcm`);
  await expect(table(page)).toBeVisible();

  // The position row's menu.
  await trow(page, `^${name}`).locator(".tt-tree, .tt-l1").first().click({ button: "right" });
  const menu = rowMenu(page, name);
  await expect(menu.getByRole("menuitem", { name: "Import worksheet…" })).toBeVisible();
  await expect(menu.getByRole("menuitem", { name: "Export CSV" })).toBeVisible();
  await shot(page, "rcm-import-1-row-menu-1280");
  await menu.getByRole("menuitem", { name: "Import worksheet…" }).click();

  // A CSV goes straight to the columns; the preview says what it adds.
  const d = await chooseFile(page, name);
  const result = d.getByTestId("rcm-import-result");
  await expect(result).toContainText("Adds 2 functions · 3 functional failures · 4 failure modes · 3 tasks");
  await expect(d.locator(".modal-foot .hint")).toHaveText("Adds 2 functions · 3 functional failures · 4 failure modes · 3 tasks.");
  await expect(d.getByText("Severity", { exact: true }).first()).toBeVisible(); // kept in the notes
  await result.scrollIntoViewIfNeeded();
  await shot(page, "rcm-import-2-preview-1280");
  await d.getByRole("button", { name: `Add to “${name}”` }).click();
  await expect(d).toHaveCount(0);
  await expect(page.locator(".tt-msg")).toContainText(`Added 2 functions, 3 functional failures, 4 failure modes, 3 tasks to “${name}”.`);

  // The rows are on the RCM tab, the position opened down to its failure modes.
  await expect(trow(page, "^Function: Move grain from the pit to the silo")).toBeVisible();
  await expect(trow(page, "^Failure mode: Belt torn")).toBeVisible();
  await expect(trow(page, "^Failure mode: Pull-wire switch stuck")).toBeVisible();
  await expect(trow(page, "^Failure mode: Head pulley bearing seizes")).toContainText("Fixed-interval");
  await shot(page, "rcm-import-3-rows-1280");

  // Again, from the heading's ⋯ menu: nothing new, so nothing to add.
  await page.locator(".tt-headslot").getByRole("button", { name: "More actions" }).click();
  await page.locator(".tt-headslot").getByRole("button", { name: "Import worksheet…" }).click();
  const again = await chooseFile(page, name);
  await expect(again.getByTestId("rcm-import-result")).toContainText(`Nothing new: it's all on ${name} already.`);
  await expect(again.getByTestId("rcm-import-result")).toContainText("Already there, left as they are: 2 functions · 3 functional failures · 4 failure modes.");
  await expect(again.getByRole("button", { name: `Add to “${name}”` })).toBeDisabled();
  await expect(again.locator(".modal-foot .hint")).toHaveText("Nothing new to add.");
  await again.getByRole("button", { name: "Back" }).click();
  await page.keyboard.press("Escape");
  await expect(again).toHaveCount(0);

  // Export CSV: the same columns the import reads.
  await page.locator(".tt-headslot").getByRole("button", { name: "More actions" }).click();
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.locator(".tt-headslot").getByRole("button", { name: "Export CSV" }).click(),
  ]);
  expect(download.suggestedFilename()).toBe(`${name} RCM.csv`);
  const text = readFileSync(await download.path(), "utf8");
  expect(text.split("\n")[0]).toBe("Position,Function,Performance standard,Standard working,Functional failure,Caused by (below),Failure mode,Effects,"
    + "Consequence,Decision,Run-to-failure basis,Task,Interval,Interval unit,Evidence check,Notes");
  expect(text).toContain(`${name},Move grain from the pit to the silo,At least 40 t/h,,Moves no grain,,Belt torn,Line stops,`
    + "Operational,On-condition,,Walk the belt and look for damage,1,weeks,,Severity 7");

  await expectHealthy(page, problems, { label: "rcm worksheet import", root: ".tx" });
});

test("a phone: the row's ⋯ menu imports a workbook, and the dialog fits 400 px", async ({ page, request, problems }) => {
  await page.setViewportSize({ width: 400, height: 860 });
  const tag = `p${Date.now()}`;
  const name = `Phone conveyor ${tag}`;
  const pos = await postOk(request, `${M}/positions`, { name });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${pos.id}&tab=rcm`);
  const row = page.getByRole("row", { name: new RegExp(`^${name}`) }).or(page.getByRole("treeitem", { name: new RegExp(`^${name}`) }));
  await row.first().getByRole("button", { name: "Actions", exact: true }).click();
  const menu = rowMenu(page, name);
  await expect(menu.getByRole("menuitem", { name: "Import worksheet…" })).toBeVisible();
  await shot(page, "rcm-import-4-row-menu-400");
  await menu.getByRole("menuitem", { name: "Import worksheet…" }).click();
  const d = await chooseFile(page, name, XLSX);
  await d.getByRole("button", { name: "Next: map columns" }).click(); // a workbook: its sheet and header row first
  await expect(d.getByTestId("rcm-import-result")).toContainText("Adds 2 functions · 3 functional failures · 4 failure modes · 3 tasks");
  await d.getByTestId("rcm-import-result").scrollIntoViewIfNeeded();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(400);
  await shot(page, "rcm-import-5-preview-400");
  await d.getByRole("button", { name: `Add to “${name}”` }).click();
  await expect(d).toHaveCount(0);
  await expect(page.getByText("Belt torn").first()).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(400);
  await shot(page, "rcm-import-6-rows-400");
  await expectHealthy(page, problems, { label: "rcm worksheet import on a phone", root: ".tx" });
});
