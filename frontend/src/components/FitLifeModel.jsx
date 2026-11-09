import { useEffect, useMemo, useRef, useState } from "react";
import { getLibraryRecord, getLibrarySources, linkPositionModel, listModels, previewPositionFit } from "../api.js";
import Plot from "./Plot.jsx";
import ProbabilityPlot from "./ProbabilityPlot.jsx";
import ChoiceChips from "./ui/ChoiceChips.jsx";
import { Select, TextInput } from "./ui/Controls.jsx";
import SegmentedControl from "./ui/SegmentedControl.jsx";
import { useModes } from "./ModelTable.jsx";
import { ACCENT, BAND_FILL, MUTED } from "../plotTheme.js";
import { saveErrorText } from "../confirm.js";
import { TRUST_CHOICES } from "../bayesUpdate.js";
import {
  AROUND_PARAMS, METHOD_CHOICES, METHOD_LINE, bodyOf, countsWords, dataOptions, effective, forWords, historyRow, previewKey,
  fitChanged, fitTitle, initialFit, libraryPriorWords, priorChoices, problem, refusalSwitch, refusalWords, showsTrust,
} from "../fitDialog.js";
import { fmt } from "../explorerModels.js";
import TablePane from "./TablePane.jsx";
import LibraryRecordPicker, { PickedRecord } from "./LibraryRecordPicker.jsx";
import { RecordCovariatesField, useRecordCovariates } from "./LibraryParts.jsx";
import { rowFromDetail } from "../libraryPicker.js";
import "./RcmWorksheet.css";
import "./FitLifeModel.css";

// "Fit a life model…" (Life model ›) fills the Explorer's table area, the tree kept beside it
// (Derryn, 9 Nov 2026: "It shouldn't be a modal itself, only the select life model from the
// library"). FitPane is that area: a heading ("Fit a life model · <position>") with a close, and
// FitLifeModel under it: inputs on the left as a step | choice grid (Data with the history under
// it, Method, Prior, Distribution, For), the result on the right (what came out, the curve, the
// numbers, reliability at an age, how it was computed, Save). Both columns scroll on their own;
// when the area is narrow they stack, inputs first, Save at the foot. Every change asks again a
// moment later (fitDialog.previewKey: the request and what's missing). Only the library record
// picker is a dialog, over the pane.
//
//   position  {id, name, position_class}
//   start     {data?, method?, priorKind?, modelId?, recordId?}   link: a row it replaces (Refit…)

const PARAM_NAMES = { weibull: ["alpha", "beta"], exponential: ["failure_rate"], lognormal: ["mu", "sigma"] };
const PARAM_WORDS = { alpha: "Characteristic life (alpha)", beta: "Shape (beta)", failure_rate: "Failure rate", mu: "mu", sigma: "sigma" };
const UNITS = ["hours", "days", "weeks", "months", "years"];

function Range({ p }) {
  if (!p) return "—";
  const b = p.lower != null && p.upper != null ? `${fmt(p.lower)}–${fmt(p.upper)}` : p.lower != null ? `≥ ${fmt(p.lower)}` : null;
  return <>{fmt(p.median ?? p.point)}{b ? <span className="rw-sum"> ({b})</span> : null}</>;
}

function Step({ label, children }) {
  return (
    <>
      <div className="rw-sl">{label}</div>
      <div className="rw-sc">{children}</div>
    </>
  );
}

// "For": every failure of the position, or the failure modes picked from a small list with a search.
function ForPicker({ modes, value, onChange }) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const shown = (modes || []).filter((m) => !q.trim() || m.text.toLowerCase().includes(q.trim().toLowerCase()));
  return (
    <div className="fit2-for">
      <button type="button" className="secondary sm fit2-for-btn" aria-haspopup="true" aria-expanded={open}
              onClick={() => setOpen((o) => !o)} disabled={modes === null}>
        {modes === null ? "Reading its failure modes…" : forWords(modes, value)} <span aria-hidden="true">▾</span>
      </button>
      {open && (
        <div className="fit2-for-list" role="group" aria-label="Failure modes it's for">
          <TextInput type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search failure modes" aria-label="Search failure modes" />
          <label className="ml-mode"><input type="checkbox" checked={!value.length} onChange={() => onChange([])} /> All failures of this position</label>
          {shown.map((m) => (
            <label key={m.id} className="ml-mode">
              <input type="checkbox" checked={value.includes(m.id)}
                     onChange={(e) => onChange(e.target.checked ? [...value, m.id] : value.filter((x) => x !== m.id))} />
              {m.text}
            </label>
          ))}
          {modes?.length === 0 && <p className="rim-tquiet">No failure modes yet.</p>}
        </div>
      )}
    </div>
  );
}

