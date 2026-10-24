// Every kind of model page the shared model frame draws, for the fit check
// (modelframe.spec.js): one row per kind, the address of a model of that kind
// and the tabs its page shows. The samples cover some kinds; seedModelKinds()
// (run by seed.js) fits one of each other kind on the local smoke server.
//
// To add a model type: add a row to MODEL_KINDS with
//   slug   a short name for the test titles and screenshots
//   find   how to reach a model of it: { id } for a sample, or { name } for a
//          model seedModelKinds() saves (add its fit there too), or { path,
//          list, name } for a model in another collection (path is the page
//          address with ":id"; list is the API route listing its models)
//   tabs   the tab names the page shows, in order (none: [] for a one-view page)
// The spec then opens every tab at 1440×900 and at 400 px wide and fails on a
// page that scrolls on the desktop or sideways on the phone.

export const MODEL_KINDS = [
  { slug: "weibull", find: { id: "sample-model-bearings-weibull" },
    tabs: ["Probability plot", "Calculator", "Model characteristics", "Diagnostics", "Data"] },
  { slug: "weibull-censored", find: { id: "sample-model-pumps-weibull" },
    tabs: ["Probability plot", "Calculator", "Model characteristics", "Diagnostics", "Data"] },
  { slug: "best-fit", find: { name: "Smoke kinds — best fit" },
    tabs: ["Probability plot", "Calculator", "Model characteristics", "Diagnostics", "Data"] },
  { slug: "mixture", find: { name: "Smoke kinds — mixture" },
    tabs: ["Probability plot", "Calculator", "Model characteristics", "Diagnostics", "Data"] },
  { slug: "params-only", find: { name: "Smoke kinds — from parameters" },
    tabs: ["Calculator", "Model characteristics", "Data"] },
  { slug: "kaplan-meier", find: { name: "Smoke kinds — Kaplan-Meier" },
    tabs: ["Survival curve", "Calculator", "Model characteristics", "Data"] },
  { slug: "royston-parmar", find: { name: "Smoke kinds — Royston-Parmar" },
    tabs: ["Survival curve", "Calculator", "Model characteristics", "Diagnostics", "Data"] },
  { slug: "discrete", find: { name: "Smoke kinds — discrete" },
    tabs: ["Chance by count", "Calculator", "Model characteristics", "Diagnostics", "Data"] },
  { slug: "per-demand", find: { name: "Smoke kinds — per demand" }, tabs: [] },
  { slug: "weibull-ph", find: { id: "sample-model-seal-weibull-ph" },
    tabs: ["Effects", "Calculator", "Model characteristics", "Diagnostics", "Data"] },
  { slug: "cox-ph", find: { name: "Smoke kinds — Cox PH" },
    tabs: ["Effects", "Calculator", "Model characteristics", "Diagnostics", "Data"] },
  { slug: "frailty", find: { name: "Smoke kinds — frailty" },
    tabs: ["Effects", "Calculator", "Model characteristics", "Diagnostics", "Data"] },
  { slug: "tvc", find: { id: "sample-model-pump-load-weibull-ph" },
    tabs: ["Effects", "Calculator", "Model characteristics", "Diagnostics", "Data"] },
  { slug: "condition-life",
    find: { path: "/models/joint/:id", list: "/api/joint/models", name: "Smoke test pumps (condition-based)" },
    tabs: ["Risk now", "Calculator", "Effects", "Diagnostics", "Data"] },
  // Competing risks: life data by failure mode; with covariates, Effects too.
  { slug: "competing-risks", find: { id: "sample-model-pump-modes" },
    tabs: ["Failure modes", "Calculator", "Diagnostics", "Data"] },
  { slug: "competing-risks-fine-gray", find: { name: "Smoke kinds — competing risks, Fine-Gray" },
    tabs: ["Failure modes", "Effects", "Calculator", "Diagnostics", "Data"] },
];

// Whole counts to failure (cycles), a few still running, for a discrete fit.
const CYCLES = [
  "cycles,censored",
  ...[2, 3, 3, 4, 5, 5, 6, 6, 7, 8, 8, 9, 10, 11, 12, 13, 15, 17, 20, 24].map((v) => `${v},0`),
  "25,1", "25,1", "25,1", "25,1",
].join("\n");

