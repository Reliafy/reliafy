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
  if (!loop) {
    if (e >= loopMs) return { index: n - 1, done: true, resting: false, wrapped: false, cycle: 0 };
    return { index: at(e), done: false, resting: false, wrapped: false, cycle: 0 };
  }
  const period = loopMs + restMs;
  const cycle = Math.floor(e / period);
  const phase = e - cycle * period;
  if (phase >= loopMs) return { index: n - 1, done: false, resting: true, wrapped: false, cycle };
  return { index: at(phase), done: false, resting: false, wrapped: cycle > 0 && phase < WRAP_CUE_MS, cycle };
}

// Elapsed ms at which snapshot `index` is shown (to resume play from the slider).
export function elapsedFor(times, index, loopMs = DEFAULT_LOOP_MS) {
  return offsets(times, loopMs)[index] ?? 0;
}

// ---- bands --------------------------------------------------------------------------

// A frequency in Hz as a multiple of the running speed (rpm), and back.
export const toOrders = (hz, rpm) => (rpm > 0 ? hz / (rpm / 60) : null);
export const fromOrders = (order, rpm) => (rpm > 0 ? order * (rpm / 60) : null);

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
