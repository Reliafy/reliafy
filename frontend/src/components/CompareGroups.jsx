import { useEffect, useMemo, useState } from "react";
import Select from "./Select.jsx";
import Plot from "./Plot.jsx";
import { COLORWAY, referenceShape } from "../plotTheme.js";
import { compareGroups } from "../api.js";
import { unitInText } from "./unitText.js";

// Compare groups within one dataset (#175): split by a column, overlay each
// group's Kaplan–Meier curve, test the difference (log-rank; Gray's test per
// failure mode) and say how much longer one group lasts on average (RMST).
// Non-parametric — nothing is fitted.

// Groups take the theme's series colours in order.
const COLORS = COLORWAY;
const CENSOR_RE = /^(c|cens|censor|censored|censoring|status|failed|failure|event|suspended|suspension|running)$/i;
const UNIT_RE = /^(hours?|hrs?|h|minutes?|mins?|days?|weeks?|months?|years?|cycles?|km|miles?|starts?)$/i;
const isNumeric = (dtype) => /int|float/.test(String(dtype));

const fmt = (v) =>
  v == null || !Number.isFinite(v)
    ? "—"
    : Math.abs(v) >= 1000
    ? Math.round(v).toLocaleString()
    : Number(v.toPrecision(3)).toString();
const fmtP = (p) => (p == null ? "—" : p < 0.001 ? "< 0.001" : p < 0.01 ? p.toFixed(3) : p.toFixed(2));

// First guesses for the column pickers.
function guessColumns(columns, splitBy) {
  const names = columns.map((c) => c.name);
  const censor = columns.find((c) => CENSOR_RE.test(c.name) && isNumeric(c.dtype))?.name || "";
  const time =
    columns.find((c) => isNumeric(c.dtype) && c.name !== censor && c.name !== splitBy)?.name || names[0] || "";
  const group =
    (splitBy && names.includes(splitBy) && splitBy) ||
    columns.find((c) => !isNumeric(c.dtype) && c.name !== time)?.name ||
    names.find((n) => n !== time && n !== censor) ||
    "";
  return { time, group, censor, unit: UNIT_RE.test(time) ? time.toLowerCase() : "" };
}

