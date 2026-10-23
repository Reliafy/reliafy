import { test } from "node:test";
import assert from "node:assert/strict";
import {
  attentionRows, dayText, recentRows, dueRows, fleetRows, otherRecent, recentFor, sparesRows, waitingFigures, workTodayRows,
} from "./home.js";

test("needs attention: worst first, samples left out, only contradicted evidence", () => {
  const rows = attentionRows({
    changes: {
      alerts: [{ fleet_id: "f1", fleet: "Trucks", url: "/forecasts/f1", text: "Above 3", at: "2026-10-10" }],
      rcm_evidence: [
        { study_id: "s1", study: "Line 2", mode: "Bearing wear", status: "contradicted", url: "/maintenance/rcm/s1" },
        { study_id: "s2", study: "Line 3", mode: "Seal", status: "supported", url: "/maintenance/rcm/s2" },
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
    models: [{ id: "m1", type: "life", kind: "Non-repairable model", name: "Bearings", to: "/models/m/m1", created_at: "2026-10-03" },
      { id: "m2", type: "life", name: "Sample", is_sample: true, to: "/models/m/m2", created_at: "2026-10-09" }],
    datasets: [{ id: "d1", name: "Lives", n_rows: 1, created_at: "2026-10-05" }],
    rbds: [{ id: "r1", name: "Pump train", n_nodes: 5, created_at: "2026-09-01", updated_at: "2026-10-07" }],
    studies: [{ id: "s1", name: "Line 2", updated_at: "2026-10-01" }],
  });
  assert.deepEqual(rows.map((r) => r.url), ["/systems/b/r1", "/data/d1", "/models/m/m1", "/maintenance/rcm/s1"]);
  assert.equal(rows[1].detail, "1 row");
  assert.equal(rows[2].kind, "Non-repairable model");
});

test("a workspace date reads as that calendar day", () => {
  assert.equal(dayText("2026-10-20"), "20 Oct 2026");
  assert.equal(dayText(""), "");
});

// ---- Role cards ----

const RECENT = recentRows({
  models: [{ id: "m1", type: "life", name: "Bearings", to: "/models/m/m1", created_at: "2026-10-03" }],
  datasets: [{ id: "d1", name: "Lives", n_rows: 3, created_at: "2026-10-04" }],
  rbds: [{ id: "r1", name: "Pump train", n_nodes: 4, created_at: "2026-10-05" }],
  forecasts: [{ id: "f1", name: "Trucks", n_items: 40, created_at: "2026-10-06" }],
});

test("role cards: each recent card shows its kind, and the rest stays in Recent", () => {
  assert.deepEqual(recentFor("recent-models", RECENT).map((r) => r.url), ["/models/m/m1"]);
  assert.deepEqual(recentFor("recent-data", RECENT).map((r) => r.url), ["/data/d1"]);
  assert.deepEqual(recentFor("recent-systems", RECENT).map((r) => r.url), ["/systems/b/r1"]);
  assert.deepEqual(otherRecent(["recent-models", "recent-data"], RECENT).map((r) => r.url),
    ["/forecasts/f1", "/systems/b/r1"]);
  assert.equal(otherRecent([], RECENT).length, RECENT.length);
});

test("role cards: a fleet's alert comes before the fleet, once", () => {
  const attention = [{ key: "alert-f1-x", url: "/forecasts/f1", kind: "Fleet alert" },
    { key: "due-t", url: "/maintenance", kind: "Overdue" }];
  assert.deepEqual(fleetRows(attention, RECENT).map((r) => r.key), ["alert-f1-x"]);
  assert.deepEqual(fleetRows([], RECENT).map((r) => r.url), ["/forecasts/f1"]);
});

const OVERVIEW = {
  today: "2026-10-20",
  due: [{ id: "t1", name: "Grease", next_due: "2026-10-18", overdue: true, open_work_order: { id: "w1", number: 7 } }],
  open_work_orders: [
    { id: "w2", number: 8, title: "Seal", due: "2026-10-20", subject: { name: "P-101" } },
    { id: "w1", number: 7, title: "Grease", due: "2026-10-18" },
    { id: "w3", number: 9, title: "Later", due: "2026-11-01" },
  ],
  proposals: [{ id: "p" }],
  critical_spares: [{ id: "c1", usable_on_hand: 0, min_on_hand: 2, part: { id: "pt", part_number: "B-1", name: "Bearing" } }],
};

test("role cards: due tasks, today's work orders and short spares from the overview", () => {
  assert.deepEqual(dueRows(OVERVIEW).map((r) => [r.kind, r.url]), [["Overdue", "/maintenance/work-orders/w1"]]);
  assert.deepEqual(workTodayRows(OVERVIEW).map((r) => [r.kind, r.name]), [["Overdue", "#7 Grease"], ["Today", "#8 Seal"]]);
  assert.deepEqual(workTodayRows(null), []);
  assert.deepEqual(sparesRows(OVERVIEW).map((r) => [r.kind, r.url, r.detail]),
    [["None left", "/asset-register/parts/pt", "0 usable, keep 2"]]);
});

test("role cards: the manager's figures, with Reliafy Maintenance's only when it's on", () => {
  const studies = [{ rollup: { supported: 3, contradicted: 1, unevidenced: 2, inconclusive: 1 } },
    { is_sample: true, rollup: { supported: 9 } }];
  const plain = waitingFigures(studies);
  assert.deepEqual(plain.map((f) => f.n), [3, 1, 3]);
  const withMaintenance = waitingFigures(studies, OVERVIEW);
  assert.deepEqual(withMaintenance.slice(3).map((f) => [f.label, f.n]),
    [["changes to decide", 1], ["tasks overdue", 1], ["open work orders", 3]]);
});
