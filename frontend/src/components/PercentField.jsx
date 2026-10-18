// A percentage input (#2 of the 18 Oct UX review): shows "%", takes 95 for
// 95%, and asks "Did you mean 99%?" when a value of 1 or less looks like a
// fraction typed by habit. The form converts with percentFraction (or the
// check's .fraction) and runs only when percentsReady says so.
import { useId } from "react";
import { checkPercent, keepAsTyped } from "../percent.js";
import "./PercentField.css";

export default function PercentField({
  label,
  value,
  onChange,
  check = null,
  optional = false,
  fractionCheck = true,
  allowMax = false,
  className = "calc-t",
  hint = null,
  placeholder,
  disabled = false,
  title,
  ariaLabel,
  inputProps = {},
}) {
  const id = useId();
  const msgId = `${id}-msg`;
  const c = check || checkPercent(value, { optional, fractionCheck, allowMax });
  const showMsg = !disabled && (c.state === "error" || c.state === "confirm") && String(value ?? "").trim() !== "";
  return (
    <div className={`${className} pct-field`} title={title}>
      <label htmlFor={id}>{label}</label>
      <span className="pct-input">
        <input
          id={id}
          type="text"
          inputMode="decimal"
          autoComplete="off"
          value={value ?? ""}
          placeholder={placeholder}
          disabled={disabled}
          aria-label={ariaLabel}
          aria-invalid={showMsg || undefined}
          aria-describedby={showMsg ? msgId : undefined}
          onChange={(e) => onChange(e.target.value)}
          {...inputProps}
        />
        <span className="pct-suffix" aria-hidden="true">%</span>
      </span>
      {hint && !showMsg && <small>{hint}</small>}
      {showMsg && (
        <span id={msgId} className={`pct-msg${c.state === "error" ? " pct-msg-error" : ""}`} role="status" aria-live="polite">
          {c.message}
          {c.state === "confirm" && (
            <span className="pct-actions">
              {c.suggestion && (
                <button type="button" className="secondary pct-btn" onClick={() => onChange(c.suggestion)}>
                  Use {c.suggestion}%
                </button>
              )}
              <button type="button" className="ghost pct-btn" onClick={() => onChange(keepAsTyped(value))}>
                Keep {String(value).trim()}%
              </button>
            </span>
          )}
        </span>
      )}
    </div>
  );
}
