import Field from "./ui/Field.jsx";
import { Select, TextInput } from "./ui/Controls.jsx";
import { ROLES, defaultText, groupInputs, limitProblem, limitText, neededInputs } from "../covariate.js";
import "./CovariateCalculator.css";

// A covariate model's inputs, grouped Design / Use / Environment: the one input component for
// every library record's covariates (a pipe's length, the clock and running hours, the demands a
// year, a handbook part's environment and quality, NSWC-11's conditions, a component's demands and
// hours), accelerated life and proportional-hazards models, wherever they're set (a record's or
// component's Try it, Use as a model…, a prior in the Fit dialog, a prediction line's Conditions…,
// fixing them at a position, an RBD block). An input another one's value makes unnecessary
// (``needed_if``: running hours when the clock is the record's own; ``needed_when``: a winding's
// temperature rise while its insulation class isn't known) isn't shown.
// Each shows its unit, its default (and where that comes from) and its limits; a value past a
// limit says which, and the page, as it's typed. Options add what a place needs:
//
//   inputs, values {key: text}, onChange(values), idPrefix
//   fix      {fixed: {key: true}, onFix(key, on)}: a "Fix at this position" tick on each
//   onRole   (key, role): what each one is, for a model that doesn't say (ALT, PH)
//   sources  {key: {from, words}}: where a value came from when it isn't typed here (an RBD block)
//   conditions [{name, role, unit, value}] with map {key: name} and onMap(key, name): take the
//            diagram's value of another name
//   readOnly true: shown, not changed
//   extra    (input) => what goes under an input's field (a mission phase: the blocks it feeds and
//            their own values)
//   bare     the inputs alone, not grouped under Design / Use / Environment (one block's override)

export default function CovariateInputs({
  inputs = [], values = {}, onChange, idPrefix = "cov", fix = null, onRole = null, sources = null, conditions = null,
  map = {}, onMap = null, readOnly = false, extra = null, bare = false,
}) {
  const set = (key, v) => onChange?.({ ...values, [key]: v });
  const shown = neededInputs(inputs, values);
  const groups = bare ? [{ role: "all", label: "", what: "", inputs: shown }] : groupInputs(shown);
  return (
    <div className={"cov-inputs" + (bare ? " cov-bare" : "")}>
      {groups.map((g) => (
        <fieldset key={g.role} className="cov-group">
          {!bare && <legend className="cov-legend">{g.label}</legend>}
          {g.what && <p className="cov-what">{g.what}</p>}
          <div className="cov-grid">
            {g.inputs.map((i) => {
              const id = `${idPrefix}-${i.key.replace(/[^A-Za-z0-9_-]/g, "-")}`;
              const raw = values[i.key] ?? "";
              const fixedHere = fix ? !!fix.fixed?.[i.key] : true;
              const prob = limitProblem(i, raw);
              const from = sources?.[i.key];
              const help = [
                prob?.severity === "warn" ? prob.text : null,
                String(raw).trim() === "" && from ? `Using ${from.value != null ? `${from.value} from ` : ""}${from.words}` : null,
                i.default == null ? (String(raw).trim() === "" && !from ? "Needed: no default" : "") : defaultText(i),
                limitText(i),
              ].filter(Boolean).join(" · ");
              const label = `${i.label}${i.symbol ? ` (${i.symbol})` : ""}${i.group ? ` · ${i.group}` : ""}`;
              const off = readOnly || (fix && !fixedHere);
              return (
                <div key={i.key} className={"cov-cell" + (fix && !fixedHere ? " is-open" : "")}>
                  <Field id={id} label={label} help={help} error={prob?.severity === "refuse" && !off ? prob.text : null}
                         className={"cov-field" + (prob?.severity === "warn" ? " cov-warn" : "")}>
                    {i.kind === "choice" ? (
                      <Select value={raw === "" ? (i.default ?? "") : raw} disabled={off} onChange={(e) => set(i.key, e.target.value)}>
                        {i.default == null && <option value="">Choose…</option>}
                        {(i.choices || []).map((c) => <option key={c.code} value={c.code}>{c.label}</option>)}
                      </Select>
                    ) : (
                      <span className="cov-num">
                        <TextInput inputMode="decimal" value={raw} disabled={off}
                                   placeholder={from?.value != null ? String(from.value) : i.default != null ? String(i.default) : "Needed"}
                                   onChange={(e) => set(i.key, e.target.value)} />
                        {i.unit ? <span className="cov-unit">{i.unit}</span> : null}
                      </span>
                    )}
                  </Field>
                  {(fix || onRole || (onMap && conditions?.length)) && (
                    <div className="cov-extra">
                      {fix && (
                        <label className="cov-fix">
                          <input type="checkbox" checked={fixedHere} disabled={readOnly}
                                 aria-label={`Fix ${i.label} at this position`}
                                 onChange={(e) => fix.onFix(i.key, e.target.checked)} />
                          Fix at this position
                        </label>
                      )}
                      {onRole && (
                        <select className="cov-role" aria-label={`What ${i.label} is`} value={i.role} disabled={readOnly}
                                onChange={(e) => onRole(i.key, e.target.value)}>
                          {ROLES.map((r) => <option key={r.role} value={r.role}>{r.label}</option>)}
                        </select>
                      )}
                      {onMap && conditions?.length > 0 && (
                        <select className="cov-map" aria-label={`Diagram value for ${i.label}`} value={map[i.key] || ""}
                                disabled={readOnly} onChange={(e) => onMap(i.key, e.target.value)}>
                          <option value="">Diagram value: matched by name</option>
                          {conditions.map((c) => <option key={c.name} value={c.name}>Diagram: {c.name}{c.unit ? ` (${c.unit})` : ""}</option>)}
                        </select>
                      )}
                    </div>
                  )}
                  {extra?.(i)}
                </div>
              );
            })}
          </div>
        </fieldset>
      ))}
    </div>
  );
}
