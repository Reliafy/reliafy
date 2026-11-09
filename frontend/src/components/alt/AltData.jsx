// The Data tab of an accelerated life model: what it was fitted to (each
// tested level with its units, failures and fitted life), how it was fitted,
// and every parameter with its interval.
import { Link } from "react-router-dom";
import { ScrollCard, TablePanel } from "../model/ModelLayouts.jsx";
import { formatNumber } from "../../format.js";
import { shapeParam, stressName } from "../../altFrame.js";
import { unitInText } from "../unitText.js";

// "85.9–203", or "−0.862 to −0.366" where a dash would read as a minus.
const ci = (pair) => {
  if (!Array.isArray(pair) || pair.length !== 2) return "—";
  const [lo, hi] = pair;
  const b = hi == null ? "∞" : formatNumber(hi, { sig: 4 });
  return lo < 0 || (hi != null && hi < 0) ? `${formatNumber(lo, { sig: 4 })} to ${b}` : `${formatNumber(lo, { sig: 4 })}–${b}`;
};

export default function AltData({ results, datasetId }) {
  const r = results || {};
  const unit = r.unit ? unitInText(r.unit) : "";
  const levels = r.levels || [];
  const hasFailures = levels.some((l) => Number.isFinite(l.failures));
  const shape = shapeParam(r);
  const counts = [
    ["Observations", r.n],
    ["Failed", r.n_failures],
    ["Still running", Number.isFinite(r.n_failures) && Number.isFinite(r.n) ? r.n - r.n_failures : null],
    ["Tested levels", levels.length],
  ];
  return (
    <TablePanel
      className="mf-l5-wide"
      main={
        <>
          <ScrollCard title="Each tested level" sub="its units and the life the model gives it" id="alt-levels-h">
            <table className="mini-table">
              <thead>
                <tr>
                  {(r.stresses || []).map((s) => <th key={s.key} className="mf-num">{stressName(s)}</th>)}
                  <th className="mf-num">Units</th>
                  {hasFailures && <th className="mf-num">Failed</th>}
                  <th className="mf-num">Life{unit ? ` (${unit})` : ""}</th>
                </tr>
              </thead>
              <tbody>
                {levels.map((l, i) => (
                  <tr key={i}>
                    {(l.stress || []).map((v, j) => <td key={j} className="mf-num">{formatNumber(v, { sig: 5 })}</td>)}
                    <td className="mf-num">{l.n}</td>
                    {hasFailures && <td className="mf-num">{l.failures ?? "—"}</td>}
                    <td className="mf-num">{formatNumber(l.characteristic_life, { sig: 4 })}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="mf-note">Life is the characteristic life: the {r.distribution === "Weibull" ? "time by which 63.2% have failed" : "life parameter"} at that level.</p>
          </ScrollCard>
          <ScrollCard title="Every parameter" sub="with 95% intervals" id="alt-params-h">
            <table className="mini-table">
              <thead><tr><th>Parameter</th><th className="mf-num">Estimate</th><th className="mf-num">95% interval</th></tr></thead>
              <tbody>
                {(r.params || []).map((p, i) => (
                  <tr key={p.name}>
                    <td>{i === 0 && shape ? shape.label : p.name}</td>
                    <td className="mf-num">{formatNumber(p.value, { sig: 4 })}</td>
                    <td className="mf-num">{ci(p.ci)}</td>
                  </tr>
                ))}
                {(r.coefficients || []).map((c) => (
                  <tr key={`c-${c.name}`}>
                    <td>{c.name} <span className="gof-sub">(life-stress)</span></td>
                    <td className="mf-num">{formatNumber(c.value, { sig: 4 })}</td>
                    <td className="mf-num">{ci(c.ci)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="mf-note">
              Wald intervals. The Calculator gives likelihood-ratio
              {(r.bounds_methods || []).includes("bootstrap") ? " and bootstrap" : ""} bounds at your use stress.
            </p>
          </ScrollCard>
        </>
      }
      side={
        <>
          <section className="gof-card mf-flex-none" aria-labelledby="alt-data-counts">
            <div className="gofh mf-card-head">
              <h3 className="mf-card-title" id="alt-data-counts">What it was fitted to</h3>
              {datasetId && <Link className="link" to={`/data/${datasetId}`}>Open the dataset ›</Link>}
            </div>
            {counts.filter(([, v]) => Number.isFinite(v)).map(([k, v]) => (
              <div className="gofr" key={k}><span className="gk">{k}</span><span className="gv">{Number(v).toLocaleString()}</span></div>
            ))}
            {(r.stresses || []).map((s, j) => (
              <div className="gofr" key={s.key || j}>
                <span className="gk">Stress {j + 1}</span>
                <span className="gv">{stressName(s)}{s.column && s.column !== s.label ? <span className="gof-sub"> · column {s.column}</span> : null}</span>
              </div>
            ))}
            {r.unit && <div className="gofr"><span className="gk">Time unit</span><span className="gv">{unit}</span></div>}
          </section>
          <section className="gof-card mf-flex-none" aria-labelledby="alt-data-how">
            <div className="gofh"><h3 className="mf-card-title" id="alt-data-how">How it was fitted</h3></div>
            <p className="mf-note">
              A {r.distribution} distribution whose life follows the {r.life_model} life-stress model, with one
              {r.distribution_id === "exponential" ? " failure rate per level" : " shape at every stress"}, fitted by
              maximum likelihood.
              {r.interval_censored ? " Inspection data: each failure lies between two inspections." : ""}
            </p>
            {(r.unit_warnings || []).map((w) => <p className="mf-note" key={w}>{w}</p>)}
          </section>
        </>
      }
    />
  );
}
