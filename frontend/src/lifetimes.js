// The dataset page's Lifetimes view (components/LifetimesView.jsx): the lines
// the server read off SurPyval's SurpyvalData with the dataset's reading
// (GET /api/datasets/{id}/lifetimes, backend/services/lifetimes.py), sorted,
// sampled and turned into the chart's traces. One line per unit (per system
// for repairable data): where it came under observation, and how it ended.
import { DATA_INK, INK, REFERENCE, COLORWAY, withAlpha } from "./plotTheme.js";
import { formatNumber } from "./format.js";

// Above this many lines the chart shows an even sample, with Show all.
export const SAMPLE_LINES = 200;

const plural = (n, one, many = one + "s") => `${n.toLocaleString()} ${n === 1 ? one : many}`;

// The legend in words, one entry per kind of mark the lines hold.
export const MARK_WORDS = {
  failed: "Failed",
  event: "Failure",
  running: "Still running (last seen working)",
  before: "Failed before this time (found failed)",
  window: "Failed in this window (between inspections)",
  entered: "Entered late (observed from here)",
  step: "Next row starts",
  bound: "Record ends",
};

// "150 units: 98 failed, 49 still running, 3 in a window · 20 entered late",
// or "12 systems · 48 failures" (repairable).
export function summaryText(payload) {
  const s = payload?.summary;
  if (!s) return "";
  if (payload.mode === "repairable") {
    const stream = (payload.lines || []).length === 1 && payload.lines[0].id === "All rows";
    return `${stream ? "1 stream" : plural(s.units, "system")} · ${plural(s.events, "failure")}`;
  }
  const parts = [];
  if (s.failed) parts.push(`${s.failed.toLocaleString()} failed`);
  if (s.running) parts.push(`${s.running.toLocaleString()} still running`);
  if (s.window) parts.push(`${s.window.toLocaleString()} in a window`);
  if (s.before) parts.push(`${s.before.toLocaleString()} failed before their first look`);
  let text = `${plural(s.units, "unit")}${parts.length ? ": " + parts.join(", ") : ""}`;
  if (s.late) text += ` · ${s.late.toLocaleString()} entered late`;
  return text;
}

// A warning when the reading says something a quick look should question:
// every unit failed, or none did. Facts, not verdicts: the user decides.
export function readingHint(payload) {
  const s = payload?.summary;
  if (!s || payload.mode === "repairable" || s.units < 2) return null;
  const ended = s.failed + s.before + s.window;
  if (ended === s.units) return "Every unit is read as failed. If some were still running, check the status column (c) and which way round it is.";
  if (ended === 0) return "No unit is read as failed. If some failed, check the status column (c) and which way round it is.";
  return null;
}

// What a line is called: its id, or its row ("Row 12").
export function lineName(line, mode) {
  if (line.id != null) return String(line.id);
  if (line.rows?.length) return `Row ${line.rows[0]}`;
  return mode === "repairable" ? "System" : "Unit";
}

// The sort choices: by time (the line's end), by unit or row order, and by
// each covariate with few values.
export function sortOptions(payload) {
  const unit = payload?.mode === "rows" ? "Row order" : payload?.mode === "repairable" ? "System" : "Unit";
  return [
    { value: "time", label: "Time" },
    { value: "unit", label: unit },
    ...Object.keys(payload?.groups || {}).map((c) => ({ value: `group:${c}`, label: c })),
  ];
}

const natural = new Intl.Collator(undefined, { numeric: true, sensitivity: "base" });

// The lines in the chosen order, each with its group value (``group``).
export function sortedLines(payload, sort = "time") {
  const lines = (payload?.lines || []).map((line, k) => ({ line, k }));
  const by = sort.startsWith("group:") ? sort.slice(6) : null;
  const values = by ? payload.groups?.[by] || [] : [];
  const time = (a, b) => a.line.end - b.line.end || a.k - b.k;
  const unit = (a, b) => (a.line.id != null && b.line.id != null ? natural.compare(a.line.id, b.line.id) : 0) || a.k - b.k;
  const group = (a, b) => natural.compare(String(values[a.k] ?? "￿"), String(values[b.k] ?? "￿")) || time(a, b);
  lines.sort(by ? group : sort === "unit" ? unit : time);
  return lines.map(({ line, k }) => ({ ...line, group: by ? values[k] ?? null : null }));
}

// An even sample of ``limit`` lines across their order (first and last kept).
export function sampleLines(lines, limit = SAMPLE_LINES) {
  if (lines.length <= limit) return lines;
  const out = [];
  for (let j = 0; j < limit; j += 1) out.push(lines[Math.round((j * (lines.length - 1)) / (limit - 1))]);
  return out;
}

// The height of one line on the chart, in px: roomy for a few, dense for many.
export function rowHeight(n) {
  if (n <= 20) return 24;
  if (n <= 40) return 16;
  if (n <= 60) return 10;
  if (n <= 200) return 6;
  return 3;
}

// An "-open" symbol is drawn in its colour with no fill (on the chart's surface).
function markerTrace(name, symbol, color, { size = 8, line = 1.5, legend = true } = {}) {
  return {
    type: "scatter", mode: "markers", name, x: [], y: [], text: [], hovertemplate: "%{text}<extra></extra>",
    marker: { symbol, size, color, line: { color, width: line } }, showlegend: legend,
  };
}

