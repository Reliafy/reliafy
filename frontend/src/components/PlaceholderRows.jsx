import "./PlaceholderRows.css";

// Quiet grey rows drawn where a list will be while it loads: never "Loading…"
// in a card, and never the list's empty sentence, which says something untrue
// until the answer is in. The rows have the shape of a list row (a kind, a
// name, a line of detail). `label` is what a screen reader hears; pass null
// when a parent already says the page is loading.
//
// It carries `view-loading`, the mark the smoke suite waits on, so a page
// counts as settled only once its placeholders are gone.
export default function PlaceholderRows({ rows = 3, label = "Loading…" }) {
  return (
    <div className="wait-rows view-loading" role={label ? "status" : undefined}>
      {label && <span className="sr-only">{label}</span>}
      {Array.from({ length: rows }, (_, i) => (
        <div className="wait-row" key={i} aria-hidden="true">
          <span className="wait-bar wait-kind" />
          <span className="wait-body">
            <span className="wait-bar wait-name" />
            <span className="wait-bar wait-detail" />
          </span>
        </div>
      ))}
    </div>
  );
}