export default function CompareGroups({ dataset, splitBy, onClose }) {
  const columns = dataset.columns || [];
  const first = useMemo(() => guessColumns(columns, splitBy), [columns, splitBy]);
  const [timeCol, setTimeCol] = useState(first.time);
  const [groupCol, setGroupCol] = useState(first.group);
  const [censorCol, setCensorCol] = useState(first.censor);
  const [invert, setInvert] = useState(false);
  const [causeCol, setCauseCol] = useState("");
  const [unit, setUnit] = useState(first.unit);
  const [tau, setTau] = useState("");
  const [reference, setReference] = useState(null);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  const colOptions = columns.map((c) => ({ value: c.name, label: c.name, hint: c.dtype }));
  const optional = (label) => [{ value: "", label }, ...colOptions];

  const run = async (ref = reference) => {
    setLoading(true);
    setError(null);
    try {
      const t = tau === "" ? null : Number(tau);
      if (t != null && !(t > 0)) throw new Error("The window must be a positive time.");
      const out = await compareGroups(dataset.id, {
        time_column: timeCol,
        group_column: groupCol,
        censor_column: censorCol || null,
        c_invert: !!censorCol && invert,
        cause_column: causeCol || null,
        unit: unit || null,
        tau: t,
        reference: ref,
      });
      setResult(out);
      setReference(out.reference);
    } catch (e) {
      setError(e.message);
      setResult(null);
    } finally {
      setLoading(false);
    }
  };

  // A new split starts from the default reference group.
  useEffect(() => { setReference(null); }, [groupCol, timeCol]);

  return (
    <div className="card cg-card">
      <div className="cg-head">
        <div>
          <h2>Compare groups</h2>
          <p className="muted-line">
            Split the data by a column (supplier, site, design revision) to see whether one group lasts
            longer. Nothing is fitted: each group gets its Kaplan–Meier curve, the log-rank test says whether
            the difference is real, and the average life over a common window (RMST) says by how much.
          </p>
        </div>
        {onClose && (
          <button className="secondary" onClick={onClose}>Close</button>
        )}
      </div>

      <div className="cg-inputs">
        <label className="calc-t">
          <span>Time column</span>
          <Select value={timeCol} onChange={setTimeCol} options={colOptions} />
        </label>
        <label className="calc-t">
          <span>Split by</span>
          <Select value={groupCol} onChange={setGroupCol} options={colOptions} />
        </label>
        <label className="calc-t">
          <span>Censor column (optional)</span>
          <Select value={censorCol} onChange={setCensorCol} options={optional("— none: all failed —")} />
        </label>
        <label className="calc-t">
          <span>Failure mode (optional)</span>
          <Select value={causeCol} onChange={setCauseCol} options={optional("— none —")} />
        </label>
        <label className="calc-t">
          <span>Unit (optional)</span>
          <input type="text" placeholder="e.g. hours" value={unit} onChange={(e) => setUnit(e.target.value)} />
        </label>
        <label className="calc-t">
          <span>Window (optional)</span>
          <input type="number" min="0" placeholder="auto" value={tau} onChange={(e) => setTau(e.target.value)} />
        </label>
      </div>
      {censorCol && (
        <label className="map-invert cg-invert">
          <input type="checkbox" checked={invert} onChange={(e) => setInvert(e.target.checked)} />
          <span>My censor column uses 1 = failed (invert it)</span>
        </label>
      )}
      <div className="strategy-actions cg-actions">
        <button onClick={() => run(null)} disabled={loading || !timeCol || !groupCol}>
          {loading ? "Comparing…" : "Compare"}
        </button>
        {result && result.groups.length > 2 && (
          <label className="calc-t">
            <span>Measure differences from</span>
            <Select
              value={reference}
              onChange={(v) => { setReference(v); run(v); }}
              options={result.groups.map((g) => g.group)}
            />
          </label>
        )}
      </div>

      {error && <div className="error">{error}</div>}
      {result && <CompareGroupsResult result={result} />}
    </div>
  );
}

