import { Children, cloneElement, createContext, isValidElement, useContext, useEffect, useId, useRef, useState } from "react";

// A form field (#UI): the label, an "optional" marker beside it, a slot at the
// label's right end (a character counter, or "✓ Saved" for 2 s after a save),
// the control, then one line under it: an error (red, with a round "!" and
// role="alert") or else the help. Never both.
//
//   label     the words over the control (the control's accessible name)
//   optional  true: "optional" beside the label, quieter, not in brackets (and
//             not part of the control's name)
//   help      one line of help (12 px, muted), wired to the control
//   error     the reason a value isn't kept; the control is marked invalid
//   count     a node at the label's end (e.g. <CharCount>), aria-hidden
//   saved     a number that changes on each save: "✓ Saved" shows for 2 s
//   as        "div" (default) or "fieldset" for a group (comparator + value + unit)
//
// The control is the child. TextInput, TextArea and Select read the field's
// ids from context; a bare <input>, <select> or <textarea> child gets them
// cloned on. Anything else (a group) uses useField() itself.
const FieldContext = createContext(null);
export const useField = () => useContext(FieldContext);

export function SavedMark({ saved }) {
  const [show, setShow] = useState(false);
  const first = useRef(saved);
  useEffect(() => {
    if (!saved || saved === first.current) return undefined;
    setShow(true);
    const t = setTimeout(() => setShow(false), 2000);
    return () => clearTimeout(t);
  }, [saved]);
  return show ? <span className="field-saved" role="status">✓ Saved</span> : null;
}

const NATIVE = new Set(["input", "select", "textarea"]);

export default function Field({
  label, optional = false, help = null, error = null, count = null, saved = 0, as = "div", className = "", id: forced, children, labelHidden = false,
}) {
  const auto = useId();
  const id = forced || `f${auto}`;
  const helpId = `${id}-help`;
  const describedBy = error || help ? helpId : undefined;
  // A group (fieldset) names its controls itself: they don't take its id.
  const ctx = { id: as === "fieldset" ? undefined : id, describedBy, invalid: !!error };
  const kids = Children.map(children, (c) => (isValidElement(c) && typeof c.type === "string" && NATIVE.has(c.type)
    ? cloneElement(c, {
      id: c.props.id || ctx.id,
      "aria-describedby": c.props["aria-describedby"] || describedBy,
      "aria-invalid": c.props["aria-invalid"] ?? (error ? "true" : undefined),
    })
    : c));
  const Tag = as === "fieldset" ? "fieldset" : "div";
  const Label = as === "fieldset" ? "legend" : "label";
  return (
    <FieldContext.Provider value={ctx}>
      <Tag className={"field" + (error ? " has-error" : "") + (className ? ` ${className}` : "")}>
        <span className={"field-head" + (labelHidden ? " sr-only" : "")}>
          <span className="field-name">
            <Label className="field-label" htmlFor={as === "fieldset" ? undefined : id}>{label}</Label>
            {/* Beside the label, not in it: the control's name stays the label's words. */}
            {optional && <span className="field-opt">optional</span>}
          </span>
          {/* Always there, so "✓ Saved" can show on the first save too. */}
          <span className="field-aside">
            <SavedMark saved={saved} />
            {count && <span aria-hidden="true">{count}</span>}
          </span>
        </span>
        {kids}
        {error ? (
          <p id={helpId} className="field-error" role="alert">{error}</p>
        ) : help ? (
          <p id={helpId} className="field-help">{help}</p>
        ) : null}
      </Tag>
    </FieldContext.Provider>
  );
}