// The fit in the table area. `onDirty(changed)`: whether anything has been changed since it
// opened (selecting another row asks "Discard this fit?" only then). `onSaving(busy)`: while
// it saves, it can't be closed. `headingRef`: its heading,
// focused when it opens. `phone`: it takes the screen, with Back.
export function FitPane({ position, start = {}, link = null, phone = false, headingRef = null, onClose, onDone, onDirty, onSaving }) {
  const [saving, setSavingState] = useState(false);
  const setSaving = (v) => { setSavingState(v); onSaving?.(v); };
  return (
    <TablePane title={fitTitle(link)} subject={position.name} phone={phone} busy={saving} headingRef={headingRef} onClose={onClose}
               className="fit-pane">
      <FitLifeModel position={position} start={start} link={link} onClose={onClose} onDone={onDone} onDirty={onDirty} onSaving={setSaving} />
    </TablePane>
  );
}

export default function FitLifeModel({ position, start = {}, link = null, onClose, onDone, onDirty, onSaving }) {
  const modes = useModes(position.id);
  const [opened] = useState(() => initialFit(start, link));
  const [state, setState] = useState(opened);
  const set = (k, v) => setState((s) => ({ ...s, [k]: v }));
  const changed = fitChanged(opened, state);
  useEffect(() => { onDirty?.(changed); }, [changed]); // eslint-disable-line react-hooks/exhaustive-deps
  // The picker closed: focus back on what opens it ("Change…", or "Pick a library record…").
  const pickArea = useRef(null);
  const closePicker = () => {
    setPicking(false);
    setTimeout(() => pickArea.current?.querySelector(".lib-picked-acts button, .lib-picked-pick")?.focus({ preventScroll: true }), 0);
  };
  const [models, setModels] = useState(null);
  // The library record picked as the prior (its kind and bounds shape the words beside the picker).
  const [record, setRecord] = useState(null);
  // "Pick a library record" (a modal over this one): open, and whether it has opened by itself yet
  // (the first time "A library record" is chosen with nothing picked).
  const [picking, setPicking] = useState(false);
  const autoOpened = useRef(false);
  // Opened with a record already chosen (Use as a prior… on a record's page): read it for the summary.
  useEffect(() => {
    if (!state.recordId || record?.id === state.recordId) return undefined;
    let live = true;
    Promise.all([getLibraryRecord(state.recordId), getLibrarySources().catch(() => ({ sources: [] }))])
      .then(([d, src]) => live && setRecord(rowFromDetail(d, src.sources)), () => {});
    return () => { live = false; };
  }, [state.recordId]); // eslint-disable-line react-hooks/exhaustive-deps
  // The record's covariates (a pipe's length, the clock, the demands a year...): the shared calculator
  // under the picked record, its values kept on the request.
  const libCov = useRecordCovariates(state.recordId, opened.libCov);
  const libSig = JSON.stringify([libCov.toSave, libCov.missing.map((i) => i.label)]);
  useEffect(() => {
    setState((s) => ({ ...s, libCov: libCov.toSave, libMissing: libCov.missing.map((i) => i.label) }));
  }, [libSig]); // eslint-disable-line react-hooks/exhaustive-deps
  const [preview, setPreview] = useState({ data: null, refused: null, busy: false });
  const [chart, setChart] = useState("sf");
  const [saving, setSaving] = useState(false);
  const [failed, setFailed] = useState(null);
  const seq = useRef(0);
  const eff = effective(state);
  const wanting = problem(state);

  useEffect(() => {
    let live = true;
    listModels().then((out) => live && setModels((out.models || []).filter((m) => m.kind === "distribution"
      && /weibull|exponential|lognormal/i.test(m.distribution || ""))), () => live && setModels([]));
    return () => { live = false; };
  }, []);

  const body = useMemo(() => bodyOf({ ...state, kind: eff.priorKind }), [state, eff.priorKind]);
  const key = previewKey(state);
  useEffect(() => {
    const mine = ++seq.current;
    if (wanting) { setPreview((p) => ({ ...p, refused: null, busy: false, data: null })); return undefined; }
    setPreview((p) => ({ ...p, busy: true }));
    const t = setTimeout(() => {
      previewPositionFit(position.id, body).then((d) => {
        if (mine !== seq.current) return;
        setPreview(d.refused ? { data: null, refused: d, busy: false } : { data: d, refused: null, busy: false });
      }, (e) => mine === seq.current && setPreview({ data: null, refused: { refused: e.message }, busy: false }));
    }, 300);
    return () => clearTimeout(t);
  }, [key, position.id]); // eslint-disable-line react-hooks/exhaustive-deps
  // A plain fit opens on its probability plot; one with a prior on the reliability curve.
  useEffect(() => setChart(eff.method === "mle" ? "paper" : "sf"), [eff.method]);

  useEffect(() => { onSaving?.(saving); }, [saving]); // eslint-disable-line react-hooks/exhaustive-deps
  const save = async () => {
    setSaving(true);
    setFailed(null);
    try {
      const made = await linkPositionModel(position.id, { fit: true, ...body, ...(link ? { replace_link_id: link.id } : {}) });
      onDone(made, `Saved ${made.name} and attached it to ${position.name}.`);
    } catch (e) {
      setSaving(false);
      setFailed(saveErrorText(e, { offline: navigator.onLine === false }));
    }
  };
  const d = preview.data;
  const ctx = d || preview.refused; // the history and counts come with a refusal too
  // The Data dropdown's counts: this position's, remembered from whichever preview last read them.
  const [positionCounts, setPositionCounts] = useState(null);
  useEffect(() => {
    if (ctx?.counts && ctx.data !== "class") setPositionCounts(ctx.counts);
  }, [ctx?.counts, ctx?.data]);
  const u = (ctx?.unit || "").toLowerCase();
  const cls = ctx?.class_history;
  const bayes = eff.method === "bayes";
  const showDist = !bayes || ["class", "around", "library"].includes(eff.priorKind);
  const rows = ctx?.rows || [];
  const toggle = (id) => setState((s) => {
    const next = new Set(s.exclude);
    if (next.has(id)) next.delete(id); else next.add(id);
    return { ...s, exclude: next };
  });
  const way = preview.refused ? refusalSwitch(eff.method) : null;
  const charts = [...(d?.plot && !bayes ? [{ value: "paper", label: "Probability plot" }] : []), { value: "sf", label: "Reliability" },
    ...(d?.curves?.hf ? [{ value: "hf", label: "Hazard" }] : [])];
  const shownChart = charts.some((c) => c.value === chart) ? chart : "sf";
  return (
    <>
      <div className="fit2">
        <section className="fit2-in" aria-label="What to fit">
          <div className="rw-sg rw-steps-first fit2-grid">
            <Step label="Data">
              <Select aria-label="Data" value={state.data} onChange={(e) => set("data", e.target.value)}>
                {dataOptions({ positionCounts, cls: ctx?.class_history, hasClass: !!position.position_class })
                  .map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
              </Select>
              <p className="fit2-sum">
                {state.data === "class" && cls ? `${cls.positions} positions of ${cls.name}: ${countsWords(cls)}`
                  : ctx?.counts ? countsWords(ctx.counts) : "…"}
                {state.data === "both" && cls ? ` · prior: the class ${cls.name}'s other positions` : ""}
              </p>
              {rows.length > 0 && (
                <div className="fit2-hist maint-scroll">
                  <table className="ml-params">
                    <thead><tr><th>When</th><th>What happened</th><th className="num">Age</th><th>Counts as</th><th><span className="sr-only">Use</span></th></tr></thead>
                    <tbody>
                      {rows.map((r, i) => {
                        const h = historyRow(r, ctx.unit);
                        return (
                          <tr key={r.fitment_id || i} className={state.exclude.has(r.fitment_id) ? "off" : undefined}>
                            <td>{h.when}</td><td>{h.what}</td><td className="num">{h.age}</td><td>{h.kind}</td>
                            <td><input type="checkbox" aria-label={`Use ${h.what} ${h.when}`} checked={!state.exclude.has(r.fitment_id)}
                                       disabled={!r.fitment_id} onChange={() => toggle(r.fitment_id)} /></td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </Step>
            {state.data !== "both" && (
              <Step label="Method">
                <ChoiceChips label="Method" className="sm" value={eff.method} onChange={(v) => v && set("method", v)} options={METHOD_CHOICES} />
              </Step>
            )}
            {bayes && (
              <Step label="Prior">
                {state.data !== "both" && (
                  <Select aria-label="Prior" value={eff.priorKind} onChange={(e) => {
                    set("priorKind", e.target.value);
                    if (e.target.value === "library" && !state.recordId && !autoOpened.current) { autoOpened.current = true; setPicking(true); }
                  }}>
                    {priorChoices(state.data).filter((p) => p.value !== "class" || position.position_class)
                      .map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
                  </Select>
                )}
                {showsTrust(eff.priorKind) && (
                  <ChoiceChips label="How much to trust the prior" className="sm" value={state.trust} onChange={(v) => v && set("trust", v)}
                               options={TRUST_CHOICES.map((t) => ({ value: t.value, label: t.label }))} />
                )}
                {eff.priorKind === "library" && (
                  <>
                    <div ref={pickArea} className="fit2-pick">
                      <PickedRecord record={state.recordId ? record || { id: state.recordId } : null} onPick={() => setPicking(true)} />
                    </div>
                    {state.recordId && <p className="fit2-sum">{libraryPriorWords(state.distribution, record)}</p>}
                    {state.recordId && record?.kind !== "life" && <RecordCovariatesField recordId={state.recordId} cov={libCov} idPrefix="fitcov" />}
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
                {eff.priorKind === "around" && (
                  <div className="fit2-around" role="group" aria-label="Around a value, between two bounds">
                    <div className="fit2-around-head" aria-hidden="true"><span /><span>about</span><span>between</span><span>and</span></div>
                    {AROUND_PARAMS[state.distribution === "best" ? "weibull" : state.distribution].map(([k, label]) => (
                      <div key={k} className="fit2-around-row">
                        <span className="fit2-around-name">{label}</span>
                        {[["about", "about"], ["lo", "between"], ["hi", "and"]].map(([f, word]) => (
                          <TextInput key={f} inputMode="decimal" aria-label={`${label} ${word}`} value={state.around[k]?.[f] || ""}
                                     onChange={(e) => set("around", { ...state.around, [k]: { ...(state.around[k] || {}), [f]: e.target.value } })} />
                        ))}
                      </div>
                    ))}
                    <Select aria-label="Unit" value={state.unit} onChange={(e) => set("unit", e.target.value)}>{UNITS.map((x) => <option key={x} value={x}>{x}</option>)}</Select>
                  </div>
                )}
                {eff.priorKind === "model" && (
                  <Select aria-label="Prior model" value={state.modelId || ""} onChange={(e) => set("modelId", e.target.value || null)}>
                    <option value="">{models === null ? "Loading models…" : "Pick a Weibull, exponential or lognormal model"}</option>
                    {(models || []).map((m) => <option key={m.id} value={m.id}>{m.name}{m.is_sample ? " (sample)" : ""}</option>)}
                  </Select>
                )}
                {eff.priorKind === "params" && (
                  <div className="fit2-pair">
                    <Select aria-label="Prior distribution" value={state.distribution === "best" ? "weibull" : state.distribution} onChange={(e) => set("distribution", e.target.value)}>
                      <option value="weibull">Weibull</option><option value="exponential">Exponential</option><option value="lognormal">Lognormal</option>
                    </Select>
                    <Select aria-label="Unit" value={state.unit} onChange={(e) => set("unit", e.target.value)}>{UNITS.map((x) => <option key={x} value={x}>{x}</option>)}</Select>
                    {PARAM_NAMES[state.distribution === "best" ? "weibull" : state.distribution].map((k) => (
                      <TextInput key={k} inputMode="decimal" aria-label={PARAM_WORDS[k]} placeholder={PARAM_WORDS[k]} value={state.params[k] || ""}
                                 onChange={(e) => set("params", { ...state.params, [k]: e.target.value })} />
                    ))}
                  </div>
                )}
                {eff.priorKind === "b10" && (
                  <div className="fit2-pair">
                    <TextInput inputMode="decimal" aria-label="B10 about" placeholder="B10 about" value={state.b10.value || ""} onChange={(e) => set("b10", { ...state.b10, value: e.target.value })} />
                    <Select aria-label="Unit" value={state.unit} onChange={(e) => set("unit", e.target.value)}>{UNITS.map((x) => <option key={x} value={x}>{x}</option>)}</Select>
                    <TextInput inputMode="decimal" aria-label="Surprised under" placeholder="Surprised under" value={state.b10.low || ""} onChange={(e) => set("b10", { ...state.b10, low: e.target.value })} />
                    <TextInput inputMode="decimal" aria-label="Surprised over" placeholder="Surprised over" value={state.b10.high || ""} onChange={(e) => set("b10", { ...state.b10, high: e.target.value })} />
                  </div>
                )}
              </Step>
            )}
            {showDist && (
              <Step label="Distribution">
                <Select aria-label="Distribution" value={state.distribution} onChange={(e) => set("distribution", e.target.value)}>
                  <option value="weibull">Weibull</option><option value="exponential">Exponential</option><option value="lognormal">Lognormal</option>
                  {!bayes && <option value="best">The best fit of these</option>}
                </Select>
              </Step>
            )}
            <Step label="For"><ForPicker modes={modes} value={state.modes} onChange={(v) => set("modes", v)} /></Step>
          </div>
        </section>
        <section className="fit2-out" aria-label="The fit" aria-busy={preview.busy || undefined}>
          <p className="fit2-sub">{METHOD_LINE[eff.method]}</p>
          {preview.busy && <p className="rim-tquiet">Working it out…</p>}
          {!preview.busy && wanting && <p className="rim-tquiet">{wanting}</p>}
          {!preview.busy && preview.refused && (
            <p className="field-error" role="alert">
              {refusalWords(preview.refused.refused)}
              {way && <> <button type="button" className="link" onClick={() => set("method", way.to)}>{way.label}</button></>}
            </p>
          )}
          {d && (
            <>
              <p className="ml-lead" role="status">{d.words}</p>
              {(d.warnings || []).map((w) => <p key={w} className="ml-stale" role="note">{w}</p>)}
              {charts.length > 1 && <SegmentedControl size="sm" label="What to plot" value={shownChart} onChange={setChart} options={charts} />}
              {shownChart === "paper" && d.plot ? (
                <ProbabilityPlot plot={d.plot} unit={u} download={`${position.name} — probability plot`} />
              ) : d.curves?.x && (
                <Plot data={shownChart === "hf" ? [
                  ...(d.curves.baseline_hf ? [{ x: d.curves.x, y: d.curves.baseline_hf, mode: "lines", line: { color: MUTED, width: 1.5, dash: "dash" },
                    name: eff.priorKind === "class" ? "The class's own fit" : "The prior" }] : []),
                  { x: d.curves.x, y: d.curves.hf, mode: "lines", line: { color: ACCENT, width: 2 }, name: d.method === "bayes" ? "Fitted with the prior" : "Hazard rate" },
                ] : [
                  ...(d.curves.sf_lower && d.curves.sf_upper ? [
                    { x: d.curves.x, y: d.curves.sf_upper, mode: "lines", line: { width: 0 }, hoverinfo: "skip", showlegend: false },
                    { x: d.curves.x, y: d.curves.sf_lower, mode: "lines", line: { width: 0 }, fill: "tonexty", fillcolor: BAND_FILL,
                      name: d.method === "bayes" ? "90% credible band" : "95% confidence band", hoverinfo: "skip" },
                  ] : []),
                  ...(d.curves.baseline_sf ? [{ x: d.curves.x, y: d.curves.baseline_sf, mode: "lines", line: { color: MUTED, width: 1.5, dash: "dash" },
                    name: eff.priorKind === "class" ? "The class's own fit" : "The prior" }] : []),
                  { x: d.curves.x, y: d.curves.sf, mode: "lines", line: { color: ACCENT, width: 2 }, name: d.method === "bayes" ? "Fitted with the prior" : "Fitted" },
                ]} layout={{ height: 320, xaxis: { title: { text: `Age${u ? ` (${u})` : ""}` } },
                  // A hazard per hour can be 1e-7: ticks to 3 significant figures (not "5.0049999999e-8").
                  yaxis: shownChart === "hf" ? { title: { text: "Hazard rate" }, rangemode: "tozero", tickformat: ".3~g" } : { title: { text: "Reliability" }, range: [0, 1.02] } }}
                      download={`${position.name} — life model`} />
              )}
              <div className="maint-scroll">
                <table className="ml-params fit2-numbers">
                  <thead><tr><th />{d.method === "bayes" && <th className="num">Prior</th>}<th className="num">{d.method === "bayes" ? "Fitted" : "Value"} ({d.interval_label})</th></tr></thead>
                  <tbody>
                    {d.posterior.map((p) => (
                      <tr key={p.name}>
                        <td>{PARAM_WORDS[p.name] || p.label}</td>
                        {d.method === "bayes" && <td className="num">{(() => { const b = (d.prior || []).find((x) => x.name === p.name); return b ? <Range p={b} /> : "—"; })()}</td>}
                        <td className="num"><Range p={p} /></td>
                      </tr>
                    ))}
                    {d.b10 && <tr><td>B10 life{u ? ` (${u})` : ""}</td>{d.method === "bayes" && <td className="num">{(() => { const b = (d.prior || []).find((x) => x.name === "B10"); return b ? <Range p={b} /> : "—"; })()}</td>}<td className="num"><Range p={d.b10} /></td></tr>}
                    {d.mean && <tr><td>Mean life{u ? ` (${u})` : ""}</td>{d.method === "bayes" && <td className="num">{(() => { const b = (d.prior || []).find((x) => x.name === "mean"); return b ? <Range p={b} /> : "—"; })()}</td>}<td className="num"><Range p={d.mean} /></td></tr>}
                  </tbody>
                </table>
              </div>
              <div className="fit2-age">
                <label htmlFor="fit2-age">Reliability at</label>
                <TextInput id="fit2-age" inputMode="decimal" value={state.age} onChange={(e) => set("age", e.target.value)} placeholder="an age" aria-label="Reliability at an age" />
                <span>{u}</span>
                {d.at_age && (
                  <span className="fit2-age-r">
                    {Math.round(d.at_age.reliability * 1000) / 10}%
                    {d.at_age.lower != null && d.at_age.upper != null
                      ? ` (${d.method === "bayes" ? "90% credible" : "95% confidence"} ${Math.round(d.at_age.lower * 1000) / 10}–${Math.round(d.at_age.upper * 1000) / 10}%)` : ""}
                  </span>
                )}
              </div>
              <p className="rim-tquiet fit2-how">
                How it was computed: {d.method === "bayes" ? `Bayesian (SurPyval fit_bayes), prior: ${d.baseline?.name || "—"}` : "maximum likelihood (SurPyval)"};
                {" "}{countsWords(d.counts)} in {state.data === "class" ? "the class's history" : "this position's history"}.
                {d.prior_note ? ` ${d.prior_note}` : ""}
              </p>
            </>
          )}
          {failed && <p className="field-error" role="alert">{failed}</p>}
          <div className="fit2-foot">
            <button type="button" className="secondary" onClick={onClose} disabled={saving}>Cancel</button>
            <button type="button" onClick={save} disabled={saving || !d?.can_save} aria-busy={saving || undefined}>
              {saving ? "Saving…" : "Save as this position's model"}
            </button>
          </div>
        </section>
      </div>
      {picking && (
        <LibraryRecordPicker use="prior" selectedId={state.recordId} onClose={closePicker}
                             onPick={(r) => { set("recordId", r.id); setRecord(r); closePicker(); }} />
      )}
    </>
  );
}
