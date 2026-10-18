// Guide screenshot capture harness.
//
// Produces the step screenshots referenced by content/guides/*.md into
// public/guides/img/, so guides stay in sync with the UI. Run it against a
// LOCAL, auth-disabled, seeded instance of the app (single-user mode, which
// serves the sample data): the same server used for local development.
//
//   1. Build the auth-disabled bundle: VITE_AUTH_DISABLED=true npm run build
//   2. Serve it with the backend in single-user mode and the samples seeded
//      (AUTH_DISABLED=true SEED_SAMPLES=true; with no MONGODB_URI it uses an
//      in-memory database), e.g. on :8000.
//   3. npx playwright install chromium   (playwright is a devDependency)
//   4. BASE_URL=http://localhost:8000 npm run capture:guides
//
// The "Guide screenshots" workflow (.github/workflows/guide-screenshots.yml),
// run by hand on the release branch as a release step, does exactly this and
// opens a pull request into that branch when any image changed (#74).
//
// The hard canvas gestures (drag-to-wire, right-click menus) are NOT scripted —
// instead each RBD guide seeds a real saved diagram through the API and the
// harness screenshots its builder and results. Add new shots to sampleShots
// (sample data only) or fixtureShots (seeded fixtures) below. The condition-based
// risk shots fit the smoke suite's demo fleet (smoke/seed.js) as a fixture.

import { chromium } from "playwright";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { mkdir, stat } from "node:fs/promises";
import { jointFleet } from "../smoke/seed.js";

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

// The safety function starter (src/rbdSafetyStarter.js) with a second shutdown
// valve alongside the first, voting 1oo2 through a junction, the two valves in
// a common-cause group of their own (verify-a-safety-function guide).
async function seedTwoValveSif() {
  const EDGE = { type: "smoothstep", markerEnd: { type: "arrowclosed", width: 18, height: 18 } };
  const el = (id, label, rate, x, y) => ({
    id, type: "component", position: { x, y }, sourcePosition: "right", targetPosition: "left",
    data: { label, instant_repair: true, inspection: { interval: 8760 },
            model: { source: "params", distribution: "Exponential", distribution_id: "exponential",
                     params: [{ name: "failure_rate", value: rate }] } },
  });
  const nodes = [
    { id: "input", type: "input", data: { label: "Input" }, position: { x: 0, y: 0 } },
    el("c1", "Pressure transmitter A", 3e-7, 240, -90),
    el("c2", "Pressure transmitter B", 3e-7, 240, 90),
    el("c3", "Logic solver", 1e-8, 520, 0),
    el("c4", "Shutdown valve", 1e-6, 800, -90),
    el("c5", "Shutdown valve B", 1e-6, 800, 90),
    { id: "k6", type: "knode", data: { n: 1, k: 2 }, position: { x: 1040, y: 0 } },
    { id: "output", type: "output", data: { label: "Output" }, position: { x: 1200, y: 0 } },
  ];
  const links = [["input", "c1"], ["input", "c2"], ["c1", "c3"], ["c2", "c3"], ["c3", "c4"], ["c3", "c5"],
                 ["c4", "k6"], ["c5", "k6"], ["k6", "output"]];
  const graph = {
    unit: "Hours", repairable: true, safety_function: true, target_sil: 3, nodes,
    edges: links.map(([source, target]) => ({ id: `e-${source}-${target}`, source, target, ...EDGE })),
    ccf_groups: [{ id: "ccf-transmitters", members: ["c1", "c2"], beta: 0.05 },
                 { id: "ccf-valves", members: ["c4", "c5"], beta: 0.1 }],
  };
  return (await api("/rbds", { name: "Safety function — two shutdown valves", graph })).id;
}

// Condition-based risk: the smoke suite's demo fleet (40 pumps, vibration read
// every 10 days; smoke/seed.js), fitted as a joint model, and a diagram with two
// of its running pumps in parallel as condition-based blocks.
async function seedJointModel() {
  const { lifetimes, readings } = jointFleet();
  const life = await api("/datasets/paste", { name: "Pump lives", content: lifetimes });
  const reads = await api("/datasets/paste", { name: "Pump vibration", content: readings });
  const fit = await api("/joint/models", {
    name: "Feed pumps (condition-based)",
    lifetimes_dataset_id: life.id, readings_dataset_id: reads.id,
    mapping: { id: "pump", x: "age", c: "running" },
    readings_mapping: { id: "pump", age: "age", value: "vibration" },
    covariates: ["load"], path_model: "linear", unit: "Days", marker: "vibration", marker_unit: "mm/s",
  });
  const modelId = fit.model_id;
  const block = (id, unitId, y) => ({
    id, type: "component", position: { x: 240, y },
    data: { label: `Pump ${unitId}`,
            model: { source: "joint", kind: "joint", modelId, name: "Feed pumps (condition-based)",
                     distribution: "Condition-based risk", unit: "Days", joint_unit: { id: unitId } } },
  });
  const graph = {
    unit: "Days",
    nodes: [
      { id: "input", type: "input", position: { x: 0, y: 160 }, data: { label: "Input" } },
      block("pa", "P8", 80), block("pb", "P38", 240),
      comp("valve", "Header valve", { col: 2.2, alpha: 2000, beta: 1.5 }),
      { id: "output", type: "output", position: { x: 720, y: 160 }, data: { label: "Output" } },
    ],
    edges: [
      { id: "e1", source: "input", target: "pa" }, { id: "e2", source: "input", target: "pb" },
      { id: "e3", source: "pa", target: "valve" }, { id: "e4", source: "pb", target: "valve" },
      { id: "e5", source: "valve", target: "output" },
    ],
  };
  const rbd = await api("/rbds", { name: "Feed pump train", graph });
  return { modelId, rbdId: rbd.id, datasetIds: [life.id, reads.id] };
}

// A model of the user's own (samples can't be shared), for the Share dialog.
async function seedOwnModel() {
  const form = new FormData();
  form.append("name", "Pump life — Weibull");
  form.append("distribution", "weibull");
  form.append("dataset_id", "sample-ds-pumps");
  form.append("x", "months");
  form.append("c", "censored");
  form.append("unit", "Months");
  const res = await fetch(`${BASE}/api/models`, { method: "POST", body: form });
  if (!res.ok) throw new Error(`save model → ${res.status} ${await res.text()}`);
  return (await res.json()).id;
}

// --- Import a diagram, outage history, networks (guides import-a-diagram,
// --- outage-history, network-reliability) ---

