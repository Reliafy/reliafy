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
// With SMOKE_SHOTS_DIR set, screenshots for the pull request.
const SHOTS = process.env.SMOKE_SHOTS_DIR || "";
const shot = async (page, name) => {
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: false });
};

// The heading's "…" on the Modelling tab is two levels (Life model ›, RBD ›, Prediction ›): open
// it, open the group, pick the item.
// Saving a fit refits it on the server (a fit with a prior on SurPyval's grid, then the save and
// the link): on a shared CI runner that can take longer than an expect's 10 s. Wait for the save's
// own answer, then check it worked and the fit pane closed.
async function saveFit(page, dialog, positionId) {
  const saved = page.waitForResponse((r) => r.url().includes(`/api/maintenance/positions/${positionId}/models`)
    && r.request().method() === "POST", { timeout: 60_000 });
  await dialog.getByRole("button", { name: "Save as this position's model" }).click();
  expect((await saved).status()).toBe(200);
  await expect(dialog).toHaveCount(0);
}

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
  await expect(page.getByRole("menu", { name: "Life model" }).getByRole("menuitem")).toContainText(["Fit a life model…",
    "Assign a saved model…", "From the class…", "Enter parameters…"]);
  await page.getByRole("menu", { name: "Life model" }).getByRole("menuitem", { name: "Assign a saved model…" }).click();
  const dialog = page.getByRole("dialog", { name: "Assign a saved model" });
  // The radio's accessible name is the model's name, then its kind and unit. Matched exactly (no
  // regex to escape), because saved updates of it (other tests, repeats) carry its name inside theirs.
  await dialog.getByRole("radio", { name: `${SAMPLE} Weibull · Hours`, exact: true }).check();
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
  await headPick(page, "Life model", "Fit a life model…");
  const dialog = page.getByRole("region", { name: "Fit a life model" });
  await dialog.getByRole("radio", { name: "With a prior" }).click();
  await dialog.getByRole("combobox", { name: "Prior", exact: true }).selectOption("model");
  const option = await dialog.locator("option", { hasText: "Bearing life — Weibull" }).first().getAttribute("value");
  await dialog.getByRole("combobox", { name: "Prior model" }).selectOption(option);
  await expect(dialog.getByRole("status")).toContainText("90% one-sided credible bound"); // B-life bounds are one-sided (#818)
  await expect(dialog.locator(".js-plotly-plot")).toBeVisible();
  await expect(dialog.getByRole("checkbox")).toHaveCount(2);
  await saveFit(page, dialog, pump.id);
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
  // Refresh the prediction…: in the table area (not a dialog), the part listed with its part type.
  await pred.locator(".tp-nm").click({ button: "right" });
  await page.getByRole("menu").last().getByRole("menuitem", { name: "Refresh the prediction…" }).click();
  const pd = page.getByRole("region", { name: "Refresh the prediction" });
  await expect(page.getByRole("dialog", { name: "Refresh the prediction" })).toHaveCount(0);
  await expect(pd.locator(".table-pane-title")).toHaveText(`Refresh the prediction · Controller ${tag}`);
  await expect(pd.locator(".pred2-table tbody tr")).toHaveCount(1);
  await expect(pd.getByRole("status")).toContainText("failures per million hours");
  await pd.getByRole("button", { name: "Cancel" }).click();
  await expect(pd).toHaveCount(0);
  await expectHealthy(page, problems, { label: "ALT and prediction rows" });
});

// An RBD row: built from the two positions inside (one with a model, one a flagged placeholder).
// Build from what's inside… opens the RBD builder itself in the table area, beside the tree (no
// dialog): what it made said over it, the canvas with a block per position. Esc goes back to the
// table, the row still picked; the row's panel lists its blocks; Use this one makes it the model
// in use over the position's own life model.
const rbdPane = (page) => page.getByRole("region", { name: "RBD", exact: true });
const rbdOf = (page) => new URL(page.url()).searchParams.get("rbd");
// How many of the diagram's blocks are wholly inside its canvas.
const blocksInView = (pane) => pane.locator(".react-flow").evaluate((flow) => {
  const box = flow.getBoundingClientRect();
  const nodes = [...flow.querySelectorAll(".react-flow__node")].map((n) => n.getBoundingClientRect());
  const inside = nodes.filter((r) => r.left >= box.left - 1 && r.right <= box.right + 1 && r.top >= box.top - 1 && r.bottom <= box.bottom + 1);
  return { all: nodes.length, inside: inside.length };
});
async function station(request, tag) {
  const st = await postOk(request, `${M}/positions`, { name: `Station ${tag}` });
  const a = await postOk(request, `${M}/positions`, { name: `Pump A ${tag}`, parent_id: st.id });
  await postOk(request, `${M}/positions`, { name: `Pump B ${tag}`, parent_id: st.id });
  await postOk(request, `${M}/positions/${a.id}/models`, { model_id: "sample-model-bearings-weibull" });
  return st;
}

