import { useEffect, useMemo, useState } from "react";
import Plot from "./Plot.jsx";
import Chip from "./ui/Chip.jsx";
import { getJointUnit, predictJointUnit } from "../api.js";
import { formatNumber } from "../format.js";
import { bandPair, dataPoints, fitLine, referenceShape } from "../plotTheme.js";
import { medianText, paramGroups, parseReadings, readingsText, riskText, riskTone } from "../joint.js";
import { ModelTabs } from "./model/ModelFrame.jsx";
import { PlotCard, ScrollCard, TablePanel } from "./model/ModelLayouts.jsx";
import { JointEffects } from "./model/Effects.jsx";
import { JointDiagnostics } from "./model/Diagnostics.jsx";
import { modelTabs, resolveTab } from "../modelFrame.js";

// A fitted condition and life model in the model frame's five tabs:
//   Risk now     the running units' risk (highest first) beside the chosen
//                unit's updating prediction (its survival from now and its
//                reading's path)
//   Calculator   enter a unit (age, covariates, readings so far) and predict;
//                before that, a new unit's survival with typical covariates
//   Effects      what changes the risk: the hazard ratios, charted and in words
//   Diagnostics  the fit's checks: whether it settled, the units' readings
//                against the fitted path, the fit statistics and notes
//   Data         the counts and every parameter
// A shared page (no ``modelId``) shows the saved results; anything that asks
// the model again says to sign in.

const n3 = (v) => formatNumber(v);
const FAINT = "rgba(20, 23, 28, 0.18)";
const SIGN_IN = "Sign in to change this: a unit's prediction needs your own copy of the model.";

function Params({ params }) {
  const groups = paramGroups(params);
  return (
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
  );
}

export function PathChart({ results, name, fill = false }) {
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
  return <Plot fill={fill} data={traces} layout={layout} download={`${name || "Model"} — reading path`} />;
}

function SurvivalChart({ curve, unit, name, title, age = null, fill = false }) {
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
  return <Plot fill={fill} data={traces} layout={layout} download={`${name || "Model"} — ${title}`} />;
}

function MarkerChart({ pred, results, name, fill = false }) {
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
  return <Plot fill={fill} data={traces} layout={layout} download={`${name || "Model"} — reading trajectory`} />;
}

function RiskCells({ row, n = 3 }) {
  return Array.from({ length: n }, (_, i) => (
    <td key={i} className="num">
      <Chip tone={riskTone(row.risk?.[i])}>{riskText(row.risk?.[i])}</Chip>
    </td>
  ));
}

