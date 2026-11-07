import test from "node:test";
import assert from "node:assert/strict";
import {
  CONSEQUENCES, DEFAULT_FILTERS, OPEN_STATUSES, STATUSES, STATUS_CHIPS, canMoveTo, closeBlock, consequenceLabel,
  consequenceShort, countsSentence, defaultFoundBy, filtering, historyRows, isOpen, itemText, levelText, nextStatus,
  positionsInScope, queryParams, repeatSentence, scopeOf, signOffText, statusLabel,
} from "./failureReports.js";
import { buildDisplay } from "./assetTree.js";

test("the loop in order, Rejected outside it", () => {
  assert.deepEqual(STATUSES, ["reported", "investigating", "corrective_action", "verifying", "closed"]);
  assert.deepEqual(OPEN_STATUSES, ["reported", "investigating", "corrective_action", "verifying"]);
  assert.equal(nextStatus("reported"), "investigating");
  assert.equal(nextStatus("verifying"), "closed");
  assert.equal(nextStatus("closed"), null);
  assert.equal(nextStatus("rejected"), null);
  assert.ok(isOpen("corrective_action"));
  assert.ok(!isOpen("closed") && !isOpen("rejected"));
  assert.equal(statusLabel("corrective_action"), "Corrective action");
  assert.deepEqual(STATUS_CHIPS.map((c) => c.id), ["open", ...STATUSES, "rejected", "all"]);
  assert.equal(STATUS_CHIPS[0].label, "Open");
});

test("what a status may move to: open any way, close only verified, reopen from the end", () => {
  assert.ok(canMoveTo("reported", "verifying"));
  assert.ok(canMoveTo("verifying", "reported"));
  assert.ok(canMoveTo("investigating", "rejected"));
  assert.ok(!canMoveTo("verifying", "closed"));
  assert.ok(canMoveTo("verifying", "closed", { verified: true }));
  assert.ok(!canMoveTo("closed", "rejected"));
  assert.ok(canMoveTo("closed", "investigating"));
  assert.ok(canMoveTo("rejected", "reported"));
  assert.ok(!canMoveTo("reported", "reported"));
  assert.ok(!canMoveTo("reported", "nope"));
});

test("the words: consequence, item line, repeat check, sign-off", () => {
  assert.equal(consequenceLabel("operational"), "Operational (output or quality)");
  assert.equal(consequenceShort("operational"), "Operational");
  assert.equal(consequenceLabel(null), "Not sure");
  assert.equal(CONSEQUENCES.at(-1).id, "");
  assert.equal(itemText(null), "");
  assert.equal(itemText({ name: "Pump unit 7", serial: "MU-7", part: { part_number: "P-1234", name: "KSB Etanorm" }, exists: true }),
    "Pump unit 7 · serial MU-7 · part P-1234 KSB Etanorm");
  assert.equal(itemText({ name: "Pump unit 7", serial: "", part: null, item_class: { name: "Centrifugal pump" }, exists: false }),
    "Pump unit 7 · Centrifugal pump (no longer in the register)");
  assert.equal(repeatSentence(null), "");
  assert.equal(repeatSentence({ since: "2026-10-12", repeats: 0, same_mode_repeats: 0, latest: null }, (d) => d),
    "No repeat failure at this position since 2026-10-12.");
  assert.equal(repeatSentence({ since: "2026-10-12", repeats: 2, same_mode_repeats: 1, latest: "2026-10-30" }, (d) => `[${d}]`),
    "2 repeat failures at this position since [2026-10-12], 1 of the same failure mode.");
  assert.equal(repeatSentence({ since: null, repeats: 1, same_mode_repeats: 0 }), "1 repeat failure at this position, none of the same failure mode.");
  assert.equal(signOffText("Closed", { on: "2026-10-12", by: "Sam", note: "Seal replaced" }, (d) => d), "Closed on 2026-10-12 by Sam: Seal replaced");
  assert.equal(signOffText("Rejected", { on: "2026-10-12", by: "", note: "" }), "Rejected on 2026-10-12");
  assert.equal(signOffText("Closed", null), "");
  assert.deepEqual(historyRows([{ change: "a" }, { change: "b" }]).map((h) => h.change), ["b", "a"]);
  assert.equal(defaultFoundBy({ displayName: "Dev User", email: "dev@local" }), "Dev User");
  assert.equal(defaultFoundBy({ email: "dev@local" }), "dev@local");
  assert.equal(defaultFoundBy(null), "");
});

