// Links that open a page with its answer worked out (urlAsks.js): a demonstration run as one link a
// step, with no clicks.
import { test, expect, open, expectHealthy } from "./health.js";

test("an RBD link opens on the Calculator, calculated", async ({ page, problems }) => {
  await open(page, "/systems/b/sample-rbd-pump-station?tab=calc&calc=1");
  await expect(page.getByRole("tab", { name: "Calculator" })).toHaveAttribute("aria-selected", "true");
  const panel = page.locator(".rbd-calc-panel").first();
  await expect(panel.getByText("Minimal cut sets")).toBeVisible({ timeout: 30_000 });
  await expectHealthy(page, problems, { label: "RBD ?tab=calc&calc=1", chart: true });
});

test("an RBD link opens on the Fault tree tab", async ({ page, problems }) => {
  await open(page, "/systems/b/sample-rbd-pump-station?tab=tree");
  await expect(page.getByRole("tab", { name: "Fault tree" })).toHaveAttribute("aria-selected", "true");
  await expectHealthy(page, problems, { label: "RBD ?tab=tree" });
});

test("a repairable model link works out From now on", async ({ page, problems }) => {
  await open(page, "/models/recurrent/sample-rec-compressors-grp?tab=calc&next=500");
  await expect(page.getByText("Fleet failures").first()).toBeVisible({ timeout: 30_000 });
  await expectHealthy(page, problems, { label: "repairable ?next=500" });
});