test("build an RBD from what's inside: the builder in the table area, its row, and the model in use", async ({ page, request, problems }) => {
  const tag = `r${Date.now()}`;
  const st = await station(request, tag);
  await postOk(request, `${M}/positions/${st.id}/models`, { model_id: "sample-model-bearings-lognormal" });
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${st.id}&tab=models`);
  await headPick(page, "RBD", "Build from what's inside…");
  const pane = rbdPane(page);
  await expect(pane).toBeVisible();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.locator(".tt-main .tt-side .rbd-pane")).toBeVisible();
  // No heading row on a wide screen (it took too much room): the region keeps the name for screen readers.
  await expect(pane.locator(".table-pane-title")).toHaveCount(0);
  await expect(pane.locator("h2.sr-only")).toHaveText(`RBD · Station ${tag}`);
  await expect(page).toHaveURL(new RegExp(`[?&]rbd=[\\w-]+&on=${st.id}`));
  const treeBox = await page.locator(".tp-scroll").boundingBox();
  const paneBox = await pane.boundingBox();
  expect(paneBox.x).toBeGreaterThanOrEqual(treeBox.x + treeBox.width - 2);  // beside the tree
  expect(paneBox.width).toBeGreaterThan(800);  // the table's room
  // Straight into the builder (no note over it): a block per position inside.
  await expect(pane.getByRole("region", { name: "What was built" })).toHaveCount(0);
  await expect(pane.getByRole("tab", { name: "Builder" })).toHaveAttribute("aria-selected", "true");
  await expect(pane.locator(".react-flow__node").filter({ hasText: `Pump A ${tag}` })).toBeVisible();
  await expect(pane.locator(".react-flow__node").filter({ hasText: `Pump B ${tag}` })).toBeVisible();
  await expect(pane.locator(".rbd-full-status")).toContainText("Saved");
  // Open full page is the builder's ⋯ menu's last item; × ends its toolbar.
  await pane.getByRole("button", { name: "More diagram settings" }).click();
  await expect(pane.getByRole("link", { name: "Open full page" })).toHaveAttribute("href", `/systems/b/${rbdOf(page)}`);
  await pane.getByRole("button", { name: "More diagram settings" }).click();  // closes the menu
  await expect(pane.getByRole("link", { name: "Open full page" })).toHaveCount(0);
  await expect(pane.getByRole("button", { name: "Close the RBD" })).toBeVisible();
  // The whole diagram is in view: every block inside the canvas.
  await expect.poll(() => blocksInView(pane)).toEqual({ all: 4, inside: 4 });
  await shot(page, "1440-rbd-built");
  const first = rbdOf(page);

  // Esc: the table again, the position still picked, the address as it was.
  await page.keyboard.press("Escape");
  await expect(pane).toHaveCount(0);
  await expect(row(page, st.id)).toHaveAttribute("aria-selected", "true");
  await expect(page).not.toHaveURL(/[?&](rbd|on)=/);
  const rbd = page.locator(".tp-row", { has: page.locator(".tp-nm", { hasText: `Station ${tag} (from the tree)` }) });
  // The menu again: it opens the diagram already built (the same one) and never makes a second.
  await headMenu(page);
  await page.getByRole("menuitem", { name: "RBD", exact: true }).click();
  await expect(page.getByRole("menu", { name: "RBD" }).getByRole("menuitem"))
    .toHaveText(["Open the RBD", "Rebuild from what's inside…", "Redundancy inside…", "New blank RBD…", "Link an existing RBD…"]);  // + Redundancy (#829)
  await page.getByRole("menu", { name: "RBD" }).getByRole("menuitem", { name: "Open the RBD" }).click();
  await expect(pane).toBeVisible();
  expect(rbdOf(page)).toBe(first);
  await page.keyboard.press("Escape");
  await expect(pane).toHaveCount(0);
  await expect(rbd).toHaveCount(1);
  const links = (await (await request.get(`${M}/position-models?position_ids=${st.id}`)).json()).links;
  expect(links.filter((x) => x.model_type === "rbd").length).toBe(1);
  // Asked for again over the API: the same row comes back, nothing new saved.
  const again = await postOk(request, `${M}/positions/${st.id}/models`, { build_rbd: true });
  expect(again.existing).toBe(true);
  expect(again.model_id).toBe(first);
  await expect(rbd.locator(".mt-c-kind")).toContainText("RBD");
  await expect(rbd.locator(".mt-c-source")).toHaveText("Built from 2 positions inside · 1 placeholder");
  // A non-repairable RBD's headline is its mean life, never an MTBF (#815).
  await expect(rbd.locator(".mt-c-numbers")).toContainText(/Mean life [\d,]+ hours/);
  await expect(rbd.locator(".mt-c-quality")).toContainText("1 placeholder");
  // Its own life model is in use by default.
  const life = page.locator(".tp-row", { has: page.locator(".tp-nm", { hasText: "Bearing life — Lognormal" }) });
  await expect(life.locator(".ml-inuse")).toHaveText("In use");
  await rbd.locator(".tp-nm").click();
  await expect(side(page).locator(".ml-blocks tbody tr")).toHaveCount(2);
  await expect(side(page).locator(".ml-blocks")).toContainText("Placeholder");
  await expect(side(page).locator(".ml-blocks")).toContainText(`Pump A ${tag}`);
  await expect(side(page).getByRole("link", { name: "Open full page" })).toBeVisible();
  // Use this one: the RBD becomes the model in use.
  await page.keyboard.press("Escape");
  await rbd.locator(".tp-nm").click({ button: "right" });
  const menu = page.getByRole("menu").last();
  await expect(menu.getByRole("menuitem").first()).toHaveText("Open in the pane");
  await expect(menu.getByRole("menuitem", { name: "Open full page" })).toBeVisible();
  await menu.getByRole("menuitem", { name: "Use this one" }).click();
  await expect(rbd.locator(".ml-inuse")).toHaveText("In use");
  await expect(life.locator(".ml-inuse")).toHaveCount(0);
  await expect(row(page, st.id).locator(".tt-rollup-t")).toContainText("in use: RBD");
  await expectHealthy(page, problems, { label: "an RBD row" });
});

// An RBD row opens in the table area (a double-click, Enter, Open in the pane): the address keeps
// it over a reload; an edit saved goes to the diagram (the same save as its page); unsaved, ×
// and another row ask first; Rebuild from what's inside… reopens it; Link an existing RBD… is a
// picker, then the linked one opens.
test("an RBD row opens in the table area: reload, edit and save, unsaved changes, rebuild, link another", async ({ page, request, problems }) => {
  const tag = `ro${Date.now()}`;
  const st = await station(request, tag);
  const built = await postOk(request, `${M}/positions/${st.id}/models`, { build_rbd: true });
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${st.id}&tab=models`);
  const rbd = page.locator(".tp-row", { has: page.locator(".tp-nm", { hasText: `Station ${tag} (from the tree)` }) });
  await rbd.locator(".tp-nm").dblclick();
  const pane = rbdPane(page);
  await expect(pane).toBeVisible();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page).toHaveURL(new RegExp(`[?&]rbd=${built.model_id}&on=${st.id}`));
  const nodes = pane.locator(".react-flow__node");
  await expect(nodes.filter({ hasText: `Pump B ${tag}` })).toBeVisible();
  // No "what was built" note when only opened.
  await expect(pane.getByRole("region", { name: "What was built" })).toHaveCount(0);

  // A reload keeps it open, the builder on the canvas.
  await page.reload();
  await expect(pane).toBeVisible();
  await expect(nodes.filter({ hasText: `Pump B ${tag}` })).toBeVisible();
  const count = await nodes.count();

  // An edit: unsaved, so × asks; keeping it leaves the edit there.
  await pane.getByRole("button", { name: "Add block" }).click();
  await pane.locator(".ovm-item", { hasText: /^Component$/ }).click();
  await expect(nodes).toHaveCount(count + 1);
  await expect(pane.locator(".rbd-full-status")).toContainText("Unsaved changes");
  await pane.getByRole("button", { name: "Close the RBD" }).click();
  const discard = page.getByRole("alertdialog", { name: "Discard your changes to this RBD?" });
  await expect(discard).toBeVisible();
  await discard.getByRole("button", { name: "Keep editing" }).click();
  await expect(pane).toBeVisible();
  await expect(nodes).toHaveCount(count + 1);
  // Another row asks too. (A row beside this one: a new root can be far down a long tree that only
  // draws the rows in view, as on CI with every other test's plants.)
  await page.locator(".tp-row", { has: page.locator(".tp-nm", { hasText: `Pump B ${tag}` }) }).locator(".tp-nm").click();
  await expect(discard).toBeVisible();
  await discard.getByRole("button", { name: "Keep editing" }).click();
  await expect(pane).toBeVisible();
  // Esc in the block's name box is the builder's (the rename stops), not the pane's.
  await nodes.filter({ hasText: `Pump B ${tag}` }).click();
  await page.keyboard.press("F2");
  await expect(pane.locator(".react-flow__node input")).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(pane.locator(".react-flow__node input")).toHaveCount(0);
  await expect(pane).toBeVisible();

  // Saved the same way as the RBD's page: the diagram has the new block.
  await pane.locator(".rbd-save-main").click(); // Save saves in one click
  await expect(pane.locator(".rbd-full-status")).toContainText("Saved");
  await expect.poll(async () => ((await (await request.get(`/api/rbds/${built.model_id}`)).json()).graph.nodes || []).length).toBe(count + 1);
  // Saved: × closes without asking, the position picked.
  await pane.getByRole("button", { name: "Close the RBD" }).click();
  await expect(pane).toHaveCount(0);
  await expect(page.getByRole("alertdialog")).toHaveCount(0);
  await expect(row(page, st.id)).toHaveAttribute("aria-selected", "true");

  // Rebuild from what's inside…: the diagram opens and asks in the pane (no dialog). Cancel leaves
  // it as it is; Rebuild runs again into the same diagram, the saved edit kept.
  await rbd.locator(".tp-nm").click({ button: "right" });
  await page.getByRole("menu").last().getByRole("menuitem", { name: "Rebuild from what's inside…" }).click();
  await expect(pane).toBeVisible();
  const ask = pane.getByRole("group", { name: "Rebuild from what's inside" });
  await expect(ask).toContainText(`Rebuild from what’s inside Station ${tag}?`);
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByRole("alertdialog")).toHaveCount(0);
  await ask.getByRole("button", { name: "Cancel" }).click();
  await expect(ask).toHaveCount(0);
  await expect(nodes).toHaveCount(count + 1);
  await page.keyboard.press("Escape");
  await expect(pane).toHaveCount(0);
  await postOk(request, `${M}/positions`, { name: `Pump C ${tag}`, parent_id: st.id });
  await headPick(page, "RBD", "Rebuild from what's inside…");
  await expect(ask).toBeVisible();
  await ask.getByRole("button", { name: "Rebuild", exact: true }).click();
  await expect(ask).toHaveCount(0);
  await expect(page).toHaveURL(new RegExp(`[?&]rbd=${built.model_id}&on=${st.id}`));
  await expect(nodes.filter({ hasText: `Pump C ${tag}` })).toBeVisible();
  await expect(nodes).toHaveCount(count + 2);  // the saved edit kept, the new position's block added

  // Link an existing RBD…: a picker, then the linked diagram in the pane (a sample: read only).
  await page.keyboard.press("Escape");
  await headPick(page, "RBD", "Link an existing RBD…");
  const picker = page.getByRole("dialog", { name: "Link an existing RBD" });
  await picker.getByText("Pump station — 1 controller, 2 pumps (sample)").click();
  await picker.getByRole("button", { name: "Link", exact: true }).click();
  await expect(picker).toHaveCount(0);
  await expect(pane).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`[?&]rbd=sample-rbd-pump-station&on=${st.id}`));
  await expect(nodes.filter({ hasText: "PLC controller" })).toBeVisible();
  await expect(pane.locator(".rbd-full-status")).toContainText("Read only");
  await expectHealthy(page, problems, { label: "the RBD pane" });
});

