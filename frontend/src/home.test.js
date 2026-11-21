import { test } from "node:test";
import assert from "node:assert/strict";
import {
  ATTENTION_ROWS, LITTLE_WORK, NEAR_EMPTY, RECENT_ROWS, attentionFailed, attentionReady, attentionRest, attentionRows, dayText,
  recentRows, dueRows, fleetRows, lateFigures, lateSummary, maintenanceRows, otherRecent, recentFor, sparesRows, startersPlace,
  waitingFigures, workTodayRows, homeOverview,
} from "./home.js";
import { lateWorkText, ordersSummary } from "./maintenanceOrders.js";
import { dueText } from "./maintenanceAssets.js";

test("needs attention: worst first, samples left out, only contradicted evidence", () => {
  const rows = attentionRows({
    changes: {
      alerts: [{ fleet_id: "f1", fleet: "Trucks", url: "/forecasts/f1", text: "Above 3", at: "2026-10-10" }],
      rcm_evidence: [
        { position_id: "p1", position: "Line 2", mode: "Bearing wear", status: "contradicted",
          url: "/asset-register/explorer?arrange=positions&tab=rcm&sel=p1" },
        { position_id: "p2", position: "Line 3", mode: "Seal", status: "supported",
          url: "/asset-register/explorer?arrange=positions&tab=rcm&sel=p2" },
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
  // "Inspect" has a work order open: it shows as that work order (none in this overview), not twice.
  assert.deepEqual(rows.map((r) => r.name), ["Line 2", "Pads", "Trucks", "Belts", "Grease"]);
  assert.equal(rows.find((r) => r.name === "Line 2").url, "/asset-register/explorer?arrange=positions&tab=rcm&sel=p1");
  assert.equal(rows.find((r) => r.name === "Pads").detail, "2 items to replace now");
  assert.equal(rows.find((r) => r.name === "Grease").url, "/maintenance/work-orders?tab=due");
  assert.match(rows.find((r) => r.name === "Grease").detail, /^Due 20 Oct 2026 · no work order yet$/);
});

test("needs attention is empty with nothing to go on", () => {
  assert.deepEqual(attentionRows(), []);
  assert.deepEqual(attentionRows({ changes: null, tracked: null, maintenance: null }), []);
});

test("needs attention is ready only once every source it reads has answered", () => {
  const loaded = { changes: { alerts: [] }, tracked: [], access: false };
  // Nothing in yet, and each source alone still loading: not ready, so no "nothing needs you".
  assert.equal(attentionReady(), false);
  assert.equal(attentionReady({ ...loaded, changes: undefined }), false);
  assert.equal(attentionReady({ ...loaded, tracked: undefined }), false);
  assert.equal(attentionReady({ ...loaded, access: undefined }), false);
  // Without Reliafy Maintenance the overview is never asked for.
  assert.equal(attentionReady(loaded), true);
  // With it, the overview must be in: this is the wait that showed the empty sentence too early.
  assert.equal(attentionReady({ ...loaded, access: true }), false);
  assert.equal(attentionReady({ ...loaded, access: true, maintenance: { due: [] } }), true);
  // A source that failed (null) has answered: the page doesn't wait for ever.
  assert.equal(attentionReady({ ...loaded, changes: null }), true);
  assert.equal(attentionReady({ ...loaded, access: true, maintenance: null }), true);
  // The Maintenance access check itself failed: ready (no "Loading…" for ever) and failed (Try again).
  assert.equal(attentionReady({ ...loaded, access: null }), true);
  assert.equal(attentionFailed({ ...loaded, access: null }), true);
});

test("needs attention: the rows not shown are linked to the pages that list them", () => {
  const due = (n) => Array.from({ length: n }, (_, i) => ({ key: `due-t${i}` }));
  // Everything fits: nowhere else to send anyone.
  assert.deepEqual(attentionRest(due(ATTENTION_ROWS)), []);
  assert.deepEqual(attentionRest([]), []);
  assert.deepEqual(attentionRest(), []);
  // 35 due tasks, 6 shown: the rest are on Due soon, named once.
  assert.deepEqual(attentionRest(due(35)), [{ to: "/maintenance/work-orders?tab=due", label: "Due soon" }]);
  // Only the rows left out count: a shown alert doesn't add its page.
  assert.deepEqual(attentionRest([{ key: "alert-f1-x" }, ...due(ATTENTION_ROWS)]),
    [{ to: "/maintenance/work-orders?tab=due", label: "Due soon" }]);
  // Open work orders left out are on Orders.
  assert.deepEqual(attentionRest([...due(ATTENTION_ROWS), { key: "order-w1" }]),
    [{ to: "/maintenance/work-orders", label: "Orders" }]);
  // Mixed kinds left out: each page once, in the rows' order; alerts and RCM evidence share one.
  const mixed = [...due(ATTENTION_ROWS), { key: "track-f2" }, { key: "alert-f1-x" }, { key: "rcm-p1-m-u" }, { key: "due-z" }];
  assert.deepEqual(attentionRest(mixed).map((p) => [p.to, p.label]),
    [["/risk", "Condition monitoring"], ["/changes", "What changed"], ["/maintenance/work-orders?tab=due", "Due soon"]]);
  // A smaller window, and a row of a kind with no page of its own.
  assert.deepEqual(attentionRest([{ key: "due-a" }, { key: "track-b" }], 1).map((p) => p.to), ["/risk"]);
  assert.deepEqual(attentionRest([{ key: "due-a" }, { key: "other-b" }], 1), []);
});

test("the ways to start: large and first when near-empty, compact and first with a little work, last with plenty", () => {
  assert.equal(startersPlace(0), "large");
  assert.equal(startersPlace(NEAR_EMPTY - 1), "large");
  assert.equal(startersPlace(NEAR_EMPTY), "first");
  assert.equal(startersPlace(LITTLE_WORK - 1), "first");
  // From a full Recent list up, the order is as it was: the lists, then the ways to start.
  assert.equal(LITTLE_WORK, RECENT_ROWS);
  assert.equal(startersPlace(LITTLE_WORK), "last");
  assert.equal(startersPlace(400), "last");
});

test("recent: own items only, newest save first, each linked to its page", () => {
  const rows = recentRows({
    models: [{ id: "m1", type: "life", kind: "Non-repairable model", name: "Bearings", to: "/models/m/m1", created_at: "2026-10-03" },
      { id: "m2", type: "life", name: "Sample", is_sample: true, to: "/models/m/m2", created_at: "2026-10-09" }],
    datasets: [{ id: "d1", name: "Lives", n_rows: 1, created_at: "2026-10-05" }],
    rbds: [{ id: "r1", name: "Pump train", n_nodes: 5, created_at: "2026-09-01", updated_at: "2026-10-07" }],
    analyses: [{ id: "a1", name: "Bearing replacement", headline: "Every 580 h", updated_at: "2026-10-01" }],
  });
  assert.deepEqual(rows.map((r) => r.url), ["/systems/b/r1", "/data/d1", "/models/m/m1", "/strategy/analyses/a1"]);
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
    { id: "w1", number: 7, title: "Grease", due: "2026-10-18", overdue: true },
    { id: "w3", number: 9, title: "Later", due: "2026-11-01" },
  ],
  late: { work_orders_late: 1, tasks_overdue_without_work_order: 0 },
  proposals: [{ id: "p" }],
  critical_spares: [{ id: "c1", usable_on_hand: 0, min_on_hand: 2, part: { id: "pt", part_number: "B-1", name: "Bearing" } }],
};

test("role cards: due tasks, today's work orders and short spares from the overview", () => {
  assert.deepEqual(dueRows(OVERVIEW).map((r) => [r.kind, r.url]), [
    ["Late", "/maintenance/work-orders/w1"], ["Open", "/maintenance/work-orders/w2"], ["Open", "/maintenance/work-orders/w3"]]);
  assert.deepEqual(workTodayRows(OVERVIEW).map((r) => [r.kind, r.name]), [["Overdue", "#7 Grease"], ["Today", "#8 Seal"]]);
  assert.deepEqual(workTodayRows(null), []);
  assert.deepEqual(sparesRows(OVERVIEW).map((r) => [r.kind, r.url, r.detail]),
    [["None left", "/asset-register/parts/pt", "0 usable, keep 2"]]);
});

test("role cards: the manager's figures, from the tree's RCM rollup and the overview, each only when it's there", () => {
  const rollup = { modes: 9, decided: 7, supported: 3, contradicted: 1, unevidenced: 2, inconclusive: 1, stale: 0 };
  const rcm = waitingFigures(rollup);
  assert.deepEqual(rcm.map((f) => f.n), [3, 1, 3]);
  assert.ok(rcm.every((f) => f.to === "/asset-register/explorer?tab=rcm"));
  const both = waitingFigures(rollup, OVERVIEW);
  assert.deepEqual(both.slice(3).map((f) => [f.label, f.n]),
    [["changes to decide", 1], ["work orders late", 1], ["tasks overdue with no work order", 0], ["open work orders", 3]]);
  // Without Reliafy Maintenance there is no RCM on the tree and no overview: nothing to show.
  assert.deepEqual(waitingFigures(), []);
  assert.deepEqual(waitingFigures(null, OVERVIEW).map((f) => f.label),
    ["changes to decide", "work orders late", "tasks overdue with no work order", "open work orders"]);
});

// Before Nov 2026 hand-raised work orders a month late never
// reached Home, which listed only work raised from tasks.
const HOUSE = {
  today: "2026-11-20",
  open_work_orders: [
    { id: "w7", number: 7, title: "Gutter clean", type: "corrective", due: "2026-11-14", overdue: true },
    { id: "w4", number: 4, title: "Fix the gate", type: "corrective", due: "2026-10-18", overdue: true, subject: { name: "Gate" } },
    { id: "w12", number: 12, title: "Filter swap", type: "preventive", due: "2026-11-02", overdue: true },
    { id: "w20", number: 20, title: "Paint fence", type: "corrective", due: "2026-12-15", overdue: false },
    { id: "w21", number: 21, title: "Whenever", type: "corrective", due: null, overdue: false },
  ],
  due: [
    // Raised: shown once, as work order #12.
    { id: "t1", name: "Filter swap", next_due: "2026-11-02", overdue: true, open_work_order: { id: "w12", number: 12 } },
    // Overdue with no work order yet.
    { id: "t2", name: "Test the RCD", next_due: "2026-10-25", overdue: true },
    { id: "t3", name: "Flush the tank", next_due: "2026-12-01", overdue: false },
  ],
  late: { work_orders_late: 3, tasks_overdue_without_work_order: 1 },
};

test("needs attention lists every open work order, however raised, and tasks with none, oldest due first", () => {
  const rows = maintenanceRows(HOUSE);
  assert.deepEqual(rows.map((r) => r.key),
    ["order-w4", "due-t2", "order-w12", "order-w7", "due-t3", "order-w20", "order-w21"]);
  const gate = rows[0];
  assert.equal(gate.kind, "Late");
  assert.equal(gate.tone, "danger");
  assert.equal(gate.name, "#4 Fix the gate");
  assert.equal(gate.url, "/maintenance/work-orders/w4");
  assert.equal(gate.detail, "Due 18 Oct 2026 · 33 days late · Gate");
  // Home's list: the late and overdue ones first (danger), oldest first, then the rest.
  const home = attentionRows({ maintenance: HOUSE });
  assert.deepEqual(home.slice(0, 4).map((r) => r.name), ["#4 Fix the gate", "Test the RCD", "#12 Filter swap", "#7 Gutter clean"]);
  // The rows count what the shared counts count: late work orders and overdue tasks with none.
  assert.equal(home.filter((r) => r.kind === "Late").length, HOUSE.late.work_orders_late);
  assert.equal(home.filter((r) => r.kind === "Overdue").length, HOUSE.late.tasks_overdue_without_work_order);
});

test("one count, one wording: Home, Orders and Assets say the late work the same way", () => {
  const words = "3 work orders late · 1 task overdue with no work order";
  assert.equal(lateWorkText(HOUSE.late), words);
  assert.equal(lateSummary(HOUSE), words);
  assert.match(ordersSummary({ open: HOUSE.open_work_orders, late: HOUSE.late, today: HOUSE.today }),
    /^5 open work orders\. 3 work orders late \(the latest by 33 days\) · 1 task overdue with no work order\.$/);
  assert.equal(dueText({ due: 2, overdue: 2, late: HOUSE.late }).overdue, words);
  assert.deepEqual(lateFigures(HOUSE).map((f) => [f.label, f.n]),
    [["work orders late", 3], ["tasks overdue with no work order", 1]]);
  assert.equal(lateSummary(null), "");
});

// Before Nov 2026 a failed load said "Nothing needs you right now" and welcomed a new account.
test("needs attention says it failed, not that there's nothing, when what it reads didn't load", () => {
  const ok = { changes: { alerts: [] }, tracked: [], access: false };
  assert.equal(attentionFailed(ok), false);
  assert.equal(attentionFailed({ ...ok, changes: null }), true);
  assert.equal(attentionFailed({ ...ok, tracked: null }), true);
  assert.equal(attentionFailed({ ...ok, access: true, maintenance: null }), true);
  assert.equal(attentionFailed({ ...ok, access: true, maintenance: { due: [] } }), false);
  // Without Maintenance, its overview isn't read: not a failure.
  assert.equal(attentionFailed({ ...ok, maintenance: null }), false);
  // A failed source is still an answer: the card stops loading and shows the error.
  assert.equal(attentionReady({ ...ok, changes: null }), true);
});

test("work orders turned off: Home shows what's due and no work order at all", () => {
  // On (or not said), the overview is as it came.
  assert.equal(homeOverview(HOUSE), HOUSE);
  assert.equal(homeOverview(null, false), null);
  const off = homeOverview(HOUSE, false);
  assert.deepEqual(off.open_work_orders, []);
  // Every due task, the one with a (hidden) work order too; none says "no work order yet".
  const rows = dueRows(off);
  assert.deepEqual(rows.map((r) => r.name), ["Test the RCD", "Filter swap", "Flush the tank"]);
  assert.ok(rows.every((r) => r.key.startsWith("due-") && r.url === "/maintenance/work-orders?tab=due"));
  assert.ok(rows.every((r) => !/work order/.test(r.detail)));
  // The figures and the summary count overdue tasks, never work orders.
  assert.deepEqual(lateFigures(off).map((f) => [f.label, f.n]), [["tasks overdue", 2]]);
  assert.equal(lateSummary(off), "2 tasks overdue");
  assert.ok(waitingFigures(null, off).every((f) => !/work order/.test(f.label)));
  // A technician's work today: the tasks due by today.
  assert.deepEqual(workTodayRows(off).map((r) => [r.kind, r.name]), [["Overdue", "Test the RCD"], ["Overdue", "Filter swap"]]);
  // Hidden, not lost: the overview itself is untouched.
  assert.equal(HOUSE.open_work_orders.length, 5);
});
