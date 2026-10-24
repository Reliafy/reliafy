// The Diagnostics tab: "Can I trust this model?" Each check is a small chart
// or table titled with its question, the technical name in brackets and a
// one-line verdict; the fit statistics and the comparison with other models
// sit in the column beside them. Every number is one the fit (or the
// model's own endpoints) already gives: nothing here resamples.
import { useEffect, useRef, useState } from "react";
import Plot from "../Plot.jsx";
import Select from "../Select.jsx";
import Chip from "../ui/Chip.jsx";
import SegmentedControl from "../ui/SegmentedControl.jsx";
import RegressionChecks from "../RegressionChecks.jsx";
import { CheckCard, ChecksGrid } from "./ModelLayouts.jsx";
import { getModelValidation, getResiduals } from "../../api.js";
import { formatNumber } from "../../format.js";
import { bestFitSentence, compareRows, criterionLabel } from "../../lifeResults.js";
import { COLORWAY, DATA_INK, dataPoints, fitLine, referenceShape } from "../../plotTheme.js";
import { countsSummary, curveSummary, hazardShape, oddUnits, ppSummary } from "../../modelFrame.js";
import { unitInText } from "../unitText.js";

const fmt5 = (v) => formatNumber(v, { sig: 5 });
const tAxis = (unit) => ({ title: { text: unit ? `Time (${unit})` : "Time" }, rangemode: "tozero" });
const SMALL = { margin: { t: 6, r: 10, b: 40, l: 50 } };

// ---- The column beside the checks --------------------------------------------

// AIC and the other criteria (today's "Fit statistics"), in the panel's card style.
export function FitStatsCard({ gof, n, note, extra = [] }) {
  const rows = [...(gof || []), ...extra];
  return (
    <section className="gof-card" aria-labelledby="mf-fit-stats">
      <div className="gofh life-card-head">
        <h3 className="mf-card-title" id="mf-fit-stats">Fit statistics</h3>
        <span className="gof-sub">lower is better</span>
      </div>
      {rows.length ? rows.map((g) => (
        <div className="gofr" key={g.id}>
          <span className="gk">
            {g.label}
            {(g.id === "log_likelihood") && <span className="gof-sub"> · higher is better</span>}
          </span>
          <span className="gv">{fmt5(g.value)}</span>
        </div>
      )) : <p className="mf-note">No fit statistics for this model.</p>}
      {n != null && (
        <div className="gofr"><span className="gk">Observations</span><span className="gv">{Number(n).toLocaleString()}</span></div>
      )}
      <p className="mf-note">
        {note ? `${note} ` : ""}These only mean something beside another model fitted to the same data.
      </p>
    </section>
  );
}

// "Would another distribution fit better?": every plain distribution fitted
// to the same data, ranked by AIC. A Best fit carries the ranking; any other
// fit runs it when the tab opens (once a page: ``cache``). ``self`` adds this
// model's own row when it isn't one of the plain distributions (a mixture,
// a spline).
const compared = new Map();

function useComparison(result, compare, key) {
  const own = (result.selection?.candidates?.length || 0) > 1 ? result.selection : null;
  const [state, setState] = useState(() => (key && compared.has(key) ? { data: compared.get(key) } : null));
  // The latest ``compare``; a caller may pass a new function each render.
  const run = useRef(compare);
  run.current = compare;
  const can = !!compare;
  useEffect(() => {
    if (own || !can || (key && compared.has(key))) return undefined;
    let live = true;
    setState({ busy: true });
    run.current()
      .then((data) => { if (key) compared.set(key, data); if (live) setState({ data }); })
      .catch((err) => live && setState({ error: err.message }));
    return () => { live = false; };
  }, [own, can, key]);
  return { selection: own || state?.data || null, busy: !!state?.busy, error: state?.error || null };
}

