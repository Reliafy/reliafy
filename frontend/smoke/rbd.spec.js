// RBDs: every tab of every sample diagram, a calculation, and the importers
// (BlockSim, Open-PSA, Galileo, Excel) through the RBDs page's Import button.
import { existsSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { test, expect, open, expectHealthy } from "./health.js";

const fixture = (name) => fileURLToPath(new URL(`fixtures/${name}`, import.meta.url));

test("every tab of every sample RBD", async ({ page, request, problems }) => {
  const { rbds } = await (await request.get("/api/rbds")).json();
  const samples = rbds.filter((r) => r.is_sample);
  expect(samples.length).toBeGreaterThan(0);
  for (const rbd of samples) {
    await open(page, `/rbds/b/${rbd.id}`);
    const tablist = page.getByRole("tablist", { name: "Diagram views" });
    const names = await tablist.getByRole("tab").allInnerTexts();
    expect(names.length, `${rbd.id}: no tabs`).toBeGreaterThan(1);
    for (const name of names) {
      await test.step(`${rbd.id} › ${name}`, async () => {
        const tab = tablist.getByRole("tab", { name, exact: true });
        await tab.click();
        await expect(tab).toHaveAttribute("aria-selected", "true");
        await page.waitForLoadState("networkidle", { timeout: 10_000 }).catch(() => {});
        await expectHealthy(page, problems, { label: `${rbd.id} › ${name}` });
      });
    }
  }
});

test("calculate a sample RBD", async ({ page, problems }) => {
  await open(page, "/rbds/b/sample-rbd-pump-station");
  await page.getByRole("tab", { name: "Calculator" }).click();
  await page.locator('[data-wt="rbd-calculate"]').click();
  const panel = page.locator(".rbd-calc-panel").first();
  await expect(panel.getByText("Minimal cut sets")).toBeVisible({ timeout: 30_000 });
  await expect(panel.getByText(/MTTF/).first()).toBeVisible();
  await expectHealthy(page, problems, { label: "calculated RBD", chart: true });
});

// The BlockSim examples are ReliaSoft's copyright, so they aren't in the
// repository: backend/scripts/fetch_rbd_import_fixtures.py downloads them.
const BLOCKSIM_DIR = fileURLToPath(new URL("../../backend/tests/fixtures/external/blocksim/", import.meta.url));
const blocksim = () => {
  const files = existsSync(BLOCKSIM_DIR) ? readdirSync(BLOCKSIM_DIR).filter((f) => /\.(rsgz|rsr)\d+$|\.rsrp$/.test(f)) : [];
  const file = files.includes("blocksim_example1_V20.rsgz20") ? "blocksim_example1_V20.rsgz20" : files[0];
  return file && BLOCKSIM_DIR + file;
};

const IMPORTS = [
  { format: "Galileo", file: () => fixture("pump-train.dft"), blocks: 4 },
  { format: "Open-PSA", file: () => fixture("cooling.xml"), blocks: 5 },
  { format: "Excel", file: null, blocks: 2 }, // the template the app offers
  { format: "BlockSim", file: blocksim, blocks: 2 },
];

for (const { format, file, blocks } of IMPORTS) {
  test(`import an RBD from ${format}`, async ({ page, request, problems }) => {
    let upload;
    if (file) {
      upload = file();
      test.skip(!upload, "No BlockSim example here: run backend/scripts/fetch_rbd_import_fixtures.py");
    } else {
      const res = await request.get("/api/rbds/import/template.xlsx");
      expect(res.ok()).toBeTruthy();
      upload = { name: "reliafy-rbd-template.xlsx", mimeType: "application/octet-stream", buffer: await res.body() };
    }
    await open(page, "/rbds");
    await page.locator('input[type="file"]').setInputFiles(upload);
    await page.waitForURL(/\/rbds\/b$/, { timeout: 30_000 });
    await expect(page.locator(".react-flow__node").nth(blocks - 1)).toBeVisible();
    await expectHealthy(page, problems, { label: `${format} import` });
  });
}
