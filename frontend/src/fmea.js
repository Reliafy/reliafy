// FMEA and FMECA arithmetic, as the FME(C)A tab shows it: the risk priority
// number (RPN = S × O × D), the action priority (AP: High, Medium or Low from
// the table the server sends in /rcm/options, never written here), the mode
// criticality (Cm = β × α × λ × t) and the item criticality (Cr, the sum of
// Cm), the labels for each choice, one way of rounding every number on the
// tab, and the criticality matrix a position's details draw.
//
// Pure functions (no React), tested in fmea.test.js. The server computes rpn,
// ap and cm on every read; this file recomputes them only where a value is
// being typed (the live preview in a failure mode's details) and for the
// roll-ups and the matrix.

export const AP_LABEL = { H: "High", M: "Medium", L: "Low" };
export const AP_TONE = { H: "danger", M: "warning", L: "neutral" };
export const STATUS_LABEL = { open: "Open", in_progress: "In progress", done: "Done" };
export const SOURCE_LABEL = { entered: "Entered", model: "From a model", data: "From own data" };
export const CLASS_LABEL = { I: "I Catastrophic", II: "II Critical", III: "III Marginal", IV: "IV Minor" };
export const CLASS_ORDER = ["IV", "III", "II", "I"]; // left low, right high, as the matrix's columns
export const SCORES = ["severity", "occurrence", "detection"];
export const SCORE_LETTER = { severity: "S", occurrence: "O", detection: "D" };
// The ends of each scale, said beside the field (the server's ten-line hints
// are the tooltip when they arrive).
export const SCORE_ENDS = {
  severity: "1 no effect … 10 hazardous, no warning",
  occurrence: "1 almost never … 10 almost certain",
  detection: "1 almost certain to detect … 10 cannot detect",
};

// A whole number from 1 to 10, or null for blank or anything else.
export function score(v) {
  if (v === "" || v == null) return null;
  const n = Number(v);
  return Number.isInteger(n) && n >= 1 && n <= 10 ? n : null;
}

// S × O × D, null unless all three are set.
export function rpnOf(s, o, d) {
  const [S, O, D] = [score(s), score(o), score(d)];
  return S && O && D ? S * O * D : null;
}

// β × α × λ × t, null unless all four are numbers.
export function cmOf({ loss_probability: b, mode_ratio: a, failure_rate: l, operating_time: t } = {}) {
  const v = [b, a, l, t].map((x) => (x === "" || x == null ? NaN : Number(x)));
  return v.every(Number.isFinite) ? v[0] * v[1] * v[2] * v[3] : null;
}

// ---- the action priority table (from GET /api/maintenance/rcm/options, `fmea`) ---
// The server owns the table (its own writing of the publicly known AIAG-VDA
// 2019 rule). It arrives as `ap_bands` (the band each score falls in) and
// `ap_table` (the answer per band triple); both are read here in the shapes a
// JSON API is likely to send, so a small change on the server doesn't blank
// the preview: bands as a list of {id, min, max} (or [id, min, max], or
// {id: [min, max]}) per scale; the table as nested objects {s9: {o8: {d7:
// "H"}}} or a list of rows ({s, o, d7, d5, ...} or {s, o, d, ap}).

const SCALE_KEYS = { severity: ["severity", "s", "S"], occurrence: ["occurrence", "o", "O"], detection: ["detection", "d", "D"] };

function readBands(raw) {
  if (!raw) return null;
  const out = {};
  for (const scale of SCORES) {
    const key = SCALE_KEYS[scale].find((k) => raw[k] != null);
    const list = key ? raw[key] : null;
    if (!list) return null;
    const bands = [];
    const entries = Array.isArray(list) ? list : Object.entries(list).map(([id, v]) => ({ id, ...(Array.isArray(v) ? { min: v[0], max: v[1] } : v) }));
    for (const b of entries) {
      const e = Array.isArray(b) ? { id: b[0], min: b[1], max: b[2] } : b;
      const id = e.id ?? e.band ?? e.name;
      const min = Number(e.min ?? e.lo ?? e.from ?? e.low);
      const max = Number(e.max ?? e.hi ?? e.to ?? e.high ?? min);
      if (!id || !Number.isFinite(min) || !Number.isFinite(max)) return null;
      bands.push({ id: String(id), min, max });
    }
    out[scale] = bands.sort((x, y) => x.min - y.min);
  }
  return out;
}