// At 400 px the RBD takes the screen with ‹ Back: the builder fits, its toolbar on one row (the
// settings in ⋯), nothing sideways. The address alone opens it (a link, or a reload).
test("an RBD at 400 px takes the screen: the builder fits, nothing sideways, Back", async ({ page, request }) => {
  const tag = `rn${Date.now()}`;
  const st = await station(request, tag);
  const built = await postOk(request, `${M}/positions/${st.id}/models`, { build_rbd: true });
  await page.setViewportSize({ width: 400, height: 860 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${st.id}&tab=models&rbd=${built.model_id}&on=${st.id}`);
  const pane = rbdPane(page);
  await expect(pane.locator(".react-flow__node").filter({ hasText: `Pump A ${tag}` })).toBeVisible();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect(Math.round((await pane.boundingBox()).width)).toBe(400);
  expect(await sideways(page)).toBeLessThanOrEqual(400);
  expect(await pane.evaluate((el) => el.scrollWidth <= el.clientWidth + 1)).toBe(true);
  // The narrow toolbar: the unit and kind in ⋯, + Add, Validate and Save on one row.
  await expect(pane.locator(".rbd-builder")).toHaveClass(/is-narrow/);
  await expect(pane.locator(".rbd-tb-settings")).toBeHidden();
  const add = await pane.getByRole("button", { name: "Add block" }).boundingBox();
  const save = await pane.locator(".rbd-save-main").boundingBox();
  expect(Math.abs(add.y - save.y)).toBeLessThan(4);
  const canvas = await pane.locator(".rbd-canvas").boundingBox();
  expect(canvas.height).toBeGreaterThan(300);
  expect(canvas.x + canvas.width).toBeLessThanOrEqual(400.5);
  await shot(page, "400-rbd-pane");
  await pane.getByRole("button", { name: "Back to the table" }).click();
  await expect(pane).toHaveCount(0);
  await expect(row(page, st.id)).toBeVisible();
  await expect(page).not.toHaveURL(/[?&](rbd|on)=/);
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
  await headPick(page, "Life model", "Fit a life model…");
  const dialog = page.getByRole("region", { name: "Fit a life model" });
  // A plain fit to one failure is refused, in words; with a prior, the class has nothing besides this pump.
  await expect(dialog.getByRole("alert")).toContainText("a plain Weibull fit needs at least 2");
  // The refusal offers the way out: fit with a prior.
  await dialog.getByRole("button", { name: "Fit with a prior instead" }).click();
  await expect(dialog.getByRole("radio", { name: "With a prior" })).toHaveAttribute("aria-checked", "true");
  await expect(dialog.getByRole("alert")).toContainText("no history besides");
  await dialog.getByRole("combobox", { name: "Prior", exact: true }).selectOption("params");
  await expect(dialog).not.toContainText("no history besides");
  await expect(dialog).toContainText("Give the prior's numbers.");
  await dialog.getByLabel("Characteristic life (alpha)").fill("4");
  await dialog.getByLabel("Shape (beta)").fill("2");
  await dialog.getByLabel("Unit").selectOption("years");
  await expect(dialog.getByRole("status")).toContainText("90% one-sided credible bound"); // B-life bounds are one-sided (#818)
  await expect(dialog.getByRole("status")).toContainText("1 failure at");
  await expect(dialog.locator(".js-plotly-plot")).toBeVisible();
  await expect(dialog.getByRole("checkbox")).toHaveCount(2);
  await expect(dialog.locator(".fit2-numbers")).toContainText("90% credible interval");
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
  await expect(menu.locator(":scope > [role='menuitem']")).toHaveText(["Life model", "RBD", "Prediction", "Rename…", "Focus", "Pin this branch"]);
  await expect(menu.getByRole("separator")).toHaveCount(1);
  for (const gone of ["New position inside", "Add failure report…", "Log an event…", "Move to…", "Delete…"]) {
    await expect(menu.getByRole("menuitem", { name: gone })).toHaveCount(0);
  }
  // The keyboard: → opens a group.
  await menu.getByRole("menuitem", { name: "RBD", exact: true }).focus();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("menu", { name: "RBD" }).getByRole("menuitem")).toHaveText(["Build from what's inside…", "Redundancy inside…", "New blank RBD…", "Link an existing RBD…"]);  // + Redundancy (#829)
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

// "Fit a life model…" through each Data choice, on a class of two pumps: this pump's own history
// (a plain fit), the class's pooled history (how many positions, failures and suspensions), and
// both (this pump's history with the other pump's as a power prior, counted as half its evidence).
test("Fit a life model… through each Data choice on a class of two positions", async ({ page, request, problems }) => {
  const tag = `f${Date.now()}`;
  const ago = (d) => new Date(Date.now() - d * 864e5).toISOString().slice(0, 10);
  const klass = `Fit pump ${tag}`;
  const a = await postOk(request, `${M}/positions`, { name: `Fit pump A ${tag}`, position_class: klass });
  const b = await postOk(request, `${M}/positions`, { name: `Fit pump B ${tag}`, position_class: klass });
  for (const [pos, lives] of [[a, [300, 420, 380]], [b, [350, 260]]]) {
    let at = 2000;
    for (const [i, life] of lives.entries()) {
      await postOk(request, `${M}/positions/${pos.id}/fit`, { new_item: { name: `U${i} ${pos.id.slice(-4)}` }, on: ago(at) });
      at -= life;
      await postOk(request, `${M}/positions/${pos.id}/remove`, { on: ago(at), reason: "failure" });
    }
    await postOk(request, `${M}/positions/${pos.id}/fit`, { new_item: { name: `Run ${pos.id.slice(-4)}` }, on: ago(at) });
  }
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${b.id}&tab=models`);
  await headPick(page, "Life model", "Fit a life model…");
  const dialog = page.getByRole("region", { name: "Fit a life model" });
  await expect(dialog.getByRole("status")).toContainText("A plain fit (maximum likelihood) to 2 failures and 1 suspension in this position's history");
  await expect(dialog.locator(".fit2-numbers thead")).toContainText("90% confidence bounds");
  await dialog.getByRole("combobox", { name: "Data" }).selectOption("class");
  await expect(dialog).toContainText(`2 positions of ${klass}: 5 failures, 2 suspensions`);
  await expect(dialog.getByRole("status")).toContainText("5 failures and 2 suspensions in the class");
  await dialog.getByRole("combobox", { name: "Data" }).selectOption("both");
  await expect(dialog.getByRole("status")).toContainText("counted as half of its evidence");
  await expect(dialog.locator(".fit2-numbers thead")).toContainText("90% credible interval");
  await expect(dialog.locator(".js-plotly-plot")).toBeVisible();
  await saveFit(page, dialog, b.id);
  const model = page.locator(".tp-row", { has: page.locator(".tp-nm", { hasText: "Bayesian update of the class" }) });
  await expect(model.locator(".mt-c-kind")).toHaveText("Weibull (Bayesian)");
  await expectHealthy(page, problems, { label: "Fit a life model" });
});

test("the fit at 400 px takes the screen: inputs, then the result, nothing sideways, Save in reach, Back", async ({ page, request }) => {
  const tag = `w${Date.now()}`;
  const ago = (d) => new Date(Date.now() - d * 864e5).toISOString().slice(0, 10);
  const pump = await postOk(request, `${M}/positions`, { name: `Narrow pump ${tag}` });
  let at = 1500;
  for (const life of [300, 420, 380]) {
    await postOk(request, `${M}/positions/${pump.id}/fit`, { new_item: { name: `N${life} ${tag}` }, on: ago(at) });
    at -= life;
    await postOk(request, `${M}/positions/${pump.id}/remove`, { on: ago(at), reason: "failure" });
  }
  await page.setViewportSize({ width: 400, height: 860 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${pump.id}&tab=models`);
  await row(page, pump.id).locator(".tp-nm").click({ button: "right" });
  await page.getByRole("menuitem", { name: "Life model", exact: true }).click();
  await page.getByRole("group", { name: "Life model" }).getByRole("menuitem", { name: "Fit a life model…" }).click();
  const dialog = page.getByRole("region", { name: "Fit a life model" });
  await expect(dialog.getByRole("status")).toContainText("A plain fit (maximum likelihood) to 3 failures");
  await expect(page.getByRole("dialog", { name: "Fit a life model" })).toHaveCount(0);
  const paneBox = await dialog.boundingBox();
  expect(Math.round(paneBox.width)).toBe(400);  // the whole screen, as the Explorer's other panels on a phone
  const inBox = await dialog.locator(".fit2-in").boundingBox();
  const outBox = await dialog.locator(".fit2-out").boundingBox();
  expect(outBox.y).toBeGreaterThan(inBox.y);  // stacked: inputs first
  expect(await sideways(page)).toBeLessThanOrEqual(400);
  expect(await dialog.evaluate((el) => el.scrollWidth <= el.clientWidth + 1)).toBe(true);
  await dialog.getByRole("button", { name: "Save as this position's model" }).scrollIntoViewIfNeeded();
  await expect(dialog.getByRole("button", { name: "Save as this position's model" })).toBeEnabled();
  // Back: the tree again.
  await dialog.getByRole("button", { name: "Back to the table" }).click();
  await expect(dialog).toHaveCount(0);
  await expect(row(page, pump.id)).toBeVisible();
});

// Too narrow for the two columns side by side (the tree takes its share of a 1280 px window): the
// parts stack, each as tall as what's in it, so neither is drawn over the other; the pane scrolls
// as one, and Cancel and Save stay at its foot whichever part is being read.
test("the fit beside the tree at 1280 px stacks its two parts, neither over the other, Save always in view", async ({ page, request }) => {
  const tag = `k${Date.now()}`;
  const ago = (d) => new Date(Date.now() - d * 864e5).toISOString().slice(0, 10);
  const pump = await postOk(request, `${M}/positions`, { name: `Stacked pump ${tag}` });
  let at = 1500;
  for (const life of [300, 420, 380]) {
    await postOk(request, `${M}/positions/${pump.id}/fit`, { new_item: { name: `K${life} ${tag}` }, on: ago(at) });
    at -= life;
    await postOk(request, `${M}/positions/${pump.id}/remove`, { on: ago(at), reason: "failure" });
  }
  await page.setViewportSize({ width: 1280, height: 800 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${pump.id}&tab=models`);
  await headPick(page, "Life model", "Fit a life model…");
  const dialog = page.getByRole("region", { name: "Fit a life model" });
  await expect(dialog.getByRole("status")).toContainText("A plain fit (maximum likelihood) to 3 failures");
  // The tallest the inputs get: a prior, typed as ranges.
  await dialog.getByRole("radio", { name: "With a prior" }).click();
  await dialog.getByRole("combobox", { name: "Prior", exact: true }).selectOption("around");
  await expect(dialog.getByRole("group", { name: "Around a value, between two bounds" })).toBeVisible();
  const save = dialog.getByRole("button", { name: "Save as this position's model" });
  const parts = () => dialog.evaluate((el) => {
    const box = (sel) => { const e = el.querySelector(sel); const r = e.getBoundingClientRect(); return { top: r.top, bottom: r.bottom, left: r.left, spills: e.scrollHeight - e.clientHeight }; };
    return { pane: el.getBoundingClientRect().bottom, inputs: box(".fit2-in"), result: box(".fit2-out"), foot: box(".fit2-foot") };
  });
  const top = await parts();
  expect(top.result.left).toBeLessThanOrEqual(top.inputs.left + 1);  // stacked, not side by side
  expect(top.result.top).toBeGreaterThanOrEqual(top.inputs.bottom - 1);  // the result starts where the inputs end
  expect(top.inputs.spills).toBeLessThanOrEqual(1);  // and nothing of either hangs out of its box
  expect(top.result.spills).toBeLessThanOrEqual(1);
  expect(top.foot.bottom).toBeLessThanOrEqual(top.pane + 1);
  await expect(save).toBeInViewport({ ratio: 1 });
  // Scrolled to the end of the result: the bar is still at the pane's foot, under the last of it.
  const scrolled = await dialog.locator(".fit2").evaluate((el) => { el.scrollTop = el.scrollHeight; return el.scrollTop; });
  expect(scrolled).toBeGreaterThan(0);
  const end = await parts();
  expect(end.foot.bottom).toBeLessThanOrEqual(end.pane + 1);
  expect(end.foot.top).toBeGreaterThanOrEqual(top.foot.top - 1);
  await expect(save).toBeInViewport({ ratio: 1 });
  expect(await sideways(page)).toBeLessThanOrEqual(1280);
});

// A prior around a value, between two bounds: alpha about 400 (90% between 300 and 600), beta just
// between 1.5 and 4; no trust chips (the ranges are the belief); the how-it-was-computed line says it.
test("Fit a life model… with a prior around a value, between two bounds", async ({ page, request, problems }) => {
  const tag = `a${Date.now()}`;
  const ago = (d) => new Date(Date.now() - d * 864e5).toISOString().slice(0, 10);
  const pump = await postOk(request, `${M}/positions`, { name: `Around pump ${tag}` });
  await postOk(request, `${M}/positions/${pump.id}/fit`, { new_item: { name: `A1 ${tag}` }, on: ago(700) });
  await postOk(request, `${M}/positions/${pump.id}/remove`, { on: ago(350), reason: "failure" });
  await postOk(request, `${M}/positions/${pump.id}/fit`, { new_item: { name: `A2 ${tag}` }, on: ago(350) });
  const other = await postOk(request, `${M}/positions`, { name: `Around neighbour ${tag}` });
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${pump.id}&tab=models`);
  await headPick(page, "Life model", "Fit a life model…");
  const dialog = page.getByRole("region", { name: "Fit a life model" });
  // In the table area, not a dialog: the tree beside it, the heading naming the position, the address saying so.
  await expect(dialog).toBeVisible();
  await expect(page.getByRole("dialog", { name: "Fit a life model" })).toHaveCount(0);
  await expect(page.locator(".tt-main .tt-side .fit-pane")).toBeVisible();
  await expect(dialog.locator(".table-pane-title")).toHaveText(`Fit a life model · Around pump ${tag}`);
  await expect(row(page, pump.id)).toBeVisible();
  await expect(row(page, other.id)).toBeVisible();
  await expect(row(page, pump.id)).toHaveAttribute("aria-selected", "true");
  await expect(page).toHaveURL(new RegExp(`[?&]fit=${pump.id}`));
  const treeBox = await page.locator(".tp-scroll").boundingBox();
  const paneBox = await dialog.boundingBox();
  expect(paneBox.x).toBeGreaterThanOrEqual(treeBox.x + treeBox.width - 2);  // beside the tree
  expect(paneBox.width).toBeGreaterThan(700);  // the table's room, both columns side by side
  const inBox = await dialog.locator(".fit2-in").boundingBox();
  const outBox = await dialog.locator(".fit2-out").boundingBox();
  expect(outBox.x).toBeGreaterThan(inBox.x);
  // Escape: the table again, the row still picked and focused, the address back as it was.
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(row(page, pump.id)).toHaveAttribute("aria-selected", "true");
  await expect(row(page, pump.id)).toBeFocused();
  await expect(page).not.toHaveURL(/[?&]fit=/);
  // ×: the same. Nothing changed, so picking another row just closes it.
  await headPick(page, "Life model", "Fit a life model…");
  await dialog.getByRole("button", { name: "Close fit a life model" }).click();
  await expect(dialog).toHaveCount(0);
  await expect(row(page, pump.id)).toBeFocused();
  await headPick(page, "Life model", "Fit a life model…");
  await row(page, other.id).locator(".tp-nm").click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByRole("alertdialog", { name: "Discard this fit?" })).toHaveCount(0);
  await row(page, pump.id).locator(".tp-nm").click();
  // A reload keeps it open (the choices fresh).
  await headPick(page, "Life model", "Fit a life model…");
  await dialog.getByRole("radio", { name: "With a prior" }).click();
  await page.reload();
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole("radio", { name: "Plain fit" })).toHaveAttribute("aria-checked", "true");
  await expect(dialog.getByRole("combobox", { name: "Data" }).locator("option").first()).toHaveText("This position's history (1 failure, 1 suspension)");
  await dialog.getByRole("radio", { name: "With a prior" }).click();
  await dialog.getByRole("combobox", { name: "Prior", exact: true }).selectOption("around");
  await expect(dialog.getByRole("radiogroup", { name: "How much to trust the prior" })).toHaveCount(0);
  const rows = dialog.getByRole("group", { name: "Around a value, between two bounds" });
  await rows.getByLabel("Characteristic life (alpha) about").fill("400");
  await rows.getByLabel("Characteristic life (alpha) between").fill("300");
  await rows.getByLabel("Characteristic life (alpha) and").fill("600");
  await rows.getByLabel("Shape (beta) between").fill("1.5");
  await rows.getByLabel("Shape (beta) and").fill("4");
  await rows.getByLabel("Unit").selectOption("days");
  await expect(dialog.getByRole("status")).toContainText("(as stated)");
  await expect(dialog.locator(".fit2-how")).toContainText("alpha about 400, 90% between 300 and 600; beta 90% between 1.5 and 4");
  // A bound the wrong way round is refused in words, before asking.
  await rows.getByLabel("Shape (beta) and").fill("1");
  await expect(dialog).toContainText("For Shape (beta), the low bound must be below the high one.");
  await rows.getByLabel("Shape (beta) and").fill("4");
  // Changed: picking another row asks first; keeping it leaves everything as typed.
  await row(page, other.id).locator(".tp-nm").click();
  const discard = page.getByRole("alertdialog", { name: "Discard this fit?" });
  await expect(discard).toBeVisible();
  await discard.getByRole("button", { name: "Keep fitting" }).click();
  await expect(dialog).toBeVisible();
  await expect(rows.getByLabel("Characteristic life (alpha) about")).toHaveValue("400");
  await expect(row(page, pump.id)).toHaveAttribute("aria-selected", "true");
  await saveFit(page, dialog, pump.id);
  // Saved: the table again, the new model row under the pump picked.
  const picked = page.locator(`.tp-row[aria-selected="true"][data-key^="L:"]`);
  await expect(picked).toHaveCount(1);
  await expect(picked.locator(".mt-c-kind")).toContainText("Bayesian");
  await expectHealthy(page, problems, { label: "a prior around a value" });
});

// Life model › From the data library… at 400 px: "Pick a library record" fills the screen over the
// dialog, each record a card (the name, one grey line), and nothing scrolls the page sideways.
test("the library record picker at 400 px", async ({ page, request, problems }) => {
  const tag = `lp${Date.now()}`;
  const pump = await postOk(request, `${M}/positions`, { name: `Phone pump ${tag}` });
  await page.setViewportSize({ width: 400, height: 860 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${pump.id}&tab=models`);
  await row(page, pump.id).locator(".tp-nm").click({ button: "right" });
  await page.getByRole("menuitem", { name: "Life model", exact: true }).click();
  await page.getByRole("group", { name: "Life model" }).getByRole("menuitem", { name: "From the data library…" }).click();
  const picker = page.getByRole("dialog", { name: "Pick a library record" });
  await picker.getByRole("combobox", { name: "Search the data library" }).fill("Motor-driven pump fails to run");
  const first = picker.getByRole("listbox").getByRole("option").first();
  await expect(first.locator(".lib-pick-detail")).toBeVisible();
  await expect(first.locator(".lib-pick-detail")).toContainText("NRC/INL 2020");
  await expect(picker.locator(".lib-pick-head")).toBeHidden();
  const box = await picker.boundingBox();
  expect(Math.round(box.width)).toBe(400);
  expect(await sideways(page)).toBeLessThanOrEqual(400);
  expect(await picker.locator(".lib-pick-list").evaluate((el) => el.scrollWidth <= el.clientWidth + 1)).toBe(true);
  await first.click();
  await expect(picker).toHaveCount(0);
  // A published record goes on to Fix covariates (its covariates fixed here or set in the RBD), at 400 px too.
  const pane = page.getByRole("region", { name: "Fix covariates" });
  await expect(pane).toContainText("Motor-driven pump");
  expect(await sideways(page)).toBeLessThanOrEqual(400);
  await expectHealthy(page, problems, { label: "the library record picker at 400 px" });
});

// The product page's Modelling tab is the same Explorer: the fit fills its table area too, the
// address keeping the page's own ?view=, and Escape returns to the table.
test("a product's Modelling tab: Fit a life model… in the table area", async ({ page, request, problems }) => {
  const tag = `pp${Date.now()}`;
  const product = await postOk(request, `${M}/products`, { name: `Fit drone ${tag}`, part_number: `FD-${tag}` });
  const motor = await postOk(request, `${M}/positions`, { name: `Fit motor ${tag}`, parent_id: product.id });
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, `/products/${product.id}?view=models&sel=${motor.id}`);
  await headPick(page, "Life model", "Fit a life model…");
  const pane = page.getByRole("region", { name: "Fit a life model" });
  await expect(pane.locator(".table-pane-title")).toHaveText(`Fit a life model · Fit motor ${tag}`);
  await expect(page.getByRole("dialog", { name: "Fit a life model" })).toHaveCount(0);
  await expect(row(page, motor.id)).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`/products/${product.id}\\?.*view=models.*fit=${motor.id}`));
  await page.reload();
  await expect(pane).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(pane).toHaveCount(0);
  await expect(row(page, motor.id)).toHaveAttribute("aria-selected", "true");
  await expect(page).not.toHaveURL(/[?&]fit=/);
  await expectHealthy(page, problems, { label: "a product's fit pane" });
});

