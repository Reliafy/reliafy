import { test } from "node:test";
import assert from "node:assert/strict";
import { checkPercent, keepAsTyped, percentApiMessage, percentFraction, percentsReady, RANGE_MESSAGE } from "./percent.js";

test("a percentage converts to a fraction", () => {
  assert.deepEqual(checkPercent("95"), { state: "ok", fraction: 0.95, percent: 95 });
  assert.equal(percentFraction("99.9"), 0.999);
  assert.equal(percentFraction(" 50 % "), 0.5);
});

test("outside 0–100 is an error in percent, never in fractions", () => {
  for (const v of ["150", "100", "0", "-5"]) {
    const c = checkPercent(v);
    assert.equal(c.state, "error", v);
    assert.equal(c.message, RANGE_MESSAGE);
    assert.doesNotMatch(c.message, /0 and 1\b/);
  }
  assert.equal(checkPercent("100", { allowMax: true }).state, "ok");
  assert.equal(checkPercent("abc").state, "error");
});

test("blank is an error unless optional", () => {
  assert.equal(checkPercent("").state, "error");
  assert.equal(checkPercent("", { optional: true }).state, "empty");
  assert.equal(percentFraction("", { optional: true }), null);
});

test("a value of 1 or less asks whether it was a fraction", () => {
  const c = checkPercent("0.99");
  assert.equal(c.state, "confirm");
  assert.equal(c.message, "Did you mean 99%?");
  assert.equal(c.suggestion, "99");
  assert.equal(percentFraction("0.99"), null);
  assert.equal(checkPercent("0.95").suggestion, "95");
  assert.equal(checkPercent("0.999").suggestion, "99.9");
  // 1 would mean 100%: no suggestion, but still asked.
  const one = checkPercent("1");
  assert.equal(one.state, "confirm");
  assert.equal(one.suggestion, null);
});

test("typing the % sign keeps a small value", () => {
  assert.equal(keepAsTyped("0.99"), "0.99%");
  assert.equal(keepAsTyped("0.99%"), "0.99%");
  assert.equal(percentFraction(keepAsTyped("0.99")), 0.0099);
});

test("fields where small percentages are normal skip the question", () => {
  assert.equal(percentFraction("1", { fractionCheck: false }), 0.01);
  assert.equal(percentFraction("0.1", { fractionCheck: false }), 0.001);
});

test("percentsReady needs every field usable", () => {
  assert.equal(percentsReady(checkPercent("95"), checkPercent("", { optional: true })), true);
  assert.equal(percentsReady(checkPercent("95"), checkPercent("0.9")), false);
  assert.equal(percentsReady(checkPercent("150")), false);
});

test("backend fraction messages are reworded in percent", () => {
  assert.equal(percentApiMessage("reliability must be strictly between 0 and 1 (e.g. 0.95); got 1.5"), RANGE_MESSAGE);
  assert.equal(percentApiMessage("target_availability must be strictly between 0 and 1 (e.g. 0.99)"), RANGE_MESSAGE);
  assert.equal(percentApiMessage("Units must be at least 2"), "Units must be at least 2");
});