function readTable(raw) {
  if (!raw) return null;
  const map = new Map();
  const put = (s, o, d, ap) => {
    const v = String(ap || "").toUpperCase()[0];
    if (s && o && d && "HML".includes(v)) map.set(`${s}|${o}|${d}`, v);
  };
  if (Array.isArray(raw)) {
    for (const row of raw) {
      const s = row.s ?? row.severity ?? row.s_band;
      const o = row.o ?? row.occurrence ?? row.o_band;
      if (row.d != null || row.detection != null || row.d_band != null) put(s, o, row.d ?? row.detection ?? row.d_band, row.ap ?? row.priority);
      else for (const [k, v] of Object.entries(row)) if (/^d\d/.test(k)) put(s, o, k, v);
    }
  } else if (typeof raw === "object") {
    for (const [s, os] of Object.entries(raw)) {
      if (!os || typeof os !== "object") continue;
      for (const [o, ds] of Object.entries(os)) {
        if (!ds || typeof ds !== "object") continue;
        for (const [d, ap] of Object.entries(ds)) put(s, o, d, ap);
      }
    }
  }
  return map.size ? map : null;
}

// The options' `fmea` part read into what this file uses, or null when the
// table isn't there (then only the server's own `ap` on each mode is shown).
export function readFmeaOptions(fmea) {
  if (!fmea) return null;
  const bands = readBands(fmea.ap_bands);
  const table = readTable(fmea.ap_table);
  return {
    bands, table,
    scales: fmea.scales || {},
    statuses: fmea.action_statuses || Object.keys(STATUS_LABEL),
    sources: fmea.rate_sources || Object.keys(SOURCE_LABEL),
    classes: fmea.severity_classes || Object.keys(CLASS_LABEL),
  };
}

// The band a score falls in on a scale ({id, min, max}), or null.
export function bandOf(opts, scale, value) {
  const v = score(value);
  if (!v || !opts?.bands?.[scale]) return null;
  return opts.bands[scale].find((b) => v >= b.min && v <= b.max) || null;
}

// "S 9–10": a band in words.
export const bandWords = (scale, band) => (band ? `${SCORE_LETTER[scale]} ${band.min === band.max ? band.min : `${band.min}–${band.max}`}` : "");

// The action priority for three scores from the table: "H", "M" or "L"; null
// without all three scores or without the table.
export function apOf(opts, s, o, d) {
  if (!opts?.bands || !opts?.table) return null;
  const bs = bandOf(opts, "severity", s);
  const bo = bandOf(opts, "occurrence", o);
  const bd = bandOf(opts, "detection", d);
  if (!bs || !bo || !bd) return null;
  return opts.table.get(`${bs.id}|${bo.id}|${bd.id}`)
    // A row written once for every occurrence band ("any"): the lowest severity.
    ?? opts.table.get(`${bs.id}|any|${bd.id}`) ?? null;
}

// ---- numbers on screen ----------------------------------------------------------
// Every number on the tab to three significant figures, written plainly
// ("0.0012", "216", "1230"); very small or large ones as "1.2e-7".
export function fmt3(x) {
  if (x === "" || x == null) return "";
  const n = Number(x);
  if (!Number.isFinite(n)) return "";
  if (n === 0) return "0";
  const a = Math.abs(n);
  // Plain decimals as far as the language itself writes them (down to 1e-6), then "1.2e-7".
  if (a < 1e-6 || a >= 1e6) return n.toExponential(2).replace(/\.?0+e/, "e");
  return String(Number(n.toPrecision(3)));
}

