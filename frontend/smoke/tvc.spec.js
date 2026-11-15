// Covariate schedules in a repairable diagram (planning #372): the builder's Set covariates offers
// Schedule on a repairable diagram's covariate block, says what it means (the plant's clock,
// simulated with Pro), and the diagram is then worked out by simulation. Desktop and 400 px.
import { test, expect, open, expectHealthy } from "./health.js";

const SHOTS = process.env.SMOKE_SHOTS_DIR || "";
const shot = async (page, name) => {
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}.png` });
};
const sideways = (page) => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);

test("a repairable block follows a covariate schedule", async ({ page, request, problems }) => {
  const model = { kind: "regression", modelId: "sample-model-pump-load-weibull-ph", distribution: "Weibull PH",
                  covariates: [{ name: "load_pct", type: "number", default: 75, unit: "%" }] };
  const repair = { source: "params", distribution: "Exponential", distribution_id: "exponential",
                   params: [{ name: "failure_rate", value: 0.05 }] };
  const graph = {
    repairable: true, unit: "Hours",
    nodes: [{ id: "input", type: "input", position: { x: 0, y: 0 }, data: { label: "Input" } },
            { id: "p", type: "component", position: { x: 200, y: 0 }, data: { label: "Process pump", model, repair } },
            { id: "output", type: "output", position: { x: 400, y: 0 }, data: { label: "Output" } }],
    edges: [{ id: "a", source: "input", target: "p" }, { id: "b", source: "p", target: "output" }],
  };
  const { id } = await (await request.post("/api/rbds", { data: { name: "Smoke repairable schedule", graph } })).json();
  for (const [width, height] of [[1440, 900], [400, 860]]) {
    await page.setViewportSize({ width, height });
    await open(page, `/systems/b/${id}`);
    await page.getByRole("tab", { name: "Calculator" }).click();
    await page.getByRole("button", { name: "Set covariates" }).first().click();
    const dialog = page.getByRole("dialog", { name: "Covariates" });
    await expect(dialog.getByText(/follows the plant.s clock/)).toBeVisible();
    await dialog.getByRole("radio", { name: "Schedule" }).first().click();
    await dialog.getByLabel(/as an expression in t/).fill("90 if t % 24 < 16 else 60");
    await expect(dialog.locator(".rbd-sched-preview")).toBeVisible({ timeout: 20_000 });
    await expect.poll(() => sideways(page)).toBeLessThanOrEqual(0);
    await shot(page, `repairable-schedule-${width}`);
    await dialog.getByRole("button", { name: "Apply" }).click();
    await expect(dialog).toHaveCount(0);
    await expect(page.locator(".rbd-cov-bar")).toContainText("load_pct follows a schedule");
  }
  await expectHealthy(page, problems, { label: "repairable covariate schedule" });
  await request.delete(`/api/rbds/${id}`);
});
