import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { portalHost } from "../fullScreen.js";
import { guidesByCategory, getGuide } from "../guides.js";
import { filterGuideGroups } from "../guideFilter.js";
import { getEntry } from "../reference.js";
import { publicUrl } from "../firebase.js";
import GuideBody from "./GuideBody.jsx";
import ReferenceEntry from "./ReferenceEntry.jsx";
import ListSearch from "./ListSearch.jsx";

// Open the Help drawer at a specific guide from anywhere (contextual
// "How do I…?" links on features). No shared store needed — a window event.
export function openGuide(slug) {
  window.dispatchEvent(new CustomEvent("reliafy:help", { detail: { guide: slug } }));
}

// The same drawer, opened at a model-reference entry — used by the "?" beside
// the distribution and life-stress pickers, so "what actually is expo_weibull?"
// gets answered without leaving the fit you're setting up.
export function openReference(entryId) {
  window.dispatchEvent(new CustomEvent("reliafy:help", { detail: { reference: entryId } }));
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
// contextual "How do I…" links on complex features), or to a reference entry.
// The list has a filter box (guideFilter.js): what's typed stays while a guide
// is read, so "← All guides" comes back to the same short list; opening the
// drawer afresh clears it.
export default function HelpButton({ openSlug = null }) {
  const [open, setOpen] = useState(false);
  const [slug, setSlug] = useState(openSlug);
  const [refId, setRefId] = useState(null);
  const [query, setQuery] = useState("");
  const guide = slug ? getGuide(slug) : null;
  const entry = refId ? getEntry(refId) : null;
  const listed = !guide && !entry;
  const groups = listed ? filterGuideGroups(guidesByCategory(), query) : [];

  useEffect(() => {
    const onHelp = (e) => {
      const d = e.detail;
      // Older callers passed a bare slug string; keep that working.
      const next = typeof d === "string" ? { guide: d } : d || {};
      setSlug(next.guide || null);
      setRefId(next.reference || null);
      setQuery("");
      setOpen(true);
    };
    window.addEventListener("reliafy:help", onHelp);
    return () => window.removeEventListener("reliafy:help", onHelp);
  }, []);

  // Escape closes the drawer, as it does a modal (#302).
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  const back = () => { setSlug(null); setRefId(null); };

  return (
    <>
      <button className="nav-help-btn" title="Guides & help" aria-label="Help"
              onClick={() => { setSlug(openSlug); setRefId(null); setQuery(""); setOpen(true); }}>
        <QIcon />
      </button>
      {open && createPortal(
        <>
          <div className="help-drawer-backdrop" onClick={() => setOpen(false)} />
          <aside className="help-drawer" role="dialog" aria-label="Help">
            <div className="help-drawer-head">
              {guide || entry ? (
                <button className="secondary" onClick={back}>← All guides</button>
              ) : (
                <strong>Guides</strong>
              )}
              <button className="modal-close" onClick={() => setOpen(false)} aria-label="Close">×</button>
            </div>
            {/* Above the scrolling list, so it stays in reach. */}
            {listed && (
              <div className="tablebar help-filter">
                <ListSearch value={query} onChange={setQuery} placeholder="Filter guides…" />
              </div>
            )}
            <div className="help-drawer-body">
              {entry ? (
                <>
                  <ReferenceEntry entry={entry} />
                  <p style={{ marginTop: 16 }}>
                    <a className="guide-full-link"
                       href={publicUrl(`/reference/${entry.family.id}#${entry.id}`)}
                       target="_blank" rel="noreferrer">
                      All {entry.family.title.toLowerCase()} ↗
                    </a>
                  </p>
                </>
              ) : guide ? (
                <>
                  <GuideBody guide={guide} compact />
                  <p style={{ marginTop: 16 }}>
                    <a className="guide-full-link" href={publicUrl(`/guides/${guide.slug}`)} target="_blank" rel="noreferrer">
                      Open the full guide ↗
                    </a>
                  </p>
                </>
              ) : groups.length === 0 ? (
                <p className="help-none" role="status">
                  No guide matches “{query.trim()}”.{" "}
                  <button type="button" className="link" onClick={() => setQuery("")}>Show all guides</button>
                </p>
              ) : (
                // Same grouping as the public /guides index, so the two read
                // the same way round.
                groups.map((group) => (
                  <div className="help-group" key={group.category}>
                    <h3 className="help-group-h">{group.category}</h3>
                    <ul className="help-list">
                      {group.items.map((g) => (
                        <li key={g.slug}>
                          <button onClick={() => setSlug(g.slug)}>
                            {g.title}
                            <span className="help-item-task">{g.task}</span>
                          </button>
                        </li>
                      ))}
                    </ul>
                  </div>
                ))
              )}
            </div>
          </aside>
        </>,
        portalHost()
      )}
    </>
  );
}
