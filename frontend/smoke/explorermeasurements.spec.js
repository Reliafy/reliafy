// The Explorer's Measurements tab is a tree-table like the RCM tab (Derryn,
// 9 Nov 2026): the position tree is the first column and each position's
// measuring points, settings, sensor channels and consumables hang under it,
// with Kind, Latest, State, Trend, Next due and a Record box beside them. A
// position rolls up its rows ("2 points · 1 needs attention"). Picking a row
// opens its details beside the table (history, chart, changes, additions);
// ?point= opens one from a link, and the earlier own pages come here. A value
// typed in Record is recorded now; a consumable's quantity is a use, out of
// stock. Each test makes its own small plant through the API.
import { test, expect, open, expectHealthy, postOk } from "./health.js";
import { headMenu } from "./explorer.js";

const M = "/api/maintenance";
const ago = (d) => new Date(Date.now() - d * 864e5).toISOString().slice(0, 10);
const query = (page) => new URL(page.url()).searchParams;
const row = (page, key) => page.locator(`.tp-row[data-key="${key}"]`);
const side = (page) => page.locator(".mt-panel");
const sideways = (page) => page.evaluate(() => document.documentElement.scrollWidth);

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

test("a point hangs under its position in the tree-table, and opens beside it", async ({ page, request, problems }) => {
  const tag = `p${Date.now()}`;
  const p = await plant(request, tag);
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pump.id}&tab=measurements`);
  const grid = page.getByRole("treegrid", { name: /and their measurements/ });
  await expect(grid).toBeVisible();
  const pos = row(page, p.pump.id);
  await expect(pos.locator(".tt-rollup-t")).toHaveText("2 points");
  const bearing = row(page, `M:${p.point.id}`);
  await expect(bearing.locator(".tp-nm")).toHaveText(`Bearing ${tag}`);
  await expect(bearing.locator(".mt-c-kind")).toHaveText("Condition");
  await expect(bearing.locator(".mt-latest strong")).toHaveText("3.3 mm/s");
  await expect(row(page, `M:channel:${p.channel.id}`).locator(".mt-c-kind")).toHaveText("Fed");
  // Picked: its details beside the table, its actions in the heading's "…".
  await bearing.locator(".tp-nm").click();
  await expect(side(page).getByRole("heading", { name: `Bearing ${tag}` })).toBeVisible();
  await expect(side(page).locator(".rt-row")).toHaveCount(3);
  await expect(side(page).locator(".js-plotly-plot")).toBeVisible();
  const head = await headMenu(page);
  await expect(head.locator(".ovm-menu .ovm-item")).toContainText(["Add a measuring point…", "Add a setting…", "Add a consumable…",
    "Add a sensor channel…", "Columns…", "Export CSV", "Add reading…", "Edit limits…", "Move…"]);
  await page.keyboard.press("Escape");
  // Full screen, and back.
  await page.locator(".tt-headslot .tt-actions").getByRole("button", { name: "Full screen", exact: true }).click();
  await expect(bearing).toBeVisible();
  await page.getByRole("button", { name: "Exit full screen" }).click();
  // Closed: the position rolls up what's inside it; open again, its rows show.
  await pos.locator(".tp-chev").click();
  await expect(bearing).toHaveCount(0);
  await pos.locator(".tp-chev").click();
  await expect(bearing).toBeVisible();
  await expectHealthy(page, problems, { label: "Measurements tree-table" });
});

test("a link to a point, and the earlier own pages, open it beside the tree", async ({ page, request, problems }) => {
  const tag = `r${Date.now()}`;
  const p = await plant(request, tag);
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, `/asset-register/points/${p.point.id}`);
  await expect.poll(() => new URL(page.url()).pathname).toBe("/asset-register/explorer");
  expect(query(page).get("point")).toBe(p.point.id);
  expect(query(page).get("sel")).toBe(p.pump.id);
  await expect(side(page).getByRole("heading", { name: `Bearing ${tag}` })).toBeVisible();
  await expect(row(page, `M:${p.point.id}`)).toHaveAttribute("aria-selected", "true");

  await open(page, `/asset-register/channels/${p.channel.id}`);
  await expect.poll(() => query(page).get("channel")).toBe(p.channel.id);
  await expect(side(page).getByRole("heading", { name: `Plug ${tag}` })).toBeVisible();
  await expectHealthy(page, problems, { label: "a channel beside the tree" });
});

test("the tree-table at 400 px: rows with their line under, a row's details as a sheet, nothing sideways", async ({ page, request }) => {
  const tag = `m${Date.now()}`;
  const p = await plant(request, tag);
  await page.setViewportSize({ width: 400, height: 860 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pump.id}&tab=measurements`);
  const bearing = row(page, `M:${p.point.id}`);
  await expect(bearing.locator(".tt-l2")).toContainText("Condition · 3.3 mm/s");
  expect(await sideways(page)).toBeLessThanOrEqual(400);
  await bearing.locator(".tp-nm").click();
  await expect(side(page).getByRole("heading", { name: `Bearing ${tag}` })).toBeVisible();
  await expect(side(page).locator(".rt-row")).toHaveCount(3);
  expect(await sideways(page)).toBeLessThanOrEqual(400);
});

