// Global setup for the local run: the samples cover most pages, but nothing
// seeds Maintenance or an RBD simulation run, so make one of each here (a
// position from the sample RCM study, a location, an item fitted to the
// position, a work order, a part and an assembly of it, the starter item classes, a position
// class with a fitted non-repairable model and a spare with a lead time, one availability run,
// and a model of each kind the samples don't cover)
// through the API. Skipped against a deployed site.
import { request } from "@playwright/test";
import { seedModelKinds } from "./modelKinds.js";

// A deterministic fleet: 40 pumps, a vibration path each, those whose
// vibration starts high failing sooner; still running at day 120 otherwise.
export function jointFleet() {
  let state = 12345;
  const rand = () => ((state = (state * 1103515245 + 12345) % 2147483648) + 0.5) / 2147483648;
  const normal = () => Math.sqrt(-2 * Math.log(rand())) * Math.cos(2 * Math.PI * rand());
  const life = ["pump,age,running,load"];
  const reads = ["pump,age,vibration"];
  for (let k = 0; k < 40; k += 1) {
    const start = 2 + 0.4 * normal();
    const rate = 0.02 + 0.005 * normal();
    const load = k % 2;
    const t = 100 * Math.sqrt(-Math.log(rand())) * Math.exp(-0.9 * (start - 2) - 0.3 * load);
    const end = Math.min(t, 120);
    life.push(`P${k},${end.toFixed(3)},${t >= 120 ? 1 : 0},${load}`);
    for (let age = 0; age < end; age += 10) {
      reads.push(`P${k},${age},${(start + rate * age + 0.2 * normal()).toFixed(4)}`);
    }
  }
  return { lifetimes: life.join("\n"), readings: reads.join("\n") };
}

async function seedJointModel(post) {
  const { lifetimes, readings } = jointFleet();
  const life = await post("/api/datasets/paste", { name: "Smoke test pump lives", content: lifetimes });
  const reads = await post("/api/datasets/paste", { name: "Smoke test pump vibration", content: readings });
  await post("/api/joint/models", {
    name: "Smoke test pumps (condition-based)",
    lifetimes_dataset_id: life.id,
    readings_dataset_id: reads.id,
    mapping: { id: "pump", x: "age", c: "running" },
    readings_mapping: { id: "pump", age: "age", value: "vibration" },
    covariates: ["load"],
    path_model: "linear",
    unit: "Days",
    marker: "vibration",
    marker_unit: "mm/s",
  });
}

export default async function seed(config) {
  if (process.env.SMOKE_BASE_URL) return;
  const api = await request.newContext({ baseURL: config.projects[0].use.baseURL });
  const send = (method) => async (path, data) => {
    const res = await api.fetch(path, { method, data });
    if (!res.ok()) throw new Error(`Seeding: ${method} ${path} answered ${res.status()}: ${await res.text()}`);
    return res.json();
  };
  const post = send("POST");
  const patch = send("PATCH");
  try {
    const m = "/api/maintenance";
    const { position_id } = await post(`${m}/from-rcm`, { study_id: "sample-rcm-truck" });
    // The sample study is off the list, so make one of our own for the study pages to open.
    await post("/api/rcm/studies", { name: "Smoke test study", system: "Smoke test system", description: "" });
    const location = await post(`${m}/locations`, { name: "Smoke test depot" });
    const item = await post(`${m}/items`, { name: "Smoke test brake set", serial: "SMOKE-1" });
    await patch(`${m}/positions/${position_id}`, { location_id: location.id });
    await post(`${m}/positions/${position_id}/fit`, { item_id: item.id });
    await post(`${m}/work-orders`, { position_id, title: "Smoke test inspection" });
    const pad = await post(`${m}/parts`, { part_number: "SMOKE-PAD", name: "Smoke test brake pad" });
    // A product structure (#435): an axle brake set made of four pads, the item an instance of it.
    const brakes = await post(`${m}/parts`, { part_number: "SMOKE-BRAKES", name: "Smoke test axle brake set" });
    await post(`${m}/parts/${brakes.id}/structure`, { child_id: pad.id, quantity: 4, ref: "LF, RF, LR, RR" });
    await send("PUT")(`${m}/parts/${brakes.id}/level`, { level: "Assembly" });
    await send("PUT")(`${m}/items/${item.id}/part`, { part_id: brakes.id });
    await post(`${m}/item-classes/starter`, { dry_run: false });

    // A position class with a fitted non-repairable model, so its page draws the failure
    // forecast (#407): three pumps, each with two past failures and an item in
    // now, a critical replacement part with one in stock, and the class's costs.
    const ago = (days) => new Date(Date.now() - days * 86400000).toISOString().slice(0, 10);
    const pump = "Smoke test pump";
    const spare = await post(`${m}/parts`, { part_number: "SMOKE-PUMP", name: "Smoke test pump", unit_cost: 900 });
    await post(`${m}/parts/${spare.id}/stock`, { location_id: location.id, delta: 1, reason: "smoke test" });
    // A lead time, so the forecast's stock levels (#31) go by the part's own.
    await patch(`${m}/parts/${spare.id}`, { lead_time_days: 60 });
    for (const [i, lives] of [[520, 610], [470, 690], [560, 580]].entries()) {
      const p = await post(`${m}/positions`, { name: `Smoke pump ${i + 1}`, position_class: pump });
      let day = 1500;
      for (const [n, life] of lives.entries()) {
        await post(`${m}/positions/${p.id}/past-fitments`, {
          start: ago(day), end: ago(day - life), reason: "failure", failure_mode_text: "Seized",
          new_item: { name: `Smoke pump ${i + 1}.${n}` },
        });
        day -= life;
      }
      await post(`${m}/positions/${p.id}/fit`, { new_item: { name: `Smoke pump ${i + 1}.now` }, on: ago(day) });
      await post(`${m}/positions/${p.id}/parts`, { part_id: spare.id, role: "replacement", critical: true });
    }
    await send("PUT")(`${m}/classes/costs`, { position_class: pump, planned_cost: 400, failure_cost: 4000 });
    await post(`${m}/classes/fit`, { position_class: pump });

    // A condition and life model: a small fleet of pumps, each with its
    // vibration read every 10 days, fitted in-process (billing is off here).
    await seedJointModel(post);
    // One model of each kind the samples don't cover, for the model pages'
    // fit check (modelframe.spec.js).
    await seedModelKinds(api);

    // One availability run, for the run history pages.
    const rbd = await (await api.get("/api/rbds/sample-rbd-instrument-air-availability")).json();
    await post("/api/rbds/analyze", { graph: rbd.graph, rbd_id: rbd.id, simulate: true, force: true });
  } finally {
    await api.dispose();
  }
}
