// Open in › from a position with several tasks (forecast plan step 2, Nov 2026): the quick forecast
// tool shows the records as lines by owner, no form. Each task's line is certain; each failure mode's
// corrective line is worked out, with a range; the total is the known total, and "Not counted" lists
// every gap with where to fix it (a failure mode with no cost of a failure, a check with no P-F
// interval). At 400 px nothing scrolls sideways.
//
// With SMOKE_SHOTS_DIR set, it saves screenshots (for the pull request).
import { test, expect, open, expectHealthy, postOk } from "./health.js";

const M = "/api/maintenance";
const SHOTS = process.env.SMOKE_SHOTS_DIR || "";
const shot = async (page, name) => {
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: true });
};
const sideways = (page) => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);

async function deck(request, tag) {
  const post = (path, data) => postOk(request, path, data);
  const patch = async (path, data) => expect((await request.patch(path, { data })).ok()).toBeTruthy();
  const top = await post(`${M}/positions`, { name: `Cutting deck ${tag}` });
  expect((await request.put(`${M}/positions/${top.id}/operating-plan`, {
    data: { plan: { background: { kind: "rate", amount: 12, per: "week" } }, from: "2025-01-01" } })).ok()).toBeTruthy();
  const meter = await post(`${M}/positions/${top.id}/points`, { name: "Hour meter", kind: "counter", unit: "hours" });
  await post(`${M}/points/${meter.id}/readings`, { value: 0, on: "2025-06-02" });
  await post(`${M}/points/${meter.id}/readings`, { value: 900 });
  const modes = [];
  for (const k of [1, 2, 3]) {
    const p = await post(`${M}/positions`, { name: `Spindle ${k} ${tag}`, parent_id: top.id });
    await post(`${M}/positions/${p.id}/fit`, { new_item: { name: `Bearing ${k} ${tag}` }, on: "2025-06-02" });
    const fm = await post(`${M}/positions/${p.id}/failure-modes`, { text: "Spindle bearing worn out" });
    if (k !== 3) await patch(`${M}/failure-modes/${fm.id}`, { failure_cost: 900 });
    await post(`${M}/positions/${p.id}/models`, { model_id: "sample-model-bearings-weibull", failure_mode_ids: [fm.id] });
    modes.push(fm.id);
  }
  const grease = await post(`${M}/positions/${top.id}/tasks`, { name: `Grease deck spindles ${tag}`, interval: 50, unit: "hours" });
  await patch(`${M}/tasks/${grease.id}`, { cost: 18, resources: { labour: [{ trade: "Fitter", people: 1, hours: 0.2 }] } });
  const check = await post(`${M}/positions/${top.id}/tasks`, { name: `Inspect bearings for play ${tag}`, interval: 100,
    unit: "hours", outcome: "on_condition", failure_mode_ids: modes });
  await patch(`${M}/tasks/${check.id}`, { cost: 22.5, resources: { labour: [{ trade: "Fitter", people: 1, hours: 0.3 }] } });
  return top;
}

for (const width of [1440, 400]) {
  test(`Open in › from a position: lines by owner, gaps listed (${width} px)`, async ({ page, request, problems }) => {
    const tag = `l${Date.now()}`;
    const top = await deck(request, tag);
    await page.setViewportSize({ width, height: 900 });
    await open(page, `/forecasts/costs?from=position%3A${top.id}&root=${top.id}`);
    await expect(page.locator(".ft-from")).toContainText(`Cutting deck ${tag}`);
    const table = page.locator(".ft-lines");
    await expect(table).toContainText(`Grease deck spindles ${tag}`, { timeout: 30_000 });
    await expect(table).toContainText(`Inspect bearings for play ${tag}`);
    await expect(table).toContainText("Corrective: after a failure");
    await expect(table).toContainText("Certain");
    await expect(table).toContainText("Worked out");
    await expect(page.locator(".ft-result .rs-sentence")).toContainText("known costs expected in the next 12 months");
    const gaps = page.getByRole("region", { name: "Not counted" });
    await expect(gaps).toContainText("no response if it fails, so its failure cost is unknown");
    await expect(gaps).toContainText("no P-F interval");
    await expect(page.getByRole("textbox")).toHaveCount(0); // no form: the records are the inputs
    await shot(page, `forecast-lines-costs-${width}`);
    if (width <= 400) expect(await sideways(page)).toBeLessThanOrEqual(0);
    // The same lines on the Hours view.
    await page.getByRole("radiogroup", { name: "Show" }).getByRole("radio", { name: "Labour hours" }).click();
    await expect(page.locator(".ft-result .rs-sentence")).toContainText("known hours");
    await shot(page, `forecast-lines-hours-${width}`);
    await expectHealthy(page, problems, { label: `forecast lines ${width}` });
  });
}