// The Cm line for a mode with the figures that make it (the details and the
// matrix's table): "1.0 × 0.6 × 2e-5 /h × 100 h = 0.0012".
export function cmWords(m) {
  const cm = m?.cm ?? cmOf(m);
  if (cm == null) return "";
  const u = m.time_unit || "hours";
  return `${fmt3(m.loss_probability)} × ${fmt3(m.mode_ratio)} × ${fmt3(m.failure_rate)} /${u} × ${fmt3(m.operating_time)} ${u} = ${fmt3(cm)}`;
}

// ---- the criticality matrix (a position's details) ------------------------------
// Columns: the severity bands, low to high (or the severity classes IV … I
// when every scored mode has a class); rows: the occurrence bands, high at
// the top. Each cell: the modes in it, with the worst action priority among
// them as its tone. `modes` are the failure modes to count (the position's,
// and those inside it), each with its scores and `ap`. The server's bands
// give the axes; without them the ten scores are the axes.
export function matrixOf(modes, opts) {
  const scored = (modes || []).filter((m) => score(m.severity) && score(m.occurrence));
  const byClass = scored.length > 0 && scored.every((m) => CLASS_LABEL[m.severity_class]);
  const sBands = byClass ? CLASS_ORDER.map((c) => ({ id: c, label: c, title: CLASS_LABEL[c] }))
    : (opts?.bands?.severity || tenBands()).map((b) => ({ id: b.id, label: b.min === b.max ? String(b.min) : `${b.min}–${b.max}`, title: `Severity ${b.min === b.max ? b.min : `${b.min} to ${b.max}`}`, min: b.min, max: b.max }));
  const oBands = (opts?.bands?.occurrence || tenBands()).map((b) => ({ id: b.id, label: b.min === b.max ? String(b.min) : `${b.min}–${b.max}`, title: `Occurrence ${b.min === b.max ? b.min : `${b.min} to ${b.max}`}`, min: b.min, max: b.max })).reverse();
  const colOf = (m) => (byClass ? sBands.findIndex((c) => c.id === m.severity_class) : sBands.findIndex((b) => score(m.severity) >= b.min && score(m.severity) <= b.max));
  const rowOf = (m) => oBands.findIndex((b) => score(m.occurrence) >= b.min && score(m.occurrence) <= b.max);
  const cells = oBands.map(() => sBands.map(() => ({ n: 0, worst: null, modes: [] })));
  const rank = { H: 3, M: 2, L: 1 };
  for (const m of scored) {
    const c = colOf(m);
    const r = rowOf(m);
    if (c < 0 || r < 0) continue;
    const cell = cells[r][c];
    cell.n += 1;
    cell.modes.push(m);
    const ap = m.ap || apOf(opts, m.severity, m.occurrence, m.detection);
    if (ap && (rank[ap] || 0) > (rank[cell.worst] || 0)) cell.worst = ap;
  }
  return { cols: sBands, rows: oBands, cells, byClass, scored: scored.length, total: (modes || []).length };
}

// The scores 1 … 10 as ten one-wide bands (when the server sends none).
const tenBands = () => Array.from({ length: 10 }, (_, i) => ({ id: String(i + 1), min: i + 1, max: i + 1 }));

// The modes with a Cm, highest first (the table under the matrix).
export function byCriticality(modes) {
  return (modes || []).map((m) => ({ ...m, cm: m.cm ?? cmOf(m) })).filter((m) => m.cm != null).sort((a, b) => b.cm - a.cm);
}

// The item criticality: the sum of Cm over the modes, and per severity class;
// null with no Cm at all.
export function crOf(modes) {
  let any = false;
  let total = 0;
  const byClass = {};
  for (const m of modes || []) {
    const cm = m.cm ?? cmOf(m);
    if (cm == null) continue;
    any = true;
    total += cm;
    if (m.severity_class) byClass[m.severity_class] = (byClass[m.severity_class] || 0) + cm;
  }
  return any ? { cr: total, byClass } : null;
}
