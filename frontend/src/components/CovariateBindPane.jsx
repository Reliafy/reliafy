import { useEffect, useMemo, useState } from "react";
import { getBindingInputs, linkPositionModel } from "../api.js";
import TablePane from "./TablePane.jsx";
import CovariateInputs from "./CovariateInputs.jsx";
import { saveErrorText } from "../confirm.js";
import { LIBRARY_SOURCES, bindSummary, bindingToSave, initialFix, initialValues } from "../covariate.js";
import "./CovariateCalculator.css";

// A covariate model at a position, in the Explorer's table area (Derryn, 9 Nov 2026: "the user can
// choose to fix some, all, or none of the covariates. These could be design parameters or they
// could be use or environmental. If they are use or env one can set them in the RBD"; and "make it
// the same for ALT"): an NSWC-11 covariate model, an accelerated life model or a proportional-
// hazards model, or any data library record or component (Derryn, 9 Nov 2026: every input a
// record needs is a covariate of the record: a pipe's length, the clock, the demands a year, a
// handbook part's environment and quality, a component's demands and hours). Each covariate, grouped Design / Use / Environment, has "Fix at this position" and
// a value. Design inputs start ticked for an NSWC-11 model; an ALT's stresses and a PH model's
// covariates start open, and the user says what each one is. Saved, the model is linked here with
// the fixed values; the open ones are set on each RBD block (or the diagram's Use and Environment
// values). Every one fixed: a constant-rate (or constant-stress) model at this position.
//
//   position {id, name}     binding {source, ref}     name  the model's name     link  the row it replaces
//   onDone(link, text)      onDirty, onSaving, phone, headingRef, onClose: TablePane's

export default function CovariateBindPane({ position, binding, name = "", link = null, phone = false, headingRef = null, onClose, onDone, onDirty, onSaving }) {
  const [inputs, setInputs] = useState(null);
  const [error, setError] = useState(null);
  const [fix, setFix] = useState({});
  const [values, setValues] = useState({});
  const [roles, setRoles] = useState({});
  const [saving, setSaving] = useState(false);
  const [failed, setFailed] = useState(null);
  const was = link?.source?.binding || null;

  useEffect(() => {
    getBindingInputs({ ...binding, ...(was ? { fixed: was.fixed, roles: was.roles } : {}) }).then((d) => {
      setInputs(d.inputs);
      setFix(initialFix(binding.source, d.inputs, was));
      setValues(initialValues(d.inputs, was));
    }, (e) => setError(e.message));
  }, [binding.source, binding.ref]); // eslint-disable-line react-hooks/exhaustive-deps

  const shown = useMemo(() => (inputs || []).map((i) => ({ ...i, role: roles[i.key] || i.role })), [inputs, roles]);
  const touch = () => onDirty?.(true);
  const out = bindingToSave({ ...binding, inputs: shown, fix, values, roles });
  const save = async () => {
    setSaving(true);
    onSaving?.(true);
    try {
      const made = await linkPositionModel(position.id, { bind: out.binding, ...(link ? { replace_link_id: link.id } : {}) });
      onSaving?.(false);
      onDone(made, `Linked ${name || "the model"} to ${position.name} with ${Object.keys(out.binding.fixed).length} covariates fixed.`);
    } catch (e) {
      setSaving(false);
      onSaving?.(false);
      setFailed(saveErrorText(e, { offline: navigator.onLine === false }));
    }
  };
  const words = { nswc: "an NSWC-11 covariate model", library: "a data library record", component: "a data library component (its failure modes together)",
    alt: "an accelerated life model", ph: "a proportional-hazards model" }[binding.source];
  return (
    <TablePane title="Fix covariates" subject={position.name} phone={phone} busy={saving} headingRef={headingRef} onClose={onClose}
               className="bind-pane">
      <div className="bind">
        <p className="rw-fhelp">
          {name || "The model"}, {words}, at {position.name}. Tick what’s fixed here (usually the design). What isn’t
          fixed is set where the model is used: on each block of an RBD built from the tree, or once for the whole
          diagram as its Use and Environment values.
        </p>
        {error && <p className="field-error" role="alert">{error}</p>}
        {!inputs && !error && <p className="rim-tquiet">Reading its covariates…</p>}
        {inputs && (
          <CovariateInputs inputs={shown} values={values} idPrefix="bind"
                           onChange={(v) => { setValues(v); touch(); }}
                           fix={{ fixed: fix, onFix: (k, on) => { setFix((f) => ({ ...f, [k]: on })); touch(); } }}
                           onRole={LIBRARY_SOURCES.includes(binding.source) ? null : (k, r) => { setRoles((x) => ({ ...x, [k]: r })); touch(); }} />
        )}
        {inputs && inputs.length === 0 && <p className="rim-tquiet">It needs no covariates: it’s saved as a constant-rate model here.</p>}
        {inputs && inputs.length > 0 && <p className="bind-sum" role="status">{bindSummary(binding.source, shown, fix, values)}</p>}
        {out.missing.length > 0 && <p className="field-error">Give a value for {out.missing.join(", ")}, or untick it.</p>}
        {failed && <p className="field-error" role="alert">{failed}</p>}
        <div className="bind-foot">
          <button type="button" className="secondary" onClick={onClose} disabled={saving}>Cancel</button>
          <button type="button" onClick={save} disabled={saving || !inputs || out.missing.length > 0} aria-busy={saving || undefined}>
            {saving ? "Saving…" : "Save at this position"}
          </button>
        </div>
      </div>
    </TablePane>
  );
}
