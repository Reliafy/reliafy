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

test("attach a sample model to a position, see its row and its details, then unlink it", async ({ page, request, problems }) => {
  const tag = `l${Date.now()}`;
  const pump = await postOk(request, `${M}/positions`, { name: `Model pump ${tag}` });
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${pump.id}&tab=models`);
  await expect(page.getByRole("treegrid", { name: /and their life models/ })).toBeVisible();
  await expect(page.locator(".tt-headslot .mt-rollup")).toHaveText("No models here yet");

  // Assign a saved model… from the heading's "…": the library's samples, picked and attached.
  const head = await headMenu(page);
  await expect(head.locator(".ovm-menu .ovm-item")).toContainText(["Fit from history…", "Assign a saved model…", "Assign from class…", "Columns…"]);
  await head.getByRole("button", { name: "Assign a saved model…" }).click();
  const dialog = page.getByRole("dialog", { name: "Assign a saved model" });
  await dialog.getByRole("radio", { name: SAMPLE, exact: true }).check();
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
  const head = await headMenu(page);
  await head.getByRole("button", { name: "Update a baseline with this position's history…" }).click();
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
  const head = await headMenu(page);
  await head.getByRole("button", { name: "Assign a saved model…" }).click();
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
