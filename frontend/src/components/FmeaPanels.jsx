import { useEffect, useRef, useState } from "react";
import Chip from "./ui/Chip.jsx";
import ChoiceChips from "./ui/ChoiceChips.jsx";
import Field from "./ui/Field.jsx";
import Section from "./ui/Section.jsx";
import { CloseIcon } from "./icons.jsx";
import { PanelField } from "./PanelField.jsx";
import { Field as FormField, FormModal } from "./MaintenanceParts.jsx";
import {
  AP_LABEL, AP_TONE, CLASS_LABEL, SCORES, SCORE_ENDS, SOURCE_LABEL, STATUS_LABEL, apOf, bandOf, bandWords, cmOf, cmWords, fmt3, rpnOf,
} from "../fmea.js";
import "./FmeaPanels.css";

// The FME(C)A's parts of the Explorer's details panel (RcmWorksheet.jsx
// Details draws them on a failure mode; AssetExplorer draws the position's):
// the FME(C)A group (cause, the three effects, detection method, S, O and D
// with the RPN and action priority previewed as they're typed, the
// recommended action with its owner, due date and status); the Criticality
// group (λ, its unit and source, α, β, t, Cm and the severity class); a
// position's panel with its criticality matrix, Cr and the modes ranked by
// Cm; and the dialog that puts a function's direct failure modes under one of
// its functional failures. Every field is kept as you go (PanelField).

const SCORE_LABEL = { severity: "Severity (S)", occurrence: "Occurrence (O)", detection: "Detection (D)" };
const SCORE_RANGE = { min: 1, max: 10, integer: true };

// A scale's ten hints from the server (opts.scales), one per line, as the
// field's tooltip; the ends of the scale under it.
const hintsOf = (opts, scale) => {
  const lines = opts?.scales?.[scale];
  return Array.isArray(lines) && lines.length ? lines.map((t, i) => `${i + 1}: ${t}`).join("\n") : null;
};

//   r          the failure mode's row; opts the action priority table (fmea.js readFmeaOptions)
//   saved      {col: n} the "✓ Saved" counters (the panel's); onCommit(col, raw) keeps a field
//   consequence the Consequence field (on the FME(C)A tab the end effect's partner), or null
export function FmeaGroup({ r, opts, readOnly, saved = {}, onCommit, consequence = null }) {
  const m = r.ref;
  // The scores as typed, for the live RPN and action priority; back to the
  // saved ones when the row changes or a save comes back.
  const fromRef = () => Object.fromEntries(SCORES.map((k) => [k, m[k] ?? ""]));
  const [drafts, setDrafts] = useState(fromRef);
  useEffect(() => setDrafts(fromRef()), [r.key, m.severity, m.occurrence, m.detection]); // eslint-disable-line react-hooks/exhaustive-deps
  const rpn = rpnOf(drafts.severity, drafts.occurrence, drafts.detection);
  const typed = SCORES.some((k) => String(drafts[k]) !== String(m[k] ?? ""));
  // The table from the server when it's here; else the server's own answer
  // for the saved scores (none while a different score is being typed).
  const ap = opts?.table ? apOf(opts, drafts.severity, drafts.occurrence, drafts.detection) : typed ? null : m.ap || null;
  const bands = rpn != null && opts?.bands
    ? SCORES.map((k) => bandWords(k, bandOf(opts, k, drafts[k]))).filter(Boolean).join(", ") : "";
  const text = (label, col, { area = false, help = null } = {}) => (
    <PanelField key={`${r.key}:${col}`} label={label} value={m[col] ?? ""} area={area} help={help} readOnly={readOnly} optional
                saved={saved[col]} onCommit={(raw) => onCommit(col, raw)} />
  );
  return (
    <Section title="FME(C)A" label="FME(C)A" className="rw-fmea">
      <div className="rw-fields">
        {text("Cause", "cause", { area: true })}
        {text("Local effect", "effect_local", { area: true })}
        {text("Next higher effect", "effect_next", { area: true })}
        {text("End effect", "effects", { area: true, help: "The RCM tab's Failure effects: the same field" })}
        {consequence}
        {text("Detection method", "detection_method", { area: true, help: "The current controls: how the failure or its cause would be noticed first" })}
        <div className="fm-scores">
          {SCORES.map((k) => (
            <PanelField key={`${r.key}:${k}`} label={SCORE_LABEL[k]} type="number" range={SCORE_RANGE} value={m[k] ?? ""} readOnly={readOnly}
                        help={SCORE_ENDS[k]} title={hintsOf(opts, k)} saved={saved[k]}
                        onDraft={(v) => setDrafts((d) => ({ ...d, [k]: v }))} onCommit={(raw) => onCommit(k, raw)} />
          ))}
        </div>
        {/* The two answers from the three scores, as typed: said in words as well as the chip's tone. */}
        <p className="fm-preview" role="status" aria-live="polite">
          <span>RPN <b>{rpn ?? "—"}</b></span>
          <span>Action priority {ap ? <Chip tone={AP_TONE[ap]} className="rw-ap">{AP_LABEL[ap]}</Chip> : <b>—</b>}</span>
          {bands && <span className="rw-fhelp">({bands})</span>}
          {rpn == null && <span className="rw-fhelp">Score all three to get them.</span>}
        </p>
        {text("Recommended action", "action", { area: true })}
        {text("Owner", "action_owner")}
        <PanelField key={`${r.key}:action_due`} label="Due" type="date" value={m.action_due ?? ""} readOnly={readOnly} optional
                    saved={saved.action_due} onCommit={(raw) => onCommit("action_due", raw)} />
        <Field label="Status" saved={saved.action_status} optional>
          {readOnly ? <span className="rw-fval">{STATUS_LABEL[m.action_status] || "—"}</span> : (
            <ChoiceChips label="Status" clearable value={m.action_status || ""}
                         options={Object.entries(STATUS_LABEL).map(([value, label]) => ({ value, label }))}
                         onChange={(v) => onCommit("action_status", v)} />
          )}
        </Field>
      </div>
    </Section>
  );
}

