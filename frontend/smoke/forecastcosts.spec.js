// What a failure costs, and what the forecast asks for (Explorer › Maintenance › Forecast…): the
// forecast lists failure modes with no failure cost and checks with no P-F interval, each with a link
// straight to the failure mode on the RCM tab, where "What a failure costs" takes the figures; with a
// cost entered the prompt goes. At 400 px nothing scrolls the page sideways. Each test makes its own
// small plant through the API.
//
// With SMOKE_SHOTS_DIR set, it saves screenshots (for the pull request).
import { test, expect, open, expectHealthy, postOk } from "./health.js";

const M = "/api/maintenance";
const SHOTS = process.env.SMOKE_SHOTS_DIR || "";
const shot = async (page, name) => {
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}.png` });
};
const query = (page) => new URL(page.url()).searchParams;
const sideways = (page) => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);

async function plant(request, tag) {
  const pump = await postOk(request, `${M}/positions`, { name: `Cost pump ${tag}` });
  const fn = await postOk(request, `${M}/positions/${pump.id}/functions`, { text: `Pump water ${tag}`, standard: "50 L/s" });
  const ff = await postOk(request, `${M}/functions/${fn.id}/failures`, { text: `No flow ${tag}` });
  const mode = await postOk(request, `${M}/positions/${pump.id}/failure-modes`, { text: `Seal leaks ${tag}`, functional_failure_id: ff.id });
  const res = await request.put(`${M}/failure-modes/${mode.id}/decision`, {
    data: { consequence: "operational", hidden: false, decision: { outcome: "on_condition", task: `Check the seal ${tag}`, interval: 1, interval_unit: "months" } },
  });
  expect(res.ok()).toBeTruthy();
  return { pump, mode };
}

test("Forecast… lists what to enter; the link opens the failure mode, whose failure cost then counts", async ({ page, request, problems }) => {
  const tag = `c${Date.now()}`;
  const p = await plant(request, tag);
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, `/asset-register/explorer?arrange=positions&root=${p.pump.id}&sel=${p.pump.id}&tab=maintenance&forecast=${p.pump.id}`);
  const pane = page.locator("section.table-pane");
  const enter = pane.locator("details", { has: page.locator("summary", { hasText: "What to enter" }) });
  await expect(enter).toContainText("Failure modes with no failure cost (1)", { timeout: 30_000 });
  await expect(enter).toContainText("Checks with no P-F interval (1)");
  await expect(enter).toContainText(`Check the seal ${tag}`);
  await expect(pane.getByRole("columnheader", { name: "Unplanned cost" })).toBeVisible();
  await expect(pane.getByRole("columnheader", { name: "Total cost" })).toBeVisible();
  await shot(page, "forecast-what-to-enter-desktop");

  // The link: the failure mode on the RCM tab, its "What a failure costs" under its consequence.
  await enter.locator("li", { hasText: `Seal leaks ${tag}` }).getByRole("link", { name: "Enter the cost" }).click();
  await expect.poll(() => query(page).get("tab")).toBe("rcm");
  await expect.poll(() => query(page).get("forecast")).toBe(null);
  const costs = page.getByRole("region", { name: "Failure consequences" });
  await expect(costs).toContainText("What a failure costs");
  await expect(costs).toContainText("No failure cost yet");
  const box = costs.getByRole("spinbutton", { name: /A failure costs/ });
  await box.fill("1200");
  await box.press("Enter");
  await expect(costs).toContainText("One failure, all in: $1,200");
  await shot(page, "failure-mode-costs-desktop");
  const saved = await (await request.get(`${M}/failure-modes/${p.mode.id}/costs`)).json();
  expect(saved.own.failure_cost).toBe(1200);

  // Back on the forecast: no failure mode is left without a cost; the check still asks for its P-F.
  await open(page, `/asset-register/explorer?arrange=positions&root=${p.pump.id}&sel=${p.pump.id}&tab=maintenance&forecast=${p.pump.id}`);
  await expect(enter).toContainText("Checks with no P-F interval (1)", { timeout: 30_000 });
  await expect(enter).not.toContainText("Failure modes with no failure cost");
  await expectHealthy(page, problems, { label: "forecast costs" });
});

test("Forecast… and a failure mode's costs at 400 px: nothing scrolls sideways", async ({ page, request, problems }) => {
  const tag = `d${Date.now()}`;
  const p = await plant(request, tag);
  await page.setViewportSize({ width: 400, height: 860 });
  await open(page, `/asset-register/explorer?arrange=positions&root=${p.pump.id}&sel=${p.pump.id}&tab=maintenance&forecast=${p.pump.id}`);
  await expect(page.locator("section.table-pane")).toContainText("What to enter", { timeout: 30_000 });
  expect(await sideways(page)).toBeLessThanOrEqual(0);
  await shot(page, "forecast-what-to-enter-phone");
  await open(page, `/asset-register/explorer?arrange=positions&root=${p.pump.id}&sel=${p.mode.id}&tab=rcm`);
  await expect(page.getByRole("region", { name: "Failure consequences" })).toContainText("What a failure costs", { timeout: 30_000 });
  expect(await sideways(page)).toBeLessThanOrEqual(0);
  await shot(page, "failure-mode-costs-phone");
  await expectHealthy(page, problems, { label: "forecast costs phone" });
});
