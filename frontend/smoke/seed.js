// Global setup for the local run: the samples cover most pages, but nothing
// seeds Maintenance or an RBD simulation run, so make one of each here (a
// position from the sample RCM study, a location, an item fitted to the
// position, a work order, a part and an assembly of it, the starter item classes, a position
// class with a fitted life model and a spare with a lead time, and one availability run)
// through the API, and a generic sample plan for the Admin page's Plan tab. Skipped
// against a deployed site.
import { request } from "@playwright/test";

export const SAMPLE_PLAN = [
  "# Example plan",
  "",
  "A sample plan with dummy tasks in each state. See [the notes](docs/notes.md).",
  "",
  "```mermaid",
  "gantt",
  "    title Example plan",
  "    dateFormat YYYY-MM-DD",
  "    section Sample",
  "    Task one :done, a1, 2026-01-05, 14d",
  "    Task two :active, a2, after a1, 10d",
  "    Task three :crit, a3, after a2, 7d",
  "    Task four :a4, after a3, 10d",
  "    section Release",
  "    Milestone :milestone, m1, after a4, 0d",
  "```",
  "",
].join("\n");
export const SAMPLE_PLAN_SOURCE = "example/plans@abc1234";

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

    // A position class with a fitted life model, so its page draws the failure
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

    // A generic sample plan for the Admin page's Plan tab: prose and a Gantt chart.
    await send("PUT")("/api/admin/plan", { markdown: SAMPLE_PLAN, source: SAMPLE_PLAN_SOURCE });

    // One availability run, for the run history pages.
    const rbd = await (await api.get("/api/rbds/sample-rbd-instrument-air-availability")).json();
    await post("/api/rbds/analyze", { graph: rbd.graph, rbd_id: rbd.id, simulate: true, force: true });
  } finally {
    await api.dispose();
  }
}
