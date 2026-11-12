import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import Select from "./Select.jsx";
import { ErrorNotice } from "./StorageCap.jsx";
import { getBilling, listDatasets, uploadSplitDatasets } from "../api.js";
import { useAppConfig } from "../ConfigProvider.jsx";
import {
  blankWarning, countWords, groupCounts, parseCsv, sourceStem, splitNames, splitProblems, splitRoom, splitSheet,
} from "../datasetSplit.js";

// The Data step's "dataset" selector (the first row of ColumnMapper): split
// one sheet into several datasets by a column, each value its own dataset
// named by the value. Off by default; with it off, nothing changes. One
// mapping for all: the flow's selectors read every dataset the same way.
//
//   const split = useDatasetSplit({ file, columns, mapping, spec, reading, fitTo, enabled });
//   <ColumnMapper top={split.picker} issues={[...issues, ...split.issues]} notes={[...split.notes]} … />
//   {split.active && split.summary}       // "This sheet makes 3 datasets: …"
//   Next → <button onClick={split.save} disabled={!split.canSave}>{split.saveLabel}</button>
//   after saving: split.savedList (links to each dataset and its Fit), in place of the step.
//
// ``file``: the sheet as a CSV File (an upload or a paste; a saved dataset
// is already one dataset, so the selector isn't offered). ``spec``: what the
// flow's mapping asks of each row (datasetSplit.groupCounts). ``reading``:
// { kind, mapping, unit, options } kept on each new dataset, so its own fit
// starts from the same reading. ``fitTo(id)``: the dataset's Fit link.
export function useDatasetSplit({ file, columns = [], mapping = {}, spec, reading, fitTo, enabled = true }) {
  const config = useAppConfig();
  const [column, setColumn] = useState("");
  const [sheet, setSheet] = useState(null);
  const [taken, setTaken] = useState(null);
  const [billing, setBilling] = useState(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(null);
  const [error, setError] = useState(null);
  const offered = enabled && !!file && columns.length > 1;
  const active = offered && !!column && columns.includes(column);

  // A new sheet starts with no split.
  useEffect(() => { setColumn(""); setSheet(null); setSaved(null); setError(null); }, [file]);
  useEffect(() => {
    if (!active || sheet) return undefined;
    let live = true;
    file.text().then((t) => live && setSheet(parseCsv(t)), () => {});
    return () => { live = false; };
  }, [active, sheet, file]);
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

  const source = sourceStem(file?.name);
  const parts = useMemo(() => {
    if (!active || !sheet) return null;
    const { groups, blank } = splitSheet(sheet, column);
    const names = splitNames(groups.map((g) => g.value), taken || [], source);
    return {
      blank,
      groups: groups.map((g, i) => ({ ...g, name: names[i], counts: groupCounts(sheet.header, g.rows, spec) })),
      problems: splitProblems(sheet.header, groups, spec),
    };
  }, [active, sheet, column, taken, source, spec]);

  const n = parts?.groups.length || 0;
  const room = parts ? splitRoom(billing, n) : null;
  const issues = (parts?.problems || []).filter((p) => !p.note);
  const notes = (parts?.problems || []).filter((p) => p.note);
  const canSave = active && !!parts && n > 0 && issues.length === 0 && !room && !saving;
  const saveLabel = saving ? "Saving…" : `Save ${n} dataset${n === 1 ? "" : "s"}`;
  const waitingFor = !active ? null : !parts ? "Reading the sheet…" : n === 0 ? "The dataset column has no values."
    : issues.length ? `First settle the note${issues.length === 1 ? "" : "s"} beside ${[...new Set(issues.map((i) => i.row))].join(", ")}.`
    : room ? room.text : null;

  const save = async () => {
    if (!canSave) return;
    setSaving(true);
    setError(null);
    try {
      setSaved(await uploadSplitDatasets(file, source, column, reading));
    } catch (err) {
      setError(err);
    } finally {
      setSaving(false);
    }
  };

  // The selector, the first row of the Data step.
  const used = new Set(Object.values(mapping).filter((v) => typeof v === "string" && v));
  const warn = parts && blankWarning(parts.blank);
  const picker = offered ? (
    <div className="xcn-row" key="dataset">
      <span className="xcn-key">
        <code>dataset</code>
        <span className="xcn-words">optional: one sheet, several datasets</span>
      </span>
      <div className="xcn-fields">
        <Select value={column} onChange={setColumn} ariaLabel="dataset" className="xcn-pick"
                options={[{ value: "", label: "— none: one dataset —" },
                  ...columns.map((c) => (used.has(c) && c !== column ? { value: c, label: c, hint: "in use", disabled: true } : c))]} />
        {active && <span className="xcn-words">each value becomes its own dataset, named by the value</span>}
      </div>
      {warn && <div className="xcn-below"><p className="xcn-issue" role="status">{warn}</p></div>}
    </div>
  ) : null;

  const summary = active && parts ? (
    <section className="split-summary" aria-label="Datasets this sheet makes">
      <h3>This sheet makes {n} dataset{n === 1 ? "" : "s"}:</h3>
      <div className="maint-scroll">
        <table className="split-table">
          <tbody>
            {parts.groups.map((g) => (
              <tr key={g.value}>
                <th scope="row">{g.name}</th>
                <td>{countWords(g.counts)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted-line" style={{ margin: 0 }}>Each is saved on its own. Fit each from its dataset page.</p>
      {room && (
        <div className="card upgrade-nudge" role="status">
          <p>{room.text} <Link to="/billing">Upgrade to Pro</Link> for unlimited datasets, or delete some you no longer need.</p>
        </div>
      )}
      <ErrorNotice error={error} />
    </section>
  ) : null;

  const savedList = saved ? (
    <section className="split-summary" aria-label="Saved datasets">
      <h3>Saved {saved.datasets.length} dataset{saved.datasets.length === 1 ? "" : "s"}:</h3>
      <div className="maint-scroll">
        <table className="split-table">
          <tbody>
            {saved.datasets.map((d) => (
              <tr key={d.id}>
                <th scope="row"><Link to={`/data/${d.id}`}>{d.name}</Link></th>
                <td>{d.n_rows} row{d.n_rows === 1 ? "" : "s"}{d.reused ? " · already saved" : ""}</td>
                <td>{fitTo && fitTo(d.id) ? <Link to={fitTo(d.id)}>Fit</Link> : null}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted-line" style={{ margin: 0 }}>
        Fit each from its dataset page.
        {saved.left_out ? ` ${blankWarning(saved.left_out)}.` : ""}
      </p>
    </section>
  ) : null;

  return {
    offered, active, column, setColumn, issues, notes, summary, savedList, saved, picker, canSave, saveLabel,
    waitingFor, save, saving,
  };
}
