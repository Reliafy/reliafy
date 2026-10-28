import { useEffect, useRef, useState } from "react";
import { useConfirm } from "./ConfirmProvider.jsx";
import { saveErrorText } from "../confirm.js";
import {
  COMPARATORS, COMPARATOR_LABEL, canSplit, limitWords, proposeSplit, splitLines, standardsShown, unbreachedWords,
} from "../rcmStandards.js";

// A function's performance standards, as a list, in its dialog and its
// Details (the Explorer's RCM tab): each one a line of text (one parameter,
// one limit: "pH 7.2-7.8"), with the structured limit, when it applies and
// its source folded away. Add, edit, remove, move up or down; and, for a
// function that still has its one text with ';' or line breaks in it, "Split
// into standards…", which proposes a line per part for the user to edit,
// drop or mark as a condition, and writes them on Confirm. Each change is
// written at once through `ops.standards` (useTreeRcm) and the row is read
// again, so the list follows. A function's one text (no list yet) shows as
// the first item and is edited as the function's text.
//
//   r         the function's row (read afresh after each save)
//   ops       standards.add / update / remove / reorder / split, set (the one text)
//   readOnly  a team workspace that's view only
//   onSaid    (text) a few words in the page's status line once done

const plural = (n, one, many = `${one}s`) => `${n.toLocaleString("en-AU")} ${n === 1 ? one : many}`;

export default function RcmFunctionStandards({ r, ops, readOnly = false, onSaid }) {
  const confirm = useConfirm();
  const fn = r.ref;
  const shown = standardsShown(fn);
  const [form, setForm] = useState(null); // {mode: "add"} | {mode: "edit", st} | {mode: "split"}
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(null);
  const alive = useRef(true);
  useEffect(() => () => { alive.current = false; }, []);

  const run = async (go, said) => {
    if (busy) return false;
    setBusy(true);
    setFailed(null);
    try {
      await go();
      if (alive.current) {
        setBusy(false);
        setForm(null);
      }
      if (said) onSaid?.(said);
      return true;
    } catch (e) {
      if (alive.current) {
        setBusy(false);
        setFailed(saveErrorText(e, { offline: navigator.onLine === false }));
      }
      return false;
    }
  };

  const remove = async (st) => {
    const body = st.legacy
      ? `The performance standard “${st.text}” is cleared from this function.`
      : `“${st.text}” comes off this function${st.failures ? `; the ${plural(st.failures, "functional failure")} that breached it breach the whole function instead` : ""}.`;
    const ok = await confirm({
      title: "Remove this standard?", body, confirmLabel: "Remove standard", pendingLabel: "Removing…", failedWhat: "remove it",
      run: () => (st.legacy ? ops.set(r, "standard", "") : ops.standards.remove(st.id)).then(() => true),
    });
    if (ok) onSaid?.("Removed the standard.");
  };
  const move = (i, by) => {
    const ids = shown.map((st) => st.id);
    const j = i + by;
    if (j < 0 || j >= ids.length) return;
    [ids[i], ids[j]] = [ids[j], ids[i]];
    run(() => ops.standards.reorder(r, ids), null);
  };

  const hint = unbreachedWords(fn);
  return (
    <section className="rfs" aria-label="Performance standards">
      <h3>{shown.length > 1 ? `Performance standards (${shown.length})` : "Performance standards"}</h3>
      {shown.length === 0 && !form && (
        <p className="rw-fhelp">None yet. One parameter and one limit each, e.g. within 30 m from 60 km/h.</p>
      )}
      {shown.length > 0 && (
        <ol className="rfs-list">
          {shown.map((st, i) => (
            <li key={st.id || "legacy"}>
              <span className="rfs-main">
                <span className="rfs-text">{st.text}</span>
                {limitWords(st) && <span className="rw-fhelp">{limitWords(st)}</span>}
              </span>
              {!readOnly && (
                <span className="rfs-acts">
                  {shown.length > 1 && !st.legacy && (
                    <>
                      <button type="button" className="link" disabled={busy || i === 0} onClick={() => move(i, -1)} aria-label={`Move ${st.text} up`}>↑</button>
                      <button type="button" className="link" disabled={busy || i === shown.length - 1} onClick={() => move(i, 1)} aria-label={`Move ${st.text} down`}>↓</button>
                    </>
                  )}
                  <button type="button" className="link" disabled={busy} aria-label={`Edit ${st.text}`}
                          onClick={() => { setFailed(null); setForm({ mode: "edit", st }); }}>Edit…</button>
                  <button type="button" className="link" disabled={busy} aria-label={`Remove ${st.text}`} onClick={() => remove(st)}>Remove</button>
                </span>
              )}
            </li>
          ))}
        </ol>
      )}
      {hint && <p className="rw-fhelp rfs-hint">{hint}</p>}
      {form?.mode === "add" || form?.mode === "edit" ? (
        <StandardForm key={form.st?.id || "add"} st={form.st || null} busy={busy} failed={failed}
                      onCancel={() => { setForm(null); setFailed(null); }}
                      onSubmit={(body) => run(
                        () => (form.st?.legacy ? ops.set(r, "standard", body.text)
                          : form.st ? ops.standards.update(form.st.id, body) : ops.standards.add(r, body)),
                        form.st ? "Saved the standard." : "Added the standard.",
                      )} />
      ) : form?.mode === "split" ? (
        <SplitForm text={fn.standard} busy={busy} failed={failed} onCancel={() => { setForm(null); setFailed(null); }}
                   onSubmit={(standards) => run(() => ops.standards.split(r, standards), `Split into ${plural(standards.length, "standard")}.`)} />
      ) : !readOnly && (
        <div className="rfs-add">
          <button type="button" className="secondary" disabled={busy} onClick={(e) => { if (e.detail < 2) { setFailed(null); setForm({ mode: "add" }); } }}>
            Add standard
          </button>
          {canSplit(fn) && (
            <button type="button" className="link" disabled={busy} onClick={(e) => { if (e.detail < 2) { setFailed(null); setForm({ mode: "split" }); } }}>
              Split into standards…
            </button>
          )}
        </div>
      )}
      {failed && !form && <p className="rw-ferr" role="alert">{failed}</p>}
    </section>
  );
}

