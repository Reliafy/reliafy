// RBDs: every tab of every sample diagram, a calculation, and the importers
// (BlockSim, Open-PSA, Galileo, Excel) through the RBDs page's Import button.
import { existsSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { test, expect, open, expectHealthy } from "./health.js";

const fixture = (name) => fileURLToPath(new URL(`fixtures/${name}`, import.meta.url));

test("every tab of every sample RBD", async ({ page, request, problems }) => {
  const { rbds } = await (await request.get("/api/rbds")).json();
  const samples = rbds.filter((r) => r.is_sample);
  expect(samples.length).toBeGreaterThan(0);
  for (const rbd of samples) {
    await open(page, `/systems/b/${rbd.id}`);
    const tablist = page.getByRole("tablist", { name: "Diagram views" });
    const names = await tablist.getByRole("tab").allInnerTexts();
    expect(names.length, `${rbd.id}: no tabs`).toBeGreaterThan(1);
    for (const name of names) {
      await test.step(`${rbd.id} › ${name}`, async () => {
        const tab = tablist.getByRole("tab", { name, exact: true });
        await tab.click();
        await expect(tab).toHaveAttribute("aria-selected", "true");
        await page.waitForLoadState("networkidle", { timeout: 10_000 }).catch(() => {});
        await expectHealthy(page, problems, { label: `${rbd.id} › ${name}` });
      });
    }
  }
});

test("calculate a sample RBD", async ({ page, problems }) => {
  await open(page, "/systems/b/sample-rbd-pump-station");
  await page.getByRole("tab", { name: "Calculator" }).click();
  await page.locator('[data-wt="rbd-calculate"]').click();
  const panel = page.locator(".rbd-calc-panel").first();
  await expect(panel.getByText("Minimal cut sets")).toBeVisible({ timeout: 30_000 });
  await expect(panel.getByText(/MTTF/).first()).toBeVisible();
  await expectHealthy(page, problems, { label: "calculated RBD", chart: true });
});

// The BlockSim examples are ReliaSoft's copyright, so they aren't in the
// repository: backend/scripts/fetch_rbd_import_fixtures.py downloads them.
const BLOCKSIM_DIR = fileURLToPath(new URL("../../backend/tests/fixtures/external/blocksim/", import.meta.url));
const blocksim = () => {
  const files = existsSync(BLOCKSIM_DIR) ? readdirSync(BLOCKSIM_DIR).filter((f) => /\.(rsgz|rsr)\d+$|\.rsrp$/.test(f)) : [];
  const file = files.includes("blocksim_example1_V20.rsgz20") ? "blocksim_example1_V20.rsgz20" : files[0];
  return file && BLOCKSIM_DIR + file;
};

const IMPORTS = [
  { format: "Galileo", file: () => fixture("pump-train.dft"), blocks: 4 },
  { format: "Open-PSA", file: () => fixture("cooling.xml"), blocks: 5 },
  { format: "Excel", file: null, blocks: 2 }, // the template the app offers
  { format: "BlockSim", file: blocksim, blocks: 2 },
];

for (const { format, file, blocks } of IMPORTS) {
  test(`import an RBD from ${format}`, async ({ page, request, problems }) => {
    let upload;
    if (file) {
      upload = file();
      test.skip(!upload, "No BlockSim example here: run backend/scripts/fetch_rbd_import_fixtures.py");
    } else {
      const res = await request.get("/api/rbds/import/template.xlsx");
      expect(res.ok()).toBeTruthy();
      upload = { name: "reliafy-rbd-template.xlsx", mimeType: "application/octet-stream", buffer: await res.body() };
    }
    await open(page, "/systems/rbds");
    await page.locator('input[type="file"]').setInputFiles(upload);
    await page.waitForURL(/\/systems\/b$/, { timeout: 30_000 });
    await expect(page.locator(".react-flow__node").nth(blocks - 1)).toBeVisible();
    await expectHealthy(page, problems, { label: `${format} import` });
  });
}

// Full screen: the toolbar and canvas cover the screen, and every dialog,
// list and menu opened there shows inside it (they render in a portal, which
// would otherwise be hidden behind the full-screen part).
const inFull = (page, selector) =>
  page.evaluate((sel) => {
    const full = document.querySelector(".rbd-builder.is-full");
    const el = document.querySelector(sel);
    return !!(full && el && full.contains(el));
  }, selector);
const nativeFull = (page) => page.evaluate(() => document.fullscreenElement?.classList.contains("rbd-builder") ?? false);
const noFullscreenApi = () => {
  for (const k of ["requestFullscreen", "webkitRequestFullscreen"]) {
    delete Element.prototype[k];
    delete HTMLElement.prototype[k];
  }
  for (const k of ["exitFullscreen", "webkitExitFullscreen"]) delete Document.prototype[k];
};
const addComponent = async (page) => {
  await page.getByRole("button", { name: "Add block" }).click();
  await page.locator(".ovm-item", { hasText: /^Component$/ }).click();
};

test("full screen: edit, open dialogs and save without leaving it", async ({ page, problems }) => {
  await open(page, "/systems/b");
  const nodes = page.locator(".react-flow__node");
  const before = await nodes.count();
  await addComponent(page); // made before entering: still there after
  await expect(nodes).toHaveCount(before + 1);

  // Full screen is in the toolbar, its icon with the words as its name.
  const toggle = page.locator(".rbd-toolbar").getByRole("button", { name: "Full screen", exact: true });
  await expect(toggle).toHaveAttribute("title", "Full screen (F)");
  await toggle.click();
  await expect.poll(() => nativeFull(page)).toBe(true);
  await expect(page.getByRole("button", { name: "Exit full screen" })).toBeVisible();
  await expect(page.locator(".rbd-save-status")).toContainText("Not saved yet");
  const box = await page.locator(".rbd-builder").boundingBox();
  expect(box.width).toBe(1280);
  expect(box.height).toBe(900);

  // Add a block and open its dialog, with a dropdown in it, inside full screen.
  await addComponent(page);
  await expect(nodes).toHaveCount(before + 2);
  await nodes.filter({ hasText: "Component 2" }).dblclick();
  await expect(page.getByRole("dialog")).toBeVisible();
  expect(await inFull(page, ".overlay")).toBe(true);
  await page.getByRole("dialog").getByRole("combobox").first().click();
  await expect(page.getByRole("listbox")).toBeVisible();
  expect(await inFull(page, ".sel-menu")).toBe(true);
  await page.keyboard.press("Escape");
  await expect(page.getByRole("listbox")).toHaveCount(0);
  await page.getByRole("dialog").getByRole("button", { name: "Cancel" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);

  // The diagram's settings, a popover off the toolbar, open inside full screen.
  await page.getByRole("button", { name: /^Diagram settings/ }).click();
  const settings = page.getByRole("dialog", { name: "Diagram settings" });
  await expect(settings).toBeVisible();
  expect(await inFull(page, ".rbd-settings-pop")).toBe(true);
  await settings.getByRole("radio", { name: /Non-repairable/ }).click();
  await page.keyboard.press("Escape");
  await expect(settings).toBeHidden();

  // Save: the name dialog shows, and the first save keeps full screen and the canvas.
  // Not saved yet: one Save… button; once saved, autosave keeps each change.
  await page.getByRole("button", { name: "Save…", exact: true }).click(); // the first save asks for a name
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  expect(await inFull(page, ".overlay")).toBe(true);
  await dialog.locator("input").first().fill("Full screen smoke");
  await dialog.locator("input").first().press("Enter");
  await page.waitForURL(/\/systems\/b\/[\w-]+$/);
  await expect(page.locator(".rbd-save-status")).toContainText("Saved");
  await expect.poll(() => nativeFull(page)).toBe(true);
  await expect(nodes).toHaveCount(before + 2);
  await page.locator(".react-flow__pane").click({ position: { x: 40, y: 40 } });
  await addComponent(page);
  await expect(page.locator(".rbd-save-status")).toContainText("Saved", { timeout: 10_000 });
  await expect(page.getByRole("button", { name: /^Save/ })).toHaveCount(0); // autosave: no Save button

  // Out again: the browser's full screen ends, focus is back on the button,
  // and every block is still there.
  await page.getByRole("button", { name: "Exit full screen" }).click();
  await expect.poll(() => nativeFull(page)).toBe(false);
  await expect(page.locator(".rbd-builder.is-full")).toHaveCount(0);
  await expect(toggle).toBeFocused();
  await expect(nodes).toHaveCount(before + 3);
  await expect(page.locator(".portal-host")).toHaveCount(1);
  expect(await page.evaluate(() => document.querySelector(".portal-host").parentElement === document.body)).toBe(true);
  // F goes in and out too (the browser's own exit is picked up the same way).
  await page.locator(".react-flow__pane").click({ position: { x: 40, y: 40 } });
  await page.keyboard.press("f");
  await expect.poll(() => nativeFull(page)).toBe(true);
  await page.evaluate(() => document.exitFullscreen());
  await expect(page.locator(".rbd-builder.is-full")).toHaveCount(0);
  await expectHealthy(page, problems, { label: "full screen" });
});

// Autosave: a saved diagram keeps each change by itself; Undo and Redo step back and forward
// (and the step back is saved too). Off (⋯ › Autosave), Save is back and leaving asks first.
test("autosave keeps each change, Undo takes it back, and off it asks before leaving", async ({ page, request, problems }) => {
  await open(page, "/systems/b");
  const nodes = page.locator(".react-flow__node");
  const status = page.locator(".rbd-save-status");
  await addComponent(page);
  await expect(status).toContainText("Not saved yet");
  await page.getByRole("button", { name: "Save…", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await dialog.locator("input").first().fill(`Autosave smoke ${Date.now()}`);
  await dialog.locator("input").first().press("Enter");
  await page.waitForURL(/\/systems\/b\/[\w-]+$/);
  const id = page.url().split("/").pop();
  const blocksSaved = async () => ((await (await request.get(`/api/rbds/${id}`)).json()).graph.nodes || []).length;
  const opened = await blocksSaved();
  await expect(status).toContainText("Saved");

  // A change saves itself.
  await page.locator(".react-flow__pane").click({ position: { x: 40, y: 40 } });
  await addComponent(page);
  await expect.poll(blocksSaved, { timeout: 10_000 }).toBe(opened + 1);
  await expect(status).toContainText("Saved");

  // Undo (Ctrl+Z) takes it back, and that is saved too; Redo puts it back.
  await page.locator(".react-flow__pane").click({ position: { x: 40, y: 40 } });
  await page.keyboard.press("ControlOrMeta+z");
  await expect(nodes).toHaveCount(opened);
  await expect.poll(blocksSaved, { timeout: 10_000 }).toBe(opened);
  await page.getByRole("button", { name: "Redo" }).click();
  await expect(nodes).toHaveCount(opened + 1);
  await expect.poll(blocksSaved, { timeout: 10_000 }).toBe(opened + 1);

  // Off: Save is back, the status says what's unsaved, and a link away asks first.
  await page.getByRole("button", { name: "More", exact: true }).click();
  await page.getByRole("menuitemcheckbox", { name: /Autosave/ }).click();
  try {
    await addComponent(page);
    await expect(status).toContainText("Unsaved changes");
    await page.waitForTimeout(2000);
    expect(await blocksSaved()).toBe(opened + 1); // not saved by itself
    await page.getByRole("link", { name: "Home" }).first().click();
    const ask = page.getByRole("alertdialog").or(page.getByRole("dialog")).filter({ hasText: "Leave without saving?" });
    await expect(ask).toBeVisible();
    await ask.getByRole("button", { name: "Stay" }).click();
    await expect(page).toHaveURL(new RegExp(`/systems/b/${id}$`));
    await page.getByRole("button", { name: "Save", exact: true }).click();
    await expect(status).toContainText("Saved");
    expect(await blocksSaved()).toBe(opened + 2);
  } finally {
    // The preference is the account's: put it back for the other tests.
    await request.put("/api/me/editor-preferences", { data: { autosave: true } });
  }
  await expectHealthy(page, problems, { label: "autosave and undo" });
});

test("full screen without the browser's Fullscreen API (iPhone): covers the page", async ({ page, problems }) => {
  await page.addInitScript(noFullscreenApi);
  await open(page, "/systems/b/sample-rbd-pump-station");
  const nodes = page.locator(".react-flow__node");
  await expect(nodes.first()).toBeVisible();
  const count = await nodes.count();
  await page.locator(".react-flow__pane").click({ position: { x: 40, y: 40 } });
  await page.keyboard.press("F");
  const builder = page.locator(".rbd-builder.is-full");
  await expect(builder).toBeVisible();
  expect(await nativeFull(page)).toBe(false);
  await expect(page.locator("html.full-screen-lock")).toHaveCount(1);
  const box = await builder.boundingBox();
  expect([box.x, box.y, box.width, box.height]).toEqual([0, 0, 1280, 900]);
  await expect(page.locator(".rbd-save-status")).toContainText("Read only");

  // Escape closes the dialog first, then leaves full screen.
  await addComponent(page);
  await expect(nodes).toHaveCount(count + 1);
  await nodes.filter({ hasText: "Component" }).last().dblclick();
  await expect(page.getByRole("dialog")).toBeVisible();
  expect(await inFull(page, ".overlay")).toBe(true);
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(builder).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.locator(".rbd-builder.is-full")).toHaveCount(0);
  await expect(page.locator("html.full-screen-lock")).toHaveCount(0);
  await expect(nodes).toHaveCount(count + 1);
  // ...and the button.
  await page.getByRole("button", { name: "Full screen", exact: true }).click();
  await expect(builder).toBeVisible();
  await page.getByRole("button", { name: "Exit full screen" }).click();
  await expect(page.locator(".rbd-builder.is-full")).toHaveCount(0);
  await expectHealthy(page, problems, { label: "full screen fallback" });
});

test("full screen on a phone (400 px): no sideways scroll, big enough to tap", async ({ page, problems }) => {
  await page.setViewportSize({ width: 400, height: 860 });
  await page.addInitScript(noFullscreenApi);
  await open(page, "/systems/b/sample-rbd-pump-station");
  await expect(page.locator(".react-flow__node").first()).toBeVisible();
  const enter = page.getByRole("button", { name: "Full screen", exact: true });
  expect((await enter.boundingBox()).height).toBeGreaterThanOrEqual(40);
  await enter.click();
  await expect(page.locator(".rbd-builder.is-full")).toBeVisible();
  const exit = page.getByRole("button", { name: "Exit full screen" });
  await expect(exit).toBeVisible();
  const size = await exit.boundingBox();
  expect(size.height).toBeGreaterThanOrEqual(40);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(400);
  await addComponent(page);
  await page.locator(".react-flow__node").filter({ hasText: "Component" }).last().dblclick();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.getByRole("dialog").getByRole("button", { name: "Cancel" }).click();
  await exit.click();
  await expect(page.locator(".rbd-builder.is-full")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Full screen", exact: true })).toBeFocused();
  await expectHealthy(page, problems, { label: "full screen at 400 px" });
});

// A mistyped or old diagram link says so, rather than opening a blank builder
// that looks like a lost diagram.
test("an unknown diagram id says it isn't there", async ({ page }) => {
  await open(page, "/systems/b/no-such-diagram");
  await expect(page.getByRole("heading", { name: "Diagram not found" })).toBeVisible();
  await expect(page.getByRole("link", { name: "See your RBDs" })).toBeVisible();
});

// On a phone a sample diagram fits the canvas on load: no block starts off
// either edge.
test("a sample diagram fits a phone's canvas", async ({ page }) => {
  await page.setViewportSize({ width: 400, height: 860 });
  await open(page, "/systems/b/sample-rbd-instrument-air-design");
  const pane = page.locator(".react-flow").first();
  await expect(page.locator(".react-flow__node").first()).toBeVisible();
  await page.waitForTimeout(800); // the fit animates (300 ms)
  const box = await pane.boundingBox();
  const nodes = await page.locator(".react-flow__node").evaluateAll((els) => els.map((e) => {
    const r = e.getBoundingClientRect();
    return [r.left, r.right];
  }));
  expect(nodes.length).toBeGreaterThan(3);
  for (const [l, r] of nodes) {
    expect(l).toBeGreaterThanOrEqual(box.x - 2);
    expect(r).toBeLessThanOrEqual(box.x + box.width + 2);
  }
});

// A new diagram built from the Add block menu alone is connected: the first
// block goes between Input and Output, "add after" keeps Output ahead of the
// chain, and "add alongside" merges the pair through a junction into Output.
test("a new diagram built with Add block is connected from Input to Output", async ({ page, problems }) => {
  await open(page, "/systems/b");
  const nodes = page.locator(".react-flow__node");
  const menuItem = async (name) => {
    await page.getByRole("button", { name: "Add block" }).click();
    await page.locator(".ovm-item", { hasText: name }).click();
  };
  await menuItem(/^Component$/);
  await expect(nodes.filter({ hasText: "Component 1" })).toHaveCount(1);
  await expect(page.locator(".react-flow__edge")).toHaveCount(2);
  await menuItem("Add after (in series)");
  await expect(nodes.filter({ hasText: "Component 2" })).toHaveCount(1);
  await menuItem("Add alongside (in parallel)");
  await expect(nodes.filter({ hasText: "Component 3" })).toHaveCount(1);
  await expect(page.locator(".react-flow__node-knode")).toHaveCount(1);

  // Output stays to the right of every block.
  const right = await nodes.evaluateAll((els) => els.map((e) => ({
    out: e.classList.contains("react-flow__node-output"), x: e.getBoundingClientRect().left,
    r: e.getBoundingClientRect().right,
  })));
  const out = right.find((n) => n.out);
  for (const n of right.filter((x) => !x.out)) expect(n.r).toBeLessThanOrEqual(out.x + 1);

  // The check runs by itself: the blocks have no models yet, but nothing is left unconnected.
  const status = page.locator(".rbd-valid-menu .rbd-valid-toggle");
  await expect(status).toContainText(/Valid|problem|warning/, { timeout: 15_000 });
  await expect(status).not.toContainText("Nothing to check");
  await status.click();
  const check = page.locator(".rbd-check").first();
  await expect(check).toBeVisible();
  await expect(check).not.toContainText(/Not connected|Nothing feeds into|don't lead anywhere|not on any path/);
  await expectHealthy(page, problems, { label: "new diagram built with Add block" });
});

// The Maintenance plan (a repairable diagram): one table under the canvas, edited in place. A
// replacement in running time converts through the block's Runs (blank: all the time); at phone
// width the table scrolls inside its card, never the page.
test("the maintenance plan edits planned work and duty in place", async ({ page, problems }) => {
  await open(page, "/systems/b");
  await page.getByRole("button", { name: "Add block" }).click();
  await page.locator(".ovm-item", { hasText: /^Component$/ }).click();
  await page.getByRole("button", { name: /^Diagram settings/ }).click();
  const settings = page.getByRole("dialog", { name: "Diagram settings" });
  await settings.getByRole("radio", { name: /^Repairable/ }).click();
  await settings.getByLabel("Time unit").fill("Hours");
  await settings.getByRole("switch", { name: "Show the maintenance plan" }).click();
  await page.keyboard.press("Escape");
  const plan = page.getByRole("region", { name: "Maintenance plan" });
  await expect(plan).toBeVisible();
  await plan.getByLabel("Component 1: task").selectOption("age");
  await plan.getByLabel("Component 1: counted in").selectOption("operating");
  await plan.getByLabel("Component 1: every").fill("500");
  // Runs blank is "all the time" since #829: running time is calendar time, nothing to fix.
  await expect(plan.locator(".rbd-plan-problem")).toHaveCount(0);
  await plan.getByLabel("Component 1: runs, % of the time").fill("25");
  await expect(plan.locator(".rbd-plan-problem")).toHaveCount(0);
  await expect(plan).toContainText("= 2,000 h on the calendar at Runs 25%");
  await expect(page.locator(".rbd-chip", { hasText: "25%" })).toBeVisible();
  // A proof test takes running hours too (#365): the unit stays with the interval.
  await plan.getByLabel("Component 1: task").selectOption("test");
  await expect(plan.getByLabel("Component 1: counted in")).toHaveValue("operating");
  await expect(plan).toContainText("= 2,000 h on the calendar at Runs 25%");
  await expect(page.locator(".rbd-chip", { hasText: "running" })).toBeVisible();
  await page.setViewportSize({ width: 400, height: 860 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(400);
  await expectHealthy(page, problems, { label: "maintenance plan" });
});

// A repairable model as a block (#367): its "Repairs and replacement" section says whether the model
// wears out, pre-fills the suggested rule and says how the long-run availability is worked out.
test("a repairable model's block: repairs and replacement", async ({ page, request, problems }) => {
  const doc = await (await request.get("/api/recurrent/models/sample-rec-compressors")).json();
  const model = {
    kind: "repairable", source: "saved", modelId: doc.id, name: doc.name, form: doc.spec?.model_id || "crow_amsaa",
    params: (doc.results.params || []).map((p) => ({ name: p.name, value: p.value })), unit: doc.results.unit,
  };
  const repair = { source: "params", distribution: "Exponential", distribution_id: "exponential",
                   params: [{ name: "failure_rate", value: 0.1 }] };
  const graph = {
    repairable: true, unit: "Hours",
    nodes: [{ id: "input", type: "input", position: { x: 0, y: 0 }, data: { label: "Input" } },
            { id: "c", type: "component", position: { x: 200, y: 0 },
              data: { label: "Compressor", model, repair, costs: { repair: 800, replace: 25000 } } },
            { id: "output", type: "output", position: { x: 400, y: 0 }, data: { label: "Output" } }],
    edges: [{ id: "a", source: "input", target: "c" }, { id: "b", source: "c", target: "output" }],
  };
  const { id } = await (await request.post("/api/rbds", { data: { name: "Smoke repairable block", graph } })).json();
  await open(page, `/systems/b/${id}`);
  await page.locator(".react-flow__node", { hasText: "Compressor" }).first().dblclick();
  const section = page.getByRole("region", { name: "Repairs and replacement" });
  await expect(section.getByText(/Replacement needed: this model's failure rate rises with age/)).toBeVisible({ timeout: 20_000 });
  await expect(section.getByText("Suggested", { exact: true })).toBeVisible();
  // Crow-AMSAA with a replacement rule is worked out exactly since RePyability 0.19, so free.
  await expect(section.getByText("Its long-run availability is worked out without simulation.")).toBeVisible();
  await expectHealthy(page, problems, { label: "repairable model block" });
  await request.delete(`/api/rbds/${id}`);
});

test("a standby block as plants run it: words, units that differ, refusal and simulate", async ({ page, request, problems }) => {
  const weibull = (alpha, beta) => ({ source: "params", distribution: "Weibull", distribution_id: "weibull",
                                      params: [{ name: "alpha", value: alpha }, { name: "beta", value: beta }] });
  const graph = {
    unit: "Hours",
    nodes: [{ id: "input", type: "input", position: { x: 0, y: 0 }, data: { label: "Input" } },
            { id: "s", type: "standby", position: { x: 200, y: 0 },
              data: { label: "Cooling pumps", model: weibull(8000, 2), k: 2, spares: 1, dormancy: 0.3, cold: false,
                      startProb: 0.95 } },
            { id: "output", type: "output", position: { x: 400, y: 0 }, data: { label: "Output" } }],
    edges: [{ id: "a", source: "input", target: "s" }, { id: "b", source: "s", target: "output" }],
  };
  const { id } = await (await request.post("/api/rbds", { data: { name: "Smoke standby as plants run it", graph } })).json();
  await open(page, `/systems/b/${id}`);
  await page.locator(".react-flow__node", { hasText: "Cooling pumps" }).first().dblclick();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText("2 running, 1 warm spare ageing at 30% while waiting; each spare starts 95% of the time.")).toBeVisible();
  // Warm Weibull spares with two running: RePyability's plain refusal and the offer.
  await expect(dialog.getByText(/warm standby with 2 units running can be worked out exactly only/)).toBeVisible({ timeout: 20_000 });
  const save = dialog.getByRole("button", { name: "Save block" });
  await expect(save).toBeDisabled();
  await dialog.getByLabel(/Simulate this block/).check();
  await expect(save).toBeEnabled();
  // Units that differ: a spare on its own model.
  await dialog.getByText("Units that differ").click();
  await expect(dialog.getByText("Running unit 1")).toBeVisible();
  // exact: "Every spare: which model" holds the words "Spare: which model" too.
  await dialog.getByRole("radiogroup", { name: "Spare: which model", exact: true })
    .getByRole("radio", { name: "Its own" }).click();
  await expect(dialog.getByText("Spare's non-repairable model")).toBeVisible();
  // Another spare: the words follow.
  await dialog.locator(".standby-settings input[type=number]").nth(1).fill("2");
  await expect(dialog.getByText("2 running, 2 warm spares ageing at 30% while waiting; each spare starts 95% of the time.")).toBeVisible();
  await save.click();
  await expect(page.locator(".react-flow__node", { hasText: "simulated" })).toBeVisible();
  await expectHealthy(page, problems, { label: "standby as plants run it" });
  await request.delete(`/api/rbds/${id}`);
});