function CompareGroupsResult({ result }) {
  const u = result.unit ? ` ${unitInText(result.unit)}` : "";
  const colorOf = Object.fromEntries(result.groups.map((g, i) => [g.group, COLORS[i % COLORS.length]]));
  const diffs = Object.fromEntries(result.rmst_differences.map((d) => [d.group, d]));
  const v = result.verdict;

  const traces = result.groups.map((g) => ({
    x: g.curve.x, y: g.curve.R, type: "scatter", mode: "lines", name: g.group,
    line: { color: colorOf[g.group], width: 2, shape: "hv" },
    hovertemplate: `${g.group}<br>t = %{x:,.4~g}${u}<br>R = %{y:.3f}<extra></extra>`,
  }));
  const layout = {
    height: 380,
    showlegend: true,
    xaxis: { title: { text: `Time${result.unit ? ` (${result.unit})` : ""}` }, rangemode: "tozero" },
    yaxis: { title: { text: "Reliability, R(t)" }, range: [0, 1.02] },
    shapes: [referenceShape({ x: result.tau, line: { dash: "dot" } })],
    annotations: [{
      x: result.tau, y: 1, yref: "paper", text: "window", showarrow: false,
      xanchor: "right", yanchor: "top", font: { size: 12 },
    }],
  };

  return (
    <div className="cg-result">
      <div className={"strategy-reco" + (v.significant ? "" : " strategy-reco-warn")}>
        <span className="strategy-reco-icon">{v.significant ? "✓" : "≈"}</span>
        <span>{v.text}</span>
      </div>

      <Plot data={traces} layout={layout} />

      <div className="ds-section-h cg-h">Groups · average life over the first {fmt(result.tau)}{u}</div>
      <div className="demo-table-wrap">
        <table className="calc-table cg-table cg-wide">
          <thead>
            <tr>
              <th>{result.group_column || "Group"}</th>
              <th>Units</th>
              <th>Failed</th>
              <th>Median{u && ` (${result.unit})`}</th>
              <th>Average life (95% CI)</th>
              <th>vs {result.reference} (95% CI)</th>
            </tr>
          </thead>
          <tbody>
            {result.groups.map((g) => {
              const d = diffs[g.group];
              return (
                <tr key={g.group} className={v.significant && v.better === g.group ? "strategy-best" : ""}>
                  <td className="calc-row-label">
                    <span className="combo-dot" style={{ background: colorOf[g.group] }} />
                    {g.group}
                  </td>
                  <td>{g.units.toLocaleString()}</td>
                  <td>{g.failures.toLocaleString()}</td>
                  <td>{g.median == null ? "not reached" : fmt(g.median)}</td>
                  <td>{fmt(g.rmst)} <span className="cg-ci">({fmt(g.rmst_lower)} – {fmt(g.rmst_upper)})</span></td>
                  <td>
                    {d ? (
                      <>
                        {d.difference > 0 ? "+" : ""}{fmt(d.difference)}{" "}
                        <span className="cg-ci">({fmt(d.lower)} – {fmt(d.upper)})</span>
                      </>
                    ) : (
                      <span className="cg-ci">reference</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="ds-section-h cg-h">Is the difference real?</div>
      <div className="demo-table-wrap">
        <table className="calc-table cg-table">
          <thead>
            <tr><th>Test</th><th>χ²</th><th>dof</th><th>p-value</th></tr>
          </thead>
          <tbody>
            {result.tests.map((t) => (
              <tr key={t.id}>
                <td className="calc-row-label">{t.label}{t.id === "log-rank" ? " ★" : ""}</td>
                <td>{fmt(t.statistic)}</td>
                <td>{t.dof}</td>
                <td className={t.p_value < result.alpha ? "strategy-best" : ""}>{fmtP(t.p_value)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted-line">
        A p-value under {result.alpha} means the groups' lives differ by more than chance. Gehan–Wilcoxon
        weights early failures more; Tarone–Ware is in between. If the curves cross, trust the plot and the
        average-life difference over the log-rank test.
      </p>

      {result.competing_risks && (
        <>
          <div className="ds-section-h cg-h">By failure mode (Gray's test)</div>
          {result.competing_risks.available ? (
            <>
              <div className="demo-table-wrap">
                <table className="calc-table cg-table">
                  <thead>
                    <tr><th>Failure mode</th><th>Failures</th><th>χ²</th><th>p-value</th><th>Groups</th></tr>
                  </thead>
                  <tbody>
                    {result.competing_risks.results.map((r) => (
                      <tr key={r.mode}>
                        <td className="calc-row-label">{r.mode}</td>
                        <td>{r.failures.toLocaleString()}</td>
                        <td>{r.error ? "—" : fmt(r.statistic)}</td>
                        <td className={r.significant ? "strategy-best" : ""}>{r.error ? "—" : fmtP(r.p_value)}</td>
                        <td>{r.error ? "could not test" : r.significant ? "differ" : "no clear difference"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="muted-line">
                Each row asks whether the groups' chance of failing by that mode differs, with the other
                modes competing.{result.competing_risks.note ? ` ${result.competing_risks.note}` : ""}
              </p>
            </>
          ) : (
            <p className="muted-line">{result.competing_risks.reason}</p>
          )}
        </>
      )}

      {result.notes?.length > 0 && (
        <ul className="cg-notes">
          {result.notes.map((n) => <li key={n}>{n}</li>)}
        </ul>
      )}
    </div>
  );
}
