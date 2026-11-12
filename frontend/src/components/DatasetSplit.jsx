import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import Select from "./Select.jsx";
import { ErrorNotice } from "./StorageCap.jsx";
import { getBilling, listDatasets } from "../api.js";
import { useAppConfig } from "../ConfigProvider.jsx";
import { blankWarning, readSheet, splitPlan, splitRoom } from "../datasetSplit.js";

// The Data section's upload (New dataset): "Split into datasets by [column]",
// one sheet saved as several datasets, each value its own dataset named by the
// value. Off by default; with it off, the upload is exactly as before.
// Every part keeps the one reading set on the upload screen (less the split
// column), so the split itself only counts rows.
//
//   const split = useDatasetSplit({ text, noHeader, source, enabled });
//   {split.picker}{split.summary}           // the selector, then "This file makes 3 datasets"
//   <button onClick={() => split.save(upload)} disabled={!split.canSave}>{split.saveLabel}</button>
//   after saving: split.savedList (links to each dataset), in place of the form.
//
// ``text``: the file as CSV text (an Excel sheet already converted); null
// while it is being read. ``source``: the file's name without its extension,
// added to a value's name when a dataset of that name exists.
// ``save(upload)``: ``upload(column)`` sends the file with ``dataset_col``
// (api.uploadSplitDatasets) and answers { datasets, left_out }.
export function useDatasetSplit({ text, noHeader = false, source = "", enabled = true }) {
  const config = useAppConfig();
  const [column, setColumn] = useState("");
  const [taken, setTaken] = useState(null);
  const [billing, setBilling] = useState(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(null);
  const [error, setError] = useState(null);
  const sheet = useMemo(() => (enabled && text != null ? readSheet(text, noHeader) : null), [enabled, text, noHeader]);
  const columns = sheet?.header || [];
  // A dataset of one column left is no dataset: the split column is dropped.
  const offered = !!sheet && columns.length > 1 && sheet.rows.length > 0;
  const active = offered && !!column && columns.includes(column);

  // A new file starts with no split.
  useEffect(() => { setColumn(""); setSaved(null); setError(null); }, [text, noHeader]);
  useEffect(() => {
    if (!active) return undefined;
    let live = true;
    if (taken === null) {
      listDatasets().then((d) => live && setTaken((d.datasets || []).filter((x) => !x.is_sample && !x.read_only)
        .map((x) => x.name)), () => live && setTaken([]));
    }
    if (config.billing && billing === null) getBilling().then((b) => live && setBilling(b), () => {});
    return () => { live = false; };
  }, [active, taken, billing, config.billing]);

  const plan = useMemo(() => (active ? splitPlan(sheet, column, taken || [], source) : null),
    [active, sheet, column, taken, source]);
  const n = plan?.parts.length || 0;
  const room = plan ? splitRoom(billing, n) : null;
  const canSave = active && n > 0 && !room && !saving;
  const saveLabel = saving ? "Saving…" : `Save ${n} dataset${n === 1 ? "" : "s"}`;
  const waitingFor = !active ? null : n === 0 ? `Column “${column}” has no values to split by.` : room ? room.text : null;

  const save = async (upload) => {
    if (!canSave) return;
    setSaving(true);
    setError(null);
    try {
      setSaved(await upload(column));
    } catch (err) {
      setError(err);
    } finally {
      setSaving(false);
    }
  };

  const warn = plan && blankWarning(plan.blank, column);
  const picker = offered ? (
    <div className="ds-split">
      <div className="ds-split-pick">
        <span>Split into datasets by</span>
        <Select value={column} onChange={setColumn} ariaLabel="Split into datasets by"
                options={[{ value: "", label: "— no split: one dataset —" }, ...columns]} />
      </div>
      <span className="hint" style={{ margin: 0 }}>
        Optional. Each value of the column becomes its own dataset, named by the value.
      </span>
    </div>
  ) : null;

  const summary = active && plan ? (
    <section className="split-summary" aria-label="Datasets this file makes">
      <h3>This file makes {n} dataset{n === 1 ? "" : "s"}:</h3>
      <div className="maint-scroll split-scroll">
        <table className="split-table">
          <tbody>
            {plan.parts.map((p) => (
              <tr key={p.value}>
                <th scope="row">{p.name}</th>
                <td>{p.rows.toLocaleString()} row{p.rows === 1 ? "" : "s"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {warn && <p className="ds-header-note" role="status"><span>{warn}</span></p>}
      <p className="muted-line" style={{ margin: 0 }}>
        Each is saved on its own, without the “{column}” column, and every one is read as set below.
      </p>
      {room && (
        <div className="card upgrade-nudge" role="status">
          <p>{room.text} Nothing is saved until they all fit. <Link to="/billing">Upgrade to Pro</Link> for unlimited
            datasets, or delete some you no longer need.</p>
        </div>
      )}
      <ErrorNotice error={error} />
    </section>
  ) : null;

  const savedList = saved ? (
    <section className="split-summary" aria-label="Saved datasets">
      <h3>Saved {saved.datasets.length} dataset{saved.datasets.length === 1 ? "" : "s"}:</h3>
      <div className="maint-scroll split-scroll">
        <table className="split-table">
          <tbody>
            {saved.datasets.map((d) => (
              <tr key={d.id}>
                <th scope="row"><Link to={`/data/${d.id}`}>{d.name}</Link></th>
                <td>{d.n_rows.toLocaleString()} row{d.n_rows === 1 ? "" : "s"}{d.reused ? " · already saved" : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted-line" style={{ margin: 0 }}>
        Open one to fit a model to it.
        {saved.left_out ? ` ${blankWarning(saved.left_out, column)}.` : ""}
      </p>
    </section>
  ) : null;

  return { offered, active, column, setColumn, picker, summary, savedList, saved, canSave, saveLabel, waitingFor, save, saving };
}
