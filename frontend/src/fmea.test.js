import { test } from "node:test";
import assert from "node:assert/strict";
import {
  AP_LABEL, apOf, bandOf, bandWords, byCriticality, cmOf, cmWords, crOf, fmt3, matrixOf, readFmeaOptions, rpnOf, score,
} from "./fmea.js";

// The action priority table as the server sends it in /rcm/options (its own
// writing of the public AIAG-VDA 2019 rule): the bands, and the answer per
// band triple, nested. The hand cases below are the contract's.
const TABLE = {
  s9: { o8: { d7: "H", d5: "H", d2: "H", d1: "H" }, o6: { d7: "H", d5: "H", d2: "H", d1: "H" }, o4: { d7: "H", d5: "H", d2: "H", d1: "M" },
    o2: { d7: "H", d5: "M", d2: "L", d1: "L" }, o1: { d7: "L", d5: "L", d2: "L", d1: "L" } },
  s7: { o8: { d7: "H", d5: "H", d2: "H", d1: "H" }, o6: { d7: "H", d5: "H", d2: "H", d1: "M" }, o4: { d7: "H", d5: "M", d2: "M", d1: "M" },
    o2: { d7: "M", d5: "M", d2: "L", d1: "L" }, o1: { d7: "L", d5: "L", d2: "L", d1: "L" } },
  s4: { o8: { d7: "H", d5: "H", d2: "M", d1: "M" }, o6: { d7: "M", d5: "M", d2: "M", d1: "L" }, o4: { d7: "M", d5: "L", d2: "L", d1: "L" },
    o2: { d7: "L", d5: "L", d2: "L", d1: "L" }, o1: { d7: "L", d5: "L", d2: "L", d1: "L" } },
  s2: { o8: { d7: "M", d5: "M", d2: "L", d1: "L" }, o6: { d7: "L", d5: "L", d2: "L", d1: "L" }, o4: { d7: "L", d5: "L", d2: "L", d1: "L" },
    o2: { d7: "L", d5: "L", d2: "L", d1: "L" }, o1: { d7: "L", d5: "L", d2: "L", d1: "L" } },
  s1: { o8: { d7: "L", d5: "L", d2: "L", d1: "L" }, o6: { d7: "L", d5: "L", d2: "L", d1: "L" }, o4: { d7: "L", d5: "L", d2: "L", d1: "L" },
    o2: { d7: "L", d5: "L", d2: "L", d1: "L" }, o1: { d7: "L", d5: "L", d2: "L", d1: "L" } },
};
const BANDS = {
  severity: [{ id: "s9", min: 9, max: 10 }, { id: "s7", min: 7, max: 8 }, { id: "s4", min: 4, max: 6 }, { id: "s2", min: 2, max: 3 }, { id: "s1", min: 1, max: 1 }],
  occurrence: [{ id: "o8", min: 8, max: 10 }, { id: "o6", min: 6, max: 7 }, { id: "o4", min: 4, max: 5 }, { id: "o2", min: 2, max: 3 }, { id: "o1", min: 1, max: 1 }],
  detection: [{ id: "d7", min: 7, max: 10 }, { id: "d5", min: 5, max: 6 }, { id: "d2", min: 2, max: 4 }, { id: "d1", min: 1, max: 1 }],
};
export const OPTIONS = { ap_table: TABLE, ap_bands: BANDS, scales: { severity: ["No effect", "", "", "", "", "", "", "", "", "Hazardous, no warning"] } };
const opts = readFmeaOptions(OPTIONS);

test("the action priority from the server's table: the contract's hand cases", () => {
  const cases = [
    [10, 10, 10, "H"], [9, 4, 1, "M"], [9, 2, 5, "M"], [9, 2, 3, "L"], [9, 1, 10, "L"], [8, 6, 1, "M"], [7, 4, 5, "M"], [7, 2, 7, "M"],
    [7, 2, 2, "L"], [6, 8, 4, "M"], [5, 6, 1, "L"], [4, 4, 7, "M"], [3, 8, 6, "M"], [3, 8, 2, "L"], [2, 6, 10, "L"], [1, 10, 10, "L"],
  ];
  for (const [s, o, d, ap] of cases) assert.equal(apOf(opts, s, o, d), ap, `(${s},${o},${d})`);
  // Without all three scores, or without the table: none.
  assert.equal(apOf(opts, 9, null, 3), null);
  assert.equal(apOf(opts, 9, 4, ""), null);
  assert.equal(apOf(null, 9, 4, 1), null);
  assert.equal(apOf(readFmeaOptions({}), 9, 4, 1), null);
  assert.equal(AP_LABEL.H, "High");
});

test("the table in the other shapes a JSON API might send: rows, and bands as triples", () => {
  const rows = [];
  for (const [s, os] of Object.entries(TABLE)) for (const [o, ds] of Object.entries(os)) rows.push({ s, o, ...ds });
  const triples = Object.fromEntries(Object.entries(BANDS).map(([k, v]) => [k, v.map((b) => [b.id, b.min, b.max])]));
  const alt = readFmeaOptions({ ap_table: rows, ap_bands: triples });
  assert.equal(apOf(alt, 9, 4, 1), "M");
  assert.equal(apOf(alt, 10, 10, 10), "H");
  const flat = readFmeaOptions({ ap_table: [{ s: "s9", o: "o4", d: "d1", ap: "M" }], ap_bands: { s: BANDS.severity, o: BANDS.occurrence, d: BANDS.detection } });
  assert.equal(apOf(flat, 9, 4, 1), "M");
  assert.equal(apOf(flat, 9, 4, 2), null); // not in the (partial) table
});

