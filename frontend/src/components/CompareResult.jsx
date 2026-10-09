import Plot from "./Plot.jsx";
import ResultSummary, { ResultDetails } from "./ui/ResultSummary.jsx";
import { COLORWAY, referenceShape } from "../plotTheme.js";
import { formatWithUnit } from "../format.js";
import { unitInText } from "./unitText.js";

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

const fmtP = (p) => (p == null ? "—" : p < 1e-4 ? p.toExponential(2) : p.toFixed(4));

// The verdict in one sentence, from its parts (the server's text also carries
// the medians, which are tiles here).
function verdictSentence(result, unit) {
  const v = result.verdict;
  const la = result.a.label;
  const lb = result.b.label;
  if (v.more_reliable === "a" || v.more_reliable === "b") {
    const [win, lose] = v.more_reliable === "a" ? [la, lb] : [lb, la];
    return <><b>{win}</b> is more reliable than {lose} across the range.</>;
  }
  if (v.more_reliable === "tie") return <>{la} and {lb} are effectively the same.</>;
  if (v.more_reliable === "mixed" && v.crossover_time != null) {
    // Which is ahead first: where they first differ by a reliability point.
    const sa = result.a.sf || [];
    const sb = result.b.sf || [];
    const i = sa.findIndex((x, k) => x != null && sb[k] != null && Math.abs(x - sb[k]) >= 0.01);
    const [before, after] = i < 0 || sa[i] > sb[i] ? [la, lb] : [lb, la];
    return (
      <>
        The curves cross at <b>≈ {formatWithUnit(v.crossover_time, unit)}</b>: <b>{before}</b> is more
        reliable before it, <b>{after}</b> after.
      </>
    );
  }
  return v.text;
}

// Presentational renderer for a two-model comparison result — used by the live
// tool and by saved analyses. Answer first (#311): the verdict in a sentence,
// the medians as tiles, the reliability curves, then the metric table and the
// difference tests under Details. ``actions`` (the live tool's Save) sits
// with the answer.
export default function CompareResult({ result, name = null, actions = null }) {
  const u = result?.unit ? ` (${result.unit})` : "";
  const unit = result?.unit ? unitInText(result.unit) : "";
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

  const tests = result.tests;
  const tested = tests?.available;
  const primary = tested ? tests.results.find((r) => r.id === tests.primary) || tests.results[0] : null;
  const mixed = result.verdict.more_reliable === "mixed";
  const restricted = result.a.metrics.mttf_restricted || result.b.metrics.mttf_restricted;
  const stats = [
    { label: `Median, ${result.a.label}`, value: formatWithUnit(result.a.metrics.median, unit) },
    { label: `Median, ${result.b.label}`, value: formatWithUnit(result.b.metrics.median, unit) },
    primary && { label: "Log-rank p-value", value: fmtP(primary.p_value) },
  ].filter(Boolean);

  return (
    <>
      <ResultSummary
        tone={mixed || (tested && !tests.significant) ? "caveat" : "neutral"}
        sentence={verdictSentence(result, unit)}
        stats={stats}
      >
        {tested &&
          (tests.significant
            ? `The difference is statistically significant (p < ${tests.alpha}): unlikely to be chance.`
            : `Not statistically significant (p ≥ ${tests.alpha}): the data don't establish a difference.`)}
      </ResultSummary>
      {actions && <div className="rs-actions">{actions}</div>}

      <Plot data={traces} layout={layout} download={`${name || `${result.a.label} vs ${result.b.label}`} — reliability`} />

      <ResultDetails>
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
              return (
                <tr key={m.id}>
                  <td className="calc-row-label">{m.label}{m.id === "mttf" && restricted ? " *" : ""}</td>
                  <td className={va != null && vb != null && va >= vb ? "strategy-best" : ""}>{fmt(va)}</td>
                  <td className={va != null && vb != null && vb > va ? "strategy-best" : ""}>{fmt(vb)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {restricted && (
          <p className="rs-note">
            * MTTF from non-parametric data is a restricted mean (area under the
            Kaplan–Meier curve) and can understate the true mean when the data
            is censored.
          </p>
        )}

        {tested ? (
          <div className="compare-tests">
            <h3 className="demo-h">Test of difference (log-rank)</h3>
            <table className="calc-table">
              <thead>
                <tr><th>Test</th><th>χ² statistic</th><th>dof</th><th>p-value</th></tr>
              </thead>
              <tbody>
                {tests.results.map((r) => (
                  <tr key={r.id}>
                    <td className="calc-row-label">{r.label}{r.id === tests.primary ? " ★" : ""}</td>
                    <td>{fmt(r.statistic)}</td>
                    <td>{r.dof}</td>
                    <td className={r.p_value < tests.alpha ? "strategy-best" : ""}>{fmtP(r.p_value)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="rs-note">
              H₀: the two have the same survival distribution. A small p-value
              (&lt; {tests.alpha}) rejects it — the difference is unlikely
              to be chance. Gehan–Wilcoxon weights early differences;
              Tarone–Ware is in between.
            </p>
          </div>
        ) : (
          tests && <p className="rs-note">{tests.reason}</p>
        )}
      </ResultDetails>
    </>
  );
}
