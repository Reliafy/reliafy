import { Suspense, lazy, useEffect, useMemo, useRef, useState } from "react";
import { calculateMission, getMission, getRbd, updateMission } from "../api.js";
import TablePane from "./TablePane.jsx";
import CovariateInputs from "./CovariateInputs.jsx";
import MissionBlockGrid from "./MissionBlockGrid.jsx";
import ResultSummary from "./ui/ResultSummary.jsx";
import Chip from "./ui/Chip.jsx";
import { saveErrorText } from "../confirm.js";
import { ShowMe } from "./SectionPage.jsx";
import {
  SOURCE_WORDS, answerText, cleanPhases, editablePhase, fadedIn, feedsText, fmt, leaveOut, lengthText, movePhase, newPhase, pct, phaseCompletes,
  phaseCovariates, phaseLine, phaseNeeds, placeholderWarning, unitWord, withBlockValue, withValue,
} from "../explorerMissions.js";
import "./CovariateCalculator.css";
import "./RbdMission.css";
import "./MissionPane.css";

// The diagram loads only when "Show the RBD" asks for it (React Flow is large).
const RbdDiagramView = lazy(() => import("./RbdDiagramView.jsx"));

// A mission in the Explorer's table area (?mission=<RBD id>:<mission id>&on=<position id>,
// tablePane.js), the tree kept beside it: the RBD flown through its phases (Derryn, 9 Nov 2026).
// Each phase is a row with its name, duration, the chance of completing it once started and the
// chance the mission is still going at its end; opening a phase shows every Use and Environment
// covariate its blocks left open (from the RBD's NSWC-11, accelerated life and proportional-
// hazards blocks), grouped Use / Environment with the blocks each feeds. A value is set once for
// the phase and every block using it takes it; a block can have its own for the phase. A block
// still without a value says "needs a value", and that phase's result waits. Under the covariates:
// the blocks the phase doesn't need, vote counts for the phase, and "Show the RBD" with the blocks
// it doesn't need faded. The covariate fields are the one shared component (CovariateInputs.jsx).
//
//   rbdId, missionId     position {id, name}
//   phase                the phase to open on (its index, from a phase row in the tree): opened,
//                        its name field focused; else the first phase is opened
//   onSaved(text)        onDeleted(text)      onDirty(changed)
//   onOpenRbd()          the mission's RBD opened in the shared RBD builder, in this table area
//   phone, headingRef, onClose: TablePane's

const valueText = (v, unit) => (v == null ? "—" : `${typeof v === "number" ? fmt(v) : v}${unit ? (unit === "%" ? "%" : ` ${unit}`) : ""}`);