test("the counts sentence names the scope", () => {
  const counts = { reported: 2, investigating: 1, corrective_action: 0, verifying: 0, closed: 3, rejected: 1, open: 3 };
  assert.equal(countsSentence(counts, { kind: "position", positions: 13 }), "3 open · 7 in all, at this position and the 12 positions inside it");
  assert.equal(countsSentence(counts, { kind: "position", positions: 1 }), "3 open · 7 in all, at this position");
  assert.equal(countsSentence(counts, { kind: "location", positions: 4 }, { kind: "loc" }), "3 open · 7 in all, at this location (4 positions)");
  assert.equal(countsSentence({ open: 1, reported: 1 }, { kind: "item" }, { kind: "item" }), "1 open · 1 in all, on this item");
  assert.equal(countsSentence(null, null), "0 open · 0 in all, at this position");
});

test("the level under the row picked, and the scope of a row", () => {
  assert.equal(levelText(["Circulation", "Pump"]), "Circulation › Pump");
  assert.equal(levelText([]), "");
  assert.equal(levelText(null), "");
  assert.deepEqual(scopeOf({ type: "pos", key: "p1" }), { position_id: "p1" });
  assert.deepEqual(scopeOf({ type: "loc", key: "l1" }), { location_id: "l1" });
  assert.deepEqual(scopeOf({ type: "item", key: "i1" }), { item_id: "i1" });
  assert.equal(scopeOf({ type: "group", key: "G:x" }), null);
  assert.equal(scopeOf(null), null);
});

test("the filters as the server's query", () => {
  assert.deepEqual(queryParams(DEFAULT_FILTERS, { position_id: "p1" }), { position_id: "p1", below: 1, status: "open", limit: 50 });
  assert.deepEqual(queryParams({ status: "all", sort: "status", q: "  seal " }, { location_id: "l1" }, { limit: 20, offset: 40 }),
    { location_id: "l1", sort: "status", q: "seal", limit: 20, offset: 40 });
  assert.deepEqual(queryParams({ status: "closed", consequence: "safety", failure_mode_id: "m1", since: "2026-01-01", until: "2026-02-01" }, { item_id: "i1" }),
    { item_id: "i1", status: "closed", consequence: "safety", failure_mode_id: "m1", since: "2026-01-01", until: "2026-02-01", limit: 50 });
  assert.deepEqual(queryParams(null, { position_id: "p1", below: false }), { position_id: "p1", below: 0, status: "open", limit: 50 });
  assert.ok(!filtering(DEFAULT_FILTERS));
  assert.ok(filtering({ status: "all" }));
  assert.ok(filtering({ q: "x" }));
  assert.ok(!filtering({ q: "  " }));
});

test("why a report can't be closed, in words", () => {
  assert.equal(closeBlock({ status: "verifying", verification: { result: "worked" }, can: { close: true } }), null);
  assert.equal(closeBlock({ status: "verifying", verification: null, can: { close: false } }),
    "Record a verification first: did the corrective action work?");
  assert.match(closeBlock({ status: "verifying", verification: { result: "not_worked" }, can: { close: false } }), /didn't work/);
  assert.equal(closeBlock({ status: "closed", verification: { result: "worked" }, can: { close: false } }), "Reopen the report first.");
  assert.equal(closeBlock({ status: "verifying", can: { close: false, reasons: ["The server's words."] } }), "The server's words.");
  assert.equal(closeBlock({ status: "verifying", can: { close: false, reasons: "One reason." } }), "One reason.");
  assert.equal(closeBlock(null), null);
});

test("the positions a report can be filed at from a row", () => {
  const DATA = {
    positions: [
      { id: "pool", name: "Swimming pool", parent_id: null, location_id: "site" },
      { id: "circ", name: "Circulation", parent_id: "pool" },
      { id: "pump", name: "Filter pump", parent_id: "circ", item: { id: "u1", name: "Pump unit" } },
      { id: "shedpos", name: "Shed heater", parent_id: null, location_id: "shed" },
    ],
    locations: [{ id: "site", name: "Site", parent_id: null }, { id: "shed", name: "Pump shed", parent_id: "site" }],
    spares: [], unhomed: [],
  };
  const d = buildDisplay(DATA, "positions");
  assert.deepEqual(positionsInScope(d, d.rows.get("pool")).map((p) => `${"-".repeat(p.depth)}${p.id}`), ["pool", "-circ", "--pump"]);
  assert.deepEqual(positionsInScope(d, d.rows.get("pump")).map((p) => p.id), ["pump"]);
  const l = buildDisplay(DATA, "locations");
  const atSite = positionsInScope(l, l.rows.get("site")).map((p) => p.id);
  assert.ok(atSite.includes("pool") && atSite.includes("shedpos"));
  // An item fitted to a position: that position.
  const u1 = { key: "u1", type: "item", ref: { id: "u1", name: "Pump unit", fitted_to: { id: "pump", name: "Filter pump" } }, kids: [], parent: null };
  assert.deepEqual(positionsInScope(d, u1).map((p) => p.id), ["pump"]);
  assert.deepEqual(positionsInScope(null, null), []);
});
