import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { searchLibrary } from "../api.js";
import { portalHost } from "../fullScreen.js";
import { listPlace } from "../listPlace.js";
import "../views/Predictions.css";
import { NO_PART_TYPE_HINT, fmtPerMillion } from "../predictions.js";

// The handbook sources a parts count draws on (backend/services/reliability_prediction.py):
// MIL-HDBK-217F for electronic parts, NSWC-11 (covariate models) for mechanical ones.
export const HANDBOOK_SOURCE = "mil-hdbk-217f-n2";
export const MECHANICAL_SOURCE = "nswc-11";
export const BOOKS = [
  { source: HANDBOOK_SOURCE, label: "MIL-HDBK-217F N2 · electronic parts", kind: "rate" },
  { source: MECHANICAL_SOURCE, label: "NSWC-11 · mechanical parts (with conditions)" },
];
const PAGE = 10;
const SECTION = /Section [\d.]+/;

// A search row's rate in words: a part stress type's base rate, or a parts-count type's
// generic rates (environment included) from the lowest to the highest environment.
export function rateMeta(r) {
  if (r.covariate) {
    const c = r.covariate;
    const f = c.modes?.length > 1 ? `${c.modes.length} parts` : `base × ${c.factors} factor${c.factors === 1 ? "" : "s"}`;
    return `Eq. ${c.equation} · ${f} · ${c.rate_unit === "per_million_hours" ? "per 10⁶ h" : c.rate_unit === "per_million_cycles" ? "per 10⁶ cycles" : "per 10⁶ operations"} · needs conditions`;
  }
  const g = r.generic_rates && Object.values(r.generic_rates);
  if (g && g.length) {
    const lo = Math.min(...g);
    const hi = Math.max(...g);
    return `λg ${fmtPerMillion(lo)}–${fmtPerMillion(hi)} per 10⁶ h by environment · parts count`;
  }
  return `λb ${fmtPerMillion((r.mean || 0) * 1e6)} per 10⁶ h`;
}

// Choose a handbook part type for one line of a parts list: type to search
// the reliability data library's handbook records (MIL-HDBK-217F base failure
// rates and its parts-count generic rates for electronic parts; NSWC-11's
// covariate models for mechanical ones, each handbook a group), pick one. ``value`` is the chosen
// record ({ id, name, ... }) or null. ``onUseRate``, when given, offers "Give a
// rate of your own" for a part the handbook has no type for (a battery).
export default function PartTypePicker({ value, onChange, onUseRate = null, label = "Handbook part type", placeholder = "Search part types…" }) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [rows, setRows] = useState([]);
  const [total, setTotal] = useState(0);
  const [busy, setBusy] = useState(false);
  const [active, setActive] = useState(0);
  const [error, setError] = useState(null);
  const box = useRef(null);
  const input = useRef(null);
  const list = useRef(null);
  const [place, setPlace] = useState(null);
  const placeList = useCallback(() => {
    const r = input.current?.getBoundingClientRect();
    if (r) setPlace(listPlace(r, { width: window.innerWidth, height: window.innerHeight }));
  }, []);
  // Placed as it opens, and again as the page, the table or the window moves under it.
  useLayoutEffect(() => {
    if (!open) return undefined;
    placeList();
    const again = (e) => { if (!list.current?.contains(e.target)) placeList(); };
    window.addEventListener("scroll", again, true);
    window.addEventListener("resize", placeList);
    return () => {
      window.removeEventListener("scroll", again, true);
      window.removeEventListener("resize", placeList);
    };
  }, [open, placeList]);
  const id = useId();

  // The search, a moment after typing stops (at once for the opening list).
  useEffect(() => {
    if (!open) return undefined;
    const q = query.trim();
    let live = true;
    setBusy(true);
    const t = setTimeout(() => {
      // Both handbooks in one search, each its own group in the list (electronic first, then mechanical).
      searchLibrary({ q, source: BOOKS.map((b) => b.source).join(","), pageSize: PAGE })
        .then((d) => {
          if (!live) return;
          const all = (d.results || []).map((r) => ({ ...r, book: r.id.split(":")[0] }));
          setRows(BOOKS.flatMap((b) => all.filter((r) => r.book === b.source)));
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
      if (box.current && !box.current.contains(e.target) && !list.current?.contains(e.target)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  useEffect(() => {
    if (open && input.current) input.current.focus();
  }, [open]);

  const pick = (r) => {
    onChange({
      id: r.id, name: r.name, label: r.label, mean: r.mean, quality_factor_range: r.quality_factor_range || null,
      quality_factor_default: r.quality_factor_default ?? null, quality_factors: r.quality_factors || null,
      generic_rates: r.generic_rates || null,
      ...(r.covariate ? { kind: r.kind, covariate: { rate_unit: r.covariate.rate_unit, per_cycle: r.covariate.per_cycle, equation: r.covariate.equation } } : {}),
    });
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
      {open && place && createPortal(
        <ul className="ptp-list" id={listId} role="listbox" aria-label={`${label} matches`} ref={list} style={place}>
          {error && <li className="ptp-note" role="presentation">{error}</li>}
          {!error && !rows.length && (
            <li className="ptp-note" role="presentation">
              {busy ? "Searching…" : `No handbook part type matches. Try another word: microprocessor, motor, capacitor, connector; bearing, seal, pump, spring, gear. ${NO_PART_TYPE_HINT}`}
            </li>
          )}
          {rows.map((r, i) => [
            (i === 0 || rows[i - 1].book !== r.book) && (
              <li key={`h-${r.book}`} className="ptp-group" role="presentation">{BOOKS.find((b) => b.source === r.book)?.label || r.book}</li>
            ),
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
                {rateMeta(r)}{SECTION.test(r.citation || "") ? ` · ${SECTION.exec(r.citation)[0]}` : ""}
              </span>
            </li>,
          ])}
          {total > rows.length && (
            <li className="ptp-note" role="presentation">{total - rows.length} more match: add a word to narrow it.</li>
          )}
          {onUseRate && (
            <li className="ptp-note" role="presentation">
              <button type="button" className="link" onMouseDown={(e) => {
                e.preventDefault();
                setOpen(false);
                onUseRate();
              }}>
                Give a rate of your own instead
              </button>
              {" "}(a part the handbook doesn’t have, such as a battery)
            </li>
          )}
        </ul>,
        portalHost(),
      )}
    </div>
  );
}
