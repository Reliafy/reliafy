// Signal channels (Operate › Assets › Explorer › Signals): the small pieces of
// logic behind the spectrum chart and its player, kept apart from the screen so
// they can be tested.

// ---- the player ---------------------------------------------------------------------
//
// The player steps through snapshots and holds each for its share of the real
// time to the next one. The whole history plays in `loopMs` (about 2 s): a
// snapshot taken 30 days before the next is held 30 times longer than one taken
// a day before it. No spectrum is invented between two snapshots; the chart
// holds one until the next is due.

export const DEFAULT_LOOP_MS = 2000;
export const SPEEDS = [0.5, 1, 2, 4];
// Seconds-long cue on the first frame after the loop wraps to the start.
export const WRAP_CUE_MS = 450;

// When each snapshot is due, in ms from the start. `times` are ms since 1970,
// oldest first. Snapshots all at one time are spread evenly.
export function offsets(times, loopMs = DEFAULT_LOOP_MS) {
  const n = times.length;
  if (n < 2) return n ? [0] : [];
  const span = times[n - 1] - times[0];
  if (!(span > 0)) return times.map((_, i) => (loopMs * i) / (n - 1));
  return times.map((t) => (loopMs * (t - times[0])) / span);
}

// How long each snapshot is held, in ms (the last has none: it is where play
// stops, or rests before a loop restarts).
export function holds(times, loopMs = DEFAULT_LOOP_MS) {
  const o = offsets(times, loopMs);
  return o.map((v, i) => (i + 1 < o.length ? o[i + 1] - v : 0));
}

// Which snapshot shows `elapsedMs` after play started.
// -> { index, done, resting, wrapped, cycle }
//   done     play-once reached the latest snapshot and stops
//   resting  loop mode: holding the latest for `rest` (a quarter of the loop) before the restart
//   wrapped  the cue: the loop has just come back to the start
export function frameAt(times, elapsedMs, { loopMs = DEFAULT_LOOP_MS, loop = false, restMs = loopMs / 4 } = {}) {
  const n = times.length;
  if (n === 0) return { index: -1, done: true, resting: false, wrapped: false, cycle: 0 };
  if (n === 1) return { index: 0, done: true, resting: false, wrapped: false, cycle: 0 };
  const o = offsets(times, loopMs);
  const at = (ms) => {
    let lo = 0;
    for (let i = 0; i < n; i += 1) {
      if (o[i] <= ms) lo = i;
      else break;
    }
    return lo;
  };
  const e = Math.max(0, elapsedMs);
  // How far through its hold the current snapshot is (0 to 1): the fade uses it.
  const progress = (ms, i) => (i + 1 < n && o[i + 1] > o[i] ? Math.min(1, (ms - o[i]) / (o[i + 1] - o[i])) : 0);
  if (!loop) {
    if (e >= loopMs) return { index: n - 1, done: true, resting: false, wrapped: false, cycle: 0, progress: 0 };
    const i = at(e);
    return { index: i, done: false, resting: false, wrapped: false, cycle: 0, progress: progress(e, i) };
  }
  const period = loopMs + restMs;
  const cycle = Math.floor(e / period);
  const phase = e - cycle * period;
  if (phase >= loopMs) return { index: n - 1, done: false, resting: true, wrapped: false, cycle, progress: 0 };
  const i = at(phase);
  return { index: i, done: false, resting: false, wrapped: cycle > 0 && phase < WRAP_CUE_MS, cycle, progress: progress(phase, i) };
}

// The optional fade (a display effect only: nothing is invented, the two real
// spectra are drawn at partial opacity). The current snapshot starts to give way
// to the next in the last `share` of its hold. -> { current, next } opacities.
export function fadeWeights(progress, share = 0.25) {
  if (!(progress > 1 - share)) return { current: 1, next: 0 };
  const w = Math.min(1, (progress - (1 - share)) / share);
  return { current: 1 - w, next: w };
}

// Elapsed ms at which snapshot `index` is shown (to resume play from the slider).
export function elapsedFor(times, index, loopMs = DEFAULT_LOOP_MS) {
  return offsets(times, loopMs)[index] ?? 0;
}

// ---- running only -------------------------------------------------------------------

// A snapshot counts as stopped only when the sender said so (running === false);
// "unknown" is kept.
export const isStopped = (s) => s.running === false;
export function runningOnly(index, on) {
  return on ? index.filter((s) => !isStopped(s)) : index;
}
// Drop the points of a series (band level over time) taken at a stopped snapshot.
export function dropStopped(series, index, on) {
  if (!on || !series) return series;
  const stopped = new Set(index.filter(isStopped).map((s) => new Date(s.t).getTime()));
  return series.filter((p) => !stopped.has(new Date(p.t).getTime()));
}

