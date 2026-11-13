// Global setup for the local run: the samples cover most pages, but nothing
// seeds Maintenance or an RBD simulation run, so make one of each here (a
// product, the smoke test pump skid: its design with an RCM and a scored FME(C)A, its
// bill of materials, three items built from it with two failure reports and an RBD built
// from its tree; a fault tree, a reliability prediction and a maintainability prediction
// for their own pages (there's no shared sample of those); a position with a location, an item fitted to it, a work order, a part and an assembly of it, the starter item classes, a position
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

async function seedJointModel(post, put) {
  const { lifetimes, readings } = jointFleet();
  const life = await post("/api/datasets/paste", { name: "Smoke test pump lives", content: lifetimes });
  await put(`/api/datasets/${life.id}/measurements/paste`, { content: readings });
  await post("/api/joint/models", {
    name: "Smoke test pumps (condition-based)",
    dataset_id: life.id,
    mapping: { id: "pump", x: "age", c: "running" },
    readings_mapping: { id: "pump", age: "age", value: "vibration" },
    covariates: ["load"],
    path_model: "linear",
    unit: "Days",
    marker: "vibration",
    marker_unit: "mm/s",
  });
}

export const SMOKE_PRODUCT = "Smoke test pump skid";

// The smoke test pump skid: a part with a one-level bill of materials, the product's design
// (Drive › Motor 1, Motor 2; Pump › Seal 1, Seal 2; Controls › Speed drive), Motor 1's RCM
// (two failure modes, both scored, one decided and one not), the bearing model on the
// motors, three items built (0007, 0008, 0009) with two failure reports on 0007's Motor 1,
// and an RBD built from the design's tree.
async function seedProduct(post, put, patch) {
  const m = "/api/maintenance";
  const part = await post(`${m}/parts`, { part_number: "SMOKE-SKID", name: SMOKE_PRODUCT });
  for (const [number, name, quantity] of [["SMOKE-CB", "Controller board", 1], ["SMOKE-M30", "Motor 30 kW", 2],
    ["SMOKE-FRAME", "Base frame", 1], ["SMOKE-MS", "Mechanical seal", 2], ["SMOKE-UPS", "Backup battery", 1]]) {
    const child = await post(`${m}/parts`, { part_number: number, name });
    await post(`${m}/parts/${part.id}/structure`, { child_id: child.id, quantity });
  }
  const product = await post(`${m}/products`, { name: SMOKE_PRODUCT, part_id: part.id, rev: "B" });
  const at = {};
  for (const [group, kids] of [["Drive", ["Motor 1", "Motor 2"]], ["Pump", ["Seal 1", "Seal 2"]], ["Controls", ["Speed drive"]]]) {
    const g = await post(`${m}/positions`, { name: group, parent_id: product.id });
    for (const kid of kids) at[kid] = (await post(`${m}/positions`, { name: kid, parent_id: g.id })).id;
  }
  for (const motor of ["Motor 1", "Motor 2"]) {
    await post(`${m}/positions/${at[motor]}/models`, { model_id: "sample-model-bearings-weibull" });
  }
  const fn = await post(`${m}/positions/${at["Motor 1"]}/functions`, { text: "Drive the pump at 1,480 rpm" });
  const ff = await post(`${m}/functions/${fn.id}/failures`, { text: "Motor stops" });
  const seizure = await post(`${m}/positions/${at["Motor 1"]}/failure-modes`, { text: "Bearing seizure", functional_failure_id: ff.id });
  const winding = await post(`${m}/positions/${at["Motor 1"]}/failure-modes`, { text: "Winding insulation breaks down", functional_failure_id: ff.id });
  await patch(`${m}/failure-modes/${seizure.id}`, { severity: 9, occurrence: 4, detection: 6, cause: "Dust in the grease",
    effects: "Pump stops" });
  await patch(`${m}/failure-modes/${winding.id}`, { severity: 7, occurrence: 2, detection: 5, effects: "Pump stops" });
  // Run to failure as "random", against a bearing model that shows wear-out: contradicted.
  await put(`${m}/failure-modes/${seizure.id}/decision`, { consequence: "operational",
    decision: { outcome: "rtf", rtf_basis: "random", evidence: { type: "model", id: "sample-model-bearings-weibull" } } });
  for (const serial of ["0007", "0008", "0009"]) {
    const built = await post(`${m}/products/${product.id}/build`, { serial, dry_run: false }, 120000);
    if (serial !== "0007") continue;
    const motor = built.positions.find((row) => row.path.endsWith("› Drive › Motor 1"));
    for (const title of ["Smoke test: motor tripped on overload", "Smoke test: bearing running hot"]) {
      await post(`${m}/failure-reports`, { position_id: motor.id, title, consequence: "operational" });
    }
  }
  await post(`${m}/positions/${product.id}/models`, { build_rbd: true });
  return product;
}

