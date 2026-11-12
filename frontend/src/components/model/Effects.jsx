// The Effects tab (regressions, covariates that change over time, condition
// and life): what changes the life. A chart of each covariate's ratio with
// its 90% interval (a "forest" chart: 1 means no effect), each effect in
// words, and a panel with the baseline the ratios multiply.
import Plot from "../Plot.jsx";
import CiNote from "../CiNote.jsx";
import { paramView } from "../LifeSummary.jsx";
import { PlotCard, PlotPanel, ScrollCard } from "./ModelLayouts.jsx";
import { ACCENT, DATA_INK, logTicks, referenceShape } from "../../plotTheme.js";
import { formatNumber } from "../../format.js";
import { dataWords, effectText, forestRows } from "../../modelFrame.js";
import { fmtP } from "../RegressionChecks.jsx";
import { LEVEL_TEXT, ciPct, levelPct } from "../../levels.js";

const sentence = (s) => (s ? s[0].toUpperCase() + s.slice(1) : s);

// What the ratio multiplies, on the axis: below 1 a shorter life for a time
// ratio, a lower failure rate for a hazard ratio.
const AXIS_TITLE = {
  "time ratio": "Time ratio: the life ×",
  "odds ratio": "Odds ratio: the odds of having failed ×",
  "hazard ratio": "Hazard ratio: the failure rate ×",
};

export function ForestChart({ rows, ratioLabel, name, download }) {
  const additive = rows.some((r) => r.additive);
  const shown = rows.filter((r) => (additive ? r.value != null : r.ratio != null && r.ratio > 0));
  if (!shown.length) return <p className="muted-line">No covariate effects to chart.</p>;
  const label = (r) => (r.unit ? `${r.label || r.name} (per ${r.unit})` : r.label || r.name);
  const point = (r) => (additive ? r.value : r.ratio);
  const hasCi = (r) => r.lo != null && r.hi != null && (additive || (r.lo > 0 && r.hi > 0));
  const trace = {
    type: "scatter", mode: "markers",
    x: shown.map(point),
    y: shown.map(label),
    marker: { color: ACCENT, size: 10, symbol: "square" },
    error_x: {
      type: "data", symmetric: false, color: DATA_INK, thickness: 1.5, width: 6,
      array: shown.map((r) => (hasCi(r) ? r.hi - point(r) : 0)),
      arrayminus: shown.map((r) => (hasCi(r) ? point(r) - r.lo : 0)),
    },
    customdata: shown.map((r) => (hasCi(r) ? `${formatNumber(r.lo)} to ${formatNumber(r.hi)}` : "no interval")),
    hovertemplate: `%{y}: %{x:.3~g} (${rows[0]?.level || LEVEL_TEXT} %{customdata})<extra></extra>`,
    name: additive ? "Coefficient" : sentence(ratioLabel || "ratio"),
  };
  const values = shown.flatMap((r) => [point(r), r.lo, r.hi]).filter((v) => v != null && (additive || v > 0));
  const lo = additive ? 0 : Math.min(1, ...values);
  const hi = additive ? 0 : Math.max(1, ...values);
  const span = additive ? 0 : Math.log10(hi) - Math.log10(lo);
  const pad = Math.max(0.08, span * 0.12);
  // Labelled in full (0.4, not Plotly's "4" between decades).
  const ticks = additive ? null : logTicks(10 ** (Math.log10(lo) - pad), 10 ** (Math.log10(hi) + pad));
  const layout = {
    showlegend: false,
    margin: { t: 10, r: 16, b: 46, l: 12 },
    xaxis: additive
      ? { title: { text: "Coefficient (0 = no effect)" }, zeroline: false }
      : {
          type: "log",
          title: { text: `${AXIS_TITLE[ratioLabel] || sentence(ratioLabel || "ratio")} (1 = no effect)` },
          range: [Math.log10(lo) - pad, Math.log10(hi) + pad],
          ...(ticks ? { tickmode: "array", tickvals: ticks.tickvals, ticktext: ticks.ticktext } : {}),
        },
    yaxis: { type: "category", autorange: "reversed", automargin: true, showgrid: false, ticks: "" },
    shapes: [referenceShape(additive ? { x: 0, line: { dash: "dot" } } : { x: 1, line: { dash: "dot" } })],
  };
  return <Plot fill data={[trace]} layout={layout} download={download || `${name || "Model"} — effects`} />;
}

// The effects in words, with the p-value where the fit gives one.
function EffectWords({ rows, ratioLabel, readings }) {
  const items = readings?.length
    ? readings.map((r) => ({ key: r.name, text: r.text }))
    : rows.map((r) => ({ key: r.name, text: effectText(r, ratioLabel), p: r.p }));
  if (!items.length) return <p className="mf-note">This model has no covariates.</p>;
  return (
    <ul className="mf-effects-words">
      {items.map((it) => (
        <li key={it.key}>
          {it.text}
          {it.p != null && <span className="mf-effect-p"> p {it.p < 0.001 ? "" : "= "}{fmtP(it.p)}.</span>}
        </li>
      ))}
    </ul>
  );
}

const baseOf = (result) => ({
  ...result, distribution_id: String(result.distribution_id || "").replace(/_(ph|aft|po|ah|frailty)$/, ""),
});