// ---- orders -------------------------------------------------------------------------

// A spectrum's x values in the unit the chart shows. Hz as they are; orders
// (multiples of running speed) need that snapshot's rpm: null when it has none.
export function xFor(freqs, rpm, unit) {
  if (unit !== "orders") return freqs;
  if (!(rpm > 0)) return null;
  const hz = rpm / 60;
  return freqs.map((f) => f / hz);
}
// The Hz range to ask the server for when the chart is zoomed to [a, b] in `unit`.
export function hzRange(a, b, rpm, unit) {
  if (unit !== "orders") return { f_min: a, f_max: b };
  if (!(rpm > 0)) return null;
  return { f_min: a * (rpm / 60), f_max: b * (rpm / 60) };
}
// Convert a picked range between Hz and orders (null when there is no speed).
export function convertRange(range, from, to, rpm) {
  if (!range || from === to) return range;
  if (!(rpm > 0)) return null;
  const k = rpm / 60;
  return from === "Hz" ? { low: range.low / k, high: range.high / k } : { low: range.low * k, high: range.high * k };
}

// ---- adding a snapshot from a file --------------------------------------------------

export const MAX_VALUES = 500000; // numbers in one snapshot, all axes (the server's limit)

function bad(message) {
  const e = new Error(message);
  e.plain = true;
  return e;
}

// A JSON file: one snapshot, a {snapshots: [...]} batch, or a bare list.
export function parseJsonSnapshots(text) {
  let data;
  try {
    data = JSON.parse(text);
  } catch {
    throw bad("That file isn't valid JSON. Check for a missing bracket or comma, or choose a CSV or WAV file instead.");
  }
  const list = Array.isArray(data) ? data : Array.isArray(data?.snapshots) ? data.snapshots : [data];
  if (!list.length || list.some((x) => !x || typeof x !== "object" || Array.isArray(x))) {
    throw bad("The JSON should be one snapshot like {\"time\": ..., \"axes\": {...}} or {\"snapshots\": [...]}.");
  }
  if (list.length > 20) throw bad(`That file has ${list.length} snapshots; up to 20 can be added at once.`);
  return list;
}

const isNumber = (t) => t.trim() !== "" && Number.isFinite(Number(t));

// CSV or plain text: columns of numbers, one column per axis. A first row of
// names gives the axis names; a column called time / t / seconds is read as
// seconds, and gives the sample rate when the steps are even.
export function parseCsv(text) {
  const lines = text.split(/\r?\n/).map((l) => l.trim()).filter((l) => l && !l.startsWith("#"));
  if (!lines.length) throw bad("The file is empty.");
  const split = (l) => l.split(/[,;\t]/).map((c) => c.trim());
  let names = null;
  let rows = lines.map(split);
  if (rows[0].some((c) => !isNumber(c))) {
    names = rows[0];
    rows = rows.slice(1);
  }
  if (!rows.length) throw bad("The file has a header row but no numbers.");
  const width = rows[0].length;
  if (rows.some((r) => r.length !== width)) throw bad("Every row needs the same number of columns.");
  const cols = Array.from({ length: width }, () => []);
  for (let i = 0; i < rows.length; i += 1) {
    for (let j = 0; j < width; j += 1) {
      const c = rows[i][j];
      if (!isNumber(c)) throw bad(`Row ${i + 1 + (names ? 1 : 0)}, column ${j + 1} (“${c.slice(0, 20)}”) isn't a number.`);
      cols[j].push(Number(c));
    }
  }
  let sampleRate = null;
  let axisNames = names ? [...names] : cols.map((_, j) => String(j + 1));
  let data = cols;
  const timeCol = names ? names.findIndex((n) => /^(time|t|seconds|s)$/i.test(n)) : -1;
  if (timeCol >= 0) {
    const t = cols[timeCol];
    const steps = t.slice(1).map((v, i) => v - t[i]);
    const mean = steps.length ? steps.reduce((a, b) => a + b, 0) / steps.length : 0;
    if (mean > 0 && steps.every((d) => Math.abs(d - mean) <= mean * 0.01)) sampleRate = Math.round((1 / mean) * 1e6) / 1e6;
    data = cols.filter((_, j) => j !== timeCol);
    axisNames = axisNames.filter((_, j) => j !== timeCol);
    if (!data.length) throw bad("The file has a time column but no signal column.");
  }
  return { axes: Object.fromEntries(data.map((c, j) => [axisNames[j] || String(j + 1), c])), sampleRate };
}

