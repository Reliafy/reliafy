import Plot from "./Plot.jsx";
import { COLORWAY, NEUTRAL_BAND_FILL, bandPair } from "../plotTheme.js";

// Each failure mode's colour, in the fit's order (most failures first).
export const causeColor = (i) => COLORWAY[i % COLORWAY.length];

function tint(hex, alpha) {
  const h = hex.replace("#", "");
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16));
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

const sum = (a, b) => a.map((v, i) => (v == null || b[i] == null ? null : v + b[i]));

// The cumulative incidence of each failure mode (#177): stacked, so the top
// is the all-cause failure probability with its 95% band, or each mode on
// its own with its band. Step curves, as SurPyval estimates them.
export default function CompetingRisksPlot({ result, unit, stacked = true, download = null }) {
  const c = result.curves || {};
  const x = c.x || [];
  const names = (result.causes || []).map((k) => k.name);
  const traces = [];
  if (stacked) {
    let base = x.map(() => 0);
    names.forEach((name, i) => {
      const top = sum(base, c.cif?.[name] || []);
      traces.push({
        type: "scatter", mode: "lines", x, y: top, name,
        fill: i === 0 ? "tozeroy" : "tonexty", fillcolor: tint(causeColor(i), 0.28),
        line: { color: causeColor(i), width: 1.5, shape: "hv" },
        customdata: c.cif?.[name],
        hovertemplate: `${name}: %{customdata:.1%}<extra></extra>`,
      });
      base = top;
    });
    if ((c.all_lower || []).some((v) => v != null)) {
      traces.push(...bandPair(x, c.all_lower, c.all_upper, {
        name: "95% CI, all modes", fillcolor: NEUTRAL_BAND_FILL, line: { shape: "hv" },
      }));
    }
  } else {
    names.forEach((name, i) => {
      traces.push(...bandPair(x, c.lower?.[name] || [], c.upper?.[name] || [], {
        fillcolor: tint(causeColor(i), 0.12), line: { shape: "hv" }, showlegend: false, legendgroup: name,
      }));
      traces.push({
        type: "scatter", mode: "lines", x, y: c.cif?.[name], name, legendgroup: name,
        line: { color: causeColor(i), width: 2, shape: "hv" },
        hovertemplate: `${name}: %{y:.1%}<extra></extra>`,
      });
    });
  }
  const tops = stacked ? [...(c.all_upper || []), ...(c.all || [])]
    : names.flatMap((n) => [...(c.upper?.[n] || []), ...(c.cif?.[n] || [])]);
  const ymax = Math.min(1, Math.max(0.05, ...tops.filter((v) => v != null)) * 1.08);
  return (
    <Plot
      data={traces}
      layout={{
        height: 340,
        hovermode: "x unified",
        xaxis: { title: { text: unit ? `Time (${unit})` : "Time" }, rangemode: "tozero" },
        yaxis: { title: { text: "Probability of failure" }, range: [0, ymax], tickformat: ".0%" },
        showlegend: true,
      }}
      download={download}
    />
  );
}
