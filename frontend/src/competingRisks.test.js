import test from "node:test";
import assert from "node:assert/strict";
import { causesAt, effectSentence, leadSentence, pct, readingAt, stepAt } from "./competingRisks.js";

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