// A WAV file (PCM 8 / 16 / 24 / 32-bit or float): channels become axes, values
// are fractions of full scale (-1 to 1), the sample rate comes from the header.
export function parseWav(buffer) {
  const v = new DataView(buffer);
  const tag = (o) => String.fromCharCode(v.getUint8(o), v.getUint8(o + 1), v.getUint8(o + 2), v.getUint8(o + 3));
  if (buffer.byteLength < 44 || tag(0) !== "RIFF" || tag(8) !== "WAVE") throw bad("That doesn't look like a WAV file.");
  let fmt = null;
  let dataAt = -1;
  let dataLen = 0;
  for (let o = 12; o + 8 <= buffer.byteLength;) {
    const id = tag(o);
    const len = v.getUint32(o + 4, true);
    if (id === "fmt ") {
      fmt = { format: v.getUint16(o + 8, true), channels: v.getUint16(o + 10, true), rate: v.getUint32(o + 12, true), bits: v.getUint16(o + 22, true) };
      if (fmt.format === 0xfffe && len >= 26) fmt.format = v.getUint16(o + 32, true);
    } else if (id === "data") {
      dataAt = o + 8;
      dataLen = Math.min(len, buffer.byteLength - dataAt);
      break;
    }
    o += 8 + len + (len % 2);
  }
  if (!fmt || dataAt < 0) throw bad("That WAV file has no readable sound data.");
  const { format, channels, rate, bits } = fmt;
  const ok = (format === 1 && [8, 16, 24, 32].includes(bits)) || (format === 3 && [32, 64].includes(bits));
  if (!ok) throw bad(`This WAV file uses a format Reliafy can't read (${bits}-bit, type ${format}). Use PCM or float.`);
  const bytes = bits / 8;
  const frames = Math.floor(dataLen / (bytes * channels));
  const axes = {};
  for (let c = 0; c < channels; c += 1) axes[String(c + 1)] = new Array(frames);
  for (let i = 0; i < frames; i += 1) {
    for (let c = 0; c < channels; c += 1) {
      const o = dataAt + (i * channels + c) * bytes;
      let x;
      if (format === 3) x = bits === 32 ? v.getFloat32(o, true) : v.getFloat64(o, true);
      else if (bits === 8) x = (v.getUint8(o) - 128) / 128;
      else if (bits === 16) x = v.getInt16(o, true) / 32768;
      else if (bits === 24) x = (((v.getUint8(o + 2) << 24) | (v.getUint8(o + 1) << 16) | (v.getUint8(o) << 8)) >> 8) / 8388608;
      else x = v.getInt32(o, true) / 2147483648;
      axes[String(c + 1)][i] = x;
    }
  }
  return { axes, sampleRate: rate, bits };
}

// How many numbers a set of axes holds, and plain words if it is too many.
export function sizeProblem(axes, limit = MAX_VALUES) {
  const names = Object.keys(axes || {});
  if (!names.length) return null;
  const per = axes[names[0]].length;
  const total = per * names.length;
  if (total <= limit) return null;
  const fits = Math.floor(limit / names.length);
  return {
    total, perAxis: per, fits,
    message: `This file has ${total.toLocaleString("en-GB")} numbers (${per.toLocaleString("en-GB")} on each of ${names.length} axis${names.length === 1 ? "" : "es"}). `
      + `One snapshot can hold at most ${limit.toLocaleString("en-GB")} (about 5 MB). `
      + `Use only the first ${fits.toLocaleString("en-GB")} samples of each axis, or split the recording into shorter files.`,
  };
}
export function trimAxes(axes, n) {
  return Object.fromEntries(Object.entries(axes).map(([k, v]) => [k, v.slice(0, n)]));
}

// Fewer points to draw a long waveform: the lowest and highest of each stretch.
export function thinWave(x, maxPoints = 800) {
  if (x.length <= maxPoints) return { x: x.map((_, i) => i), y: x };
  const step = Math.ceil(x.length / (maxPoints / 2));
  const xs = [];
  const ys = [];
  for (let i = 0; i < x.length; i += step) {
    const seg = x.slice(i, i + step);
    let lo = 0;
    let hi = 0;
    seg.forEach((v, k) => { if (v < seg[lo]) lo = k; if (v > seg[hi]) hi = k; });
    const pair = lo <= hi ? [lo, hi] : [hi, lo];
    for (const k of lo === hi ? [lo] : pair) { xs.push(i + k); ys.push(seg[k]); }
  }
  return { x: xs, y: ys };
}

