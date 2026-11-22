import "./WhereItLives.css";

// Where a rolled-up record lives: its position's name, and under it "This position" on the node's
// own records or what it sits in ("Pump 2 › Drive motor"), so twins can be told apart; the whole
// path on hover. For a table cell in an Explorer panel that lists a node's records and everything
// below it (the tree-tables say it by their own nesting). Guideline:
// docs/design-system/components/WhereItLives.md.
export function wherePath(rec) {
  return [rec?.subject?.within, rec?.subject?.name].filter(Boolean).join(" › ");
}

export default function WhereItLives({ rec, here = null, own = "This position", className = "" }) {
  const mine = !!here && rec?.subject?.id === here;
  const note = mine ? own : rec?.subject?.within || "";
  return (
    <span className={`where-lives ${className}`.trim()} title={wherePath(rec) || undefined}>
      <span className="where-lives-name">{rec?.subject?.name || ""}</span>
      {note && <span className="where-lives-note">{note}</span>}
    </span>
  );
}
