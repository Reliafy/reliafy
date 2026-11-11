import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import Chip from "./ui/Chip.jsx";
import PreviewTable from "./PreviewTable.jsx";
import { getDataset } from "../api.js";
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
//   extra     the flow's own rule on top of the tags: (dataset) => reason | null
//   empty     the pane's words before anything is picked
export default function DatasetPicker({ kind, datasets, value, onPick, children, disabled = false, extra = null, empty = null }) {
  const [query, setQuery] = useState("");
  const out = useMemo(() => pickerGroups(kind, datasets, query, extra), [kind, datasets, query, extra]);
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
    <div className="dsp-c">
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
            {out.usable > 0 ? empty || "Pick a dataset to see its first rows and how its columns will be read." : null}
          </p>
        )}
      </div>
    </div>
    </div>
  );
}

// The picked dataset at a glance: its name, what it holds and its first rows.
//   detail  the dataset's detail (/api/datasets/:id), or null while it loads
//   part    "measurements": show its readings (its measurements part, when it has one)
export function DatasetGlance({ summary, detail, error, rows = 5, part = null, children }) {
  if (error) return <p className="error" role="alert">{error}</p>;
  if (!detail) return <p className="dsp-quiet" role="status">Reading {shownName(summary)}…</p>;
  const table = part === "measurements" && detail.measurements ? detail.measurements : detail;
  const cols = table.preview_columns || [];
  return (
    <div className="dsp-glance">
      <div className="dsp-glance-h">
        <b>{shownName(detail)}</b>
        <span className="dsp-quiet-inline">
          {table !== detail ? `${(table.n_rows ?? 0).toLocaleString("en-GB")} readings` : rowsWords(detail.n_rows)} · {cols.length} column{cols.length === 1 ? "" : "s"}
          {detail.summary ? ` · ${detail.summary}` : ""}
        </span>
      </div>
      <PreviewTable columns={cols} rows={(table.preview || []).slice(0, rows)} className="dsp-preview" />
      {children}
    </div>
  );
}

// A picked dataset's detail, read when it's picked (the pane's first rows): { summary, detail, error }.
export function usePickedDataset() {
  const [picked, setPicked] = useState(null);
  const pick = (d) => {
    setPicked({ summary: d, detail: null, error: null });
    getDataset(d.id).then(
      (full) => setPicked((p) => (p?.summary.id === d.id ? { ...p, detail: full } : p)),
      (err) => setPicked((p) => (p?.summary.id === d.id ? { ...p, error: err.message } : p)),
    );
  };
  return [picked, pick];
}

// The first step of a new-model flow: where the data comes from. "Saved data" (the picker, the
// picked dataset's first rows and Use this dataset) first, then "Upload a file" (the flow's own
// drop zone, passed as ``upload``). The New model page's FitFlow adds pasting and its own pane.
//   kind, datasets, extra   as DatasetPicker
//   onUse      (dataset) => void: the flow's own "use a saved dataset"
//   upload     the upload tab's content
//   part       "measurements": the pane shows the readings (DatasetGlance)
//   busy       the flow is reading something: Use waits
export function DataSourceStep({ kind, datasets, onUse, upload, extra = null, part = null, busy = false }) {
  const [source, setSource] = useState("saved");
  const [picked, pick] = usePickedDataset();
  return (
    <>
      <div className="source-toggle" role="tablist" aria-label="Where the data comes from">
        {[["saved", "Saved data"], ["upload", "Upload a file"]].map(([v, label]) => (
          <button key={v} type="button" role="tab" aria-selected={source === v}
                  className={`source-tab${source === v ? " active" : ""}`} onClick={() => setSource(v)}>
            {label}
          </button>
        ))}
      </div>
      {source === "saved" ? (
        <DatasetPicker kind={kind} datasets={datasets} value={picked?.summary.id} onPick={pick} extra={extra} disabled={busy}
                       empty="Pick a dataset to see its first rows.">
          {picked && (
            <DatasetGlance summary={picked.summary} detail={picked.detail} error={picked.error} part={part}>
              <div className="dsp-use">
                <button type="button" onClick={() => onUse(picked.summary)} disabled={busy || !picked.detail}>
                  {busy ? "Reading…" : "Use this dataset"}
                </button>
              </div>
            </DatasetGlance>
          )}
        </DatasetPicker>
      ) : upload}
    </>
  );
}