function RiskTable({ results, selected, onPick, live = true }) {
  const rows = results.risk || [];
  const labels = results.horizons?.labels || [];
  const unit = results.unit || "";
  if (!rows.length) return <p className="mf-note">No units are still running in the data.</p>;
  return (
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
          <tr key={r.id} className={selected === r.id ? "is-selected" : ""} onClick={() => onPick(r.id)}>
            <td>{r.id}</td>
            <td className="num">{n3(r.age)}</td>
            <RiskCells row={r} n={labels.length} />
            <td className="num">{medianText(r, unit)}</td>
            <td>
              <button type="button" className="link" aria-pressed={selected === r.id}
                      onClick={(e) => { e.stopPropagation(); onPick(r.id); }}>
                {selected === r.id && live ? "Shown" : "View"}
              </button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// A unit's prediction in words, then its two charts side by side.
function UnitPrediction({ view, results, name }) {
  const unit = results.unit || "";
  return (
    <>
      <p className="joint-unit-sum" role="status">
        {view.unit_id ? <>Unit <b>{view.unit_id}</b>, </> : "This unit, "}
        age {n3(view.age)}{unit ? ` ${unit.toLowerCase()}` : ""}, {view.markers.length} reading{view.markers.length === 1 ? "" : "s"}.{" "}
        {(results.horizons?.labels || []).map((l, i) => `${riskText(view.risk?.[i])} chance of failing in the next ${l}`).join("; ")}.
        {" "}Median life left: {medianText(view, unit)}.
      </p>
      <div className="mf-unit-charts">
        <PlotCard title="Survival from now">
          <SurvivalChart fill curve={view.prediction} unit={unit} name={name} title="unit survival" age={view.age} />
        </PlotCard>
        <PlotCard title={`Its ${results.marker || "reading"}`}>
          <MarkerChart fill pred={view.prediction} results={results} name={name} />
        </PlotCard>
      </div>
    </>
  );
}

// Risk now: the table, and the chosen unit's updating prediction.
function RiskNow({ modelId, results, name, unitId, onUnitId, onEnter }) {
  const [view, setView] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!unitId || !modelId) return undefined;
    let live = true;
    setBusy(true); setError(null);
    getJointUnit(modelId, unitId)
      .then((v) => live && setView(v))
      .catch((e) => live && setError(e.message))
      .finally(() => live && setBusy(false));
    return () => { live = false; };
  }, [modelId, unitId]);
  const shown = view && view.unit_id === unitId ? view : null;
  return (
    <TablePanel
      className="mf-l5-joint"
      main={
        <ScrollCard title="Running units' risk" sub="highest first">
          <RiskTable results={results} selected={unitId} onPick={onUnitId} live={!!modelId} />
        </ScrollCard>
      }
      side={
        <section className="mf-unit" id="joint-unit-view" aria-label="A unit's updating prediction">
          <p className="hint" style={{ margin: 0 }}>
            Each unit's chance of failing over the next stretch, given its own readings so far. Each new reading
            moves the curve: a unit whose {results.marker || "reading"} climbs faster than the fleet's carries more risk.
          </p>
          {!modelId && <p className="muted-line" style={{ margin: 0 }}>{SIGN_IN}</p>}
          {error && <div className="card error" role="alert">{error}</div>}
          {busy && !shown && <p className="hint" style={{ margin: 0 }}>Working…</p>}
          {!unitId && modelId && <p className="muted-line" style={{ margin: 0 }}>Choose a unit in the table to see its prediction.</p>}
          {shown && <UnitPrediction view={shown} results={results} name={name} />}
          {shown && shown.markers?.length > 0 && (
            <p className="hint" style={{ margin: 0 }}>To try newer readings for this unit, enter it in the Calculator:{" "}
              <button type="button" className="link" onClick={() => onEnter(shown)}>copy its readings</button>.
            </p>
          )}
        </section>
      }
    />
  );
}

// The Calculator: enter a unit and predict. Until then, a new unit's
// survival with typical covariates.
function JointCalculator({ modelId, results, name, entered, setEntered }) {
  const [view, setView] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const covNames = results.covariates || [];
  const unit = results.unit || "";
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
  const life = results.survival_new?.remaining_life?.life?.[1];
  return (
    <div className="mf-joint-calc">
      <div className="calc-rail-card mf-joint-calc-form">
        <div className="gofh" style={{ padding: "12px 14px" }}>Enter a unit</div>
        <div className="joint-enter" style={{ padding: "0 14px 14px" }}>
          <label className="dist-field">
            <span className="dist-label">Age now{unit ? ` (${unit}, since new)` : " (since new)"}</span>
            <input type="number" inputMode="decimal" min="0" step="any" value={entered.age}
                   onChange={(e) => setEntered({ ...entered, age: e.target.value })} />
          </label>
          {covNames.map((c) => (
            <label className="dist-field" key={c}>
              <span className="dist-label">{c}</span>
              <input type="number" inputMode="decimal" step="any" value={entered.covariates[c] ?? ""}
                     onChange={(e) => setEntered({ ...entered, covariates: { ...entered.covariates, [c]: e.target.value } })} />
            </label>
          ))}
          <label className="dist-field joint-readings">
            <span className="dist-label">Readings so far: age and value, one per line</span>
            <textarea rows={5} value={entered.readings} placeholder={"0 2.1\n20 2.6\n40 3.0"}
                      onChange={(e) => setEntered({ ...entered, readings: e.target.value })} />
          </label>
          <div>
            <button type="button" onClick={onPredict} disabled={busy || !modelId}
                    title={modelId ? undefined : SIGN_IN}>{busy ? "Working…" : "Predict"}</button>
          </div>
          {!modelId && <p className="muted-line" style={{ margin: 0 }}>{SIGN_IN}</p>}
          {error && <div className="error" role="alert">{error}</div>}
        </div>
      </div>
      <div className="mf-joint-calc-out mf-unit">
        {view ? (
          <UnitPrediction view={view} results={results} name={name} />
        ) : (
          <>
            <p className="joint-unit-sum">
              A new unit with typical covariates{life != null ? <>: half fail by <b>{medianText({ median_remaining: life, median_reached: true }, unit)}</b></> : ""}.
              {" "}Enter a unit's age and readings to see its own.
            </p>
            <PlotCard title="A new unit's survival">
              <SurvivalChart fill curve={results.survival_new} unit={unit} name={name} title="new unit survival" />
            </PlotCard>
          </>
        )}
      </div>
    </div>
  );
}

