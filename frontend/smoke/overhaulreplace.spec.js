// Strategy › Overhaul and replace, and a model's Strategy on a position in the Explorer
// (Derryn, 16 Nov 2026: "each model for a position needs a sub item which is 'strategy'", then
// "Strategy is optional"): a model row has no Strategy item until one is saved for it; its ⋯
// offers Add a strategy…, which opens the tools that fit it in the table pane beside the tree.
import { test, expect, open, expectHealthy, postOk } from "./health.js";
import { subItem } from "./explorer.js";
import { choose } from "./select.js";

// An item of a row's menu: at its top level, or under More › (the menu standard keeps ten a level).
async function menuPick(page, name) {
  const menu = page.getByRole("menu").last();
  await expect(menu).toBeVisible();
  const direct = menu.locator(":scope > [role='menuitem']").filter({ hasText: name });
  if (await direct.count()) return menu.getByRole("menuitem", { name }).first();
  return subItem(page, menu, "More", name, { exact: false });
}


const M = "/api/maintenance";
const SAMPLE = "Bearing life — Weibull (sample)";
const SHOTS = process.env.SMOKE_SHOTS_DIR || "";
const shot = async (page, name, fullPage = false) => {
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage });
};
const sideways = (page) => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);

async function savedRepairable(request, name) {
  const res = await request.post("/api/recurrent/from-params", {
    multipart: { name, model: "crow_amsaa", alpha: "500", beta: "2.2", horizon: "5000", unit: "Flight hours" },
  });
  expect(res.ok(), await res.text()).toBeTruthy();
  return res.json();
}

async function fill(scope) {
  await scope.getByLabel(/Repair cost, per failure/).fill("2000");
  await scope.getByLabel(/Overhaul cost/).fill("15000");
  await scope.getByLabel(/Replacement cost/).fill("60000");
  await scope.getByLabel("An overhaul takes off (% of its age)").fill("60");
}

for (const width of [1440, 400]) {
  test(`the Overhaul and replace page answers in the model's unit (${width} px)`, async ({ page, request, problems }) => {
    const model = await savedRepairable(request, `Gearbox ${Date.now()}`);
    await page.setViewportSize({ width, height: 900 });
    await open(page, `/strategy/overhaul-replace?model=${model.id}`);
    await expect(page.getByRole("heading", { name: "Overhaul and replace", level: 1 })).toBeVisible();
    await fill(page);
    await page.getByRole("button", { name: "Compute" }).click();
    const summary = page.locator(".result-summary").first();
    await expect(summary).toContainText(/Overhaul every [\d,]+ Flight hours/);
    await expect(page.locator(".or-table").first()).toContainText("Overhaul only, never replace");
    await expect(page.getByText("Run to failure: repair, then replace at a failure")).toBeVisible();
    await shot(page, `overhaul-replace-page-${width}`, true);
    expect(await sideways(page)).toBeLessThanOrEqual(0);
    await expectHealthy(page, problems, { label: "Overhaul and replace page" });
  });

  test(`a model on a position: Add a strategy…, save one, and its Strategy row appears (${width} px)`, async ({ page, request, problems }) => {
    const tag = `s${Date.now()}`;
    const pump = await postOk(request, `${M}/positions`, { name: `Strategy gearbox ${tag}` });
    const model = await savedRepairable(request, `Gearbox model ${tag}`);
    await postOk(request, `${M}/positions/${pump.id}/models`, { model_type: "recurrent_model", model_id: model.id });
    await page.setViewportSize({ width, height: 900 });
    await open(page, `/asset-register/explorer?arrange=positions&root=${pump.id}&sel=${pump.id}&tab=models`);
    const row = page.locator(".tp-row", { has: page.locator(".tp-nm", { hasText: `Gearbox model ${tag}` }) });
    await expect(row).toBeVisible();
    // Strategy is optional: no Strategy row until one is saved.
    await expect(page.locator(".tp-row", { has: page.locator(".tp-nm", { hasText: /^Strategy$/ }) })).toHaveCount(0);
    await row.locator(".tp-nm").click({ button: "right" });
    await (await menuPick(page, "Add a strategy…")).click();
    const pane = page.locator(".strategy-pane");
    await expect(pane).toBeVisible();
    // A repairable (minimal repair) model: overhaul and replace, and the optimal overhaul.
    await expect(pane.getByRole("tab")).toHaveText(["Overhaul and replace", "Optimal overhaul"]);
    await fill(pane);
    await pane.getByRole("button", { name: "Compute" }).click();
    await expect(pane.locator(".result-summary").first()).toContainText(/Flight hours/);
    expect(await sideways(page)).toBeLessThanOrEqual(0);
    await shot(page, `overhaul-replace-explorer-pane-${width}`);
    await pane.getByRole("button", { name: "Save analysis" }).click();
    await page.getByRole("dialog", { name: "Save this analysis" }).getByRole("button", { name: "Save" }).click();
    await expect(pane.getByText("Saved for this model here")).toBeVisible();
    // Back at the tree: the model row now has its Strategy row.
    if (width < 700) await pane.getByRole("button", { name: "Back to the table" }).click();
    else await page.keyboard.press("Escape");

    const strategy = page.locator(".tp-row", { has: page.locator(".tp-nm", { hasText: /^Strategy$/ }) });
    await expect(strategy).toHaveCount(1);
    await shot(page, `overhaul-replace-explorer-row-${width}`);
    await expectHealthy(page, problems, { label: "Explorer model strategy" });
  });
}