test("RPN and the mode criticality, as the contract's cases; blanks give null, never NaN", () => {
  assert.equal(rpnOf(10, 10, 10), 1000);
  assert.equal(rpnOf(9, 4, 6), 216);
  assert.equal(rpnOf(1, 1, 1), 1);
  assert.equal(rpnOf("9", "4", "6"), 216);
  assert.equal(rpnOf(9, 4, null), null);
  assert.equal(rpnOf(9, 4, 11), null);
  assert.equal(rpnOf(9, 4.5, 6), null);
  assert.equal(score("7"), 7);
  assert.equal(score("0"), null);
  assert.equal(score(""), null);
  const a = { loss_probability: 1.0, mode_ratio: 0.6, failure_rate: 2e-5, operating_time: 100 };
  const b = { loss_probability: 0.3, mode_ratio: 0.4, failure_rate: 5e-5, operating_time: 100 };
  assert.ok(Math.abs(cmOf(a) - 1.2e-3) < 1e-12);
  assert.ok(Math.abs(cmOf(b) - 6e-4) < 1e-12);
  assert.equal(cmOf({ ...a, operating_time: null }), null);
  assert.equal(cmOf({ ...a, mode_ratio: "" }), null);
  const cr = crOf([{ ...a, severity_class: "I" }, { ...b, severity_class: "II" }]);
  assert.ok(Math.abs(cr.cr - 1.8e-3) < 1e-12);
  assert.ok(Math.abs(cr.byClass.I - 1.2e-3) < 1e-12);
  assert.equal(crOf([{}]), null);
  // The server's own cm is used when it's there.
  assert.equal(crOf([{ cm: 0.5 }]).cr, 0.5);
});

test("numbers on screen: three significant figures, plainly", () => {
  assert.equal(fmt3(1.2e-3), "0.0012");
  assert.equal(fmt3(0.004), "0.004");
  assert.equal(fmt3(216), "216");
  assert.equal(fmt3(1234.5), "1230");
  assert.equal(fmt3(0.123456), "0.123");
  assert.equal(fmt3(8e-5), "0.00008");
  assert.equal(fmt3(1.23e-7), "1.23e-7");
  assert.equal(fmt3(2e-5), "0.00002");
  assert.equal(fmt3(0), "0");
  assert.equal(fmt3(null), "");
  assert.equal(fmt3("x"), "");
  assert.equal(cmWords({ loss_probability: 1, mode_ratio: 0.6, failure_rate: 2e-5, operating_time: 100 }), "1 × 0.6 × 0.00002 /hours × 100 hours = 0.0012");
});

test("the bands a score falls in, in words", () => {
  assert.equal(bandOf(opts, "severity", 9).id, "s9");
  assert.equal(bandOf(opts, "occurrence", 5).id, "o4");
  assert.equal(bandOf(opts, "detection", 1).id, "d1");
  assert.equal(bandOf(opts, "detection", 0), null);
  assert.equal(bandWords("severity", bandOf(opts, "severity", 9)), "S 9–10");
  assert.equal(bandWords("detection", bandOf(opts, "detection", 1)), "D 1");
});

test("the criticality matrix: severity across (low to high), occurrence down (high at the top), the worst AP per cell", () => {
  const modes = [
    { id: "a", severity: 9, occurrence: 4, detection: 6, ap: "H" },
    { id: "b", severity: 9, occurrence: 5, detection: 1, ap: "M" },
    { id: "c", severity: 2, occurrence: 10, detection: 2, ap: "L" },
    { id: "d", severity: null, occurrence: 3 }, // not scored: left out
  ];
  const m = matrixOf(modes, opts);
  assert.deepEqual(m.cols.map((c) => c.id), ["s1", "s2", "s4", "s7", "s9"]);
  assert.deepEqual(m.rows.map((r) => r.id), ["o8", "o6", "o4", "o2", "o1"]);
  assert.equal(m.scored, 3);
  assert.equal(m.total, 4);
  const cell = (o, s) => m.cells[m.rows.findIndex((r) => r.id === o)][m.cols.findIndex((c) => c.id === s)];
  assert.equal(cell("o4", "s9").n, 2);
  assert.equal(cell("o4", "s9").worst, "H");
  assert.equal(cell("o8", "s2").n, 1);
  assert.equal(cell("o8", "s2").worst, "L");
  assert.equal(cell("o1", "s1").n, 0);
  assert.equal(m.byClass, false);
  // Every scored mode with a class: the classes are the columns, IV … I.
  const byClass = matrixOf(modes.slice(0, 3).map((x, i) => ({ ...x, severity_class: ["I", "II", "IV"][i] })), opts);
  assert.equal(byClass.byClass, true);
  assert.deepEqual(byClass.cols.map((c) => c.id), ["IV", "III", "II", "I"]);
  assert.equal(byClass.cells[2][3].n, 1); // o4 row, class I
  // Without the server's bands: the ten scores are the axes.
  const ten = matrixOf(modes, null);
  assert.equal(ten.cols.length, 10);
  assert.equal(ten.rows[0].id, "10");
  assert.equal(ten.cells[0][1].n, 1); // O 10, S 2
});

test("modes ranked by Cm, highest first, those without one left out", () => {
  const ranked = byCriticality([
    { id: "a", cm: 0.001 }, { id: "b", loss_probability: 1, mode_ratio: 0.5, failure_rate: 8e-5, operating_time: 100 }, { id: "c" },
  ]);
  assert.deepEqual(ranked.map((m) => m.id), ["b", "a"]);
  assert.ok(Math.abs(ranked[0].cm - 0.004) < 1e-12);
});
