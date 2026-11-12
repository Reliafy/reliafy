// The Data step's "dataset" selector: one sheet of three equipment classes
// saved as three datasets, each named by its class, with the rows left out
// said beside the selector. Nothing is fitted; each dataset links to its fit.
import { test, expect, open, expectHealthy } from "./health.js";

const SHEET = [
  "Tag,Equipment class,Hours,Failed",
  "T-1,Transformer,1200,Yes", "T-2,Transformer,4000,No", "T-3,Transformer,2500,Yes",
  "M-1,Coal mill,300,Yes", "M-2,Coal mill,450,No", "M-3,Coal mill,610,Yes", "M-4,Coal mill,700,Yes",
  "P-1,Boiler feed pump,800,Yes", "P-2,Boiler feed pump,950,No",
  "X-1,,900,Yes",
].join("\n") + "\n";

test("split one sheet into a dataset per equipment class", async ({ page, problems }) => {
  await open(page, "/models/new?mode=data");
  await page.locator('input[type="file"]').setInputFiles({
    name: "plant.csv", mimeType: "text/csv", buffer: Buffer.from(SHEET),
  });
  await expect(page.getByText(/plant\.csv · 10 rows/)).toBeVisible();
  // Off by default: Next, as before.
  await expect(page.getByRole("combobox", { name: "dataset", exact: true })).toContainText("none");
  await expect(page.getByRole("button", { name: "Next" })).toBeVisible();

  await page.getByRole("combobox", { name: "dataset", exact: true }).click();
  await page.getByRole("option", { name: "Equipment class" }).click();
  await expect(page.getByText("1 row has no dataset name and is left out")).toBeVisible();
  const list = page.getByRole("region", { name: "Datasets this sheet makes" });
  await expect(list.getByText("This sheet makes 3 datasets:")).toBeVisible();
  await expect(list.getByRole("row", { name: /Transformer\s+3 rows · 2 failed/ })).toBeVisible();
  await expect(list.getByRole("row", { name: /Coal mill\s+4 rows · 3 failed/ })).toBeVisible();
  await expect(list.getByRole("row", { name: /Boiler feed pump\s+2 rows · 1 failed/ })).toBeVisible();
  await expect(page.getByRole("button", { name: "Next" })).toHaveCount(0);
  await expectHealthy(page, problems, { label: "split chosen" });

  await page.getByRole("button", { name: "Save 3 datasets" }).click();
  const saved = page.getByRole("region", { name: "Saved datasets" });
  await expect(saved.getByText("Saved 3 datasets:")).toBeVisible({ timeout: 30_000 });
  await expect(saved.getByText("Fit each from its dataset page.")).toBeVisible();
  await saved.getByRole("link", { name: "Coal mill" }).click();
  await expect(page).toHaveURL(/\/data\/[0-9a-f]{32}$/);
  await expect(page.getByText(/4 rows/).first()).toBeVisible();
  await expectHealthy(page, problems, { label: "a split dataset" });
});
