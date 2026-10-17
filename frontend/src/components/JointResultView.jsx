import { useEffect, useMemo, useState } from "react";
import Plot from "./Plot.jsx";
import Chip from "./ui/Chip.jsx";
import SegmentedControl from "./ui/SegmentedControl.jsx";
import { getJointUnit, predictJointUnit } from "../api.js";
import { formatNumber } from "../format.js";
import { bandPair, dataPoints, fitLine, referenceShape } from "../plotTheme.js";
import { medianText, paramGroups, parseReadings, readingsText, riskText, riskTone } from "../joint.js";

const n3 = (v) => formatNumber(v);
const FAINT = "rgba(20, 23, 28, 0.18)";

function Params({ params }) {
  const groups = paramGroups(params);
  return (
    <div className="maint-scroll">
      <table className="calc-table joint-params">
        <thead>
          <tr>
            <th>Parameter</th>
            <th className="num">Estimate</th>
            <th className="num">95% interval</th>
            <th>What it means</th>
          </tr>
        </thead>
        {groups.map((g) => (
          <tbody key={g.part}>
            <tr className="joint-part"><th colSpan={4}>{g.label}</th></tr>
            {g.rows.map((p) => (
              <tr key={p.name}>
                <td><code>{p.name}</code></td>
                <td className="num">{n3(p.value)}</td>
                <td className="num">{p.lower == null ? "—" : `${n3(p.lower)} to ${n3(p.upper)}`}</td>
                <td className="muted">{p.meaning}</td>
              </tr>
            ))}
          </tbody>
        ))}
      </table>
    </div>
  );
}

function PathChart({ results, name }) {
  const path = results.path || {};
  const unit = results.unit || "";
  const marker = results.marker || "reading";
  const traces = [];
  (path.sample || []).forEach((s, i) => {
    traces.push({
      type: "scatter", mode: "lines+markers", x: s.ages, y: s.values,
      line: { color: FAINT, width: 1 }, marker: { color: FAINT, size: 4 },
      name: "Units' readings", legendgroup: "units", showlegend: i === 0, hovertext: s.id, hoverinfo: "text+x+y",
    });
  });
  if (path.x) {
    traces.push(...bandPair(path.x, path.lower, path.upper, { name: "95% of units' paths" }));
    traces.push(fitLine({ x: path.x, y: path.mean, name: "Mean path" }));
  }
  const layout = {
    height: 360,
    xaxis: { title: { text: `Age since new${unit ? ` (${unit})` : ""}` } },
    yaxis: { title: { text: `${marker}${results.marker_unit ? ` (${results.marker_unit})` : ""}` } },
    showlegend: true,
  };
  return <Plot data={traces} layout={layout} download={`${name || "Model"} — reading path`} />;
}

function SurvivalChart({ curve, unit, name, title, age = null }) {
  if (!curve?.x) return null;
  const traces = [];
  if (curve.sf_lower && curve.sf_upper) traces.push(...bandPair(curve.x, curve.sf_lower, curve.sf_upper, { name: "95% band" }));
  traces.push(fitLine({ x: curve.x, y: curve.sf, name: "Survival" }));
  const layout = {
    height: 320,
    xaxis: { title: { text: `Age since new${unit ? ` (${unit})` : ""}` } },
    yaxis: { title: { text: "Probability still running" }, range: [0, 1.02] },
    shapes: age != null ? [referenceShape({ x: age })] : [],
    showlegend: true,
  };
  return <Plot data={traces} layout={layout} download={`${name || "Model"} — ${title}`} />;
}

function MarkerChart({ pred, results, name }) {
  const m = pred.marker || {};
  const unit = results.unit || "";
  const marker = results.marker || "reading";
  const pts = pred.markers || [];
  const traces = [
    ...bandPair(m.x, m.lower, m.upper, { name: "95% interval of its path" }),
    fitLine({ x: m.x, y: m.mean, name: "Its path (smoothed, then projected)" }),
    dataPoints({ x: pts.map((p) => p[0]), y: pts.map((p) => p[1]), name: "Its readings" }),
  ];
  const layout = {
    height: 320,
    xaxis: { title: { text: `Age since new${unit ? ` (${unit})` : ""}` } },
    yaxis: { title: { text: `${marker}${results.marker_unit ? ` (${results.marker_unit})` : ""}` } },
    shapes: [referenceShape({ x: pred.age })],
    showlegend: true,
  };
  return <Plot data={traces} layout={layout} download={`${name || "Model"} — reading trajectory`} />;
}

function RiskCells({ row, n = 3 }) {
  return Array.from({ length: n }, (_, i) => (
    <td key={i} className="num">
      <Chip tone={riskTone(row.risk?.[i])}>{riskText(row.risk?.[i])}</Chip>
    </td>
  ));
}

