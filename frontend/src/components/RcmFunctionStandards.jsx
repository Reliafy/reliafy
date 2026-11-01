import { useEffect, useRef, useState } from "react";
import { useConfirm } from "./ConfirmProvider.jsx";
import { saveErrorText } from "../confirm.js";
import { Field, FormModal } from "./MaintenanceParts.jsx";
import UiField from "./ui/Field.jsx";
import InputGroup, { ReadsAs } from "./ui/InputGroup.jsx";
import MoreMenu from "./ui/MoreMenu.jsx";
import Section from "./ui/Section.jsx";
import { InlineAddButton, InlineAddRow, useInlineAdd } from "./ui/InlineAdd.jsx";
import Chip from "./ui/Chip.jsx";
import { Select, TextInput } from "./ui/Controls.jsx";
import { GripIcon } from "./icons.jsx";
import {
  COMPARATORS, COMPARATOR_LABEL, canSplit, limitReads, limitWords, proposeSplit, splitLines, standardsShown,
} from "../rcmStandards.js";
import { moveItem } from "../listMove.js";

// A function's performance standards, as a list, in its details (the
// Explorer's RCM tab): each one a line of text (one parameter,
// one limit: "pH 7.2-7.8"), with the structured limit, when it applies and
// its source folded away. Add from the dashed row at the end: it becomes a
// new row of the list, a box for the text (Enter or leaving it saves; Esc
// drops it); the limit, when it applies and the source are then the row's
// ⋯ Edit…, as for any other row. From each row's ⋯: edit, move up or down, remove; or drag a
// row by its grip to reorder. For a function that still has its one text with
// ';' or line breaks in it, "Split into standards…" proposes a line per part
// for the user to edit, drop or mark as a condition, and writes them on
// Confirm. Each change is written at once through `ops.standards` (useTreeRcm)
// and the row is read again, so the list follows. A function's one text (no
// list yet) shows as the first item and is edited as the function's text.
//
//   r         the function's row (read afresh after each save)
//   ops       standards.add / update / remove / reorder / split, set (the one text)
//   readOnly  a team workspace that's view only
//   addStart  a value that, when it changes, opens the add row (a row menu's Add a performance standard…)
//   onSaid    (text) a few words in the page's status line once done

// What a performance standard is, behind the "?" by the heading.
const STANDARD_TIP = "One parameter and one limit each, e.g. pH 7.2–7.8. One with “and” in it is two; one that needs its own verb is another function.";

const plural = (n, one, many = `${one}s`) => `${n.toLocaleString("en-AU")} ${n === 1 ? one : many}`;

