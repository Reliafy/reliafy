import test from "node:test";
import assert from "node:assert/strict";
import { changeRows, changesForAssistant, periodQuery, refitDetail, sentenceParts } from "./changes.js";

const DATA = {
  since: "2026-09-11T00:00:00+00:00",
  period: { kind: "days", days: 30, label: "in the last 30 days" },
  sentence: "In the last 30 days: 1 fleet alert fired, 1 refit moved its answer and 1 item was added.",
  counts: { items: 4, new: 1, changed: 0, refits: 2, refits_moved: 1, forecasts_moved: 0, alerts: 1,
    rcm_evidence: 0, runs: 0, runs_moved: 0 },
  new: [{ collection: "rbds", type: "Block diagram", id: "d", name: "Skid", url: "/systems/b/d", at: "2026-10-09T00:00:00+00:00" }],
  changed: [],
  refits: [
    { id: "m1", name: "Pump life", url: "/models/m/m1", at: "2026-10-08T00:00:00+00:00", unit: "Hours", comparable: true,
      moved: [{ measure: "B10", before: 1200, after: 900, change: -0.25 }, { measure: "Failure pattern", before: "random", after: "wear-out" }] },
    { id: "m2", name: "Seal life", url: "/models/m/m2", at: "2026-10-07T00:00:00+00:00", unit: "Hours", comparable: true, moved: [] },
  ],
  forecasts: [],
  alerts: [{ fleet_id: "f", fleet: "Trucks", url: "/forecasts/f", at: "2026-10-10T00:00:00+00:00",
    text: "Expected failures for Trucks rose above 2" }],
  rcm_evidence: [],
  simulations: [],
  thresholds: { relative: 0.1, availability_points: 0.5 },
  not_compared: [{ what: "Failures recorded against the forecast", why: "Not stored." }],
};

test("rows put alerts and moved answers before new items, and held refits last", () => {
  const rows = changeRows(DATA);
  assert.deepEqual(rows.map((r) => r.kind), ["Fleet alert", "Refit moved", "New block diagram", "Refitted"]);
  assert.equal(rows[0].tone, "warning");
  assert.equal(rows[1].url, "/models/m/m1");
});

test("a refit's detail gives each measure before and after", () => {
  assert.equal(refitDetail(DATA.refits[0]), "B10 1,200 → 900 hours (−25%); failure pattern random → wear-out");
  assert.equal(refitDetail(DATA.refits[1]), "Refitted; B10 and MTTF held");
});

test("the sentence's counts are marked bold, not its period", () => {
  assert.deepEqual(sentenceParts("In the last 30 days: 1 item was added and 12 changed.").filter((p) => p.bold)
    .map((p) => p.text), ["1", "12"]);
  assert.deepEqual(sentenceParts("Since your last visit (3 Oct 2026): 2 items changed.").map((p) => p.text).join(""),
    "Since your last visit (3 Oct 2026): 2 items changed.");
  assert.deepEqual(sentenceParts("Nothing changed in the last 30 days.").filter((p) => p.bold), []);
});

test("periods map to the request", () => {
  assert.deepEqual(periodQuery("7"), { days: 7 });
  assert.deepEqual(periodQuery("last_visit"), { since: "last_visit" });
  assert.deepEqual(periodQuery("junk"), { days: 30 });
});

test("the assistant gets the computed facts and what couldn't be compared, nothing more", () => {
  const out = changesForAssistant(DATA);
  assert.equal(out.sentence, DATA.sentence);
  assert.equal(out.changes.length, 4);
  assert.deepEqual(out.changes[0], { kind: "Fleet alert", name: "Trucks", path: "/forecasts/f",
    detail: "Expected failures for Trucks rose above 2", at: "2026-10-10T00:00:00+00:00" });
  assert.deepEqual(out.not_compared, ["Failures recorded against the forecast: Not stored."]);
  assert.equal(changesForAssistant(DATA, 2).more, 2);
});

test("simulations and evidence read plainly", async () => {
  const { simulationDetail, rcmDetail } = await import("./changes.js");
  assert.equal(simulationDetail({ runs: 2, before: { availability: 0.9621 }, after: { availability: 0.9487 } }),
    "2 runs; availability 96.21% → 94.87%");
  assert.equal(rcmDetail({ mode: "Seal leaks", evidence: "Seal life", status_before: "supported", status: "contradicted",
    status_changed: true }), "“Seal leaks”: Seal life was refitted; evidence supported → contradicted");
  const rows = changeRows({ rcm_evidence: [{ position_id: "p", position: "Pump A",
    url: "/asset-register/explorer?arrange=positions&tab=rcm&sel=p", mode: "Seal leaks",
    evidence: "Seal life", evidence_url: "/models/m/x", status: "contradicted" }] });
  assert.equal(rows[0].tone, "danger");
  assert.equal(rows[0].name, "Pump A");
  assert.equal(rows[0].key, "rcm-p-Seal leaks-/models/m/x");
});

test("a refit that only changed its failure pattern starts with a capital", () => {
  assert.equal(refitDetail({ moved: [{ measure: "Failure pattern", before: "random", after: "wear-out" }] }),
    "Failure pattern random → wear-out");
});
