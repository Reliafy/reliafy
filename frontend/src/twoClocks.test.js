import { test } from "node:test";
import assert from "node:assert/strict";
import { bLife, kWords, lifeText, parseRate, rateText } from "./twoClocks.js";

test("a rate is read as starts per hour, or as 1 start every so many hours", () => {
  assert.deepEqual(parseRate("0.125"), { rate: 0.125 });
  assert.deepEqual(parseRate("1/8"), { rate: 0.125 });
  assert.deepEqual(parseRate("every 8"), { rate: 0.125 });
  assert.deepEqual(parseRate("0"), { rate: 0 });
  assert.match(parseRate("").error, /starts per hour/);
  assert.match(parseRate("-1").error, /negative/);
  assert.match(parseRate("fast").error, /number/);
  assert.match(parseRate("1/0").error, /above 0/);
});

test("the rate box round-trips the server's rate", () => {
  assert.equal(rateText(1 / 16), "0.0625");
  assert.equal(rateText(0.00998), "0.00998");
  assert.equal(rateText(null), "");
});

test("a B-life is said with its 90% lower bound and unit", () => {
  const at = { life: { b_lives: [{ label: "B10", value: 6294.1, lower: 5812.4 }] } };
  assert.equal(lifeText(bLife(at, "B10"), "hours"), "6,290 hours (at least 5,810 hours)");
  assert.equal(lifeText(bLife(at, "B1"), "hours"), "—");
});

test("k is read in plain words with its range", () => {
  const r = { clocks: { second_one: "start", first_word: "hours" },
              params: [{ name: "k", value: 18.37, ci: [14.82, 22.77] }] };
  assert.equal(kWords(r), "One start wears it as much as 18.4 hours of running (90% range 14.8–22.8).");
});
