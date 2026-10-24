import "./Outline.css";

// Small pieces every outline shares (the asset tree pane, the RCM worksheet):
// the open/close arrow, the filter's text marked in a name, and the level
// buttons (1 · 2 · 3 · All, then Close everything).

export const Chevron = () => (
  <svg viewBox="0 0 16 16" width="13" height="13" aria-hidden="true">
    <path d="M6 3.5 10.5 8 6 12.5" stroke="currentColor" strokeWidth="1.8" fill="none" strokeLinecap="round" />
  </svg>
);

// The text with the filter's words marked.
export function Highlight({ text, query }) {
  const q = query.trim();
  const i = q ? text.toLowerCase().indexOf(q.toLowerCase()) : -1;
  if (i < 0) return text;
  return <>{text.slice(0, i)}<mark>{text.slice(i, i + q.length)}</mark>{text.slice(i + q.length)}</>;
}

// Open the outline to a level, everything, or close everything. `names`
// (optional) says what each level is, for the buttons' titles.
export function LevelButtons({ levels, onLevel, onCloseAll, names, className = "tp-levels" }) {
  return (
    <div className={className} role="group" aria-label="Open the tree to a level">
      <span className="tp-levels-label" aria-hidden="true">Levels</span>
      <div className="seg seg-sm">
        {levels.map((n) => (
          <button key={n} type="button" className="seg-btn" onClick={() => onLevel(n)}
                  aria-label={`Open to level ${n}`}
                  title={names?.[n - 1] ? `Open to level ${n}: ${names[n - 1]}` : `Open to level ${n}`}>{n}</button>
        ))}
        <button type="button" className="seg-btn" onClick={() => onLevel(Infinity)} aria-label="Open everything" title="Open everything">All</button>
      </div>
      <button type="button" className="tp-icon-btn" onClick={onCloseAll} aria-label="Close everything" title="Close everything">
        <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><rect x="2.5" y="2.5" width="11" height="11" rx="2" stroke="currentColor" strokeWidth="1.4" fill="none" /><path d="M5.5 8h5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" /></svg>
      </button>
    </div>
  );
}
