import { useEffect, useRef, useState } from "react";
import { calculateMission, getMission, updateMission } from "../api.js";
import Chip from "./ui/Chip.jsx";
import Field from "./ui/Field.jsx";
import { Select, TextInput } from "./ui/Controls.jsx";
import QuantityInput from "./ui/QuantityInput.jsx";
import { CloseIcon, ExpandIcon, ShrinkIcon } from "./icons.jsx";
import { saveErrorText } from "../confirm.js";
import {
  BLOCK_STATES, MAX_PHASES, changedPhases, startText, completesText, covStatus, covValueText, isCovRow, isPhaseRow, isRuleRow, lengthText,
  pct, phaseKey, phaseOfText, phaseResult, phaseSettingsText, placeholderTitle, placeholderTone, ruleKey, ruleState, ruleText, covKey,
  withBlockState, withValue, isSchedule,
} from "../explorerMissions.js";
import PhaseCovValue from "./PhaseCovValue.jsx";
import "./MissionSide.css";

// The details beside the Missions tab's tree for the row picked (Derryn, 15 Nov 2026: "I want the
// mission, and the phases to have their own details panel"), the Modelling tab's pattern: a mission
// (its RBD, phases in order, the chance of completing it, add a phase, rename, open in the
// builder), a phase (name, duration, order, its covariates and node status rules, the chance of
// getting through it), a phase's covariate (its value in the phase, set here) and a node status
// rule (a block's state in the phase). Every change is saved through the mission's own update
// route into the RBD's phases, the same data the RBD builder's Phased mission… edits, then the
// mission is worked out again so the tree's figures follow.
//
//   r                    the row picked (mission, phase, mcov, mrule)
//   onAction(r, id)      the row menu's actions (delete, open in the editor, open the RBD)
//   onChanged(text)      a change was saved: the tree read again (text: what was done)
//   onSelect(key)        pick another row of the tree (a phase in the mission's list, a covariate)
//   addRule              open on the phase's Add node status rule form
//   viewOnly             why nothing can be changed here, or null

// Missions worked out once from here while their result was missing (so a panel opening again
// doesn't ask again).
const ASKED = new Set();

