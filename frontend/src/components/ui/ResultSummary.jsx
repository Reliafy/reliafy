// The answer, first (#311): one plain sentence with the numbers in bold, then
// at most four tiles, then (outside this component) one chart, then the rest
// folded under ResultDetails.
//
//   tone      "good" (green: a good verdict) | "caveat" (amber: a warning or
//             a result with a catch) | "bad" (red: a failing verdict, e.g. a
//             requirement not met) | "neutral" (a plan or a fact)
//   sentence  node — the answer, with <b> around its numbers
//   stats     [{ label, value, hint? }] — at most 4, values formatted by the
//             caller (format.js: formatNumber / formatPercent)
//   children  an optional short muted line under the sentence
const ICON = { good: "✓", caveat: "!", bad: "✕" };

export default function ResultSummary({ tone = "neutral", sentence, stats = [], children, className }) {
  const t = ["good", "caveat", "bad", "neutral"].includes(tone) ? tone : "neutral";
  const tiles = stats.filter(Boolean).slice(0, 4);
  return (
    <section className={`result-summary rs-${t}` + (className ? " " + className : "")} aria-label="Result">
      <div className="rs-answer">
        {ICON[t] && <span className="rs-icon" aria-hidden="true">{ICON[t]}</span>}
        <div>
          <p className="rs-sentence">{sentence}</p>
          {children && <p className="rs-note">{children}</p>}
        </div>
      </div>
      {tiles.length > 0 && (
        <div className="stats rs-stats">
          {tiles.map((s, i) => (
            <div className="stat" key={i}>
              <div className="k">{s.label}</div>
              <div className="v">{s.value}</div>
              {s.hint && <div className="rs-hint">{s.hint}</div>}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

// Secondary figures and method notes, folded away under "Details".
//   summary   the disclosure's label ("Details" by default)
//   rows      [{ label, value }] — shown as a two-column list (optional)
//   children  anything else (notes, a table)
export function ResultDetails({ summary = "Details", rows = [], children, open = false }) {
  return (
    <details className="rs-details" open={open}>
      <summary>{summary}</summary>
      <div className="rs-details-body">
        {rows.length > 0 && (
          <dl className="rs-dl">
            {rows.filter(Boolean).map((r, i) => (
              <div key={i}>
                <dt>{r.label}</dt>
                <dd>{r.value}</dd>
              </div>
            ))}
          </dl>
        )}
        {children}
      </div>
    </details>
  );
}