export default function RcmFunctionStandards({ r, ops, readOnly = false, addStart = null, onSaid }) {
  const confirm = useConfirm();
  const fn = r.ref;
  const shown = standardsShown(fn);
  const [form, setForm] = useState(null); // {mode: "edit", st} | {mode: "split"}
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(null);
  const [drag, setDrag] = useState(null); // {from, over}
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
      title: "Remove this performance standard?", body, confirmLabel: "Remove performance standard", pendingLabel: "Removing…", failedWhat: "remove it",
      run: () => (st.legacy ? ops.set(r, "standard", "") : ops.standards.remove(st.id)).then(() => true),
    });
    if (ok) onSaid?.("Removed the performance standard.");
  };
  const moveTo = (i, j) => {
    const ids = moveItem(shown.map((st) => st.id), i, j);
    if (!ids) return;
    run(() => ops.standards.reorder(r, ids), "Moved the performance standard.");
  };
  const canMove = !readOnly && shown.length > 1 && !shown.some((st) => st.legacy);
  // The add row: a new row of the list, saved on Enter or leaving it.
  const add = useInlineAdd({
    disabled: busy || readOnly,
    startToken: addStart,
    onSave: (text) => ops.standards.add(r, { text }).then(() => { onSaid?.("Added the performance standard."); }),
    errorText: (e) => saveErrorText(e, { offline: navigator.onLine === false }),
  });
  const adding = add.open && !readOnly && form?.mode !== "split";

  return (
    <Section title="Performance standards" count={shown.length} className="rfs" tip={STANDARD_TIP}>
      {(shown.length > 0 || adding) && (
        <ol className="rfs-list">
          {shown.map((st, i) => (
            form?.mode === "edit" && (form.st.id ?? null) === (st.id ?? null) ? (
              <li key={st.id || "legacy"} className="rfs-row editing">
                <StandardForm st={st} busy={busy} failed={failed} onCancel={() => { setForm(null); setFailed(null); }}
                              onSubmit={(body) => run(
                                () => (st.legacy ? ops.set(r, "standard", body.text) : ops.standards.update(st.id, body)),
                                "Saved the performance standard.",
                              )} />
              </li>
            ) : (
              <li key={st.id || "legacy"}
                  className={"rfs-row" + (drag?.over === i && drag.from !== i ? (drag.from < i ? " drop-after" : " drop-before") : "") + (drag?.from === i ? " dragging" : "")}
                  draggable={canMove && !busy}
                  onDragStart={(e) => { setDrag({ from: i, over: i }); e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", st.text); }}
                  onDragOver={(e) => { if (!drag) return; e.preventDefault(); if (drag.over !== i) setDrag({ ...drag, over: i }); }}
                  onDrop={(e) => { e.preventDefault(); if (drag && drag.from !== i) moveTo(drag.from, i); setDrag(null); }}
                  onDragEnd={() => setDrag(null)}>
                {canMove && <span className="rfs-grip" title="Drag to reorder (or use ⋯: Move up, Move down)" aria-hidden="true"><GripIcon /></span>}
                <span className="rfs-main">
                  <span className="rfs-text">{st.text}</span>
                  {limitWords(st) && <span className="rw-fhelp">{limitWords(st)}</span>}
                  {!st.legacy && st.failures === 0 && <span><Chip tone="warning">No functional failure yet</Chip></span>}
                </span>
                {!readOnly && (
                  <MoreMenu label={`Actions for ${st.text}`} disabled={busy} className="rfs-more" items={[
                    { id: "edit", label: "Edit…", onSelect: () => { setFailed(null); setForm({ mode: "edit", st }); } },
                    ...(canMove ? [
                      { id: "up", label: "Move up", disabled: i === 0, reason: i === 0 ? "It's first already." : undefined, onSelect: () => moveTo(i, i - 1) },
                      { id: "down", label: "Move down", disabled: i === shown.length - 1, reason: i === shown.length - 1 ? "It's last already." : undefined, onSelect: () => moveTo(i, i + 1) },
                    ] : []),
                    { id: "remove", label: "Remove…", danger: true, onSelect: () => remove(st) },
                  ]} />
                )}
              </li>
            )
          ))}
          {adding && (
            <InlineAddRow add={add} as="li" className="rfs-row rfs-new" label="New performance standard" placeholder="e.g. pH 7.2–7.8"
                          lead={canMove || shown.length > 0 ? <span className="rfs-grip" aria-hidden="true" /> : null} />
          )}
        </ol>
      )}
      {form?.mode === "split" ? (
        <SplitForm text={fn.standard} busy={busy} failed={failed} onCancel={() => { setForm(null); setFailed(null); }}
                   onSubmit={(standards) => run(() => ops.standards.split(r, standards), `Split into ${plural(standards.length, "performance standard")}.`)} />
      ) : !readOnly && !form && (
        <div className="rfs-add">
          {!add.open && <InlineAddButton add={add}>Add a performance standard</InlineAddButton>}
          {canSplit(fn) && (
            <button type="button" className="link" disabled={busy} onClick={(e) => { if (e.detail < 2) { setFailed(null); setForm({ mode: "split" }); } }}>
              Split into performance standards…
            </button>
          )}
        </div>
      )}
      {failed && !form && <p className="field-error" role="alert">{failed}</p>}
    </Section>
  );
}

// Changing one standard (its ⋯ Edit…): its text, and the structured limit,
// condition and source folded under "Limit…". Saved once; a refusal shows
// here with everything as typed.
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
  const reads = limitReads({ parameter, comparator, value, unit, when });
  return (
    <form className="rfs-form" onSubmit={(e) => {
      e.preventDefault();
      if (!can) return;
      onSubmit(legacy ? { text: text.trim() } : {
        text: text.trim(), parameter: parameter.trim(), comparator, value: num, unit: unit.trim(), when: when.trim(), source: source.trim(),
      });
    }}>
      <UiField label="Performance standard">
        <TextInput ref={box} value={text} readOnly={busy} placeholder="e.g. pH 7.2–7.8" onChange={(e) => setText(e.target.value)} />
      </UiField>
      {!legacy && (
        <>
          <button type="button" className="link rfs-fold" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
            {open ? "Limit (hide)" : "Limit…"}
          </button>
          {open && (
            <div className="rfs-limit">
              <UiField label="Parameter"><TextInput value={parameter} readOnly={busy} onChange={(e) => setParameter(e.target.value)} /></UiField>
              <UiField label="Limit" as="fieldset" help={comparator === "between" ? "A range as “80-120”; one limit as a number." : null}>
                <InputGroup label="Limit">
                  <Select aria-label="Comparator" value={comparator} disabled={busy} onChange={(e) => setComparator(e.target.value)}>
                    <option value="">—</option>
                    {COMPARATORS.map((c) => <option key={c} value={c}>{COMPARATOR_LABEL[c]}</option>)}
                  </Select>
                  <TextInput aria-label="Value" value={value} readOnly={busy} placeholder="Value" onChange={(e) => setValue(e.target.value)} />
                  <TextInput aria-label="Unit" className="ctl-unit" value={unit} readOnly={busy} placeholder="Unit" onChange={(e) => setUnit(e.target.value)} />
                </InputGroup>
              </UiField>
              <ReadsAs>{reads}</ReadsAs>
              <UiField label="When it applies" optional><TextInput value={when} readOnly={busy} placeholder="Always" onChange={(e) => setWhen(e.target.value)} /></UiField>
              <UiField label="Source" optional><TextInput value={source} readOnly={busy} placeholder="A standard, manual or study" onChange={(e) => setSource(e.target.value)} /></UiField>
            </div>
          )}
        </>
      )}
      {failed && <p className="field-error" role="alert">{failed}</p>}
      <div className="rim-tform-acts">
        {!can && !busy && <p className="rim-why">Write the performance standard first.</p>}
        <button type="button" className="secondary sm" onClick={onCancel} disabled={busy}>Cancel</button>
        <button type="submit" className="sm" disabled={!can} aria-busy={busy || undefined}>{busy ? "Saving…" : "Save performance standard"}</button>
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
      <h4>Split into performance standards</h4>
      <p className="rw-fhelp">
        One performance standard per line, from the text's “;” and line breaks. Edit a line, drop one, or mark a “given …” clause as a
        condition of the performance standard before it. Nothing is written until you confirm; the text itself stays.
      </p>
      <ol className="rfs-split">
        {lines.map((l) => (
          <li key={l.id} className={l.drop ? "dropped" : ""}>
            <TextInput value={l.text} readOnly={busy || l.drop} aria-label={`Line ${l.id + 1}`} onChange={(e) => edit(l.id, { text: e.target.value })} />
            <Select value={l.kind} disabled={busy || l.drop} aria-label={`Line ${l.id + 1} is`} onChange={(e) => edit(l.id, { kind: e.target.value })}>
              <option value="standard">A performance standard</option>
              <option value="when">A condition (when)</option>
            </Select>
            <button type="button" className="link" disabled={busy} onClick={() => edit(l.id, { drop: !l.drop })}>{l.drop ? "Keep" : "Drop"}</button>
          </li>
        ))}
      </ol>
      {!out && <p className="rw-fhelp">Nothing left to write: keep at least one performance standard.</p>}
      {failed && <p className="field-error" role="alert">{failed}</p>}
      <div className="rim-tform-acts">
        <button type="button" className="secondary sm" onClick={onCancel} disabled={busy}>Cancel</button>
        <button type="submit" className="sm" disabled={!out || busy} aria-busy={busy || undefined}>
          {busy ? "Writing…" : `Confirm: ${out ? plural(out.length, "performance standard") : "nothing"}`}
        </button>
      </div>
    </form>
  );
}

