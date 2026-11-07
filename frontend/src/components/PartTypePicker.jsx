import { useEffect, useId, useRef, useState } from "react";
import { searchLibrary } from "../api.js";
import { fmtPerMillion } from "../predictions.js";

// The handbook source a parts count draws on (backend/services/reliability_prediction.py).
export const HANDBOOK_SOURCE = "mil-hdbk-217f-n2";
const PAGE = 8;
const SECTION = /Section [\d.]+/;

// Choose a handbook part type for one line of a parts list: type to search
// the reliability data library's handbook records (MIL-HDBK-217F base failure
// rates), pick one. ``value`` is the chosen record ({ id, name, ... }) or null.
export default function PartTypePicker({ value, onChange, label = "Handbook part type", placeholder = "Search part types…" }) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [rows, setRows] = useState([]);
  const [total, setTotal] = useState(0);
  const [busy, setBusy] = useState(false);
  const [active, setActive] = useState(0);
  const [error, setError] = useState(null);
  const box = useRef(null);
  const input = useRef(null);
  const id = useId();

  // The search, a moment after typing stops (at once for the opening list).
  useEffect(() => {
    if (!open) return undefined;
    const q = query.trim();
    let live = true;
    setBusy(true);
    const t = setTimeout(() => {
      searchLibrary({ q, source: HANDBOOK_SOURCE, kind: "rate", pageSize: PAGE })
        .then((d) => {
          if (!live) return;
          setRows(d.results || []);
          setTotal(d.total || 0);
          setActive(0);
          setError(null);
        })
        .catch((e) => live && setError(e.message))
        .finally(() => live && setBusy(false));
    }, q ? 180 : 0);
    return () => {
      live = false;
      clearTimeout(t);
    };
  }, [query, open]);

  // A click outside closes the list.
  useEffect(() => {
    if (!open) return undefined;
    const onDown = (e) => {
      if (box.current && !box.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  useEffect(() => {
    if (open && input.current) input.current.focus();
  }, [open]);

  const pick = (r) => {
    onChange({ id: r.id, name: r.name, label: r.label, mean: r.mean, quality_factor_range: r.quality_factor_range || null });
    setOpen(false);
    setQuery("");
  };
  const onKey = (e) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      if (!open) setOpen(true);
      else setActive((a) => Math.min(a + 1, Math.max(rows.length - 1, 0)));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => Math.max(a - 1, 0));
    } else if (e.key === "Enter") {
      if (open && rows[active]) {
        e.preventDefault();
        pick(rows[active]);
      }
    } else if (e.key === "Escape" && open) {
      e.preventDefault();
      setOpen(false);
    }
  };

  if (value && !open) {
    return (
      <div className="ptp ptp-chosen">
        <button type="button" className="ptp-name" title={`${value.name} (click to change)`} onClick={() => setOpen(true)}
                aria-label={`${label}: ${value.name}. Change it`}>
          {value.name}
        </button>
        <button type="button" className="ptp-clear" aria-label="Clear the part type" title="Clear"
                onClick={() => onChange(null)}>×</button>
      </div>
    );
  }
  const listId = `${id}-list`;
  return (
    <div className="ptp" ref={box}>
      <input
        ref={input}
        type="text"
        value={query}
        placeholder={value ? value.name : placeholder}
        aria-label={label}
        role="combobox"
        aria-expanded={open}
        aria-controls={listId}
        aria-autocomplete="list"
        autoComplete="off"
        onChange={(e) => {
          setQuery(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={onKey}
      />
      {open && (
        <ul className="ptp-list" id={listId} role="listbox" aria-label={`${label} matches`}>
          {error && <li className="ptp-note" role="presentation">{error}</li>}
          {!error && !rows.length && (
            <li className="ptp-note" role="presentation">
              {busy ? "Searching…" : "No handbook part type matches. Try another word: capacitor, resistor, connector, diode, transistor, switch, relay."}
            </li>
          )}
          {rows.map((r, i) => (
            <li
              key={r.id}
              role="option"
              aria-selected={i === active}
              className={"ptp-item" + (i === active ? " is-active" : "")}
              onMouseDown={(e) => {
                e.preventDefault();
                pick(r);
              }}
              onMouseEnter={() => setActive(i)}
            >
              <span className="ptp-item-name">{r.name}</span>
              <span className="ptp-item-meta">
                λb {fmtPerMillion((r.mean || 0) * 1e6)} per 10⁶ h{SECTION.test(r.citation || "") ? ` · ${SECTION.exec(r.citation)[0]}` : ""}
              </span>
            </li>
          ))}
          {total > rows.length && (
            <li className="ptp-note" role="presentation">{total - rows.length} more match: add a word to narrow it.</li>
          )}
        </ul>
      )}
    </div>
  );
}