// "Add a prediction (parts count)…" in the table area, as Fit a life model… is: beside the tree,
// the parts table across it with its result beside it, live; the part-type list over the pane,
// not cut off; Esc and × back to the table; another row asks first only when something changed;
// ?predict= survives a reload; Save picks the new row.
async function predictedController(request, tag) {
  const ctl = await postOk(request, `${M}/positions`, { name: `Prediction board ${tag}` });
  for (const [pn, name, quantity] of [[`C-${tag}`, `Bypass capacitor ${tag}`, 4], [`R-${tag}`, `Chip resistor ${tag}`, 12], [`AF-${tag}`, `Enclosure ${tag}`, 1]]) {
    const part = await postOk(request, `${M}/parts`, { part_number: pn, name });
    await postOk(request, `${M}/positions/${ctl.id}/parts`, { part_id: part.id, role: "component", quantity });
  }
  return ctl;
}

test("Add a prediction… opens in the table area: live result, the part-type list not cut off, Esc, discard, reload, save", async ({ page, request, problems }) => {
  const tag = `pr${Date.now()}`;
  const ctl = await predictedController(request, tag);
  const other = await postOk(request, `${M}/positions`, { name: `Prediction neighbour ${tag}` });
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${ctl.id}&tab=models`);
  await headPick(page, "Prediction", "Add a prediction (parts count)…");
  const pane = page.getByRole("region", { name: "Add a prediction" });
  await expect(pane).toBeVisible();
  await expect(page.getByRole("dialog", { name: "Add a prediction" })).toHaveCount(0);
  await expect(page.locator(".tt-main .tt-side .pred-pane")).toBeVisible();
  await expect(pane.locator(".table-pane-title")).toHaveText(`Add a prediction · Prediction board ${tag}`);
  await expect(row(page, ctl.id)).toHaveAttribute("aria-selected", "true");
  await expect(row(page, other.id)).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`[?&]predict=${ctl.id}`));
  const treeBox = await page.locator(".tp-scroll").boundingBox();
  const paneBox = await pane.boundingBox();
  expect(paneBox.x).toBeGreaterThanOrEqual(treeBox.x + treeBox.width - 2);  // beside the tree
  expect(paneBox.width).toBeGreaterThan(800);  // the table's room
  // The parts across the pane, every column in view; at this width the result under them, in view
  // with Save (side by side on a wider screen: the product test below).
  await expect(pane.locator(".pred2-table tbody tr")).toHaveCount(3);
  await expect(pane.locator(".pred2-table thead th")).toHaveText(["Part", "Qty", "Handbook part type", "Quality or conditions", "Not electronic", "Your own rate", "λ per 10⁶ h", "Actions"]);
  const inBox = await pane.locator(".pred2-in").boundingBox();
  const outBox = await pane.locator(".pred2-out").boundingBox();
  expect(outBox.y).toBeGreaterThan(inBox.y + inBox.height - 2);
  expect(outBox.y + outBox.height).toBeLessThanOrEqual(900);
  const lines = pane.locator(".pred2-lines");
  expect(await lines.evaluate((el) => el.scrollWidth <= el.clientWidth + 1)).toBe(true);
  await expect(pane.locator(".pred2-ref").first()).toHaveText(`C-${tag}`);
  await expect(pane.getByRole("status")).toContainText("Give the parts their handbook part types");
  await expect(pane.getByRole("button", { name: "Save as this position's model" })).toBeDisabled();

  // Esc: the table again, the row still picked and focused, the address back as it was.
  await page.keyboard.press("Escape");
  await expect(pane).toHaveCount(0);
  await expect(row(page, ctl.id)).toHaveAttribute("aria-selected", "true");
  await expect(row(page, ctl.id)).toBeFocused();
  await expect(page).not.toHaveURL(/[?&]predict=/);
  // ×: the same. Nothing changed, so picking another row just closes it.
  await headPick(page, "Prediction", "Add a prediction (parts count)…");
  await pane.getByRole("button", { name: "Close add a prediction" }).click();
  await expect(pane).toHaveCount(0);
  await expect(row(page, ctl.id)).toBeFocused();
  await headPick(page, "Prediction", "Add a prediction (parts count)…");
  await expect(pane.locator(".pred2-table tbody tr")).toHaveCount(3);
  await row(page, other.id).locator(".tp-nm").click();
  await expect(pane).toHaveCount(0);
  await expect(page.getByRole("alertdialog", { name: "Discard this prediction?" })).toHaveCount(0);
  await row(page, ctl.id).locator(".tp-nm").click();

  // A reload keeps it open.
  await headPick(page, "Prediction", "Add a prediction (parts count)…");
  await page.reload();
  await expect(pane).toBeVisible();
  await expect(pane.locator(".pred2-table tbody tr")).toHaveCount(3);

  // A part type from the search: the list shows whole over the pane, not cut off by the table.
  const picker = pane.getByRole("combobox", { name: `Handbook part type of Bypass capacitor ${tag}` });
  await picker.fill("capacitor");
  const list = page.getByRole("listbox", { name: `Handbook part type of Bypass capacitor ${tag} matches` });
  await expect(list.getByRole("option").first()).toBeVisible();
  const lb = await list.boundingBox();
  expect(lb.y + lb.height).toBeLessThanOrEqual(900);
  expect(lb.height).toBeGreaterThan(100);
  const onTop = await list.evaluate((el) => {
    const r = el.getBoundingClientRect();
    return el.contains(document.elementFromPoint(r.left + r.width / 2, r.bottom - 6));
  });
  expect(onTop).toBe(true);
  // Esc closes the list first, the pane stays.
  await page.keyboard.press("Escape");
  await expect(list).toHaveCount(0);
  await expect(pane).toBeVisible();
  // ↓ opens it again on the same words.
  await picker.press("ArrowDown");
  await list.getByRole("option").first().click();
  // The live result: the rate, the MTBF, the line's own λ, and what's left out.
  const status = pane.getByRole("status");
  await expect(status).toContainText("failures per million hours");
  await expect(status).toContainText(/about [\d,.]+ hours/);
  await expect(status).toContainText("1 of 3 lines counted");
  await expect(status).toContainText(`Left out, no part type yet: Chip resistor ${tag} ×12, Enclosure ${tag}`);
  await expect(pane.locator(".pred2-c-lambda").first()).not.toHaveText("—");
  await pane.getByRole("checkbox", { name: `Enclosure ${tag} is not electronic: leave it out` }).check();
  await expect(status).toContainText(`Left out, not electronic: Enclosure ${tag}`);
  await pane.getByLabel(`Your own failure rate for Chip resistor ${tag}, per million hours`).fill("0.5");
  await expect(status).toContainText("2 of 3 lines counted");
  await pane.getByLabel("Mission time (hours)").fill("500");
  await expect(status).toContainText("chance of no failure in 500 hours");

  // Changed: picking another row asks first; keeping it leaves everything as it was.
  await row(page, other.id).locator(".tp-nm").click();
  const discard = page.getByRole("alertdialog", { name: "Discard this prediction?" });
  await expect(discard).toBeVisible();
  await discard.getByRole("button", { name: "Keep predicting" }).click();
  await expect(pane).toBeVisible();
  await expect(pane.getByLabel("Mission time (hours)")).toHaveValue("500");
  await expect(row(page, ctl.id)).toHaveAttribute("aria-selected", "true");

  // Saved: the table again, the new prediction row picked.
  await pane.getByRole("button", { name: "Save as this position's model" }).click();
  await expect(pane).toHaveCount(0);
  const picked = page.locator(`.tp-row[aria-selected="true"][data-key^="L:"]`);
  await expect(picked).toHaveCount(1);
  await expect(picked.locator(".mt-c-kind")).toHaveText("Prediction (parts count)");
  await expectHealthy(page, problems, { label: "the prediction pane" });
});

test("the prediction at 400 px takes the screen: the parts, then the result, nothing sideways, Save in reach, Back", async ({ page, request }) => {
  const tag = `pn${Date.now()}`;
  const ctl = await predictedController(request, tag);
  await page.setViewportSize({ width: 400, height: 860 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${ctl.id}&tab=models`);
  await row(page, ctl.id).locator(".tp-nm").click({ button: "right" });
  await page.getByRole("menuitem", { name: "Prediction", exact: true }).click();
  await page.getByRole("group", { name: "Prediction" }).getByRole("menuitem", { name: "Add a prediction (parts count)…" }).click();
  const pane = page.getByRole("region", { name: "Add a prediction" });
  await expect(pane.locator(".pred2-table tbody tr")).toHaveCount(3);
  await expect(page.getByRole("dialog", { name: "Add a prediction" })).toHaveCount(0);
  const paneBox = await pane.boundingBox();
  expect(Math.round(paneBox.width)).toBe(400);
  const inBox = await pane.locator(".pred2-in").boundingBox();
  const outBox = await pane.locator(".pred2-out").boundingBox();
  expect(outBox.y).toBeGreaterThan(inBox.y);  // stacked: the parts first
  expect(await sideways(page)).toBeLessThanOrEqual(400);
  expect(await pane.evaluate((el) => el.scrollWidth <= el.clientWidth + 1)).toBe(true);
  // The part-type list stays on the screen.
  await pane.getByRole("combobox", { name: `Handbook part type of Bypass capacitor ${tag}` }).fill("capacitor");
  const list = page.getByRole("listbox", { name: `Handbook part type of Bypass capacitor ${tag} matches` });
  await expect(list.getByRole("option").first()).toBeVisible();
  const lb = await list.boundingBox();
  expect(lb.x).toBeGreaterThanOrEqual(0);
  expect(lb.x + lb.width).toBeLessThanOrEqual(400);
  await list.getByRole("option").first().click();
  await expect(pane.getByRole("status")).toContainText("failures per million hours");
  await pane.getByRole("button", { name: "Save as this position's model" }).scrollIntoViewIfNeeded();
  await expect(pane.getByRole("button", { name: "Save as this position's model" })).toBeEnabled();
  expect(await sideways(page)).toBeLessThanOrEqual(400);
  await pane.getByRole("button", { name: "Back to the table" }).click();
  await expect(pane).toHaveCount(0);
  await expect(row(page, ctl.id)).toBeVisible();
});

