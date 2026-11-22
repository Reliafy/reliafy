import { forwardRef, useEffect, useRef, useState } from "react";
import { clockText, dayText, outOfRange, parseClockText, parseDayText } from "../../dateFields.js";
import { useField } from "./Field.jsx";

// The app's date and time fields (#UI), in place of <input type="date"> and <input type="time">:
// a browser's own fields follow its language ("11/22/2026", "04:00 PM" in an English (US)
// browser); these show "22 Nov 2026" and "16:00" everywhere (dates.js). They take and hand back
// the same ISO values as the browser's ("2026-11-22", "16:00"), and onChange gets an event-like
// {target: {value}}, so one can stand in for the other. Text left that isn't a day (or a time)
// hands back "", as the browser's do. A date field's calendar button opens the browser's own
// picker. Inside a <Field> they take its id, help and error wiring.
//
//   value, onChange(e), min, max (ISO days), disabled, readOnly, required, autoFocus, id,
//   aria-label, className (on the text box), onBlur, onKeyDown
//   picker   false: no calendar button (a table cell's editor, which closes when it loses focus)

const wire = (field, props) => ({
  id: props.id || field?.id,
  "aria-describedby": props["aria-describedby"] || field?.describedBy,
  "aria-invalid": props["aria-invalid"] ?? (field?.invalid ? "true" : undefined),
});
const event = (value) => ({ target: { value }, currentTarget: { value } });

// The text box both fields share: what's typed stays as typed until it's left, then it reads
// as the value ("8" becomes "08:00"); a value set from outside replaces it.
function useTyped(value, show, parse, onChange) {
  const [text, setText] = useState(() => show(value));
  const sent = useRef(value || "");
  useEffect(() => {
    if ((value || "") !== sent.current) { sent.current = value || ""; setText(show(value)); }
  }, [value]); // eslint-disable-line react-hooks/exhaustive-deps
  // Half-typed text ("22/1") hands nothing back until it's left: a caller that puts a default in
  // for "" would otherwise replace the text mid-word.
  const type = (t, leaving = false) => {
    setText(t);
    const v = parse(t, leaving) || "";
    if (!v && t.trim() && !leaving) return v;
    if (v !== sent.current) { sent.current = v; onChange?.(event(v)); }
    return v;
  };
  const leave = () => { const v = type(text, true); if (v) setText(show(v)); };
  return { text, type, leave, bad: !!text.trim() && !parse(text, true) };
}

export const DateInput = forwardRef(function DateInput({
  value, onChange, min, max, className, disabled, readOnly, onBlur, picker: withPicker = true, ...props
}, ref) {
  const field = useField();
  const picker = useRef(null);
  const year = (value || "").slice(0, 4) || String(new Date().getFullYear());
  const { text, type, leave, bad } = useTyped(value, dayText, (t, loose) => parseDayText(t, { loose, year }), onChange);
  const w = wire(field, props);
  const invalid = w["aria-invalid"] || (bad || outOfRange(value, min, max) ? "true" : undefined);
  const open = () => {
    const el = picker.current;
    if (!el) return;
    try { el.showPicker(); } catch { el.focus(); el.click(); }
  };
  return (
    <span className={"ctl-group dti" + (disabled ? " is-disabled" : "")}>
      <input ref={ref} type="text" inputMode="text" autoComplete="off" spellCheck={false} placeholder="dd/mm/yyyy"
             {...props} {...w} aria-invalid={invalid} className={"ctl dti-text" + (className ? ` ${className}` : "")}
             value={text} disabled={disabled} readOnly={readOnly}
             onChange={(e) => type(e.target.value)} onBlur={(e) => { leave(); onBlur?.(e); }} />
      {withPicker && <>
      <button type="button" className="ghost sm dti-btn" tabIndex={-1} disabled={disabled || readOnly} onClick={open}
              aria-label="Pick from a calendar" title="Pick from a calendar">
        <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.7"
             strokeLinecap="round" strokeLinejoin="round">
          <rect x="3.5" y="5" width="17" height="15" rx="2" /><path d="M3.5 10h17M8 3v4M16 3v4" />
        </svg>
      </button>
      {/* The browser's own picker, out of sight: what it picks comes back as an ISO day. */}
      <input ref={picker} type="date" className="dti-native" tabIndex={-1} aria-hidden="true" value={value || ""} min={min} max={max}
             disabled={disabled || readOnly} onChange={(e) => onChange?.(event(e.target.value))} />
      </>}
    </span>
  );
});

export const TimeInput = forwardRef(function TimeInput({ value, onChange, className, onBlur, ...props }, ref) {
  const field = useField();
  const { text, type, leave, bad } = useTyped(value, clockText, (t) => parseClockText(t), onChange);
  const w = wire(field, props);
  return (
    <input ref={ref} type="text" inputMode="numeric" autoComplete="off" spellCheck={false} placeholder="hh:mm"
           {...props} {...w} aria-invalid={w["aria-invalid"] || (bad ? "true" : undefined)}
           className={"ctl dti-time" + (className ? ` ${className}` : "")}
           value={text} onChange={(e) => type(e.target.value)} onBlur={(e) => { leave(); onBlur?.(e); }} />
  );
});

// A day and a clock time together, for a "YYYY-MM-DDTHH:MM" value (in place of
// <input type="datetime-local">).
export function DateTimeInput({ value, onChange, disabled, required, "aria-label": label = "When", ...props }) {
  const [day, setDay] = useState((value || "").slice(0, 10));
  const [time, setTime] = useState((value || "").slice(11, 16));
  useEffect(() => {
    if ((value || "") !== (day && time ? `${day}T${time}` : "")) { setDay((value || "").slice(0, 10)); setTime((value || "").slice(11, 16)); }
  }, [value]); // eslint-disable-line react-hooks/exhaustive-deps
  const put = (d, t) => { setDay(d); setTime(t); onChange?.(event(d && t ? `${d}T${t}` : "")); };
  return (
    <span className="dti-pair" role="group" aria-label={label}>
      <DateInput {...props} value={day} disabled={disabled} required={required} aria-label={`${label}: day`}
                 onChange={(e) => put(e.target.value, time)} />
      <TimeInput value={time} disabled={disabled} required={required} aria-label={`${label}: time`}
                 onChange={(e) => put(day, e.target.value)} />
    </span>
  );
}
