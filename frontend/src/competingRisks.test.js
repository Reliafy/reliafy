import test from "node:test";
import assert from "node:assert/strict";
import {
  ANY_MODE, anyAt, causesAt, effectSentence, effectsByMode, firstReach, incidenceRows, leadSentence, modeSupport, pct,
  readingAt, stepAt, timeToChance, widestBand,
} from "./competingRisks.js";

// A fit payload's shape (backend/competing_risks.py), with round numbers.
const RESULT = {
  causes: [{ name: "bearing wear", failures: 29 }, { name: "seal leak", failures: 15 }],
  curves: {
    x: [0, 100, 1000, 3000, 5000],
    cif: { "bearing wear": [0, 0, 0.1, 0.3, 0.4], "seal leak": [0, 0.05, 0.1, 0.2, 0.2] },
    lower: { "bearing wear": [null, null, 0.05, 0.2, 0.28], "seal leak": [null, 0.01, 0.05, 0.12, 0.12] },
    upper: { "bearing wear": [null, null, 0.2, 0.41, 0.52], "seal leak": [null, 0.15, 0.2, 0.3, 0.31] },
  },
  leads: [{ cause: "seal leak", from: 100 }, { cause: "bearing wear", from: 2810 }],
};

test("stepAt reads a right-continuous step curve", () => {
  const x = [0, 10, 20];
  const y = [0, 0.5, 0.8];
  assert.equal(stepAt(x, y, 0), 0);
  assert.equal(stepAt(x, y, 9.99), 0);
  assert.equal(stepAt(x, y, 10), 0.5);
  assert.equal(stepAt(x, y, 15), 0.5);
  assert.equal(stepAt(x, y, 1e6), 0.8);
  assert.equal(stepAt(x, y, -1), 0);
  assert.equal(stepAt([], [], 3), null);
  assert.equal(stepAt(x, y, Number.NaN), null);
});

test("causesAt gives each mode's incidence, bounds and share of the failures", () => {
  const rows = causesAt(RESULT, 4000);
  assert.deepEqual(rows.map((r) => r.name), ["bearing wear", "seal leak"]);
  assert.equal(rows[0].cif, 0.3);
  assert.equal(rows[0].lower, 0.2);
  assert.ok(Math.abs(rows[0].share - 0.6) < 1e-12);
  assert.ok(Math.abs(rows[1].share - 0.4) < 1e-12);
  assert.equal(causesAt(RESULT, 0)[0].share, null);
});

test("readingAt says which mode causes most failures, as the backend does", () => {
  assert.equal(
    readingAt(RESULT, 5000, "hours"),
    "Bearing wear causes 67% of failures by 5,000 hours: 40% of units fail from it by then "
      + "(we're 95% sure it's between 28% and 52%).",
  );
  assert.equal(readingAt(RESULT, 50, "hours"), "No unit has failed by 50 hours.");
  const one = { ...RESULT, causes: [RESULT.causes[0]] };
  assert.match(readingAt(one, 5000), /^Every failure is bearing wear: 40% of units/);
  assert.equal(pct(0.062), "6.2%");
  assert.equal(pct(null), "—");
});

test("leadSentence words a change of lead, and nothing when one mode leads", () => {
  assert.equal(leadSentence(RESULT.leads, "hours"), "Seal leak leads early; bearing wear overtakes it at about 2,810 hours.");
  assert.equal(leadSentence([RESULT.leads[0]]), "");
});

test("effectSentence names the ratio's meaning per model", () => {
  const c = { cause: "bearing wear", covariate: "duty_pct", ratio: 1.1335 };
  assert.equal(effectSentence(c, "hazard ratio"), "Each +1 in duty_pct multiplies the bearing wear failure rate by 1.13");
  assert.equal(effectSentence(c, "subdistribution hazard ratio"),
    "Each +1 in duty_pct multiplies the chance of failing from bearing wear by 1.13");
});

