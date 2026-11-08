import { useEffect, useMemo, useRef, useState } from "react";
import { listModels, previewPositionBayes, savePositionBayes } from "../api.js";
import Modal from "./Modal.jsx";
import Plot from "./Plot.jsx";
import Field from "./ui/Field.jsx";
import { Select, TextInput } from "./ui/Controls.jsx";
import SegmentedControl from "./ui/SegmentedControl.jsx";
import { ACCENT, BAND_FILL, MUTED } from "../plotTheme.js";
import { saveErrorText } from "../confirm.js";
import { BASELINE_KINDS, TRUST_CHOICES, bodyOf, ready, rowWords, trustWords } from "../bayesUpdate.js";
import { fmt } from "../explorerModels.js";

// "Update a baseline with this position's history…" (the Modelling tab's heading "…", and a
// model row's ⋯): a Bayesian update. Pick the baseline (the class's model, a saved model,
// numbers, or a B10 you believe) and how much to trust it; the position's own failures and
// suspensions (tick out any that don't belong) move it. The result says in words what moved
// and how far, then the numbers with 90% credible intervals, and a plot of the baseline
// against the update. "Save as this position's model" keeps it in Models and attaches it.
//
//   position   {id, name, position_class}     start   {modelId?, link?}: a row's model as the baseline
//   onDone     (link, text) after a save

const PARAM_NAMES = { weibull: ["alpha", "beta"], exponential: ["failure_rate"], lognormal: ["mu", "sigma"] };
const PARAM_WORDS = { alpha: "Characteristic life (alpha)", beta: "Shape (beta)", failure_rate: "Failure rate", mu: "mu", sigma: "sigma" };

function RangeCell({ p }) {
  return <>{fmt(p.median)} <span className="rw-sum">({fmt(p.lower)}–{fmt(p.upper)})</span></>;
}