// The chart's traces for ``lines`` (sorted and sampled), with y = 0 at the top.
// ``unit``: the time unit, in hover text. ``colourBy``: true when the lines are
// sorted by a group, which then colours them (with a legend entry each).
export function lifetimesTraces(lines, { mode = "rows", unit = "", colourBy = false } = {}) {
  const u = unit ? ` ${unit.toLowerCase()}` : "";
  const at = (v) => `${formatNumber(v)}${u}`;
  const groups = colourBy ? [...new Set(lines.map((l) => l.group ?? "(blank)"))] : [];
  const colour = (l) => (colourBy ? COLORWAY[groups.indexOf(l.group ?? "(blank)") % COLORWAY.length] : REFERENCE);
  const lineTraces = new Map();
  const lineTrace = (l) => {
    const key = colourBy ? l.group ?? "(blank)" : "";
    if (!lineTraces.has(key)) {
      lineTraces.set(key, {
        type: "scatter", mode: "lines", name: colourBy ? String(key) : "Observed", x: [], y: [], hoverinfo: "skip",
        line: { color: colour(l), width: colourBy ? 2 : 1.5 }, showlegend: colourBy,
      });
    }
    return lineTraces.get(key);
  };
  const windows = {
    type: "scatter", mode: "lines", name: MARK_WORDS.window, x: [], y: [], hoverinfo: "skip",
    line: { color: withAlpha(INK, 0.45), width: 6 }, showlegend: true,
  };
  const t = {
    failed: markerTrace(mode === "repairable" ? MARK_WORDS.event : MARK_WORDS.failed,
      mode === "repairable" ? "line-ns" : "circle", DATA_INK, mode === "repairable" ? { size: 10, line: 2 } : {}),
    running: markerTrace(MARK_WORDS.running, "triangle-right-open", DATA_INK, { size: 9 }),
    before: markerTrace(MARK_WORDS.before, "triangle-left-open", DATA_INK, { size: 9 }),
    windowEnds: markerTrace(MARK_WORDS.window, "line-ns", DATA_INK, { size: 10, legend: false }),
    entered: markerTrace(MARK_WORDS.entered, "line-ns", DATA_INK, { size: 12, line: 2 }),
    step: markerTrace(MARK_WORDS.step, "line-ns", REFERENCE, { size: 6, line: 1 }),
    bound: markerTrace(MARK_WORDS.bound, "line-ns", REFERENCE, { size: 12, line: 2 }),
  };
  const counts = { type: "scatter", mode: "text", x: [], y: [], text: [], textposition: "middle right",
    hoverinfo: "skip", showlegend: false, textfont: { size: 11, color: DATA_INK } };
  const push = (trace, x, y, text) => { trace.x.push(x); trace.y.push(y); trace.text.push(text); };
  lines.forEach((l, y) => {
    const name = lineName(l, mode);
    const lt = lineTrace(l);
    lt.x.push(l.start, l.end, null);
    lt.y.push(y, y, null);
    if (l.entered != null) push(t.entered, l.entered, y, `${name}: observed from ${at(l.entered)}`);
    for (const m of l.marks || []) {
      const n = m.n > 1 ? ` (${m.n.toLocaleString()} units)` : "";
      if (m.kind === "failed") push(t.failed, m.at, y, `${name}: ${mode === "repairable" ? "failure" : "failed"} at ${at(m.at)}${n}`);
      else if (m.kind === "running") push(t.running, m.at, y, `${name}: still running at ${at(m.at)}${n}`);
      else if (m.kind === "before") push(t.before, m.at, y, `${name}: found failed by ${at(m.at)}${n}`);
      else if (m.kind === "step") push(t.step, m.at, y, `${name}: next row from ${at(m.at)}`);
      else if (m.kind === "bound") push(t.bound, m.at, y, `${name}: ${mode === "repairable" ? "record ends" : "observed only up to"} ${at(m.at)}`);
      else if (m.kind === "window") {
        windows.x.push(m.from, m.at, null);
        windows.y.push(y, y, null);
        const text = `${name}: failed between ${at(m.from)} and ${at(m.at)}${n}`;
        push(t.windowEnds, m.from, y, text);
        push(t.windowEnds, m.at, y, text);
      }
      if (m.n > 1) push(counts, m.at, y, ` ${m.n.toLocaleString()}×`);
    }
  });
  const marks = [t.entered, t.step, t.bound, t.failed, t.running, t.before];
  return [
    ...lineTraces.values(),
    ...(windows.x.length ? [windows, t.windowEnds] : []),
    ...marks.filter((m) => m.x.length),
    ...(counts.x.length ? [counts] : []),
  ];
}

// The x range: from the window start (0, or below it) to past the last time.
export function timeRange(lines, floor = 0) {
  let hi = floor;
  for (const l of lines) {
    hi = Math.max(hi, l.end);
    for (const m of l.marks || []) hi = Math.max(hi, m.at);
  }
  const pad = (hi - floor || 1) * 0.04;
  return [floor, hi + pad];
}
