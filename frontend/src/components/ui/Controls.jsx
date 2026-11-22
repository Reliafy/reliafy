import { forwardRef } from "react";
import { useField } from "./Field.jsx";
import useAutoGrow from "./useAutoGrow.js";
import { DateInput, TimeInput } from "./DateTimeInput.jsx";

// The app's text controls (#UI): one look for every input, textarea and
// select (.ctl in index.css): white, a 1 px line, 34 px tall, 14 px text
// (16 px on a phone, so iOS doesn't zoom), the accent ring on focus, red on
// an error. Inside a <Field> they take its id, help and error wiring.
const wire = (field, props) => ({
  id: props.id || field?.id,
  "aria-describedby": props["aria-describedby"] || field?.describedBy,
  "aria-invalid": props["aria-invalid"] ?? (field?.invalid ? "true" : undefined),
});
const cls = (base, className) => base + (className ? ` ${className}` : "");

export const TextInput = forwardRef(function TextInput({ className, ...props }, ref) {
  const field = useField();
  // A date or a time: the shared fields, day first and 24-hour whatever the browser's language.
  if (props.type === "date") return <DateInput ref={ref} {...props} type={undefined} className={className} />;
  if (props.type === "time") return <TimeInput ref={ref} {...props} type={undefined} className={className} />;
  return <input ref={ref} type="text" {...props} {...wire(field, props)} className={cls("ctl", className)} />;
});

// Starts at one line and grows with its text; no resize handle.
export const TextArea = forwardRef(function TextArea({ className, rows = 1, value, ...props }, ref) {
  const field = useField();
  const grow = useAutoGrow(value, ref);
  return <textarea ref={grow} rows={rows} value={value} {...props} {...wire(field, props)} className={cls("ctl ctl-area", className)} />;
});

export const Select = forwardRef(function Select({ className, children, ...props }, ref) {
  const field = useField();
  return <select ref={ref} {...props} {...wire(field, props)} className={cls("ctl", className)}>{children}</select>;
});

// A checkbox with its label beside it (.check in index.css): for a form field that waits
// for Save (a setting that applies at once is a Switch). The whole label is the target,
// 16 px box in the accent colour, the label in body text; inside a <Field as="fieldset">
// a list of them is one group under the field's label.
// With no label (a row-select box in a table) it renders the box alone (.check-bare):
// no row padding, named by aria-label, and a 40 px touch target on a phone that doesn't
// change the row's height.
//   checked, onChange(event), label (node), disabled, name, className, aria-label,
//   title and style (on the whole row)
export const Checkbox = forwardRef(function Checkbox({ label, className, ...props }, ref) {
  return <Check ref={ref} type="checkbox" label={label} className={className} {...props} />;
});

// One choice of several, with its label beside it: the same .check row as Checkbox, a
// native radio (so ← → move within its `name` group). For options that carry long text or
// a control of their own; short labels are ChoiceChips (a saved value) or a
// SegmentedControl (a view).
//   checked, onChange(event), name, value, label (node), disabled, className
export const Radio = forwardRef(function Radio({ label, className, ...props }, ref) {
  return <Check ref={ref} type="radio" label={label} className={className} {...props} />;
});

// title and style go on the label (the whole row).
const Check = forwardRef(function Check({ type, label, className, title, style, ...props }, ref) {
  const bare = label == null || label === false;
  return (
    <label className={cls(bare ? "check check-bare" : "check", className)} title={title} style={style}>
      <input ref={ref} {...props} type={type} />
      {!bare && <span className="check-label">{label}</span>}
    </label>
  );
});
