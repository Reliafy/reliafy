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

// ---- slice 2 ----

import {
  convertRange, dropStopped, fadeWeights, hzRange, isStopped, limitLines, localToIso, parseCsv, parseJsonSnapshots,
  parseWav, runningOnly, sizeProblem, snapshotBody, thinWave, trimAxes, xFor,
} from "./signals.js";

function wavBuffer({ rate = 8000, channels = 1, samples = [0, 16384, -16384, 32767] } = {}) {
  const bytes = samples.length * 2;
  const b = new ArrayBuffer(44 + bytes);
  const v = new DataView(b);
  const s = (o, t) => [...t].forEach((c, i) => v.setUint8(o + i, c.charCodeAt(0)));
  s(0, "RIFF"); v.setUint32(4, 36 + bytes, true); s(8, "WAVE"); s(12, "fmt ");
  v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, channels, true); v.setUint32(24, rate, true);
  v.setUint32(28, rate * channels * 2, true); v.setUint16(32, channels * 2, true); v.setUint16(34, 16, true);
  s(36, "data"); v.setUint32(40, bytes, true);
  samples.forEach((x, i) => v.setInt16(44 + i * 2, x, true));
  return b;
}

test("a WAV file gives its sample rate, channels as axes, and values as fractions of full scale", () => {
  const out = parseWav(wavBuffer({ rate: 12800, channels: 2, samples: [0, 16384, 16384, 0, -16384, 32767] }));
  assert.equal(out.sampleRate, 12800);
  assert.deepEqual(Object.keys(out.axes), ["1", "2"]);
  assert.equal(out.axes["1"].length, 3);
  assert.equal(out.axes["1"][1], 0.5);
  assert.ok(Math.abs(out.axes["2"][2] - 32767 / 32768) < 1e-9);
  assert.throws(() => parseWav(new ArrayBuffer(100)), /WAV/);
});

test("a CSV gives axes by column, names from a header, and a sample rate from an even time column", () => {
  const plain = parseCsv("0.1,0.2\n0.3,0.4\n0.5,0.6");
  assert.deepEqual(plain.axes, { 1: [0.1, 0.3, 0.5], 2: [0.2, 0.4, 0.6] });
  assert.equal(plain.sampleRate, null);
  const timed = parseCsv("time,X,Y\n0,1,2\n0.001,3,4\n0.002,5,6");
  assert.deepEqual(Object.keys(timed.axes), ["X", "Y"]);
  assert.equal(timed.sampleRate, 1000);
  assert.throws(() => parseCsv("1,2\n3,x"), /Row 2, column 2/);
  assert.throws(() => parseCsv("1,2\n3"), /same number of columns/);
});

