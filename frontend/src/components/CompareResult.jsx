import Plot from "./Plot.jsx";
import { COLORWAY, referenceShape } from "../plotTheme.js";

// Item A and B take the theme's first two series colours (the form uses them too).
export const COLORS = { a: COLORWAY[0], b: COLORWAY[1] };

const fmt = (v) =>
  v == null
    ? "—"
    : Math.abs(v) >= 1e-4 || v === 0
    ? Number(v).toPrecision(5)
    : Number(v).toExponential(3);

const METRICS = [
  { id: "b10", label: "B10 life" },
  { id: "median", label: "Median" },
  { id: "mttf", label: "MTTF" },
];

// Presentational renderer for a two-model comparison result — used by the live
// tool and by saved analyses.
export default function CompareResult({ result, name = null }) {
  const u = result?.unit ? ` (${result.unit})` : "";
  const traces = ["a", "b"].map((k) => ({
    x: result.time, y: result[k].sf, mode: "lines", type: "scatter",
    line: { color: COLORS[k], width: 2 }, name: result[k].label, connectgaps: false,
  }));
  const xc = result.verdict.crossover_time;
  const layout = {
    height: 420,
    showlegend: true,
    xaxis: { title: { text: `Time${u}` } },
    yaxis: { title: { text: "Reliability, R(t)" }, range: [0, 1.02] },
    shapes: xc == null ? [] : [referenceShape({ x: xc, line: { dash: "dot" } })],
  };

  return (
    <>
      <div className={"strategy-reco" + (result.verdict.more_reliable === "mixed" ? " strategy-reco-warn" : "")}>
        <span className="strategy-reco-icon">{result.verdict.more_reliable === "mixed" ? "⇄" : "✓"}</span>
        <span>{result.verdict.text}</span>
      </div>

      {result.tests &&
        (result.tests.available ? (
          <div className="compare-tests">
            <div className="rbd-section-head">Test of difference (log-rank)</div>
            <div className={"strategy-reco" + (result.tests.significant ? "" : " strategy-reco-warn")}>
              <span className="strategy-reco-icon">{result.tests.significant ? "✓" : "≈"}</span>
              <span>{result.tests.summary}</span>
            </div>
            <table className="calc-table">
              <thead>
                <tr><th>Test</th><th>χ² statistic</th><th>dof</th><th>p-value</th></tr>
              </thead>
              <tbody>
                {result.tests.results.map((r) => (
                  <tr key={r.id}>
                    <td className="calc-row-label">{r.label}{r.id === result.tests.primary ? " ★" : ""}</td>
                    <td>{fmt(r.statistic)}</td>
                    <td>{r.dof}</td>
                    <td className={r.p_value < result.tests.alpha ? "strategy-best" : ""}>
                      {r.p_value < 1e-4 ? r.p_value.toExponential(2) : r.p_value.toFixed(4)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="muted-line">
              H₀: the two have the same survival distribution. A small p-value
              (&lt; {result.tests.alpha}) rejects it — the difference is unlikely
              to be chance. Gehan–Wilcoxon weights early differences;
              Tarone–Ware is in between.
            </p>
          </div>
        ) : (
          <p className="muted-line compare-tests">{result.tests.reason}</p>
        ))}

      <Plot data={traces} layout={layout} download={`${name || `${result.a.label} vs ${result.b.label}`} — reliability`} />

      <table className="calc-table strategy-table">
        <thead>
          <tr>
            <th>Metric{u}</th>
            <th><span className="combo-dot" style={{ background: COLORS.a }} />{result.a.label}</th>
            <th><span className="combo-dot" style={{ background: COLORS.b }} />{result.b.label}</th>
          </tr>
        </thead>
        <tbody>
          {METRICS.map((m) => {
            const va = result.a.metrics[m.id];
            const vb = result.b.metrics[m.id];
            const restricted =
              m.id === "mttf" &&
              (result.a.metrics.mttf_restricted || result.b.metrics.mttf_restricted);
            return (
              <tr key={m.id}>
                <td className="calc-row-label">{m.label}{restricted ? " *" : ""}</td>
                <td className={va != null && vb != null && va >= vb ? "strategy-best" : ""}>{fmt(va)}</td>
                <td className={va != null && vb != null && vb > va ? "strategy-best" : ""}>{fmt(vb)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {(result.a.metrics.mttf_restricted || result.b.metrics.mttf_restricted) && (
        <p className="muted-line">
          * MTTF from non-parametric data is a restricted mean (area under the
          Kaplan–Meier curve) and can understate the true mean when the data
          is censored.
        </p>
      )}
    </>
  );
}