// The standard a functional failure breaches: one of its function's, or the
// whole function (a total loss). Saved at once.
export function BreachesField({ r, standards, readOnly = false, onChange, saved = 0 }) {
  const current = r.ref.standard?.id || "";
  if (!standards.length) return null;
  return (
    <UiField label="Breaches" saved={saved} help="Which performance standard this failure is a breach of, as a hint for the reader.">
      {readOnly ? <span className="rw-fval">{r.ref.standard?.text || "The whole function"}</span> : (
        <Select value={current} onChange={(e) => onChange(e.target.value || null)}>
          <option value="">The whole function</option>
          {standards.map((st) => <option key={st.id} value={st.id}>{st.text}</option>)}
        </Select>
      )}
    </UiField>
  );
}

// Which of its function's standards a functional failure breaches, from its
// row menu (Change standard…): the whole function, or one of the list. Saved
// once from the dialog (FormModal: the button saying "Saving…" until the
// server answers; a refusal keeps it open with the reason).
//   row       the functional failure's row
//   standards [{id, text}] its function's list
//   onChange  (standardId | null) → a promise
//   onDone    (text | null) once saved: the standard's text, or null for the whole function
export function ChangeStandardModal({ row, standards, onClose, onChange, onDone }) {
  const before = row.ref.standard?.id || "";
  const [to, setTo] = useState(before);
  const name = `“${String(row.ref.text || "").slice(0, 80)}”`;
  return (
    <FormModal title="Which performance standard does it breach?" submitLabel="Save" pendingLabel="Saving…" onClose={onClose}
               canSubmit={to !== before}
               onSubmit={async () => {
                 await onChange(to || null);
                 onDone(to ? standards.find((st) => st.id === to)?.text || null : null);
               }}>
      <p className="lib-date">{name} moves under the performance standard it breaches in the tree. A total loss breaches the whole function.</p>
      <Field label="Breaches">
        <select value={to} onChange={(e) => setTo(e.target.value)} autoFocus aria-label="Breaches">
          <option value="">The whole function</option>
          {standards.map((st) => <option key={st.id} value={st.id}>{st.text}</option>)}
        </select>
      </Field>
    </FormModal>
  );
}
