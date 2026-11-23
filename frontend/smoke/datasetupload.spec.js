// The Data section's New dataset: numbers written with thousands separators ("14,010") are read as
// numbers and the dialog says how; an Excel file's sheet can be changed after Continue, keeping the
// file.
import { readFileSync } from "node:fs";
import { test, expect, open, expectHealthy } from "./health.js";

const XLSX = { name: "worksheet.xlsx", mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  buffer: readFileSync(new URL("./fixtures/rcm-worksheet.xlsx", import.meta.url)) };

test("thousands separators are read as numbers, and said", async ({ page, problems }) => {
  await open(page, "/data");
  await page.getByRole("button", { name: "New dataset" }).first().click();
  const dialog = page.getByRole("dialog");
  await dialog.locator('input[type="file"]').setInputFiles({
    name: "runs.csv", mimeType: "text/csv",
    buffer: Buffer.from('Pump,Run hrs,Failed\nP-1,"14,010",1\nP-2,"8,240",0\nP-3,"11,190",1\n'),
  });
  const notes = dialog.getByRole("list", { name: "How the numbers were read" });
  await expect(notes).toContainText("“Run hrs” is read as numbers, with commas as thousands separators: 14,010 is 14010.",
                                    { timeout: 20_000 });
  await expectHealthy(page, problems, { label: "thousands separators" });
});

test("an Excel file's sheet can be changed after Continue", async ({ page, problems }) => {
  await open(page, "/data");
  await page.getByRole("button", { name: "New dataset" }).first().click();
  const dialog = page.getByRole("dialog").last();
  await page.getByRole("dialog").locator('input[type="file"]').setInputFiles(XLSX);
  await page.getByRole("button", { name: "Continue" }).click({ timeout: 20_000 });
  await expect(dialog.getByText("worksheet.xlsx")).toBeVisible();
  await dialog.getByRole("button", { name: "Change sheet" }).click();
  // The sheet picker again, on the same file.
  await expect(page.getByRole("button", { name: "Continue" })).toBeVisible({ timeout: 20_000 });
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByRole("dialog").getByText("worksheet.xlsx")).toBeVisible();
  await expect(page.getByRole("dialog").getByRole("button", { name: "Change sheet" })).toBeVisible();
  await expectHealthy(page, problems, { label: "change sheet" });
});
