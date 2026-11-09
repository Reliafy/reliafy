import { test } from "node:test";
import assert from "node:assert/strict";
import {
  csvFileName, factorsText, fmtHours, fmtPerHour, fmtPerMillion, fmtReliability, lineFromServer, linesCsv,
  linesForServer, linesFromSaved, linesProblem, newPredictionPath, paretoBars, parsePartsList, predictionPath,
  partTypeMode, summaryText,
} from "./predictions.js";

test("addresses", () => {
  assert.equal(predictionPath("a b"), "/predictions/a%20b");
  assert.equal(newPredictionPath(), "/predictions/new");
  assert.equal(newPredictionPath({ product: "p1" }), "/predictions/new?product=p1");
  assert.equal(newPredictionPath({ from: "x" }), "/predictions/new?from=x");
});

test("a pasted parts list: name, quantity and assembly in several spellings", () => {
  const lines = parsePartsList([
    "Part, Qty, Assembly",
    "Ceramic capacitor, 48, Flight controller",
    "Chip resistor\t62\tFlight controller",
    "4 x Brushless motor",
    "Propeller x4",
    "Power connector ×2; Power",
    "",
    "GPS module",
  ].join("\n"));
  assert.deepEqual(lines.map((l) => [l.name, l.quantity, l.assembly]), [
    ["Ceramic capacitor", 48, "Flight controller"],
    ["Chip resistor", 62, "Flight controller"],
    ["Brushless motor", 4, ""],
    ["Propeller", 4, ""],
    ["Power connector", 2, "Power"],
    ["GPS module", 1, ""],
  ]);
  assert.equal(lines[0].record_id, null);
  assert.deepEqual(parsePartsList(""), []);
  // A second column that isn't a number is the assembly.
  assert.deepEqual(parsePartsList("Diode, Power board").map((l) => [l.name, l.quantity, l.assembly]),
    [["Diode", 1, "Power board"]]);
});

test("lines to and from the server", () => {
  const sent = linesForServer([
    { name: " D1 ", reference: "", quantity: "2", assembly: "Power › BMS", record_id: "r1", quality_factor: "" },
    { name: "C1", quantity: 10, assembly: "", record_id: null, quality_factor: "2.5" },
    { name: "", quantity: 1 },
    { name: "Q1", quantity: 1, record_id: "r2", quality_factor: "1" },
    { name: "Battery", quantity: 1, record_id: null, user_rate: "20" },
    { name: "Airframe", quantity: 1, record_id: "r3", excluded: true },
  ]);
  // A quality factor goes only with a part type, and as typed (1 too: blank means the type's default grade).
  assert.deepEqual(sent, [
    { name: "D1", quantity: 2, assembly: "Power › BMS", record_id: "r1" },
    { name: "C1", quantity: 10 },
    { name: "Q1", quantity: 1, record_id: "r2", quality_factor: 1 },
    { name: "Battery", quantity: 1, rate_per_million_hours: 20 },
    { name: "Airframe", quantity: 1, excluded: true },
  ]);
  const rated = lineFromServer({ name: "Battery", quantity: 1, rate_per_million_hours: 20 });
  assert.equal(rated.user_rate, 20);
  assert.equal(lineFromServer({ name: "Prop", quantity: 4, excluded: true }).excluded, true);
  const back = lineFromServer({ name: "D1", quantity: 4, assembly: ["Power", "BMS"], record_id: "r1",
    part_type: "Diode", quality_factor: 1, reference: "D-1" });
  assert.equal(back.assembly, "Power › BMS");
  assert.equal(back.record.name, "Diode");
  assert.equal(back.quality_factor, "");
  assert.equal(back.reference, "D-1");
  const saved = linesFromSaved({ inputs: { lines: [{ name: "D1", quantity: 1, record_id: "r1", quality_factor: 2 }] },
    results: { lines: [{ part_type: "Diode, low frequency" }] } });
  assert.equal(saved[0].record.name, "Diode, low frequency");
  assert.equal(saved[0].quality_factor, 2);
});

test("what stops a calculation", () => {
  assert.equal(linesProblem([]), "Add at least one part.");
  assert.equal(linesProblem([{ name: "D", quantity: 0, record_id: "r" }]), "D: the quantity must be more than 0.");
  assert.equal(linesProblem([{ name: "D", quantity: 1, record_id: "r", quality_factor: "-1" }]),
    "D: the quality factor must be more than 0.");
  assert.equal(linesProblem([{ name: "D", quantity: 1 }]),
    "Give at least one part a handbook part type (or a rate of your own).");
  assert.equal(linesProblem([{ name: "D", quantity: 1, record_id: "r", excluded: true }]),
    "Give at least one part a handbook part type (or a rate of your own).");
  assert.equal(linesProblem([{ name: "B", quantity: 1, user_rate: "0" }]),
    "B: a rate you give must be more than 0 per million hours.");
  assert.equal(linesProblem([{ name: "B", quantity: 1, user_rate: "12" }, { name: "A", quantity: 1, excluded: true }]), null);
  assert.equal(linesProblem([{ name: "D", quantity: 1, record_id: "r" }, { name: "M", quantity: 4 }]), null);
});

