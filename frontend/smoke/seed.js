// Global setup for the local run: the samples cover most pages, but nothing
// seeds Maintenance or an RBD simulation run, so make one of each here (a
// position from the sample RCM study, a location, an item fitted to the
// position, a work order, a part, the starter item classes, and one
// availability run) through the API. Skipped against a deployed site.
import { request } from "@playwright/test";

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
    await post(`${m}/parts`, { part_number: "SMOKE-PAD", name: "Smoke test brake pad" });
    await post(`${m}/item-classes/starter`, { dry_run: false });

    // One availability run, for the run history pages.
    const rbd = await (await api.get("/api/rbds/sample-rbd-instrument-air-availability")).json();
    await post("/api/rbds/analyze", { graph: rbd.graph, rbd_id: rbd.id, simulate: true, force: true });
  } finally {
    await api.dispose();
  }
}