// A small Galileo dynamic fault tree, written here (no vendor file): a supply
// with a cold spare, three pumps voting 2-of-3, and a valve with only a fixed
// failure probability, which imports without a life model and says so.
const GALILEO_FEED = [
  'toplevel "Feed system";',
  '"Feed system" or "Supply" "Pumps" "Valve";',
  '"Pumps" 2of3 "Pump A" "Pump B" "Pump C";',
  '"Supply" csp "Main supply" "Backup supply";',
  '"Main supply" lambda=2e-4;',
  '"Backup supply" lambda=2e-4 dorm=0;',
  '"Pump A" lambda=1e-4;',
  '"Pump B" lambda=1e-4;',
  '"Pump C" lambda=1e-4;',
  '"Valve" prob=0.001;',
  "",
].join("\n");

// A repairable pump station (controller, two redundant pumps) with a year of
// real outages logged against it.
const OUTAGE_LOG = `asset,down,back up,reason,planned
Pump A,2025-01-14 08:00,2025-01-14 19:30,seal leak,no
Controller,2025-02-03 02:10,2025-02-03 09:40,PLC card,no
Pump B,2025-03-02 06:00,2025-03-02 14:00,service,yes
Pump A,2025-03-02 10:00,2025-03-02 16:30,bearing,no
Pump B,2025-04-21 13:00,2025-04-22 01:00,impeller,no
Controller,2025-05-30 22:00,2025-05-31 03:00,power supply,no
Pump A,2025-06-18 07:00,2025-06-18 12:00,service,yes
Pump B,2025-07-09 09:00,2025-07-09 23:00,seal leak,no
Pump A,2025-08-25 05:00,2025-08-25 15:00,coupling,no
Controller,2025-09-12 11:00,2025-09-12 13:30,firmware,no
Pump B,2025-10-28 16:00,2025-10-29 02:00,bearing,no
Pump A,2025-11-30 08:00,2025-11-30 20:00,seal leak,no
`;

async function seedOutageRbd() {
  const graph = {
    unit: "Hours", repairable: true,
    nodes: [
      { id: "input", type: "input", position: { x: 0, y: 160 }, data: { label: "Input" } },
      comp("ctrl", "Controller", { col: 1, alpha: 2000, beta: 1.4, repair: true }),
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
  const rbd = await api("/rbds", { name: "Pump station", graph });
  await api(`/rbds/${rbd.id}/outage-logs`, {
    csv: OUTAGE_LOG, name: "Pump station 2025", window_start: "2025-01-01", window_end: "2026-01-01",
  });
  return rbd.id;
}

// A water main as a network: a plant and a town joined by four lines in a
// square, with a tie line across the middle (the classic bridge).
async function seedNetworkRbd() {
  const line = (id, label, x, y, alpha) => ({
    id, type: "component", position: { x, y },
    data: { label, model: { source: "params", distribution: "Weibull", distribution_id: "weibull",
                            params: [{ name: "alpha", value: alpha }, { name: "beta", value: 1.2 }] } },
  });
  const nodes = [
    { id: "input", type: "input", position: { x: 0, y: 160 }, data: { label: "Plant" } },
    line("l1", "Line 1", 220, 40, 40), line("l2", "Line 2", 220, 280, 40), line("tie", "Tie line", 420, 160, 30),
    line("l3", "Line 3", 620, 40, 40), line("l4", "Line 4", 620, 280, 40),
    { id: "output", type: "output", position: { x: 840, y: 160 }, data: { label: "Town" } },
  ];
  const links = [["input", "l1"], ["input", "l2"], ["l1", "tie"], ["l3", "tie"], ["tie", "l2"], ["tie", "l4"],
                 ["l1", "l3"], ["l2", "l4"], ["l3", "output"], ["l4", "output"]];
  const graph = {
    unit: "Years", network: { source: "input", target: "output" }, nodes,
    edges: links.map(([source, target], i) => ({ id: `n${i}`, source, target })),
  };
  return (await api("/rbds", { name: "Water main", graph })).id;
}

// --- Targets and design, phased missions, production, costs and intervals ---
// Four diagrams for the rbd-targets-and-design, phased-missions,
// production-availability and rbd-costs-and-intervals guides.
const rbdW = (alpha, beta) => ({ source: "params", distribution: "Weibull", distribution_id: "weibull",
  params: [{ name: "alpha", value: alpha }, { name: "beta", value: beta }] });
const rbdE = (mean) => ({ source: "params", distribution: "Exponential", distribution_id: "exponential",
  params: [{ name: "failure_rate", value: 1 / mean }] });
const rbdLN = (mu, sigma) => ({ source: "params", distribution: "Lognormal", distribution_id: "lognormal",
  params: [{ name: "mu", value: mu }, { name: "sigma", value: sigma }] });
const rbdBlock = (id, label, x, y, data) => ({ id, type: "component", position: { x, y }, data: { label, ...data } });
const rbdIn = { id: "input", type: "input", position: { x: 0, y: 160 }, data: { label: "Input" } };
const rbdOut = (x) => ({ id: "output", type: "output", position: { x, y: 160 }, data: { label: "Output" } });
const rbdEdges = (pairs) => pairs.map(([source, target]) => ({ id: `e-${source}-${target}`, source, target }));

async function seedDesignRbds() {
  // A cooling-water train: a controller, a pair of duty pumps, a heat exchanger.
  const train = {
    unit: "Hours",
    nodes: [rbdIn,
      rbdBlock("ctl", "Controller", 220, 160, { model: rbdW(6000, 1.2) }),
      { id: "pumps", type: "parallel", position: { x: 440, y: 160 },
        data: { label: "Cooling pumps", n: 2, model: rbdW(2000, 1.6) } },
      rbdBlock("hx", "Heat exchanger", 660, 160, { model: rbdW(9000, 2.2) }),
      rbdOut(880)],
    edges: rbdEdges([["input", "ctl"], ["ctl", "pumps"], ["pumps", "hx"], ["hx", "output"]]),
  };
  // The same train repairable, priced and maintained: the pumps wear out and
  // are replaced by age; lost production costs 2,000 an hour.
  const pump = (id, label, y) => rbdBlock(id, label, 440, y, {
    model: rbdW(2000, 2.5), repair: rbdLN(2.5, 0.5),
    costs: { repair: 800, replace: 3000, acquisition: 25000 },
    preventive: { policy: "age", interval: 1500, duration: 4, cost: 2000 },
  });
  const repairable = {
    unit: "Hours", repairable: true,
    nodes: [rbdIn,
      rbdBlock("ctl", "Controller", 220, 160, { model: rbdE(20000), repair: rbdLN(1.5, 0.6),
                                               costs: { repair: 500, replace: 2000 } }),
      pump("pa", "Pump A", 80), pump("pb", "Pump B", 240),
      rbdBlock("hx", "Heat exchanger", 660, 160, { model: rbdE(40000), repair: rbdLN(3.9, 0.5),
                                                   costs: { repair: 4000, replace: 12000, acquisition: 60000 } }),
      rbdOut(880)],
    edges: rbdEdges([["input", "ctl"], ["ctl", "pa"], ["ctl", "pb"], ["pa", "hx"], ["pb", "hx"], ["hx", "output"]]),
    costs: { downtime_rate: 2000, horizon: 87600, discount_rate: 7 },
  };
  // A flight in three phases: both hydraulic pumps to take off and land, one
  // to cruise; the landing gear isn't needed in the cruise.
  const flight = {
    unit: "Hours",
    nodes: [rbdIn,
      rbdBlock("eng", "Engine", 220, 160, { model: rbdE(4000) }),
      rbdBlock("h1", "Hydraulic pump 1", 440, 80, { model: rbdE(1500) }),
      rbdBlock("h2", "Hydraulic pump 2", 440, 240, { model: rbdE(1500) }),
      { id: "vote", type: "knode", position: { x: 640, y: 160 }, data: { label: "Hydraulics", n: 1, k: 2 } },
      rbdBlock("gear", "Landing gear", 820, 160, { model: rbdE(8000) }),
      rbdOut(1040)],
    edges: rbdEdges([["input", "eng"], ["eng", "h1"], ["eng", "h2"], ["h1", "vote"], ["h2", "vote"],
                     ["vote", "gear"], ["gear", "output"]]),
    phases: [
      { name: "Take-off", duration: 0.2, votes: { vote: 2 } },
      { name: "Cruise", duration: 6, not_needed: ["gear"] },
      { name: "Landing", duration: 0.3, votes: { vote: 2 } },
    ],
  };
  // A solar farm's export: four 250 kW inverters into a 1 MW transformer,
  // against a 900 kW demand.
  const inverter = (i, y) => rbdBlock(`inv${i}`, `Inverter ${i}`, 260, y,
    { model: rbdE(8760), repair: rbdLN(3.9, 0.6), capacity: 250 });
  const solar = {
    unit: "Hours", repairable: true,
    nodes: [rbdIn, inverter(1, 0), inverter(2, 110), inverter(3, 220), inverter(4, 330),
      rbdBlock("tx", "Transformer", 540, 165, { model: rbdE(80000), repair: rbdLN(5.8, 0.4), capacity: 1000 }),
      rbdOut(760)],
    edges: rbdEdges([["input", "inv1"], ["input", "inv2"], ["input", "inv3"], ["input", "inv4"],
      ["inv1", "tx"], ["inv2", "tx"], ["inv3", "tx"], ["inv4", "tx"], ["tx", "output"]]),
    production: { demand: 900, unit: "kW", period: 8760 },
  };
  const save = async (name, graph) => (await api("/rbds", { name, graph })).id;
  return {
    train: await save("Cooling-water train", train),
    repairable: await save("Cooling-water train (repairable)", repairable),
    flight: await save("Flight in three phases", flight),
    solar: await save("Solar farm export", solar),
  };
}

// Open a diagram tab by name.
async function rbdTab(page, name) {
  await page.locator(".rbd-tabs .tab", { hasText: new RegExp(`^${name}$`) }).click();
  await wait(800);
}
// Bring an element to the top of the view.
async function scrollTo(locator, offset = 80) {
  await locator.first().evaluate((el, off) => window.scrollBy(0, el.getBoundingClientRect().top - off), offset);
  await wait(600);
}

// RCM and teams guides: a study of the user's own (the sample is read-only, so
// its decision dialog can't open), with one mode still to decide; and a team
// with one pending invitation (single-user mode can create one: no billing).
async function seedRcmStudy() {
  const study = await api("/rcm/studies", { name: "Conveyor drive — RCM", system: "Conveyor line 2", description: "" });
  const res = await fetch(`${BASE}/api/rcm/studies/${study.id}/tree`, {
    method: "PUT", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ functions: [{ text: "Drive the belt at 4 m/s", failures: [{ text: "Belt stops", modes: [
      { text: "Gearbox bearing fatigue", effects: "Line stops until the bearing is changed; about 8 hours lost.",
        consequence: null, decision: null },
      { text: "Motor overload trip fails to operate (hidden)", effects: "Motor burns out on the next jam.",
        consequence: "hidden", decision: null },
    ] }] }] }),
  });
  if (!res.ok) throw new Error(`rcm tree → ${res.status} ${await res.text()}`);
  return study.id;
}
async function seedTeam() {
  const team = await api("/teams", { name: "Reliability team" });
  await api(`/teams/${team.id}/members`, { email: "colleague@example.com" });
  return team.id;
}

