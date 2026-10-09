// One chart theme for every Plotly chart (#308). `Plot.jsx` deep-merges
// BASE_LAYOUT under each chart's layout and PLOT_CONFIG under its config, so a
// chart sets only what is particular to it (axis titles, ranges, shapes) and
// can still override any of these.
//
// Series carry a role rather than a colour of their own: the fitted curve is
// the accent, observed data is ink, a confidence band is a faint accent fill,
// a reference line is a dashed grey and an optimum is an ink marker with a
// label. Several comparable series (covariate combinations, stress levels,
// items) take COLORWAY in order.

export const ACCENT = "#2f6df6";
export const INK = "#14171c";
export const MUTED = "#5f6670";
export const SUBTLE = "#6c727c";
export const REFERENCE = "#9aa0a8"; // borders, reference lines
export const GRID = "#e9ebee";
export const AXIS = "#cfd3d8";
export const DANGER = "#b91c1c";
export const SUCCESS = "#15803d";
export const WARNING = "#b45309";
export const SURFACE = "#ffffff"; // card and page surface; marker outlines

// Kinds, not series: model kinds, distribution families, planned work. The
// same palette as the --cat-* tokens in index.css (blue is the accent).
export const CATEGORY = { blue: ACCENT, amber: "#d0762f", teal: "#0f9ab0", violet: "#7c3aed", grey: SUBTLE };

export const DATA_INK = "rgba(20, 23, 28, 0.7)"; // observed data: ink at 70%
export const BAND_FILL = "rgba(47, 109, 246, 0.10)"; // accent at 0.10
export const NEUTRAL_BAND_FILL = "rgba(20, 23, 28, 0.08)"; // a band around observed (ink) data

// Categorical order, led by the accent; validated for colour-vision
// deficiency on adjacent pairs. Assign in order, never by rank.
export const COLORWAY = [ACCENT, "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"];

const FONT = '"IBM Plex Sans", system-ui, -apple-system, "Segoe UI", Roboto, sans-serif';

export const PLOT_CONFIG = {
  displayModeBar: false,
  displaylogo: false,
  responsive: true,
};

// Shared by every x/y axis (xaxis, yaxis, xaxis2, …).
const AXIS_BASE = {
  automargin: true,
  zeroline: false,
  linecolor: AXIS,
  tickcolor: AXIS,
  // "12,000", not "12k".
  exponentformat: "none",
  separatethousands: true,
  title: { standoff: 10, font: { color: MUTED, size: 12 } },
};

export const BASE_LAYOUT = {
  autosize: true,
  font: { family: FONT, size: 12, color: MUTED },
  paper_bgcolor: "rgba(0,0,0,0)",
  plot_bgcolor: "rgba(0,0,0,0)",
  colorway: COLORWAY,
  barcornerradius: 3,
  margin: { l: 56, r: 16, t: 16, b: 48 },
  xaxis: { ...AXIS_BASE, showgrid: false, ticks: "outside", ticklen: 4 },
  yaxis: { ...AXIS_BASE, showgrid: true, gridcolor: GRID, showline: false },
  // Above the plot, left-aligned: a legend outside the plot area pushes the
  // margin, so it never sits on the x-axis title.
  legend: {
    orientation: "h",
    x: 0,
    xanchor: "left",
    y: 1.02,
    yanchor: "bottom",
    bgcolor: "rgba(0,0,0,0)",
    font: { color: INK, size: 12 },
  },
  hoverlabel: {
    bgcolor: INK,
    bordercolor: INK,
    font: { family: FONT, color: SURFACE, size: 12 },
  },
};


const isObject = (v) => v !== null && typeof v === "object" && !Array.isArray(v);

// Merge `over` onto `base`, recursing into plain objects; arrays and scalars
// in `over` replace. Neither argument is modified.
export function deepMerge(base, over) {
  if (!isObject(base) || !isObject(over)) return over === undefined ? base : over;
  const out = { ...base };
  for (const [k, v] of Object.entries(over)) {
    out[k] = v === undefined ? base[k] : isObject(v) && isObject(base[k]) ? deepMerge(base[k], v) : v;
  }
  return out;
}

const AXIS_KEY = /^[xy]axis\d*$/;

