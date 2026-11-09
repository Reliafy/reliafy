import { useCallback, useRef, useState } from "react";
import useMenuDismiss from "./useMenuDismiss.js";

// Compact overflow ("…") menu for a page's secondary actions (share, delete).
// Closes like every menu (useMenuDismiss): outside click, Escape, or the mouse well clear. Children are the menu items (e.g. .ovm-item buttons).
// The items stay mounted while the menu is closed (only hidden), so an item
// that opens a dialog of its own (ShareButton) keeps it open after the click
// that closes the menu.
//
// With ``label`` it's a menu button instead ("+ New analysis ▾"): a page's
// main action when that action is one of several tools. ``triggerClass``
// replaces the "…" button's look (the Explorer's panel heading draws it as
// the tree pane's 30 × 30 icon buttons); ``disabled`` greys it, with
// ``title`` saying why.
export default function OverflowMenu({ children, label, ariaLabel, triggerClass = "secondary", disabled = false, title = "More actions" }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  const close = useCallback(() => setOpen(false), []);
  useMenuDismiss(open, close, ref);
  return (
    <div className="ovm" ref={ref}>
      {label ? (
        <button className="ovm-trigger ovm-label" aria-haspopup="menu" aria-expanded={open}
                aria-label={ariaLabel} onClick={() => setOpen((o) => !o)}>
          {label}
          <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2.2"
               strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="m6 9 6 6 6-6" /></svg>
        </button>
      ) : (
        <button
          type="button"
          className={`${triggerClass} ovm-trigger`}
          aria-label="More actions"
          aria-haspopup="menu"
          aria-expanded={open}
          title={title}
          disabled={disabled}
          onClick={() => setOpen((o) => !o)}
        >
          <svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor">
            <circle cx="5" cy="12" r="1.8" /><circle cx="12" cy="12" r="1.8" /><circle cx="19" cy="12" r="1.8" />
          </svg>
        </button>
      )}
      <div className="ovm-menu" hidden={!open} onClick={() => setOpen(false)}>
        {children}
      </div>
    </div>
  );
}
