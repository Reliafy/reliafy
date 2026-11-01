import { forwardRef, useId, useState } from "react";
import { PlusIcon } from "../icons.jsx";

// A section of a panel or form (#UI): a 14 px heading, a count pill, and one
// small action at the right ("+ Add", "Change…"). Sections sit 16 px apart
// with a quiet line between them. `label` is the region's name (defaults to
// the title); `action` is {label, onClick, ariaLabel?, plus?: true, disabled?}.
// `tip`: a few words of guidance behind a small "?" by the heading (shown on
// press, so it works on a phone and from the keyboard), kept out of the way.
export default function Section({ title, count = null, action = null, label, className = "", children, headingLevel = 3, tip = null }) {
  const H = `h${headingLevel}`;
  const [tipOpen, setTipOpen] = useState(false);
  const tipId = useId();
  return (
    <section className={"psec" + (className ? ` ${className}` : "")} aria-label={label || title}>
      <div className="psec-head">
        <H className="psec-title">{title}</H>
        {count != null && <span className="psec-count">{count}</span>}
        {tip && (
          <button type="button" className="ghost sm psec-tip" aria-expanded={tipOpen} aria-controls={tipId}
                  aria-label={`About ${String(title).toLowerCase()}`} title={tip} onClick={() => setTipOpen((o) => !o)}>
            ?
          </button>
        )}
        {action && (
          <button type="button" className={"sm psec-act " + (action.plus ? "ghost" : "secondary")} disabled={action.disabled}
                  aria-label={action.ariaLabel} title={action.title}
                  onClick={(e) => { if (e.detail < 2) action.onClick(e); }}>
            {action.plus && <PlusIcon />}
            {action.label}
          </button>
        )}
      </div>
      {tip && tipOpen && <p id={tipId} className="field-help psec-tipText">{tip}</p>}
      {children}
    </section>
  );
}

// The dashed "+ Add …" row that ends a list.
export const AddRow = forwardRef(function AddRow({ children, onClick, disabled }, ref) {
  return (
    <button ref={ref} type="button" className="add-row" disabled={disabled} onClick={(e) => { if (e.detail < 2) onClick(e); }}>
      <PlusIcon />
      {children}
    </button>
  );
});
