import { useEffect, useRef, useState } from "react";

// Compact overflow ("…") menu for a page's secondary actions (share, delete).
// Closes on outside click. Children are the menu items (e.g. .ovm-item buttons).
export default function OverflowMenu({ children }) {
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
      {open && (
        <div className="ovm-menu" onClick={() => setOpen(false)}>
          {children}
        </div>
      )}
    </div>
  );
}
