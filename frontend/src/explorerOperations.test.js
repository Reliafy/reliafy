import assert from "node:assert/strict";
import test from "node:test";
import { clearLabel, dutyText, opsCellText, opsPhoneLine, sourceText, windowText, windowsCell, zoneText } from "./explorerOperations.js";

const plan = { id: "p1", text: "Mon to Fri", hours_per_week: 80, time_zone: "Australia/Perth",
  plan: { background: { kind: "shifts", shifts: [{ days: ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"], start: "06:00", stop: "22:00" }] } } };
const own = { id: "s", name: "Site A", duty: { source: "own", from: null, plan }, parent_duty: { source: "none", from: null, text: "All the time" },
  other_use: [{ meter: "km", amount: 400, per: "day", text: "400 km a day" }], windows: [], time_zone: { zone: "Australia/Perth", source: "plan" } };
const below = { id: "p", name: "Pump 1", duty: { source: "inherited", from: { id: "s", name: "Site A" }, plan }, parent_duty: null,
  other_use: [], time_zone: { zone: "Australia/Perth", source: "plan" },
  windows: [
    { kind: "outage", name: "Cyclone season", start: "2027-01-03", end: "2027-01-10", own: false, source: { id: "s", name: "Site A" } },
    { kind: "shutdown", name: "Annual shut", start: "2027-03-01", end: "2027-03-04T00:00", hours: 72, own: false, source: { id: "l", name: "Line 1" } },
  ] };
const none = { id: "n", name: "Spare", duty: { source: "none", from: null, plan: null }, other_use: [], windows: [], time_zone: { zone: "Australia/Brisbane", source: "workspace" } };

test("each row says its duty and where it comes from", () => {
  assert.equal(dutyText(own), "Monday to Friday, 06:00 to 22:00 · about 80 hours a week");
  assert.equal(sourceText(own), "Own");
  assert.equal(sourceText(below), "From Site A");
  assert.equal(dutyText(none), "All the time (no duty set)");
  assert.equal(sourceText(none), "None here or above");
});

test("Clear names the plan it goes back to", () => {
  assert.equal(clearLabel({ parent_duty: { source: "inherited", from: { id: "s", name: "Site A" } } }), "Clear (use Site A's)");
  assert.equal(clearLabel(own), "Clear (run all the time)");
});

test("windows in words, day first, with where an inherited one comes from", () => {
  assert.equal(windowText(below.windows[0]), "Cyclone season · 3 Jan 2027 to 10 Jan 2027 · from Site A");
  assert.equal(windowText(below.windows[1]), "Annual shut · 1 Mar 2027, 72 h · from Line 1");
  assert.equal(windowsCell(below), "Cyclone season · 3 Jan 2027 to 10 Jan 2027 · from Site A (+1 more)");
  assert.equal(windowsCell(own), "");
});

test("cells, the time zone and the phone line", () => {
  assert.equal(opsCellText(own, "use"), "400 km a day");
  assert.equal(zoneText(own), "Australia/Perth");
  assert.equal(zoneText(none), "Australia/Brisbane (workspace)");
  assert.match(opsPhoneLine(below), /^From Site A · Monday to Friday/);
});

test("a date by hours with no duty links to where the duty is set", async () => {
  const { dutyHref, assumesContinuous } = await import("./explorerOperations.js");
  assert.equal(dutyHref("p1", "top"), "/asset-register/explorer?arrange=positions&root=top&sel=p1&tab=operations&plan=p1");
  assert.equal(dutyHref("p1"), "/asset-register/explorer?arrange=positions&root=p1&sel=p1&tab=operations&plan=p1");
  assert.equal(assumesContinuous({ kind: "continuous" }), true);
  assert.equal(assumesContinuous({ kind: "plan" }), false);
});
