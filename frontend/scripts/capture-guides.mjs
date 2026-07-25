// Guide screenshot capture harness.
//
// Produces the step screenshots referenced by content/guides/*.md into
// public/guides/img/, so guides stay in sync with the UI. Run it against a
// LOCAL, auth-disabled, seeded instance of the app (single-user mode, which
// serves the sample data): the same server used for local development.
//
//   1. Build + serve the auth-disabled app so /rbds etc. are reachable, e.g.
//      the local dev backend on :8000 that serves frontend/dist.
//   2. npm i -D playwright && npx playwright install chromium
//   3. BASE_URL=http://localhost:8000 node scripts/capture-guides.mjs
//
// The hard canvas gestures (drag-to-wire, right-click menus) are NOT scripted —
// instead each RBD guide seeds a real saved diagram through the API and the
// harness screenshots its builder and results. Add new shots to SHOTS below.

import { chromium } from "playwright";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { mkdir } from "node:fs/promises";

const BASE = process.env.BASE_URL || "http://localhost:8000";
const OUT = resolve(dirname(fileURLToPath(import.meta.url)), "../public/guides/img");

// --- Fixtures: create real saved diagrams via the API so we can screenshot
// --- them without automating the canvas. Auth-disabled mode needs no token.
async function api(path, body) {
  const res = await fetch(`${BASE}/api${path}`, {
    method: body ? "POST" : "GET",
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(`${path} → ${res.status} ${await res.text()}`);
  return res.json();
}

function comp(id, label, extra = {}) {
  return {
    id, type: "component",
    position: { x: 220 * (extra.col ?? 1), y: extra.y ?? 160 },
    data: {
      label,
      model: { source: "params", distribution: "Weibull", distribution_id: "weibull",
               params: [{ name: "alpha", value: extra.alpha ?? 900 }, { name: "beta", value: extra.beta ?? 1.4 }] },
      ...(extra.repair
        ? { repair: { source: "params", distribution: "Lognormal", distribution_id: "lognormal",
                      params: [{ name: "mu", value: 2.3 }, { name: "sigma", value: 0.4 }] } }
        : {}),
    },
  };
}

async function seedRepairableRbd() {
  const graph = {
    unit: "hours", repairable: true,
    nodes: [
      { id: "input", type: "input", position: { x: 0, y: 160 }, data: { label: "Input" } },
      comp("ctrl", "Controller", { col: 1, alpha: 2000, beta: 1.6, repair: true }),
      comp("pumpA", "Pump A", { col: 2, y: 90, repair: true }),
      comp("pumpB", "Pump B", { col: 2, y: 230, repair: true }),
      { id: "output", type: "output", position: { x: 660, y: 160 }, data: { label: "Output" } },
    ],
    edges: [
      { id: "e1", source: "input", target: "ctrl" },
      { id: "e2", source: "ctrl", target: "pumpA" }, { id: "e3", source: "ctrl", target: "pumpB" },
      { id: "e4", source: "pumpA", target: "output" }, { id: "e5", source: "pumpB", target: "output" },
    ],
  };
  const saved = await api("/rbds", { name: "Availability example", graph });
  return saved.id;
}

async function seedCcfRbd() {
  const graph = {
    unit: "hours",
    nodes: [
      { id: "input", type: "input", position: { x: 0, y: 160 }, data: { label: "Input" } },
      comp("pA", "Pump A", { col: 1, y: 90 }), comp("pB", "Pump B", { col: 1, y: 230 }),
      { id: "output", type: "output", position: { x: 440, y: 160 }, data: { label: "Output" } },
    ],
    edges: [
      { id: "e1", source: "input", target: "pA" }, { id: "e2", source: "input", target: "pB" },
      { id: "e3", source: "pA", target: "output" }, { id: "e4", source: "pB", target: "output" },
    ],
    ccf_groups: [{ id: "g1", members: ["pA", "pB"], beta: 0.1 }],
  };
  const saved = await api("/rbds", { name: "Common-cause example", graph });
  return saved.id;
}

// Same two-pump diagram but with NO common-cause group yet — for the "select"
// and "set β" steps that show the before state.
async function seedCcfUngroupedRbd() {
  const graph = {
    unit: "hours",
    nodes: [
      { id: "input", type: "input", position: { x: 0, y: 160 }, data: { label: "Input" } },
      comp("pA", "Pump A", { col: 1, y: 90 }), comp("pB", "Pump B", { col: 1, y: 230 }),
      { id: "output", type: "output", position: { x: 440, y: 160 }, data: { label: "Output" } },
    ],
    edges: [
      { id: "e1", source: "input", target: "pA" }, { id: "e2", source: "input", target: "pB" },
      { id: "e3", source: "pA", target: "output" }, { id: "e4", source: "pB", target: "output" },
    ],
  };
  return (await api("/rbds", { name: "Common-cause example (ungrouped)", graph })).id;
}

// Load-sharing needs a fitted AFT (load-life) model, so build one for real:
// upload failure times gathered at three loads, fit weibull_aft with load as
// the covariate, then reference it from a load-sharing node.
async function seedLoadSharingRbd() {
  let csv = "life,load\n";
  for (const L of [1, 2, 4]) {
    // Deterministic pseudo-sample around an inverse-power life ~ 1000·L^-1.5.
    const scale = 1000 * Math.pow(L, -1.5);
    for (let k = 1; k <= 25; k++) {
      const q = k / 26; // quantiles of a Weibull(scale, 2)
      csv += `${(scale * Math.pow(-Math.log(1 - q), 1 / 2)).toFixed(2)},${L}\n`;
    }
  }
  const form = new FormData();
  form.append("file", new Blob([csv], { type: "text/csv" }), "load-life.csv");
  form.append("name", "Pump load-life (guide fixture)");
  const ds = await (await fetch(`${BASE}/api/datasets`, { method: "POST", body: form })).json();

  const mf = new FormData();
  mf.append("name", "Pump load-life (guide fixture)");
  mf.append("distribution", "weibull_aft"); // AFT: load as the covariate
  mf.append("dataset_id", ds.id);
  mf.append("x", "life");
  mf.append("formula", "load");
  mf.append("unit", "hours");
  const mres = await fetch(`${BASE}/api/models`, { method: "POST", body: mf });
  if (!mres.ok) throw new Error(`save model → ${mres.status} ${await mres.text()}`);
  const model = await mres.json();

  const graph = {
    unit: "hours",
    nodes: [
      { id: "input", type: "input", position: { x: 0, y: 160 }, data: { label: "Input" } },
      { id: "ls", type: "loadshare", position: { x: 240, y: 160 },
        data: { kind: "loadshare", label: "Pump bank", model: { source: "saved", modelId: model.id },
                load: 3, units: 3, k: 1 } },
      { id: "output", type: "output", position: { x: 520, y: 160 }, data: { label: "Output" } },
    ],
    edges: [
      { id: "e1", source: "input", target: "ls" },
      { id: "e2", source: "ls", target: "output" },
    ],
  };
  const rbd = await (await fetch(`${BASE}/api/rbds`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: "Load-sharing example", graph }),
  })).json();
  return { rbdId: rbd.id, modelId: model.id, datasetId: ds.id };
}