// The panel beside the chart: the baseline the ratios multiply, the data,
// a frailty model's spread between groups.
function EffectsPanel({ result, split }) {
  const params = result.params || [];
  const base = baseOf(result);
  const data = result.tvc
    ? `${result.tvc.items?.toLocaleString()} items over ${result.tvc.rows?.toLocaleString()} rows`
      + (result.tvc.failures != null ? `, ${result.tvc.failures.toLocaleString()} failures` : "")
    : dataWords(result, split);
  const f = result.frailty;
  return (
    <>
      <div className="gof-card">
        <div className="gofh">{params.length ? "Baseline (every covariate at 0)" : "Model"}</div>
        {params.map((p) => {
          const v = paramView(base, p);
          return (
            <div className="gofr" key={p.name}>
              <span className="gk">{v.label}</span>
              <span className="gv-col">
                <span className="gv">{v.value}</span>
                {v.ci && <span className="param-ci">{ciPct(result)} {v.ci}</span>}
              </span>
            </div>
          );
        })}
        {!params.length && (
          <div className="gofr"><span className="gk">Baseline</span><span className="gv">none (semi-parametric)</span></div>
        )}
        {data && <div className="gofr"><span className="gk">Data</span><span className="gv">{data}</span></div>}
      </div>
      {f && (
        <div className="gof-card">
          <div className="gofh">Group effect</div>
          <div className="gofr"><span className="gk">Grouped by</span><span className="gv">{f.group_column} · {f.n_groups} groups</span></div>
          <div className="gofr">
            <span className="gk" title="How much the groups' hidden multipliers vary">Spread θ</span>
            <span className="gv-col">
              <span className="gv">{formatNumber(f.theta)}</span>
              {f.theta_ci && <span className="param-ci">{levelPct(f.theta_ci_level ?? 0.95)} {formatNumber(f.theta_ci[0])}–{formatNumber(f.theta_ci[1])}</span>}
            </span>
          </div>
          {f.reading && <p className="mf-note">{f.reading}</p>}
        </div>
      )}
      <CiNote params={params} note={result.ci_note} level={ciPct(result)} />
      <p className="life-method">
        {result.effect === "aft" || result.ratio_label === "time ratio"
          ? "A time ratio of 2 doubles the life; 0.5 halves it (the item ages twice as fast)."
          : result.ratio_label === "odds ratio"
          ? "An odds ratio of 2 doubles the odds of having failed by any age; 0.5 halves them."
          : result.ratio_label
          ? "A hazard ratio of 2 doubles the failure rate at any moment; 0.5 halves it."
          : "Additive effects: each coefficient adds to the failure rate."}
        {" "}Every coefficient, with its standard error, is in the Data tab.
      </p>
      {params.length > 1 && !result.tvc && (
        <p className="life-method">
          One shape for every unit: the covariates stretch or shrink the life, but the way failures spread out
          with age is the same for every group. If groups may wear out differently, fit each group on its own and
          compare them.
        </p>
      )}
    </>
  );
}

export default function Effects({ result, name, split }) {
  const rows = forestRows(result);
  return (
    <PlotPanel
      plot={
        <PlotCard title={result.ratio_label ? `Each covariate's ${result.ratio_label}, with its ${ciPct(result)} interval` : `Each covariate's effect, with its ${ciPct(result)} interval`}>
          <ForestChart rows={rows} ratioLabel={result.ratio_label} name={name || result.distribution} />
        </PlotCard>
      }
      below={
        <ScrollCard title="In words" className="mf-effects-table">
          <EffectWords rows={rows} ratioLabel={result.ratio_label} readings={result.tvc?.readings} />
        </ScrollCard>
      }
      side={<EffectsPanel result={result} split={split} />}
    />
  );
}

// Condition and life: its hazard ratios (the reading, and each covariate at
// the same reading), charted and in words.
export function JointEffects({ results, name }) {
  const rows = forestRows(results);
  return (
    <PlotPanel
      plot={
        <PlotCard title={`What changes the risk: each hazard ratio, with its ${ciPct(results)} interval`}>
          <ForestChart rows={rows} ratioLabel="hazard ratio" name={name} />
        </PlotCard>
      }
      below={
        <ScrollCard title="In words" className="mf-effects-table">
          {rows.length ? (
            <ul className="mf-effects-words">{rows.map((r) => <li key={r.name}>{r.text}</li>)}</ul>
          ) : <p className="mf-note">No risk coefficients.</p>}
        </ScrollCard>
      }
      side={
        <>
          <div className="gof-card">
            <div className="gofh">The risk part</div>
            <div className="gofr"><span className="gk">Reading</span><span className="gv">{results.marker || "reading"}{results.marker_unit ? ` (${results.marker_unit})` : ""}</span></div>
            <div className="gofr"><span className="gk">Covariates</span><span className="gv">{(results.hazard_covariates || results.covariates || []).join(", ") || "none"}</span></div>
            <div className="gofr"><span className="gk">Baseline</span><span className="gv">Weibull</span></div>
          </div>
          <p className="life-method">
            A hazard ratio of 2 doubles the failure rate at any moment; 0.5 halves it. The reading's ratio is per
            unit of the reading; a covariate's is at the same reading. Every parameter is in the Data tab.
          </p>
        </>
      }
    />
  );
}
