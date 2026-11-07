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
