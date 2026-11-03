import test from "node:test";
import assert from "node:assert/strict";
import { bandLabel, defaultPicks, elapsedFor, fmt, fmtBytes, frameAt, fromOrders, holds, offsets, toOrders } from "./signals.js";

const H = 3600e3;
// Three snapshots an hour apart, then one a day later: unequal gaps.
const T = [0, 1 * H, 2 * H, 26 * H];

test("hold time is proportional to the real gap over a fixed loop", () => {
  const h = holds(T, 2000);
  assert.deepEqual(h.map((v) => Math.round(v)), [77, 77, 1846, 0]);
  assert.equal(Math.round(h.reduce((a, b) => a + b, 0)), 2000);
  assert.deepEqual(offsets(T, 2000).map(Math.round), [0, 77, 154, 2000]);
  // Same times, a loop twice as long: every hold doubles.
  assert.deepEqual(holds(T, 4000).map(Math.round), [154, 154, 3692, 0]);
});

test("play once steps and stops on the latest", () => {
  const f = (ms) => frameAt(T, ms, { loopMs: 2000 });
  assert.equal(f(0).index, 0);
  assert.equal(f(76).index, 0);
  assert.equal(f(78).index, 1);
  assert.equal(f(160).index, 2);
  assert.equal(f(1999).index, 2); // held until the last is due
  assert.deepEqual([f(2000).index, f(2000).done], [3, true]);
  assert.deepEqual([f(99999).index, f(99999).done], [3, true]);
});

test("loop mode rests a quarter of the loop on the last, then wraps with a cue", () => {
  const f = (ms) => frameAt(T, ms, { loopMs: 2000, loop: true });
  assert.equal(f(1999).index, 2);
  assert.deepEqual([f(2000).index, f(2000).resting], [3, true]);
  assert.deepEqual([f(2499).index, f(2499).resting], [3, true]);
  const wrapped = f(2500);
  assert.deepEqual([wrapped.index, wrapped.wrapped, wrapped.cycle, wrapped.resting], [0, true, 1, false]);
  assert.equal(f(2500 + 600).wrapped, false);
  assert.equal(f(2500 + 600).index, 2); // 600 ms in
  assert.equal(f(0).wrapped, false); // the first start has no cue
});

test("one snapshot, none, or all at one time", () => {
  assert.equal(frameAt([], 0).index, -1);
  assert.deepEqual([frameAt([5], 10).index, frameAt([5], 10).done], [0, true]);
  assert.deepEqual(offsets([7, 7, 7], 1000), [0, 500, 1000]);
  assert.equal(elapsedFor(T, 3, 2000), 2000);
});

test("orders and band labels", () => {
  assert.equal(toOrders(50, 3000), 1);
  assert.equal(fromOrders(2, 1500), 50);
  assert.equal(toOrders(50, 0), null);
  assert.equal(bandLabel({ type: "band", low: 45, high: 55, in: "Hz", axis: "X" }), "45 to 55 Hz (X)");
  assert.equal(bandLabel({ type: "band", low: 0.9, high: 1.1, in: "orders", axis: "Y" }), "0.9 to 1.1 × running speed (Y)");
  assert.equal(bandLabel({ type: "level", stat: "rms", axis: "Z" }), "rms of Z");
});

test("numbers are rounded sensibly", () => {
  assert.equal(fmt(0.353553390593), "0.354");
  assert.equal(fmt(1234.5678), "1230");
  assert.equal(fmt(null), "–");
  assert.equal(fmt(Infinity), "–");
  assert.equal(fmtBytes(1200), "1 kB");
  assert.equal(fmtBytes(12_400_000), "12.4 MB");
});

test("defaults: the latest snapshot and a running baseline", () => {
  const idx = [{ id: "a", running: false }, { id: "b", running: true }, { id: "c", running: true }];
  assert.deepEqual(defaultPicks(idx), { picked: ["c"], baseline: "b" });
  assert.deepEqual(defaultPicks([{ id: "a" }]), { picked: ["a"], baseline: null });
  assert.deepEqual(defaultPicks([]), { picked: [], baseline: null });
});
