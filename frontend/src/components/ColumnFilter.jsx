import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { portalHost } from "../fullScreen.js";
import { placeMenu } from "../menuPlace.js";
import "./ColumnFilter.css";
import { Checkbox } from "./ui/Controls.jsx";

// A tree-table column's filter (docs/design-system/components/ColumnFilter.md): a small funnel in
// the column's header that opens a list of the values in that column, each with how many rows
// have it; ticking values keeps only the rows with one of them. The button is filled (accent) while
// the column filters, and its name says how many values are ticked. On a phone (no column
// headers) one "Filter" button holds every column's values, a section each.
//
//   label     the column's name ("Kind"), or "Filter" for the phone's one button
//   facets    [{id, label, values: [{value, label, count}]}]: a column may have more than one
//             (Interval: its unit, then the interval itself); a heading each when there are two
//   chosen    {facet id: [values ticked]}
//   onChange(facetId, values)    onClear()  untick every value here
//   wide      the phone's button: its label shown, not only the funnel
export default function ColumnFilter({ label, facets, chosen = {}, onChange, onClear, wide = false }) {
  const [at, setAt] = useState(null);
  const btn = useRef(null);
  const pop = useRef(null);
  const uid = useId();
  const ticked = facets.reduce((n, f) => n + (chosen[f.id]?.length || 0), 0);
  const close = (refocus = false) => {
    setAt(null);
    if (refocus) btn.current?.focus({ preventScroll: true });
  };
  useEffect(() => {
    if (!at) return undefined;
    const away = (e) => {
      if (pop.current?.contains(e.target) || btn.current?.contains(e.target)) return;
      close(false);
    };
    const keys = (e) => {
      if (e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation();
        close(true);
      }
    };
    // A scroll anywhere but in the list itself moves the header away from it.
    const scrolled = (e) => { if (!pop.current?.contains(e.target)) close(false); };
    document.addEventListener("mousedown", away);
    document.addEventListener("touchstart", away);
    document.addEventListener("keydown", keys, true);
    window.addEventListener("scroll", scrolled, true);
    window.addEventListener("resize", () => close(false), { once: true });
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("touchstart", away);
      document.removeEventListener("keydown", keys, true);
      window.removeEventListener("scroll", scrolled, true);
    };
  }, [at]); // eslint-disable-line react-hooks/exhaustive-deps
  // Placed under its button, moved in to stay on screen; the first box takes the focus.
  const [pos, setPos] = useState(null);
  useLayoutEffect(() => {
    if (!at || !pop.current) { setPos(null); return; }
    const r = pop.current.getBoundingClientRect();
    setPos(placeMenu(at, { w: r.width, h: r.height }, { vw: window.innerWidth, vh: window.innerHeight }));
  }, [at]);
  useEffect(() => {
    if (pos) pop.current?.querySelector("input")?.focus({ preventScroll: true });
  }, [pos]);
  const toggle = (f, value, on) => {
    const now = chosen[f.id] || [];
    onChange(f.id, on ? [...now, value] : now.filter((v) => v !== value));
  };
  const name = `Filter ${wide ? "the tasks" : label}${ticked ? ` (${ticked} chosen)` : ""}`;
  return (
    <>
      <button ref={btn} type="button" className={"cf-btn" + (ticked ? " on" : "") + (wide ? " wide" : "")} aria-haspopup="dialog"
              aria-expanded={!!at} aria-label={name} title={ticked ? `${name}: click to change` : `Filter by ${label.toLowerCase()}`}
              onDoubleClick={(e) => e.stopPropagation()}
              onClick={(e) => {
                e.stopPropagation();
                if (at) return close(false);
                const b = e.currentTarget.getBoundingClientRect();
                return setAt({ x: wide ? b.left : b.right - 240, y: b.bottom + 4 });
              }}>
        <svg viewBox="0 0 16 16" width="12" height="12" aria-hidden="true"><path d="M2 3h12l-4.6 5.4v4.2L6.6 14V8.4z" fill={ticked ? "currentColor" : "none"} stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" /></svg>
        {wide && <span>{label}{ticked ? ` · ${ticked}` : ""}</span>}
      </button>
      {at && createPortal(
        <div ref={pop} className="cf-pop" role="dialog" aria-label={wide ? "Filter the tasks" : `Filter: ${label}`}
             style={pos ? { left: pos.left, top: pos.top } : { left: 0, top: 0, visibility: "hidden" }}>
          {facets.map((f) => (
            <div key={f.id} className="cf-group" role="group" aria-labelledby={`${uid}-${f.id}`}>
              <div className={"cf-head" + (facets.length > 1 ? "" : " sr-only")} id={`${uid}-${f.id}`}>{f.label}</div>
              {f.values.length === 0 && <p className="cf-none">Nothing on show to filter by.</p>}
              {f.values.map((v) => {
                const on = (chosen[f.id] || []).includes(v.value);
                return (
                  <Checkbox key={`${f.id}:${v.value}`} className={"cf-item" + (v.count ? "" : " zero")}
                            checked={on} onChange={(e) => toggle(f, v.value, e.target.checked)}
                            label={<>
                              <span className="cf-lbl" title={v.label}>{v.label}</span>
                              <span className="cf-n" aria-label={`${v.count} ${v.count === 1 ? "row" : "rows"}`}>{v.count.toLocaleString("en-AU")}</span>
                            </>} />
                );
              })}
            </div>
          ))}
          <div className="cf-foot">
            <span className="cf-note">From the rows open in the tree</span>
            <button type="button" className="link" disabled={!ticked} onClick={() => { onClear(); close(true); }}>Clear</button>
          </div>
        </div>,
        portalHost() || document.body,
      )}
    </>
  );
}