const wait = (ms) => new Promise((r) => setTimeout(r, ms));

// Select the two pump blocks (click + shift-click) so the group button appears.
async function selectPumps(page) {
  await page.locator(".rbd-comp", { hasText: "Pump A" }).click().catch(() => {});
  await page.locator(".rbd-comp", { hasText: "Pump B" }).click({ modifiers: ["Shift"] }).catch(() => {});
  await wait(600);
}

// Tidy the diagram: click Auto-arrange and let the layout settle.
async function arrange(page) {
  await page.getByRole("button", { name: /Auto-arrange/i }).click().catch(() => {});
  await wait(1200);
}
// Validate on the Builder tab (Calculate is gated on it), then show the panel.
async function validateAndShowPanel(page) {
  await page.getByRole("button", { name: /^Validate$/i }).click().catch(() => {});
  await wait(2200);
  await page.getByRole("button", { name: /^Calculator$/i }).click().catch(() => {});
  await wait(700);
}
// Full run: validate, open Calculator, Calculate, wait for the results to render
// (availability Monte-Carlo can take several seconds).
async function calculate(page) {
  await validateAndShowPanel(page);
  await page.getByRole("button", { name: /^Calculate$/i }).click().catch(() => {});
  await page.waitForSelector(".rbd-avail, .calc .params, .rbd-ccf-impact", { timeout: 40000 }).catch(() => {});
  await wait(1200);
}

