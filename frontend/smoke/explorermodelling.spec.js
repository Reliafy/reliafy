// The Explorer's Modelling tab (Derryn, 9 Nov 2026: "life models against every
// functional location"): a tree-table like the RCM and Measurements tabs. The position
// tree is the first column and each position's life models hang under it, with Kind,
// Source, the headline numbers, Mean life, Confidence and Used by beside them. A
// position rolls up its rows ("1 model"). The heading's "…" attaches one (fit from
// history, a saved model, the class's); picking a row opens its details beside the
// table (the plot, the parameters with bounds, the data, what uses it); its ⋯ unlinks it.
import { test, expect, open, expectHealthy, postOk } from "./health.js";
import { headMenu } from "./explorer.js";

const M = "/api/maintenance";
const SAMPLE = "Bearing life — Weibull (sample)";
const row = (page, key) => page.locator(`.tp-row[data-key="${key}"]`);
const side = (page) => page.locator(".ml-panel");
const sideways = (page) => page.evaluate(() => document.documentElement.scrollWidth);

// The heading's "…" on the Modelling tab is two levels (Life model ›, RBD ›, Prediction ›): open
// it, open the group, pick the item.
async function headPick(page, group, item) {
  await headMenu(page);
  await page.getByRole("menuitem", { name: group, exact: true }).click();
  await page.getByRole("menu", { name: group }).getByRole("menuitem", { name: item }).click();
}

test("attach a sample model to a position, see its row and its details, then unlink it", async ({ page, request, problems }) => {
  const tag = `l${Date.now()}`;
  const pump = await postOk(request, `${M}/positions`, { name: `Model pump ${tag}` });
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${pump.id}&tab=models`);
  await expect(page.getByRole("treegrid", { name: /and their life models/ })).toBeVisible();
  await expect(page.locator(".tt-headslot .mt-rollup")).toHaveText("No models here yet");

  // Assign a saved model… from the heading's "…": the library's samples, picked and attached.
  await headMenu(page);
  const top = page.getByRole("menu", { name: "More actions" });
  await expect(top.locator(":scope > [role='menuitem']")).toContainText(["Life model", "RBD", "Prediction", "Columns…"]);
  await top.getByRole("menuitem", { name: "Life model", exact: true }).click();
  // (From the class… is off here, its reason under it: no class.)
  await expect(page.getByRole("menu", { name: "Life model" }).getByRole("menuitem")).toContainText(["Fit from this position's history…",
    "Update a baseline with its history…", "Assign a saved model…", "From the class…", "Enter parameters…"]);
  await page.getByRole("menu", { name: "Life model" }).getByRole("menuitem", { name: "Assign a saved model…" }).click();
  const dialog = page.getByRole("dialog", { name: "Assign a saved model" });
  // The radio's accessible name carries the model's kind and figures after its name:
  // a plain-string name match is a substring match, with nothing to escape.
  await dialog.getByRole("radio", { name: SAMPLE }).check();
  await dialog.getByRole("button", { name: "Attach" }).click();
  await expect(dialog).toHaveCount(0);

  const pos = row(page, pump.id);
  await expect(pos.locator(".tt-rollup-t")).toHaveText("1 model");
  const model = page.locator(".tp-row", { has: page.locator(".tp-nm", { hasText: SAMPLE }) });
  await expect(model.locator(".mt-c-kind")).toHaveText("Weibull");
  await expect(model.locator(".mt-c-source")).toContainText(`Assigned: ${SAMPLE}`);
  await expect(model.locator(".mt-c-numbers")).toContainText(/Life [\d,]+ hours \([\d,]+–[\d,]+\) · shape/);
  await expect(model.locator(".mt-c-quality")).toContainText("Good");

  // Spread across the table (a double-click): the plot, the parameters with bounds, the data.
  await model.locator(".tp-nm").dblclick();
  await expect(side(page).getByRole("heading", { name: SAMPLE })).toBeVisible();
  await expect(side(page).locator(".js-plotly-plot")).toBeVisible();
  await expect(side(page).locator(".ml-params tbody tr")).toHaveCount(2);
  await expect(side(page).getByText("30 failures, 0 suspensions").first()).toBeVisible();
  await expectHealthy(page, problems, { label: "Modelling tree-table" });

  // Unlink… from the row's ⋯: it comes off; the model stays in Models.
  await page.keyboard.press("Escape");
  await model.locator(".tp-nm").click({ button: "right" });
  await expect(page.getByRole("menu").last().getByRole("menuitem")).toContainText(["Open", "Open in Models", "Replace with…", "Unlink…"]);
  await page.getByRole("menu").last().getByRole("menuitem", { name: "Unlink…" }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Unlink" }).click();
  await expect(model).toHaveCount(0);
  await expect(page.locator(".tt-headslot .mt-rollup")).toHaveText("No models here yet");
});

test("the Modelling tab at 400 px: a model's line under it, its details as a sheet, nothing sideways", async ({ page, request }) => {
  const tag = `n${Date.now()}`;
  const pump = await postOk(request, `${M}/positions`, { name: `Model fan ${tag}` });
  await postOk(request, `${M}/positions/${pump.id}/models`, { model_id: "sample-model-bearings-weibull" });
  await page.setViewportSize({ width: 400, height: 860 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${pump.id}&tab=models`);
  const model = page.locator(".tp-row", { has: page.locator(".tp-nm", { hasText: SAMPLE }) });
  await expect(model.locator(".tt-l2")).toContainText("Weibull · Life");
  expect(await sideways(page)).toBeLessThanOrEqual(400);
  await model.locator(".tp-nm").click();
  await expect(side(page).getByRole("heading", { name: SAMPLE })).toBeVisible();
  expect(await sideways(page)).toBeLessThanOrEqual(400);
});