test("a JSON file may hold one snapshot, a batch or a list; bad JSON is explained", () => {
  assert.equal(parseJsonSnapshots('{"time":"2026-01-01T00:00:00Z"}').length, 1);
  assert.equal(parseJsonSnapshots('{"snapshots":[{},{}]}').length, 2);
  assert.throws(() => parseJsonSnapshots("{oops"), /isn't valid JSON/);
  assert.throws(() => parseJsonSnapshots("[1,2]"), /one snapshot like/);
});

test("too many numbers is explained in plain words with what would fit", () => {
  const axes = { X: new Array(300000).fill(0), Y: new Array(300000).fill(0) };
  const p = sizeProblem(axes);
  assert.equal(p.total, 600000);
  assert.equal(p.fits, 250000);
  assert.match(p.message, /600,000 numbers/);
  assert.match(p.message, /first 250,000 samples/);
  assert.equal(sizeProblem({ X: [1, 2, 3] }), null);
  assert.equal(trimAxes(axes, 10).X.length, 10);
});

test("a long waveform is thinned but keeps its extremes", () => {
  const x = Array.from({ length: 10000 }, (_, i) => (i === 5000 ? 9 : Math.sin(i / 10)));
  const t = thinWave(x, 400);
  assert.ok(t.y.length <= 500);
  assert.ok(t.y.includes(9));
});

test("the snapshot body takes the form's choices", () => {
  const b = snapshotBody({ channelId: "c1", time: "2026-01-01T00:00:00.000Z", axes: { X: [1, 2] }, sampleRate: "3200", scale: 2, rpm: "1500", running: "no", note: "n" });
  assert.deepEqual(b, { channel_id: "c1", time: "2026-01-01T00:00:00.000Z", axes: { X: [2, 4] }, sample_rate: 3200, rpm: 1500, running: false, note: "n" });
  assert.equal("running" in snapshotBody({ channelId: "c", time: "t", axes: {}, sampleRate: 1, running: "unknown" }), false);
  assert.equal(localToIso(""), null);
  assert.match(localToIso("2026-11-03T10:00"), /^2026-11-0\d/);
});

test("orders: x values and zoom ranges follow each snapshot's speed", () => {
  assert.deepEqual(xFor([0, 25, 50], 1500, "orders"), [0, 1, 2]);
  assert.deepEqual(xFor([0, 25], 1500, "Hz"), [0, 25]);
  assert.equal(xFor([1], null, "orders"), null);
  assert.deepEqual(hzRange(0.5, 2, 1500, "orders"), { f_min: 12.5, f_max: 50 });
  assert.deepEqual(hzRange(5, 9, null, "Hz"), { f_min: 5, f_max: 9 });
  assert.equal(hzRange(1, 2, 0, "orders"), null);
  assert.deepEqual(convertRange({ low: 25, high: 50 }, "Hz", "orders", 1500), { low: 1, high: 2 });
  assert.deepEqual(convertRange({ low: 1, high: 2 }, "orders", "Hz", 1500), { low: 25, high: 50 });
  assert.equal(convertRange({ low: 1, high: 2 }, "orders", "Hz", null), null);
});

test("running only drops stopped snapshots (and their band values), keeps unknown ones", () => {
  const index = [{ id: "a", t: "2026-01-01T00:00:00Z", running: true }, { id: "b", t: "2026-01-02T00:00:00Z", running: false },
    { id: "c", t: "2026-01-03T00:00:00Z", running: null }];
  assert.equal(isStopped(index[1]), true);
  assert.deepEqual(runningOnly(index, true).map((s) => s.id), ["a", "c"]);
  assert.equal(runningOnly(index, false).length, 3);
  const series = index.map((s, i) => ({ t: s.t, value: i }));
  assert.deepEqual(dropStopped(series, index, true).map((p) => p.value), [0, 2]);
  assert.equal(dropStopped(series, index, false).length, 3);
});

test("the fade starts late in a hold and never invents a spectrum", () => {
  assert.deepEqual(fadeWeights(0.5), { current: 1, next: 0 });
  assert.deepEqual(fadeWeights(1), { current: 0, next: 1 });
  const mid = fadeWeights(0.875);
  assert.ok(Math.abs(mid.current - 0.5) < 1e-9 && Math.abs(mid.next - 0.5) < 1e-9);
  const f = frameAt([0, 1000, 3000], 500, { loopMs: 2000 });
  assert.ok(f.progress >= 0 && f.progress <= 1);
});

test("limit lines name their kind in words as well as colour", () => {
  const lines = limitLines({ warn_above: 0.3, alarm_above: 0.5, alarm_below: null });
  assert.deepEqual(lines.map((l) => l.kind), ["warn", "alarm"]);
  assert.match(lines[1].label, /^Alarm above 0.5/);
  assert.deepEqual(limitLines(null), []);
});

test("a channel's link opens its own page (the Signals tab is hidden), at its bands when asked", async () => {
  const { channelPath } = await import("./signals.js");
  // In the Explorer's Measurements tab, its position picked; a bare id goes to the old address (it redirects).
  assert.equal(channelPath({ id: "c1", position: { id: "p1" } }), "/asset-register/explorer?arrange=positions&sel=p1&tab=measurements&channel=c1");
  assert.equal(channelPath({ id: "c1", position: { id: "p1" } }, { bands: true }).endsWith("&channel=c1#bands"), true);
  assert.equal(channelPath("c 2", { bands: true }), "/asset-register/channels/c%202#bands");
});
