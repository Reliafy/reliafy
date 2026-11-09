import { test } from "node:test";
import assert from "node:assert/strict";
import {
  defaultLibrary, facetOptions, lastLibrary, libraryOptions, moveHighlight, recordSummary, rememberLibrary, rowDetail, rowFromDetail,
  showsKind, valueText,
} from "./libraryPicker.js";

const NRC = { id: "nrc", short_name: "NRC/INL 2020", name: "NRC long", basis: "field_data", kinds: { rate: 200, per_demand: 89 } };
const MIL = { id: "mil", short_name: "MIL-HDBK-217F", name: "MIL long", basis: "prediction_model", kinds: { rate: 236 } };
const MINE = { id: "u1", name: "Site gearboxes", mine: true, basis: "fitted", kinds: { life: 3 } };
const EMPTY = { id: "u2", name: "Empty one", mine: true, basis: "fitted", kinds: {} };

test("the picker opens on the last library used, else the first with usable records", () => {
  assert.equal(defaultLibrary([MIL, NRC]), "nrc"); // handbook base rates can't be a prior on their own
  assert.equal(defaultLibrary([EMPTY, MIL, NRC, MINE]), "nrc");
  assert.equal(defaultLibrary([MIL, NRC], "mil"), "mil"); // the user's own last choice wins
  assert.equal(defaultLibrary([MIL, NRC], "gone"), "nrc"); // a library no longer listed is ignored
  assert.equal(defaultLibrary([MIL, NRC], ""), ""); // "Every library" was the last choice
  assert.equal(defaultLibrary([MIL]), "mil");
  assert.equal(defaultLibrary([]), "");
});

test("the last library is remembered for the session", () => {
  rememberLibrary("u1");
  assert.equal(lastLibrary(), "u1");
  rememberLibrary("");
  assert.equal(lastLibrary(), "");
});

test("the Library dropdown lists the user's own first, marked (yours)", () => {
  assert.deepEqual(libraryOptions([NRC, MINE, MIL]).map((o) => o.label), ["Site gearboxes (yours)", "NRC/INL 2020", "MIL-HDBK-217F"]);
  assert.deepEqual(libraryOptions(null), []);
});

test("filter choices come from the facets with their counts, keeping the chosen one", () => {
  const eq = facetOptions({ pump: 41, valve: 60 }, "", { pump: "Pumps", valve: "Valves" });
  assert.deepEqual(eq, [{ value: "pump", label: "Pumps (41)" }, { value: "valve", label: "Valves (60)" }]);
  assert.deepEqual(facetOptions({ pump: 2 }, "fan", { fan: "Fans" }).at(-1), { value: "fan", label: "Fans (0)" });
  assert.deepEqual(facetOptions(undefined), []);
  assert.equal(showsKind({ rate: 4 }), false);
  assert.equal(showsKind({ rate: 4, life: 1 }), true);
  assert.equal(showsKind({ rate: 4 }, "rate"), true); // chosen: keep it so it can be cleared
});

test("arrow keys, Home, End and the page keys move the highlight within the rows", () => {
  assert.equal(moveHighlight(-1, "ArrowDown", 5), 0);
  assert.equal(moveHighlight(0, "ArrowDown", 5), 1);
  assert.equal(moveHighlight(4, "ArrowDown", 5), 4);
  assert.equal(moveHighlight(0, "ArrowUp", 5), 0);
  assert.equal(moveHighlight(3, "ArrowUp", 5), 2);
  assert.equal(moveHighlight(9, "ArrowUp", 5), 3); // a stale index past the end comes back in
  assert.equal(moveHighlight(2, "Home", 5), 0);
  assert.equal(moveHighlight(2, "End", 5), 4);
  assert.equal(moveHighlight(1, "PageDown", 30), 11);
  assert.equal(moveHighlight(5, "PageUp", 30), 0);
  assert.equal(moveHighlight(1, "Enter", 5), null);
  assert.equal(moveHighlight(0, "ArrowDown", 0), null);
});

const RATE = { id: "nrc:mdp-ftr", label: "Motor-driven pump: fails to run", kind: "rate", equipment_type: "pump", failure_mode: "Fails to run",
  mean: 2.26e-6, p05: 3.94e-7, p95: 5.38e-6, units: "per hour (running)", source: "NRC/INL 2020" };
const LIFE = { id: "u1:x", label: "Gearbox: Bearing wear", kind: "life", family: "weibull", mean: 2126, units: "hours", source: "Site gearboxes",
  equipment_type: "rotating", failure_mode: "Bearing wear" };

test("a picked record's summary: name, value with unit, short source", () => {
  assert.equal(recordSummary(RATE), "Motor-driven pump: fails to run · 2.26e−6 per hour (running) · NRC/INL 2020");
  assert.equal(recordSummary(LIFE), "Gearbox: Bearing wear · mean life 2,130 hours · Site gearboxes");
  assert.equal(recordSummary(null), "");
  assert.equal(valueText({ kind: "life", family: "weibull" }), "Weibull");
});

test("a row on a phone: one grey line with the table's other columns", () => {
  assert.equal(rowDetail(RATE, { pump: "Pumps" }),
    "Pumps · Fails to run · Failure rate · 2.26e−6 per hour (running) · 5–95%: 3.94e−7 – 5.38e−6 · NRC/INL 2020");
});

test("a full record becomes a row for a dialog opened with it chosen", () => {
  const detail = { units: "per hour (calendar)", record: { id: "nrc:mov-sop", source: "nrc", label: "Motor-operated valve: spurious operation",
    kind: "rate", equipment_type: "valve", failure_mode: { name: "Spurious operation" }, basis: "field_data",
    summary: { mean: 2.54e-8, p05: 1.93e-8, p95: 3.23e-8 }, distribution: { family: "gamma", params: [] } } };
  const row = rowFromDetail(detail, [NRC]);
  assert.equal(row.source, "NRC/INL 2020");
  assert.equal(recordSummary(row), "Motor-operated valve: spurious operation · 2.54e−8 per hour (calendar) · NRC/INL 2020");
  assert.equal(rowFromDetail(detail, []).source, "nrc");
  assert.equal(rowFromDetail(null), null);
});