const wait = (ms) => new Promise((r) => setTimeout(r, ms));

// Click the first control named `name`, whichever role it has: tabs and
// segmented choices are radios or tabs, menu items and actions are buttons.
async function press(page, name) {
  for (const role of ["button", "tab", "radio", "link", "option"]) {
    const loc = page.getByRole(role, { name });
    if (await loc.count()) return loc.first().click();
  }
  throw new Error(`No control named ${name}`);
}

// Choose an option of a custom Select (components/Select.jsx) by its label.
async function chooseOption(page, label, option) {
  await page.getByRole("combobox", { name: label }).first().click(); await wait(300);
  await page.getByRole("option", { name: option }).first().click(); await wait(300);
}

// Open the builder's ⋯ menu and choose an item.
async function builderMenu(page, item) {
  await page.getByRole("button", { name: "More diagram settings" }).click();
  await wait(300);
  await page.getByRole("button", { name: item }).click();
}

// Select the two pump blocks (click + shift-click) so the group button appears.
async function selectPumps(page) {
  await page.locator(".rbd-comp", { hasText: "Pump A" }).click();
  await page.locator(".rbd-comp", { hasText: "Pump B" }).click({ modifiers: ["Shift"] });
  await wait(600);
}

// Tidy the diagram: ⋯ → Auto-arrange, and let the layout settle.
async function arrange(page) {
  await builderMenu(page, /^Auto-arrange$/);
  await wait(1200);
}
// Validate on the Builder tab (Calculate is gated on it). After a pass the
// button becomes the "✓ Valid" status.
async function validate(page) {
  const btn = page.getByRole("button", { name: /^Validate$/ });
  if (await btn.count()) await btn.click();
  await page.locator(".rbd-valid-toggle").waitFor({ timeout: 20000 });
}
// The check itself: validate, then open the status's panel.
async function validateAndShowCheck(page) {
  await validate(page);
  await page.locator(".rbd-valid-toggle").click();
  await wait(500);
}
// Full run: validate, open the Calculator tab, Calculate, wait for the results
// to render (a repairable diagram can take several seconds).
async function calculate(page) {
  await validate(page);
  await page.locator(".rbd-tabs .tab", { hasText: /^Calculator$/ }).click();
  await wait(500);
  await page.getByRole("button", { name: /^Calculate$/ }).click();
  await page.getByRole("button", { name: /^Recalculate$/ }).waitFor({ timeout: 60000 });
  await wait(2500);
}
// The model page's Calculator tab.
// The per-demand form (one-shot-devices guide): a relief valve, three batches
// of demands and failures, at 90% confidence.
async function fillPerDemand(page) {
  await page.getByLabel("Model name").fill("Relief valve — open on demand");
  for (let i = 0; i < 2; i++) await page.getByRole("button", { name: /Add a batch/ }).click();
  const batches = [["Site A", 120, 1], ["Site B", 80, 0], ["Proof tests 2025", 46, 1]];
  for (const [i, [label, demands, failures]] of batches.entries()) {
    await page.getByLabel(`Batch ${i + 1} name`).fill(label);
    await page.getByLabel("Demands", { exact: true }).nth(i).fill(String(demands));
    await page.getByLabel("Failures", { exact: true }).nth(i).fill(String(failures));
  }
  await page.getByLabel("Confidence (%)").fill("90");
  await wait(500);
}