function RiskTable({ results, selected, onPick }) {
  const rows = results.risk || [];
  const labels = results.horizons?.labels || [];
  const unit = results.unit || "";
  if (!rows.length) return <p className="muted-line">No units are still running in the data.</p>;
  return (
    <div className="maint-scroll">
      <table className="calc-table joint-risk">
        <thead>
          <tr>
            <th>Unit</th>
            <th className="num">Age{unit ? ` (${unit})` : ""}</th>
            {labels.map((l) => <th key={l} className="num">Fails in next {l}</th>)}
            <th className="num">Median life left</th>
            <th><span className="sr-only">View</span></th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id} className={selected === r.id ? "is-selected" : ""}>
              <td>{r.id}</td>
              <td className="num">{n3(r.age)}</td>
              <RiskCells row={r} n={labels.length} />
              <td className="num">{medianText(r, unit)}</td>
              <td><button type="button" className="link" onClick={() => onPick(r.id)}>View</button></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// One unit's updating prediction: a running unit of the fit, or one entered.
function UnitView({ modelId, results, name, unitId, onUnitId }) {
  const [mode, setMode] = useState("fitted");
  const [view, setView] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const covNames = results.covariates || [];
  const [entered, setEntered] = useState(() => ({
    age: "", readings: "", covariates: Object.fromEntries(covNames.map((c) => [c, String(results.typical_covariates?.[c] ?? "")])),
  }));
  const unit = results.unit || "";

  useEffect(() => {
    if (mode !== "fitted" || !unitId) return;
    let live = true;
    setBusy(true); setError(null);
    getJointUnit(modelId, unitId)
      .then((v) => live && setView(v))
      .catch((e) => live && setError(e.message))
      .finally(() => live && setBusy(false));
    return () => { live = false; };
  }, [modelId, unitId, mode]);

  const onPredict = async () => {
    const parsed = parseReadings(entered.readings);
    if (parsed.error) { setError(parsed.error); return; }
    setBusy(true); setError(null);
    try {
      const cov = Object.fromEntries(covNames.map((c) => [c, Number(entered.covariates[c])]));
      setView(await predictJointUnit(modelId, {
        age: entered.age === "" ? null : Number(entered.age), markers: parsed.readings, covariates: cov,
      }));
    } catch (e) { setError(e.message); setView(null); }
    finally { setBusy(false); }
  };

  const unitIds = (results.risk || []).map((r) => r.id);
  return (
    <div className="joint-unit">
      <SegmentedControl
        label="Which unit" size="sm" value={mode}
        onChange={(v) => { setMode(v); setView(null); setError(null); }}
        options={[{ value: "fitted", label: "A running unit" }, { value: "entered", label: "Enter a unit" }]}
      />
      {mode === "fitted" ? (
        unitIds.length ? (
          <label className="dist-field" style={{ maxWidth: 260 }}>
            <span className="dist-label">Unit</span>
            <select value={unitId || ""} onChange={(e) => onUnitId(e.target.value)} aria-label="Unit">
              <option value="">— choose —</option>
              {unitIds.map((id) => <option key={id} value={id}>{id}</option>)}
            </select>
          </label>
        ) : <p className="muted-line">No running units in the data: enter one instead.</p>
      ) : (
        <div className="joint-enter">
          <label className="dist-field">
            <span className="dist-label">Age now{unit ? ` (${unit}, since new)` : " (since new)"}</span>
            <input type="number" inputMode="decimal" min="0" step="any" value={entered.age}
                   onChange={(e) => setEntered({ ...entered, age: e.target.value })} />
          </label>
          {covNames.map((c) => (
            <label className="dist-field" key={c}>
              <span className="dist-label">{c}</span>
              <input type="number" inputMode="decimal" step="any" value={entered.covariates[c]}
                     onChange={(e) => setEntered({ ...entered, covariates: { ...entered.covariates, [c]: e.target.value } })} />
            </label>
          ))}
          <label className="dist-field joint-readings">
            <span className="dist-label">Readings so far: age and value, one per line</span>
            <textarea rows={4} value={entered.readings} placeholder={"0 2.1\n20 2.6\n40 3.0"}
                      onChange={(e) => setEntered({ ...entered, readings: e.target.value })} />
          </label>
          <div><button type="button" onClick={onPredict} disabled={busy}>{busy ? "Working…" : "Predict"}</button></div>
        </div>
      )}
      {error && <div className="card error" role="alert">{error}</div>}
      {busy && mode === "fitted" && <p className="hint">Working…</p>}
      {view && (
        <>
          <p className="joint-unit-sum" role="status">
            {view.unit_id ? <>Unit <b>{view.unit_id}</b>, </> : "This unit, "}
            age {n3(view.age)}{unit ? ` ${unit.toLowerCase()}` : ""}, {view.markers.length} reading{view.markers.length === 1 ? "" : "s"}.{" "}
            {(results.horizons?.labels || []).map((l, i) => `${riskText(view.risk?.[i])} chance of failing in the next ${l}`).join("; ")}.
            {" "}Median life left: {medianText(view, unit)}.
          </p>
          <div className="joint-charts">
            <div>
              <h3 className="joint-h3">Survival from now</h3>
              <SurvivalChart curve={view.prediction} unit={unit} name={name} title="unit survival" age={view.age} />
              <p className="hint">The curve starts at 1 at its age now: it has survived that far.</p>
            </div>
            <div>
              <h3 className="joint-h3">Its {results.marker || "reading"}</h3>
              <MarkerChart pred={view.prediction} results={results} name={name} />
            </div>
          </div>
          {mode === "fitted" && view.markers?.length > 0 && (
            <p className="hint">To try newer readings for this unit, enter it: <button type="button" className="link" onClick={() => {
              setEntered({ age: String(view.age), readings: readingsText(view.markers),
                covariates: Object.fromEntries(covNames.map((c) => [c, String(view.covariates?.[c] ?? "")])) });
              setMode("entered");
            }}>copy its readings</button>.</p>
          )}
        </>
      )}
    </div>
  );
}

// A fitted condition-based risk model: the answer (the running units at the
// highest risk), the risk table, a unit's updating prediction, the reading's
// path, a new unit's survival, the hazard ratios and the parameters.
export default function JointResultView({ results, modelId, name }) {
  const r = results || {};
  const unit = r.unit || "";
  const [unitId, setUnitId] = useState(() => r.risk?.[0]?.id || "");
  const top = useMemo(() => (r.risk || [])[0], [r.risk]);
  const mid = r.horizons?.labels?.[1];

  return (
    <div className="joint-result">
      <div className="card joint-answer">
        <p style={{ margin: 0 }}>
          {r.n_items} units ({r.n_events} failed, {r.n_running} still running), {r.n_readings} readings of{" "}
          {r.marker || "the reading"}; {r.path_label?.toLowerCase()} path ({r.path_formula}), Weibull risk.
        </p>
        {top && (
          <p style={{ margin: "6px 0 0" }}>
            Highest risk now: <b>unit {top.id}</b>, {riskText(top.risk?.[1])} chance of failing in the next {mid}.
          </p>
        )}
        {!r.fit_ok && <p className="joint-warn" style={{ margin: "6px 0 0" }}>The fit didn't reach a verified maximum: treat these numbers with care.</p>}
      </div>

      <section className="card">
        <h2>Running units' risk</h2>
        <p className="hint">Each unit's chance of failing over the next stretch, given its own readings so far. Highest first.</p>
        <RiskTable results={r} selected={unitId} onPick={(id) => {
          setUnitId(id);
          document.getElementById("joint-unit-view")?.scrollIntoView?.({ behavior: "smooth", block: "start" });
        }} />
      </section>

      <section className="card" id="joint-unit-view">
        <h2>A unit's updating prediction</h2>
        <p className="hint">Each new reading moves the curve: a unit whose {r.marker || "reading"} is climbing faster than the fleet's carries more risk.</p>
        <UnitView modelId={modelId} results={r} name={name} unitId={unitId} onUnitId={setUnitId} />
      </section>

      <section className="card">
        <h2>The {r.marker || "reading"}'s path</h2>
        <PathChart results={r} name={name} />
        <p className="hint">Faint lines: some units' readings. The band is where 95% of units' true paths lie (a new unit, typical covariates).</p>
      </section>

      <section className="card">
        <h2>What changes the risk</h2>
        {(r.hazard_ratios || []).length ? (
          <ul className="joint-hr">
            {r.hazard_ratios.map((h) => <li key={h.name}>{h.text}</li>)}
          </ul>
        ) : <p className="muted-line">No risk coefficients.</p>}
        <p className="hint">A hazard ratio of 2 doubles the failure rate at any moment; 0.5 halves it.</p>
      </section>

      <section className="card">
        <h2>A new unit's survival</h2>
        <SurvivalChart curve={r.survival_new} unit={unit} name={name} title="new unit survival" />
        {r.survival_new?.remaining_life && (
          <p className="hint">
            A new unit with typical covariates: half fail by {medianText({
              median_remaining: r.survival_new.remaining_life.life?.[1],
              median_reached: r.survival_new.remaining_life.life?.[1] != null,
            }, unit)}.
          </p>
        )}
      </section>

      <section className="card">
        <h2>Parameters</h2>
        <Params params={r.params} />
        <p className="hint">Times and rates in {unit ? unit.toLowerCase() : "the model's time unit"}. Intervals are 95%.</p>
      </section>

      {(r.notes || []).length > 0 && (
        <section className="card note">
          <h2>Notes</h2>
          <ul>{r.notes.map((n) => <li key={n}>{n}</li>)}</ul>
        </section>
      )}
    </div>
  );
}

