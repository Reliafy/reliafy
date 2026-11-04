// Signals tab › Time to the limit: a scalar level that drifts up toward its alarm limit gets a
// most-likely date and a range; a level with too few readings gets a plain message and no dates.
// At 400 px nothing scrolls the page sideways. Names start "Ttl" so they sort after the other specs' plants.
import { test, expect, open, expectHealthy } from "./health.js";

const M = "/api/maintenance";
const SHOTS = process.env.SMOKE_SHOTS_DIR || "";
const shot = async (page, name) => {
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}.png` });
};

async function plant(request, tag, readings) {
  const post = async (path, data) => {
    const res = await request.post(path, { data });
    expect(res.ok(), `${path}: ${res.status()} ${await res.text()}`).toBeTruthy();
    return res.json();
  };
  const pump = await post(`${M}/positions`, { name: `Ttl pump ${tag}` });
  const channel = await post(`${M}/signals/channels`, { position_id: pump.id, name: `Ttl pressure ${tag}`, unit: "mm/s" });
  await post(`${M}/signals/channels/${channel.id}/levels`, { name: "Overall", stat: "value", alarm_above: 12 });
  const day = 24 * 3600 * 1000;
  const now = Date.now();
  // About 0.2 a day with some scatter: the limit is a couple of months off.
  for (let i = 0; i < readings; i += 1) {
    const wobble = 0.35 * Math.sin(i * 2.3) + 0.2 * Math.cos(i * 0.9);
    await post(`${M}/signals/snapshots`, {
      channel_id: channel.id, time: new Date(now - (readings - 1 - i) * 2 * day).toISOString(), value: +(2 + 0.4 * i + wobble).toFixed(3),
    });
  }
  return { pump, channel };
}

test("Time to the limit: a date and a range, and the two ways on", async ({ page, request, problems }) => {
  const p = await plant(request, "A", 16);
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pump.id}&tab=signals`);
  const panel = page.getByRole("region", { name: "Time to the limit" });
  await expect(panel).toBeVisible();
  await expect(panel.getByRole("status").first()).toContainText("most likely to reach", { timeout: 15_000 });
  await expect(panel.locator(".js-plotly-plot")).toBeVisible();
  await expect(panel.getByText("Chance of reaching the limit within")).toBeVisible();
  await panel.getByText("What this assumes").click();
  await expect(panel.getByText("The level is modelled as a random walk")).toBeVisible();
  await panel.scrollIntoViewIfNeeded();
  await shot(page, "time-to-limit-desktop");

  // With no tracked fleet, Watch in Risk says what to do first.
  await panel.getByRole("button", { name: "Watch in Risk" }).click();
  await expect(page.getByText(/no tracked fleet|Add this band/)).toBeVisible();
  await page.getByRole("button", { name: "Cancel" }).click();

  // Use in a degradation model: the trend becomes a dataset and the model flow opens on it.
  await panel.getByRole("button", { name: "Use in a degradation model" }).click();
  await expect(page).toHaveURL(/\/models\/degradation\?dataset=/);
  await expectHealthy(page, problems, { label: "time to the limit" });
});

test("Time to the limit: too few readings gives a message and fits a phone", async ({ page, request, problems }) => {
  const p = await plant(request, "B", 3);
  await page.setViewportSize({ width: 400, height: 800 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pump.id}&tab=signals`);
  await page.getByText("Ttl pump B", { exact: true }).click();
  const panel = page.getByRole("region", { name: "Time to the limit" });
  await expect(panel.getByRole("status").first()).toContainText("at least 6", { timeout: 15_000 });
  await expect(panel.locator(".js-plotly-plot")).toHaveCount(0);
  const sideways = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
  expect(sideways, "the page scrolls sideways at 400 px").toBe(false);
  await panel.scrollIntoViewIfNeeded();
  await shot(page, "time-to-limit-phone");
  expect(problems, "errors on the page").toEqual([]);
});