// One standard: its text, and the structured limit, condition and source
// folded under "Limit…". Saved once; a refusal shows here with everything as typed.
function StandardForm({ st, busy, failed, onCancel, onSubmit }) {
  const [text, setText] = useState(st?.text || "");
  const [open, setOpen] = useState(!!(st && (st.parameter || st.comparator || st.value != null || st.unit || st.when || st.source)));
  const [parameter, setParameter] = useState(st?.parameter || "");
  const [comparator, setComparator] = useState(st?.comparator || "");
  const [value, setValue] = useState(st?.value != null ? String(st.value) : "");
  const [unit, setUnit] = useState(st?.unit || "");
  const [when, setWhen] = useState(st?.when || "");
  const [source, setSource] = useState(st?.source || "");
  const box = useRef(null);
  useEffect(() => { box.current?.focus(); }, []);
  const legacy = !!st?.legacy;
  const can = !!text.trim() && !busy;
  const num = value.trim() !== "" && Number.isFinite(Number(value)) ? Number(value) : value.trim();
  return (
    <form className="rfs-form" onSubmit={(e) => {
      e.preventDefault();
      if (!can) return;
      onSubmit(legacy ? { text: text.trim() } : {
        text: text.trim(), parameter: parameter.trim(), comparator, value: num, unit: unit.trim(), when: when.trim(), source: source.trim(),
      });
    }}>
      <h4>{st ? "Change the standard" : "Another performance standard"}</h4>
      <label className="rw-field">
        <span className="rw-flabel">Standard</span>
        <input ref={box} value={text} readOnly={busy} placeholder="One parameter and one limit, e.g. pH 7.2-7.8"
               onChange={(e) => setText(e.target.value)} />
        <span className="rw-fhelp">A standard with “and” in it is two standards; one that needs its own verb is another function.</span>
      </label>
      {!legacy && (
        <>
          <button type="button" className="link rfs-fold" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
            {open ? "Limit (hide)" : "Limit…"}
          </button>
          {open && (
            <div className="rfs-limit">
              <div className="rim-trow">
                <label className="rw-field"><span className="rw-flabel">Parameter</span>
                  <input value={parameter} readOnly={busy} placeholder="e.g. pH" onChange={(e) => setParameter(e.target.value)} /></label>
                <label className="rw-field"><span className="rw-flabel">Comparator</span>
                  <select value={comparator} disabled={busy} onChange={(e) => setComparator(e.target.value)}>
                    <option value="">—</option>
                    {COMPARATORS.map((c) => <option key={c} value={c}>{COMPARATOR_LABEL[c]} ({c})</option>)}
                  </select></label>
                <label className="rw-field"><span className="rw-flabel">Value</span>
                  <input value={value} readOnly={busy} placeholder="7.2-7.8" onChange={(e) => setValue(e.target.value)} /></label>
                <label className="rw-field"><span className="rw-flabel">Unit</span>
                  <input value={unit} readOnly={busy} placeholder="ppm" onChange={(e) => setUnit(e.target.value)} /></label>
              </div>
              <label className="rw-field"><span className="rw-flabel">When it applies (optional)</span>
                <input value={when} readOnly={busy} placeholder="e.g. while the filter pump runs" onChange={(e) => setWhen(e.target.value)} /></label>
              <label className="rw-field"><span className="rw-flabel">Source (optional)</span>
                <input value={source} readOnly={busy} placeholder="e.g. AS 1926.3, the E25 manual" onChange={(e) => setSource(e.target.value)} /></label>
            </div>
          )}
        </>
      )}
      {failed && <p className="rw-ferr" role="alert">{failed}</p>}
      <div className="rim-tform-acts">
        <button type="button" className="secondary" onClick={onCancel} disabled={busy}>Cancel</button>
        <button type="submit" disabled={!can} aria-busy={busy || undefined}>{busy ? "Saving…" : st ? "Save standard" : "Add standard"}</button>
      </div>
    </form>
  );
}

