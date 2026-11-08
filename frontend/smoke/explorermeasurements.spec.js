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
  await page.locator(".ms-panel").getByRole("button", { name: `Bearing ${tag}`, exact: true }).click();
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
  await expect(page.locator(".ms-panel .ms-trow")).toHaveCount(2);
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

// A setting (the pool's chlorinator output): a "Setting" chip with its value in
// the list, and in full a step chart and its changes ("Set to 60% … (from 45%)").
test("a setting shows its chip in the list, and steps and changes in full", async ({ page, request, problems }) => {
  const tag = `s${Date.now()}`;
  const post = (path, data) => postOk(request, path, data);
  const pool = await post(`${M}/positions`, { name: `Meas pool ${tag}` });
  const chl = await post(`${M}/positions/${pool.id}/points`, {
    name: `Chlorinator ${tag}`, kind: "setting", unit: "%", range_min: 0, range_max: 100 });
  await post(`${M}/points/${chl.id}/readings`, { value: 45, on: ago(200) });
  await post(`${M}/points/${chl.id}/readings`, { value: 60, on: ago(30) });
  await page.setViewportSize({ width: 1280, height: 800 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${pool.id}&tab=measurements`);
  const row = page.locator(".ms-panel .ms-trow").filter({ hasText: `Chlorinator ${tag}` });
  await expect(row.locator(".ms-c-kind")).toHaveText("Setting");
  await expect(row.locator(".ms-chip")).toHaveText(/^Set \d{1,2} \w{3} \d{4}$/);
  await expect(row.locator(".ms-c-latest strong")).toHaveText("60%");
  // A new setting typed in place: recorded now, the row shows it.
  await row.getByRole("textbox", { name: `New setting for Chlorinator ${tag} (%)` }).fill("70");
  await row.getByRole("textbox", { name: `New setting for Chlorinator ${tag} (%)` }).press("Enter");
  await expect(row.locator(".ms-rec-said")).toHaveText("✓ Set to 70%");
  await expect(row.locator(".ms-c-latest strong")).toHaveText("70%");
  // Outside its allowed range: refused in place, nothing recorded.
  await row.getByRole("textbox", { name: `New setting for Chlorinator ${tag} (%)` }).fill("140");
  await row.getByRole("textbox", { name: `New setting for Chlorinator ${tag} (%)` }).press("Enter");
  await expect(row.locator(".ms-rec-said")).toHaveText("Highest allowed is 100%");
  await row.getByRole("button", { name: `Chlorinator ${tag}`, exact: true }).click();
  await expect(view(page).getByRole("heading", { name: "What it's been over time" })).toBeVisible();
  await expect(view(page).locator(".mv-summary")).toContainText("Set 3 times since");
  await expect(view(page).locator(".js-plotly-plot")).toBeVisible();
  const shape = await view(page).locator(".js-plotly-plot").evaluate((el) => el.data?.[0]?.line?.shape);
  expect(shape).toBe("hv");
  await expect(view(page).locator(".mv-changes li").first()).toContainText(/^Set to 70% on .+ \(from 60%\) · by hand · still set/);
  const head = await headMenu(page);
  await expect(head.locator(".ovm-menu .ovm-item")).toContainText(["Record a change…", "Edit…", "Move…"]);
  await page.keyboard.press("Escape");
  await expectHealthy(page, problems, { label: "a setting in the Measurements tab" });
});

// The tab is a table of every point, setting and sensor below the row picked:
// grouped by position (each group folds), searched, sorted, a reading typed in
// place, and "Add a setting…" in the heading's "…" opens the dialog as a setting.
test("the Measurements table: groups, search, sort, a reading in place, add a setting", async ({ page, request, problems }) => {
  const tag = `t${Date.now()}`;
  const post = (path, data) => postOk(request, path, data);
  const plantRoot = await post(`${M}/positions`, { name: `Meas plant ${tag}` });
  const filter = await post(`${M}/positions`, { name: `Meas filter ${tag}`, parent_id: plantRoot.id });
  const heater = await post(`${M}/positions`, { name: `Meas heater ${tag}`, parent_id: plantRoot.id });
  const gauge = await post(`${M}/positions/${filter.id}/points`, {
    name: `Filter pressure ${tag}`, kind: "condition", unit: "kPa", alarm_above: 200, tag: `PT-${tag}` });
  await post(`${M}/points/${gauge.id}/readings`, { value: 120, on: ago(3) });
  const hot = await post(`${M}/positions/${heater.id}/points`, {
    name: `Water temp ${tag}`, kind: "condition", unit: "°C", alarm_above: 30 });
  await post(`${M}/points/${hot.id}/readings`, { value: 35, on: ago(1) });
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${plantRoot.id}&tab=measurements`);
  const panel = page.locator(".ms-panel");
  // Two positions below: a group row each, worst first (the hot water first).
  await expect(panel.locator(".ms-grow")).toHaveCount(2);
  await expect(panel.locator(".ms-gname")).toHaveText([`Meas heater ${tag}`, `Meas filter ${tag}`]);
  await expect(panel.locator(".ms-grow").first()).toContainText("1 point, 1 needs attention");
  await panel.getByRole("button", { name: new RegExp(`Meas heater ${tag}`) }).click();
  await expect(panel.locator(".ms-trow")).toHaveCount(1);
  await panel.getByRole("button", { name: new RegExp(`Meas heater ${tag}`) }).click();
  await expect(panel.locator(".ms-trow")).toHaveCount(2);
  // Search: the tag finds its point.
  await panel.getByRole("searchbox", { name: "Search the measurements" }).fill(`pt-${tag}`);
  await expect(panel.locator(".ms-trow")).toHaveCount(1);
  await expect.poll(() => query(page).get("q")).toBe(`pt-${tag}`);
  await panel.getByRole("searchbox", { name: "Search the measurements" }).fill("");
  // Sort by point name.
  await panel.getByRole("button", { name: /^Point: sort/ }).click();
  await expect.poll(() => query(page).get("sort")).toBe("point");
  // A reading typed in place.
  const row = panel.locator(".ms-trow").filter({ hasText: `Filter pressure ${tag}` });
  const box = row.getByRole("textbox", { name: `New reading for Filter pressure ${tag} (kPa)` });
  await box.fill("130");
  await box.press("Enter");
  await expect(row.locator(".ms-rec-said")).toHaveText("✓ Saved");
  await expect(row.locator(".ms-c-latest strong")).toHaveText("130 kPa");
  // The heading's "…": add a setting (the dialog opens as one).
  const head = await headMenu(page);
  await expect(head.locator(".ovm-menu .ovm-item")).toContainText(["Add a measuring point…", "Add a setting…", "Add a sensor channel…", "Columns…", "Export CSV"]);
  await head.locator(".ovm-menu .ovm-item", { hasText: "Add a setting…" }).click();
  await expect(page.getByRole("dialog", { name: "Add a setting" })).toBeVisible();
  await page.getByRole("dialog", { name: "Add a setting" }).getByRole("button", { name: "Cancel" }).click();
  // The row's ⋯.
  await row.getByRole("button", { name: `Actions for Filter pressure ${tag}` }).click();
  await expect(page.locator(".ovm-menu").last().getByRole("menuitem")).toHaveText(["Open", "Record a reading…", "Edit limits…", "Move…", "Retire…"]);
  await page.keyboard.press("Escape");
  await expectHealthy(page, problems, { label: "the Measurements table" });

  // At 400 px: the table scrolls in its card, the page doesn't.
  await page.setViewportSize({ width: 400, height: 860 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${plantRoot.id}&tab=measurements`);
  await page.getByRole("treeitem", { name: new RegExp(`^Meas plant ${tag}`) }).locator(".tp-nm").click();
  await expect(page.locator(".ms-panel .ms-trow")).toHaveCount(2);
  expect(await sideways(page)).toBeLessThanOrEqual(400);
});