test("numbers as shown: no NaN, Infinity or long floats", () => {
  assert.equal(fmtPerMillion(0.022799999999), "0.0228");
  assert.equal(fmtPerMillion(112.25044), "112");
  assert.equal(fmtPerHour(2.2799999e-8), "2.28e-8");
  assert.equal(fmtPerHour(0), "0");
  assert.equal(fmtHours(8908.651), "8,910");
  assert.equal(fmtHours(481.23), "481.2");
  assert.equal(fmtHours(43859649.12), "43,900,000");
  assert.equal(fmtReliability(0.9888377), "98.88%");
  assert.equal(fmtReliability(0.9999772), "99.998%");
  assert.equal(fmtReliability(0.5), "50%");
  for (const f of [fmtPerMillion, fmtPerHour, fmtHours, fmtReliability]) {
    assert.equal(f(null), "—");
    assert.equal(f(NaN), "—");
    assert.equal(f(Infinity), "—");
  }
});

test("the one-line answer and the factors", () => {
  const results = {
    failure_rate_per_million_hours: 112.25, failure_rate_per_hour: 1.1225e-4, mtbf_hours: 8908.65,
    reliability_at_mission: 0.98884, mission_time_hours: 100,
  };
  assert.equal(summaryText(results),
    "112 failures per million hours (1.12e-4 per hour) · MTBF 8,910 h · 98.88% reliable over 100 h");
  assert.equal(summaryText({ failure_rate_per_million_hours: 0 }), "No part type assigned yet, so no failure rate.");
  assert.equal(factorsText({
    applied: [{ symbol: "λb" }, { symbol: "πE" }, { symbol: "πQ" }],
    not_applied: [{ symbol: "πT", name: "temperature" }, { symbol: "πS", name: "electrical stress" }],
  }), "Applied: λb, πE, πQ. Not applied: πT (temperature), πS (electrical stress).");
  assert.equal(factorsText({ applied: [{ symbol: "λb" }], not_applied: [] }),
    "Applied: λb. That's the whole handbook model for these parts.");
});

test("the Pareto keeps the top lines and groups the rest", () => {
  const byLine = Array.from({ length: 12 }, (_, i) => ({
    name: i < 2 ? "Chip resistors" : `Part ${i}`, assembly: i === 0 ? "ESC" : "FC",
    rate_per_million_hours: 12 - i, share: (12 - i) / 78,
  }));
  const bars = paretoBars(byLine, 10);
  assert.equal(bars.length, 11);
  assert.equal(bars[0].label, "Chip resistors · ESC");
  assert.equal(bars[1].label, "Chip resistors · FC");
  assert.equal(bars[2].label, "Part 2");
  assert.equal(bars[10].label, "Other (2 lines)");
  assert.equal(bars[10].rate, 3);
  assert.deepEqual(paretoBars([]), []);
});

test("the CSV of the lines", () => {
  const csv = linesCsv({ lines: [
    { name: "D1", reference: "D-1", assembly_label: "Power", quantity: 2, part_type: "Diode", record_id: "r1",
      base_rate_per_million_hours: 0.0038, environment_factor: 6, quality_factor: 1, assigned: true,
      rate_per_million_hours: 0.0456, rate_per_hour: 4.56e-8, share: 1 },
    { name: "Motor", reference: "", assembly_label: "", quantity: 4, assigned: false, quality_factor: 1 },
  ] });
  const rows = csv.split("\n");
  assert.equal(rows[0].split(",")[0], "Part");
  assert.equal(rows[1], "D1,D-1,Power,2,Diode,r1,0.0038,6,1,0.0456,4.56e-8,1");
  assert.equal(rows[2], "Motor,,,4,,,,,,,,");
  assert.equal(csvFileName("Survey quadcopter (sample)"), "survey-quadcopter-sample-parts-count.csv");
  assert.equal(csvFileName(""), "prediction-parts-count.csv");
});

test("the factors in words name what a parts-count rate holds at the handbook's defaults", () => {
  const text = factorsText({
    applied: [{ symbol: "λb" }, { symbol: "πE" }, { symbol: "πQ" }, { symbol: "λg" }],
    not_applied: [{ symbol: "πT", name: "temperature" }],
    held_at_defaults: [{ symbol: "πL", name: "learning", held_at: "1" }],
  });
  assert.equal(text, "Applied: λb, πE, πQ, λg. Not applied: πT (temperature). "
    + "Held at the handbook's defaults in the generic rates: πL (learning).");
});

test("which of the three a parts-list line uses", () => {
  assert.equal(partTypeMode({ excluded: true, record: { id: "r" } }), "excluded");
  assert.equal(partTypeMode({ record: { id: "r" }, rate: "3" }), "type");
  assert.equal(partTypeMode({ rate: "3" }), "rate");
  assert.equal(partTypeMode({ rateMode: true }), "rate");
  assert.equal(partTypeMode({ rate: " " }), "type");
  assert.equal(partTypeMode(), "type");
});
