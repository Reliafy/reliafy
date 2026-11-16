import { test } from "node:test";
import assert from "node:assert/strict";
import {
  bLife, clockWords, cleanUnit, defaultSecondUnit, kTestWords, kWords, lifeText, parseRate, pluralUnit, rateHint,
  rateLabel, rateText,
} from "./twoClocks.js";
import { lifeMapping, readingParts, secondClockUnit, setRole } from "./datasetReading.js";
import { mappingColumns, mappingFields, savedMapping } from "./lifeData.js";

test("a rate is read as starts per hour, or as 1 start every so many hours (a model saved before units)", () => {
  assert.deepEqual(parseRate("0.125"), { rate: 0.125 });
  assert.deepEqual(parseRate("1/8"), { rate: 0.125 });
  assert.deepEqual(parseRate("every 8"), { rate: 0.125 });
  assert.deepEqual(parseRate("0"), { rate: 0 });
  assert.match(parseRate("").error, /starts per hour/);
  assert.match(parseRate("-1").error, /negative/);
  assert.match(parseRate("fast").error, /number/);
  assert.match(parseRate("1/0").error, /above 0/);
});

test("the rate box speaks the model's own units: landings per flight hour", () => {
  const w = clockWords(null, "flight hours", "landing");
  assert.equal(w.second_word, "landings");
  assert.equal(w.second_one, "landing");
  assert.equal(w.first_one, "flight hour");
  assert.equal(rateLabel(w), "Landings per flight hour");
  assert.equal(rateHint(w), "0.125 is 1 landing every 8 flight hours; 1/8 works too.");
  assert.equal(parseRate("", w).error, "Enter landings per flight hour, e.g. 0.125 (1 landing every 8 flight hours).");
  assert.match(parseRate("-2", w).error, /^Landings per flight hour can't be negative/);
  assert.doesNotMatch(JSON.stringify([parseRate("", w), parseRate("x", w), parseRate("1/0", w)]), /start/);
});

test("the server's words win over the defaults", () => {
  const server = { first_word: "hours", first_one: "hour", second_word: "cycles", second_one: "cycle",
                   rate_unit: "cycles per hour" };
  assert.equal(clockWords(server, "km", "shots"), server);
  assert.equal(rateLabel(server), "Cycles per hour");
});

test("units: typed singular reads plural; the column name gives the default", () => {
  assert.equal(pluralUnit("cycle"), "cycles");
  assert.equal(pluralUnit("cycles"), "cycles");
  assert.equal(pluralUnit("km"), "km");
  assert.equal(pluralUnit("kWh"), "kWh");
  assert.equal(cleanUnit("  landing  "), "landings");
  assert.equal(defaultSecondUnit("starts"), "starts");
  assert.equal(defaultSecondUnit("Landings"), "landings");
  assert.equal(defaultSecondUnit("num_cycles"), "cycles");
  assert.equal(defaultSecondUnit("StartCount"), "starts");
  assert.equal(defaultSecondUnit("Distance (km)"), "km");
  assert.equal(defaultSecondUnit("x2"), "uses");
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

test("k is read in plain words with its range, in the model's units", () => {
  const r = { clocks: { second_one: "start", first_word: "hours" },
              params: [{ name: "k", value: 18.37, ci: [14.82, 22.77] }] };
  assert.equal(kWords(r), "One start wears it as much as 18.4 hours (90% range 14.8–22.8).");
  const cycles = { unit: "Hours", second_unit: "cycles", params: [{ name: "k", value: 1, ci: [null, null] }] };
  assert.equal(kWords(cycles), "One cycle wears it as much as 1 hour.");
  const p = (v) => String(v);
  assert.equal(kTestWords({ ...cycles, k_test: { matters: true, p_value: 0.001 } }, p),
               "Cycles clearly matter: the test that they don't gives p 0.001.");
  assert.equal(kTestWords({ ...cycles, k_test: { matters: false, p_value: 0.4 } }, p),
               "The data can't tell cycles from no effect (p 0.4): hours alone may do.");
});

test("a model saved before units says starts", () => {
  const old = { unit: "Hours", clocks: { first: "hours", second: "Start count" },
                params: [{ name: "k", value: 2, ci: [1, 3] }] };
  assert.equal(kWords(old), "One start wears it as much as 2 hours (90% range 1–3).");
});

test("the reading keeps the second clock's unit, defaulted from its column, and sends it to the fit", () => {
  const facts = { hours: { dtype: "int64" }, landings: { dtype: "int64" }, status: { dtype: "int64" } };
  let r = setRole({ x: "hours", c: "status", x2: "", x2_unit: "", z: [], not_used: [] }, "x2", "landings", facts, 10);
  assert.equal(r.x2_unit, "landings");
  assert.equal(secondClockUnit({ x2: "landings", x2_unit: "" }), "landings");
  assert.equal(secondClockUnit({ x2: "lnd", x2_unit: "landing" }), "landings");
  r = { ...r, x2_unit: "deck landings" };
  const m = lifeMapping(r);
  assert.equal(m.x2, "landings");
  assert.equal(m.x2_unit, "deck landings");
  assert.deepEqual(Object.fromEntries(mappingFields(m).filter(([f]) => f.startsWith("x2"))), { x2: "landings", x2_unit: "deck landings" });
  assert.ok(!mappingColumns(m).includes("deck landings"));
  assert.deepEqual(readingParts(r).find((p) => p.key === "x2"), { key: "x2", label: "second clock", value: "landings (deck landings)" });
  // A unit is never read as a column: a refit's saved mapping still matches the dataset.
  const saved = savedMapping({ mapping: { x: "hours", c: "status", x2: "landings", x2_unit: "cycles" } },
                             ["hours", "status", "landings"]);
  assert.equal(saved.mapping.x2, "landings");
});
