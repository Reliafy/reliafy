import test from "node:test";
import assert from "node:assert/strict";
import { checkRows, checksTone, pText } from "./modelChecks.js";

const mc = {
  available: true,
  rows: [
    { check: "a", title: "A", covariates: ["z"], verdict: "ok", p: 0.4, detail: "fine" },
    { check: "b", title: "B", covariates: [], verdict: "fail", p: 0.0001, detail: "bad" },
    { check: "c", title: "C", covariates: ["z", "w"], verdict: "warn", p: null, detail: "hmm" },
  ],
};

test("tone is the worst verdict", () => {
  assert.equal(checksTone(mc), "bad");
  assert.equal(checksTone({ available: true, rows: [mc.rows[0], mc.rows[2]] }), "caveat");
  assert.equal(checksTone({ available: true, rows: [mc.rows[0]] }), "good");
  assert.equal(checksTone({ available: false }), undefined);
  assert.equal(checksTone(null), undefined);
});

test("rows put problems first and read in words", () => {
  const rows = checkRows(mc);
  assert.deepEqual(rows.map((r) => r.verdictLabel), ["Fails", "Borderline", "Passes"]);
  assert.equal(rows[1].covariates, "z, w");
  assert.equal(rows[0].p, "p < 0.001");
  assert.equal(rows[1].p, "");
});

test("p-values", () => {
  assert.equal(pText(0.0123), "p = 0.012");
  assert.equal(pText(0.004), "p = 0.0040");
  assert.equal(pText(undefined), "");
});

test("checkRows: category terms in plain words", () => {
  const rows = checkRows({ available: true, rows: [{ check: "influence", covariates: ["site[T.North]"], verdict: "ok" }] });
  assert.equal(rows[0].covariates, "site = North");
});

test("phDisagreement: the drift test flags a covariate the model's own step check passes", async () => {
  const { phDisagreement } = await import("./modelChecks.js");
  const ph = { available: true, alpha: 0.05, rows: [{ covariate: "load_kN", p: 0.0428 }, { covariate: "dusty", p: 0.76 }] };
  const mc = { available: true, rows: [
    { check: "proportional_hazards", covariates: ["load_kN"], verdict: "ok", p: 0.501 },
    { check: "proportional_hazards", covariates: ["dusty"], verdict: "ok", p: 0.8 },
  ] };
  const text = phDisagreement(ph, mc);
  assert.match(text, /For load_kN, this test sees a slow drift over time \(p = 0\.043\)/);
  assert.match(text, /no jump at the median failure time \(p = 0\.501\)/);
  assert.equal(phDisagreement({ ...ph, rows: [{ covariate: "load_kN", p: 0.3 }] }, mc), null);
});