export default function MissionSide({ r, phone, expanded, onExpand, onCollapse, onClose, headingRef, onMenu, onAction, onChanged, onSelect,
  addRule = false, viewOnly = null }) {
  const { mission: m, rbd } = r.ref;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const live = useRef(true);
  useEffect(() => () => { live.current = false; }, []);

  // The row menu's own actions in the heading's "…" (as the Modelling tab's details do).
  useEffect(() => {
    onMenu?.(null);
    return () => onMenu?.(null);
  }, [r.key]); // eslint-disable-line react-hooks/exhaustive-deps

  // A mission with phases and no result yet: worked out once, so its figures show.
  useEffect(() => {
    const sig = `${rbd.id}:${m.id}:${JSON.stringify([m.phase_names, m.phase_durations, m.phase_settings, m.covariates])}`;
    if (m.result || !m.phases || ASKED.has(sig)) return;
    ASKED.add(sig);
    calculateMission(rbd.id, m.id).then(() => live.current && onChanged?.(null), () => {});
  }, [rbd.id, m.id, m.result, m.phases]); // eslint-disable-line react-hooks/exhaustive-deps

  // A change to the mission's phases (`change`: the editable phases in, out), saved and worked out.
  const savePhases = async (change, text, { name = null } = {}) => {
    setBusy(true);
    setError(null);
    try {
      const detail = await getMission(rbd.id, m.id);
      const { phases, errors } = changedPhases(detail, change);
      if (errors.length) throw new Error(errors[0]);
      await updateMission(rbd.id, m.id, { ...(name ? { name } : {}), phases, expected_updated_at: detail.rbd?.updated_at });
      await calculateMission(rbd.id, m.id).catch(() => null);
      if (live.current) onChanged?.(text);
      return true;
    } catch (e) {
      if (live.current) setError(e.status ? saveErrorText(e, { offline: navigator.onLine === false }) : e.message);
      return false;
    } finally {
      if (live.current) setBusy(false);
    }
  };
  const atPhase = (i, fn) => (rows) => rows.map((p, j) => (j === i ? { ...p, ...fn(p) } : p));

  const kind = isCovRow(r) ? `Covariate · ${cap(r.ref.cov.role || "use")}` : isRuleRow(r) ? "Node status rule"
    : isPhaseRow(r) ? phaseOfText(r.ref.phase) : "Mission";
  const where = isPhaseRow(r) ? `In ${m.name}` : isCovRow(r) || isRuleRow(r) ? `${r.ref.phase.name} · ${m.name}`
    : plainMission(m) ? (m.phases ? `${lengthText(m.duration, m.unit)} · ${startText(m).toLowerCase()}` : "No length yet")
      : m.phases ? `${m.phases} phase${m.phases === 1 ? "" : "s"} · ${lengthText(m.duration, m.unit)}` : "No phases yet";

  const props = { r, m, rbd, busy, viewOnly, savePhases, atPhase, onAction, onSelect };
  return (
    <aside className={"rw-panel mt-panel msd-panel" + (phone ? " sheet" : "") + (expanded ? " is-expanded" : "")} aria-label="Details"
           onKeyDown={(e) => {
             if (e.key !== "Escape" || e.defaultPrevented || e.target.closest("input, textarea, select, .sel-trigger, .sel-menu")) return;
             e.stopPropagation();
             if (expanded) onCollapse(); else onClose();
           }}>
      <div className="rw-panel-top">
        <div className="rw-panel-head">
          <div className="rw-panel-kind">{kind}</div>
          <div className="rw-panel-btns">
            {!phone && (expanded ? (
              <button type="button" className="ghost sm rw-x" onClick={onCollapse} title="Show the table again, with these details beside it (Esc)" aria-label="Back to table"><ShrinkIcon /></button>
            ) : (
              <button type="button" className="ghost sm rw-x" onClick={onExpand} title="Show these details across the table, the tree kept beside them" aria-label="Expand the details"><ExpandIcon /></button>
            ))}
            <button type="button" className="ghost sm rw-x" onClick={onClose} aria-label="Close the details" title="Close (Esc)"><CloseIcon /></button>
          </div>
        </div>
        <h2 className="rw-panel-title" tabIndex={-1} ref={headingRef}>{r.ref.name || "(no name)"}</h2>
        <p className="rw-sum msd-where">{where}</p>
      </div>
      <div className="rw-pbody msd-body" aria-busy={busy || undefined}>
        {viewOnly && <p className="rim-tquiet">{viewOnly}</p>}
        {error && <p className="field-error" role="alert">Not saved: {error}</p>}
        {isCovRow(r) ? <CovDetails {...props} />
          : isRuleRow(r) ? <RuleDetails {...props} />
            : isPhaseRow(r) ? <PhaseDetails {...props} addRule={addRule} />
              : <MissionDetails {...props} />}
      </div>
    </aside>
  );
}

// A plain life model's mission (no covariates): a length from a starting age, no phases to show.
const plainMission = (m) => !!m?.simple && (m.phases || 0) <= 1;

const cap = (t) => String(t || "").charAt(0).toUpperCase() + String(t || "").slice(1);

// ---- a mission ---------------------------------------------------------------------------------

