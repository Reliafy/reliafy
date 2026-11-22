import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import Modal from "./Modal.jsx";
import "./GlobalSearch.css";
import { searchEverything } from "../api.js";
import { guides } from "../guides.js";
import { useAppConfig } from "../ConfigProvider.jsx";
import { useRoles } from "../RolesProvider.jsx";
import { useWorkspace } from "../WorkspaceProvider.jsx";
import {
  contextLine, featureHref, featureList, flatResults, highlight, mergeGroups, moveActive, searchFeatures, searchGuides,
} from "../globalSearch.js";

// One search for everything (globalSearch.js): a box in the top bar, and ⌘K / Ctrl-K from
// anywhere, open a search dialog over the page (the shared Modal: focus kept in, Escape closes
// and returns focus; full screen on a phone). Results come grouped by kind, best match first;
// ↑ ↓ move, Tab jumps a group, Enter opens. Records open where they live (a position in the
// Explorer on its own asset), pages and tabs on themselves, guides in the help drawer.
const SearchIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round"
       strokeLinejoin="round" aria-hidden="true">
    <circle cx="11" cy="11" r="7" />
    <path d="m20 20-3.5-3.5" />
  </svg>
);

const isMac = () => typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent || "");

export default function GlobalSearch() {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const onKey = (e) => {
      if ((e.metaKey || e.ctrlKey) && !e.altKey && !e.shiftKey && (e.key === "k" || e.key === "K")) {
        e.preventDefault();
        setOpen(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  const shortcut = isMac() ? "⌘K" : "Ctrl K";
  return (
    <>
      <button type="button" className="gsearch-trigger" onClick={() => setOpen(true)}
              aria-label="Search everything" aria-keyshortcuts="Meta+K Control+K" aria-haspopup="dialog"
              title={`Search everything (${shortcut})`}>
        <SearchIcon />
        <span className="gsearch-trigger-text">Search…</span>
        <kbd className="gsearch-kbd">{shortcut}</kbd>
      </button>
      {open && <SearchDialog onClose={() => setOpen(false)} />}
    </>
  );
}

function SearchDialog({ onClose }) {
  const navigate = useNavigate();
  const { pathname, search } = useLocation();
  const config = useAppConfig();
  const { live, has } = useRoles();
  const { activeTeam } = useWorkspace();
  const [q, setQ] = useState("");
  const [server, setServer] = useState({ q: "", groups: [], error: null });
  const [active, setActive] = useState(0);
  const listId = useId();
  const listRef = useRef(null);
  const inputRef = useRef(null);
  // Into the box once the dialog has noted who opened it (Modal's effect runs first), so
  // closing gives the focus back to the opener: autoFocus would take it before that.
  useEffect(() => inputRef.current?.focus(), []);

  const features = useMemo(() => featureList({ live, has, billing: !!config.billing, team: !!activeTeam }),
    [live, has, config.billing, activeTeam]);

  useEffect(() => {
    const words = q.trim();
    if (!words) return undefined;
    const ctl = new AbortController();
    // A short wait so each keystroke doesn't ask the server.
    const t = setTimeout(() => {
      searchEverything(words, { signal: ctl.signal })
        .then((d) => setServer({ q: words, groups: d.groups || [], error: null }))
        .catch((e) => { if (e?.name !== "AbortError") setServer({ q: words, groups: [], error: e }); });
    }, 150);
    return () => { clearTimeout(t); ctl.abort(); };
  }, [q]);

  const words = q.trim();
  const waiting = !!words && server.q !== words;
  const groups = useMemo(() => {
    if (!words) return [];
    return mergeGroups(server.q === words ? server.groups : [], searchFeatures(features, words), searchGuides(guides, words));
  }, [words, server, features]);
  const flat = useMemo(() => flatResults(groups), [groups]);
  useEffect(() => setActive(0), [words]);
  const shown = Math.min(active, Math.max(flat.length - 1, 0));

  useEffect(() => {
    listRef.current?.querySelector(`[data-index="${shown}"]`)?.scrollIntoView?.({ block: "nearest" });
  }, [shown]);

  const openResult = useCallback((r) => {
    onClose();
    if (r.kind === "guide") {
      window.dispatchEvent(new CustomEvent("reliafy:help", { detail: { guide: r.slug } }));
      return;
    }
    navigate(r.kind === "feature" ? featureHref(r, pathname, search) : r.path);
  }, [navigate, onClose, pathname, search]);

  const onKeyDown = (e) => {
    if (e.key === "Enter") {
      if (flat[shown]) {
        e.preventDefault();
        openResult(flat[shown].result);
      }
      return;
    }
    const next = moveActive(groups, shown, e.key, e.shiftKey);
    if (next != null) {
      e.preventDefault();
      setActive(next);
    }
  };

  const optionId = (i) => `${listId}-o${i}`;
  return (
    <Modal title="Search" onClose={onClose} className="gsearch-modal" overlayClassName="gsearch-overlay">
      <div className="search live gsearch-box">
        <SearchIcon />
        <input
          ref={inputRef}
          type="search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder={has.maintenance ? "Assets, parts, models, pages, guides…" : "Data, models, diagrams, pages, guides…"}
          aria-label="Search everything"
          role="combobox"
          aria-expanded={flat.length > 0}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={flat[shown] ? optionId(shown) : undefined}
          autoComplete="off"
          spellCheck={false}
        />
      </div>
      <div className="gsearch-results" ref={listRef}>
        {!words && (
          <p className="gsearch-hint">
            {has.maintenance ? "Type a name, tag, serial or part number" : "Type a name"}, or what you want to do
            (“test planning”, “availability”).
            Use ↑ ↓ to move, Tab to jump a group, Enter to open.
          </p>
        )}
        {server.error && server.q === words && (
          <p className="gsearch-hint" role="status">
            Couldn't search your records just now ({server.error.message || "no answer"}). Pages and guides are still listed.
          </p>
        )}
        {words && !waiting && !flat.length && !server.error && (
          <p className="gsearch-hint" role="status">Nothing matches “{words}”. Try fewer words, or another spelling.</p>
        )}
        <div id={listId} role="listbox" aria-label="Search results">
          {groups.map((g, gi) => (
            <div key={g.kind} role="group" aria-labelledby={`${listId}-g${gi}`} className="gsearch-group">
              <div className="gsearch-group-head" id={`${listId}-g${gi}`}>
                <span>{g.label}</span>
                {g.total > g.results.length && <span className="gsearch-count">first {g.results.length} of {g.total}</span>}
              </div>
              {g.results.map((r) => {
                const i = flat.findIndex((x) => x.result === r);
                return (
                  <div key={`${r.kind}:${r.id}`} id={optionId(i)} data-index={i} role="option" aria-selected={i === shown}
                       className={"gsearch-option" + (i === shown ? " active" : "")}
                       onMouseMove={() => i !== shown && setActive(i)}
                       onMouseDown={(e) => e.preventDefault()}
                       onClick={() => openResult(r)}>
                    <div className="gsearch-name"><Marked text={r.name} q={words} /></div>
                    <div className="gsearch-context"><Marked text={contextLine(r)} q={words} /></div>
                  </div>
                );
              })}
            </div>
          ))}
        </div>
        {waiting && <p className="gsearch-hint gsearch-waiting" aria-live="polite">Searching your records…</p>}
      </div>
    </Modal>
  );
}

function Marked({ text, q }) {
  return highlight(text, q).map((p, i) => (p.hit ? <mark key={i}>{p.text}</mark> : <span key={i}>{p.text}</span>));
}