test("a life model's strategies: replacement, shutdown replacement and failure finding", async ({ page, request, problems }) => {
  const tag = `f${Date.now()}`;
  const pump = await postOk(request, `${M}/positions`, { name: `Strategy pump ${tag}` });
  const models = await (await request.get("/api/models")).json();
  const sample = (models.models || []).find((m) => m.name === SAMPLE);
  test.skip(!sample, "the bearing sample isn't seeded");
  const link = await postOk(request, `${M}/positions/${pump.id}/models`, { model_type: "model", model_id: sample.id });
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, `/asset-register/explorer?arrange=positions&root=${pump.id}&sel=${pump.id}&tab=models&strategy=${link.id}&on=${pump.id}`);
  const pane = page.locator(".strategy-pane");
  await expect(pane.getByRole("tab")).toHaveText(["Optimal replacement", "Shutdown replacement", "Failure finding"]);
  await pane.getByRole("tab", { name: "Failure finding" }).click();
  await expect(page).toHaveURL(/how=failureFinding/);
  await expectHealthy(page, problems, { label: "Explorer life model strategy" });
});

// Strategy answers that must read the right way round: an MTBF typed as a failure rate is caught
// before it gives "test every 0.0000004 hours", and a cheaper plan is said as a share of the best.
test("failure finding: a rate that looks like an MTBF is asked about, and the MTBF can be entered", async ({ page, problems }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, "/strategy/failure-finding");
  await page.getByRole("radio", { name: "Parameters" }).click();
  await choose(page.getByRole("combobox", { name: "Distribution" }), "exponential");
  await page.getByLabel("Unit of the model's times").fill("hours");
  await page.getByLabel(/Failure rate λ/).fill("4000");
  const hint = page.getByTestId("rate-looks-like-mean");
  await expect(hint).toContainText("This looks like an MTBF of 4,000 hours; did you mean a rate of 0.00025 per hour?");
  await hint.getByRole("button", { name: "Use 0.00025" }).click();
  await expect(page.getByLabel(/Failure rate λ/)).toHaveValue("0.00025");
  await expect(hint).toHaveCount(0);

  // The other way: the 4,000 entered as the mean life (MTBF).
  await page.getByLabel(/Failure rate λ/).fill("4000");
  await page.getByTestId("rate-looks-like-mean").getByRole("button", { name: "Enter 4000 as the mean life" }).click();
  await expect(page.getByRole("radio", { name: "Mean" })).toBeChecked();
  await expect(page.getByLabel(/Mean life \(MTBF\)/)).toHaveValue("4000");
  await page.getByRole("button", { name: "Compute" }).click();
  const summary = page.locator(".result-summary").first();
  await expect(summary).toContainText("Test every ≈ 80.5 hours");
  await expect(summary).toContainText("4,000 hours");
  await expect(summary).not.toContainText(/e-\d/);
  await expectHealthy(page, problems, { label: "Failure finding" });
});

test("overhaul and replace: a cheaper plan is said as a share of the best plan's cost", async ({ page, request, problems }) => {
  const res = await request.post("/api/recurrent/from-params", {
    multipart: { name: `Gearbox share ${Date.now()}`, model: "crow_amsaa", alpha: "500", beta: "2.2", horizon: "5000", unit: "Hours" },
  });
  expect(res.ok(), await res.text()).toBeTruthy();
  const model = await res.json();
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, `/strategy/overhaul-replace?model=${model.id}`);
  await page.getByLabel(/Repair cost, per failure/).fill("2000");
  await page.getByLabel(/Overhaul cost/).fill("15000");
  await page.getByLabel(/Replacement cost/).fill("60000");
  await page.getByLabel("An overhaul takes off (% of its age)").fill("60");
  await page.getByRole("button", { name: "Compute" }).click();
  // Overhaul only at about 37.34 an hour against the best plan's 39.31: 5.0% less, never "5.3%".
  const summary = page.locator(".result-summary").first();
  await expect(summary).toContainText("Overhaul only, never replace costs 5.0% less than this plan");
  const table = page.locator(".or-table").first();
  await expect(table.getByRole("columnheader", { name: "Against this plan" })).toBeVisible();
  await expect(table.getByRole("row", { name: /Overhaul only, never replace/ })).toContainText("costs 5.0% less");
  await expect(page.locator("body")).not.toContainText("5.3%");
  await expectHealthy(page, problems, { label: "Overhaul and replace shares" });
});
