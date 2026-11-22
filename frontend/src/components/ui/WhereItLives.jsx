import { wherePath, whereNote } from "../../subtree.js";
import "./WhereItLives.css";

// Where a rolled-up record lives (subtree.js): its position's name, and under it "This position"
// on the node's own records or what it sits in ("Pump 2 › Drive motor"), so twins can be told
// apart. The whole path on hover. For a table cell in any Explorer tab that lists a node's records
// and everything below it. Guideline: docs/design-system/components/WhereItLives.md.
export default function WhereItLives({ rec, here = null, own = "This position", className = "" }) {
  const note = whereNote(rec, here, own);
  return (
    <span className={`where-lives ${className}`.trim()} title={wherePath(rec) || undefined}>
      <span className="where-lives-name">{rec?.subject?.name || ""}</span>
      {note && <span className="where-lives-note">{note}</span>}
    </span>
  );
}
