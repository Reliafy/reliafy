// The repairable RBD calculator asks two questions, each with its own input: "Out to" a horizon
// and "Availability at" a time. One repairable block, exponential failures (mean 100 h) and
// repairs (mean 10 h): A(50 h) = 0.90909 + 0.09091 e^(-5.5) = 90.95%. Desktop and 400 px.
import { test, expect, open, expectHealthy } from "./health.js";

const SHOTS = process.env.SMOKE_SHOTS_DIR || "";
const shot = async (page, name) => {
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}.png` });
};
const sideways = (page) => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
const exp = (rate) => ({ source: "params", distribution: "Exponential", distribution_id: "exponential",
                         params: [{ name: "failure_rate", value: rate }] });

test("the repairable calculator answers out to a horizon and at a time", async ({ page, request, problems }) => {
  const graph = {
    repairable: true, unit: "Hours",
    nodes: [{ id: "input", type: "input", position: { x: 0, y: 0 }, data: { label: "Input" } },
            { id: "p", type: "component", position: { x: 200, y: 0 }, data: { label: "Pump", model: exp(0.01), repair: exp(0.1) } },
            { id: "output", type: "output", position: { x: 400, y: 0 }, data: { label: "Output" } }],
    edges: [{ id: "a", source: "input", target: "p" }, { id: "b", source: "p", target: "output" }],
  };
  const { id } = await (await request.post("/api/rbds", { data: { name: "Smoke calculator questions", graph } })).json();
  for (const [width, height] of [[1440, 900], [400, 860]]) {
    await page.setViewportSize({ width, height });
    await open(page, `/systems/b/${id}`);
    await page.getByRole("tab", { name: "Calculator" }).click();
    await page.getByRole("radio", { name: "Custom" }).click();
    await page.getByLabel(/^Horizon/).fill("200");
    await page.getByLabel(/^Availability at t/).fill("50");
    await page.getByRole("button", { name: /^Calculate/ }).first().click();
    const at = page.locator(".rbd-at-time").first();
    await expect(at).toContainText("90.95", { timeout: 30_000 });
    await expect(at).toContainText("Exact");
    await expect(page.locator(".rbd-answer").first()).toContainText(/Failures over the first 200/);
    await shot(page, `rbd-calc-questions-${width}`);
    expect(await sideways(page)).toBeLessThanOrEqual(1);
  }
  await expectHealthy(page, problems, { label: "repairable calculator questions" });
  await request.delete(`/api/rbds/${id}`);
});
