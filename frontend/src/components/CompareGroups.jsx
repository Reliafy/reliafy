import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import Select from "./Select.jsx";
import Plot from "./Plot.jsx";
import { COLORWAY, referenceShape } from "../plotTheme.js";
import { compareGroups } from "../api.js";
import { unitInText } from "./unitText.js";
import { guessCompareColumns, guessUnit } from "../datasetGuess.js";
import { guessStatus, statusMeaning, statusValues, statusValuesWithBlank } from "../lifeData.js";
import StatusMeanings from "./StatusMeanings.jsx";
import ResultSummary, { ResultDetails } from "./ui/ResultSummary.jsx";
import { ciPct } from "../levels.js";
import "./Datasets.css";

// Compare groups within one dataset (#175): split by a column, overlay each
// group's Kaplan–Meier curve, test the difference (log-rank; Gray's test per
// failure mode) and say how much longer one group lasts on average (RMST).
// Non-parametric — nothing is fitted. Laid out like a model page: the answer
// and its plot on the left, the inputs in a panel on the right.

// Groups take the theme's series colours in order.
const COLORS = COLORWAY;
const NARROW = "(max-width: 640px)";

const fmt = (v) =>
  v == null || !Number.isFinite(v)
    ? "—"
    : Math.abs(v) >= 1000
    ? Math.round(v).toLocaleString()
    : Number(v.toPrecision(3)).toString();
const fmtP = (p) => (p == null ? "—" : p < 0.001 ? "< 0.001" : p < 0.01 ? p.toFixed(3) : p.toFixed(2));

// Where to fit a model to rows that are unit histories, not one row per unit.
const HISTORY_FIT = {
  recurrent: { to: "/models/recurrent/new", label: "fit a repairable model", what: "repair history" },
  degradation: { to: "/models/degradation", label: "fit a degradation model", what: "measurements" },
  time_varying: {
    to: "/models/new", label: "fit a non-repairable model with covariates that change over time",
    what: "stretches of life at different covariate values",
  },
};

// The status fields for a column: guessed from its values, as the fit's Data
// step guesses them; without values (an older dataset), the 0/1 direction.
function statusFor(column, facts, invert) {
  if (!column) return { c_invert: false, c_map: null };
  if (facts[column]?.values) return guessStatus(column, facts);
  return { c_invert: !!invert, c_map: null };
}

// Failed and still-running rows under the meanings chosen; null while a value
// has none (or the column's values aren't known).
function statusCounts(fact, status) {
  if (!fact?.values) return null;
  const out = { failed: 0, running: 0 };
  for (const v of statusValues(statusValuesWithBlank(fact.values, 0))) {
    const m = statusMeaning(v.label, status);
    if (m === 0) out.failed += v.rows;
    else if (m === 1) out.running += v.rows;
    else return null;
  }
  return out;
}