async function seedPredictions(post) {
  await post("/api/fault-trees", { name: "Smoke test water supply", tree: { unit: "hours", top: "top", nodes: [
    { id: "top", type: "gate", gate: "or", label: "No water to the tank", inputs: ["a", "b"] },
    { id: "a", type: "event", label: "Pump A fails", probability: 0.1 },
    { id: "b", type: "event", label: "Pump B fails", probability: 0.2 }] } });
  await post("/api/predictions", { name: "Smoke test control box", inputs: { environment: "GF", mission_time: 100, lines: [
    { name: "D1", record_id: "mil-hdbk-217f-n2:6-1-general-purpose-analog", quantity: 2, assembly: "Power" },
    { name: "C1", record_id: "mil-hdbk-217f-n2:10-1-ck-11015", quantity: 10 }] } });
  const line = (name, assembly, rate, replace) => ({ name, assembly, quantity: 1, failure_rate: rate,
    elements: { isolation: 10, access: 15, replace, restore: 10, checkout: 10 } });
  await post("/api/maintainability/predictions", { name: "Smoke test pump skid — maintainability", inputs: {
    unit: "minutes", failure_rate_unit: "per_million_hours", percentile: 0.95, lines: [
      line("Motor 30 kW", "Drive", 45, 90), line("Mechanical seal", "Pump", 180, 60), line("Speed drive", "Controls", 70, 30)] } });
}

export default async function seed(config) {
  if (process.env.SMOKE_BASE_URL) return;
  const api = await request.newContext({ baseURL: config.projects[0].use.baseURL });
  const send = (method) => async (path, data, timeout = undefined) => {
    const res = await api.fetch(path, { method, data, timeout });
    if (!res.ok()) throw new Error(`Seeding: ${method} ${path} answered ${res.status()}: ${await res.text()}`);
    return res.json();
  };
  const post = send("POST");
  const patch = send("PATCH");
  try {
    // A fault tree, a reliability prediction and a maintainability prediction, for their own
    // pages (no shared sample of these).
    await seedPredictions(post);
    const m = "/api/maintenance";
    // A product: the smoke test pump skid (Products, Items, the FME(C)A on a design).
    await seedProduct(post, send("PUT"), patch);
    // A plain position in the depot, with an item fitted and a work order.
    const { id: position_id } = await post(`${m}/positions`, { name: "Depot conveyor (smoke test)" });
    const location = await post(`${m}/locations`, { name: "Smoke test depot" });
    const item = await post(`${m}/items`, { name: "Smoke test brake set", serial: "SMOKE-1" });
    await patch(`${m}/positions/${position_id}`, { location_id: location.id });
    await post(`${m}/positions/${position_id}/fit`, { item_id: item.id });
    await post(`${m}/work-orders`, { position_id, title: "Smoke test inspection" });
    // A weekly check in a work package (Maintenance › Packages, and a package's own page).
    const check = await post(`${m}/positions/${position_id}/tasks`, { name: "Smoke test belt check", interval: 1, unit: "weeks" });
    await post(`${m}/packages`, { name: "Smoke test weekly round", position_id, every: 1, unit: "weeks", tasks: [check.id] });
    // A hand-read condition point with alarm limits and a few readings, one voided: its
    // full view (the Measurements tab's &point=) draws the chart and the readings table.
    const vib = await post(`${m}/positions/${position_id}/points`, {
      name: "Smoke test vibration", kind: "condition", unit: "mm/s", alarm_above: 7.1, alarm_below: 0.5 });
    const dayAgo = (days) => new Date(Date.now() - days * 86400000).toISOString().slice(0, 10);
    let last = null;
    for (const [days, value] of [[28, 2.8], [21, 3.0], [14, 3.1], [7, 3.4]]) {
      last = await post(`${m}/points/${vib.id}/readings`, { value, on: dayAgo(days), note: days === 7 ? "After greasing" : "" });
    }
    const typo = (last.readings || [])[1];
    if (typo?.id) await post(`${m}/readings/${typo.id}/void`, { reason: "smoke test" });
    // A fed sensor channel beside it (a smart plug's power, single values) with a level to
    // watch: a row of the Explorer's Measurements tab, and its full view (&channel=).
    const plug = await post(`${m}/signals/channels`, { position_id, name: "Smoke test pump power", unit: "W", tag: "smoke.plug" });
    await post(`${m}/signals/channels/${plug.id}/levels`, { name: "Smoke test power level", stat: "value", alarm_above: 900 });
    for (const [hours, value] of [[30, 610], [20, 640], [10, 655]]) {
      await post(`${m}/signals/snapshots`, { channel_id: plug.id, time: new Date(Date.now() - hours * 3600000).toISOString(), value });
    }
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
    await seedJointModel(post, send("PUT"));
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
