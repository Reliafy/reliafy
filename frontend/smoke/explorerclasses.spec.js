// The Explorer by Classes on one asset's tree, and a class's one tab. Two
// assets carry items of one item class; opened on one of them (?root=), the
// class tree, its count, "No class" and the class's fleet cover only the
// positions inside that asset, while the whole Explorer covers both. A class
// row has a tab bar with one tab, Condition monitoring: its fleet. Choosing
// Classes with a row of an asset picked (an asset opened from the Assets page)
// opens Classes on that asset alone. A position
// on an asset has the tab too, in every arrangement: its own risk now in words
// and two charts, or what's missing in words; the tab stays from a class to a
// position and on to the next. A design's positions don't have it.
import { test, expect, open, expectHealthy, postOk } from "./health.js";
import { details, reveal } from "./explorer.js";

const M = "/api/maintenance";
const SHOTS = process.env.SMOKE_SHOTS_DIR || "";
const shot = async (page, name) => {
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}.png` });
};
const sideways = (page) => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
const row = (page, name) => page.getByRole("treeitem", { name: new RegExp(`^${name}`) });
const arrangeSwitch = (page) => page.getByRole("radiogroup", { name: "Arrange by" });

// One asset: a top position with `n` pump positions under it, each with an item of the class fitted.
async function asset(request, name, tag, cls, n) {
  const top = await postOk(request, `${M}/positions`, { name: `${name} ${tag}` });
  const pumps = [];
  for (let i = 1; i <= n; i += 1) {
    const pos = await postOk(request, `${M}/positions`, { name: `${name} pump ${i} ${tag}`, parent_id: top.id });
    await postOk(request, `${M}/positions/${pos.id}/fit`, { new_item: { name: `${name} pump unit ${i} ${tag}`, serial: `${name}-${i}-${tag}` } });
    const item = (await (await request.get(`${M}/positions/${pos.id}`)).json()).fitted.item;
    await postOk(request, `${M}/item-classes/assign`, { target_id: item.id, item_class_id: cls.id });
    pumps.push(pos);
  }
  return { top, pumps };
}

// One asset whose three pumps cover what a position's Condition monitoring tab can say: `scored`
// (a condition and life model linked, an item 90 days old, three vibration readings and its load:
// a risk now), `unread` (the model linked, nothing to read: the reason in words) and `bare` (no
// model: how to link one). The model is the shared sample; its load comes from a value condition
// matched by its code, named for this run (the suite shares one workspace).
const JOINT = "sample-joint-feed-pumps";
async function monitored(request, tag) {
  const today = (await (await request.get(`${M}/tree`)).json()).today;
  const ago = (days) => new Date(Date.parse(`${today}T00:00:00Z`) - days * 86400000).toISOString().slice(0, 10);
  const cls = await postOk(request, `${M}/item-classes`, { name: `Feed pump ${tag}` });
  const top = await postOk(request, `${M}/positions`, { name: `Boiler house ${tag}` });
  const pump = async (name) => {
    const pos = await postOk(request, `${M}/positions`, { name: `${name} ${tag}`, parent_id: top.id });
    const fit = await postOk(request, `${M}/positions/${pos.id}/fit`, {
      new_item: { name: `${name} unit ${tag}`, serial: `${name.replace(/\s+/g, "-")}-${tag}`, in_service_date: ago(90) }, on: ago(90),
    });
    await postOk(request, `${M}/item-classes/assign`, { target_id: fit.fitted.item.id, item_class_id: cls.id });
    return pos;
  };
  const scored = await pump("Feed pump A");
  const unread = await pump("Feed pump B");
  const bare = await pump("Feed pump C");
  const point = await postOk(request, `${M}/positions/${scored.id}/points`, { name: "Vibration", kind: "condition", unit: "mm/s" });
  for (const [value, days] of [[2.1, 90], [2.9, 45], [3.7, 0]]) await postOk(request, `${M}/points/${point.id}/readings`, { value, on: ago(days) });
  const load = await postOk(request, `${M}/conditions`, { name: `Load ${tag}`, kind: "value", code: "load" });
  await postOk(request, `${M}/conditions/of/${scored.id}`, { condition_id: load.id, value: 1 });
  for (const pos of [scored, unread]) await postOk(request, `${M}/positions/${pos.id}/models`, { model_id: JOINT });
  return { cls, top, scored, unread, bare };
}

test("Classes on one asset's tree covers only that asset; a class opens on Condition monitoring", async ({ page, request, problems }) => {
  const tag = `c${Date.now()}`;
  const cls = await postOk(request, `${M}/item-classes`, { name: `Dosing pump ${tag}` });
  const north = await asset(request, "North", tag, cls, 2);
  const south = await asset(request, "South", tag, cls, 1);
  const clsKey = `cls:${cls.id}`;
  const classRow = row(page, `Dosing pump ${tag}`);
  const panel = details(page);

  // North's asset by Classes: the class counts North's two positions (not South's), and its fleet lists them.
  await open(page, `/asset-register/explorer?arrange=classes&root=${north.top.id}&sel=${encodeURIComponent(clsKey)}`);
  await reveal(page, classRow);
  await expect(classRow).toHaveAttribute("aria-selected", "true");
  await expect(classRow.locator(".tp-cnt")).toHaveText("2 positions");
  await expect(page.locator(".cf-answer")).toContainText("2 positions");

  // A class has a tab bar with one tab, picked without being asked for.
  const tabs = panel.getByRole("tab");
  await expect(tabs).toHaveCount(1);
  await expect(tabs).toHaveText("Condition monitoring");
  await expect(tabs).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("region", { name: "Risk now" })).toBeVisible();

  // One asset opened: Classes is offered, and covers only what's inside it.
  await open(page, `/asset-register/explorer?arrange=positions&root=${north.top.id}`);
  const sw = arrangeSwitch(page);
  await expect(sw.getByRole("radio", { name: "Positions" })).toHaveAttribute("aria-checked", "true");
  await sw.getByRole("radio", { name: "Locations" }).click();
  await expect(page).toHaveURL(/arrange=locations/);
  await sw.getByRole("radio", { name: "Classes" }).click();
  await expect(page).toHaveURL(new RegExp(`root=${north.top.id}`));
  await expect(page).toHaveURL(/arrange=classes/);
  await expect(page.getByRole("tree", { name: "Classes" })).toBeVisible();
  await expect(classRow.locator(".tp-cnt")).toHaveText("2 positions");
  await expect(row(page, `South pump 1 ${tag}`)).toHaveCount(0);
  // "No class": the asset's own top position, and nothing from the rest of the register.
  const noClass = row(page, "No class");
  await expect(noClass).toBeVisible();
  await expect(page.getByRole("treeitem")).toHaveCount(5); // the class, its two positions, No class, the top
  await classRow.click();
  await expect(page.locator(".cf-answer")).toContainText("2 positions");
  const fleet = page.getByRole("region", { name: "Risk now" });
  await expect(fleet.getByRole("button", { name: `North pump 1 ${tag}` })).toBeVisible();
  await expect(fleet.getByRole("button", { name: `North pump 2 ${tag}` })).toBeVisible();
  await expect(fleet.getByRole("button", { name: `South pump 1 ${tag}` })).toHaveCount(0);
  await expect(fleet).toContainText("None of these positions has a condition and life model");
  await shot(page, "classes-one-asset-1440");

  // The address holds through a reload.
  await page.reload();
  await expect(sw.getByRole("radio", { name: "Classes" })).toHaveAttribute("aria-checked", "true");
  await expect(classRow.locator(".tp-cnt")).toHaveText("2 positions");
  await expect(page.locator(".cf-answer")).toContainText("2 positions");
  // From the class to one of its positions: the class's tab stays, on the position's own tabs.
  await fleet.getByRole("button", { name: `North pump 1 ${tag}` }).click();
  await expect(row(page, `North pump 1 ${tag}`)).toHaveAttribute("aria-selected", "true");
  await expect(panel.getByRole("tab", { name: "Condition monitoring" })).toHaveAttribute("aria-selected", "true");
  await expect(panel.getByRole("tab", { name: "Summary" })).toHaveAttribute("aria-selected", "false");
  await expect(panel.getByRole("region", { name: "This position's risk now" })).toContainText("no condition and life model is linked to this position");

  // Another tab in the address: the class still shows its own, and a position walked to shows the one asked for.
  await open(page, `/asset-register/explorer?arrange=classes&root=${north.top.id}&sel=${encodeURIComponent(clsKey)}&tab=reports`);
  await expect(panel.getByRole("tab", { name: "Condition monitoring" })).toHaveAttribute("aria-selected", "true");
  await expect(page.locator(".cf-answer")).toContainText("2 positions");
  await fleet.getByRole("button", { name: `North pump 2 ${tag}` }).click();
  await expect(row(page, `North pump 2 ${tag}`)).toHaveAttribute("aria-selected", "true");
  await expect(panel.getByRole("tab", { name: "Failure reports" })).toHaveAttribute("aria-selected", "true");

  // A tree-table's tab in the address (they're by position) doesn't take the tree off the class.
  await open(page, `/asset-register/explorer?arrange=classes&root=${north.top.id}&sel=${encodeURIComponent(clsKey)}&tab=rcm`);
  await expect(sw.getByRole("radio", { name: "Classes" })).toHaveAttribute("aria-checked", "true");
  await expect(classRow).toHaveAttribute("aria-selected", "true");
  await expect(panel.getByRole("tab", { name: "Condition monitoring" })).toHaveAttribute("aria-selected", "true");
  await expect(page.locator(".cf-answer")).toContainText("2 positions");

  // South's asset: its one position, nothing of North's.
  await open(page, `/asset-register/explorer?arrange=classes&root=${south.top.id}&sel=${encodeURIComponent(clsKey)}`);
  await reveal(page, classRow);
  await expect(classRow.locator(".tp-cnt")).toHaveText("1 position");

  await expectHealthy(page, problems, { label: "the Explorer by Classes on one asset" });
});

test("an asset opened from Assets, then Classes: only that asset's classes, counts and fleet", async ({ page, request, problems }) => {
  // Two places you look after, each a plant with pumps; one item class in both, one in the pool's only.
  const tag = `a${Date.now()}`;
  const shared = await postOk(request, `${M}/item-classes`, { name: `Booster pump ${tag}` });
  const poolOnly = await postOk(request, `${M}/item-classes`, { name: `Pool pump ${tag}` });
  const site = async (name, classes) => {
    const loc = await postOk(request, `${M}/locations`, { name: `${name} ${tag}` });
    const top = await postOk(request, `${M}/positions`, { name: `${name} plant ${tag}`, location_id: loc.id });
    for (const [i, cls] of classes.entries()) {
      const pos = await postOk(request, `${M}/positions`, { name: `${name} pump ${i + 1} ${tag}`, parent_id: top.id });
      const fit = await postOk(request, `${M}/positions/${pos.id}/fit`, { new_item: { name: `${name} unit ${i + 1} ${tag}`, serial: `${name}-${i}-${tag}` } });
      await postOk(request, `${M}/item-classes/assign`, { target_id: fit.fitted.item.id, item_class_id: cls.id });
    }
    return { loc, top };
  };
  const river = await site("Riverside", [shared, shared]);
  await site("Pool", [shared, poolOnly]);
  const sw = arrangeSwitch(page);

  // From the Assets page's link (the Explorer by Locations, the place picked), then Classes.
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, `/asset-register/explorer?arrange=locations&sel=${river.loc.id}`);
  await expect(row(page, `Riverside ${tag}`)).toHaveAttribute("aria-selected", "true");
  await sw.getByRole("radio", { name: "Classes" }).click();
  await expect(page).toHaveURL(new RegExp(`root=${river.loc.id}`));
  await expect(page).toHaveURL(/arrange=classes/);
  const sharedRow = row(page, `Booster pump ${tag}`);
  await expect(sharedRow.locator(".tp-cnt")).toHaveText("2 positions");
  await expect(row(page, `Pool pump ${tag}`)).toHaveCount(0);
  await expect(row(page, `Pool pump 1 ${tag}`)).toHaveCount(0);
  await expect(page.getByRole("treeitem")).toHaveCount(5); // the class, its two pumps, No class, the plant
  await sharedRow.click();
  await expect(page.locator(".cf-answer")).toContainText("2 positions");
  const fleet = page.getByRole("region", { name: "Risk now" });
  await expect(fleet.getByRole("button", { name: `Riverside pump 1 ${tag}` })).toBeVisible();
  await expect(fleet.getByRole("button", { name: `Pool pump 1 ${tag}` })).toHaveCount(0);
  await shot(page, "classes-asset-from-assets-1440");
  // By Locations again: still that one asset.
  await sw.getByRole("radio", { name: "Locations" }).click();
  await expect(page).toHaveURL(new RegExp(`root=${river.loc.id}`));
  await expect(row(page, `Riverside plant ${tag}`)).toBeVisible();
  await expect(row(page, `Pool ${tag}`)).toHaveCount(0);

  await expectHealthy(page, problems, { label: "Classes on an asset opened from Assets" });
});

test("a class on a phone: its heading, its one tab and the way back fit 400 px", async ({ page, request, problems }) => {
  const tag = `p${Date.now()}`;
  const cls = await postOk(request, `${M}/item-classes`, { name: `Transfer pump ${tag}` });
  const north = await asset(request, "East", tag, cls, 2);
  await page.setViewportSize({ width: 400, height: 800 });
  await open(page, `/asset-register/explorer?arrange=classes&root=${north.top.id}`);
  await expect(arrangeSwitch(page).getByRole("radio", { name: "Classes" })).toHaveAttribute("aria-checked", "true");
  await expect.poll(() => sideways(page)).toBeLessThanOrEqual(0);
  await shot(page, "classes-one-asset-tree-400");
  await row(page, `Transfer pump ${tag}`).locator(".tp-nm").click();
  const panel = page.getByRole("region", { name: "Details" });
  await expect(panel.getByRole("heading", { name: `Transfer pump ${tag}` })).toBeVisible();
  await expect(panel.getByRole("button", { name: /Explorer/ })).toBeVisible();
  const tabs = panel.getByRole("tab");
  await expect(tabs).toHaveCount(1);
  await expect(tabs).toHaveText("Condition monitoring");
  await expect(panel.locator(".cf-answer")).toContainText("2 positions");
  await expect.poll(() => sideways(page)).toBeLessThanOrEqual(0);
  await shot(page, "class-condition-tab-400");
  // The way back: the tree again, by Classes, on the same asset.
  await panel.getByRole("button", { name: /Explorer/ }).click();
  await expect(row(page, `Transfer pump ${tag}`)).toBeVisible();
  await expect(page).toHaveURL(/arrange=classes/);
  await expectHealthy(page, problems, { label: "a class on a phone" });
});

test("a position's Condition monitoring: its risk in words and two charts, or what's missing; the tab stays as you walk", async ({ page, request, problems }) => {
  const tag = `m${Date.now()}`;
  const { cls, top, scored, unread, bare } = await monitored(request, tag);
  const panel = details(page);
  const tabOn = panel.getByRole("tab", { name: "Condition monitoring" });
  const risk = panel.getByRole("region", { name: "This position's risk now" });
  const rowA = row(page, `Feed pump A ${tag}`);
  const rowB = row(page, `Feed pump B ${tag}`);
  const rowC = row(page, `Feed pump C ${tag}`);
  await page.setViewportSize({ width: 1440, height: 900 });

  // The class first: its fleet, and the member at highest risk drawn by the same summary and charts.
  await open(page, `/asset-register/explorer?arrange=classes&root=${top.id}`);
  await row(page, `Feed pump ${tag}`).click();
  await expect(page.locator(".cf-answer")).toContainText("3 positions");
  const chosen = panel.getByRole("region", { name: "The chosen position's prediction" });
  await expect(chosen.locator(".joint-unit-sum")).toContainText("age 90 days, 3 readings.");
  await expect(chosen.locator(".js-plotly-plot .main-svg").first()).toBeVisible({ timeout: 20_000 });
  await expect(page).not.toHaveURL(/tab=/);
  await shot(page, "class-fleet-with-risk-1440");

  // Class → position: the class's tab stays, now the position's own risk, in words and then two charts.
  await page.getByRole("region", { name: "Risk now" }).getByRole("button", { name: `Feed pump A ${tag}` }).click();
  await expect(rowA).toHaveAttribute("aria-selected", "true");
  await expect(tabOn).toHaveAttribute("aria-selected", "true");
  await expect(tabOn).toHaveAttribute("title", /^This position's risk now/);
  await expect(page).toHaveURL(/tab=condition/);
  const words = risk.locator(".joint-unit-sum");
  await expect(words).toContainText(`Position Feed pump A ${tag}, age 90 days, 3 readings.`);
  for (const horizon of ["30 days", "90 days", "365 days"]) await expect(words).toContainText(`chance of failing in the next ${horizon}`);
  // The median now carries its one-sided 90% lower bound (#821).
  await expect(words).toContainText(/Median life left: (not reached|[\d.,]+ days( \((at least [\d.,]+ days, 90%|no 90% bound here)\))?)\./);
  await expect(risk.getByRole("heading", { name: "Survival from now" })).toBeVisible();
  await expect(risk.getByRole("heading", { name: /^Its / })).toBeVisible();
  await expect(risk.locator(".js-plotly-plot .main-svg").nth(1)).toBeVisible({ timeout: 20_000 });
  await expect(risk).toContainText(`Worked out from the item fitted here, Feed pump A unit ${tag}`);
  await expect(risk).not.toContainText(/NaN|Infinity|undefined/);
  await expect.poll(() => sideways(page)).toBeLessThanOrEqual(0);
  await shot(page, "position-condition-scored-1440");

  // Position → another position: the tab stays. A model with nothing to read says why.
  await rowB.click();
  await expect(rowB).toHaveAttribute("aria-selected", "true");
  await expect(tabOn).toHaveAttribute("aria-selected", "true");
  await expect(risk).toContainText("can't score this position");
  await expect(risk).toContainText("No measurement point for");
  await expect(risk.getByRole("link", { name: /feed pumps/i })).toBeVisible();
  await expect(risk.getByRole("button", { name: "Open the Modelling tab" })).toHaveCount(0);
  await shot(page, "position-condition-not-scored-1440");

  // And the next: no model linked says so, and how to link one.
  await rowC.click();
  await expect(tabOn).toHaveAttribute("aria-selected", "true");
  await expect(risk).toContainText("No risk to show yet: no condition and life model is linked to this position.");
  await expect(risk).toContainText("open this position's Modelling tab");
  await expect(risk).toContainText(`Fitted here: Feed pump C unit ${tag}`);
  await expect(risk).not.toContainText(/NaN|Infinity|undefined/);
  await shot(page, "position-condition-no-model-1440");

  // Leaving Classes: the tab comes along, on the same position by Positions and by Locations.
  const sw = arrangeSwitch(page);
  for (const [name, arrange] of [["Positions", "positions"], ["Locations", "locations"]]) {
    await sw.getByRole("radio", { name }).click();
    await expect(page).toHaveURL(new RegExp(`arrange=${arrange}`));
    await expect(page).toHaveURL(/tab=condition/);
    await expect(page.getByRole("tree", { name })).toBeVisible();
    await expect(rowC).toHaveAttribute("aria-selected", "true");
    await expect(tabOn).toHaveAttribute("aria-selected", "true");
    await expect(risk).toContainText("no condition and life model is linked to this position");
  }
  await shot(page, "position-condition-by-locations-1440");
  // The asset's top position has the tab as well (nothing fitted there: said in words); Summary is still a click away.
  await sw.getByRole("radio", { name: "Positions" }).click();
  await row(page, `Boiler house ${tag}`).click();
  await expect(tabOn).toHaveAttribute("aria-selected", "true");
  await expect(risk).toContainText("No item is fitted here");
  await rowC.click();
  await expect(risk).toContainText(`Fitted here: Feed pump C unit ${tag}`);

  // The way to link a model: the position's Modelling tab, opened from the note.
  await risk.getByRole("button", { name: "Open the Modelling tab" }).click();
  await expect(page).toHaveURL(/tab=models/);
  await expect(page.getByRole("tab", { name: "Modelling" })).toHaveAttribute("aria-selected", "true");
  await expect(page).toHaveURL(new RegExp(`sel=${bare.id}`));

  // An address that names the tab opens on it, by any arrangement.
  await open(page, `/asset-register/explorer?arrange=locations&sel=${scored.id}&tab=condition`);
  await expect(tabOn).toHaveAttribute("aria-selected", "true");
  await expect(risk.locator(".joint-unit-sum")).toContainText("age 90 days, 3 readings.");
  expect(cls.id && unread.id).toBeTruthy();
  await expectHealthy(page, problems, { label: "a position's Condition monitoring tab" });
});

test("a design's position has no Condition monitoring: nothing is fitted or read there", async ({ page, request, problems }) => {
  const tag = `d${Date.now()}`;
  const product = await postOk(request, `${M}/products`, { name: `Dosing skid ${tag}`, part_number: `DS-${tag}` });
  const motor = await postOk(request, `${M}/positions`, { name: `Motor ${tag}`, parent_id: product.id });
  const panel = details(page);
  // The address asks for it: the design's position shows Summary, with no such tab.
  await open(page, `/products/${product.id}?view=condition&sel=${motor.id}`);
  await expect(row(page, `Motor ${tag}`)).toHaveAttribute("aria-selected", "true");
  await expect(panel.getByRole("tab", { name: "Summary" })).toHaveAttribute("aria-selected", "true");
  await expect(panel.getByRole("tab", { name: "Modelling" })).toBeVisible();
  await expect(panel.getByRole("tab", { name: "Condition monitoring" })).toHaveCount(0);
  await expect(page.getByRole("region", { name: "This position's risk now" })).toHaveCount(0);
  // The product's own row the same.
  await row(page, `Dosing skid ${tag}`).click();
  await expect(panel.getByRole("tab", { name: "Summary" })).toHaveAttribute("aria-selected", "true");
  await expect(panel.getByRole("tab", { name: "Condition monitoring" })).toHaveCount(0);
  await expectHealthy(page, problems, { label: "a design's position" });
});

test("a position's Condition monitoring on a phone: the words and the charts fit 400 px by Classes", async ({ page, request, problems }) => {
  const tag = `q${Date.now()}`;
  const { top } = await monitored(request, tag);
  await page.setViewportSize({ width: 400, height: 800 });
  await open(page, `/asset-register/explorer?arrange=classes&root=${top.id}`);
  await expect(arrangeSwitch(page).getByRole("radio", { name: "Classes" })).toHaveAttribute("aria-checked", "true");
  const panel = page.getByRole("region", { name: "Details" });
  const tabOn = panel.getByRole("tab", { name: "Condition monitoring" });
  const risk = panel.getByRole("region", { name: "This position's risk now" });

  // From the class's fleet to a position: its own tab, the same one.
  await row(page, `Feed pump ${tag}`).locator(".tp-nm").click();
  await expect(panel.locator(".cf-answer")).toContainText("3 positions");
  await expect.poll(() => sideways(page)).toBeLessThanOrEqual(0);
  await shot(page, "class-fleet-with-risk-400");
  await panel.getByRole("region", { name: "Risk now" }).getByRole("button", { name: `Feed pump A ${tag}` }).click();
  await expect(panel.getByRole("heading", { name: `Feed pump A ${tag}` })).toBeVisible();
  await expect(tabOn).toHaveAttribute("aria-selected", "true");
  await expect(risk.locator(".joint-unit-sum")).toContainText("age 90 days, 3 readings.");
  await expect(risk.locator(".js-plotly-plot .main-svg").first()).toBeVisible({ timeout: 20_000 });
  await expect.poll(() => sideways(page)).toBeLessThanOrEqual(0);
  await shot(page, "position-condition-scored-400");
  await risk.locator(".pr-note").scrollIntoViewIfNeeded();
  await expect.poll(() => sideways(page)).toBeLessThanOrEqual(0);
  await shot(page, "position-condition-scored-charts-400");

  // Back to the tree, and a position with no model (a row opened from the tree on a phone starts on
  // the tab its address names, as with every tab): the note and the way to the Modelling tab fit too.
  await panel.getByRole("button", { name: /Explorer/ }).click();
  await row(page, `Feed pump C ${tag}`).locator(".tp-nm").click();
  await expect(panel.getByRole("heading", { name: `Feed pump C ${tag}` })).toBeVisible();
  await tabOn.click();
  await expect(tabOn).toHaveAttribute("aria-selected", "true");
  await expect(risk).toContainText("No risk to show yet: no condition and life model is linked to this position.");
  await expect(risk.getByRole("button", { name: "Open the Modelling tab" })).toBeVisible();
  await expect.poll(() => sideways(page)).toBeLessThanOrEqual(0);
  await shot(page, "position-condition-no-model-400");
  await panel.getByRole("button", { name: /Explorer/ }).click();
  await expect(row(page, `Feed pump C ${tag}`)).toBeVisible();
  await expectHealthy(page, problems, { label: "a position's Condition monitoring on a phone" });
});
