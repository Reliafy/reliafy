import { forwardRef } from "react";
import { useField } from "./Field.jsx";
import useAutoGrow from "./useAutoGrow.js";
import { DateInput, TimeInput } from "./DateTimeInput.jsx";
import SharedSelect from "../Select.jsx";

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

// A form's drop-down: the shared Select (components/Select.jsx) written like a
// native <select>, with <option> children and an onChange that gets
// { target: { value, name } }, so form code reads the same as for TextInput.
export const Select = forwardRef(function Select({ className, onChange, name, ...props }, ref) {
  const change = onChange && ((value) => {
    const target = { value, name };
    onChange({ target, currentTarget: target });
  });
  return <SharedSelect ref={ref} {...props} onChange={change} className={cls("ctl ctl-sel", className)} />;
});

// A checkbox with its label beside it (.check in index.css): for a form field that waits
// for Save (a setting that applies at once is a Switch). The whole label is the target,
// 16 px box in the accent colour, the label in body text; inside a <Field as="fieldset">
// a list of them is one group under the field's label.
//   checked, onChange(event), label (node), disabled, name, className
export const Checkbox = forwardRef(function Checkbox({ label, className, ...props }, ref) {
  return (
    <label className={cls("check", className)}>
      <input ref={ref} type="checkbox" {...props} />
      <span className="check-label">{label}</span>
    </label>
  );
});
