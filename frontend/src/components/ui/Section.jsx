import { PlusIcon } from "../icons.jsx";

// A section of a panel or form (#UI): a 14 px heading, a count pill, and one
// small action at the right ("+ Add", "Change…"). Sections sit 16 px apart
// with a quiet line between them. `label` is the region's name (defaults to
// the title); `action` is {label, onClick, ariaLabel?, plus?: true, disabled?}.
export default function Section({ title, count = null, action = null, label, className = "", children, headingLevel = 3 }) {
  const H = `h${headingLevel}`;
  return (
    <section className={"psec" + (className ? ` ${className}` : "")} aria-label={label || title}>
      <div className="psec-head">
        <H className="psec-title">{title}</H>
        {count != null && <span className="psec-count">{count}</span>}
        {action && (
          <button type="button" className={"sm psec-act " + (action.plus ? "ghost" : "secondary")} disabled={action.disabled}
                  aria-label={action.ariaLabel} title={action.title}
                  onClick={(e) => { if (e.detail < 2) action.onClick(e); }}>
            {action.plus && <PlusIcon />}
            {action.label}
          </button>
        )}
      </div>
      {children}
    </section>
  );
}

// The dashed "+ Add …" row that ends a list.
export function AddRow({ children, onClick, disabled }) {
  return (
    <button type="button" className="add-row" disabled={disabled} onClick={(e) => { if (e.detail < 2) onClick(e); }}>
      <PlusIcon />
      {children}
    </button>
  );
}
