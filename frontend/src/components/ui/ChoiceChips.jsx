import { useEffect, useRef } from "react";
import { chipPick, chipStep, chipTabStop } from "../../choiceChips.js";
import { useField } from "./Field.jsx";

// One choice from a few, as chips (#UI): the Decision dialog's tiles at a
// smaller size, the chosen one filled with a ✓ (so it isn't shown by colour
// alone). A radio group: ← → (and ↑ ↓) move and choose, Tab leaves. With
// `clearable`, choosing the chosen one again clears it.
//
//   options   [{value, label, title?}] (title: the chip's tooltip)
//   value     the chosen value ("" or null: none)
//   onChange  (value | "") on a choice
//   moveOnly  arrows move the focus only; Enter, Space or a click chooses (a
//             popover where each choice is saved at once)
//   autoFocus the chosen chip (else the first) takes the focus
export default function ChoiceChips({
  label, options, value, onChange, disabled = false, clearable = false, className = "", id, moveOnly = false, autoFocus = false, onKeyDown,
}) {
  const box = useRef(null);
  const field = useField();
  const at = chipTabStop(options, value);
  useEffect(() => {
    if (!autoFocus) return undefined;
    // A frame later: in a popover that is placed (and shown) after it mounts.
    const raf = requestAnimationFrame(() => box.current?.querySelectorAll("[role=radio]")[at]?.focus({ preventScroll: true }));
    return () => cancelAnimationFrame(raf);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const pick = (v) => { if (!disabled) onChange(chipPick(v, value, clearable)); };
  const keys = (e, i) => {
    const j = chipStep(i, e.key, options.length);
    if (j == null) {
      if (e.key === " " || e.key === "Enter") { e.preventDefault(); e.stopPropagation(); pick(options[i].value); return; }
      onKeyDown?.(e);
      return;
    }
    e.preventDefault();
    e.stopPropagation();
    box.current?.querySelectorAll("[role=radio]")[j]?.focus();
    if (!disabled && !moveOnly) onChange(options[j].value);
  };
  return (
    <div ref={box} id={id || field?.id} aria-describedby={field?.describedBy} className={"choice-chips" + (className ? ` ${className}` : "")} role="radiogroup" aria-label={label}
         aria-disabled={disabled || undefined}>
      {options.map((o, i) => {
        const on = o.value === value;
        return (
          <button key={o.value} type="button" role="radio" aria-checked={on} className={"choice-chip" + (on ? " on" : "")}
                  tabIndex={i === at ? 0 : -1} disabled={disabled}
                  title={o.title ? `${o.title}${on && clearable ? " (choose it again to clear it)" : ""}`
                    : on && clearable ? "Chosen: choose it again to clear it" : undefined}
                  onClick={() => pick(o.value)} onKeyDown={(e) => keys(e, i)}>
            {on && <span className="choice-tick" aria-hidden="true">✓</span>}
            {o.label}
          </button>
        );
      })}
    </div>
  );
}