function MissionDetails({ r, m, rbd, busy, viewOnly, savePhases, onAction, onSelect }) {
  const [name, setName] = useState(m.name);
  useEffect(() => setName(m.name), [m.name]);
  const res = m.result;
  const names = m.phase_names || [];
  const lengths = m.phase_durations || [];
  const trimmed = name.trim();
  const plain = plainMission(m);
  const lb = res?.lower_bound;
  return (
    <>
      <section aria-label="The answer" className="msd-answer">
        {!names.length ? <p className="rim-tquiet">{plain ? "No length yet: open it in the mission editor to give it one." : "No phases yet: add one to work the mission out."}</p>
          : !res ? <p className="rim-tquiet">Working the mission out…</p>
            : res.reliability == null ? (
              <p><Chip tone="warning">Needs values</Chip> {res.through ? `Worked out to the end of ${res.through.phase} (${pct(res.through.reliability)} still going).` : "A phase still needs covariate values."}</p>
            ) : (
              <p className="msd-big">
                <span className="msd-figure">{completesText(m)}</span> chance of completing the mission
                {placeholderTone(res) ? <> <Chip tone={placeholderTone(res)} title={placeholderTitle(res)}>Placeholders</Chip></> : null}
              </p>
            )}
        {res?.reliability != null && lb && <p>At least <b>{pct(lb.lower)}</b> ({Math.round(lb.confidence * 100)}% one-sided lower bound).</p>}
        {res?.reliability != null && <p className="rim-tquiet">{res.method === "simulated" ? "Simulated" : "Worked out exactly"} {plain ? `${startText(m).toLowerCase()}, ` : "from each block's model at its point values, "}over {lengthText(m.duration, m.unit)}.</p>}
      </section>

      {!plain && (
      <section aria-labelledby={`msd-ph-${r.key}`}>
        <h3 className="ml-h" id={`msd-ph-${r.key}`}>Phases, in order</h3>
        {names.length ? (
          <div className="maint-scroll">
            <table className="msd-table">
              <thead><tr><th scope="col">#</th><th scope="col">Phase</th><th scope="col" className="num">Length</th><th scope="col" className="num">Gets through</th></tr></thead>
              <tbody>
                {names.map((n, i) => {
                  const pr = phaseResult(res, i);
                  return (
                    <tr key={`${n}:${i}`}>
                      <td>{i + 1}</td>
                      <td><button type="button" className="link" onClick={() => onSelect?.(phaseKey(rbd.id, m.id, i))}>{n}</button></td>
                      <td className="num">{lengthText(lengths[i], m.unit)}</td>
                      <td className="num">{pr?.waiting ? <Chip tone="warning">Needs values</Chip> : pr?.completes != null ? pct(pr.completes) : "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
              <tfoot><tr><td /><th scope="row">In all</th><td className="num">{lengthText(m.duration, m.unit)}</td><td className="num">{res?.reliability != null ? pct(res.reliability) : "—"}</td></tr></tfoot>
            </table>
          </div>
        ) : <p className="rim-tquiet">None yet.</p>}
        <div className="msd-actions">
          <button type="button" className="secondary sm" disabled={!!viewOnly || busy || names.length >= MAX_PHASES}
                  title={names.length >= MAX_PHASES ? `A mission has at most ${MAX_PHASES} phases.` : undefined}
                  onClick={() => onAction(r, "mission-phase-add")}>Add a phase</button>
        </div>
      </section>
      )}

      <section aria-labelledby={`msd-rbd-${r.key}`}>
        <h3 className="ml-h" id={`msd-rbd-${r.key}`}>Its RBD</h3>
        <p className="msd-line">Flies <b>{rbd.name}</b>{rbd.unit ? `, in ${String(rbd.unit).toLowerCase()}` : ""}.{plain ? " Its length and the age it starts at are set in the mission editor." : " Covariates come from the life models in it; node status rules set a block's state in a phase."}</p>
        <div className="msd-actions">
          <button type="button" className="secondary sm" onClick={() => onAction(r, "mission-rbd")}>Open in the RBD builder</button>
          <button type="button" className="secondary sm" onClick={() => onAction(r, "mission-open")}>Open in the mission editor</button>
        </div>
      </section>

      <form className="msd-form" onSubmit={(e) => {
        e.preventDefault();
        if (trimmed && trimmed !== m.name) savePhases((rows) => rows, `Renamed the mission ${trimmed}.`, { name: trimmed });
      }}>
        <Field label="Name">
          <TextInput value={name} maxLength={80} disabled={!!viewOnly || busy} onChange={(e) => setName(e.target.value)} />
        </Field>
        <button type="submit" className="secondary sm" disabled={!!viewOnly || busy || !trimmed || trimmed === m.name}>Rename</button>
      </form>
      <div className="msd-actions msd-end">
        <button type="button" className="secondary danger sm" disabled={!!viewOnly || busy} onClick={() => onAction(r, "mission-delete")}>Delete the mission…</button>
      </div>
    </>
  );
}

// ---- a phase -----------------------------------------------------------------------------------

function PhaseDetails({ r, m, rbd, busy, viewOnly, savePhases, atPhase, onAction, onSelect, addRule }) {
  const { index, of } = r.ref.phase;
  const settings = r.ref.settings || { covariates: [], rules: [] };
  const pr = r.ref.result;
  const [name, setName] = useState(r.ref.phase.name);
  const [len, setLen] = useState(r.ref.phase.duration ?? "");
  const [adding, setAdding] = useState(addRule);
  useEffect(() => { setName(r.ref.phase.name); setLen(r.ref.phase.duration ?? ""); }, [r.key, r.ref.phase.name, r.ref.phase.duration]);
  useEffect(() => { if (addRule) setAdding(true); }, [addRule, r.key]);
  const unit = String(m.unit || "").toLowerCase();
  const n = Number(len);
  const lenOk = String(len).trim() !== "" && Number.isFinite(n) && n >= 0;
  const changed = name.trim() !== r.ref.phase.name || (lenOk && n !== Number(r.ref.phase.duration));
  const ruled = new Set((settings.rules || []).map((x) => x.block));
  const free = (m.blocks || []).filter((b) => !ruled.has(b.id));
  return (
    <>
      <section aria-label="The answer" className="msd-answer">
        {!pr ? <p className="rim-tquiet">Not worked out yet.</p>
          : pr.waiting ? <p><Chip tone="warning">Needs values</Chip> A covariate below needs a value before this phase can be worked out.</p>
            : (
              <p className="msd-big"><span className="msd-figure">{pr.completes == null ? "—" : pct(pr.completes)}</span> chance of getting through it, once started
                {pr.atEnd != null && <span className="rim-tquiet msd-sub"> · the mission is still going at its end with {pct(pr.atEnd)}</span>}</p>
            )}
        <p className="rim-tquiet">{phaseSettingsText(settings)}.</p>
      </section>

      <form className="msd-form" onSubmit={(e) => {
        e.preventDefault();
        if (!changed || !name.trim() || !lenOk) return;
        savePhases(atPhase(index, () => ({ name: name.trim(), duration: n })), `Saved ${name.trim()}.`);
      }}>
        <Field label="Name">
          <TextInput value={name} maxLength={80} disabled={!!viewOnly || busy} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label="Duration" error={lenOk ? null : "A duration of 0 or more."}>
          <QuantityInput label={`Duration${unit ? ` (${unit})` : ""}`} suffix={unit} min="0" value={len} disabled={!!viewOnly || busy} onChange={setLen} />
        </Field>
        <button type="submit" className="secondary sm" disabled={!!viewOnly || busy || !changed || !name.trim() || !lenOk}>Save</button>
      </form>

      <section aria-labelledby={`msd-cov-${r.key}`}>
        <h3 className="ml-h" id={`msd-cov-${r.key}`}>Covariates in this phase</h3>
        {(settings.covariates || []).length ? (
          <ul className="msd-list">
            {settings.covariates.map((c) => {
              const st = covStatus(c);
              return (
                <li key={c.name}>
                  <button type="button" className="link" onClick={() => onSelect?.(covKey(rbd.id, m.id, index, c.name))}>{c.name}</button>
                  <span className={st.flag ? "" : "msd-val"} title={st.title}>
                    {st.flag === "needs" ? <Chip tone="warning">Needs a value</Chip> : st.flag === "unset" ? <Chip tone="neutral">{st.text}</Chip> : st.text}
                  </span>
                </li>
              );
            })}
          </ul>
        ) : <p className="rim-tquiet">None: no life model in the mission&apos;s RBD takes covariates. A proportional-hazards, accelerated life or covariate model adds its own here.</p>}
      </section>

      <section aria-labelledby={`msd-rule-${r.key}`}>
        <h3 className="ml-h" id={`msd-rule-${r.key}`}>Node status rules</h3>
        {(settings.rules || []).length ? (
          <ul className="msd-list">
            {settings.rules.map((x) => (
              <li key={x.block}>
                <button type="button" className="link" onClick={() => onSelect?.(ruleKey(rbd.id, m.id, index, x.block))}>{x.label}</button>
                <span className="msd-val">{ruleText(x)}</span>
              </li>
            ))}
          </ul>
        ) : <p className="rim-tquiet">None: every block is working in this phase.</p>}
        {adding ? (
          <RuleForm blocks={free} busy={busy} onCancel={() => setAdding(false)}
                    onSave={async ({ block, state, dormancy, start }) => {
                      const label = free.find((b) => b.id === block)?.label || block;
                      const ok = await savePhases(atPhase(index, (p) => withBlockState(p, block, state, dormancy, start)),
                        `${label}: ${ruleText({ state, dormancy, start_probability: start })} in ${r.ref.phase.name}.`);
                      if (ok) setAdding(false);
                    }} />
        ) : (
          <div className="msd-actions">
            <button type="button" className="secondary sm" disabled={!!viewOnly || busy || !free.length}
                    title={!free.length ? "Every block has a rule in this phase already." : undefined}
                    onClick={() => setAdding(true)}>Add node status rule…</button>
          </div>
        )}
      </section>

      <div className="msd-actions msd-end">
        <button type="button" className="secondary sm" disabled={!!viewOnly || busy || index === 0} onClick={() => onAction(r, "mission-phase-earlier")}>Move earlier</button>
        <button type="button" className="secondary sm" disabled={!!viewOnly || busy || index >= of - 1} onClick={() => onAction(r, "mission-phase-later")}>Move later</button>
        <button type="button" className="secondary sm" onClick={() => onAction(r, "mission-phase-open")}>Open in the mission editor</button>
        <button type="button" className="secondary danger sm" disabled={!!viewOnly || busy} onClick={() => onAction(r, "mission-phase-delete")}>Delete the phase…</button>
      </div>
    </>
  );
}

// A node status rule's form: the block (new rules only), its state in the phase and, on standby, how
// fast it ages while idle (0% cold … 100% hot, RePyability's dormancy factor) and the chance it
// starts when called on (RePyability's start_probability, 100% unless set).
const RULE_STATES = BLOCK_STATES.filter((s) => s.id !== "working");
export function RuleForm({ blocks = null, initial = null, busy = false, onSave, onCancel, onRemove = null }) {
  const [block, setBlock] = useState(initial?.block || blocks?.[0]?.id || "");
  const [state, setState] = useState(ruleState(initial?.state) || "standby");
  const [dorm, setDorm] = useState(initial?.dormancy ? String(Number(initial.dormancy) * 100) : "0");
  const [starts, setStarts] = useState(initial?.start_probability != null ? String(Number(initial.start_probability) * 100) : "100");
  const d = Number(dorm);
  const dormOk = state !== "standby" || (String(dorm).trim() !== "" && Number.isFinite(d) && d >= 0 && d <= 100);
  const p = Number(starts);
  const startOk = state !== "standby" || (String(starts).trim() !== "" && Number.isFinite(p) && p >= 0 && p <= 100);
  const help = BLOCK_STATES.find((s) => s.id === state)?.title;
  return (
    <form className="msd-form msd-rule" onSubmit={(e) => {
      e.preventDefault();
      if (!block || !dormOk || !startOk) return;
      const standby = state === "standby";
      onSave({ block, state, dormancy: standby ? d / 100 : null, start: standby ? p / 100 : null });
    }}>
      {blocks && (
        <Field label="Block">
          <Select value={block} disabled={busy} onChange={(e) => setBlock(e.target.value)}>
            {blocks.map((b) => <option key={b.id} value={b.id}>{b.label}</option>)}
          </Select>
        </Field>
      )}
      <Field label="State in this phase" help={help ? `${help}.` : null}>
        <Select value={state} disabled={busy} onChange={(e) => setState(e.target.value)}>
          {RULE_STATES.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
        </Select>
      </Field>
      {state === "standby" && (
        <Field label="Ages while idle (%)" help="0% is cold standby (no wear while idle); 100% wears as if running."
               error={dormOk ? null : "A percentage from 0 to 100."}>
          <QuantityInput label="Ages while idle (%)" suffix="%" chars={4} min="0" max="100" value={dorm} disabled={busy} onChange={setDorm} />
        </Field>
      )}
      {state === "standby" && (
        <Field label="Chance it starts (%)" help="How often it starts when called on. One that fails to start has failed for the rest of the mission."
               error={startOk ? null : "A percentage from 0 to 100."}>
          <QuantityInput label="Chance it starts (%)" suffix="%" chars={4} min="0" max="100" value={starts} disabled={busy} onChange={setStarts} />
        </Field>
      )}
      <div className="msd-actions">
        <button type="submit" disabled={busy || !block || !dormOk || !startOk}>{initial ? "Save" : "Add the rule"}</button>
        {onCancel && <button type="button" className="secondary" onClick={onCancel} disabled={busy}>Cancel</button>}
        {onRemove && <button type="button" className="secondary danger" onClick={onRemove} disabled={busy}>Delete…</button>}
      </div>
    </form>
  );
}

// ---- a node status rule ------------------------------------------------------------------------

function RuleDetails({ r, busy, viewOnly, savePhases, atPhase, onAction }) {
  const { rule, phase } = r.ref;
  return (
    <>
      <p className="msd-big"><span className="msd-figure-sm">{ruleText(rule)}</span> in {phase.name}</p>
      <p className="rim-tquiet">Blocks without a rule are working (running, ageing, able to fail). This one is set for this phase only; the block keeps its age across the whole mission.</p>
      {viewOnly ? null : (
        <RuleForm key={r.key} initial={rule} busy={busy}
                  onSave={({ state, dormancy, start }) => savePhases(atPhase(phase.index, (p) => withBlockState(p, rule.block, state, dormancy, start)),
                    `${rule.label}: ${ruleText({ state, dormancy, start_probability: start })} in ${phase.name}.`)}
                  onRemove={() => onAction(r, "mission-rule-delete")} />
      )}
    </>
  );
}

// ---- a phase's covariate -----------------------------------------------------------------------

function CovDetails({ r, busy, viewOnly, savePhases, atPhase, onAction }) {
  const { cov, phase, rbd } = r.ref;
  const [value, setValue] = useState(cov.value ?? "");
  useEffect(() => setValue(cov.value ?? ""), [r.key, JSON.stringify(cov.value)]); // eslint-disable-line react-hooks/exhaustive-deps
  const st = covStatus(cov);
  const choice = cov.kind === "choice" && (cov.choices || []).length;
  const sched = isSchedule(value);
  const num = Number(value);
  const ok = sched || String(value).trim() === "" || choice || Number.isFinite(num);
  const same = JSON.stringify(value) === JSON.stringify(cov.value ?? "");
  const unit = String(cov.unit || "").trim();
  return (
    <>
      <p className="msd-big">
        {st.flag === "needs" ? <Chip tone="warning">Needs a value</Chip>
          : st.flag === "unset" ? <><Chip tone="neutral">Not set</Chip> <span className="rim-tquiet">{st.title}{cov.used != null ? `: ${covValueText(cov.used, unit)}` : ""}.</span></>
            : <span className="msd-figure-sm">{st.text}</span>}
      </p>
      <form className="msd-form" onSubmit={(e) => {
        e.preventDefault();
        if (!ok || same) return;
        const v = sched ? value : String(value).trim() === "" ? "" : choice ? value : num;
        savePhases(atPhase(phase.index, (p) => withValue(p, cov.name, v)),
          v === "" ? `Cleared ${cov.name} in ${phase.name}.` : `${cov.name} in ${phase.name}: ${covValueText(v, unit)}.`);
      }}>
        <Field label={`Value in ${phase.name}${unit ? ` (${unit})` : ""}`} error={ok ? null : "A number."}
               help={sched ? "It follows this schedule through the phase: every block it feeds takes it, and the mission follows each change."
                 : "Set once for the phase: every block it feeds takes it."}>
          <PhaseCovValue cov={cov} value={value} onChange={setValue} unit={rbd?.unit} duration={phase.duration}
                         disabled={!!viewOnly || busy} constant={choice ? (
            <Select value={sched ? "" : value} disabled={!!viewOnly || busy} onChange={(e) => setValue(e.target.value)}>
              <option value="">Not set</option>
              {cov.choices.map((c) => <option key={c.code} value={c.code}>{c.label}</option>)}
            </Select>
          ) : (
            <TextInput type="number" inputMode="decimal" step="any" value={sched ? "" : value} placeholder={cov.used != null && !isSchedule(cov.used) ? String(cov.used) : "—"}
                       disabled={!!viewOnly || busy} onChange={(e) => setValue(e.target.value)} />
          )} />
        </Field>
        <div className="msd-actions">
          <button type="submit" disabled={!!viewOnly || busy || !ok || same}>Save</button>
          <button type="button" className="secondary" disabled={!!viewOnly || busy || cov.value == null} onClick={() => onAction(r, "mission-cov-clear")}>Clear the value</button>
        </div>
      </form>
      <section aria-label="What it feeds">
        <h3 className="ml-h">Feeds</h3>
        <p className="msd-line">{(cov.feeds || []).join(", ") || "—"}{cov.role ? ` · ${cap(cov.role)} covariate` : ""}</p>
        <p className="rim-tquiet">It comes from the life models in the mission&apos;s RBD, so it&apos;s listed in every phase and goes when no model uses it. A block&apos;s own value for a phase is set in the mission editor.</p>
      </section>
    </>
  );
}

// The tree's own changes to a phase (from the row menu), with the panel's save path.
export function phaseRowChange(r, id) {
  const i = r.ref.phase.index;
  if (id === "mission-cov-clear") return { change: (rows) => rows.map((p, j) => (j === i ? withValue(p, r.ref.cov.name, "") : p)), text: `Cleared ${r.ref.cov.name} in ${r.ref.phase.name}.` };
  if (id === "mission-rule-delete") return { change: (rows) => rows.map((p, j) => (j === i ? { ...p, ...withBlockState(p, r.ref.rule.block, "working") } : p)), text: `Deleted the rule for ${r.ref.rule.label}: it's working in ${r.ref.phase.name}.` };
  return null;
}