// A setting (the pool's chlorinator output): set in place, refused outside its
// range, and in its details what it's been over time and each change.
test("a setting: set in place, a refusal in place, and its changes beside the tree", async ({ page, request, problems }) => {
  const tag = `s${Date.now()}`;
  const post = (path, data) => postOk(request, path, data);
  const pool = await post(`${M}/positions`, { name: `Meas pool ${tag}` });
  const chl = await post(`${M}/positions/${pool.id}/points`, {
    name: `Chlorinator ${tag}`, kind: "setting", unit: "%", range_min: 0, range_max: 100 });
  await post(`${M}/points/${chl.id}/readings`, { value: 45, on: ago(200) });
  await post(`${M}/points/${chl.id}/readings`, { value: 60, on: ago(30) });
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${pool.id}&tab=measurements`);
  const r = row(page, `M:${chl.id}`);
  await expect(r.locator(".mt-c-kind")).toHaveText("Setting");
  await expect(r.locator(".ms-chip")).toHaveText(/^Set \d{1,2} \w{3} \d{4}$/);
  await expect(r.locator(".mt-latest strong")).toHaveText("60%");
  const box = r.getByRole("textbox", { name: `New setting for Chlorinator ${tag} (%)` });
  await box.fill("70");
  await box.press("Enter");
  await expect(r.locator(".ms-rec-said")).toHaveText("✓ Set to 70%");
  await expect(r.locator(".mt-latest strong")).toHaveText("70%");
  await box.fill("140");
  await box.press("Enter");
  await expect(r.locator(".ms-rec-said")).toHaveText("Highest allowed is 100%");
  await r.locator(".tp-nm").click();
  await expect(side(page).getByRole("heading", { name: "What it's been over time" })).toBeVisible();
  await expect(side(page).locator(".mv-summary").first()).toContainText("Set 3 times since");
  await expect(side(page).locator(".mv-changes li").first()).toContainText(/^Set to 70% on .+ \(from 60%\) · by hand · still set/);
  const shape = await side(page).locator(".js-plotly-plot").evaluate((el) => el.data?.[0]?.line?.shape);
  expect(shape).toBe("hv");
  await expectHealthy(page, problems, { label: "a setting in the Measurements tab" });
});

// Several positions below: each rolls up its rows, the search opens the way down
// to its matches, Needs attention keeps the rows that need a look, and a reading
// typed in place is recorded now.
test("roll-ups, the search, Needs attention, a reading in place, the row's ⋯", async ({ page, request, problems }) => {
  const tag = `t${Date.now()}`;
  const post = (path, data) => postOk(request, path, data);
  const root = await post(`${M}/positions`, { name: `Meas plant ${tag}` });
  const filter = await post(`${M}/positions`, { name: `Meas filter ${tag}`, parent_id: root.id });
  const heater = await post(`${M}/positions`, { name: `Meas heater ${tag}`, parent_id: root.id });
  const gauge = await post(`${M}/positions/${filter.id}/points`, {
    name: `Filter pressure ${tag}`, kind: "condition", unit: "kPa", alarm_above: 200, tag: `PT-${tag}` });
  await post(`${M}/points/${gauge.id}/readings`, { value: 120, on: ago(3) });
  const hot = await post(`${M}/positions/${heater.id}/points`, { name: `Water temp ${tag}`, kind: "condition", unit: "°C", alarm_above: 30 });
  await post(`${M}/points/${hot.id}/readings`, { value: 35, on: ago(1) });
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${root.id}&tab=measurements`);
  await expect(page.locator(".tt-headslot .mt-rollup")).toHaveText("2 points · 1 needs attention");
  await expect(row(page, heater.id).locator(".tt-rollup-t")).toHaveText("1 point · 1 needs attention");
  // The search: the tag finds its point, the way down to it open.
  const search = page.getByRole("searchbox", { name: "Filter the tree and its measurements" });
  await search.fill(`pt-${tag}`);
  await expect(row(page, `M:${gauge.id}`)).toBeVisible();
  await expect(row(page, `M:${hot.id}`)).toHaveCount(0);
  await search.fill("");
  // Needs attention (the tree's Show only).
  await page.getByRole("button", { name: /^Tree options/ }).click();
  const options = page.getByRole("menu", { name: "Tree options" });
  await options.getByRole("menuitemcheckbox", { name: "Needs attention" }).click();
  await options.getByRole("menuitem", { name: "Done" }).click();
  await expect(row(page, `M:${hot.id}`)).toBeVisible();
  await expect(row(page, `M:${gauge.id}`)).toHaveCount(0);
  await page.getByRole("button", { name: /^Tree options/ }).click();
  await options.getByRole("menuitemcheckbox", { name: "Needs attention" }).click();
  await options.getByRole("menuitem", { name: "Done" }).click();
  // A reading typed in place.
  const r = row(page, `M:${gauge.id}`);
  if (!(await r.count())) await row(page, filter.id).locator(".tp-chev").click();
  const box = r.getByRole("textbox", { name: `New reading for Filter pressure ${tag} (kPa)` });
  await box.fill("130");
  await box.press("Enter");
  await expect(r.locator(".ms-rec-said")).toHaveText("✓ Saved");
  await expect(r.locator(".mt-latest strong")).toHaveText("130 kPa");
  // The row's ⋯.
  await r.locator(".tp-nm").click({ button: "right" });
  await expect(page.getByRole("menu").last().getByRole("menuitem")).toContainText(["Open", "Record a reading…", "Edit limits…", "Move…", "Retire…"]);
  await page.keyboard.press("Escape");
  await expectHealthy(page, problems, { label: "the Measurements tree-table" });
});