export function CriticalityGroup({ r, readOnly, saved = {}, onCommit }) {
  const m = r.ref;
  const unit = m.time_unit || "hours";
  const cm = m.cm ?? cmOf(m);
  const num = (label, col, range, { help = null, suffix = null } = {}) => (
    <PanelField key={`${r.key}:${col}`} label={label} type="number" range={range} value={m[col] ?? ""} readOnly={readOnly} optional
                help={help} suffix={suffix} saved={saved[col]} onCommit={(raw) => onCommit(col, raw)} />
  );
  return (
    <Section title="Criticality" label="Criticality" className="rw-crit"
             tip="Mode criticality Cm = β × α × λ × t: the loss probability, the mode's share of the item's failures, the item's failure rate and the operating time. Item criticality Cr is the sum of Cm over the position's failure modes.">
      <div className="rw-fields">
        {num("Failure rate (λ)", "failure_rate", { min: 0 }, { suffix: `/${unit}`, help: "The item's failure rate, failures per unit of time" })}
        <PanelField key={`${r.key}:time_unit`} label="Time unit" value={m.time_unit ?? ""} placeholder="hours" readOnly={readOnly} optional
                    help="The unit the failure rate and operating time are in" saved={saved.time_unit} onCommit={(raw) => onCommit("time_unit", raw)} />
        <Field label="Rate source" saved={saved.rate_source} optional>
          {readOnly ? <span className="rw-fval">{SOURCE_LABEL[m.rate_source] || "—"}</span> : (
            <ChoiceChips label="Rate source" clearable value={m.rate_source || ""}
                         options={Object.entries(SOURCE_LABEL).map(([value, label]) => ({ value, label }))}
                         onChange={(v) => onCommit("rate_source", v)} />
          )}
        </Field>
        {num("Mode ratio (α)", "mode_ratio", { min: 0, max: 1 }, { help: "The share of the item's failures that are this mode, 0 to 1" })}
        {num("Loss probability (β)", "loss_probability", { min: 0, max: 1 }, { help: "The chance this mode's effect is the loss named by the severity class, 0 to 1" })}
        {num("Operating time (t)", "operating_time", { min: 0, exclusiveMin: true }, { suffix: unit, help: "The time the criticality is figured over" })}
        <div className="field">
          <span className="field-label">Mode criticality (Cm)</span>
          <span className="rw-fval"><b>{cm != null ? fmt3(cm) : "—"}</b></span>
          <p className="rw-fhelp">{cm != null ? cmWords(m) : "Needs the failure rate, mode ratio, loss probability and operating time."}</p>
        </div>
        <Field label="Severity class" saved={saved.severity_class} optional>
          {readOnly ? <span className="rw-fval">{CLASS_LABEL[m.severity_class] || "—"}</span> : (
            <ChoiceChips label="Severity class" clearable value={m.severity_class || ""}
                         options={Object.entries(CLASS_LABEL).map(([value, label]) => ({ value, label }))}
                         onChange={(v) => onCommit("severity_class", v)} />
          )}
        </Field>
      </div>
    </Section>
  );
}