// A Bayesian update: a pump with one failure, a sample Weibull as the baseline, the result in
// words with credible intervals and the plot, saved and attached as the pump's model.
test("update a baseline with a position's one failure, and save it as the position's model", async ({ page, request, problems }) => {
  const tag = `b${Date.now()}`;
  const ago = (d) => new Date(Date.now() - d * 864e5).toISOString().slice(0, 10);
  const pump = await postOk(request, `${M}/positions`, { name: `Bayes pump ${tag}` });
  await postOk(request, `${M}/positions/${pump.id}/fit`, { new_item: { name: `Unit A ${tag}` }, on: ago(200) });
  await postOk(request, `${M}/positions/${pump.id}/remove`, { on: ago(150), reason: "failure" });
  await postOk(request, `${M}/positions/${pump.id}/fit`, { new_item: { name: `Unit B ${tag}` }, on: ago(150) });
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${pump.id}&tab=models`);
  await headPick(page, "Life model", "Update a baseline with its history…");
  const dialog = page.getByRole("dialog", { name: "Update a baseline with this position's history" });
  const option = await dialog.locator("option", { hasText: "Bearing life — Weibull" }).first().getAttribute("value");
  await dialog.getByRole("combobox", { name: "Baseline model" }).selectOption(option);
  await expect(dialog.getByRole("status")).toContainText("90% chance it lies between");
  await expect(dialog.locator(".js-plotly-plot")).toBeVisible();
  await expect(dialog.getByRole("checkbox")).toHaveCount(2);
  await dialog.getByRole("button", { name: "Save as this position's model" }).click();
  await expect(dialog).toHaveCount(0);
  const model = page.locator(".tp-row", { has: page.locator(".tp-nm", { hasText: "Bayesian update of" }) });
  await expect(model.locator(".mt-c-kind")).toHaveText("Weibull (Bayesian)");
  await expect(model.locator(".mt-c-source")).toContainText(/^Bayesian update of .* · 1 failure, 1 suspension/);
  await expect(model.locator(".mt-c-numbers")).toContainText(/Life [\d,.]+ hours, 90% credible [\d,.]+–[\d,.]+/);
  // Its details: the credible interval named as such, and the curve with its credible band.
  await model.locator(".tp-nm").click();
  await expect(side(page).locator(".ml-params thead")).toContainText("90% credible interval");
  await expect(side(page).locator(".ml-params thead")).not.toContainText(/bounds|confidence/i);
  await expect(side(page).locator(".js-plotly-plot .legendtext", { hasText: "90% credible band" })).toHaveCount(1);
  await expectHealthy(page, problems, { label: "a Bayesian update" });
});

// An accelerated-life model attached as it is (the stress is set where it's used), and a
// parts-count prediction row from a position's parts list.
test("an ALT model attached as fitted, and a prediction row from the parts list", async ({ page, request, problems }) => {
  const tag = `p${Date.now()}`;
  const seal = await postOk(request, `${M}/positions`, { name: `ALT seal ${tag}` });
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${seal.id}&tab=models`);
  await headPick(page, "Life model", "Assign a saved model…");
  const dialog = page.getByRole("dialog", { name: "Assign a saved model" });
  await dialog.getByRole("radio", { name: "Accelerated life" }).click();
  await dialog.getByRole("radio", { name: /Valve seal — Weibull ALT/ }).check();
  await dialog.getByRole("button", { name: "Attach" }).click();
  const alt = page.locator(".tp-row", { has: page.locator(".tp-nm", { hasText: "Valve seal — Weibull ALT" }) });
  await expect(alt.locator(".mt-c-source")).toContainText("(accelerated life, stress: temperature, load)");
  await expect(alt.locator(".mt-c-numbers")).toContainText("at its lowest tested stress");
  await alt.locator(".tp-nm").click();
  await expect(side(page).locator(".ml-stress")).toContainText("set where the model is used");

  // A controller with a capacitor on its parts list, predicted (the part type given through the API).
  const ctl = await postOk(request, `${M}/positions`, { name: `Controller ${tag}` });
  const part = await postOk(request, `${M}/parts`, { part_number: `C-${tag}`, name: `Bypass capacitor ${tag}` });
  await postOk(request, `${M}/positions/${ctl.id}/parts`, { part_id: part.id, role: "component", quantity: 4 });
  await postOk(request, `${M}/positions/${ctl.id}/models`, {
    prediction: { environment: "GB", assign: { [`C-${tag}`]: { record_id: "mil-hdbk-217f-n2:10-1-cp-25" } } } });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${ctl.id}&tab=models`);
  const pred = page.locator(".tp-row", { has: page.locator(".tp-nm", { hasText: `Controller ${tag} (predicted, parts count)` }) });
  await expect(pred.locator(".mt-c-kind")).toHaveText("Prediction (parts count)");
  await expect(pred.locator(".mt-c-source")).toContainText("Predicted from its parts list (parts count");
  await expect(pred.locator(".mt-c-numbers")).toContainText(/MTBF [\d,]+ hours/);
  await expect(row(page, ctl.id).locator(".tt-rollup-t")).toHaveText("1 model");
  await pred.locator(".tp-nm").click();
  await expect(side(page).getByRole("link", { name: "Open in Predictions" })).toBeVisible();
  await expect(side(page)).toContainText(`Bypass capacitor ${tag}`);
  // Refresh the prediction…: the dialog lists the part with its part type.
  await pred.locator(".tp-nm").click({ button: "right" });
  await page.getByRole("menu").last().getByRole("menuitem", { name: "Refresh the prediction…" }).click();
  const pd = page.getByRole("dialog", { name: "Refresh the prediction" });
  await expect(pd.locator(".ml-lines tbody tr")).toHaveCount(1);
  await expect(pd.getByRole("status")).toContainText("failures per million hours");
  await pd.getByRole("button", { name: "Cancel" }).click();
  await expectHealthy(page, problems, { label: "ALT and prediction rows" });
});

// An RBD row: built from the two positions inside (one with a model, one a flagged placeholder),
// its panel's blocks, then made the position's model in use over its own life model.
test("build an RBD from what's inside, see its blocks, and make it the model in use", async ({ page, request, problems }) => {
  const tag = `r${Date.now()}`;
  const station = await postOk(request, `${M}/positions`, { name: `Station ${tag}` });
  const a = await postOk(request, `${M}/positions`, { name: `Pump A ${tag}`, parent_id: station.id });
  await postOk(request, `${M}/positions`, { name: `Pump B ${tag}`, parent_id: station.id });
  await postOk(request, `${M}/positions/${a.id}/models`, { model_id: "sample-model-bearings-weibull" });
  await postOk(request, `${M}/positions/${station.id}/models`, { model_id: "sample-model-bearings-lognormal" });
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${station.id}&tab=models`);
  await headPick(page, "RBD", "Build from what's inside…");
  const dialog = page.getByRole("dialog", { name: "Build an RBD from what's inside" });
  await expect(dialog.locator("li")).toHaveCount(2);
  await dialog.getByRole("button", { name: "Build", exact: true }).click();
  await expect(dialog).toHaveCount(0);
  const rbd = page.locator(".tp-row", { has: page.locator(".tp-nm", { hasText: `Station ${tag} (from the tree)` }) });
  await expect(rbd.locator(".mt-c-kind")).toContainText("RBD");
  await expect(rbd.locator(".mt-c-source")).toHaveText("Built from 2 positions inside · 1 placeholder");
  await expect(rbd.locator(".mt-c-numbers")).toContainText(/MTBF [\d,]+ hours/);
  await expect(rbd.locator(".mt-c-quality")).toContainText("1 placeholder");
  // Its own life model is in use by default.
  const life = page.locator(".tp-row", { has: page.locator(".tp-nm", { hasText: "Bearing life — Lognormal" }) });
  await expect(life.locator(".ml-inuse")).toHaveText("In use");
  await rbd.locator(".tp-nm").click();
  await expect(side(page).locator(".ml-blocks tbody tr")).toHaveCount(2);
  await expect(side(page).locator(".ml-blocks")).toContainText("Placeholder");
  await expect(side(page).locator(".ml-blocks")).toContainText(`Pump A ${tag}`);
  // Use this one: the RBD becomes the model in use.
  await page.keyboard.press("Escape");
  await rbd.locator(".tp-nm").click({ button: "right" });
  await page.getByRole("menu").last().getByRole("menuitem", { name: "Use this one" }).click();
  await expect(rbd.locator(".ml-inuse")).toHaveText("In use");
  await expect(life.locator(".ml-inuse")).toHaveCount(0);
  await expect(row(page, station.id).locator(".tt-rollup-t")).toContainText("in use: RBD");
  await expectHealthy(page, problems, { label: "an RBD row" });
});