// A consumable (salt into the pool): a row with its last addition, its 90-day
// total and monthly bars; a quantity typed in Record adds a use today, out of
// stock; picked, what's been added over time with the LSA's dose beside it.
// Add a consumable… in the heading's "…" puts a part from the register on it.
test("consumables: a row, a use typed in place out of stock, its additions beside the tree, Add a consumable…", async ({ page, request, problems }) => {
  const tag = `c${Date.now()}`;
  const post = (path, data) => postOk(request, path, data);
  const pool = await post(`${M}/positions`, { name: `Meas pool ${tag}` });
  const shed = await post(`${M}/locations`, { name: `Pool shed ${tag}` });
  await request.patch(`${M}/positions/${pool.id}`, { data: { location_id: shed.id } });
  const salt = await post(`${M}/parts`, { part_number: `SALT-${tag}`, name: `Pool salt ${tag}`, unit: "kg", unit_cost: 0.6 });
  await post(`${M}/parts/${salt.id}/stock`, { location_id: shed.id, delta: 100, reason: "delivered" });
  await post(`${M}/positions/${pool.id}/parts`, { part_id: salt.id, role: "consumable" });
  const task = await post(`${M}/positions/${pool.id}/tasks`, { name: `Top up salt ${tag}`, interval: 1, unit: "months" });
  await request.patch(`${M}/tasks/${task.id}`, { data: { resources: { consumables: [{ name: `Pool salt ${tag}`, qty: 20, unit: "kg" }] } } });
  await post(`${M}/positions/${pool.id}/consumables`, { part_id: salt.id, qty: 20, on: ago(20) });
  await post(`${M}/parts`, { part_number: `ACID-${tag}`, name: `Acid ${tag}`, unit: "L" });

  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${pool.id}&tab=measurements`);
  const r = row(page, `M:consumable:${pool.id}:part:${salt.id}`);
  await expect(r.locator(".mt-c-kind")).toHaveText("Consumable");
  await expect(r.locator(".mt-latest strong")).toHaveText("20 kg");
  await expect(r.locator(".ms-chip")).toHaveText(/^20 kg since /);
  await expect(r.locator(".ms-chip")).toHaveAttribute("title", /80 kg at Pool shed/);
  const box = r.getByRole("textbox", { name: `Quantity of Pool salt ${tag} added (kg)` });
  await box.fill("10");
  await box.press("Enter");
  await expect(r.locator(".ms-rec-said")).toHaveText("✓ Added 10 kg");
  await expect(r.locator(".ms-chip")).toHaveText(/^30 kg since /);
  await expect(r.locator(".ms-chip")).toHaveAttribute("title", /70 kg at Pool shed/);
  await r.locator(".tp-nm").click();
  await expect(side(page).getByRole("heading", { name: "What's been added over time" })).toBeVisible();
  await expect(side(page).getByText(/^The LSA says 20 kg every month \(Top up salt .+\); 30 kg were added in the last month\.$/)).toBeVisible();
  await expect(side(page).locator(".mv-changes li")).toHaveCount(2);
  await expect(side(page).locator(".mv-changes li").first()).toContainText("10 kg on");
  await expect(side(page).locator(".mv-changes li").first()).toContainText("by hand");
  await expect(side(page).locator(".mv-changes li").first()).toContainText(`from Pool shed ${tag}`);
  // Add a consumable… from the register.
  const head = await headMenu(page);
  await head.locator(".ovm-menu .ovm-item", { hasText: "Add a consumable…" }).click();
  const dialog = page.getByRole("dialog", { name: "Add a consumable" });
  await dialog.getByRole("combobox", { name: "Part" }).selectOption({ label: `ACID-${tag} Acid ${tag} (L)` });
  await dialog.getByRole("button", { name: "Add" }).click();
  await expect(page.locator(".tp-row", { hasText: `Acid ${tag}` }).locator(".ms-chip")).toHaveText("Never added");
  await expectHealthy(page, problems, { label: "consumables in the Measurements tab" });
});

// As an RCM row: a click opens the details beside the table, a double-click on
// the name (or Open in the row's ⋯, or Enter) spreads them across it with the
// tree kept, selecting no text; Esc puts them beside it again. The same for a
// setting, a channel and a consumable.
test("a double-click on a measurement row's name spreads its details across the table, as on the RCM tab", async ({ page, request, problems }) => {
  const tag = `d${Date.now()}`;
  const p = await plant(request, tag);
  const setting = await postOk(request, `${M}/positions/${p.pump.id}/points`, { name: `Dose ${tag}`, kind: "setting", unit: "%" });
  await postOk(request, `${M}/points/${setting.id}/readings`, { value: 40, on: ago(5) });
  await postOk(request, `${M}/positions/${p.pump.id}/consumables`, { name: `Salt ${tag}`, unit: "kg", qty: 20, on: ago(3) });
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${p.pump.id}&tab=measurements`);
  const heads = page.getByRole("treegrid", { name: /and their measurements/ }).getByRole("columnheader");
  const columns = await heads.count();
  const spread = () => side(page).evaluate((el) => el.classList.contains("is-expanded"));
  const selected = () => page.evaluate(() => String(window.getSelection?.() || ""));
  const bearing = row(page, `M:${p.point.id}`);
  // A click: beside the table.
  await bearing.locator(".tp-nm").click();
  await expect(side(page).getByRole("heading", { name: `Bearing ${tag}` })).toBeVisible();
  expect(await spread()).toBe(false);
  for (const [key, name] of [[`M:${p.point.id}`, `Bearing ${tag}`], [`M:${setting.id}`, `Dose ${tag}`],
    [`M:channel:${p.channel.id}`, `Plug ${tag}`], [`M:consumable:${p.pump.id}:name:salt ${tag}`, `Salt ${tag}`]]) {
    await row(page, key).locator(".tp-nm").dblclick();
    await expect(side(page).getByRole("heading", { name, level: 2 })).toBeFocused();
    expect(await spread(), `${name}: spread`).toBe(true);
    await expect(heads).toHaveCount(1);
    expect(await selected(), `${name}: no text selected`).toBe("");
    // Esc: beside the table again, the focus on the row.
    await page.keyboard.press("Escape");
    expect(await spread()).toBe(false);
    await expect(heads).toHaveCount(columns);
    await expect(row(page, key)).toBeFocused();
  }
  // Open in the row's ⋯ spreads them too; Enter on the row as well.
  await bearing.locator(".tp-nm").click({ button: "right" });
  await page.getByRole("menu").last().getByRole("menuitem", { name: "Open" }).click();
  expect(await spread()).toBe(true);
  await page.keyboard.press("Escape");
  await bearing.focus();
  await page.keyboard.press("Enter");
  await expect(side(page).getByRole("heading", { name: `Bearing ${tag}`, level: 2 })).toBeFocused();
  expect(await spread()).toBe(true);
  await page.keyboard.press("Escape");
  await expectHealthy(page, problems, { label: "Measurements rows spread as RCM rows" });
});
