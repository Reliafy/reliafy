import Plot from "./Plot.jsx";
import ProbabilityPlot from "./ProbabilityPlot.jsx";
import ChoiceChips from "./ui/ChoiceChips.jsx";
import { Select, TextInput } from "./ui/Controls.jsx";
import SegmentedControl from "./ui/SegmentedControl.jsx";
import { PickedRecord } from "./LibraryRecordPicker.jsx";
import { RecordCovariatesField } from "./LibraryParts.jsx";
import { ACCENT, BAND_FILL, MUTED } from "../plotTheme.js";
import { TRUST_CHOICES } from "../bayesUpdate.js";
import { AROUND_PARAMS, countsWords, libraryPriorWords } from "../fitDialog.js";
import { fmt, rangeBound } from "../explorerModels.js";
import "./RcmWorksheet.css";
import "./FitLifeModel.css";

// A fit with a prior, shared by every place that fits one: the Explorer's "Fit a life model…"
// (FitLifeModel.jsx, a position's history) and New model's "With a prior" (FitFlow.jsx, a saved
// dataset, pasted values or a file). PriorFields is the prior's inputs; FitOutcome the answer
// (the words, the prior's curve dashed under the fitted one with its band, the numbers with their
// intervals, the reliability at an age, how it was computed). The state and the request are
// fitDialog.js's (initialFit, bodyOf, problem); the arithmetic is the server's (fit_life.py).

export const PARAM_NAMES = { weibull: ["alpha", "beta"], exponential: ["failure_rate"], lognormal: ["mu", "sigma"] };
export const PARAM_WORDS = { alpha: "Characteristic life (alpha)", beta: "Shape (beta)", failure_rate: "Failure rate", mu: "mu", sigma: "sigma" };
const UNITS = ["hours", "days", "weeks", "months", "years"];

export function Range({ p }) {
  if (!p) return "—";
  const b = rangeBound(p);
  return <>{fmt(p.median ?? p.point)}{b ? <span className="rw-sum"> ({b})</span> : null}</>;
}

