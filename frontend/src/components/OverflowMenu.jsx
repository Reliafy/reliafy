import { useEffect, useRef, useState } from "react";

// Compact overflow ("…") menu for a page's secondary actions (share, delete).
// Closes on outside click. Children are the menu items (e.g. .ovm-item buttons).
// The items stay mounted while the menu is closed (only hidden), so an item
// that opens a dialog of its own (ShareButton) keeps it open after the click
// that closes the menu.
//
// With ``label`` it's a menu button instead ("+ New analysis ▾"): a page's
// main action when that action is one of several tools.
export default function OverflowMenu({ children, label, ariaLabel }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return;
    const onDoc = (e) => { if (!ref.current?.contains(e.target)) setOpen(false); };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);
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
          className="secondary ovm-trigger"
          aria-label="More actions"
          title="More actions"
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
