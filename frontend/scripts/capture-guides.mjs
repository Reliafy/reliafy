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

const wait = (ms) => new Promise((r) => setTimeout(r, ms));

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
  const repairableId = await seedRepairableRbd();
  const ccfId = await seedCcfRbd();

  const shots = [
    // Availability guide.
    { file: "availability-01-new.png", url: "/rbds/b", settle: 900 },
    { file: "availability-04-models.png", url: `/rbds/b/${repairableId}`, settle: 1400,
      async act(page) { await page.locator(".rbd-comp", { hasText: "Controller" }).dblclick().catch(() => {}); await wait(900); } },
    { file: "availability-05-wired.png", url: `/rbds/b/${repairableId}`, settle: 1400, act: arrange },
    { file: "availability-06-validate.png", url: `/rbds/b/${repairableId}`, settle: 900, act: validateAndShowPanel },
    { file: "availability-07-results.png", url: `/rbds/b/${repairableId}`, settle: 900, act: calculate },
    // Common-cause guide.
    { file: "ccf-03-grouped.png", url: `/rbds/b/${ccfId}`, settle: 1400, act: arrange },
    { file: "ccf-04-impact.png", url: `/rbds/b/${ccfId}`, settle: 900, act: calculate },
  ];

  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1280, height: 860 }, deviceScaleFactor: 2 });
  for (const s of shots) {
    await page.goto(`${BASE}${s.url}`, { waitUntil: "networkidle" });
    await wait(s.settle || 500);
    if (s.act) await s.act(page);
    await page.screenshot({ path: resolve(OUT, s.file) });
    console.log("captured", s.file);
  }
  await browser.close();

  // Clean up the fixtures we created (the local DB is shared with prod).
  for (const id of [repairableId, ccfId]) {
    await fetch(`${BASE}/api/rbds/${id}`, { method: "DELETE" }).catch(() => {});
  }
  console.log(`\nDone. ${shots.length} screenshots in ${OUT}; fixtures cleaned up.`);
  console.log("Note: shots needing multi-select / right-click menus (…-02, ccf-01/02) are best captured by hand.");
}

main().catch((e) => { console.error(e); process.exit(1); });
