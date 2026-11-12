import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { listStrategyAnalyses } from "../api.js";
import { relativeTime } from "../instrument.js";
import { strategyListFor } from "../strategyTools.js";
import { itemName } from "./LibRows.jsx";
import Chip from "./ui/Chip.jsx";
import { SAVED_EVENT } from "./SaveAnalysisButton.jsx";

const SHOWN = 5;

// Under a Strategy tool: the saved analyses of the kind it makes, the user's
// and the samples (a filtered view of the Strategy list), newest first, with
// a link to the whole filtered list.
export function SavedOfKind({ kind, noun }) {
  const [rows, setRows] = useState(null);
  const [version, setVersion] = useState(0);
  // A Save on this page lists the new analysis at once.
  useEffect(() => {
    const onSaved = (e) => { if (!e.detail?.kind || e.detail.kind === kind) setVersion((v) => v + 1); };
    window.addEventListener(SAVED_EVENT, onSaved);
    return () => window.removeEventListener(SAVED_EVENT, onSaved);
  }, [kind]);
  useEffect(() => {
    let live = true;
    listStrategyAnalyses()
      .then((d) => live && setRows((d.analyses || []).filter((a) => a.kind === kind)))
      .catch(() => live && setRows([]));
    return () => {
      live = false;
    };
  }, [kind, version]);
  if (rows === null) return null;
  const newest = [...rows].sort((a, b) =>
    String(b.updated_at || b.created_at || "").localeCompare(String(a.updated_at || a.created_at || "")));
  return (
    <section className="card strategy-saved" aria-labelledby={`saved-${kind}`}>
      <div className="strategy-saved-head">
        <h2 id={`saved-${kind}`}>Saved {noun}</h2>
        {rows.length > 0 && <Link to={strategyListFor(kind)}>See all {rows.length} →</Link>}
      </div>
      {rows.length === 0 ? (
        <p className="hint">None yet. Compute a result and press Save to keep it here and link it as evidence for an RCM decision.</p>
      ) : (
        <ul className="strategy-saved-list">
          {newest.slice(0, SHOWN).map((a) => (
            <li key={a.id}>
              <Link to={`/strategy/analyses/${encodeURIComponent(a.id)}`}>{itemName(a)}</Link>
              {a.is_sample && <Chip>Sample</Chip>}
              {a.headline && <span className="strategy-saved-result">{a.headline}</span>}
              {!a.is_sample && <span className="lib-date">{relativeTime(a.updated_at || a.created_at)}</span>}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

// Why Compute is greyed out, beside it ("Enter both costs."). Nothing when
// it's ready.
export function ComputeReason({ id, reason }) {
  if (!reason) return null;
  return <p className="hint compute-why" id={id} role="status">{reason}</p>;
}