// The prior's inputs.
//   state, set       the fitDialog state and its setter (set(key, value))
//   kind             the prior kind in force (fitDialog.effective)
//   kinds            the kinds offered ([{value, label}]), or null to hide the choice (it's fixed)
//   onKind           (kind) => void, when the choice changes
//   trust            whether to ask how much to trust the prior
//   models           the saved models a prior can be (null while loading)
//   modelFallback    an <option> for a model the list leaves out (the row a refit opened on)
//   record, libCov   the library record picked and its covariates (LibraryParts.useRecordCovariates)
//   onPickRecord     () => void: open the library record picker
//   pickArea         a ref around the picked record (focus returns there)
//   unit             a fixed unit for typed numbers (the data's: no choice shown), or null to ask
export function PriorFields({ state, set, kind, kinds = null, onKind, trust = true, models = null, modelFallback = null,
                             record = null, libCov = null, onPickRecord, pickArea = null, unit = null }) {
  const dist = state.distribution === "best" ? "weibull" : state.distribution;
  const unitField = unit
    ? <span className="fit2-unit-fixed">in {unit}</span>
    : <Select aria-label="Unit" value={state.unit} onChange={(e) => set("unit", e.target.value)}>{UNITS.map((x) => <option key={x} value={x}>{x}</option>)}</Select>;
  return (
    <>
      {kinds && (
        <Select aria-label="Prior" value={kind} onChange={(e) => onKind(e.target.value)}>
          {kinds.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
        </Select>
      )}
      {trust && (
        <ChoiceChips label="How much to trust the prior" className="sm" value={state.trust} onChange={(v) => v && set("trust", v)}
                     options={TRUST_CHOICES.map((t) => ({ value: t.value, label: t.label }))} />
      )}
      {kind === "library" && (
        <>
          <div ref={pickArea} className="fit2-pick">
            <PickedRecord record={state.recordId ? record || { id: state.recordId } : null} onPick={onPickRecord} />
          </div>
          {state.recordId && <p className="fit2-sum">{libraryPriorWords(state.distribution, record)}</p>}
          {state.recordId && record?.kind !== "life" && libCov && <RecordCovariatesField recordId={state.recordId} cov={libCov} idPrefix="fitcov" />}
          {record?.kind !== "life" && (state.distribution === "weibull" || state.distribution === "lognormal") && (
            <div className="fit2-pair">
              <TextInput inputMode="decimal" aria-label="Shape between" placeholder="Shape between (0.5)" value={state.libShape.lo || ""}
                         onChange={(e) => set("libShape", { ...state.libShape, lo: e.target.value })} />
              <TextInput inputMode="decimal" aria-label="Shape and" placeholder="and (5)" value={state.libShape.hi || ""}
                         onChange={(e) => set("libShape", { ...state.libShape, hi: e.target.value })} />
            </div>
          )}
        </>
      )}
      {kind === "around" && (
        <div className="fit2-around" role="group" aria-label="Around a value, between two bounds">
          <div className="fit2-around-head" aria-hidden="true"><span /><span>about</span><span>between</span><span>and</span></div>
          {AROUND_PARAMS[dist].map(([k, label]) => (
            <div key={k} className="fit2-around-row">
              <span className="fit2-around-name">{label}</span>
              {[["about", "about"], ["lo", "between"], ["hi", "and"]].map(([f, word]) => (
                <TextInput key={f} inputMode="decimal" aria-label={`${label} ${word}`} value={state.around[k]?.[f] || ""}
                           onChange={(e) => set("around", { ...state.around, [k]: { ...(state.around[k] || {}), [f]: e.target.value } })} />
              ))}
            </div>
          ))}
          {unitField}
        </div>
      )}
      {kind === "model" && (
        <Select aria-label="Prior model" value={state.modelId || ""} onChange={(e) => set("modelId", e.target.value || null)}>
          <option value="">{models === null ? "Loading models…" : "Pick a Weibull, exponential or lognormal model"}</option>
          {(models || []).map((m) => <option key={m.id} value={m.id}>{m.name}{m.is_sample ? " (sample)" : ""}</option>)}
          {modelFallback}
        </Select>
      )}
      {kind === "params" && (
        <div className="fit2-pair">
          <Select aria-label="Prior distribution" value={dist} onChange={(e) => set("distribution", e.target.value)}>
            <option value="weibull">Weibull</option><option value="exponential">Exponential</option><option value="lognormal">Lognormal</option>
          </Select>
          {unitField}
          {PARAM_NAMES[dist].map((k) => (
            <TextInput key={k} inputMode="decimal" aria-label={PARAM_WORDS[k]} placeholder={PARAM_WORDS[k]} value={state.params[k] || ""}
                       onChange={(e) => set("params", { ...state.params, [k]: e.target.value })} />
          ))}
        </div>
      )}
      {kind === "b10" && (
        <div className="fit2-pair">
          <TextInput inputMode="decimal" aria-label="B10 about" placeholder="B10 about" value={state.b10.value || ""} onChange={(e) => set("b10", { ...state.b10, value: e.target.value })} />
          {unitField}
          <TextInput inputMode="decimal" aria-label="Surprised under" placeholder="Surprised under" value={state.b10.low || ""} onChange={(e) => set("b10", { ...state.b10, low: e.target.value })} />
          <TextInput inputMode="decimal" aria-label="Surprised over" placeholder="Surprised over" value={state.b10.high || ""} onChange={(e) => set("b10", { ...state.b10, high: e.target.value })} />
        </div>
      )}
    </>
  );
}

// The charts a fit offers: the probability plot (a plain fit's), reliability, hazard.
export function fitCharts(d, bayes) {
  return [...(d?.plot && !bayes ? [{ value: "paper", label: "Probability plot" }] : []), { value: "sf", label: "Reliability" },
    ...(d?.curves?.hf ? [{ value: "hf", label: "Hazard" }] : [])];
}

// The answer.
//   d          the preview (fit_life.fit's or fit_dataset's result)
//   priorKind  what the prior is (names the dashed curve)
//   unit       the result's unit, lower case
//   chart      "paper" | "sf" | "hf"; onChart (chart) => void
//   download   the charts' download name
//   age        the age typed; onAge (text) => void
//   dataWords  where the data came from, for "How it was computed" ("this position's history")
export function FitOutcome({ d, priorKind, unit: u = "", chart, onChart, download, age, onAge, dataWords }) {
  const bayes = d.method === "bayes";
  const charts = fitCharts(d, bayes);
  const shownChart = charts.some((c) => c.value === chart) ? chart : "sf";
  const priorName = priorKind === "class" ? "The class's own fit" : "The prior";
  const priorOf = (name) => {
    const b = (d.prior || []).find((x) => x.name === name);
    return b ? <Range p={b} /> : "—";
  };
  return (
    <>
      <p className="ml-lead" role="status">{d.words}</p>
      {(d.warnings || []).map((w) => <p key={w} className="ml-stale" role="note">{w}</p>)}
      {charts.length > 1 && <SegmentedControl size="sm" label="What to plot" value={shownChart} onChange={onChart} options={charts} />}
      {shownChart === "paper" && d.plot ? (
        <ProbabilityPlot plot={d.plot} unit={u} download={`${download} — probability plot`} />
      ) : d.curves?.x && (
        <Plot data={shownChart === "hf" ? [
          ...(d.curves.baseline_hf ? [{ x: d.curves.x, y: d.curves.baseline_hf, mode: "lines", line: { color: MUTED, width: 1.5, dash: "dash" },
            name: priorName }] : []),
          { x: d.curves.x, y: d.curves.hf, mode: "lines", line: { color: ACCENT, width: 2 }, name: bayes ? "Fitted with the prior" : "Hazard rate" },
        ] : [
          ...(d.curves.sf_lower && d.curves.sf_upper ? [
            { x: d.curves.x, y: d.curves.sf_upper, mode: "lines", line: { width: 0 }, hoverinfo: "skip", showlegend: false },
            { x: d.curves.x, y: d.curves.sf_lower, mode: "lines", line: { width: 0 }, fill: "tonexty", fillcolor: BAND_FILL,
              name: bayes ? "90% credible band" : "90% confidence band", hoverinfo: "skip" },
          ] : []),
          ...(d.curves.baseline_sf ? [{ x: d.curves.x, y: d.curves.baseline_sf, mode: "lines", line: { color: MUTED, width: 1.5, dash: "dash" },
            name: priorName }] : []),
          { x: d.curves.x, y: d.curves.sf, mode: "lines", line: { color: ACCENT, width: 2 }, name: bayes ? "Fitted with the prior" : "Fitted" },
        ]} layout={{ height: 320, xaxis: { title: { text: `Age${u ? ` (${u})` : ""}` } },
          // A hazard per hour can be 1e-7: ticks to 3 significant figures (not "5.0049999999e-8").
          yaxis: shownChart === "hf" ? { title: { text: "Hazard rate" }, rangemode: "tozero", tickformat: ".3~g" } : { title: { text: "Reliability" }, range: [0, 1.02] } }}
              download={`${download} — life model`} />
      )}
      <div className="maint-scroll">
        <table className="ml-params fit2-numbers">
          <thead><tr><th />{bayes && <th className="num">Prior</th>}<th className="num">{bayes ? "Fitted" : "Value"} ({d.interval_label})</th></tr></thead>
          <tbody>
            {d.posterior.map((p) => (
              <tr key={p.name}>
                <td>{PARAM_WORDS[p.name] || p.label}</td>
                {bayes && <td className="num">{priorOf(p.name)}</td>}
                <td className="num"><Range p={p} /></td>
              </tr>
            ))}
            {d.b10 && <tr><td>B10 life{u ? ` (${u})` : ""}</td>{bayes && <td className="num">{priorOf("B10")}</td>}<td className="num"><Range p={d.b10} /></td></tr>}
            {d.mean && <tr><td>Mean life{u ? ` (${u})` : ""}</td>{bayes && <td className="num">{priorOf("mean")}</td>}<td className="num"><Range p={d.mean} /></td></tr>}
          </tbody>
        </table>
      </div>
      <div className="fit2-age">
        <label htmlFor="fit2-age">Reliability at</label>
        <TextInput id="fit2-age" inputMode="decimal" value={age} onChange={(e) => onAge(e.target.value)} placeholder="an age" aria-label="Reliability at an age" />
        <span>{u}</span>
        {d.at_age && (
          <span className="fit2-age-r">
            {Math.round(d.at_age.reliability * 1000) / 10}%
            {d.at_age.lower != null && d.at_age.upper != null
              ? ` (${bayes ? "90% credible" : "90% confidence"} ${Math.round(d.at_age.lower * 1000) / 10}–${Math.round(d.at_age.upper * 1000) / 10}%)` : ""}
          </span>
        )}
      </div>
      <p className="rim-tquiet fit2-how">
        How it was computed: {bayes ? `Bayesian (SurPyval fit_bayes), prior: ${d.baseline?.name || "—"}` : "maximum likelihood (SurPyval)"};
        {" "}{countsWords(d.counts)} in {dataWords}.
        {d.prior_note ? ` ${d.prior_note}` : ""}
      </p>
    </>
  );
}