export default function BayesUpdateModal({ position, start = null, onClose, onDone }) {
  const [state, setState] = useState(() => ({
    kind: start?.modelId ? "model" : position.position_class ? "class" : "model",
    modelId: start?.modelId || null, trust: "guide", exclude: new Set(), age: "",
    distribution: "weibull", unit: "hours", params: {}, b10: {}, shape: {},
  }));
  const set = (k, v) => setState((s) => ({ ...s, [k]: v }));
  const [models, setModels] = useState(null);
  const [preview, setPreview] = useState({ data: null, error: null, busy: false });
  const [saving, setSaving] = useState(false);
  const [failed, setFailed] = useState(null);
  const seq = useRef(0);
  const again = start?.link?.role === "bayesian";

  useEffect(() => {
    let live = true;
    listModels().then((out) => live && setModels((out.models || []).filter((m) => m.kind === "distribution"
      && /weibull|exponential|lognormal/i.test(m.distribution || ""))), () => live && setModels([]));
    return () => { live = false; };
  }, []);

  // Asked again a moment after each change.
  const body = useMemo(() => bodyOf(state), [state]);
  useEffect(() => {
    if (!ready(state)) { setPreview({ data: null, error: null, busy: false }); return undefined; }
    const mine = ++seq.current;
    setPreview((p) => ({ ...p, busy: true }));
    const t = setTimeout(() => {
      previewPositionBayes(position.id, body).then(
        (data) => mine === seq.current && setPreview({ data, error: null, busy: false }),
        (e) => mine === seq.current && setPreview({ data: null, error: e.message, busy: false }));
    }, 300);
    return () => clearTimeout(t);
  }, [JSON.stringify(body), position.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const save = async () => {
    setSaving(true);
    setFailed(null);
    try {
      const made = await savePositionBayes(position.id, { ...body, ...(start?.link ? { replace_link_id: start.link.id } : {}) });
      onDone(made, `Saved ${made.name} and attached it to ${position.name}.`);
    } catch (e) {
      setSaving(false);
      setFailed(saveErrorText(e, { offline: navigator.onLine === false }));
    }
  };

  const d = preview.data;
  const unit = d?.unit || "";
  const u = unit.toLowerCase();
  const toggle = (id) => setState((s) => {
    const next = new Set(s.exclude);
    if (next.has(id)) next.delete(id); else next.add(id);
    return { ...s, exclude: next };
  });
  return (
    <Modal title={again ? "Update with new failures" : "Update a baseline with this position's history"} onClose={onClose}
           locked={saving} trapFocus className="ml-dialog ml-bayes"
           footer={(
             <>
               <button type="button" className="secondary" onClick={onClose} disabled={saving}>Cancel</button>
               <button type="button" onClick={save} disabled={saving || !d?.can_save} aria-busy={saving || undefined}
                       title={d && !d.can_save ? "There's no history to update with yet" : undefined}>
                 {saving ? "Saving…" : "Save as this position's model"}
               </button>
             </>
           )}>
      <p className="rw-fhelp">
        {again
          ? <>Adds {position.name}’s failures since the last update to it, keeping the baseline and how much it was trusted.</>
          : <>With one or two failures a position’s own history says little. This starts from a baseline you trust (its class’s model, a vendor’s or handbook’s numbers, a B10 you believe) and lets {position.name}’s failures and running units move it. With plenty of failures, fit the history instead.</>}
      </p>
      {!again && (
        <>
          <Field label="Start from" as="fieldset">
            <SegmentedControl size="sm" label="Start from" value={state.kind} onChange={(v) => set("kind", v)}
                              options={BASELINE_KINDS.filter((k) => k.value !== "class" || position.position_class)} />
          </Field>
          {state.kind === "model" && (
            <Field label="Baseline model">
              <Select value={state.modelId || ""} onChange={(e) => set("modelId", e.target.value || null)}>
                <option value="">{models === null ? "Loading models…" : "Pick a Weibull, exponential or lognormal model"}</option>
                {(models || []).map((m) => <option key={m.id} value={m.id}>{m.name}{m.is_sample ? " (sample)" : ""}</option>)}
              </Select>
            </Field>
          )}
          {state.kind === "params" && (
            <div className="ml-row">
              <Field label="Distribution">
                <Select value={state.distribution} onChange={(e) => set("distribution", e.target.value)}>
                  <option value="weibull">Weibull</option><option value="exponential">Exponential</option><option value="lognormal">Lognormal</option>
                </Select>
              </Field>
              {PARAM_NAMES[state.distribution].map((k) => (
                <Field key={k} label={PARAM_WORDS[k]}>
                  <TextInput inputMode="decimal" value={state.params[k] || ""} onChange={(e) => set("params", { ...state.params, [k]: e.target.value })} />
                </Field>
              ))}
              <Field label="Unit">
                <Select value={state.unit} onChange={(e) => set("unit", e.target.value)}>
                  {["hours", "days", "weeks", "months", "years"].map((x) => <option key={x} value={x}>{x}</option>)}
                </Select>
              </Field>
            </div>
          )}
          {state.kind === "b10" && (
            <div className="ml-row">
              <Field label="B10 about"><TextInput inputMode="decimal" value={state.b10.value || ""} onChange={(e) => set("b10", { ...state.b10, value: e.target.value })} /></Field>
              <Field label="Surprised under"><TextInput inputMode="decimal" value={state.b10.low || ""} onChange={(e) => set("b10", { ...state.b10, low: e.target.value })} /></Field>
              <Field label="Surprised over"><TextInput inputMode="decimal" value={state.b10.high || ""} onChange={(e) => set("b10", { ...state.b10, high: e.target.value })} /></Field>
              <Field label="Unit">
                <Select value={state.unit} onChange={(e) => set("unit", e.target.value)}>
                  {["hours", "days", "weeks", "months", "years"].map((x) => <option key={x} value={x}>{x}</option>)}
                </Select>
              </Field>
              <p className="rim-tquiet">The B10 is the age by which 10% have failed. It assumes wear-out, a Weibull shape between 1.2 and 4.</p>
            </div>
          )}
          <Field label="How much to trust it" as="fieldset" help={trustWords(TRUST_CHOICES.find((t) => t.value === state.trust))}>
            <SegmentedControl size="sm" label="How much to trust it" value={state.trust} onChange={(v) => set("trust", v)}
                              options={TRUST_CHOICES.map((t) => ({ value: t.value, label: t.label }))} />
          </Field>
        </>
      )}
      {preview.error && <p className="field-error" role="alert">{preview.error}</p>}
      {!d && !preview.error && <p className="rim-tquiet">{ready(state) ? "Working it out…" : "Give the baseline to see the update."}</p>}
      {d && (
        <>
          <p className="ml-lead" role="status">{d.words}</p>
          {d.curves && (
            <Plot data={[
              { x: d.curves.x, y: d.curves.sf_upper, mode: "lines", line: { width: 0 }, hoverinfo: "skip", showlegend: false },
              { x: d.curves.x, y: d.curves.sf_lower, mode: "lines", line: { width: 0 }, fill: "tonexty", fillcolor: BAND_FILL, name: "90% credible band", hoverinfo: "skip" },
              ...(d.curves.baseline_sf ? [{ x: d.curves.x, y: d.curves.baseline_sf, mode: "lines", line: { color: MUTED, width: 1.5, dash: "dash" }, name: "Baseline" }] : []),
              { x: d.curves.x, y: d.curves.sf, mode: "lines", line: { color: ACCENT, width: 2 }, name: "Updated" },
            ]} layout={{ height: 230, xaxis: { title: { text: `Age${u ? ` (${u})` : ""}` } }, yaxis: { title: { text: "Reliability" }, range: [0, 1.02] } }}
                  download={`${position.name} — Bayesian update`} />
          )}
          <div className="maint-scroll">
            <table className="ml-params">
              <thead><tr><th>{d.can_save ? "" : "The baseline as given"}</th><th className="num">Before (baseline)</th><th className="num">After (updated)</th></tr></thead>
              <tbody>
                {d.posterior.map((p) => {
                  const before = d.prior.find((x) => x.name === p.name);
                  return <tr key={p.name}><td>{PARAM_WORDS[p.name] || p.label}</td><td className="num">{before ? <RangeCell p={before} /> : "—"}</td><td className="num"><RangeCell p={p} /></td></tr>;
                })}
                {d.b10 && <tr><td>B10 life{u ? ` (${u})` : ""}</td><td className="num">{(() => { const b = d.prior.find((x) => x.name === "B10"); return b ? <RangeCell p={b} /> : "—"; })()}</td><td className="num"><RangeCell p={{ median: d.b10.point, lower: d.b10.lower, upper: d.b10.upper }} /></td></tr>}
                {d.mean && <tr><td>Mean life{u ? ` (${u})` : ""}</td><td className="num">{(() => { const b = d.prior.find((x) => x.name === "mean"); return b ? <RangeCell p={b} /> : "—"; })()}</td><td className="num"><RangeCell p={{ median: d.mean.point, lower: d.mean.lower, upper: d.mean.upper }} /></td></tr>}
              </tbody>
            </table>
          </div>
          <p className="rim-tquiet">Ranges are 90% credible intervals: a 90% chance the value lies between them, given the baseline and the data.</p>
          <Field label="Reliability at an age (optional)">
            <TextInput inputMode="decimal" value={state.age} onChange={(e) => set("age", e.target.value)} placeholder={u ? `An age in ${u}` : "An age"} />
          </Field>
          {d.at_age && (
            <p className="ml-lead">At {fmt(d.at_age.age)} {u}: {Math.round(d.at_age.reliability * 100)}% chance a new unit survives (90% chance between {Math.round(d.at_age.lower * 100)}% and {Math.round(d.at_age.upper * 100)}%).</p>
          )}
          <Field label={`${position.name}’s history`} as="fieldset" help="Untick any that don't belong (a failure caused by something else, a unit that was never really in service).">
            {d.rows.length === 0 ? <p className="rim-tquiet">Nothing has been fitted here yet.</p> : (
              <div className="ml-modes">
                {d.rows.map((r, i) => (
                  <label key={r.fitment_id || i} className="ml-mode">
                    <input type="checkbox" checked={!state.exclude.has(r.fitment_id)} disabled={!r.fitment_id || (r.c === 2 ? r.xr : r.x) <= 0}
                           onChange={() => toggle(r.fitment_id)} />
                    {rowWords(r, unit)}{r.item ? ` · ${r.item}` : ""}{r.failure_mode ? ` · ${r.failure_mode}` : ""}
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