// Units at six sites, the site sharing a hidden multiplier, with a
// temperature covariate: deterministic, for a shared-frailty fit.
function frailtyUnits() {
  let state = 4242;
  const rand = () => ((state = (state * 1103515245 + 12345) % 2147483648) + 0.5) / 2147483648;
  const rows = ["unit,hours,censored,site,temp_C"];
  const sites = ["A", "B", "C", "D", "E", "F"];
  const lift = [0.7, 1.4, 1.0, 0.8, 1.3, 1.1];
  for (let k = 0; k < 60; k += 1) {
    const s = k % 6;
    const temp = 60 + 10 * (k % 3);
    const scale = 2000 * Math.exp(-0.02 * (temp - 60)) / lift[s];
    const t = scale * Math.pow(-Math.log(rand()), 1 / 1.8);
    const end = Math.min(t, 3000);
    rows.push(`U${k},${end.toFixed(1)},${t >= 3000 ? 1 : 0},${sites[s]},${temp}`);
  }
  return rows.join("\n");
}

// Fit and save one model of each kind the samples don't cover. ``api`` is a
// Playwright APIRequestContext on the smoke server.
export async function seedModelKinds(api) {
  const ok = async (pending, what) => {
    const res = await pending;
    if (!res.ok()) throw new Error(`Seeding ${what}: answered ${res.status()}: ${await res.text()}`);
    return res.json();
  };
  const fit = (name, form) => ok(api.post("/api/models", { multipart: { name, ...form } }), name);
  const json = (path, data) => ok(api.post(path, { data }), path);
  const cycles = await json("/api/datasets/paste", { name: "Smoke kinds — cycles to failure", content: CYCLES });
  const units = await json("/api/datasets/paste", { name: "Smoke kinds — units by site", content: frailtyUnits() });
  const pumps = { dataset_id: "sample-ds-pumps", x: "months", c: "censored", unit: "months" };
  const bearings = { dataset_id: "sample-ds-bearings", x: "hours", unit: "hours" };
  const seal = { dataset_id: "sample-ds-seal-alt", x: "hours", c: "censored", unit: "hours" };
  await fit("Smoke kinds — best fit", { ...bearings, distribution: "best" });
  await fit("Smoke kinds — mixture", { ...bearings, distribution: "mixture", mixture: "2", mixture_distribution: "weibull" });
  await fit("Smoke kinds — Kaplan-Meier", { ...pumps, distribution: "kaplan_meier" });
  await fit("Smoke kinds — Royston-Parmar", { ...pumps, distribution: "royston_parmar" });
  await fit("Smoke kinds — discrete", { dataset_id: cycles.id, x: "cycles", c: "censored", unit: "cycles",
                                        distribution: "geometric" });
  await fit("Smoke kinds — Cox PH", { ...seal, distribution: "cox_ph", z: "temp_C" });
  await fit("Smoke kinds — competing risks, Fine-Gray", {
    dataset_id: "sample-ds-pump-modes", x: "hours", e: "failure_mode", g: "site", z: "duty_pct", unit: "hours",
    distribution: "competing_risks_fine_gray",
  });
  await fit("Smoke kinds — frailty", { dataset_id: units.id, x: "hours", c: "censored", group: "site",
                                       z: "temp_C", unit: "hours", distribution: "weibull_frailty" });
  await json("/api/models/from-params", {
    name: "Smoke kinds — from parameters", distribution: "weibull", unit: "hours",
    params: [{ name: "alpha", value: 1200 }, { name: "beta", value: 2.2 }],
  });
  await json("/api/models/per-demand", { name: "Smoke kinds — per demand", demands: 400, failures: 3 });
}

// The page address of a kind's model on the server ``api`` talks to.
export async function kindUrl(api, kind) {
  const f = kind.find;
  if (f.id) return `/models/m/${f.id}`;
  const list = await (await api.get(f.list || "/api/models")).json();
  const rows = Array.isArray(list) ? list : list.models || list.items || [];
  const hit = rows.find((m) => m.name === f.name);
  if (!hit) throw new Error(`No model named "${f.name}": seed it in seedModelKinds()`);
  return (f.path || "/models/m/:id").replace(":id", hit.id);
}
