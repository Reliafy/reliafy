import { useEffect, useRef, useState } from "react";
import { adjustModel } from "../api.js";
import Field from "./ui/Field.jsx";
import { Select, TextInput } from "./ui/Controls.jsx";
import SegmentedControl from "./ui/SegmentedControl.jsx";
import { saveErrorText } from "../confirm.js";
import { LIFE_SCALES, adjustRequest, boundsWords, compareRows, lifeScaleExact, ratioWords } from "../modelAdjust.js";
import "./AdjustModelPanel.css";

// "Adjust for conditions…": a life model for harsher or milder conditions, as a new saved model with a
// known hazard ratio (SurPyval's hr), the original left as it is. The work in a pane, never a modal:
// the Explorer's table pane (wrapped in TablePane) or the model page's body. As the ratio is typed it
// shows B10 and mean life before and after, their 90% one-sided lower bounds (SurPyval's, hr held
// fixed; it gives none on the mean with hr, which is said) and what it assumes (the same shape).
//
//   model      {id, name, results}   the model to adjust
//   onSaved(doc, text)   the new model saved          onCancel   leave it, nothing saved
//   onDirty(bool), onSaving(bool)   for the pane's "leave it?" (optional)
//   saveLabel  the button's words      children  more controls above the buttons (where it's used)
//   extraSave  (doc) => Promise<string|void>: more to do once saved (link it at a position)
export default function AdjustModelPanel({ model, onSaved, onCancel, onDirty, onSaving, saveLabel = "Save the adjusted model",
  extraSave = null, children = null }) {
  const exact = lifeScaleExact(model?.results);
  const [mode, setMode] = useState("hr");
  const [hr, setHr] = useState("1.5");
  const [scale, setScale] = useState("0.667");
  const [name, setName] = useState("");
  const [preview, setPreview] = useState(null);
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);
  const [failed, setFailed] = useState(null);
  const ask = adjustRequest(mode, mode === "life" ? scale : hr);
  const asked = ask.error ? null : JSON.stringify(ask);
  const seq = useRef(0);

  useEffect(() => {
    if (!asked || !model?.id) { setPreview(null); return undefined; }
    const n = ++seq.current;
    const t = setTimeout(() => {
      adjustModel(model.id, JSON.parse(asked)).then((p) => {
        if (n !== seq.current) return;
        setPreview(p);
        setError(null);
      }, (e) => n === seq.current && (setPreview(null), setError(e.message)));
    }, 250);
    return () => clearTimeout(t);
  }, [asked, model?.id]);

  const touch = () => onDirty?.(true);
  const rows = compareRows(preview);
  const save = async () => {
    if (!asked) return;
    setSaving(true);
    onSaving?.(true);
    setFailed(null);
    try {
      const doc = await adjustModel(model.id, { ...JSON.parse(asked), name: name.trim() || null, save: true });
      const more = extraSave ? await extraSave(doc) : null;
      onSaving?.(false);
      onDirty?.(false);
      onSaved(doc, more || `Saved ${doc.name}. ${model.name} is unchanged.`);
    } catch (e) {
      setSaving(false);
      onSaving?.(false);
      setFailed(saveErrorText(e, { offline: navigator.onLine === false }));
    }
  };

  return (
    <div className="adj">
      <p className="rw-fhelp">
        A copy of {model?.name || "this model"} for conditions that are harsher or milder than the ones it came from.
        It is saved as a new model; {model?.name || "the original"} stays as it is.
      </p>
      {exact ? (
        <SegmentedControl label="Adjust by" value={mode} onChange={(v) => { setMode(v); touch(); }}
                          options={[{ value: "hr", label: "By hazard ratio" }, { value: "life", label: "By how long it lasts" }]} />
      ) : (
        <p className="adj-quiet">
          Give a hazard ratio. “Lasts k times as long” is exact only for a Weibull or an exponential with no offset,
          limited failure population or zero inflation, so it isn’t offered for this model.
        </p>
      )}
      {mode === "hr" || !exact ? (
        <Field label="Hazard ratio" error={ask.error && hr !== "" ? ask.error : null}
               help="1.5 is 1.5 times the hazard at every age (harsher); 0.8 is milder.">
          <TextInput inputMode="decimal" value={hr} onChange={(e) => { setHr(e.target.value); touch(); }} />
        </Field>
      ) : (
        <Field label="Here it lasts" help={preview ? `That is a hazard ratio of ${Number(preview.hazard_ratio.toPrecision(4))}.` : undefined}>
          <Select value={scale} onChange={(e) => { setScale(e.target.value); touch(); }}>
            {LIFE_SCALES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
          </Select>
        </Field>
      )}
      {error && <p className="field-error" role="alert">{error}</p>}
      {preview && (
        <div className="adj-result" role="status">
          <p className="adj-answer">{ratioWords(preview.hazard_ratio)}</p>
          <div className="maint-scroll">
            <table className="adj-table">
              <thead>
                <tr><th scope="col" /><th scope="col">Now</th><th scope="col">Adjusted</th><th scope="col">Change</th></tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id}><th scope="row">{r.label}</th><td>{r.before}</td><td>{r.after}</td><td>{r.change}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="adj-quiet">{preview.assumes}</p>
          {boundsWords(preview).map((w) => <p key={w} className="adj-quiet">{w}</p>)}
        </div>
      )}
      <Field label="Name" optional help="Left blank, it's named after the original and the ratio.">
        <TextInput value={name} placeholder={preview?.default_name || ""} onChange={(e) => { setName(e.target.value); touch(); }} />
      </Field>
      {children}
      {failed && <p className="field-error" role="alert">{failed}</p>}
      <div className="adj-foot">
        <button type="button" className="secondary" onClick={onCancel} disabled={saving}>Cancel</button>
        <button type="button" onClick={save} disabled={saving || !asked || !preview} aria-busy={saving || undefined}>
          {saving ? "Saving…" : saveLabel}
        </button>
      </div>
    </div>
  );
}