// Adding and removing the prediction's lines (Derryn, 9 Nov 2026: "definitely need a way to add and
// remove rows from the parts prediction"): the empty state's buttons, a new part on a position
// inside it (the same New part form), typed, the result changing; a line left out and put back;
// its quantity changed on the parts list; one taken off its parts list (asked first, with Undo).
test("the prediction's lines: add a part on a child, leave one out and put it back, change a quantity, remove one", async ({ page, request, problems }) => {
  const tag = `pa${Date.now()}`;
  const power = await postOk(request, `${M}/positions`, { name: `Power ${tag}` });
  const board = await postOk(request, `${M}/positions`, { name: `Board ${tag}`, parent_id: power.id });
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, `/asset-register/explorer?arrange=positions&sel=${power.id}&tab=models`);
  await headPick(page, "Prediction", "Add a prediction (parts count)…");
  const pane = page.getByRole("region", { name: "Add a prediction" });
  await expect(pane.getByText(`No parts listed on Power ${tag} or inside it.`)).toBeVisible();
  await expect(pane.getByRole("button", { name: "Import a BOM" })).toBeVisible();
  // Import a BOM: the same dialog as the Parts tab's.
  await pane.getByRole("button", { name: "Import a BOM" }).click();
  await expect(page.getByRole("dialog", { name: "Import a BOM" })).toBeVisible();
  await page.getByRole("dialog", { name: "Import a BOM" }).getByRole("button", { name: "Cancel" }).click();

  // Add a part, on the board inside it: the line comes in with its part-type picker focused.
  const addPart = async (pn, name, on, quantity) => {
    await pane.getByRole("button", { name: "Add a part" }).first().click();
    const dlg = page.getByRole("dialog", { name: "New part" });
    await dlg.getByLabel("Part number").fill(pn);
    await dlg.getByLabel("Name").fill(name);
    await dlg.getByRole("combobox", { name: "On", exact: true }).selectOption(on);
    await dlg.getByLabel("Quantity").fill(String(quantity));
    await dlg.getByRole("button", { name: "Add" }).click();
    await expect(dlg).toHaveCount(0);
  };
  await addPart(`C-${tag}`, `Capacitor ${tag}`, board.id, 2);
  const rows = pane.locator(".pred2-table tbody tr");
  await expect(rows).toHaveCount(1);
  const capType = pane.getByRole("combobox", { name: `Handbook part type of Capacitor ${tag}` });
  await expect(capType).toBeFocused();
  await expect(rows.first().locator(".pred2-ref")).toContainText(`Board ${tag}`);
  await capType.fill("capacitor");
  await page.getByRole("listbox", { name: `Handbook part type of Capacitor ${tag} matches` }).getByRole("option").first().click();
  const status = pane.getByRole("status");
  const big = pane.locator(".pred2-big b");
  await expect(status).toContainText("failures per million hours");
  const one = await big.textContent();

  // A second part, on the position itself, from the foot of the table.
  await addPart(`U-${tag}`, `Opto-isolator ${tag}`, power.id, 1);
  await expect(rows).toHaveCount(2);
  const optoType = pane.getByRole("combobox", { name: `Handbook part type of Opto-isolator ${tag}` });
  await expect(optoType).toBeFocused();
  await optoType.fill("opto");
  await page.getByRole("listbox", { name: `Handbook part type of Opto-isolator ${tag} matches` }).getByRole("option").first().click();
  await expect(big).not.toHaveText(one);
  const two = await big.textContent();
  await expect(status).toContainText("2 of 2 lines counted");
  await pane.locator(".pred2-lines").evaluate((el) => { el.scrollLeft = 0; });
  await shot(page, "1440-prediction-added-row");

  // Leave the opto-isolator out of this prediction (it stays on the list), then put it back.
  const optoRow = rows.filter({ hasText: `Opto-isolator ${tag}` });
  await optoRow.getByRole("button", { name: `Actions for Opto-isolator ${tag}` }).click();
  const menu = page.getByRole("menu", { name: `Actions for Opto-isolator ${tag}` });
  await expect(menu.getByRole("menuitem")).toHaveText(["Change quantity", "Leave out of this prediction", "Remove from the parts list…"]);
  await shot(page, "1440-prediction-line-menu");
  await menu.getByRole("menuitem", { name: "Leave out of this prediction" }).click();
  await expect(optoRow).toHaveClass(/pred2-out-row/);
  await expect(optoRow).toContainText("Left out of this prediction");
  await expect(status).toContainText(`Left out of this prediction: Opto-isolator ${tag}`);
  await expect(big).toHaveText(one);
  await pane.locator(".pred2-lines").evaluate((el) => { el.scrollLeft = 0; });
  await shot(page, "1440-prediction-left-out");
  await optoRow.getByRole("button", { name: "Put back" }).click();
  await expect(optoRow).not.toHaveClass(/pred2-out-row/);
  await expect(big).toHaveText(two);

  // Change the capacitor's quantity, on its parts list: the result follows.
  const qty = pane.getByLabel(`Quantity of Capacitor ${tag}`);
  await qty.fill("6");
  await qty.press("Enter");
  await expect(big).not.toHaveText(two);
  const listed = await (await request.get(`${M}/positions/${power.id}/parts`)).json();
  expect(listed.parts_list.map((x) => x.part.part_number)).toEqual([`U-${tag}`]);

  // Remove the opto-isolator from its parts list (right-click), asked first; Undo puts it back.
  await optoRow.click({ button: "right" });
  await page.getByRole("menu", { name: `Actions for Opto-isolator ${tag}` }).getByRole("menuitem", { name: "Remove from the parts list…" }).click();
  const ask = page.getByRole("dialog", { name: "Remove from the parts list" });
  await expect(ask).toContainText(`Remove Opto-isolator ${tag} from Power ${tag}’s parts list? It also leaves the BOM and the LSA. The part itself stays in your parts.`);
  await ask.getByRole("button", { name: "Remove" }).click();
  await expect(rows).toHaveCount(1);
  await expect(pane.getByText(`Removed Opto-isolator ${tag} from Power ${tag}’s parts list.`)).toBeVisible();
  await pane.getByRole("button", { name: "Undo" }).click();
  await expect(rows).toHaveCount(2);

  // 400 px: nothing sideways.
  await page.setViewportSize({ width: 400, height: 860 });
  await expect(rows).toHaveCount(2);
  expect(await sideways(page)).toBeLessThanOrEqual(400);
  await shot(page, "400-prediction-lines");
  await optoRow.getByRole("button", { name: `Actions for Opto-isolator ${tag}` }).click();
  await shot(page, "400-prediction-line-menu");
  await page.getByRole("menu", { name: `Actions for Opto-isolator ${tag}` }).getByRole("menuitem", { name: "Leave out of this prediction" }).click();
  await expect(optoRow).toHaveClass(/pred2-out-row/);
  await pane.locator(".pred2-lines").evaluate((el) => { el.scrollLeft = 0; });
  await optoRow.scrollIntoViewIfNeeded();
  await expect(optoRow.getByRole("button", { name: "Put back" })).toBeVisible();
  await expect(pane.getByRole("button", { name: "Add a part" })).toBeInViewport();
  await shot(page, "400-prediction-left-out");
  expect(await sideways(page)).toBeLessThanOrEqual(400);
  await expectHealthy(page, problems, { label: "adding and removing prediction lines" });
});

