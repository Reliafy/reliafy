import { useEffect, useMemo, useRef, useState } from "react";
import { linkPositionModel, listModels, previewPositionFit } from "../api.js";
import Modal from "./Modal.jsx";
import Plot from "./Plot.jsx";
import Field from "./ui/Field.jsx";
import { Select, TextInput } from "./ui/Controls.jsx";
import SegmentedControl from "./ui/SegmentedControl.jsx";
import { ModesField, useModes } from "./ModelTable.jsx";
import { ACCENT, BAND_FILL, MUTED } from "../plotTheme.js";
import { saveErrorText } from "../confirm.js";
import { TRUST_CHOICES, rowWords, trustWords } from "../bayesUpdate.js";
import { DATA_CHOICES, METHOD_CHOICES, bodyOf, effective, previewKey, priorChoices, problem } from "../fitDialog.js";
import { fmt } from "../explorerModels.js";

// "Fit a life model…" (Life model ›): one dialog for every fit from history. Which data: this
// position's history, its class's pooled history, or both (this position's, with the class's as a
// prior). Which method: a plain fit (maximum likelihood, 95% confidence bounds) or with a prior
// (Bayesian, 90% credible intervals): the class's history, a saved model, numbers you know or a
// B10 you believe. The result says in words what came out (and what moved), then the numbers, the
// curve against the class or prior, and the history used (untick what doesn't belong).
//
//   position  {id, name, position_class}
//   start     {data?, method?, priorKind?, modelId?}   link: a row it replaces (Refit…)

const PARAM_NAMES = { weibull: ["alpha", "beta"], exponential: ["failure_rate"], lognormal: ["mu", "sigma"] };
const PARAM_WORDS = { alpha: "Characteristic life (alpha)", beta: "Shape (beta)", failure_rate: "Failure rate", mu: "mu", sigma: "sigma" };
const UNITS = ["hours", "days", "weeks", "months", "years"];

function Range({ p }) {
  if (!p) return "—";
  const b = p.lower != null && p.upper != null ? `${fmt(p.lower)}–${fmt(p.upper)}` : p.lower != null ? `≥ ${fmt(p.lower)}` : null;
  return <>{fmt(p.median ?? p.point)}{b ? <span className="rw-sum"> ({b})</span> : null}</>;
}

