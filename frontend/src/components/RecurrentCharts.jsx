import { useState } from "react";
import Plot from "./Plot.jsx";
import Chip from "./ui/Chip.jsx";
import {
  COLORWAY, DATA_INK, NEUTRAL_BAND_FILL, band, dataLine, dataPoints, fitLine, referenceShape,
} from "../plotTheme.js";
import { formatNumber } from "../format.js";
import { effectTone, familyOf, growthReading, pct, ratioCiText, ratioText } from "../recurrentResults.js";

// The charts of a recurrent model's tabs (#65), each in the life model's
// layout: the chart on the left, in a tight card with no title above it and
// its legend inside, and a panel on the right.

// Inside the plot, top left: a mean cumulative function rises from bottom
// left to top right, so that corner is empty.
const LEGEND_IN = {
  orientation: "v", x: 0.015, xanchor: "left", y: 0.985, yanchor: "top", bgcolor: "rgba(255,255,255,0.85)",
};
const PLOT_HEIGHT = 500;

const xTitle = (unit) => (unit ? `Time (${String(unit).toLowerCase()})` : "Time");

function bandTrace(obs, extra = {}) {
  return band({
    x: [...obs.x, ...[...obs.x].reverse()],
    y: [...obs.upper, ...[...obs.lower].reverse()],
    fillcolor: NEUTRAL_BAND_FILL,
    name: "95% band",
    ...extra,
  });
}

// The MCF: the observed step with its 95% band, and the fitted model's
// curve (one per level of a covariate model's first text covariate).
export function McfPlot({ r, name }) {
  const obs = r.mcf?.observed || {};
  const fit = r.mcf?.fitted || {};
  const groups = r.mcf?.groups || [];
  const fam = familyOf(r);
  const traces = [];
  if (obs.lower && obs.upper) traces.push(bandTrace(obs));
  if (obs.x?.length) {
    traces.push(dataPoints({
      x: obs.x, y: obs.mcf, mode: "lines+markers",
      line: { color: DATA_INK, width: 1.25, shape: "hv" },
      marker: { size: 5, line: { width: 0 } }, name: "Observed MCF",
    }));
  }
  if (fam === "regression" && groups.length) {
    groups.forEach((g, k) => traces.push(fitLine({ x: g.x, y: g.mcf, name: g.label, line: { color: COLORWAY[k % COLORWAY.length] } })));
  } else if (fit.x) {
    const label = fit.simulated ? `${r.model?.name || "Fitted"} (simulated)` : r.model?.name || "Fitted";
    traces.push(fitLine({ x: fit.x, y: fit.mcf, name: label }));
  }
  const layout = {
    height: PLOT_HEIGHT,
    margin: { t: 8, r: 12, b: 44 },
    legend: LEGEND_IN,
    xaxis: { title: { text: xTitle(r.unit) }, rangemode: "tozero" },
    yaxis: { title: { text: "Cumulative failures per system (MCF)" }, rangemode: "tozero" },
  };
  return <Plot data={traces} layout={layout} download={`${name || r.model?.name || "Recurrent model"} — MCF`} />;
}

// Failures by cause (#65): each cause's MCF, and the band of the one chosen.
export function CausePanel({ r, name }) {
  const bc = r.by_cause || {};
  const causes = bc.causes || [];
  const [chosen, setChosen] = useState(causes[0]?.label ?? null);
  if (!causes.length) {
    return <p className="muted-line">{bc.reason || "No causes in the data."}</p>;
  }
  const traces = [];
  causes.forEach((c, k) => {
    const color = COLORWAY[k % COLORWAY.length];
    if (c.label === chosen && c.mcf.lower && c.mcf.upper) {
      traces.push(bandTrace(c.mcf, { name: `${c.label}: 95% band`, fillcolor: hexA(color, 0.12) }));
    }
    traces.push(dataLine({
      x: c.mcf.x, y: c.mcf.mcf, name: c.label,
      line: { color, width: c.label === chosen ? 2.25 : 1.5, shape: "hv" },
    }));
  });
  const layout = {
    height: PLOT_HEIGHT,
    margin: { t: 8, r: 12, b: 44 },
    legend: LEGEND_IN,
    xaxis: { title: { text: xTitle(r.unit) }, rangemode: "tozero" },
    yaxis: { title: { text: "Cumulative failures per system" }, rangemode: "tozero" },
  };
  const current = causes.find((c) => c.label === chosen);
  const reading = current?.fit ? growthReading(current.fit) : null;
  return (
    <div className="detail-panel life-panel">
      <div className="plotwrap">
        <Plot data={traces} layout={layout} download={`${name || "Recurrent model"} — MCF by cause`} />
      </div>
      <div className="aside rec-aside">
        <div className="gof-card">
          <div className="gofh life-card-head">
            <span>Causes</span>
            <span className="gof-sub">failures · growth shape β</span>
          </div>
          {causes.map((c, k) => (
            <button type="button" key={c.label}
                    className={"gofr rec-cause-row" + (c.label === chosen ? " on" : "")}
                    aria-pressed={c.label === chosen} onClick={() => setChosen(c.label)}>
              <span className="gk"><span className="rec-dot" style={{ background: COLORWAY[k % COLORWAY.length] }} />{c.label}</span>
              <span className="gv-col">
                <span className="gv">{c.failures} <span className="gof-sub">({pct(c.share)})</span></span>
                {c.fit && <span className="param-ci">β {formatNumber(c.fit.beta, { sig: 3 })}</span>}
              </span>
            </button>
          ))}
        </div>
        {current && reading && (
          <div className="life-reading">
            <div className="life-reading-title">{current.label}: {reading.title.toLowerCase()}</div>
            <div>{reading.text}</div>
          </div>
        )}
        <p className="life-method">
          {bc.model || "Crow-AMSAA per cause"}{bc.aic != null ? ` · AIC ${formatNumber(bc.aic, { sig: 5 })}` : ""}.
          {bc.note ? ` ${bc.note}` : ""} Choose a cause to see its 95% band.
        </p>
      </div>
    </div>
  );
}