test("a product's Modelling tab: Add a prediction… in the table area, on the Survey quadcopter", async ({ page, request, problems }) => {
  const { products } = await (await request.get(`${M}/products`)).json();
  const quad = products.find((p) => /^Survey quadcopter/.test(p.name));
  expect(quad, "the seeded Survey quadcopter").toBeTruthy();
  for (const [width, height] of [[1920, 1080], [1440, 900], [400, 860]]) {
    await page.setViewportSize({ width, height });
    // The address alone opens it (a link, or a reload).
    await open(page, `/products/${quad.id}?view=models&sel=${quad.id}&predict=${quad.id}`);
    const pane = page.getByRole("region", { name: /^(Add a prediction|Refresh the prediction)$/ });
    await expect(pane).toBeVisible();
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await expect(pane.locator(".table-pane-title")).toContainText("Survey quadcopter");
    await expect(pane.locator(".pred2-table tbody tr").first()).toBeVisible();
    await expect(pane.getByRole("status")).toBeVisible();
    // A few parts given their types, the mechanical ones left out, the battery a rate of its own.
    for (const [part, words] of [["Flight controller", "microprocessor"], ["Brushless motor 2210", "motor"]]) {
      await pane.getByRole("combobox", { name: `Handbook part type of ${part}` }).fill(words);
      await page.getByRole("listbox", { name: `Handbook part type of ${part} matches` }).getByRole("option").first().click();
    }
    for (const part of ["Airframe kit, carbon arms", "Propeller 10x4.5"]) {
      await pane.getByRole("checkbox", { name: `${part} is not electronic: leave it out` }).check();
    }
    await pane.getByLabel("Your own failure rate for Battery pack 6S 10 Ah, per million hours").fill("5");
    await pane.getByLabel("Mission time (hours)").fill("100");
    await expect(pane.getByRole("status")).toContainText("chance of no failure in 100 hours");
    await pane.locator(".table-pane-title").scrollIntoViewIfNeeded();
    expect(await sideways(page)).toBeLessThanOrEqual(width);
    if (width >= 1920) {
      // Wide: the result beside the parts.
      const inBox = await pane.locator(".pred2-in").boundingBox();
      const outBox = await pane.locator(".pred2-out").boundingBox();
      expect(outBox.x).toBeGreaterThan(inBox.x + inBox.width - 2);
    }
    await shot(page, `${width}-quadcopter-prediction`);
    if (width < 600) {
      await pane.getByRole("region", { name: "The prediction" }).scrollIntoViewIfNeeded();
      await shot(page, `${width}-quadcopter-prediction-result`);
    }
    if (width < 600) {
      await pane.getByRole("button", { name: "Back to the table" }).click();
    } else {
      await expect(row(page, quad.id)).toBeVisible();
      await page.keyboard.press("Escape");
      await expect(row(page, quad.id)).toHaveAttribute("aria-selected", "true");
    }
    await expect(pane).toHaveCount(0);
    await expect(page).not.toHaveURL(/[?&]predict=/);
  }
  await expectHealthy(page, problems, { label: "a product's prediction pane" });
});