async function modelCalculator(page) {
  await press(page, /^Calculator$/);
  await wait(1500);
}

// Guard: the served bundle must be the auth-disabled build, or every shot is
// silently a screenshot of the sign-in page. Fail loudly instead.
async function assertNotSignIn(page, url) {
  const signIn = (await page.locator("text=Continue with Google").count()) > 0
    || /\/login\b/.test(new URL(page.url()).pathname);
  if (signIn) {
    throw new Error(
      `Landed on the sign-in page at ${url}.\n` +
      "The served bundle is the production (auth-enabled) build. Rebuild with:\n" +
      "  VITE_AUTH_DISABLED=true npm run build\n" +
      "then re-run the capture."
    );
  }
}

async function main() {
  await mkdir(OUT, { recursive: true });
  // ONLY=loadshare (etc.) re-captures just the shots whose filename starts with
  // that prefix — much faster than a full run when iterating on one guide.
  const only = process.env.ONLY || "";

  // Refuse an auth-enabled server before taking anything.
  const config = await api("/config");
  if (config.auth) {
    throw new Error(
      `${BASE} has sign-in switched on. Serve the app with AUTH_DISABLED=true (single-user mode) ` +
      "and the VITE_AUTH_DISABLED=true build, then re-run the capture."
    );
  }

  // Guides that document existing flows are shot against the seeded sample
  // data, so they need no fixtures of their own.
  const S = {
    bearings: "sample-model-bearings-weibull",
    pumps: "sample-model-pumps-weibull",
    altModel: "sample-alt-fluid",
    recurrent: "sample-rec-compressors",
    degradation: "sample-deg-brake-wear",
    fleet: "sample-fleet-trucks",
  };

  // Shots that only need the app's own seeded sample data. These run FIRST,
  // before any fixture exists — otherwise a fixture model/diagram shows up in
  // list pages like Saved models, which real users would never see.
  const sampleShots = [
    // --- Fit your first model ---
    { file: "fit-01-new.png", url: "/modelling/new?mode=data", settle: 1200 },
    { file: "fit-02-result.png", url: `/modelling/m/${S.bearings}`, settle: 2500 },
    { file: "fit-03-calculator.png", url: `/modelling/m/${S.bearings}`, settle: 2000, act: modelCalculator },
    // --- Censored data (the pump model is right-censored) ---
    { file: "censored-01-model.png", url: `/modelling/m/${S.pumps}`, settle: 2500 },
    // --- B-lives and confidence bounds ---
    { file: "blife-01-life-card.png", url: `/modelling/m/${S.bearings}`, settle: 2500,
      async act(page) { await page.locator(".sel-trigger", { hasText: /lower bound/ }).click(); await wait(500); } },
    { file: "blife-02-calculator.png", url: `/modelling/m/${S.bearings}`, settle: 2000,
      async act(page) { await modelCalculator(page); await press(page, /^Time at reliability$/); await wait(2000); } },
    // --- Check a requirement and plan a demonstration test ---
    { file: "req-01-check.png", url: `/modelling/m/${S.bearings}`, settle: 2500,
      async act(page) {
        await page.getByRole("button", { name: /Check a requirement/ }).click(); await wait(600);
        const m = page.locator(".req-modal");
        await m.locator("input").nth(0).fill("10");
        await m.locator("input").nth(1).fill("500");
        await m.getByRole("button", { name: /^Check$/ }).click();
        await m.locator(".req-verdict").waitFor({ timeout: 20000 }); await wait(600);
      } },
    { file: "req-02-plan.png",
      url: `/strategy/test-planning?b=10&life=500&conf=90&unit=Hours&model=${S.bearings}`, settle: 2500,
      async act(page) {
        await press(page, /Lower bound 1\.88/);
        await page.getByLabel(/Test length per unit/).fill("2");
        await page.getByLabel(/true reliability|Good design's reliability/).fill("97");
        await page.getByLabel(/Producer's risk/).fill("20");
        await page.getByRole("button", { name: /^Compute$/ }).click(); await wait(3500);
        // The answer sits under the form: bring it to the top of the view.
        await page.locator(".result-summary").first().evaluate((el) => window.scrollBy(0, el.getBoundingClientRect().top - 232));
        await wait(600);
      } },
    // The Sequential test tab, on its own worked example.
    { file: "req-03-sequential.png", url: "/strategy/test-planning/sequential", settle: 1500,
      async act(page) {
        await page.getByRole("button", { name: /^Compute$/ }).click();
        await page.locator(".result-summary").first().waitFor({ timeout: 30000 }); await wait(1500);
        await page.locator(".result-summary").first().evaluate((el) => window.scrollBy(0, el.getBoundingClientRect().top - 120));
        await wait(600);
      } },
    // --- Accelerated life ---
    { file: "alt-01-new.png", url: "/modelling/alt/new", settle: 1200 },
    { file: "alt-02-lifestress.png", url: `/modelling/alt/${S.altModel}`, settle: 2500 },
    { file: "alt-03-probplot.png", url: `/modelling/alt/${S.altModel}`, settle: 1800,
      async act(page) { await press(page, /^Probability plot$/); await wait(1800); } },
    { file: "alt-04-uselevel.png", url: `/modelling/alt/${S.altModel}`, settle: 1800,
      async act(page) { await press(page, /^Use-level calculator$/); await wait(1200);
                        await page.getByRole("button", { name: /Compute at use level/i }).click().catch(() => {}); await wait(3000); } },
    // Planning the next accelerated test from the sample fit, at a use stress of 20 kV.
    { file: "alt-05-plan.png", url: `/strategy/test-planning/accelerated?model=${S.altModel}`, settle: 2000,
      async act(page) {
        await page.getByLabel("Use stress").fill("20");
        await page.getByRole("button", { name: /^Compute$/ }).click();
        await page.locator(".result-summary").first().waitFor({ timeout: 30000 }); await wait(1500);
        await page.locator(".result-summary").first().evaluate((el) => window.scrollBy(0, el.getBoundingClientRect().top - 120));
        await wait(600);
      } },
    // --- Recurrent events ---
    { file: "recurrent-01-new.png", url: "/modelling/recurrent/new", settle: 1200 },
    { file: "recurrent-02-mcf.png", url: `/modelling/recurrent/${S.recurrent}`, settle: 2500 },
    // --- Degradation ---
    { file: "degradation-01-model.png", url: `/modelling/degradation/${S.degradation}`, settle: 2500 },
    { file: "degradation-02-tracking.png", url: "/fleet/tracking", settle: 2000 },
    // --- Optimal replacement: the bearing model, 1,000 planned vs 8,000 failure ---
    // The tool opens on "Saved model"; ?model= chooses the bearing fit, as a
    // model page's "Use this model" does (#294).
    { file: "replacement-01-result.png", url: `/strategy/replacement?model=${S.bearings}`, settle: 1800,
      async act(page) {
        await page.locator(".sel-trigger", { hasText: /Bearing life — Weibull/ }).waitFor(); await wait(400);
        await page.getByLabel(/Planned replacement cost/).fill("1000");
        await page.getByLabel(/Unplanned/).fill("8000");
        await page.getByRole("button", { name: /^Compute$/ }).click(); await wait(3000);
      } },
    // Shutdown calendar: Weibull α 365 days, β 2; a shut every 180 days at 100,
    // a failure 400, a change between shuts 150 → replace if older than 138 days.
    { file: "replacement-02-calendar.png", url: "/strategy/replacement?mode=calendar", settle: 1800,
      async act(page) {
        await press(page, /^Parameters$/); await wait(400);
        const params = page.locator(".picker .param-field input");
        await params.nth(0).fill("365");
        await params.nth(1).fill("2");
        await chooseOption(page, "Model time unit", /^Days$/);
        const shut = page.getByRole("group", { name: "Shut 1" });
        await shut.getByLabel("Name").fill("Shutdown");
        await shut.getByLabel("Replacing at it costs").fill("100");
        await shut.getByLabel(/Every how many/).fill("180");
        await chooseOption(page, "Every unit", /^days$/);
        await page.getByLabel(/Failure \(unplanned\) cost/).fill("400");
        await page.getByLabel(/Replacing between shuts costs/).fill("150");
        await page.getByRole("button", { name: /^Compute$/ }).click();
        await page.getByText(/older than 138 days/).first().waitFor({ timeout: 30000 }); await wait(1500);
        await page.locator(".cal-result, [data-wt=cal-result]").first()
          .evaluate((el) => window.scrollBy(0, el.getBoundingClientRect().top - 100)).catch(() => {});
        await wait(600);
      } },
    // --- Fleet failures and spares ---
    { file: "fleet-01-forecast.png", url: `/fleet/forecasts/${S.fleet}`, settle: 3000 },
    { file: "fleet-02-new.png", url: "/fleet", settle: 1500,
      async act(page) {
        await page.getByRole("button", { name: /New forecast/ }).click(); await wait(800);
        const m = page.locator(".modal").last();
        await m.locator("input").first().fill("Pump bearings — spares");
        await m.locator(".sel-trigger", { hasText: /Choose a saved model/ }).click(); await wait(400);
        await page.getByRole("option", { name: /Bearing life — Weibull/ }).first().click(); await wait(500);
      } },
    // --- Verify a safety function: the starter, as it opens and calculated ---
    { file: "sif-01-starter.png", url: "/rbds", settle: 1500,
      async act(page) { await page.getByText("Open the starter").first().click(); await wait(2500); } },
    { file: "sif-02-results.png", url: "/rbds", settle: 1500,
      async act(page) { await page.getByText("Open the starter").first().click(); await wait(2500); await calculate(page); } },
    // --- RCM study: the sample, with its evidence statuses ---
    { file: "rcm-01-study.png", url: "/rcm/studies/sample-rcm-truck", settle: 2000 },
    // --- Failure-finding interval: a trip failing once a year (λ = 1/8,760 h), 99% ---
    { file: "ff-01-result.png", url: "/strategy/failure-finding", settle: 1200,
      async act(page) {
        await press(page, /^Parameters$/); await wait(400);
        await chooseOption(page, "Distribution", /^Exponential$/);
        await page.locator(".picker .param-field input").first().fill("0.000114155");
        await page.getByLabel("Unit (optional)").fill("Hours");
        await page.getByRole("button", { name: /^Compute$/ }).click();
        await page.getByText(/Test every/).first().waitFor({ timeout: 20000 }); await wait(800);
      } },
    // --- Import a diagram: a Galileo file through RBDs → Import. It opens
    // unsaved with its import notes, so nothing is left behind. ---
    { file: "import-01-notes.png", url: "/rbds", settle: 1500,
      async act(page) {
        await page.locator('input[type="file"]').first().setInputFiles({
          name: "feed-system.dft", mimeType: "text/plain", buffer: Buffer.from(GALILEO_FEED),
        });
        await page.locator(".rbd-import-note").waitFor({ timeout: 20000 });
        await arrange(page);
      } },
    // --- Compare groups: the sample seals split by load ---
    { file: "cmp-01-groups.png", url: "/datasets/d/sample-ds-seal-alt?compare=load", settle: 1500,
      async act(page) {
        await page.locator(".cg-run").click();
        await page.locator(".cg-result").waitFor({ timeout: 20000 }); await wait(1500);
        await page.locator(".cg-card").evaluate((el) => window.scrollBy(0, el.getBoundingClientRect().top - 80));
        await wait(500);
      } },
    // Planning a side-by-side comparison: a 40% lower failure rate, half failing.
    { file: "cmp-02-plan.png", url: "/strategy/test-planning/comparison", settle: 1500,
      async act(page) {
        await press(page, /Old and new side by side/); await wait(400);
        await page.getByRole("button", { name: /^Compute$/ }).click();
        await page.locator(".result-summary").first().waitFor({ timeout: 30000 }); await wait(1500);
        await page.locator(".result-summary").first().evaluate((el) => window.scrollBy(0, el.getBoundingClientRect().top - 120));
        await wait(600);
      } },
    // --- Competing risks: the Model step with a failure-mode column, the
    // sample by-mode model, and its Gray's test by site ---
    { file: "crisk-01-model-step.png", url: "/modelling/new?dataset=sample-ds-pump-modes", settle: 1500,
      async act(page) {
        await chooseOption(page, "Failure mode (optional)", /^failure_mode/);
        await page.getByRole("button", { name: /^Next$/ }).click(); await wait(1200);
      } },
    { file: "crisk-02-incidence.png", url: "/modelling/m/sample-model-pump-modes", settle: 2500 },
    { file: "crisk-03-by-site.png", url: "/modelling/m/sample-model-pump-modes", settle: 2500,
      async act(page) { await page.locator("button.gofr-link").click(); await wait(1000); } },
    // --- Covariates: ticking them, the PH coefficients, a changing-load schedule ---
    { file: "cov-01-covariates.png", url: "/modelling/new?dataset=sample-ds-seal-alt", settle: 1500,
      async act(page) {
        await page.getByText("Advanced (regression): covariates").click(); await wait(400);
        await page.locator(".cov-chip", { hasText: "temp_C" }).click();
        await page.locator(".cov-chip", { hasText: "load" }).click(); await wait(500);
        await page.locator(".cov-chip", { hasText: "temp_C" }).evaluate((el) => window.scrollBy(0, el.getBoundingClientRect().top - 420));
        await wait(500);
      } },
    { file: "cov-02-coefficients.png", url: "/modelling/m/sample-model-seal-weibull-ph", settle: 2500,
      async act(page) { await press(page, /^Coefficients$/); await wait(1200); } },
    { file: "cov-03-schedule.png", url: "/modelling/m/sample-model-pump-load-weibull-ph", settle: 3000 },
    // --- One-shot devices: the per-demand form, and a model made from it
    // (deleted straight after its shot) ---
    { file: "demand-01-new.png", url: "/modelling/new?mode=perdemand", settle: 1200,
      async act(page) { await fillPerDemand(page); } },
    { file: "demand-02-result.png", url: "/modelling/new?mode=perdemand", settle: 1200,
      async act(page) {
        await fillPerDemand(page);
        await page.getByRole("button", { name: /^Create model$/ }).click();
        await page.waitForURL(/\/modelling\/m\//, { timeout: 20000 }); await wait(2000);
        this.modelId = new URL(page.url()).pathname.split("/").pop();
      },
      async cleanup() {
        if (this.modelId) await fetch(`${BASE}/api/models/${this.modelId}`, { method: "DELETE" });
      } },
    // --- Reliability Agent: the landing page (saved conversations; none on a
    // fresh server). Sign-in isn't needed, but the page only exists when the
    // server runs with RELIABILITY_AGENT_ENABLED=true, and without a model key
    // (ANTHROPIC_API_KEY) it shows "Not configured yet" instead of New chat.
    // The workflow has neither (the flag would also add Agent to the sidebar
    // in every other shot), so this shot is skipped there and says so; the
    // image on disk is kept. Re-capture it by hand with both and ONLY=agent.
    { file: "agent-01-landing.png", url: "/agent", settle: 1500,
      async skip() {
        const keep = "; the existing image is kept. Re-capture it with ONLY=agent on a server that has it.";
        if (!config.reliability_agent) {
          return `the Reliability Agent is off on this server (RELIABILITY_AGENT_ENABLED)${keep}`;
        }
        const info = await api("/reliability-agent/info").catch(() => null);
        if (!info?.enabled) return `the Reliability Agent has no model key on this server (ANTHROPIC_API_KEY)${keep}`;
        return null;
      },
      async act(page) {
        await page.locator(".agent-sess-list, .empty-note").first().waitFor({ timeout: 15000 });
      } },
  ];

  // Shots needing purpose-built fixtures (created below, deleted afterwards).
  const fixtureShots = (fx) => [
    // --- RCM study: deciding a failure mode, with the sample analysis as evidence ---
    { file: "rcm-02-decision.png", url: `/rcm/studies/${fx.rcmStudyId}`, settle: 1500,
      async act(page) {
        await page.getByText("+ Decision").first().click(); await wait(600);
        const m = page.locator(".decision-modal");
        await m.getByRole("button", { name: /^Operational$/ }).click(); await wait(300);
        await m.getByRole("button", { name: /Fixed-interval replacement/ }).click(); await wait(800);
        await m.getByPlaceholder("e.g. Replace brake pads").fill("Replace the gearbox input bearing");
        await m.getByPlaceholder("Interval").fill("580");
        await m.locator(".evidence-option", { hasText: /Bearing preventive replacement/ }).click(); await wait(500);
      } },
    // --- Teams: the workspace menu, then the team's settings (members, a pending invite) ---
    { file: "team-01-switcher.png", url: "/strategy/failure-finding", settle: 1200,
      async act(page) { await page.locator(".nav-workspace-select").first().click(); await wait(500); } },
    { file: "team-02-members.png", url: "/team", settle: 600,
      async act(page) {
        await page.evaluate((id) => localStorage.setItem("reliafy.workspace", id), fx.teamId);
        await page.reload({ waitUntil: "networkidle" });
        await page.getByText("colleague@example.com").waitFor({ timeout: 20000 }); await wait(800);
      } },
    // --- Load-sharing ---
    { file: "loadshare-01-config.png", url: `/rbds/b/${fx.loadshare.rbdId}`, settle: 1600,
      async act(page) { await page.locator(".rbd-loadshare").dblclick(); await wait(1500); } },
    // --- Build an RBD (the seeded sample diagram) ---
    { file: "rbd-01-builder.png", url: "/rbds/b/sample-rbd-pump-station", settle: 2000, act: arrange },
    { file: "rbd-02-results.png", url: "/rbds/b/sample-rbd-pump-station", settle: 1200, act: calculate },
    // Availability guide.
    { file: "availability-01-new.png", url: "/rbds/b", settle: 900 },
    { file: "availability-02-system.png", url: `/rbds/b/${fx.repairableId}`, settle: 1200,
      async act(page) { await page.locator(".rbd-mode-select .sel-trigger, .sel-trigger", { hasText: /^Repairable$/ }).first().click(); await wait(700); } },
    { file: "availability-03-add.png", url: `/rbds/b/${fx.repairableId}`, settle: 1200,
      async act(page) { await page.getByRole("button", { name: "Add block" }).click(); await wait(600); } },
    { file: "availability-04-models.png", url: `/rbds/b/${fx.repairableId}`, settle: 1400,
      async act(page) { await page.locator(".rbd-comp", { hasText: "Controller" }).dblclick(); await wait(900); } },
    { file: "availability-05-wired.png", url: `/rbds/b/${fx.repairableId}`, settle: 1400, act: arrange },
    { file: "availability-06-validate.png", url: `/rbds/b/${fx.repairableId}`, settle: 900, act: validateAndShowCheck },
    { file: "availability-07-results.png", url: `/rbds/b/${fx.repairableId}`, settle: 900, act: calculate },
    // Common-cause guide.
    { file: "ccf-01-select.png", url: `/rbds/b/${fx.ccfUngroupedId}`, settle: 1400,
      async act(page) { await arrange(page); await selectPumps(page); } },
    { file: "ccf-02-beta.png", url: `/rbds/b/${fx.ccfUngroupedId}`, settle: 1400,
      async act(page) { await arrange(page); await selectPumps(page); await page.getByRole("button", { name: /Common-cause group/i }).click(); await wait(900); } },
    { file: "ccf-03-grouped.png", url: `/rbds/b/${fx.ccfId}`, settle: 1400, act: arrange },
    { file: "ccf-04-impact.png", url: `/rbds/b/${fx.ccfId}`, settle: 900, act: calculate },
    // Safety function: a second valve alongside the first, in a common-cause group.
    { file: "sif-03-two-valves.png", url: `/rbds/b/${fx.sifId}`, settle: 1600, act: arrange },
    // Condition-based risk: the new-model page with the demo fleet's two tables,
    // the risk table, one unit's view, and a unit as an RBD block.
    { file: "cbr-01-new.png", url: "/modelling/joint/new", settle: 1500,
      async act(page) {
        await chooseOption(page, "Lifetimes: one row per unit", /^Pump lives/);
        await chooseOption(page, "Readings: one row per reading", /^Pump vibration/);
        await page.getByLabel("load changes the risk").check();
        await page.getByLabel("load changes the path").check();
        await wait(800);
      } },
    { file: "cbr-02-risk.png", url: `/modelling/joint/${fx.joint.modelId}`, settle: 3000 },
    { file: "cbr-03-unit.png", url: `/modelling/joint/${fx.joint.modelId}`, settle: 3000,
      async act(page) {
        await page.locator("#joint-unit-view").evaluate((el) => window.scrollBy(0, el.getBoundingClientRect().top - 80));
        await page.locator(".joint-unit-sum").waitFor({ timeout: 20000 }); await wait(2000);
      } },
    { file: "cbr-04-rbd.png", url: `/rbds/b/${fx.joint.rbdId}`, settle: 1600,
      async act(page) { await page.locator(".rbd-comp", { hasText: "Pump P8" }).dblclick(); await wait(1500); } },
    // Sharing: the Share dialog on a model of your own.
    { file: "share-01-dialog.png", url: `/modelling/m/${fx.ownModelId}`, settle: 2500,
      async act(page) {
        await page.locator(".page-header .ovm button").first().click(); await wait(400);
        await page.getByRole("button", { name: /^Share$/ }).click(); await wait(1200);
      } },
    // --- Outage history: a year of real outages on a saved pump station ---
    { file: "outage-01-history.png", url: `/rbds/b/${fx.outageId}`, settle: 1600,
      async act(page) {
        await page.locator(".rbd-tabs .tab", { hasText: /^Outage history$/ }).click();
        await page.locator(".rbd-avail-hero").waitFor({ timeout: 30000 }); await wait(2500);
      } },
    { file: "outage-02-fit.png", url: `/rbds/b/${fx.outageId}`, settle: 1600,
      async act(page) {
        await page.locator(".rbd-tabs .tab", { hasText: /^Outage history$/ }).click();
        await page.locator(".rbd-avail-hero").waitFor({ timeout: 30000 }); await wait(1000);
        await page.getByRole("button", { name: /^Fit models from the log$/ }).click();
        await page.getByRole("button", { name: /^Use on the ticked blocks$/ }).waitFor({ timeout: 30000 });
        await page.getByText("What drove the downtime").evaluate((el) => window.scrollBy(0, el.getBoundingClientRect().top - 90));
        await wait(800);
      } },
    // --- Network: the builder, then the Calculator at 10 years ---
    { file: "network-01-builder.png", url: `/rbds/b/${fx.networkId}`, settle: 2000 },
    { file: "network-02-result.png", url: `/rbds/b/${fx.networkId}`, settle: 1600,
      async act(page) {
        await page.locator(".rbd-tabs .tab", { hasText: /^Calculator$/ }).click(); await wait(600);
        await page.locator(".rbd-network-controls input[type=number]").fill("10");
        await page.getByText(/stay connected/).first().waitFor({ timeout: 30000 }); await wait(2000);
      } },
    // --- Targets and design (rbd-targets-and-design) ---
    { file: "targets-01-allocate.png", url: `/rbds/b/${fx.design?.train}`, settle: 1600,
      async act(page) {
        await rbdTab(page, "Targets");
        await page.getByLabel("Mission time (hours)").fill("500");
        await page.getByRole("button", { name: /^Allocate$/ }).click();
        await page.locator(".rbd-targets-result").waitFor({ timeout: 30000 }); await wait(800);
      } },
    { file: "targets-02-availability.png", url: `/rbds/b/${fx.design?.repairable}`, settle: 1600,
      async act(page) {
        await rbdTab(page, "Targets");
        await page.getByRole("button", { name: /^Allocate$/ }).click();
        await page.locator(".rbd-targets-result").waitFor({ timeout: 30000 }); await wait(800);
        await scrollTo(page.locator(".rbd-targets-result"), 260);
      } },
    { file: "targets-03-design.png", url: `/rbds/b/${fx.design?.train}`, settle: 1600,
      async act(page) {
        await rbdTab(page, "Design");
        await press(page, "Cheapest to reach a target"); await wait(300);
        const costs = page.locator(".rbd-design-table tbody tr input.rbd-design-num:not(.sm)");
        for (const [i, v] of ["4000", "6000", "15000"].entries()) await costs.nth(i).fill(v);
        await page.getByRole("button", { name: /^Find design$/ }).click();
        await page.locator(".rbd-design-result").waitFor({ timeout: 60000 }); await wait(1500);
        await scrollTo(page.locator(".rbd-design-result"), 120);
      } },
    { file: "targets-04-cheapest.png", url: `/rbds/b/${fx.design?.repairable}`, settle: 1600,
      async act(page) {
        await rbdTab(page, "Design");
        await page.getByRole("button", { name: /^Find the cheapest design$/ }).click();
        await page.locator(".rbd-cheapest-result").waitFor({ timeout: 60000 }); await wait(1000);
        await scrollTo(page.locator(".rbd-cheapest-result"), 120);
      } },
    // --- Phased missions ---
    { file: "phases-01-editor.png", url: `/rbds/b/${fx.design?.flight}`, settle: 1600,
      async act(page) {
        await builderMenu(page, /^Phased mission/); await wait(800);
        await page.locator(".rbd-phase-needs summary").nth(1).click(); await wait(500);
      } },
    { file: "phases-02-result.png", url: `/rbds/b/${fx.design?.flight}`, settle: 1400,
      async act(page) {
        await calculate(page);
        await page.locator(".rbd-mission-body").waitFor({ timeout: 30000 }); await wait(1500);
        await page.locator(".rbd-mission summary", { hasText: "Each phase" }).click(); await wait(600);
        await scrollTo(page.locator(".rbd-mission"), 40);
      } },
    // --- Production availability ---
    { file: "production-01-capacity.png", url: `/rbds/b/${fx.design?.solar}`, settle: 1600,
      async act(page) {
        await page.locator(".rbd-comp", { hasText: "Inverter 1" }).dblclick(); await wait(1200);
        // Scroll the dialog's body to its end, where the Capacity section is.
        await page.locator(".modal summary", { hasText: /^Capacity/ }).first().evaluate((el) => {
          let box = el.parentElement;
          while (box && box.scrollHeight <= box.clientHeight) box = box.parentElement;
          if (box) box.scrollTop = box.scrollHeight;
        });
        await wait(500);
      } },
    { file: "production-02-result.png", url: `/rbds/b/${fx.design?.solar}`, settle: 1400,
      async act(page) {
        await calculate(page);
        await page.locator(".rbd-production-body").waitFor({ timeout: 30000 }); await wait(1000);
        await page.locator(".rbd-production summary").click(); await wait(1500);
        await scrollTo(page.locator(".rbd-production"), 40);
      } },
    // --- Costs, intervals and what to improve ---
    { file: "costs-01-block.png", url: `/rbds/b/${fx.design?.repairable}`, settle: 1600,
      async act(page) {
        await page.locator(".rbd-comp", { hasText: "Pump A" }).dblclick(); await wait(1000);
        await page.locator(".modal summary", { hasText: /^Costs/ }).first().evaluate((el) => el.scrollIntoView({ block: "center" }));
        await wait(500);
      } },
    { file: "costs-02-diagram.png", url: `/rbds/b/${fx.design?.repairable}`, settle: 1600,
      async act(page) { await builderMenu(page, /^Costs…/); await wait(800); } },
    { file: "costs-03-ownership.png", url: `/rbds/b/${fx.design?.repairable}`, settle: 1400,
      async act(page) {
        await calculate(page);
        await page.locator("summary", { hasText: /^Details$/ }).last().click(); await wait(1500);
        await scrollTo(page.locator(".ds-section-h", { hasText: "Cost of ownership" }), 40);
      } },
    { file: "costs-04-intervals.png", url: `/rbds/b/${fx.design?.repairable}`, settle: 1600,
      async act(page) {
        await rbdTab(page, "Design");
        await page.getByRole("button", { name: /^Choose intervals$/ }).click();
        await page.locator(".rbd-intervals .rbd-compare-verdict").waitFor({ timeout: 90000 }); await wait(1000);
        await scrollTo(page.locator(".rbd-intervals"), 40);
      } },
    { file: "costs-05-improve.png", url: `/rbds/b/${fx.design?.repairable}`, settle: 1400,
      async act(page) {
        await calculate(page);
        await page.locator(".rbd-improve").getByRole("radio", { name: "Cost" }).click();
        await wait(6000);
        await scrollTo(page.locator(".rbd-improve"), 40);
      } },
  ];

  const pick = (list) => (only ? list.filter((s) => s.file.startsWith(only)) : list);
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1360, height: 900 }, deviceScaleFactor: 2 });
  let n = 0;
  const failed = [];
  const skipped = [];

  const shoot = async (list) => {
    for (const s of list) {
      // A shot that can't be taken on this server (a feature switched off)
      // is skipped out loud, never silently, and keeps its existing image.
      const why = s.skip ? await s.skip() : null;
      if (why) {
        console.warn(`SKIPPED ${s.file}: ${why}`);
        skipped.push(s.file);
        continue;
      }
      try {
        // Every shot starts in the personal workspace (the team shot switches).
        if (page.url().startsWith(BASE)) await page.evaluate(() => localStorage.removeItem("reliafy.workspace"));
        await page.goto(`${BASE}${s.url}`, { waitUntil: "networkidle" });
        await wait(s.settle || 500);
        await assertNotSignIn(page, s.url);
        if (s.act) await s.act(page);
        // A shot that drifted onto the sign-in page during its steps is no shot.
        await assertNotSignIn(page, s.url);
        const path = resolve(OUT, s.file);
        await page.screenshot({ path });
        if ((await stat(path)).size < 10_000) throw new Error(`${s.file} is nearly empty`);
        console.log("captured", s.file);
        n += 1;
      } catch (e) {
        // A sign-in page means the whole run is wrong: stop at once.
        if (/sign-in/.test(e.message)) throw e;
        // Otherwise one broken step shouldn't lose the rest; report it at the end.
        console.error(`FAILED ${s.file}: ${e.message.split("\n")[0]}`);
        failed.push(s.file);
      } finally {
        // A shot that saved something of its own removes it, so it can't show
        // up in a later shot's list.
        if (s.cleanup) await s.cleanup().catch(() => {});
      }
    }
  };

  // Phase 1 — sample data only, so no fixture can leak into a list page.
  await shoot(pick(sampleShots));

  // Phase 2 — create fixtures, shoot, then always remove them.
  const wanted = pick(fixtureShots({ loadshare: {}, joint: {} }));
  let fx = null;
  if (wanted.length) {
    fx = {
      repairableId: await seedRepairableRbd(),
      ccfId: await seedCcfRbd(),
      ccfUngroupedId: await seedCcfUngroupedRbd(),
      loadshare: await seedLoadSharingRbd(),
      sifId: await seedTwoValveSif(),
      ownModelId: await seedOwnModel(),
      joint: await seedJointModel(),
      outageId: await seedOutageRbd(),
      networkId: await seedNetworkRbd(),
      design: await seedDesignRbds(),
      rcmStudyId: await seedRcmStudy(),
      teamId: await seedTeam(),
    };
    try {
      await shoot(pick(fixtureShots(fx)));
    } finally {
      await browser.close();
      // Never leave fixtures behind in the database the app is serving.
      for (const id of [fx.repairableId, fx.ccfId, fx.ccfUngroupedId, fx.loadshare.rbdId, fx.sifId, fx.joint.rbdId,
                        fx.outageId, fx.networkId, ...Object.values(fx.design)]) {
        await fetch(`${BASE}/api/rbds/${id}`, { method: "DELETE" }).catch(() => {});
      }
      for (const id of [fx.loadshare.modelId, fx.ownModelId]) {
        await fetch(`${BASE}/api/models/${id}`, { method: "DELETE" }).catch(() => {});
      }
      await fetch(`${BASE}/api/joint/models/${fx.joint.modelId}`, { method: "DELETE" }).catch(() => {});
      await fetch(`${BASE}/api/rcm/studies/${fx.rcmStudyId}`, { method: "DELETE" }).catch(() => {});
      await fetch(`${BASE}/api/teams/${fx.teamId}`, { method: "DELETE" }).catch(() => {});
      for (const id of [fx.loadshare.datasetId, ...fx.joint.datasetIds]) {
        await fetch(`${BASE}/api/datasets/${id}`, { method: "DELETE" }).catch(() => {});
      }
    }
  } else {
    await browser.close();
  }
  console.log(`\nDone. ${n} screenshots in ${OUT}${fx ? "; fixtures cleaned up" : ""}.`);
  if (skipped.length) console.warn(`${skipped.length} shot(s) skipped, images kept: ${skipped.join(", ")}`);
  if (failed.length) {
    console.error(`${failed.length} shot(s) failed: ${failed.join(", ")}`);
    process.exit(1);
  }
}

main().catch((e) => { console.error(e); process.exit(1); });
