import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { guides, getGuide } from "../guides.js";
import { publicUrl } from "../firebase.js";
import GuideBody from "./GuideBody.jsx";

// Open the Help drawer at a specific guide from anywhere (contextual
// "How do I…?" links on features). No shared store needed — a window event.
export function openGuide(slug) {
  window.dispatchEvent(new CustomEvent("reliafy:help", { detail: slug }));
}

const QIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"
       strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <circle cx="12" cy="12" r="9" />
    <path d="M9.1 9.2a3 3 0 0 1 5.8 1c0 2-3 2.5-3 4" />
    <path d="M12 17h.01" />
  </svg>
);

// A "?" in the top bar that opens a Help drawer of the product guides, viewable
// in-app next to the UI. Optionally opened straight to a specific guide (used by
// contextual "How do I…" links on complex features).
export default function HelpButton({ openSlug = null }) {
  const [open, setOpen] = useState(false);
  const [slug, setSlug] = useState(openSlug);
  const guide = slug ? getGuide(slug) : null;

  useEffect(() => {
    const onHelp = (e) => { setSlug(e.detail || null); setOpen(true); };
    window.addEventListener("reliafy:help", onHelp);
    return () => window.removeEventListener("reliafy:help", onHelp);
  }, []);

  return (
    <>
      <button className="nav-help-btn" title="Guides & help" aria-label="Help"
              onClick={() => { setSlug(openSlug); setOpen(true); }}>
        <QIcon />
      </button>
      {open && createPortal(
        <>
          <div className="help-drawer-backdrop" onClick={() => setOpen(false)} />
          <aside className="help-drawer" role="dialog" aria-label="Help">
            <div className="help-drawer-head">
              {guide ? (
                <button className="secondary" onClick={() => setSlug(null)}>← All guides</button>
              ) : (
                <strong>Guides</strong>
              )}
              <button className="modal-close" onClick={() => setOpen(false)} aria-label="Close">×</button>
            </div>
            <div className="help-drawer-body">
              {guide ? (
                <>
                  <GuideBody guide={guide} compact />
                  <p style={{ marginTop: 16 }}>
                    <a className="guide-full-link" href={publicUrl(`/guides/${guide.slug}`)} target="_blank" rel="noreferrer">
                      Open the full guide ↗
                    </a>
                  </p>
                </>
              ) : (
                <ul className="help-list">
                  {guides.map((g) => (
                    <li key={g.slug}>
                      <button onClick={() => setSlug(g.slug)}>
                        {g.title}
                        <span className="help-item-task">{g.task}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </aside>
        </>,
        document.body
      )}
    </>
  );
}