function JointData({ results }) {
  const r = results;
  const rows = [
    ["Units", r.n_items], ["Failed", r.n_events], ["Still running", r.n_running], ["Readings", r.n_readings],
  ];
  return (
    <TablePanel
      className="mf-l5-wide"
      main={
        <ScrollCard title="Every parameter" sub="with 95% intervals">
          <Params params={r.params} />
          <p className="mf-note">Times and rates in {r.unit ? r.unit.toLowerCase() : "the model's time unit"}.</p>
        </ScrollCard>
      }
      side={
        <>
          <section className="gof-card mf-flex-none">
            <div className="gofh">What it was fitted to</div>
            {rows.filter(([, v]) => v != null).map(([k, v]) => (
              <div className="gofr" key={k}><span className="gk">{k}</span><span className="gv">{Number(v).toLocaleString()}</span></div>
            ))}
            <div className="gofr"><span className="gk">Reading</span><span className="gv">{r.marker}{r.marker_unit ? ` (${r.marker_unit})` : ""}</span></div>
          </section>
          <section className="gof-card mf-flex-none">
            <div className="gofh">How it was fitted</div>
            <p className="mf-note">
              The reading follows a {r.path_label?.toLowerCase()} path ({r.path_formula}) for each unit, with the units'
              paths spread about the mean; the failure risk is Weibull, raised or lowered by the reading's current value
              and the covariates.
            </p>
            {(r.covariates || []).length > 0 && (
              <p className="mf-note">Covariates: {r.covariates.join(", ")}.</p>
            )}
          </section>
        </>
      }
    />
  );
}

export default function JointResultView({ results, modelId, name, tab: wanted = undefined, onTab = null }) {
  const r = results || {};
  const tabs = modelTabs({ ...r, kind: "joint" });
  const [own, setOwn] = useState(() => resolveTab(tabs, wanted));
  const tab = resolveTab(tabs, wanted !== undefined && onTab ? wanted : own);
  const setTab = (id) => { setOwn(id); onTab?.(id); };
  const [unitId, setUnitId] = useState(() => r.risk?.[0]?.id || "");
  const covNames = useMemo(() => r.covariates || [], [r.covariates]);
  const [entered, setEntered] = useState(() => ({
    age: "", readings: "", covariates: Object.fromEntries(covNames.map((c) => [c, String(r.typical_covariates?.[c] ?? "")])),
  }));

  let body = null;
  if (tab === "risk") {
    body = (
      <RiskNow modelId={modelId} results={r} name={name} unitId={unitId} onUnitId={setUnitId}
               onEnter={(view) => {
                 setEntered({ age: String(view.age), readings: readingsText(view.markers),
                   covariates: Object.fromEntries(covNames.map((c) => [c, String(view.covariates?.[c] ?? "")])) });
                 setTab("calc");
               }} />
    );
  } else if (tab === "calc") {
    body = <JointCalculator modelId={modelId} results={r} name={name} entered={entered} setEntered={setEntered} />;
  } else if (tab === "effects") {
    body = <JointEffects results={r} name={name} />;
  } else if (tab === "diag") {
    body = <JointDiagnostics results={r} name={name} PathChart={PathChart} />;
  } else if (tab === "data") {
    body = <JointData results={r} />;
  }
  return (
    <ModelTabs
      tabs={tabs}
      value={tab}
      onChange={setTab}
      before={!r.fit_ok && (
        <p className="joint-warn mf-before" role="note">
          The fit didn't reach a verified maximum: treat these numbers with care (Diagnostics says more).
        </p>
      )}
    >
      {body}
    </ModelTabs>
  );
}