// The split helper: the one text's parts, one line each, to edit, drop or
// mark as a condition (the "when" of the standard before it); written on
// Confirm, never before. The text itself stays on the function.
function SplitForm({ text, busy, failed, onCancel, onSubmit }) {
  const [lines, setLines] = useState(() => proposeSplit(text).map((t, i) => ({ id: i, text: t, kind: "standard", drop: false })));
  const out = splitLines(lines);
  const edit = (id, patch) => setLines((ls) => ls.map((l) => (l.id === id ? { ...l, ...patch } : l)));
  return (
    <form className="rfs-form" onSubmit={(e) => { e.preventDefault(); if (out && !busy) onSubmit(out); }}>
      <h4>Split into standards</h4>
      <p className="rw-fhelp">
        One standard per line, from the text's “;” and line breaks. Edit a line, drop one, or mark a “given …” clause as a
        condition of the standard before it. Nothing is written until you confirm; the text itself stays.
      </p>
      <ol className="rfs-split">
        {lines.map((l) => (
          <li key={l.id} className={l.drop ? "dropped" : ""}>
            <input value={l.text} readOnly={busy || l.drop} aria-label={`Line ${l.id + 1}`} onChange={(e) => edit(l.id, { text: e.target.value })} />
            <select value={l.kind} disabled={busy || l.drop} aria-label={`Line ${l.id + 1} is`} onChange={(e) => edit(l.id, { kind: e.target.value })}>
              <option value="standard">A standard</option>
              <option value="when">A condition (when)</option>
            </select>
            <button type="button" className="link" disabled={busy} onClick={() => edit(l.id, { drop: !l.drop })}>{l.drop ? "Keep" : "Drop"}</button>
          </li>
        ))}
      </ol>
      {!out && <p className="rw-fhelp">Nothing left to write: keep at least one standard.</p>}
      {failed && <p className="rw-ferr" role="alert">{failed}</p>}
      <div className="rim-tform-acts">
        <button type="button" className="secondary" onClick={onCancel} disabled={busy}>Cancel</button>
        <button type="submit" disabled={!out || busy} aria-busy={busy || undefined}>
          {busy ? "Writing…" : `Confirm: ${out ? plural(out.length, "standard") : "nothing"}`}
        </button>
      </div>
    </form>
  );
}

// The standard a functional failure breaches: one of its function's, or the
// whole function (a total loss). Saved at once.
export function BreachesField({ r, standards, readOnly = false, onChange }) {
  const current = r.ref.standard?.id || "";
  if (!standards.length) return null;
  return (
    <label className="rw-field">
      <span className="rw-flabel">Breaches</span>
      {readOnly ? <span className="rw-fval">{r.ref.standard?.text || "The whole function"}</span> : (
        <select value={current} onChange={(e) => onChange(e.target.value || null)} aria-label="Breaches">
          <option value="">The whole function</option>
          {standards.map((st) => <option key={st.id} value={st.id}>{st.text}</option>)}
        </select>
      )}
      <span className="rw-fhelp">Which performance standard this failure is a breach of, as a hint for the reader.</span>
    </label>
  );
}