// "#2f6df6" → "rgba(47,109,246,a)".
function hexA(hex, a) {
  const h = hex.replace("#", "");
  const n = parseInt(h.length === 3 ? h.split("").map((c) => c + c).join("") : h, 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
}

// Covariates (#65): each covariate's rate ratio with its 95% interval, on a
// log scale with 1 (no effect) marked, and each one in words.
export function CovariatePanel({ r, name }) {
  const coefs = (r.coefficients || []).filter((c) => c.ratio != null);
  const labels = coefs.map((c) => c.name.replace(": ", " "));
  const traces = [{
    type: "scatter",
    mode: "markers",
    x: coefs.map((c) => c.ratio),
    y: labels,
    marker: { color: DATA_INK, size: 10, line: { color: "#fff", width: 2 } },
    error_x: {
      type: "data", symmetric: false, thickness: 2, width: 0, color: DATA_INK,
      array: coefs.map((c) => (c.ratio_ci ? c.ratio_ci[1] - c.ratio : 0)),
      arrayminus: coefs.map((c) => (c.ratio_ci ? c.ratio - c.ratio_ci[0] : 0)),
    },
    hovertemplate: coefs.map((c) => `${c.name}: ${ratioText(c.ratio)}${c.ratio_ci ? ` (95% ${ratioCiText(c.ratio_ci)})` : ""}<extra></extra>`),
    showlegend: false,
  }];
  const layout = {
    height: Math.max(220, 90 + 70 * coefs.length),
    margin: { t: 8, r: 16, b: 44, l: 120 },
    xaxis: { title: { text: "Failure rate ratio (log scale)" }, type: "log", showgrid: true },
    yaxis: { type: "category", autorange: "reversed", showgrid: false },
    shapes: [referenceShape({ x: 1 })],
  };
  const cats = (r.covariates || []).filter((m) => m.kind === "category");
  return (
    <div className="detail-panel life-panel">
      <div className="plotwrap">
        <Plot data={traces} layout={layout} download={`${name || "Recurrent model"} — covariate effects`} />
        <p className="plot-caption">
          Each point is how many times as often failures come, the line its 95% interval; the dashed line at 1 is
          no effect.
        </p>
      </div>
      <div className="aside rec-aside">
        <div className="gof-card">
          <div className="gofh">Effects</div>
          {(r.coefficients || []).map((c) => (
            <div className="rec-effect" key={c.name}>
              <div className="rec-effect-head">
                <span>{c.name.replace(": ", " ")}</span>
                {c.effect && (
                  <Chip tone={effectTone(c.effect)}>
                    {c.effect === "higher" ? "More failures" : c.effect === "lower" ? "Fewer failures" : "Unclear"}
                  </Chip>
                )}
              </div>
              <p>{c.reading}</p>
            </div>
          ))}
        </div>
        {cats.length > 0 && (
          <p className="life-method">
            {cats.map((m) => `${m.column} is compared with ${m.reference}`).join("; ")} (the level most systems have).
            Baseline: {r.baseline?.name || "Crow-AMSAA"}.
          </p>
        )}
      </div>
    </div>
  );
}

// Imperfect repair (#65): each system's chance of running a further time
// without a failure, from where its history leaves it, soonest first.
export function NextFailurePanel({ r, name }) {
  const nf = r.next_failure || {};
  const unit = String(r.unit || "").trim().toLowerCase();
  const traces = (nf.curves || []).map((c, k) => fitLine({
    x: nf.x, y: c.sf, name: c.system, line: { color: COLORWAY[k % COLORWAY.length], width: 1.75 },
  }));
  const layout = {
    height: PLOT_HEIGHT,
    margin: { t: 8, r: 12, b: 44 },
    legend: { ...LEGEND_IN, x: 0.985, xanchor: "right" },
    xaxis: { title: { text: `Time from now${unit ? ` (${unit})` : ""}` }, rangemode: "tozero" },
    yaxis: { title: { text: "Chance of no failure yet" }, range: [0, 1.02], tickformat: ".0%" },
  };
  return (
    <div className="detail-panel life-panel">
      <div className="plotwrap">
        <Plot data={traces} layout={layout} download={`${name || "Recurrent model"} — next failure`} />
      </div>
      <div className="aside rec-aside rec-aside-wide">
        <div className="gof-card">
          <div className="gofh life-card-head">
            <span>Next failure{unit ? <span className="gof-sub">{unit} from now</span> : null}</span>
          </div>
          <div className="rs-table-wrap rec-nf-scroll">
            <table className="mini-table rec-nf-table">
              <thead><tr><th>System</th><th>Failures</th><th>Median</th><th>10% by</th></tr></thead>
              <tbody>
                {(nf.units || []).map((u) => (
                  <tr key={u.system} title={`${u.system}: age ${formatNumber(u.age)}, ${formatNumber(u.since_failure)} since its last failure${u.virtual_age != null ? `, virtual age ${formatNumber(u.virtual_age)}` : ""}.`}>
                    <td>{u.system}</td>
                    <td>{u.failures}</td>
                    <td>{u.median != null ? formatNumber(u.median, { sig: 3 }) : "—"}</td>
                    <td>{u.b10 != null ? formatNumber(u.b10, { sig: 3 }) : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
        <p className="life-method">
          Median: half the chance of a failure by then. 10% by: a 1-in-10 chance of a failure by then. {nf.note}
        </p>
      </div>
    </div>
  );
}
