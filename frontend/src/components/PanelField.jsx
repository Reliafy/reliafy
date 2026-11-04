import { useEffect, useRef, useState } from "react";
import Field from "./ui/Field.jsx";
import InputGroup, { Addon } from "./ui/InputGroup.jsx";
import { TextArea, TextInput } from "./ui/Controls.jsx";

// A field in the panel (the shared Field): kept when you leave it (or press
// Enter in a one-line field), "✓ Saved" by its label once it is; a value the
// server would refuse stays as typed with the reason under it, and leaving
// the field again sends it again. `suffix`: the unit inside the box. `type`
// "number" (with `range` {min, max, integer}) or "date". `onDraft`: told the
// text as it's typed (the FME(C)A's live RPN and action priority). `title`:
// the control's tooltip (a scale's ten hints).
export function PanelField({
  label, help, value, area, readOnly, type, suffix, onCommit, placeholder = null, optional = false, saved = 0, range = null, onDraft = null,
  title = null, shown = null,
}) {
  const [draft, setDraft] = useState(String(value ?? ""));
  const [error, setError] = useState(null);
  // What was last sent: Enter then leaving the field (or Enter twice) sends it
  // once; typing, or coming back to the field, can send it again.
  const sent = useRef(null);
  useEffect(() => { setDraft(String(value ?? "")); setError(null); sent.current = null; }, [value]);
  if (readOnly) {
    return (
      <div className="field">
        <span className="field-label">{label}</span>
        <span className="rw-fval">{value === "" || value == null ? "—" : `${shown ?? value}${suffix ? ` ${suffix}` : ""}`}</span>
      </div>
    );
  }
  const commit = () => {
    if (draft === String(value ?? "") || draft === sent.current) return;
    const err = onCommit(draft);
    if (typeof err !== "string") sent.current = draft;
    setError(typeof err === "string" ? err : null);
    if (err && typeof err.then === "function") {
      const was = draft;
      err.then((out) => {
        if (typeof out !== "string") return;
        if (sent.current === was) sent.current = null;
        setError(out);
      });
    }
  };
  const props = {
    value: draft, placeholder: placeholder || undefined, title: title || undefined,
    onChange: (e) => { setDraft(e.target.value); sent.current = null; onDraft?.(e.target.value); },
    onBlur: commit,
    onFocus: () => { sent.current = null; },
  };
  const num = type === "number";
  const control = area
    ? <TextArea {...props} />
    : <TextInput {...props} type={num ? "number" : type === "date" ? "date" : "text"} inputMode={num ? (range?.integer ? "numeric" : "decimal") : undefined}
                 min={num ? String(range?.min ?? 0) : undefined} max={num && range?.max != null ? String(range.max) : undefined}
                 step={num ? (range?.integer ? "1" : "any") : undefined}
                 onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); commit(); } }} />;
  return (
    <Field label={label} help={help} error={error} optional={optional} saved={saved}>
      {suffix ? <InputGroup>{control}<Addon>{suffix}</Addon></InputGroup> : control}
    </Field>
  );
}