// "Numbers I know" as the baseline on a position whose class has no model: the class message
// goes, and the update previews (data, what moved, credible intervals, the plot) once the
// numbers and unit are in; Save is on.
test("a Bayesian update from numbers I know, on a position whose class has no model", async ({ page, request, problems }) => {
  const tag = `k${Date.now()}`;
  const ago = (d) => new Date(Date.now() - d * 864e5).toISOString().slice(0, 10);
  const pump = await postOk(request, `${M}/positions`, { name: `Filter pump ${tag}`, position_class: `Filter pump ${tag}` });
  await postOk(request, `${M}/positions/${pump.id}/fit`, { new_item: { name: `Unit A ${tag}` }, on: ago(900) });
  await postOk(request, `${M}/positions/${pump.id}/remove`, { on: ago(400), reason: "failure" });
  await postOk(request, `${M}/positions/${pump.id}/fit`, { new_item: { name: `Unit B ${tag}` }, on: ago(400) });
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${pump.id}&tab=models`);
  await headPick(page, "Life model", "Update a baseline with its history…");
  const dialog = page.getByRole("dialog", { name: "Update a baseline with this position's history" });
  await expect(dialog).toContainText("no class model");
  await dialog.getByRole("radio", { name: "Numbers I know" }).click();
  await expect(dialog).not.toContainText("no class model");
  await expect(dialog).toContainText("Give the baseline's numbers to see the update.");
  await dialog.getByLabel("Characteristic life (alpha)").fill("4");
  await dialog.getByLabel("Shape (beta)").fill("2");
  await dialog.getByLabel("Unit").selectOption("years");
  await expect(dialog.getByRole("status")).toContainText("90% chance it lies between");
  await expect(dialog.getByRole("status")).toContainText("1 failure at");
  await expect(dialog.locator(".js-plotly-plot")).toBeVisible();
  await expect(dialog.getByRole("checkbox")).toHaveCount(2);
  await expect(dialog.locator(".ml-params")).toContainText("Before (baseline)");
  await expect(dialog.getByRole("button", { name: "Save as this position's model" })).toBeEnabled();
  await expectHealthy(page, problems, { label: "a Bayesian update from numbers" });
});

// The position's own row menu on the Modelling tab: the three groups (→ opens one), a line,
// then Rename…, Isolate and Pin this branch; nothing from Summary's (New position inside, a
// failure report, an event, Move to…, Delete…). "Enter parameters…" saves a model and attaches it.
test("a position's row menu on the Modelling tab is two levels, and Enter parameters… attaches a model", async ({ page, request, problems }) => {
  const tag = `m${Date.now()}`;
  const pump = await postOk(request, `${M}/positions`, { name: `Menu pump ${tag}` });
  await postOk(request, `${M}/positions`, { name: `Menu seal ${tag}`, parent_id: pump.id });
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${pump.id}&tab=models`);
  await row(page, pump.id).locator(".tp-nm").click({ button: "right" });
  const menu = page.getByRole("menu", { name: new RegExp(`^Actions for Menu pump ${tag}`) });
  await expect(menu.locator(":scope > [role='menuitem']")).toHaveText(["Life model", "RBD", "Prediction", "Rename…", "Isolate", "Pin this branch"]);
  await expect(menu.getByRole("separator")).toHaveCount(1);
  for (const gone of ["New position inside", "Add failure report…", "Log an event…", "Move to…", "Delete…"]) {
    await expect(menu.getByRole("menuitem", { name: gone })).toHaveCount(0);
  }
  // The keyboard: → opens a group.
  await menu.getByRole("menuitem", { name: "RBD", exact: true }).focus();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("menu", { name: "RBD" }).getByRole("menuitem")).toHaveText(["Build from what's inside…", "Link an existing RBD…"]);
  await page.keyboard.press("Escape");
  await page.keyboard.press("Escape");
  // Enter parameters…: a Weibull typed in, saved and attached.
  await row(page, pump.id).locator(".tp-nm").click({ button: "right" });
  await page.getByRole("menuitem", { name: "Life model", exact: true }).click();
  await page.getByRole("menu", { name: "Life model" }).getByRole("menuitem", { name: "Enter parameters…" }).click();
  const dialog = page.getByRole("dialog", { name: "Enter parameters" });
  await dialog.getByLabel("Characteristic life (alpha)").fill("5000");
  await dialog.getByLabel("Shape (beta)").fill("1.5");
  await dialog.getByRole("button", { name: "Save and attach" }).click();
  await expect(dialog).toHaveCount(0);
  const model = page.locator(".tp-row", { has: page.locator(".tp-nm", { hasText: `Menu pump ${tag} (entered)` }) });
  await expect(model.locator(".mt-c-kind")).toContainText("Weibull");
  await expect(model.locator(".mt-c-numbers")).toContainText("Life 5,000 hours");
  await expectHealthy(page, problems, { label: "the Modelling row menu" });
});

test("the Modelling row menu at 400 px: groups open in place", async ({ page, request }) => {
  const tag = `n${Date.now()}`;
  const pump = await postOk(request, `${M}/positions`, { name: `Phone pump ${tag}` });
  await page.setViewportSize({ width: 400, height: 860 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${pump.id}&tab=models`);
  await row(page, pump.id).locator(".tp-nm").click({ button: "right" });
  await page.getByRole("menuitem", { name: "Prediction", exact: true }).click();
  await expect(page.getByRole("group", { name: "Prediction" }).getByRole("menuitem")).toHaveText(["Add a prediction (parts count)…"]);
  expect(await sideways(page)).toBeLessThanOrEqual(400);
});