// A long diagram built from the tree (the Survey quadcopter's Propulsion: twelve like blocks in
// series) opens with every block in view, and its "like blocks in series" hints are one line on
// the Calculator that opens to the list, under the answer.
test("a built RBD opens whole, and its like-blocks hints fold into one line", async ({ page, request, problems }) => {
  const { products } = await (await request.get(`${M}/products`)).json();
  const quad = products.find((p) => /^Survey quadcopter/.test(p.name));
  expect(quad, "the seeded Survey quadcopter").toBeTruthy();
  const { positions } = await (await request.get(`${M}/tree`)).json();
  const prop = positions.find((p) => p.name === "Propulsion" && p.parent_id === quad.id);
  expect(prop, "the Survey quadcopter's Propulsion").toBeTruthy();
  const built = await postOk(request, `${M}/positions/${prop.id}/models`, { build_rbd: true });
  for (const [width, height] of [[1440, 900], [400, 860]]) {
    await page.setViewportSize({ width, height });
    await open(page, `/products/${quad.id}?view=models&sel=${prop.id}&rbd=${built.model_id}&on=${prop.id}`);
    const pane = rbdPane(page);
    await expect(pane.locator(".react-flow__node").first()).toBeVisible();
    await expect.poll(async () => { const b = await blocksInView(pane); return b.all > 10 && b.inside === b.all; }).toBe(true);
    await pane.getByRole("tab", { name: "Calculator" }).click();
    await pane.getByRole("button", { name: "Calculate" }).click();
    const fold = pane.locator("details.rbd-check-fold:visible").first();
    await expect(fold.locator("summary")).toHaveText("⚠ 3 groups of like blocks are in series: check whether any are redundant");
    await expect(fold.locator("li").first()).toBeHidden();
    await fold.locator("summary").click();
    await expect(fold.locator("li")).toHaveCount(3);
    await expect(fold.locator("li").filter({ hasText: "“Motor 1”, “Motor 2”, “Motor 3” and “Motor 4”" })).toHaveCount(1);
    expect(await sideways(page)).toBeLessThanOrEqual(width);
  }
  await expectHealthy(page, problems, { label: "a built RBD's hints" });
});