// A position picked on the FME(C)A tab: its criticality matrix (severity
// across, occurrence down; each cell the count of failure modes there, toned
// by the worst action priority among them, which the tooltip says too), the
// counts, the item criticality and the modes ranked by Cm.
//   summary   explorerFmea.js positionSummary
export function FmeaPositionPanel({ row, summary, phone, headingRef, onClose, onSelect }) {
  const name = row.ref.name || "(no name)";
  const { matrix, ranked, counts, own, cr, inside } = summary;
  const where = inside ? "here and in the positions inside" : "here";
  return (
    <aside className={"rw-panel fm-pos" + (phone ? " sheet" : "")} aria-label="Details"
           onKeyDown={(e) => { if (e.key === "Escape" && !e.defaultPrevented) { e.stopPropagation(); onClose(); } }}>
      <div className="rw-panel-top">
        <div className="rw-panel-head">
          <div className="rw-panel-kind">Position · FME(C)A</div>
          <div className="rw-panel-btns">
            <button type="button" className="ghost sm rw-x" onClick={onClose} aria-label="Close the details" title="Close (Esc)"><CloseIcon /></button>
          </div>
        </div>
        <h2 className="rw-panel-title" tabIndex={-1} ref={headingRef}>{name}</h2>
        <div className="rw-chips-row">
          <Chip tone={counts.modes && counts.scored === counts.modes ? "success" : counts.modes ? "warning" : "neutral"}>
            {counts.modes ? `${counts.scored} of ${counts.modes} scored` : "No failure modes yet"}
          </Chip>
          {counts.high > 0 && <Chip tone="danger">{counts.high} high</Chip>}
          {counts.medium > 0 && <Chip tone="warning">{counts.medium} medium</Chip>}
          {counts.low > 0 && <Chip tone="neutral">{counts.low} low</Chip>}
        </div>
      </div>
      <div className="rw-pbody">
        <Section title="Criticality matrix" label="Criticality matrix"
                 tip={`Severity across, low to high (the severity classes when every scored mode has one); occurrence down, high at the top. Each cell counts the failure modes ${where}, toned by the worst action priority among them.`}>
          {matrix.scored ? (
            <div className="maint-scroll">
              <table className="fm-matrix" aria-label="Criticality matrix: occurrence down, severity across">
                <thead>
                  <tr>
                    <th scope="col" className="fm-corner"><span className="fm-axis-o">O ↓</span><span className="fm-axis-s">S →</span></th>
                    {matrix.cols.map((c) => <th key={c.id} scope="col" title={c.title}>{c.label}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {matrix.rows.map((o, i) => (
                    <tr key={o.id}>
                      <th scope="row" title={o.title}>{o.label}</th>
                      {matrix.cols.map((c, j) => {
                        const cell = matrix.cells[i][j];
                        const words = cell.n ? `${cell.n} failure mode${cell.n === 1 ? "" : "s"}: ${c.title.toLowerCase()}, ${o.title.toLowerCase()}${cell.worst ? `; worst action priority ${AP_LABEL[cell.worst]}` : ""}` : "";
                        return (
                          <td key={c.id} className={"fm-cell" + (cell.worst ? ` ap-${cell.worst}` : "") + (cell.n ? " has" : "")} title={words || undefined}>
                            {cell.n ? <span>{cell.n}<span className="sr-only">, {words}</span></span> : ""}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="rw-fhelp">No failure mode {where} has both a severity and an occurrence score yet.</p>
          )}
          <p className="fm-legend rw-fhelp" aria-hidden="true">
            <span className="fm-swatch ap-H" /> High <span className="fm-swatch ap-M" /> Medium <span className="fm-swatch ap-L" /> Low
            {matrix.byClass ? " · columns are severity classes" : ""}
          </p>
        </Section>
        <Section title="Item criticality (Cr)" label="Item criticality">
          <dl className="rw-card rw-dcard">
            <div><dt>This position</dt><dd><b>{own.cr != null ? fmt3(own.cr) : "—"}</b>{own.modes ? <span className="rw-fhelp"> · {own.scored} of {own.modes} scored</span> : null}</dd></div>
            {inside && <div><dt>With what's inside</dt><dd><b>{cr ? fmt3(cr.cr) : "—"}</b></dd></div>}
            {cr && Object.keys(cr.byClass).length > 0 && (
              <div><dt>By class</dt><dd>{["I", "II", "III", "IV"].filter((c) => cr.byClass[c] != null).map((c) => `${c} ${fmt3(cr.byClass[c])}`).join(" · ")}</dd></div>
            )}
          </dl>
          {ranked.length ? (
            <div className="maint-scroll">
              <table className="fm-rank" aria-label="Failure modes by criticality, highest first">
                <thead><tr><th scope="col">Failure mode</th><th scope="col">Class</th><th scope="col">λ</th><th scope="col">α</th><th scope="col">β</th><th scope="col">t</th><th scope="col">Cm</th></tr></thead>
                <tbody>
                  {ranked.map((m) => (
                    <tr key={m.id}>
                      <td>{onSelect ? <button type="button" className="link" onClick={() => onSelect(m.id)} title={cmWords(m)}>{m.text || "(no description)"}</button> : m.text}</td>
                      <td>{m.severity_class || ""}</td>
                      <td className="num">{fmt3(m.failure_rate)}</td>
                      <td className="num">{fmt3(m.mode_ratio)}</td>
                      <td className="num">{fmt3(m.loss_probability)}</td>
                      <td className="num">{fmt3(m.operating_time)}</td>
                      <td className="num"><b>{fmt3(m.cm)}</b></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <p className="rw-fhelp">No failure mode {where} has the four criticality figures (λ, α, β, t) yet.</p>}
        </Section>
      </div>
    </aside>
  );
}

// "Assign to a functional failure…" on a "No functional failure yet" row:
// every failure mode in it goes under the functional failure chosen (the
// same records: their scores and effects stay). `failures`: the function's
// functional failures [{id, text}]; none: how to add one.
export function AssignFailureModal({ row, failures, onClose, onAssign }) {
  const [to, setTo] = useState(failures[0]?.id || "");
  const n = (row.ref.mode_ids || []).length;
  const first = useRef(null);
  useEffect(() => { first.current?.focus(); }, []);
  return (
    <FormModal title="Assign to a functional failure" submitLabel="Assign" pendingLabel="Assigning…" onClose={onClose}
               canSubmit={!!to}
               onSubmit={async () => { await onAssign(to); }}>
      <p className="lib-date">
        {n === 1 ? "The failure mode" : `The ${n} failure modes`} under “{row.ref.function_text || "this function"}” with no functional failure yet
        {n === 1 ? " goes" : " go"} under the one you choose. Scores, effects and decisions stay with {n === 1 ? "it" : "them"}.
      </p>
      {failures.length ? (
        <FormField label="Functional failure">
          <select ref={first} value={to} onChange={(e) => setTo(e.target.value)}>
            {failures.map((f) => <option key={f.id} value={f.id}>{f.text}</option>)}
          </select>
        </FormField>
      ) : (
        <p className="lib-date">This function has no functional failure yet. Add one first (the row's menu: Add a functional failure…).</p>
      )}
    </FormModal>
  );
}