export default function MissionPane({ rbdId, missionId, position, phase = null, phone = false, headingRef = null, onClose, onSaved, onDirty, onDelete, onOpenRbd }) {
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState(null);
  const [name, setName] = useState("");
  const [rows, setRows] = useState([]);
  const [open, setOpen] = useState(() => new Set());
  const [dirty, setDirty] = useState(false);
  const [tried, setTried] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState(null);
  const [result, setResult] = useState(null);
  const [calc, setCalc] = useState({ busy: false, error: null, stale: false });
  const [shown, setShown] = useState(null); // the phase key whose RBD is shown
  const [graph, setGraph] = useState(null);
  const [focusOn, setFocusOn] = useState(null); // the phase key whose name takes focus, once

  const load = () => getMission(rbdId, missionId).then((d) => {
    setDetail(d);
    setName(d.mission.name);
    const eds = (d.mission.phases || []).map(editablePhase);
    setRows(eds);
    const at = eds[phase ?? 0] || eds[0];
    setOpen(new Set(at ? [at.key] : []));
    if (phase != null && eds[phase]) setFocusOn(eds[phase].key);
    setError(null);
  }, (e) => setError(e));
  useEffect(() => { load(); }, [rbdId, missionId]); // eslint-disable-line react-hooks/exhaustive-deps

  // Opened on a phase (from the tree): its name field focused, ready to be named.
  useEffect(() => {
    if (focusOn == null) return;
    const el = document.getElementById(`mission-phase-name-${focusOn}`);
    if (el) {
      el.focus();
      el.select?.();
    }
    setFocusOn(null);
  }, [focusOn, detail]);

  const blocks = detail?.blocks || [];
  const votes = detail?.votes || [];
  const unit = detail?.unit || "";
  const readOnly = !!detail?.rbd?.read_only;
  const { phases, errors } = useMemo(() => cleanPhases(rows, { blocks, votes }), [rows, blocks, votes]);
  const covRows = detail?.covariates || [];
  const byPhase = useMemo(() => rows.map((r) => phaseCovariates(covRows, r)), [rows, covRows]);
  const total = phases.reduce((t, p) => t + (Number.isFinite(p.duration) ? p.duration : 0), 0);

  const change = (fn) => {
    setRows(fn);
    setDirty(true);
    onDirty?.(true);
    setCalc((c) => ({ ...c, stale: true }));
  };
  const patch = (key, p) => change((rs) => rs.map((r) => (r.key === key ? { ...r, ...p } : r)));
  const toggle = (key) => setOpen((s) => {
    const next = new Set(s);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    return next;
  });

  // Worked out with what's on screen (saved or not); a saved mission's result is kept for the table.
  const calculate = async () => {
    setTried(true);
    if (errors.length || !phases.length) return;
    setCalc({ busy: true, error: null, stale: false });
    try {
      const got = await calculateMission(rbdId, missionId, dirty ? phases : null);
      setResult(got);
      setCalc({ busy: false, error: null, stale: false });
      if (!dirty) onSaved?.(null);
    } catch (e) {
      setCalc({ busy: false, error: e.message, stale: false });
    }
  };
  // Opening a mission with phases works it out straight away.
  const first = useRef(true);
  useEffect(() => {
    if (!detail || !first.current) return;
    first.current = false;
    if ((detail.mission.phases || []).length) calculate();
  }, [detail]); // eslint-disable-line react-hooks/exhaustive-deps

  const save = async () => {
    setTried(true);
    if (errors.length) return;
    setSaving(true);
    setSaveError(null);
    try {
      await updateMission(rbdId, missionId, { name: name.trim() || detail.mission.name, phases, expected_updated_at: detail.rbd.updated_at });
      setDirty(false);
      onDirty?.(false);
      const fresh = await getMission(rbdId, missionId);
      setDetail(fresh);
      onSaved?.(`Saved ${name.trim() || detail.mission.name}.`);
      // The saved mission worked out, its result kept for the table: the table is told again once
      // it's there (its read after the save can come back before this has finished).
      await calculateMission(rbdId, missionId).then((got) => {
        setResult(got);
        onSaved?.(null);
      }, () => {});
    } catch (e) {
      setSaveError(saveErrorText(e, { offline: navigator.onLine === false }));
    } finally {
      setSaving(false);
    }
  };

  const showRbd = async (key) => {
    if (shown === key) return setShown(null);
    setShown(key);
    if (!graph) getRbd(rbdId).then((d) => setGraph(d.graph), () => setGraph({ nodes: [], edges: [] }));
  };

  const resultRow = (i) => (result && !calc.stale ? result.phases?.[i] : null);
  const u = unitWord(unit);
  const title = detail ? `Mission: ${detail.mission.name}` : "Mission";

  return (
    <TablePane title="Mission" subject={`${detail?.mission?.name || "…"} · ${position.name}`} phone={phone} busy={saving}
               headingRef={headingRef} onClose={onClose} className="mission-pane">
      <div className="mission">
        {error && (
          <p className="field-error" role="alert">
            {error.status === 404 ? "This mission isn't there any more: it was deleted, or its RBD was." : `The mission didn't load: ${error.message}`}
          </p>
        )}
        {!detail && !error && <p className="rim-tquiet">Opening the mission…</p>}
        {detail && (
          <>
            <div className="mission-head">
              <label className="mission-name">
                <span>Mission name</span>
                <input value={name} maxLength={80} disabled={readOnly}
                       onChange={(e) => { setName(e.target.value); setDirty(true); onDirty?.(true); }} />
              </label>
              <p className="rim-tquiet mission-on">
                Runs on <b>{detail.rbd.name}</b>{onOpenRbd ? <> (<button type="button" className="link" onClick={onOpenRbd}>open it</button>)</> : null}{u ? `, in ${u}` : ""}: {rows.length} phase{rows.length === 1 ? "" : "s"},{" "}
                {lengthText(total, unit)} in all. The blocks age through the whole mission, except while they stand by: wear in one phase stays for the next.{" "}
                <ShowMe help={{ guide: "missions-and-phases" }}>Show me how</ShowMe>
              </p>
            </div>

            {(detail.series_warning || result?.series_warning) && (
              <section className="mission-ph mission-series" role="note" aria-label="Blocks placed in series">
                <p>
                  <b>Check the wiring:</b> {result?.series_warning || detail.series_warning}{" "}
                  {onOpenRbd && <button type="button" className="secondary sm" onClick={onOpenRbd}>Open the RBD</button>}
                </p>
              </section>
            )}
            <MissionAnswer result={calc.stale ? null : result} busy={calc.busy} error={calc.error} stale={calc.stale}
                           total={total} unit={unit} />
            {!calc.stale && !calc.error && (
              <MissionPlaceholders result={result} readOnly={readOnly} onOpenRbd={onOpenRbd}
                                   onLeaveOut={(ids) => change((rs) => leaveOut(rs, ids))} />
            )}

            <MissionBlockGrid blocks={blocks} phases={rows} readOnly={readOnly} onChange={patch} />

            {detail.problems?.length > 0 && (
              <p className="field-error">{detail.problems.map((p) => `${p.label}: ${p.problem}`).join(" · ")}</p>
            )}

            <ol className="mission-phases" aria-label={`${title}: phases`}>
              {rows.map((row, i) => {
                const covs = byPhase[i] || [];
                const needs = phaseNeeds(covs);
                const isOpen = open.has(row.key);
                const res = resultRow(i);
                const done = phaseCompletes(res);
                const bodyId = `mission-phase-${row.key}`;
                return (
                  <li key={row.key} className={"mission-phase" + (isOpen ? " is-open" : "")}>
                    <div className="mission-phase-head">
                      <button type="button" className="ghost sm mission-phase-toggle" aria-expanded={isOpen} aria-controls={bodyId}
                              onClick={() => toggle(row.key)} aria-label={`${isOpen ? "Close" : "Open"} phase ${i + 1}, ${row.name || "no name"}`}>
                        <span aria-hidden="true">{isOpen ? "▾" : "▸"}</span> <span className="mission-phase-n">{i + 1}</span>
                      </button>
                      <label className="mission-phase-name">
                        <span className="sr-only">Name of phase {i + 1}</span>
                        <input id={`mission-phase-name-${row.key}`} value={row.name} placeholder="Name" maxLength={80} disabled={readOnly}
                               onChange={(e) => patch(row.key, { name: e.target.value })} />
                      </label>
                      <label className="mission-phase-duration">
                        <span className="sr-only">Duration of phase {i + 1}{u ? ` (${u})` : ""}</span>
                        <input type="number" inputMode="decimal" min="0" step="any" value={row.duration} placeholder="Duration" disabled={readOnly}
                               onChange={(e) => patch(row.key, { duration: e.target.value })} />
                        {u && <span className="cov-unit">{u}</span>}
                      </label>
                      <span className="mission-phase-result">
                        {res?.waiting || (needs.length && !res) ? (
                          <Chip tone="warning" title={`Needs a value: ${needs.join(", ")}`}>Needs values</Chip>
                        ) : res ? (
                          <span title="The chance the mission gets through this phase once it has started; then the chance it's still going at the phase's end">
                            Completes <b>{pct(done)}</b><span className="mission-sub"> · {pct(res.reliability_at_end)} still going</span>
                          </span>
                        ) : <span className="rw-blank">—</span>}
                      </span>
                      {!readOnly && (
                        <span className="mission-phase-tools">
                          <button type="button" className="ghost sm" onClick={() => change((rs) => movePhase(rs, i, -1))} disabled={i === 0}
                                  aria-label={`Move phase ${i + 1} earlier`} title="Earlier">↑</button>
                          <button type="button" className="ghost sm" onClick={() => change((rs) => movePhase(rs, i, 1))} disabled={i === rows.length - 1}
                                  aria-label={`Move phase ${i + 1} later`} title="Later">↓</button>
                          <button type="button" className="ghost sm" onClick={() => change((rs) => rs.filter((r) => r.key !== row.key))}
                                  aria-label={`Remove phase ${i + 1}`} title="Remove">×</button>
                        </span>
                      )}
                    </div>
                    <p className="mission-phase-line">{phaseLine(row, { blocks, votes })}
                      {res?.weakest ? <> · {result?.placeholders?.length ? "Weakest with a model" : "Weakest"}: <b>{res.weakest.label}</b> ({fmt(res.weakest.share * 100)}% of this phase's failures)</> : null}
                    </p>
                    {isOpen && (
                      <div className="mission-phase-body" id={bodyId}>
                        <section aria-label={`Covariates in ${row.name || `phase ${i + 1}`}`}>
                          <h4 className="mission-k">Covariates in this phase</h4>
                          {covs.length === 0 ? (
                            <p className="rim-tquiet">No block in this RBD has use or environment covariates left open: each block keeps one life model.</p>
                          ) : (
                            <PhaseCovariates rows={covs} phase={row} idPrefix={`mp-${row.key}`} readOnly={readOnly}
                                             onChange={(next) => patch(row.key, next)} />
                          )}
                        </section>
                        {votes.map((v) => (
                          <label key={v.id} className="rbd-phase-vote">
                            <span>{v.label}: working inputs needed</span>
                            <input type="number" inputMode="numeric" min="1" max={v.inputs || undefined} step="1" disabled={readOnly}
                                   value={row.votes[v.id] ?? ""} placeholder={String(v.n)}
                                   onChange={(e) => patch(row.key, { votes: { ...row.votes, [v.id]: e.target.value } })} />
                            <small>of {v.inputs}</small>
                          </label>
                        ))}
                        <button type="button" className="secondary sm" onClick={() => showRbd(row.key)} aria-expanded={shown === row.key}>
                          {shown === row.key ? "Hide the RBD" : "Show the RBD"}
                        </button>
                        {shown === row.key && (
                          graph ? (
                            <figure className="mission-rbd">
                              <Suspense fallback={<p className="rim-tquiet">Drawing the RBD…</p>}>
                                <RbdDiagramView graph={graph} dim={fadedIn(row)} label={`The RBD in ${row.name}: faded blocks aren't needed or are standing by`} />
                              </Suspense>
                              <figcaption className="rim-tquiet">
                                {fadedIn(row).size ? "Faded blocks aren't needed in this phase (they still age) or stand by (they don't)." : "Every block runs in this phase."}
                              </figcaption>
                            </figure>
                          ) : <p className="rim-tquiet">Drawing the RBD…</p>
                        )}
                      </div>
                    )}
                  </li>
                );
              })}
            </ol>
            {rows.length === 0 && <p className="rim-tquiet">No phases yet. Add the first: a start-up, steady running, a peak…</p>}

            {tried && errors.length > 0 && (
              <ul className="rbd-costs-errors">{errors.map((e) => <li key={e}>{e}</li>)}</ul>
            )}
            {saveError && <p className="field-error" role="alert">{saveError}</p>}
            <div className="mission-foot">
              {!readOnly && (
                <button type="button" className="secondary" disabled={rows.length >= 50}
                        onClick={() => change((rs) => {
                          const p = newPhase(rs.length, rs);
                          setOpen((s) => new Set([...s, p.key]));
                          return [...rs, p];
                        })}>
                  Add a phase
                </button>
              )}
              <span className="mission-foot-gap" />
              {!readOnly && onDelete && (
                <button type="button" className="secondary danger" onClick={onDelete} disabled={saving}>Delete…</button>
              )}
              <button type="button" className={dirty && !readOnly ? "secondary" : ""} onClick={calculate}
                      disabled={calc.busy || !rows.length} aria-busy={calc.busy || undefined} data-wt="mission-calculate">
                {calc.busy ? "Working it out…" : "Calculate"}
              </button>
              {!readOnly && (
                <button type="button" onClick={save} disabled={!dirty || saving} aria-busy={saving || undefined}>
                  {saving ? "Saving…" : "Save"}
                </button>
              )}
            </div>
            {readOnly && <p className="rim-tquiet">This RBD isn't yours to change: you can work its missions out, not edit them.</p>}
          </>
        )}
      </div>
    </TablePane>
  );
}

// The answer first: the chance the mission completes, in words, then the numbers.
function MissionAnswer({ result, busy, error, stale, total, unit }) {
  if (error) return <p className="field-error" role="alert">{error}</p>;
  if (!result) {
    return <p className="rim-tquiet mission-wait" role="status">{busy ? "Working the mission out…" : stale ? "Changed: Calculate to work it out again." : "Calculate to work out the chance the mission completes."}</p>;
  }
  const waiting = result.reliability == null;
  const risky = result.riskiest;
  const ph = placeholderWarning(result);
  return (
    <ResultSummary tone={waiting || ph ? "caveat" : "neutral"} className="mission-answer" sentence={answerText(result)}
                   stats={waiting ? [] : [
                     { label: ph ? "With placeholders" : "Completes", value: pct(result.reliability), hint: ph ? "not a real figure" : undefined },
                     ph ? (ph.without != null ? { label: `Without ${ph.n === 1 ? "it" : "them"}`, value: pct(ph.without), hint: "the blocks with models" } : null)
                       : { label: "Fails", value: pct(result.unreliability) },
                     { label: "Mission length", value: lengthText(total, unit) },
                     result.interval ? { label: `Range (${fmt(result.interval.confidence * 100)}%)`, value: `${pct(result.interval.lower)}–${pct(result.interval.upper)}`, hint: "the simulation's precision" } : null,
                     risky && (result.phases || []).length > 1 ? { label: "Riskiest phase", value: risky.name } : null,
                   ]}>
      {waiting && result.needs?.length ? result.needs.map((n) => `${n.phase}: ${n.lines.join("; ")}`).join(" · ") : null}
      {!waiting ? `${result.method === "exact" ? "Worked out exactly." : "Simulated: the mission is too large to work out exactly."} ${result.bound_note ? `${result.bound_note} ` : ""}${(result.notes || []).filter((n) => n !== result.series_warning).join(" ")}` : null}
    </ResultSummary>
  );
}

// The blocks with no model, said plainly under the answer: which they are, what the answer is
// without them, and what can be done (give them models in the RBD, or leave them out of the
// mission: Not needed in every phase, which is also each block's own choice in the grid below).
function MissionPlaceholders({ result, readOnly, onOpenRbd, onLeaveOut }) {
  const ph = placeholderWarning(result);
  const out = (result?.placeholders_left_out || []).map((p) => p.label);
  if (!ph) {
    if (!out.length) return null;
    return (
      <p className="rim-tquiet mission-ph-out" role="note">
        {out.join(", ")} {out.length === 1 ? "has" : "have"} no model and {out.length === 1 ? "is" : "are"} left out of this mission (Not needed in every phase), so the result doesn't rest on {out.length === 1 ? "it" : "them"}.
      </p>
    );
  }
  const them = ph.n === 1 ? "it" : "them";
  return (
    <section className="mission-ph" role="note" aria-label="Blocks with no model">
      <p className="mission-ph-what">
        <b>{ph.count.charAt(0).toUpperCase() + ph.count.slice(1)}:</b> {ph.list}. A placeholder life stands in for {ph.n === 1 ? "it" : "each"}, and the answer depends on {them}
        {ph.without != null ? <>: <b>{pct(result.reliability)}</b> with {them}, <b>{pct(ph.without)}</b> from the blocks with models alone.</> : "."}
        {result.phases?.some((p) => p.weakest) ? " The weakest block in each phase is picked from the blocks with models." : ""}
      </p>
      <ul className="mission-ph-do">
        <li>
          <b>Give {them} a model:</b> set each block's model in the mission's RBD.{" "}
          {onOpenRbd && <button type="button" className="secondary sm" onClick={onOpenRbd}>Open the RBD</button>}
        </li>
        <li>
          <b>Leave {them} out:</b> mark {them} Not needed in every phase, so the mission is worked out from the blocks with models.{" "}
          {!readOnly && (
            <button type="button" className="secondary sm" onClick={() => onLeaveOut(result.placeholders.map((p) => p.id))}>
              Leave {ph.n === 1 ? "it" : `all ${ph.n}`} out
            </button>
          )}
        </li>
        <li><b>Or one at a time:</b> set a block Not needed in the phases that don't use it, in the grid below.</li>
      </ul>
      {out.length > 0 && <p className="mission-ph-also">Already left out: {out.join(", ")}.</p>}
    </section>
  );
}

// A phase's covariates with the one covariate input component: a value set once for the phase,
// and under each, the blocks it feeds with the value each uses, where it comes from, and a field
// for a block's own value in this phase.
function PhaseCovariates({ rows, phase, idPrefix, readOnly, onChange }) {
  const [own, setOwn] = useState(() => new Set());
  // A default only where every block it feeds has one (the same): else the phase needs a value.
  const shared = (r) => {
    const ds = r.blocks.map((b) => b.default);
    return ds.length && ds.every((d) => d != null && d === ds[0]) ? ds[0] : null;
  };
  const inputs = rows.map((r) => ({ key: r.name, label: r.name, unit: r.unit, role: r.role, kind: r.kind, choices: r.choices,
    limits: r.limits, help: r.help, symbol: null, default: shared(r) }));
  const values = Object.fromEntries(rows.map((r) => [r.name, phase.values?.[r.name] ?? ""]));
  const sources = Object.fromEntries(rows.filter((r) => r.value == null && r.diagram != null && r.diagram !== "")
    .map((r) => [r.name, { value: r.diagram, words: "the RBD's value" }]));
  const extra = (input) => {
    const row = rows.find((r) => r.name === input.key);
    if (!row) return null;
    // Blocks that take the phase's value (or the RBD's, or the default) are one line; a block with
    // its own value, or none, gets its own line; "Set a block's own…" adds one for this phase.
    const shown = row.blocks.filter((b) => b.missing || b.source === "override" || b.source === "own"
      || own.has(`${b.id}:${b.key}`));
    const rest = row.blocks.filter((b) => !shown.includes(b));
    const common = rest.length ? rest[0] : null;
    const same = common && rest.every((b) => b.source === common.source && b.used === common.used);
    const pickable = row.blocks.filter((b) => !shown.includes(b));
    return (
      <div className="mission-feeds">
        <span className="mission-feeds-what">{feedsText(row)}</span>
        <ul>
          {rest.length > 0 && same && (
            <li>
              <span className="mission-feed-uses">
                {rest.length === row.blocks.length ? (row.blocks.length > 1 ? "Each uses " : "Uses ") : `The other${rest.length > 1 ? "s use" : " uses"} `}
                {valueText(common.used, row.unit)}<span className="mission-sub"> ({SOURCE_WORDS[common.source]})</span>
              </span>
            </li>
          )}
          {rest.length > 0 && !same && rest.map((b) => (
            <li key={`${b.id}:${b.key}`}>
              <span className="mission-feed-label">{b.label}</span>
              <span className="mission-feed-uses">uses {valueText(b.used, row.unit)}<span className="mission-sub"> ({SOURCE_WORDS[b.source]})</span></span>
            </li>
          ))}
          {shown.map((b) => (
            <li key={`${b.id}:${b.key}`} className={b.missing ? "is-missing" : ""}>
              <span className="mission-feed-label">{b.label}</span>
              {b.missing ? (
                <span className="field-error mission-needs">needs a value</span>
              ) : b.source === "override" ? null : b.source === "own" ? (
                <span className="mission-feed-uses">uses {valueText(b.used, row.unit)}<span className="mission-sub"> ({SOURCE_WORDS.own})</span></span>
              ) : null}
              {(b.source === "override" || own.has(`${b.id}:${b.key}`)) && (
                <CovariateInputs bare readOnly={readOnly} idPrefix={`${idPrefix}-${b.id}`}
                                 inputs={[{ ...input, key: b.key, label: `${b.label}'s own in this phase` }]}
                                 values={{ [b.key]: phase.block_values?.[b.id]?.[b.key] ?? "" }}
                                 sources={{ [b.key]: { value: row.value ?? row.diagram ?? b.default, words: "this phase" } }}
                                 onChange={(v) => onChange(withBlockValue(phase, b.id, b.key, v[b.key]))} />
              )}
            </li>
          ))}
        </ul>
        {!readOnly && pickable.length > 0 && (
          <select className="mission-own-pick" aria-label={`Set a block's own ${row.name} in this phase`} value=""
                  onChange={(e) => {
                    const v = e.target.value;
                    if (v) setOwn((s) => new Set([...s, v]));
                  }}>
            <option value="">Set a block's own…</option>
            {pickable.map((b) => <option key={`${b.id}:${b.key}`} value={`${b.id}:${b.key}`}>{b.label}</option>)}
          </select>
        )}
        {row.missing.length > 0 && (
          <p className="field-error mission-row-needs">Needs a value for {row.missing.join(", ")}: set it for the phase, or on each block.</p>
        )}
      </div>
    );
  };
  return (
    <CovariateInputs inputs={inputs} values={values} idPrefix={idPrefix} sources={sources} readOnly={readOnly} extra={extra}
                     onChange={(v) => {
                       let next = phase;
                       for (const r of rows) if ((v[r.name] ?? "") !== (values[r.name] ?? "")) next = withValue(next, r.name, v[r.name]);
                       onChange({ values: next.values });
                     }} />
  );
}
