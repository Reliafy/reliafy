import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import Chip from "./ui/Chip.jsx";
import PreviewTable from "./PreviewTable.jsx";
import { pickerGroups, rowsWords, shortDate, shownName } from "../datasetPicker.js";
import "./DatasetPicker.css";

// Pick one saved dataset for a fit: a searchable list (yours, then samples),
// each row its name, rows, tags and the date it was added, beside a pane for
// the picked one. One component for every "use a saved dataset" step: the
// list's order and the reasons a dataset doesn't suit come from
// datasetPicker.js. No modal: the list and the picked dataset sit side by
// side (stacked on a phone).
//
//   kind      the fit, as datasetFit.usableFor names it ("life", ...)
//   datasets  the /api/datasets list, or null while it loads
//   value     the picked dataset's id
//   onPick    (dataset) => void
//   children  the picked dataset's pane (DatasetGlance, plus what the caller adds)
export default function DatasetPicker({ kind, datasets, value, onPick, children, disabled = false }) {
  const [query, setQuery] = useState("");
  const out = useMemo(() => pickerGroups(kind, datasets, query), [kind, datasets, query]);
  const loading = datasets === null;
  // Stacked (a phone), the picked dataset's pane is under the list: bring it into view.
  const pane = useRef(null);
  const picked = useRef(value);
  useEffect(() => {
    if (!value || value === picked.current) return;
    picked.current = value;
    if (typeof window !== "undefined" && window.matchMedia?.("(max-width: 900px)").matches) {
      pane.current?.scrollIntoView?.({ behavior: "smooth", block: "start" });
    }
  }, [value]);
  return (
    <div className={"dsp" + (value ? " dsp-has-pick" : "")}>
      <div className="dsp-list">
        <input
          type="search"
          className="ctl dsp-search"
          placeholder="Search your datasets and samples"
          aria-label="Search datasets"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          disabled={loading}
        />
        {loading ? (
          <p className="dsp-quiet" role="status">Loading your datasets…</p>
        ) : out.total === 0 ? (
          <p className="dsp-quiet">
            No saved data yet. Paste values or upload a file instead, or add a dataset under <Link to="/data">Data</Link>.
          </p>
        ) : out.shown === 0 ? (
          <p className="dsp-quiet">Nothing matches “{query.trim()}”.</p>
        ) : (
          <div className="dsp-scroll" role="radiogroup" aria-label="Saved datasets">
            {out.groups.map((g) => (
              <div className="dsp-group" key={g.key}>
                <div className="dsp-group-h">
                  {g.label} <span className="dsp-count">{g.rows.length}</span>
                </div>
                {g.rows.map(({ dataset: d, reason }) => {
                  const on = d.id === value;
                  return (
                    <button
                      key={d.id}
                      type="button"
                      role="radio"
                      aria-checked={on}
                      className={"dsp-row" + (on ? " on" : "") + (reason ? " off" : "")}
                      disabled={disabled || !!reason}
                      title={reason || undefined}
                      onClick={() => onPick(d)}
                    >
                      <span className="dsp-name">{shownName(d)}</span>
                      <span className="dsp-rows">{rowsWords(d.n_rows)}</span>
                      <span className="dsp-tags">
                        {(d.tags || []).map((t) => <Chip key={t}>{t}</Chip>)}
                      </span>
                      <span className="dsp-date">{shortDate(d.created_at) && `Added ${shortDate(d.created_at)}`}</span>
                      {reason && <span className="dsp-why">{reason}</span>}
                    </button>
                  );
                })}
              </div>
            ))}
          </div>
        )}
      </div>
      <div className="dsp-pane" aria-live="polite" ref={pane}>
        {children || (
          <p className="dsp-quiet dsp-pane-empty">
            {out.usable > 0 ? "Pick a dataset to see its first rows and how its columns will be read." : null}
          </p>
        )}
      </div>
    </div>
  );
}

// The picked dataset at a glance: its name, what it holds and its first rows.
//   detail  the dataset's detail (/api/datasets/:id), or null while it loads
export function DatasetGlance({ summary, detail, error, rows = 5, children }) {
  if (error) return <p className="error" role="alert">{error}</p>;
  if (!detail) return <p className="dsp-quiet" role="status">Reading {shownName(summary)}…</p>;
  const cols = detail.preview_columns || [];
  return (
    <div className="dsp-glance">
      <div className="dsp-glance-h">
        <b>{shownName(detail)}</b>
        <span className="dsp-quiet-inline">
          {rowsWords(detail.n_rows)} · {cols.length} column{cols.length === 1 ? "" : "s"}
          {detail.summary ? ` · ${detail.summary}` : ""}
        </span>
      </div>
      <PreviewTable columns={cols} rows={(detail.preview || []).slice(0, rows)} className="dsp-preview" />
      {children}
    </div>
  );
}