export default function CompareGroups({ dataset, splitBy, onClose }) {
  const columns = dataset.columns || [];
  const distinct = dataset.profile?.distinct;
  const repeated = dataset.profile?.repeated_units;
  const first = useMemo(
    () => guessCompareColumns(columns, { distinct: distinct || {}, splitBy }),
    [columns, distinct, splitBy]
  );
  // Each column's few values (the dataset's profile), so a status column of
  // words ("Failed", "Removed, OK") is read as the fit reads it.
  const facts = useMemo(() => Object.fromEntries(columns.map((c) => [c.name, {
    dtype: c.dtype, values: dataset.profile?.values?.[c.name] || null,
  }])), [columns, dataset.profile]);
  // The status column the data has is preselected: still-running units are
  // never counted as failures by default.
  const firstCensor = dataset.profile?.status_column || first.censor;
  const [timeCol, setTimeCol] = useState(first.time);
  const [groupCol, setGroupCol] = useState(first.group);
  const [censorCol, setCensorCol] = useState(firstCensor);
  // What each status value means: { c_invert, c_map } (lifeData.js). A
  // "failed"-style 0/1 column is 1 = failed, so it starts inverted.
  const [status, setStatus] = useState(() => statusFor(firstCensor, facts, first.invert));
  const [causeCol, setCauseCol] = useState("");
  // The dataset's own unit ("hour" → "hours") when it names one.
  // Failing that, the unit the last model fitted to it used, or the time column's name ("Hours run").
  const [unit, setUnit] = useState(first.unit || (dataset.time_unit ? `${String(dataset.time_unit).toLowerCase()}s` : "")
    || unitInText(dataset.last_mapping?.unit || "") || unitInText(guessUnit(first.time) || ""));
  const [tau, setTau] = useState("");
  const [reference, setReference] = useState(null);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [about, setAbout] = useState(false);

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
        c_invert: !!censorCol && !!status.c_invert,
        c_map: censorCol && status.c_map ? status.c_map : null,
        // "none: all failed" said in so many words: otherwise the server reads
        // a status column the data has rather than count every row as failed.
        all_failed: !censorCol && !causeCol,
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

  // A new censor column: guess what its values mean again.
  const pickCensor = (v) => {
    setCensorCol(v);
    setStatus(statusFor(v, facts, guessCompareColumns(columns.filter((c) => c.name === v)).invert));
  };
  const readAs = censorCol ? statusCounts(facts[censorCol], status) : null;
  const unread = censorCol && facts[censorCol]?.values
    ? statusValues(facts[censorCol].values).filter((v) => statusMeaning(v.label, status) === null) : [];

  const fit = repeated && HISTORY_FIT[repeated.kind];

  return (
    <section className="card cg-card" aria-labelledby="cg-title">
      <div className="cg-head">
        <h2 id="cg-title">
          Compare groups
          <button
            type="button"
            className="ref-link"
            aria-expanded={about}
            aria-label="How the comparison works"
            title="How the comparison works"
            onClick={() => setAbout(!about)}
          >
            ?
          </button>
        </h2>
        {onClose && <button className="ghost sm" onClick={onClose}>Close</button>}
      </div>
      {about && (
        <p className="muted-line cg-about">
          Split the data by a column (supplier, site, design revision) to see whether one group lasts
          longer. Nothing is fitted: each group gets its Kaplan–Meier curve, the log-rank test says whether
          the difference is real, and the average life over a common window (RMST) says by how much.
        </p>
      )}
      {fit && (
        <p className="calc-warn cg-warn">
          Each <b>{repeated.column}</b> has several rows here (its {fit.what}), but Compare treats every
          row as a separate unit, so its answer would mislead. To model this data,{" "}
          <Link to={`${fit.to}${repeated.kind !== "degradation" ? `?dataset=${encodeURIComponent(dataset.id)}` : ""}`}>
            {fit.label}
          </Link>.
        </p>
      )}

      <div className="cg-panel">
        <div className="cg-main">
          {error && <div className="error">{error}</div>}
          {result ? (
            <CompareGroupsResult
              result={result}
              reference={reference}
              onReference={(v) => { setReference(v); run(v); }}
            />
          ) : (
            !error && (
              <p className="cg-empty muted-line">
                {loading ? "Comparing…" : "Choose how to split the data, then Compare."}
              </p>
            )
          )}
        </div>

        <aside className="cg-aside" aria-label="Comparison settings">
          <label className="calc-t">
            <span>Time column</span>
            <Select value={timeCol} onChange={setTimeCol} options={colOptions} />
          </label>
          <label className="calc-t">
            <span>Split by</span>
            <Select value={groupCol} onChange={setGroupCol} options={colOptions} />
          </label>
          <label className="calc-t">
            <span>Failed or still running?</span>
            <Select value={censorCol} onChange={pickCensor} options={optional(causeCol ? "— none: blank mode = running —" : "— none: every row failed —")} />
          </label>
          {censorCol && facts[censorCol]?.values ? (
            <StatusMeanings column={censorCol} values={facts[censorCol].values} mapping={status}
                            onChange={(m) => setStatus({ c_invert: !!m.c_invert, c_map: m.c_map || null })} />
          ) : censorCol ? (
            <label className="map-invert cg-invert">
              <input type="checkbox" checked={!!status.c_invert}
                     onChange={(e) => setStatus({ c_invert: e.target.checked, c_map: null })} />
              <span>1 = failed here (invert it)</span>
            </label>
          ) : null}
          {readAs && (
            <p className="muted-line cg-read-as">
              Read as: <b>{readAs.failed.toLocaleString()} failed</b>, <b>{readAs.running.toLocaleString()} still running</b>
            </p>
          )}
          {!censorCol && !causeCol && (
            <p className="muted-line cg-read-as">Every row is counted as a failure.</p>
          )}
          <label className="calc-t">
            <span>Failure mode (optional)</span>
            <Select value={causeCol} onChange={setCauseCol} options={optional("— none —")} />
          </label>
          <div className="cg-pair">
            <label className="calc-t">
              <span>Unit</span>
              <input type="text" placeholder="e.g. hours" value={unit} onChange={(e) => setUnit(e.target.value)} />
            </label>
            <label className="calc-t">
              <span>Window</span>
              <input type="number" inputMode="decimal" min="0" placeholder="auto" value={tau} onChange={(e) => setTau(e.target.value)} />
            </label>
          </div>
          <button className="cg-run" onClick={() => run(null)} disabled={loading || !timeCol || !groupCol || unread.length > 0}
                  title={unread.length ? "Say what each status value means first" : undefined}>
            {loading ? "Comparing…" : "Compare"}
          </button>
        </aside>
      </div>
    </section>
  );
}

