import { test } from "node:test";
import assert from "node:assert/strict";
import { attentionRows, dayText, recentRows } from "./home.js";

test("needs attention: worst first, samples left out, only contradicted evidence", () => {
  const rows = attentionRows({
    changes: {
      alerts: [{ fleet_id: "f1", fleet: "Trucks", url: "/fleet/forecasts/f1", text: "Above 3", at: "2026-10-10" }],
      rcm_evidence: [
        { study_id: "s1", study: "Line 2", mode: "Bearing wear", status: "contradicted", url: "/rcm/studies/s1" },
        { study_id: "s2", study: "Line 3", mode: "Seal", status: "supported", url: "/rcm/studies/s2" },
      ],
    },
    tracked: [
      { id: "t1", name: "Pads", tracking: { replace: 2, plan: 1 } },
      { id: "t2", name: "Sample pads", is_sample: true, tracking: { replace: 5 } },
      { id: "t3", name: "Belts", tracking: { plan: 1 } },
      { id: "t4", name: "Fine", tracking: { healthy: 4 } },
    ],
    maintenance: { due: [
      { id: "k1", name: "Grease", next_due: "2026-10-20", overdue: false },
      { id: "k2", name: "Inspect", next_due: "2026-10-01", overdue: true, open_work_order: { id: "w9", number: 9 } },
      { id: "k3", name: "No date" },
    ] },
  });
  assert.deepEqual(rows.map((r) => r.name), ["Line 2", "Pads", "Inspect", "Trucks", "Belts", "Grease"]);
  assert.equal(rows.find((r) => r.name === "Pads").detail, "2 items to replace now");
  assert.equal(rows.find((r) => r.name === "Inspect").url, "/maintenance/work-orders/w9");
  assert.equal(rows.find((r) => r.name === "Grease").url, "/maintenance");
  assert.match(rows.find((r) => r.name === "Grease").detail, /^Due 20 Oct 2026 · no work order yet$/);
});

test("needs attention is empty with nothing to go on", () => {
  assert.deepEqual(attentionRows(), []);
  assert.deepEqual(attentionRows({ changes: null, tracked: null, maintenance: null }), []);
});

test("recent: own items only, newest save first, each linked to its page", () => {
  const rows = recentRows({
    models: [{ id: "m1", type: "life", kind: "Non-repairable model", name: "Bearings", to: "/modelling/m/m1", created_at: "2026-10-03" },
      { id: "m2", type: "life", name: "Sample", is_sample: true, to: "/modelling/m/m2", created_at: "2026-10-09" }],
    datasets: [{ id: "d1", name: "Lives", n_rows: 1, created_at: "2026-10-05" }],
    rbds: [{ id: "r1", name: "Pump train", n_nodes: 5, created_at: "2026-09-01", updated_at: "2026-10-07" }],
    studies: [{ id: "s1", name: "Line 2", updated_at: "2026-10-01" }],
  });
  assert.deepEqual(rows.map((r) => r.url), ["/rbds/b/r1", "/modelling/data/d1", "/modelling/m/m1", "/rcm/studies/s1"]);
  assert.equal(rows[1].detail, "1 row");
  assert.equal(rows[2].kind, "Non-repairable model");
});

test("a workspace date reads as that calendar day", () => {
  assert.equal(dayText("2026-10-20"), "20 Oct 2026");
  assert.equal(dayText(""), "");
});