async function main() {
  await mkdir(OUT, { recursive: true });
  // ONLY=loadshare (etc.) re-captures just the shots whose filename starts with
  // that prefix — much faster than a full run when iterating on one guide.
  const only = process.env.ONLY || "";

  // Guides that document existing flows are shot against the seeded sample
  // data, so they need no fixtures of their own.
  const S = {
    bearings: "sample-model-bearings-weibull",
    pumps: "sample-model-pumps-weibull",
    seal: "sample-ds-seal-alt",
    events: "sample-ds-compressor-events",
    wear: "sample-ds-brake-wear",
    altModel: "sample-alt-fluid",
    recurrent: "sample-rec-compressors",
    degradation: "sample-deg-brake-wear",
  };

  // Shots that only need the app's own seeded sample data. These run FIRST,
  // before any fixture exists — otherwise a fixture model/diagram shows up in
  // list pages like Saved models, which real users would never see.
  const sampleShots = [
    // --- Fit your first model ---
    { file: "fit-01-new.png", url: "/modelling/new?mode=data", settle: 1200 },
    { file: "fit-02-result.png", url: `/modelling/m/${S.bearings}`, settle: 2500 },
    { file: "fit-03-calculator.png", url: `/modelling/m/${S.bearings}`, settle: 2000,
      async act(page) { await page.getByRole("button", { name: /^Calculator$/i }).first().click().catch(() => {}); await wait(1800); } },
    // --- Censored data (the pump model is right-censored) ---
    { file: "censored-01-model.png", url: `/modelling/m/${S.pumps}`, settle: 2500 },
    // --- Accelerated life ---
    { file: "alt-01-new.png", url: "/modelling/alt/new", settle: 1200 },
    { file: "alt-02-lifestress.png", url: `/modelling/alt/${S.altModel}`, settle: 2500 },
    { file: "alt-03-probplot.png", url: `/modelling/alt/${S.altModel}`, settle: 1800,
      async act(page) { await page.getByRole("button", { name: /Probability plot/i }).click().catch(() => {}); await wait(1800); } },
    { file: "alt-04-uselevel.png", url: `/modelling/alt/${S.altModel}`, settle: 1800,
      async act(page) { await page.getByRole("button", { name: /Use-level calculator/i }).click().catch(() => {}); await wait(1200);
                        await page.getByRole("button", { name: /Compute at use level/i }).click().catch(() => {}); await wait(3000); } },
    // --- Recurrent events ---
    { file: "recurrent-01-new.png", url: "/modelling/recurrent/new", settle: 1200 },
    { file: "recurrent-02-mcf.png", url: `/modelling/recurrent/${S.recurrent}`, settle: 2500 },
    // --- Degradation ---
    { file: "degradation-01-model.png", url: `/modelling/degradation/${S.degradation}`, settle: 2500 },
    { file: "degradation-02-tracking.png", url: "/fleet/tracking", settle: 2000 },
    // --- Optimal replacement ---
    { file: "replacement-01-inputs.png", url: "/strategy/replacement", settle: 1800 },
    // --- Reliability Agent ---
    { file: "agent-01-landing.png", url: "/agent", settle: 1800 },
    // --- Sharing / saved work ---
    { file: "share-01-models.png", url: "/modelling/models", settle: 1800 },
  ];

  // Shots needing purpose-built fixtures (created below, deleted afterwards).
  const fixtureShots = (repairableId, ccfId, ccfUngroupedId, loadshare) => [
    // --- Load-sharing ---
    { file: "loadshare-01-config.png", url: `/rbds/b/${loadshare.rbdId}`, settle: 1600,
      async act(page) { await page.locator(".rbd-loadshare").dblclick().catch(() => {}); await wait(1500); } },
    // --- Build an RBD (the seeded sample diagram) ---
    { file: "rbd-01-builder.png", url: "/rbds/b/sample-rbd-pump-station", settle: 2000, act: arrange },
    { file: "rbd-02-results.png", url: "/rbds/b/sample-rbd-pump-station", settle: 1200, act: calculate },
    // Availability guide.
    { file: "availability-01-new.png", url: "/rbds/b", settle: 900 },
    { file: "availability-02-system.png", url: `/rbds/b/${repairableId}`, settle: 1200,
      async act(page) { await page.locator(".sel-trigger", { hasText: /repairable/i }).first().click().catch(() => {}); await wait(700); } },
    { file: "availability-03-add.png", url: `/rbds/b/${repairableId}`, settle: 1200,
      async act(page) { await page.locator(".react-flow__pane").click({ button: "right", position: { x: 260, y: 180 } }).catch(() => {}); await wait(600); } },
    { file: "availability-04-models.png", url: `/rbds/b/${repairableId}`, settle: 1400,
      async act(page) { await page.locator(".rbd-comp", { hasText: "Controller" }).dblclick().catch(() => {}); await wait(900); } },
    { file: "availability-05-wired.png", url: `/rbds/b/${repairableId}`, settle: 1400, act: arrange },
    { file: "availability-06-validate.png", url: `/rbds/b/${repairableId}`, settle: 900, act: validateAndShowPanel },
    { file: "availability-07-results.png", url: `/rbds/b/${repairableId}`, settle: 900, act: calculate },
    // Common-cause guide.
    { file: "ccf-01-select.png", url: `/rbds/b/${ccfUngroupedId}`, settle: 1400,
      async act(page) { await arrange(page); await selectPumps(page); } },
    { file: "ccf-02-beta.png", url: `/rbds/b/${ccfUngroupedId}`, settle: 1400,
      async act(page) { await arrange(page); await selectPumps(page); await page.getByRole("button", { name: /Common-cause group/i }).click().catch(() => {}); await wait(900); } },
    { file: "ccf-03-grouped.png", url: `/rbds/b/${ccfId}`, settle: 1400, act: arrange },
    { file: "ccf-04-impact.png", url: `/rbds/b/${ccfId}`, settle: 900, act: calculate },
  ];

  const pick = (list) => (only ? list.filter((s) => s.file.startsWith(only)) : list);
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1280, height: 860 }, deviceScaleFactor: 2 });
  let n = 0;

  const shoot = async (list) => {
    for (const s of list) {
      await page.goto(`${BASE}${s.url}`, { waitUntil: "networkidle" });
      await wait(s.settle || 500);
      // Guard: the served bundle must be the auth-disabled build, or every shot
      // is silently a screenshot of the sign-in page. Fail loudly instead.
      if (await page.locator("text=Continue with Google").count()) {
        throw new Error(
          `Landed on the sign-in page at ${s.url}.\n` +
          "The served bundle is the production (auth-enabled) build. Rebuild with:\n" +
          "  VITE_AUTH_DISABLED=true npm run build\n" +
          "then re-run the capture."
        );
      }
      if (s.act) await s.act(page);
      await page.screenshot({ path: resolve(OUT, s.file) });
      console.log("captured", s.file);
      n += 1;
    }
  };

  // Phase 1 — sample data only, so no fixture can leak into a list page.
  await shoot(pick(sampleShots));

  // Phase 2 — create fixtures, shoot, then always remove them.
  const wanted = pick(fixtureShots("", "", "", { rbdId: "" }));
  let fx = null;
  if (wanted.length) {
    fx = {
      repairableId: await seedRepairableRbd(),
      ccfId: await seedCcfRbd(),
      ccfUngroupedId: await seedCcfUngroupedRbd(),
      loadshare: await seedLoadSharingRbd(),
    };
    try {
      await shoot(pick(fixtureShots(fx.repairableId, fx.ccfId, fx.ccfUngroupedId, fx.loadshare)));
    } finally {
      await browser.close();
      // The local DB is the production one — never leave fixtures behind.
      for (const id of [fx.repairableId, fx.ccfId, fx.ccfUngroupedId, fx.loadshare.rbdId]) {
        await fetch(`${BASE}/api/rbds/${id}`, { method: "DELETE" }).catch(() => {});
      }
      await fetch(`${BASE}/api/models/${fx.loadshare.modelId}`, { method: "DELETE" }).catch(() => {});
      await fetch(`${BASE}/api/datasets/${fx.loadshare.datasetId}`, { method: "DELETE" }).catch(() => {});
    }
  } else {
    await browser.close();
  }
  console.log(`\nDone. ${n} screenshots in ${OUT}${fx ? "; fixtures cleaned up" : ""}.`);
  console.log("Note: shots needing multi-select / right-click menus (…-02, ccf-01/02) are best captured by hand.");
}

main().catch((e) => { console.error(e); process.exit(1); });