export default function FitModal({ position, start = {}, link = null, onClose, onDone }) {
  const modes = useModes(position.id);
  const [state, setState] = useState(() => ({
    data: start.data || "position", method: start.method || "mle", priorKind: start.priorKind || "class",
    modelId: start.modelId || null, distribution: "weibull", trust: "guide", unit: "hours", params: {}, b10: {}, shape: {},
    modes: (link?.failure_modes || []).map((f) => f.id), exclude: new Set(), age: "",
  }));
  const set = (k, v) => setState((s) => ({ ...s, [k]: v }));
  const [models, setModels] = useState(null);
  const [preview, setPreview] = useState({ data: null, error: null });
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
    if (wanting) { setPreview({ data: null, error: null }); return undefined; }
    const t = setTimeout(() => {
      previewPositionFit(position.id, body).then((d) => mine === seq.current
        && setPreview(d.refused ? { data: null, error: d.refused } : { data: d, error: null }),
        (e) => mine === seq.current && setPreview({ data: null, error: e.message }));
    }, 300);
    return () => clearTimeout(t);
  }, [key, position.id]); // eslint-disable-line react-hooks/exhaustive-deps

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
  const u = (d?.unit || "").toLowerCase();
  const cls = d?.class_history;
  const bayes = eff.method === "bayes";
  const showDist = !bayes || eff.priorKind === "class";
  const toggle = (id) => setState((s) => {
    const next = new Set(s.exclude);
    if (next.has(id)) next.delete(id); else next.add(id);
    return { ...s, exclude: next };
  });
  return (
    <Modal title={link ? "Refit the life model" : "Fit a life model"} onClose={onClose} locked={saving} trapFocus className="ml-dialog ml-fit"
           footer={(
             <>
               <button type="button" className="secondary" onClick={onClose} disabled={saving}>Cancel</button>
               <button type="button" onClick={save} disabled={saving || !d?.can_save} aria-busy={saving || undefined}>
                 {saving ? "Saving…" : "Save as this position's model"}
               </button>
             </>
           )}>
      <Field label="Data" as="fieldset"
             help={state.data === "class" && cls ? `${cls.positions} positions of the class ${cls.name}: ${cls.failures} failures, ${cls.suspensions} suspensions.`
               : state.data === "both" ? "This position's history is the data; the class's other positions' history is the prior, weighed by how much you trust it." : null}>
        <SegmentedControl size="sm" label="Data" value={state.data} onChange={(v) => set("data", v)}
                          options={DATA_CHOICES.filter((c) => c.value === "position" || position.position_class)} />
      </Field>
      {state.data !== "both" && (
        <Field label="Method" as="fieldset" help={bayes ? "Bayesian: a prior moved by the data; 90% credible intervals." : "Maximum likelihood: the numbers that make the data most likely; 95% confidence bounds."}>
          <SegmentedControl size="sm" label="Method" value={eff.method} onChange={(v) => set("method", v)} options={METHOD_CHOICES} />
        </Field>
      )}
      {bayes && state.data !== "both" && (
        <Field label="Prior" as="fieldset" help={state.data === "class" ? "The class's history is the data here, so it can't be the prior too." : null}>
          <SegmentedControl size="sm" label="Prior" value={eff.priorKind} onChange={(v) => set("priorKind", v)}
                            options={priorChoices(state.data).filter((p) => p.value !== "class" || position.position_class)} />
        </Field>
      )}
      {bayes && eff.priorKind === "model" && (
        <Field label="Prior model">
          <Select value={state.modelId || ""} onChange={(e) => set("modelId", e.target.value || null)}>
            <option value="">{models === null ? "Loading models…" : "Pick a Weibull, exponential or lognormal model"}</option>
            {(models || []).map((m) => <option key={m.id} value={m.id}>{m.name}{m.is_sample ? " (sample)" : ""}</option>)}
          </Select>
        </Field>
      )}
      {bayes && eff.priorKind === "params" && (
        <div className="ml-row">
          <Field label="Distribution">
            <Select value={state.distribution === "best" ? "weibull" : state.distribution} onChange={(e) => set("distribution", e.target.value)}>
              <option value="weibull">Weibull</option><option value="exponential">Exponential</option><option value="lognormal">Lognormal</option>
            </Select>
          </Field>
          {PARAM_NAMES[state.distribution === "best" ? "weibull" : state.distribution].map((k) => (
            <Field key={k} label={PARAM_WORDS[k]}>
              <TextInput inputMode="decimal" value={state.params[k] || ""} onChange={(e) => set("params", { ...state.params, [k]: e.target.value })} />
            </Field>
          ))}
          <Field label="Unit"><Select value={state.unit} onChange={(e) => set("unit", e.target.value)}>{UNITS.map((x) => <option key={x} value={x}>{x}</option>)}</Select></Field>
        </div>
      )}
      {bayes && eff.priorKind === "b10" && (
        <div className="ml-row">
          <Field label="B10 about"><TextInput inputMode="decimal" value={state.b10.value || ""} onChange={(e) => set("b10", { ...state.b10, value: e.target.value })} /></Field>
          <Field label="Surprised under"><TextInput inputMode="decimal" value={state.b10.low || ""} onChange={(e) => set("b10", { ...state.b10, low: e.target.value })} /></Field>
          <Field label="Surprised over"><TextInput inputMode="decimal" value={state.b10.high || ""} onChange={(e) => set("b10", { ...state.b10, high: e.target.value })} /></Field>
          <Field label="Unit"><Select value={state.unit} onChange={(e) => set("unit", e.target.value)}>{UNITS.map((x) => <option key={x} value={x}>{x}</option>)}</Select></Field>
        </div>
      )}
      {bayes && (
        <Field label="How much to trust the prior" as="fieldset"
               help={eff.priorKind === "class"
                 ? `The class's history counts as ${{ close: "all", guide: "half", start: "a fifth" }[state.trust]} of its evidence.`
                 : trustWords(TRUST_CHOICES.find((t) => t.value === state.trust))}>
          <SegmentedControl size="sm" label="How much to trust the prior" value={state.trust} onChange={(v) => set("trust", v)}
                            options={TRUST_CHOICES.map((t) => ({ value: t.value, label: t.label }))} />
        </Field>
      )}
      {showDist && (
        <Field label="Distribution">
          <Select value={state.distribution} onChange={(e) => set("distribution", e.target.value)}>
            <option value="weibull">Weibull</option><option value="exponential">Exponential</option><option value="lognormal">Lognormal</option>
            {!bayes && <option value="best">The best fit of these</option>}
          </Select>
        </Field>
      )}
      <ModesField modes={modes} value={state.modes} onChange={(v) => set("modes", v)} />
      {(preview.error || wanting) && <p className={preview.error ? "field-error" : "rim-tquiet"} role={preview.error ? "alert" : undefined}>{preview.error || wanting}</p>}
      {!d && !preview.error && !wanting && <p className="rim-tquiet">Working it out…</p>}
      {d && (
        <>
          <p className="ml-lead" role="status">{d.words}</p>
          {(d.warnings || []).map((w) => <p key={w} className="ml-stale" role="note">{w}</p>)}
          {d.curves?.x && (
            <Plot data={[
              ...(d.curves.sf_lower && d.curves.sf_upper ? [
                { x: d.curves.x, y: d.curves.sf_upper, mode: "lines", line: { width: 0 }, hoverinfo: "skip", showlegend: false },
                { x: d.curves.x, y: d.curves.sf_lower, mode: "lines", line: { width: 0 }, fill: "tonexty", fillcolor: BAND_FILL,
                  name: d.method === "bayes" ? "90% credible band" : "95% confidence band", hoverinfo: "skip" },
              ] : []),
              ...(d.curves.baseline_sf ? [{ x: d.curves.x, y: d.curves.baseline_sf, mode: "lines", line: { color: MUTED, width: 1.5, dash: "dash" },
                name: eff.priorKind === "class" ? "The class's own fit" : "The prior" }] : []),
              { x: d.curves.x, y: d.curves.sf, mode: "lines", line: { color: ACCENT, width: 2 }, name: d.method === "bayes" ? "Fitted with the prior" : "Fitted" },
            ]} layout={{ height: 230, xaxis: { title: { text: `Age${u ? ` (${u})` : ""}` } }, yaxis: { title: { text: "Reliability" }, range: [0, 1.02] } }}
                  download={`${position.name} — life model`} />
          )}
          <div className="maint-scroll">
            <table className="ml-params">
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
          <p className="rim-tquiet">{d.method === "bayes"
            ? "Ranges are 90% credible intervals: a 90% chance the value lies between them, given the prior and the data."
            : "Ranges are 95% confidence bounds (B10 and mean life: a 90% lower bound)."}</p>
          <Field label={state.data === "class" ? "The class's history" : `${position.name}’s history`} as="fieldset"
                 help="Untick any that don't belong (a failure caused by something else, a unit never really in service).">
            {d.rows.length === 0 ? <p className="rim-tquiet">No history yet.</p> : (
              <div className="ml-modes">
                {d.rows.map((r, i) => (
                  <label key={r.fitment_id || i} className="ml-mode">
                    <input type="checkbox" checked={!state.exclude.has(r.fitment_id)} disabled={!r.fitment_id}
                           onChange={() => toggle(r.fitment_id)} />
                    {rowWords(r, d.unit)}{r.position && state.data === "class" ? ` · ${r.position}` : ""}{r.item ? ` · ${r.item}` : ""}
                  </label>
                ))}
              </div>
            )}
          </Field>
        </>
      )}
      {failed && <p className="field-error" role="alert">{failed}</p>}
    </Modal>
  );
}
