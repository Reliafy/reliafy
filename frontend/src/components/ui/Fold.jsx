import { forwardRef, useId, useState } from "react";
import "./Fold.css";

// A fold-out part of a form or panel (#UI): one quiet line, "› Title", that opens what's under it.
// Folded with something set inside, the line says what (`summary`, one short line), so nothing is
// hidden silently; folded with nothing set it's the title alone. Guideline:
// docs/design-system/components/Fold.md.
//
//   title      the words on the line ("Cost", "More scheduling options")
//   summary    what's set inside, in a few words, shown while folded ("$40 each time"); "" for none
//   open / onToggle   controlled; else `defaultOpen`
//   id         on the fold, for a link or a scroll to it
export const Fold = forwardRef(function Fold({ title, summary = "", open: controlled, onToggle, defaultOpen = false, id, className = "", children }, ref) {
  const [own, setOwn] = useState(defaultOpen);
  const open = controlled ?? own;
  const bodyId = useId();
  const toggle = () => (onToggle ? onToggle(!open) : setOwn((o) => !o));
  return (
    <div ref={ref} id={id} className={"fold" + (open ? " is-open" : "") + (className ? ` ${className}` : "")}>
      <button type="button" className="fold-head" aria-expanded={open} aria-controls={bodyId} onClick={toggle}>
        <span className="fold-mark" aria-hidden="true">›</span>
        <span className="fold-title">{title}</span>
        {!open && summary ? <span className="fold-sum">{summary}</span> : null}
      </button>
      {open && <div id={bodyId} className="fold-body" role="region" aria-label={title}>{children}</div>}
    </div>
  );
});

export default Fold;