// The body to post for one snapshot made from a file's numbers and the form.
export function snapshotBody({ channelId, time, axes, sampleRate, scale = 1, rpm, running, note }) {
  const k = Number(scale) || 1;
  const body = {
    channel_id: channelId, time,
    axes: Object.fromEntries(Object.entries(axes).map(([n, v]) => [n, k === 1 ? v : v.map((y) => y * k)])),
    sample_rate: Number(sampleRate),
  };
  if (rpm !== "" && rpm !== null && rpm !== undefined && Number(rpm) > 0) body.rpm = Number(rpm);
  if (running === "yes") body.running = true;
  if (running === "no") body.running = false;
  if (note) body.note = note;
  return body;
}

// A local date-time field's value ("2026-11-03T10:00") as an ISO time with the
// browser's zone, which is what the server needs.
export function localToIso(value) {
  if (!value) return null;
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? null : d.toISOString();
}

// ---- bands --------------------------------------------------------------------------

// A frequency in Hz as a multiple of the running speed (rpm), and back.
export const toOrders = (hz, rpm) => (rpm > 0 ? hz / (rpm / 60) : null);
export const fromOrders = (order, rpm) => (rpm > 0 ? order * (rpm / 60) : null);

// Lines for a band's limits on its level chart: warning amber, alarm red, drawn
// differently (dotted / dashed) and labelled, so colour isn't the only sign.
export function limitLines(band) {
  if (!band) return [];
  const out = [];
  const add = (v, kind, side) => { if (v !== null && v !== undefined) out.push({ value: v, kind, label: `${kind === "alarm" ? "Alarm" : "Warn"} ${side} ${fmt(v)}` }); };
  add(band.warn_above, "warn", "above");
  add(band.alarm_above, "alarm", "above");
  add(band.warn_below, "warn", "below");
  add(band.alarm_below, "alarm", "below");
  return out;
}

export function bandLabel(rule) {
  if (!rule) return "";
  if (rule.type === "level") return `${rule.stat} of ${rule.axis}`;
  const unit = rule.in === "orders" ? "× running speed" : "Hz";
  return `${fmt(rule.low)} to ${fmt(rule.high)} ${unit} (${rule.axis})`;
}

// ---- numbers and dates --------------------------------------------------------------

// Three or four significant figures, never a 15-digit float.
export function fmt(v, digits = 3) {
  if (v === null || v === undefined || !Number.isFinite(Number(v))) return "–";
  const n = Number(v);
  if (n === 0) return "0";
  const a = Math.abs(n);
  if (a >= 1e5 || a < 1e-3) return n.toExponential(digits - 1).replace("e", " × 10^").replace("+", "");
  return String(Number(n.toPrecision(digits)));
}

export function fmtBytes(b) {
  if (!Number.isFinite(b)) return "–";
  if (b < 1e3) return `${b} B`;
  if (b < 1e6) return `${(b / 1e3).toFixed(0)} kB`;
  return `${(b / 1e6).toFixed(1)} MB`;
}

export function fmtMB(bytes) {
  if (!Number.isFinite(bytes)) return "–";
  return bytes < 1e5 ? `${(bytes / 1e3).toFixed(0)} kB` : `${(bytes / 1e6).toFixed(bytes < 1e7 ? 2 : 1)} MB`;
}

export function fmtWhen(iso, { time = true } = {}) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const opts = { day: "numeric", month: "short", year: "numeric", ...(time ? { hour: "2-digit", minute: "2-digit" } : {}) };
  return d.toLocaleString("en-GB", opts);
}

// Which snapshots to offer in the picker when there are many: all of them are
// listed (newest first); this keeps the chart's default to the latest plus a
// baseline (the oldest one that was running, else the oldest).
export function defaultPicks(index) {
  if (!index.length) return { picked: [], baseline: null };
  const latest = index[index.length - 1];
  const baseline = index.find((s) => s.running === true) || index[0];
  return { picked: [latest.id], baseline: baseline.id === latest.id ? null : baseline.id };
}

// Colour for the n-th picked snapshot (the shared categorical colours; the
// player's own trace is the accent and the baseline is grey).
export function snapshotColor(colors, n) {
  return colors[n % colors.length];
}
