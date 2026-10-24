import Plot from "./Plot.jsx";
import Chip from "./ui/Chip.jsx";
import {
  COLORWAY, DATA_INK, NEUTRAL_BAND_FILL, band, dataLine, dataPoints, fitLine,
} from "../plotTheme.js";
import { formatNumber } from "../format.js";
import { ciText, effectTone, familyOf } from "../recurrentResults.js";
import { ForestChart } from "./model/Effects.jsx";
import { PlotCard, PlotPanel, ScrollCard, TablePanel } from "./model/ModelLayouts.jsx";

// The charts of a repairable model's tabs, each filling its box in the model
// frame (components/model/): the mean cumulative function (all failures, or
// by cause), the covariates' effects and each system's next failure.

// Inside the plot, top left: a mean cumulative function rises from bottom
// left to top right, so that corner is empty.
const LEGEND_IN = {
  orientation: "v", x: 0.015, xanchor: "left", y: 0.985, yanchor: "top", bgcolor: "rgba(255,255,255,0.85)",
};
const MARGIN = { t: 8, r: 12, b: 44 };

export const xTitle = (unit) => (unit ? `Time (${String(unit).toLowerCase()})` : "Time");

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
      marker: { size: 5, line: { width: 0 } }, name: "Failures so far (per system)",
    }));
  }
  if (fam === "regression" && groups.length) {
    groups.forEach((g, k) => traces.push(fitLine({ x: g.x, y: g.mcf, name: g.label, line: { color: COLORWAY[k % COLORWAY.length] } })));
  } else if (fit.x) {
    const label = fit.simulated ? `${r.model?.name || "Fitted"} (simulated)` : r.model?.name || "Fitted";
    traces.push(fitLine({ x: fit.x, y: fit.mcf, name: label }));
  }
  const layout = {
    margin: MARGIN,
    legend: LEGEND_IN,
    xaxis: { title: { text: xTitle(r.unit) }, rangemode: "tozero" },
    yaxis: { title: { text: "Cumulative failures per system (MCF)" }, rangemode: "tozero" },
  };
  return <Plot fill data={traces} layout={layout} download={`${name || r.model?.name || "Recurrent model"} — MCF`} />;
}

// "#2f6df6" → "rgba(47,109,246,a)".
function hexA(hex, a) {
  const h = hex.replace("#", "");
  const n = parseInt(h.length === 3 ? h.split("").map((c) => c + c).join("") : h, 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
}

// Failures by cause: each cause's MCF, and the band of the one chosen (the
// first when none is).
export function CausesPlot({ r, name, chosen }) {
  const causes = r.by_cause?.causes || [];
  const pick = causes.some((c) => c.label === chosen) ? chosen : causes[0]?.label;
  const traces = [];
  causes.forEach((c, k) => {
    const color = COLORWAY[k % COLORWAY.length];
    if (c.label === pick && c.mcf.lower && c.mcf.upper) {
      traces.push(bandTrace(c.mcf, { name: `${c.label}: 95% band`, fillcolor: hexA(color, 0.12) }));
    }
    traces.push(dataLine({
      x: c.mcf.x, y: c.mcf.mcf, name: c.label,
      line: { color, width: c.label === pick ? 2.25 : 1.5, shape: "hv" },
    }));
  });
  const layout = {
    margin: MARGIN,
    legend: LEGEND_IN,
    xaxis: { title: { text: xTitle(r.unit) }, rangemode: "tozero" },
    yaxis: { title: { text: "Cumulative failures per system" }, rangemode: "tozero" },
  };
  return <Plot fill data={traces} layout={layout} download={`${name || "Recurrent model"} — MCF by cause`} />;
}

// The Effects tab (covariate models): each covariate's rate ratio with its 95%
// interval (1 is no effect), each one in words, and the baseline beside them.
export function RecurrentEffects({ r, name }) {
  const coefs = r.coefficients || [];
  const rows = coefs.filter((c) => c.ratio != null).map((c) => ({
    name: c.name.replace(": ", " "), ratio: c.ratio, lo: c.ratio_ci?.[0] ?? null, hi: c.ratio_ci?.[1] ?? null,
  }));
  const cats = (r.covariates || []).filter((m) => m.kind === "category");
  const shape = (r.params || []).find((p) => p.name === (r.baseline?.id === "duane" ? "alpha" : "beta"));
  return (
    <PlotPanel
      sideClassName="rec-side"
      plot={
        <PlotCard title="How many times as often failures come, for each covariate, with its 95% interval">
          <ForestChart rows={rows} ratioLabel="failure rate ratio" name={name} download={`${name || "Recurrent model"} — covariate effects`} />
        </PlotCard>
      }
      below={
        <ScrollCard title="In words" className="mf-effects-table">
          <ul className="mf-effects-words">
            {coefs.map((c) => (
              <li key={c.name} className="rec-effect-line">
                {c.effect && (
                  <Chip tone={effectTone(c.effect)}>
                    {c.effect === "higher" ? "More failures" : c.effect === "lower" ? "Fewer failures" : "Unclear"}
                  </Chip>
                )}
                <span>{c.reading}</span>
              </li>
            ))}
          </ul>
        </ScrollCard>
      }
      side={
        <>
          <div className="gof-card">
            <div className="gofh">Baseline</div>
            <div className="gofr"><span className="gk">Model</span><span className="gv">{r.baseline?.name || "Crow-AMSAA"}</span></div>
            {shape && (
              <div className="gofr">
                <span className="gk">Shape {r.baseline?.id === "duane" ? "α" : "β"}</span>
                <span className="gv-col">
                  <span className="gv">{formatNumber(shape.value, { sig: 3 })}</span>
                  {ciText(shape.ci) && <span className="param-ci">95% {ciText(shape.ci)}</span>}
                </span>
              </div>
            )}
            {cats.map((m) => (
              <div className="gofr" key={m.column}><span className="gk">{m.column} compared with</span><span className="gv">{m.reference}</span></div>
            ))}
          </div>
          <p className="life-method">
            A ratio of 2 means failures come twice as often; 0.5, half as often. A text covariate is compared with the
            level most systems have. Every coefficient is in the Data tab.
          </p>
        </>
      }
    />
  );
}

// Imperfect repair: each system's chance of running a further time without a
// failure, from where its history leaves it, soonest first.
export function NextFailureView({ r, name }) {
  const nf = r.next_failure || {};
  const unit = String(r.unit || "").trim().toLowerCase();
  const traces = (nf.curves || []).map((c, k) => fitLine({
    x: nf.x, y: c.sf, name: c.system, line: { color: COLORWAY[k % COLORWAY.length], width: 1.75 },
  }));
  const layout = {
    margin: MARGIN,
    legend: { ...LEGEND_IN, x: 0.985, xanchor: "right" },
    xaxis: { title: { text: `Time from now${unit ? ` (${unit})` : ""}` }, rangemode: "tozero" },
    yaxis: { title: { text: "Chance of no failure yet" }, range: [0, 1.02], tickformat: ".0%" },
  };
  return (
    <TablePanel
      className="rec-next"
      main={
        <PlotCard title="Each system's chance of running on without a failure">
          <Plot fill data={traces} layout={layout} download={`${name || "Recurrent model"} — next failure`} />
        </PlotCard>
      }
      side={
        <>
          <ScrollCard title="Next failure" sub={unit ? `${unit} from now, soonest first` : "soonest first"}>
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
          </ScrollCard>
          <p className="life-method mf-flex-none">
            Median: half the chance of a failure by then. 10% by: a 1-in-10 chance of a failure by then. {nf.note}
          </p>
        </>
      }
    />
  );
}