export function CompareCheck({ result, compare, onPick, cacheKey, question = "Would another distribution fit better?" }) {
  const aic = (result.gof || []).find((g) => g.id === "aic")?.value;
  // Kept per model and fit: an edited fit compares again.
  const { selection, busy, error } = useComparison(result, compare, cacheKey ? `${cacheKey}:${result.n}:${aic}` : null);
  const key = selection?.criterion || "aic";
  const label = criterionLabel(key);
  const plain = result.kind === "distribution" && result.distribution_id !== "mixture";
  const current = plain ? result.distribution_id : "self";
  let candidates = selection?.candidates || [];
  const ownValue = (result.gof || []).find((g) => g.id === key)?.value;
  if (!plain && selection && Number.isFinite(Number(ownValue))) {
    candidates = [...candidates, { id: "self", name: `${result.distribution} (this model)`, [key]: ownValue }];
  }
  const rows = compareRows(candidates, key, current);
  const mine = rows.find((r) => r.current);
  let tone;
  let verdict;
  if (!selection) {
    verdict = busy ? "Fitting every distribution to the same data…"
      : error ? `Couldn't compare: ${error}`
      : "Comparing needs the model's data, which isn't here.";
  } else if (!mine) {
    verdict = bestFitSentence(rows);
  } else if (mine.verdict === "best" || mine.verdict === "about") {
    tone = "good";
    verdict = mine.verdict === "best"
      ? `No: this model has the lowest ${label}.`
      : `No: ${rows[0].name} is within 2 of it, so the data can't tell them apart.`;
  } else {
    tone = mine.verdict === "clearly" ? "bad" : "caveat";
    verdict = `Yes: ${rows[0].name} fits better (${label} lower by ${mine.delta.toFixed(1)}).`;
  }
  return (
    <CheckCard question={question} term={`${label} ranking`} tone={tone} verdict={verdict}
               footer={rows.length > 0 && (
                 <p className="muted-line">
                   Lower {label} is better; under 2 apart, the data can't tell two models apart.
                   {onPick ? " Pick a name to fit that one instead." : ""}
                 </p>
               )}>
      {rows.length > 0 && (
        <table className="mini-table compare-table">
          <thead><tr><th>Model</th><th>Δ{label}</th><th>Verdict</th></tr></thead>
          <tbody>
            {rows.map((r) => {
              const pick = onPick && !r.current && r.id !== "self" && !String(r.id).includes(":");
              return (
                <tr key={r.id} className={r.current ? "current" : undefined}>
                  <td>
                    {pick ? (
                      <button type="button" className="link" onClick={() => onPick(r.id)}
                              title={`Fit ${r.name} to these data instead`}>{r.name}</button>
                    ) : r.name}
                    {r.current && r.id !== "self" && <span className="gof-sub"> · this model</span>}
                  </td>
                  <td>{r.delta === 0 ? "—" : `+${r.delta.toFixed(1)}`}</td>
                  <td>
                    {r.verdict === "best" ? <Chip tone="success">Best</Chip>
                      : <span className={r.verdict === "about" ? "" : "compare-worse"}>{r.verdictLabel}</span>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      {selection?.failed?.length > 0 && (
        <p className="muted-line">Couldn't fit: {selection.failed.map((f) => f.name).join(", ")}.</p>
      )}
    </CheckCard>
  );
}

function WarningCard({ result }) {
  const warnings = [result.fit_warning && !result.no_finite_maximum ? result.fit_warning : null, ...(result.warnings || [])]
    .filter(Boolean);
  if (!warnings.length) return null;
  return (
    <div className="life-reading caveat">
      {warnings.map((w) => <p key={w} style={{ margin: 0 }}>{w}</p>)}
    </div>
  );
}

// ---- Non-repairable: a distribution or a mixture -------------------------------

function noPoints() {
  return <p className="muted-line">Not stored with this model: refit it (⋯ › Edit fit) to see this check.</p>;
}

function CurveOverData({ result, name }) {
  const e = result.plot?.empirical;
  const c = result.functions?.curves;
  const s = curveSummary(e, result.unit);
  const traces = [];
  if (e) {
    traces.push({ type: "scatter", mode: "lines+markers", x: [0, ...e.x], y: [1, ...e.F.map((f) => 1 - f)],
                  line: { shape: "hv", color: DATA_INK, width: 1.25 }, marker: { color: DATA_INK, size: 5 },
                  name: `The data (${e.method})`, hovertemplate: "%{x:,.4~g}: R=%{y:.3f}<extra>data</extra>" });
  }
  if (c?.x) traces.push(fitLine({ x: c.x, y: c.sf, name: "The model", hovertemplate: "%{x:,.4~g}: R=%{y:.3f}<extra>model</extra>" }));
  return (
    <CheckCard chart question="Does the curve follow the data?" term="fitted curve over the data's own estimate"
               verdict={s?.words || null}>
      {e ? (
        <Plot fill data={traces} download={`${name || result.distribution} — curve over the data`}
              layout={{ ...SMALL, xaxis: tAxis(result.unit), yaxis: { title: { text: "Reliability, R(t)" }, range: [0, 1.02] },
                        showlegend: true, legend: { x: 1, xanchor: "right", y: 1, yanchor: "top", bgcolor: "rgba(255,255,255,0.85)" } }} />
      ) : noPoints()}
    </CheckCard>
  );
}

function PPCheck({ result, name }) {
  const e = result.plot?.empirical;
  const s = ppSummary(e, result.unit);
  const traces = e ? [
    { type: "scatter", mode: "lines", x: [0, 1], y: [0, 1], line: { color: "#9aa0a8", width: 1, dash: "dash" },
      hoverinfo: "skip", name: "Where the points should lie" },
    dataPoints({ x: e.model_F, y: e.F, name: "Failures", customdata: e.x,
                 hovertemplate: "at %{customdata:,.4~g}: model %{x:.2f}, data %{y:.2f}<extra></extra>" }),
  ] : [];
  return (
    <CheckCard chart question="Are the failures where the model expects?" term="P-P plot"
               verdict={s?.words || null}>
      {e ? (
        <Plot fill data={traces} download={`${name || result.distribution} — P-P plot`}
              layout={{ ...SMALL, showlegend: false,
                        xaxis: { title: { text: "Model's fraction failed" }, range: [0, 1] },
                        yaxis: { title: { text: "Data's fraction failed" }, range: [0, 1] } }} />
      ) : noPoints()}
    </CheckCard>
  );
}

function DistributionDiagnostics({ result, name, compare, onPick, modelId }) {
  return (
    <ChecksGrid
      side={
        <>
          <WarningCard result={result} />
          <CompareCheck result={result} compare={compare} onPick={onPick} cacheKey={modelId}
                        question={result.distribution_id === "mixture" ? "Is a mixture worth it?" : undefined} />
          <FitStatsCard gof={result.gof} n={result.n} note={result.gof_note} />
        </>
      }
    >
      <CurveOverData result={result} name={name} />
      <PPCheck result={result} name={name} />
    </ChecksGrid>
  );
}

// ---- Royston-Parmar ---------------------------------------------------------

function FlexibleDiagnostics({ result, name, compare, modelId }) {
  const c = result.functions?.curves || {};
  const shape = hazardShape(c.x, c.hf);
  return (
    <ChecksGrid
      side={
        <>
          <WarningCard result={result} />
          <CompareCheck result={result} compare={compare} cacheKey={modelId}
                        question="Does a plain distribution fit as well?" />
          <FitStatsCard gof={result.gof} n={result.n} note={result.gof_note} />
        </>
      }
    >
      <CheckCard chart question="Is the hazard shape believable?" term="fitted hazard rate"
                 verdict={shape ? `${shape.words} Does that match what you know of these units?` : null}>
        {c.hf ? (
          <Plot fill data={[fitLine({ x: c.x, y: c.hf, name: "Hazard rate", hovertemplate: "%{x:,.4~g}: h=%{y:.3~g}<extra></extra>" })]}
                download={`${name || result.distribution} — hazard rate`}
                layout={{ ...SMALL, showlegend: false, xaxis: tAxis(result.unit),
                          yaxis: { title: { text: "Hazard rate, h(t)" }, rangemode: "tozero" } }} />
        ) : <p className="muted-line">This model gives no hazard rate.</p>}
      </CheckCard>
    </ChecksGrid>
  );
}

// ---- Discrete ---------------------------------------------------------------

function DiscreteDiagnostics({ result, name }) {
  const k = result.counts;
  const u = result.unit ? unitInText(result.unit) : "count";
  const s = countsSummary(k, result.unit);
  return (
    <ChecksGrid side={<><WarningCard result={result} /><FitStatsCard gof={result.gof} n={result.n} /></>}>
      <CheckCard chart question="Do the failures at each count match the model?" term="observed against expected"
                 verdict={s ? `${s.words} Units still running count only up to the count they reached.` : null}>
        {k ? (
          <Plot fill download={`${name || result.distribution} — observed and expected failures`}
                data={[
                  { type: "bar", x: k.k, y: k.failed, name: "Failed (the data)", marker: { color: "rgba(20,23,28,0.35)" } },
                  { type: "scatter", mode: "lines+markers", x: k.k, y: k.expected, name: "Expected (the model)",
                    line: { color: COLORWAY[0], width: 2 }, marker: { size: 6 } },
                ]}
                layout={{ ...SMALL, bargap: 0.25, showlegend: true,
                          xaxis: { title: { text: `Failed at (${u})` } },
                          yaxis: { title: { text: "Units" }, rangemode: "tozero" } }} />
        ) : noPoints()}
      </CheckCard>
    </ChecksGrid>
  );
}

// ---- Regression -------------------------------------------------------------

function useFetched(stored, fetcher, key) {
  const [got, setGot] = useState(null);
  useEffect(() => {
    if (stored || !key) return undefined;
    let live = true;
    setGot(null);
    fetcher().then((v) => live && setGot({ v })).catch((err) => live && setGot({ error: err.message }));
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stored, key]);
  return { value: stored || got?.v || null, loading: !stored && !!key && !got, error: got?.error || null };
}

function ResidualChecks({ result, name }) {
  const path = result.functions?.residuals_path;
  const ph = result.diagnostics?.ph_test;
  const { value: res, loading, error } = useFetched(null, () => getResiduals(path), path);
  const [which, setWhich] = useState(0);
  const u = result.unit ? ` (${unitInText(result.unit)})` : "";
  const dots = (color) => ({ type: "scatter", mode: "markers", marker: { size: 4, color, opacity: 0.55 }, hoverinfo: "x+y" });
  const empty = (text) => <p className="muted-line">{text}</p>;
  const body = (draw) => (loading ? empty("Computing the residuals…")
    : error ? empty(`Couldn't load the residuals: ${error}`)
    : !res ? empty("No residuals for this model.")
    : !res.available ? empty(res.reason || "Not available for this model.")
    : draw());
  const sch = res?.schoenfeld || [];
  const s = sch[Math.min(which, sch.length - 1)];
  const odd = res?.available ? oddUnits(res.deviance) : null;
  return (
    <>
      <CheckCard chart question="Does each effect stay constant over time?" term="Schoenfeld residuals, PH test"
                 tone={ph?.available ? ph.tone : undefined}
                 verdict={ph?.available ? ph.reading : ph?.reason ? ph.reason.replace(/^Not available:\s*/, "") : null}
                 footer={sch.length > 1 && (
                   <Select value={String(Math.min(which, sch.length - 1))} onChange={(v) => setWhich(Number(v))}
                           ariaLabel="Covariate" options={sch.map((x, i) => ({ value: String(i), label: x.covariate }))} />
                 )}>
        {body(() => (s ? (
          <Plot fill download={`Scaled Schoenfeld residuals — ${s.covariate}`}
                data={[
                  { ...dots(COLORWAY[0]), x: s.x, y: s.y, name: s.covariate },
                  { type: "scatter", mode: "lines", x: s.trend.x, y: s.trend.y, line: { color: COLORWAY[0], width: 2 },
                    name: "Trend", hoverinfo: "skip" },
                ]}
                layout={{ ...SMALL, showlegend: false, shapes: [referenceShape({ y: s.coef, line: { dash: "dot" } })],
                          xaxis: { title: { text: `Failure time${u}` } },
                          yaxis: { title: { text: `Effect of ${s.covariate}, β(t)` } } }} />
        ) : empty("No covariates to check.")))}
      </CheckCard>
      <CheckCard chart question="Is each effect a straight line?" term="martingale residuals"
                 verdict="A curve in the points suggests a covariate needs another form (a log, say).">
        {body(() => (
          <Plot fill download={`${name || "Model"} — martingale residuals`}
                data={[{ ...dots(COLORWAY[0]), x: res.martingale.x, y: res.martingale.y, name: "martingale" }]}
                layout={{ ...SMALL, showlegend: false, shapes: [referenceShape({ y: 0, line: { dash: "dot" } })],
                          xaxis: { title: { text: "Linear predictor" } }, yaxis: { title: { text: "Martingale residual" } } }} />
        ))}
      </CheckCard>
      <CheckCard chart question="Any odd units?" term="deviance residuals" tone={odd?.tone === "neutral" ? undefined : odd?.tone}
                 verdict={odd?.words || null}>
        {body(() => (
          <Plot fill download={`${name || "Model"} — deviance residuals`}
                data={[{ ...dots(COLORWAY[0]), x: res.deviance.x, y: res.deviance.y, name: "deviance" }]}
                layout={{ ...SMALL, showlegend: false,
                          shapes: [referenceShape({ y: 2.5, line: { dash: "dot" } }), referenceShape({ y: -2.5, line: { dash: "dot" } })],
                          xaxis: { title: { text: "Linear predictor" } }, yaxis: { title: { text: "Deviance residual" } } }} />
        ))}
      </CheckCard>
    </>
  );
}

const RATING_TONE = { strong: "good", good: "good", moderate: "caveat", weak: "caveat", "no better than chance": "bad" };
const n2 = (v) => Number(v).toFixed(2);
const n3 = (v) => Number(v).toFixed(3);

function AccuracyChecks({ result, modelId }) {
  const stored = result.validation;
  const { value: v, loading, error } = useFetched(stored, () => getModelValidation(modelId), stored ? null : modelId);
  const u = result.unit ? ` ${unitInText(result.unit)}` : "";
  const time = (t) => Number(t).toLocaleString(undefined, { maximumSignificantDigits: 3 });
  if (loading) return <CheckCard question="How good is this model?" verdict="Scoring the model against its data…" />;
  if (!v || error || !v.available) {
    const reason = error ? "The scores couldn't be loaded." : v?.reason || "Not computed for this model.";
    return <CheckCard question="How good is this model?" verdict={`Not available. ${reason.replace(/^Not available:\s*/, "")}`} />;
  }
  const c = v.concordance;
  const b = v.brier;
  return (
    <>
      <CheckCard question="Does it put units in the right order?" term="Harrell's C" tone={RATING_TONE[c.rating]}
                 verdict={c.reading}
                 footer={(v.note || v.sample_note) && <p className="muted-line">{v.note} {v.sample_note || ""}</p>}>
        <p className="mf-big-number">{n2(c.value)}</p>
        <p className="muted-line">0.5 is a coin toss, 1 is perfect.</p>
      </CheckCard>
      <CheckCard question="How far off are its predictions?" term="integrated Brier score"
                 tone={b ? (b.model < b.baseline ? "good" : "caveat") : undefined}
                 verdict={b ? b.reading : "Not available: too few distinct failure times to score over."}>
        {b && (
          <>
            <p className="mf-big-number">{n3(b.model)}</p>
            <p className="muted-line">
              {n3(b.baseline)} with one survival curve for every unit (no covariates). Lower is better; from{" "}
              {time(b.from)} to {time(b.to)}{u}.
            </p>
          </>
        )}
      </CheckCard>
      <CheckCard chart={v.auc?.length > 0} question="Does it tell failed from running?" term="time-dependent AUC"
                 verdict="How well it separates units that have failed by each time from those still running (0.5 is a coin toss, 1 is perfect).">
        {v.auc?.length > 0 ? (
          <Plot fill data={[{ type: "bar", x: v.auc.map((a) => `by ${time(a.time)}${u}`), y: v.auc.map((a) => a.value),
                              marker: { color: COLORWAY[0] }, hovertemplate: "%{x}: %{y:.2f}<extra></extra>" }]}
                layout={{ ...SMALL, showlegend: false, yaxis: { range: [0, 1], title: { text: "AUC" } },
                          xaxis: { type: "category" }, shapes: [referenceShape({ y: 0.5, line: { dash: "dot" } })] }} />
        ) : <p className="muted-line">Not available for this model.</p>}
      </CheckCard>
    </>
  );
}

const VIEWS = [
  { value: "assumptions", label: "Assumptions" },
  { value: "accuracy", label: "Predictive accuracy" },
  { value: "stats", label: "Fit statistics" },
];

function RegressionDiagnostics({ result, name, modelId }) {
  const [view, setView] = useState("assumptions");
  const stats = <FitStatsCard gof={result.gof} n={result.n} note={result.gof_note} />;
  if (result.tvc) {
    return (
      <ChecksGrid side={<><WarningCard result={result} />{stats}</>}>
        <CheckCard question="Do the fixed-covariate checks apply?"
                   verdict="No: each unit's covariates change along its life, so the proportional-hazards test, the residuals and the ranking scores (which take one set of values per unit) don't apply here." />
      </ChecksGrid>
    );
  }
  const toolbar = (
    <SegmentedControl label="Which checks" size="sm" value={view} onChange={setView} options={VIEWS} />
  );
  if (view === "stats") {
    return <ChecksGrid toolbar={toolbar} side={<WarningCard result={result} />}>{stats}</ChecksGrid>;
  }
  if (view === "accuracy") {
    return <ChecksGrid toolbar={toolbar} side={stats}><AccuracyChecks result={result} modelId={modelId} /></ChecksGrid>;
  }
  return (
    <ChecksGrid toolbar={toolbar}
                side={<><WarningCard result={result} />
                  <RegressionChecks diagnostics={result.diagnostics} modelId={modelId}
                                    residualsPath={result.functions?.residuals_path} unit={result.unit} /></>}>
      <ResidualChecks result={result} name={name} />
    </ChecksGrid>
  );
}

// ---- Condition and life ---------------------------------------------------------

export function JointDiagnostics({ results, name, PathChart }) {
  const r = results || {};
  const extra = [
    r.log_likelihood != null && { id: "log_likelihood", label: "Log-likelihood", value: r.log_likelihood },
    r.aic != null && { id: "aic", label: "AIC", value: r.aic },
  ].filter(Boolean);
  return (
    <ChecksGrid
      side={
        <>
          <CheckCard question="Did the fit settle?" term="maximum likelihood" tone={r.fit_ok ? "good" : "caveat"}
                     verdict={r.fit_ok ? "Yes: the fit reached a verified maximum."
                       : "No: the fit didn't reach a verified maximum, so treat these numbers with care."} />
          <FitStatsCard gof={extra} n={r.n_items} />
          {(r.notes || []).length > 0 && (
            <div className="gof-card">
              <div className="gofh">Notes</div>
              {r.notes.map((n) => <p className="mf-note" key={n}>{n}</p>)}
            </div>
          )}
        </>
      }
    >
      <CheckCard chart question={`Do the units' readings follow the fitted path?`} term={`${(r.path_label || "").toLowerCase()} path`}
                 verdict={`Faint lines: some units' readings of ${r.marker || "the reading"}. The band is where 95% of units' true paths lie (a new unit with typical covariates); readings far outside it don't follow the path.`}>
        <PathChart results={r} name={name} fill />
      </CheckCard>
    </ChecksGrid>
  );
}

export default function Diagnostics({ result, name, compare, onPick, modelId }) {
  switch (result.kind) {
    case "regression":
      return <RegressionDiagnostics result={result} name={name} modelId={modelId} />;
    case "flexible":
      return <FlexibleDiagnostics result={result} name={name} compare={compare} modelId={modelId} />;
    case "discrete":
      return <DiscreteDiagnostics result={result} name={name} />;
    default:
      return <DistributionDiagnostics result={result} name={name} compare={compare} onPick={onPick} modelId={modelId} />;
  }
}

