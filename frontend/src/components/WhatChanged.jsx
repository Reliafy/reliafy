import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getWorkspaceChanges } from "../api.js";
import { changeRows, sentenceParts } from "../changes.js";
import { relativeTime } from "../instrument.js";
import Chip from "./ui/Chip.jsx";
import "./WhatChanged.css";

// "What changed" (#41). Every fact comes from the server (GET /api/changes),
// computed from what Reliafy stores; nothing here is estimated.

// The computed sentence with its numbers in bold.
export function ChangesSentence({ sentence, as: Tag = "p", className = "wc-sentence" }) {
  return (
    <Tag className={className}>
      {sentenceParts(sentence).map((p, i) => (p.bold ? <b key={i}>{p.text}</b> : <span key={i}>{p.text}</span>))}
    </Tag>
  );
}

// One list of changes, most important first.
export function ChangeList({ rows }) {
  return (
    <ul className="wc-list">
      {rows.map((r) => (
        <li key={r.key}>
          <Link className="wc-row" to={r.url}>
            <span className="wc-kind">
              {r.tone ? <Chip tone={r.tone}>{r.kind}</Chip> : r.kind}
            </span>
            <span className="wc-body">
              <span className="wc-name">{r.name}</span>
              {r.detail && <span className="wc-detail">{r.detail}</span>}
            </span>
            {r.at && <span className="wc-when">{relativeTime(r.at)}</span>}
          </Link>
        </li>
      ))}
    </ul>
  );
}

const PANEL_ROWS = 4;

// The Modelling home's panel: the last 30 days in one sentence, then the few
// changes that matter most, and a link to the full page. Hidden while the
// workspace has nothing of its own.
export default function WhatChangedPanel() {
  const [data, setData] = useState(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let live = true;
    getWorkspaceChanges()
      .then((d) => live && setData(d))
      .catch(() => live && setFailed(true));
    return () => {
      live = false;
    };
  }, []);
  // Nothing saved in this workspace yet: "Start here" says what to do.
  if (failed || !data || !data.counts?.items) return null;
  const rows = changeRows(data);
  return (
    <section className="wc-panel" aria-labelledby="wc-title">
      <div className="recent-models-head">
        <h2 id="wc-title">What changed</h2>
        <Link to="/changes">See all changes →</Link>
      </div>
      <div className="wc-card">
        <ChangesSentence sentence={data.sentence} />
        {rows.length > 0 && <ChangeList rows={rows.slice(0, PANEL_ROWS)} />}
      </div>
    </section>
  );
}