// The calculator and the checks read the same stored curves.
const FULL = {
  ...RESULT,
  horizon: 5000,
  causes: [
    { name: "bearing wear", failures: 29, at: { cif: 0.4, lower: 0.28, upper: 0.52 } },
    { name: "seal leak", failures: 3, at: { cif: 0.2, lower: 0.12, upper: 0.31 } },
  ],
  curves: { ...RESULT.curves, all: [0, 0.05, 0.2, 0.5, 0.6], all_lower: [0, 0.01, 0.1, 0.4, 0.5],
            all_upper: [0, 0.1, 0.3, 0.6, 0.7] },
};

test("anyAt reads the chance of failing from any mode, with its band", () => {
  assert.deepEqual(anyAt(FULL, 3000), { cif: 0.5, lower: 0.4, upper: 0.6 });
  assert.deepEqual(anyAt({}, 3000), { cif: null, lower: null, upper: null });
});

test("firstReach finds the first stored time at or above a chance", () => {
  assert.equal(firstReach([0, 10, 20], [0, 0.1, 0.3], 0.1), 10);
  assert.equal(firstReach([0, 10, 20], [null, 0.1, 0.3], 0.2), 20);
  assert.equal(firstReach([0, 10, 20], [0, 0.1, 0.3], 0.5), null);
});

test("timeToChance gives the time to a share failed, its 95% range, or how far it gets", () => {
  // Bearing wear: 30% at 3,000 (the upper band reaches 30% at 3,000 too, the
  // lower one at... never: 28% at most).
  assert.deepEqual(timeToChance(FULL, "bearing wear", 0.1),
    { time: 1000, lower: 1000, upper: 3000, top: 0.4, last: 5000 });
  assert.deepEqual(timeToChance(FULL, ANY_MODE, 0.5),
    { time: 3000, lower: 3000, upper: 5000, top: 0.6, last: 5000 });
  const never = timeToChance(FULL, "seal leak", 0.5);
  assert.equal(never.time, null);
  assert.equal(never.top, 0.2);
  assert.equal(never.last, 5000);
});

test("modeSupport flags a mode resting on few failures; widestBand names the least certain", () => {
  const s = modeSupport(FULL);
  assert.equal(s.tone, "caveat");
  assert.match(s.words, /^Seal leak rests on fewer than 5 failures/);
  assert.equal(s.rows[0].few, false);
  assert.ok(Math.abs(s.rows[0].width - 0.24) < 1e-9);
  assert.equal(modeSupport({ causes: [{ name: "a", failures: 12, at: {} }] }).tone, "good");
  assert.equal(widestBand(FULL, "hours"), "Bearing wear is the least certain: between 28% and 52% of units by 5,000 hours.");
  assert.equal(widestBand({ causes: [{ name: "a", failures: 1, at: { cif: 0.1 } }] }), "");
});

test("incidenceRows keeps the times where a curve steps", () => {
  const rows = incidenceRows(FULL);
  assert.deepEqual(rows.map((r) => r.x), [100, 1000, 3000, 5000]);
  assert.deepEqual(rows[0], { x: 100, modes: [0, 0.05], any: 0.05 });
});

test("effectsByMode words each mode's coefficients, with the interval", () => {
  const out = effectsByMode({
    ratio_label: "hazard ratio",
    coefficients: [
      { cause: "bearing wear", covariate: "duty_pct", ratio: 1.14, ratio_ci: [1.08, 1.21], p_value: 0.0001 },
      { cause: "seal leak", covariate: "duty_pct", ratio: 0.973, ratio_ci: [0.932, 1.02], p_value: 0.22 },
    ],
  });
  assert.equal(out.length, 2);
  assert.equal(out[0].lines[0].text,
    "Each +1 in duty_pct multiplies the bearing wear failure rate by 1.14 (95% 1.08 to 1.21).");
  assert.match(out[1].lines[0].text, /can't rule out no effect\.$/);
  assert.deepEqual(effectsByMode(null), []);
});
