import { useEffect, useMemo, useRef, useState } from "react";
import { getLibraryRecord, getLibrarySources, linkPositionModel, listModels, previewPositionFit } from "../api.js";
import ChoiceChips from "./ui/ChoiceChips.jsx";
import { Select, TextInput } from "./ui/Controls.jsx";
import { useModes } from "./ModelTable.jsx";
import { saveErrorText } from "../confirm.js";
import {
  METHOD_CHOICES, METHOD_LINE, bodyOf, countsWords, dataOptions, effective, forWords, historyRow, previewKey,
  fitChanged, fitTitle, initialFit, keepsOwnPrior, priorChoices, problem, refusalSwitch, refusalWords, showsTrust,
} from "../fitDialog.js";
import { FitOutcome, PriorFields } from "./PriorFit.jsx";
import TablePane from "./TablePane.jsx";
import LibraryRecordPicker from "./LibraryRecordPicker.jsx";
import { useRecordCovariates } from "./LibraryParts.jsx";
import { rowFromDetail } from "../libraryPicker.js";
import "./RcmWorksheet.css";
import "./FitLifeModel.css";

// "Fit a life model…" (Life model ›) fills the Explorer's table area, the tree kept beside it
// (Derryn, 9 Nov 2026: "It shouldn't be a modal itself, only the select life model from the
// library"). FitPane is that area: a heading ("Fit a life model · <position>") with a close, and
// FitLifeModel under it: inputs on the left as a step | choice grid (Data with the history under
// it, Method, Prior, Distribution, For), the result on the right (what came out, the curve, the
// numbers, reliability at an age, how it was computed), Cancel and Save in a bar under it. Both
// columns scroll on their own; when the area is narrow they stack, inputs first, each as tall as
// what's in it, the pane scrolling as one with Cancel and Save kept at its foot. Every change asks again a
// moment later (fitDialog.previewKey: the request and what's missing). Only the library record
// picker is a dialog, over the pane.
//
//   position  {id, name, position_class}
//   start     {data?, method?, priorKind?, modelId?, recordId?, update?}   link: a row it replaces (Refit…)
//             update: "Update with new failures…" on a fit with a prior, that row's model the prior
//             (fitDialog.priorFrom); its own prior is kept, so trust isn't asked.

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
    <TablePane title={fitTitle(link, start)} subject={position.name} phone={phone} busy={saving} headingRef={headingRef} onClose={onClose}
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
                <PriorFields
                  state={state} set={set} kind={eff.priorKind}
                  kinds={state.data !== "both" ? priorChoices(state.data).filter((p) => p.value !== "class" || position.position_class) : null}
                  onKind={(k) => {
                    set("priorKind", k);
                    if (k === "library" && !state.recordId && !autoOpened.current) { autoOpened.current = true; setPicking(true); }
                  }}
                  trust={showsTrust(eff.priorKind) && !keepsOwnPrior(state, start, d)}
                  models={models}
                  modelFallback={state.modelId && state.modelId === link?.model_id && !(models || []).some((m) => m.id === state.modelId) ? (
                    // The row it was opened from, while the list is read or if the list leaves it out.
                    <option value={state.modelId}>{link.model?.name || link.name}</option>
                  ) : null}
                  record={record} libCov={libCov} onPickRecord={() => setPicking(true)} pickArea={pickArea}
                />
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
            <FitOutcome d={d} priorKind={eff.priorKind} unit={u} chart={chart} onChart={setChart} download={position.name}
                        age={state.age} onAge={(v) => set("age", v)}
                        dataWords={state.data === "class" ? "the class's history" : "this position's history"} />
          )}
        </section>
        {/* Cancel and Save are the pane's own foot, not the result's: always in view, whichever part is being read. */}
        <div className="fit2-foot">
          {failed && <p className="field-error fit2-failed" role="alert">{failed}</p>}
          <button type="button" className="secondary" onClick={onClose} disabled={saving}>Cancel</button>
          <button type="button" onClick={save} disabled={saving || !d?.can_save} aria-busy={saving || undefined}>
            {saving ? "Saving…" : "Save as this position's model"}
          </button>
        </div>
      </div>
      {picking && (
        <LibraryRecordPicker use="prior" selectedId={state.recordId} onClose={closePicker}
                             onPick={(r) => { set("recordId", r.id); setRecord(r); closePicker(); }} />
      )}
    </>
  );
}