// The chart's layout over the theme. Extra axes (xaxis2, yaxis2) get the same
// axis defaults as the first pair. `narrow` (a phone): level tick labels, and
// fewer of them on x.
export function themedLayout(layout = {}, { narrow = false } = {}) {
  let base = BASE_LAYOUT;
  for (const k of Object.keys(layout)) {
    if (AXIS_KEY.test(k) && !(k in base)) {
      base = { ...base, [k]: k.startsWith("x") ? BASE_LAYOUT.xaxis : BASE_LAYOUT.yaxis };
    }
  }
  if (narrow) {
    base = { ...base };
    for (const k of Object.keys(base)) {
      if (!AXIS_KEY.test(k)) continue;
      // A category axis shows every category; nticks only thins numbers and dates.
      const over = layout[k] || {};
      base[k] = { ...base[k], tickangle: 0, ...(k.startsWith("x") && over.type !== "category" ? { nticks: 4 } : {}) };
    }
  }
  const merged = deepMerge(base, layout);
  if (narrow) {
    // Fixed ticks (probability paper) ignore nticks: keep every k-th on x.
    for (const k of Object.keys(merged)) {
      const ax = merged[k];
      if (!k.startsWith("x") || !AXIS_KEY.test(k) || !Array.isArray(ax?.tickvals) || ax.tickvals.length <= 5) continue;
      const step = Math.ceil(ax.tickvals.length / 4);
      const keep = (_, i) => i % step === 0;
      merged[k] = {
        ...ax,
        tickvals: ax.tickvals.filter(keep),
        ...(Array.isArray(ax.ticktext) ? { ticktext: ax.ticktext.filter(keep) } : {}),
      };
    }
  }
  return merged;
}

export const themedConfig = (config = {}) => deepMerge(PLOT_CONFIG, config);

// ---- Series roles ----------------------------------------------------------
// Each takes the rest of the trace (x, y, name, …) and fills in the role's
// style; anything passed wins.

const role = (style) => (trace = {}) => deepMerge({ type: "scatter", ...style }, trace);

// The fitted / estimated curve: accent, 2 px.
export const fitLine = role({ mode: "lines", line: { color: ACCENT, width: 2 } });

// Observed data points: ink at 70%, with a thin surface ring.
export const dataPoints = role({
  mode: "markers",
  marker: { color: DATA_INK, size: 7, line: { color: SURFACE, width: 1 } },
});

// A line through observed data (e.g. an empirical step curve).
export const dataLine = role({ mode: "lines", line: { color: DATA_INK, width: 1.5 } });

// Confidence band: accent at 0.10, no edge lines. Pass x/y for a closed
// polygon (fill "toself"), or use bandPair() for a lower/upper pair.
export const band = role({
  mode: "lines",
  fill: "toself",
  fillcolor: BAND_FILL,
  line: { width: 0, color: "rgba(0,0,0,0)" },
  hoverinfo: "skip",
});

// A band as two traces: the lower edge (no legend) then the upper filled down
// to it. Put them before the curve they belong to.
export function bandPair(x, lower, upper, extra = {}) {
  const { name, showlegend, fillcolor, ...rest } = extra;
  return [
    deepMerge({ type: "scatter", mode: "lines", line: { width: 0 }, hoverinfo: "skip", showlegend: false }, { x, y: lower, ...rest }),
    deepMerge(
      { type: "scatter", mode: "lines", line: { width: 0 }, hoverinfo: "skip", fill: "tonexty", fillcolor: fillcolor || BAND_FILL },
      { x, y: upper, name, ...(showlegend === undefined ? { showlegend: !!name } : { showlegend }), ...rest },
    ),
  ];
}

// A reference line drawn as a trace (e.g. run-to-failure cost): dashed grey.
export const referenceLine = role({ mode: "lines", line: { color: REFERENCE, width: 1.5, dash: "dash" }, hoverinfo: "skip" });

// A reference line as a layout shape: { x } for a vertical, { y } for a
// horizontal line across the plot.
export function referenceShape({ x, y, ...rest } = {}) {
  const line = { color: REFERENCE, width: 1, dash: "dash" };
  const shape = x != null
    ? { type: "line", x0: x, x1: x, yref: "paper", y0: 0, y1: 1, line }
    : { type: "line", xref: "paper", x0: 0, x1: 1, y0: y, y1: y, line };
  return deepMerge(shape, rest);
}

// The optimum (or the chosen point): an ink marker with its label beside it.
export const optimumMarker = (trace = {}) =>
  deepMerge(
    {
      type: "scatter",
      mode: "markers+text",
      marker: { color: INK, size: 10, line: { color: SURFACE, width: 2 } },
      text: trace.name ? [trace.name] : undefined,
      textposition: "top center",
      textfont: { color: INK, size: 12 },
      cliponaxis: false,
      showlegend: false,
    },
    trace,
  );

// The marker for the evaluated point on a calculator curve.
export const pointMarker = (color = ACCENT) => ({
  type: "scatter",
  mode: "markers",
  marker: { color, size: 9, line: { color: SURFACE, width: 2 } },
  showlegend: false,
  hoverinfo: "y",
});

// An axis title from the backend in sentence case: "test length" -> "Test length".
export const sentence = (text) => (text ? String(text).charAt(0).toUpperCase() + String(text).slice(1) : text);

// "Bearings — probability plot" -> "bearings-probability-plot".
export function slugify(text) {
  const s = String(text || "")
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 80);
  return s || "chart";
}
