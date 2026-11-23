import { forwardRef } from "react";
import InputGroup, { Addon } from "./InputGroup.jsx";
import { TextInput } from "./Controls.jsx";
import SharedSelect from "../Select.jsx";
import { useField } from "./Field.jsx";
import "./QuantityInput.css";

// A number and its unit as ONE control (#UI): one border, one focus ring, a number box sized to the
// numbers it takes (no browser spinners), and the unit inside the box, either fixed words (`suffix`)
// or a drop-down of units (`units`). Inside a <Field> the number takes the field's id, help and
// error; the unit drop-down gets its own id. The group itself is unnamed: the number and the unit
// carry the names, so a label finds one control, never the box round them. Guideline: docs/design-system/components/QuantityInput.md.
//
//   label       the number's accessible name ("Length", "Hours a day")
//   value, onChange(text)          the number as typed (a string; the caller parses it)
//   suffix      fixed unit words ("h a day", "flight hours")
//   units, unit, onUnitChange(v)   a choice of units: [{value, label}] or strings
//   unitLabel   the drop-down's accessible name (default "<label> unit")
//   chars       the number box's width in digits (default 6)
//   type        "number" (default: a spinbutton, no spinners shown) or "text" (allows "9,000")
//   min, max, step, inputMode, placeholder, disabled, invalid, id, className, title
export const QuantityInput = forwardRef(function QuantityInput({
  label, value, onChange, suffix = null, units = null, unit, onUnitChange, unitLabel, chars = 6, type = "number",
  min, max, step = "any", inputMode = "decimal", placeholder, disabled = false, invalid, id, className = "", title,
}, ref) {
  const field = useField();
  const opts = (units || []).map((u) => (typeof u === "string" ? { value: u, label: u } : u));
  return (
    <InputGroup className={"qty" + (disabled ? " is-disabled" : "") + (className ? ` ${className}` : "")}>
      <TextInput ref={ref} id={id} type={type} inputMode={inputMode} min={min} max={max} step={type === "number" ? step : undefined}
                 aria-label={label} placeholder={placeholder} disabled={disabled} title={title}
                 aria-invalid={invalid == null ? undefined : invalid ? "true" : undefined}
                 className="qty-num" style={{ "--qty-chars": chars }}
                 value={value ?? ""} onChange={(e) => onChange?.(e.target.value)} />
      {opts.length > 0 ? (
        <SharedSelect className="ctl ctl-sel sel-embedded qty-unit" ariaLabel={unitLabel || `${label} unit`} disabled={disabled}
                      id={field?.id ? `${field.id}-unit` : undefined} searchable={false}
                      value={unit ?? opts[0].value} options={opts} onChange={(v) => onUnitChange?.(v)} />
      ) : suffix != null && suffix !== "" ? <Addon>{suffix}</Addon> : null}
    </InputGroup>
  );
});

export default QuantityInput;
