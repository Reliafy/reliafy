// The Data section's upload (New dataset): "Split into datasets by" saves one
// sheet of three equipment classes as three datasets, each named by its
// class, with the rows left out said in the list. No columns are mapped here;
// each dataset links to its own page, where it is fitted.
import { test, expect, open, expectHealthy } from "./health.js";

const SHEET = [
  "Tag,Equipment class,Hours,Failed",
  "T-1,Transformer,1200,Yes", "T-2,Transformer,4000,No", "T-3,Transformer,2500,Yes",
  "M-1,Coal mill,300,Yes", "M-2,Coal mill,450,No", "M-3,Coal mill,610,Yes", "M-4,Coal mill,700,Yes",
  "P-1,Boiler feed pump,800,Yes", "P-2,Boiler feed pump,950,No",
  "X-1,,900,Yes",
].join("\n") + "\n";

test("split one sheet into a dataset per equipment class from the Data page", async ({ page, problems }) => {
  await open(page, "/data");
  await page.getByRole("button", { name: "New dataset" }).first().click();
  const dialog = page.getByRole("dialog");
  await dialog.locator('input[type="file"]').setInputFiles({
    name: "plant.csv", mimeType: "text/csv", buffer: Buffer.from(SHEET),
  });
  await expect(dialog.getByText("plant.csv")).toBeVisible();
  // Off by default: one dataset, as before.
  const pick = dialog.getByRole("combobox", { name: "Split into datasets by" });
  await expect(pick).toContainText("no split");
  await expect(dialog.getByRole("button", { name: "Create dataset" })).toBeVisible();

  await pick.click();
  await page.getByRole("option", { name: "Equipment class" }).click();
  const list = dialog.getByRole("region", { name: "Datasets this file makes" });
  await expect(list.getByText("This file makes 3 datasets:")).toBeVisible();
  await expect(list.getByRole("row", { name: /Transformer\s+3 rows/ })).toBeVisible();
  await expect(list.getByRole("row", { name: /Coal mill\s+4 rows/ })).toBeVisible();
  await expect(list.getByRole("row", { name: /Boiler feed pump\s+2 rows/ })).toBeVisible();
  await expect(list.getByText("Rows with no Equipment class are left out: 1")).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Create dataset" })).toHaveCount(0);
  await expectHealthy(page, problems, { label: "split chosen" });

  await dialog.getByRole("button", { name: "Save 3 datasets" }).click();
  const saved = dialog.getByRole("region", { name: "Saved datasets" });
  await expect(saved.getByText("Saved 3 datasets:")).toBeVisible({ timeout: 30_000 });
  await saved.getByRole("link", { name: "Coal mill" }).click();
  await expect(page).toHaveURL(/\/data\/[0-9a-f]{32}$/);
  await expect(page.getByText(/4 rows/).first()).toBeVisible();
  await expectHealthy(page, problems, { label: "a split dataset" });
});