function CompareGroupsResult({ result, reference, onReference }) {
  const u = result.unit ? ` ${unitInText(result.unit)}` : "";
  const colorOf = Object.fromEntries(result.groups.map((g, i) => [g.group, COLORS[i % COLORS.length]]));
  const diffs = Object.fromEntries(result.rmst_differences.map((d) => [d.group, d]));
  const v = result.verdict;

  const traces = result.groups.map((g) => ({
    x: g.curve.x, y: g.curve.R, type: "scatter", mode: "lines", name: g.group,
    line: { color: colorOf[g.group], width: 2, shape: "hv" },
    hovertemplate: `${g.group}<br>t = %{x:,.4~g}${u}<br>R = %{y:.3f}<extra></extra>`,
  }));
  // A phone has room for about four ticks: 1.5k, not 1,500.
  const narrow = typeof window !== "undefined" && !!window.matchMedia?.(NARROW).matches;
  const xMax = Math.max(0, ...result.groups.flatMap((g) => g.curve.x));
  const layout = {
    height: 380,
    showlegend: true,
    xaxis: {
      title: { text: `Time${result.unit ? ` (${result.unit})` : ""}` },
      rangemode: "tozero",
      ...(narrow && xMax >= 1000 ? { tickformat: "~s" } : {}),
    },
    yaxis: { title: { text: "Reliability, R(t)" }, range: [0, 1.02] },
    shapes: [referenceShape({ x: result.tau, line: { dash: "dot" } })],
    annotations: [{
      x: result.tau, y: 1, yref: "paper", text: "window", showarrow: false,
      xanchor: "right", yanchor: "top", font: { size: 12 },
    }],
  };

  return (
    <div className="cg-result">
      {/* A plain statement either way: "no clear difference" is an answer,
          not a warning. */}
      <ResultSummary
        tone="neutral"
        sentence={v.text}
        stats={
          // Two groups: each one's average life over the window; more are in
          // the table.
          result.groups.length === 2
            ? result.groups.map((g) => ({ label: `Average life, ${g.group}`, value: `${fmt(g.rmst)}${u}` }))
            : []
        }
      />

      {result.read_as && (
        <p className="muted-line cg-read-as">
          Read as {result.read_as.failed.toLocaleString()} failed, {result.read_as.running.toLocaleString()} still
          running{result.read_as.status_column ? ` (from “${result.read_as.status_column}”)`
            : result.read_as.cause_column ? ` (a blank “${result.read_as.cause_column}” is still running)` : ": every row counted as a failure"}.
        </p>
      )}
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
              <th>Average life ({ciPct(result)} CI)</th>
              <th>
                {result.groups.length > 2 ? (
                  <span className="cg-ref">
                    vs
                    <Select
                      className="cg-ref-sel"
                      title="Measure differences from"
                      value={reference}
                      onChange={onReference}
                      options={result.groups.map((g) => g.group)}
                    />
                  </span>
                ) : (
                  <>vs {result.reference}</>
                )}{" "}
                ({ciPct(result)} CI)
              </th>
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

      <ResultDetails summary="Tests of the difference">
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
        <p className="rs-note">
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
                <p className="rs-note">
                  Each row asks whether the groups' chance of failing by that mode differs, with the other
                  modes competing.{result.competing_risks.note ? ` ${result.competing_risks.note}` : ""}
                </p>
              </>
            ) : (
              <p className="rs-note">{result.competing_risks.reason}</p>
            )}
          </>
        )}

        {result.notes?.length > 0 && (
          <ul className="cg-notes">
            {result.notes.map((n) => <li key={n}>{n}</li>)}
          </ul>
        )}
      </ResultDetails>
    </div>
  );
}
