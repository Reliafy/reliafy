// A measuring point and a sensor channel open in full inside the Explorer's
// Measurements tab (?tab=measurements&point= or &channel=): the tree stays on
// the left, the panel shows the point (limits and state, chart, readings) with
// "← Measurements" back to the list, its actions in the heading's "…", and
// full screen works as on any tab. Their earlier own pages
// (/asset-register/points/:id, /asset-register/channels/:id) come here.
// Each test makes its own small plant through the API.
import { test, expect, open, expectHealthy, postOk } from "./health.js";
import { headMenu } from "./explorer.js";

const M = "/api/maintenance";
const ago = (days) => new Date(Date.now() - days * 86400000).toISOString().slice(0, 10);

async function plant(request, tag) {
  const post = (path, data) => postOk(request, path, data);
  const pump = await post(`${M}/positions`, { name: `Meas pump ${tag}` });
  const point = await post(`${M}/positions/${pump.id}/points`, {
    name: `Bearing ${tag}`, kind: "condition", unit: "mm/s", alarm_above: 7.1, alarm_below: 0.5 });
  for (const [days, value] of [[21, 2.8], [14, 3.0], [7, 3.3]]) {
    await post(`${M}/points/${point.id}/readings`, { value, on: ago(days) });
  }
  const channel = await post(`${M}/signals/channels`, { position_id: pump.id, name: `Plug ${tag}`, unit: "W", tag: `smoke.${tag}` });
  return { pump, point, channel };
}

const query = (page) => new URL(page.url()).searchParams;
const view = (page) => page.locator(".mv-view");
const sideways = (page) => page.evaluate(() => document.documentElement.scrollWidth);

test("a point opens in full in the Measurements tab, the tree still on the left", async ({ page, request, problems }) => {
  const tag = `p${Date.now()}`;
  const p = await plant(request, tag);
  await page.setViewportSize({ width: 1280, height: 800 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pump.id}&tab=measurements`);
  await page.locator(".ms-panel").getByRole("link", { name: `Bearing ${tag}` }).click();
  await expect.poll(() => query(page).get("point")).toBe(p.point.id);
  expect(query(page).get("sel")).toBe(p.pump.id);
  // The tree stays, its row picked; the panel shows the point.
  await expect(page.getByRole("treeitem", { name: new RegExp(`^Meas pump ${tag}`) })).toBeVisible();
  await expect(view(page).getByRole("heading", { name: `Bearing ${tag}` })).toBeVisible();
  await expect(view(page).locator(".js-plotly-plot")).toBeVisible();
  await expect(view(page).locator(".rt-row")).toHaveCount(3);
  await expect(view(page).getByText("Value (mm/s)")).toBeVisible();
  // Its actions are in the heading's "…".
  const head = await headMenu(page);
  await expect(head.locator(".ovm-menu .ovm-item")).toContainText(["Add reading…", "Edit limits…", "Move…"]);
  await page.keyboard.press("Escape");
  // Full screen, and back.
  await page.locator(".tt-headslot .tt-actions").getByRole("button", { name: "Full screen", exact: true }).click();
  await expect(view(page).getByRole("heading", { name: `Bearing ${tag}` })).toBeVisible();
  await page.getByRole("button", { name: "Exit full screen" }).click();
  // Back to the list.
  await view(page).getByRole("button", { name: "← Measurements" }).click();
  await expect.poll(() => query(page).get("point")).toBe(null);
  await expect(page.locator(".ms-panel .ms-row")).toHaveCount(2);
  await expectHealthy(page, problems, { label: "point in the Measurements tab" });
});

test("the earlier own pages of a point and a channel open them in the Explorer", async ({ page, request, problems }) => {
  const tag = `r${Date.now()}`;
  const p = await plant(request, tag);
  await page.setViewportSize({ width: 1280, height: 800 });
  await open(page, `/asset-register/points/${p.point.id}`);
  await expect.poll(() => new URL(page.url()).pathname).toBe("/asset-register/explorer");
  expect(query(page).get("point")).toBe(p.point.id);
  expect(query(page).get("sel")).toBe(p.pump.id);
  await expect(view(page).getByRole("heading", { name: `Bearing ${tag}` })).toBeVisible();

  await open(page, `/asset-register/channels/${p.channel.id}`);
  await expect.poll(() => query(page).get("channel")).toBe(p.channel.id);
  await expect(view(page).getByRole("heading", { name: `Plug ${tag}` })).toBeVisible();
  await expect(view(page).getByRole("button", { name: "← Measurements" })).toBeVisible();
  await expectHealthy(page, problems, { label: "channel in the Measurements tab" });
});

test("a point in full at 400 px: the panel sheet, nothing scrolls sideways", async ({ page, request }) => {
  const tag = `m${Date.now()}`;
  const p = await plant(request, tag);
  await page.setViewportSize({ width: 400, height: 860 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pump.id}&tab=measurements&point=${p.point.id}`);
  // On a phone the panel is its own screen: tap the row to open it.
  await page.getByRole("treeitem", { name: new RegExp(`^Meas pump ${tag}`) }).locator(".tp-nm").click();
  await expect(view(page).getByRole("heading", { name: `Bearing ${tag}` })).toBeVisible();
  await expect(view(page).locator(".rt-row")).toHaveCount(3);
  expect(await sideways(page)).toBeLessThanOrEqual(400);
});