// A product's Modelling tab: Build from what's inside… opens the builder in the table area too.
test("a product's Modelling tab: Build from what's inside… opens the RBD builder in the table area", async ({ page, request, problems }) => {
  const tag = `rp${Date.now()}`;
  const product = await postOk(request, `${M}/products`, { name: `RBD drone ${tag}`, part_number: `RD-${tag}` });
  const motor = await postOk(request, `${M}/positions`, { name: `Drone motor ${tag}`, parent_id: product.id });
  await postOk(request, `${M}/positions`, { name: `Drone battery ${tag}`, parent_id: product.id });
  await postOk(request, `${M}/positions/${motor.id}/models`, { model_id: "sample-model-bearings-weibull" });
  let first = null;
  for (const [width, height] of [[1440, 900], [400, 860]]) {
    await page.setViewportSize({ width, height });
    await open(page, `/products/${product.id}?view=models&sel=${product.id}`);
    if (width < 600) {
      // Built at the first width: the menu now opens that diagram rather than building another.
      await row(page, product.id).locator(".tp-nm").click({ button: "right" });
      await page.getByRole("menuitem", { name: "RBD", exact: true }).click();
      await expect(page.getByRole("group", { name: "RBD" }).getByRole("menuitem", { name: "Build from what's inside…", exact: true })).toHaveCount(0);
      await page.getByRole("group", { name: "RBD" }).getByRole("menuitem", { name: "Open the RBD" }).click();
    } else {
      await headPick(page, "RBD", "Build from what's inside…");
    }
    const pane = rbdPane(page);
    await expect(pane.locator(".react-flow__node").filter({ hasText: `Drone battery ${tag}` })).toBeVisible();
    if (first) expect(rbdOf(page)).toBe(first);
    first = rbdOf(page);
    await expect.poll(() => blocksInView(pane)).toEqual({ all: 4, inside: 4 });
    await expect(page.getByRole("dialog")).toHaveCount(0);
    // The heading row shows on a phone (for ‹ Back); on a wide screen it is for screen readers only.
    await expect(pane.locator(width < 600 ? ".table-pane-title" : "h2.sr-only")).toContainText(`RBD drone ${tag}`);
    await expect(page).toHaveURL(new RegExp(`/products/${product.id}\\?.*view=models.*rbd=[\\w-]+&on=${product.id}`));
    expect(await sideways(page)).toBeLessThanOrEqual(width);
    await shot(page, `${width}-product-rbd`);
    if (width < 600) {
      await pane.getByRole("button", { name: "Back to the table" }).click();
    } else {
      await page.keyboard.press("Escape");
      await expect(row(page, product.id)).toHaveAttribute("aria-selected", "true");
    }
    await expect(pane).toHaveCount(0);
    await expect(page).not.toHaveURL(/[?&](rbd|on)=/);
  }
  await expectHealthy(page, problems, { label: "a product's RBD pane" });
});
