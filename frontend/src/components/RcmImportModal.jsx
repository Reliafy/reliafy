import { useEffect, useMemo, useRef, useState } from "react";
import Modal from "./Modal.jsx";
import Select from "./Select.jsx";
import ExcelSheetPicker, { useExcelInspection } from "./ExcelSheetPicker.jsx";
import SheetColumnMapper, { mappingComplete } from "./SheetColumnMapper.jsx";
import { excelTable, importPositionRcm, previewPositionRcmImport } from "../api.js";
import { WORKSHEET_ACCEPT, importSummary, isCsvFile } from "../rcmImport.js";

const CONSEQUENCES = [
  ["safety", "Safety"],
  ["environmental", "Environmental"],
  ["operational", "Operational"],
  ["non_operational", "Non-operational"],
  ["hidden", "Hidden"],
];
const OUTCOMES = [
  ["on_condition", "On-condition (monitor)"],
  ["fixed_interval", "Fixed-interval replacement"],
  ["rtf:random", "Run-to-failure — failures are random"],
  ["rtf:uneconomic", "Run-to-failure — prevention isn't economic"],
  ["failure_finding", "Failure-finding task"],
  ["redesign", "Redesign"],
  ["accept", "Accept risk / no scheduled maintenance"],
];

// Import an FMEA / RCM worksheet onto a position's RCM (``position``: {id,
// name}): pick the file (Excel, or CSV: no sheet to pick), the sheet and
// header row, map columns (function / functional failure / failure mode /
// effects / consequence / decision…), check how consequence and decision
// values map onto Reliafy's categories, then add it. The preview says what it
// adds and what's there already, and the import only adds.
export default function RcmImportModal({ position, onClose, onImported }) {
  const fileRef = useRef(null);
  const [file, setFile] = useState(null);
  const [step, setStep] = useState("file"); // file | sheet | map
  const csv = isCsvFile(file);
  const { inspection, error: inspectError, loading } = useExcelInspection(csv ? null : file);
  const [sel, setSel] = useState(null);
  const [table, setTable] = useState(null);
  const [mapping, setMapping] = useState({});
  const [extras, setExtras] = useState([]);
  const [extrasOn, setExtrasOn] = useState(true);
  const [consequenceMap, setConsequenceMap] = useState({});
  const [outcomeMap, setOutcomeMap] = useState({});
  const [preview, setPreview] = useState(null);
  const [previewError, setPreviewError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const errorRef = useRef(null);
  useEffect(() => {
    if (error) errorRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [error]);

  useEffect(() => {
    const first = inspection?.sheets?.find((s) => s.rows > 0) || inspection?.sheets?.[0];
    if (first) setSel({ sheet: first.name, headerRow: first.guessed_header_row });
  }, [inspection]);

  const pick = (f) => {
    if (!f) return;
    setFile(f);
    setError(null);
    if (isCsvFile(f)) {
      // One table, its header on the first line: straight to the columns.
      const whole = { sheet: null, headerRow: null };
      setSel(whole);
      toMapping(f, whole);
    } else setStep("sheet");
  };

  const toMapping = async (f = file, at = sel) => {
    setBusy(true);
    setError(null);
    try {
      const t = await excelTable(f, at.sheet, at.headerRow, "rcm");
      setTable(t);
      setMapping(t.guess || {});
      setExtras(t.extra_columns || []);
      setConsequenceMap({});
      setOutcomeMap({});
      setPreview(null);
      setStep("map");
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const options = useMemo(() => ({
    mapping,
    consequence_map: consequenceMap,
    outcome_map: outcomeMap,
    extra_columns: extrasOn ? extras : [],
  }), [mapping, consequenceMap, outcomeMap, extras, extrasOn]);

  const ready = table && mappingComplete(table.fields, mapping);

  // Live preview from the server (debounced) whenever the mapping changes.
  useEffect(() => {
    if (step !== "map" || !ready) { setPreview(null); return undefined; }
    let live = true;
    const t = setTimeout(() => {
      previewPositionRcmImport(position.id, file, sel.sheet, sel.headerRow, options)
        .then((p) => { if (live) { setPreview(p); setPreviewError(null); } })
        .catch((e) => { if (live) { setPreview(null); setPreviewError(e.message); } });
    }, 300);
    return () => { live = false; clearTimeout(t); };
  }, [step, ready, file, sel, options, position]);

  const unmapped = table ? table.columns.filter((c) => !Object.values(mapping).includes(c)) : [];

  const doImport = async () => {
    setBusy(true);
    setError(null);
    try {
      const done = await importPositionRcm(position.id, file, sel.sheet, sel.headerRow, options);
      if (!done.ok) {
        setPreview(done);
        setError("Nothing was added: fix the rows listed and try again.");
        setBusy(false);
        return;
      }
      onImported(done);
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  };

  const summary = preview ? importSummary(preview.counts) : null;
  const canImport = ready && preview && !busy && preview.ok && !summary.nothing;

  let footer;
  if (step === "file") {
    footer = <button className="secondary" onClick={onClose}>Cancel</button>;
  } else if (step === "sheet") {
    footer = (
      <>
        <button className="secondary" onClick={() => { setFile(null); setStep("file"); }} disabled={busy}>Back</button>
        <button onClick={() => toMapping()} disabled={busy || !sel || !inspection}>{busy ? "Reading…" : "Next: map columns"}</button>
      </>
    );
  } else {
    // What it adds, beside the button (the full preview is above, maybe out of view).
    footer = (
      <>
        <span className="hint" role="status">
          {!preview ? "Reading the columns…" : preview.errors?.length ? "Fix the rows listed, then try again."
            : summary.nothing ? "Nothing new to add." : `Adds ${summary.adds.join(" · ")}.`}
        </span>
        <div className="row xl-foot-row">
          <button className="secondary" onClick={() => (csv ? (setFile(null), setStep("file")) : setStep("sheet"))}
                  disabled={busy}>Back</button>
          <button onClick={doImport} disabled={!canImport} title={`Add to “${position.name}”`}>
            {busy ? "Adding…" : `Add to “${clip(position.name, 40)}”`}
          </button>
        </div>
      </>
    );
  }

  return (
    <Modal title={`Import a worksheet onto “${clip(position.name)}”`}
           className="modal-xl" locked={busy} onClose={onClose} footer={footer}>
      {step === "file" && (
        <div className="fit-step">
          <p className="muted-line" style={{ marginTop: 0 }}>
            An FMEA or RCM worksheet with one row per failure mode — columns like Function,
            Functional failure, Failure mode, Effects, Consequence, Task and Interval. Blank
            function / failure cells carry down from the row above, as in most worksheets.
          </p>
          <p className="muted-line">
            It's added to {clip(position.name)}'s RCM. Nothing there is changed or removed: a function or
            functional failure with the same words is used as it is, and failure modes already there are left
            alone, so importing the same file again adds nothing.
          </p>
          {busy && <p className="hint">Reading the file…</p>}
          <div className="dropzone" onClick={() => fileRef.current?.click()}
               onDragOver={(e) => e.preventDefault()}
               onDrop={(e) => { e.preventDefault(); pick(e.dataTransfer.files?.[0]); }}>
            <span className="dz-big">Drop an Excel workbook or a CSV file here or <strong>click to browse</strong></span>
            <span className="dz-hint">.xlsx or .csv</span>
            <input ref={fileRef} type="file" accept={WORKSHEET_ACCEPT} hidden
                   aria-label="Worksheet file"
                   onChange={(e) => { pick(e.target.files?.[0]); e.target.value = ""; }} />
          </div>
        </div>
      )}

      {step === "sheet" && (
        <div className="fit-step">
          {loading && <p className="hint">Reading the workbook…</p>}
          {inspectError && <div className="error">{inspectError}</div>}
          {inspection && sel && <ExcelSheetPicker inspection={inspection} value={sel} onChange={setSel} />}
        </div>
      )}

      {step === "map" && table && (
        <div className="fit-step">
          <p className="muted-line" style={{ margin: 0 }}>
            <b>{table.sheet}</b> · {table.n_rows.toLocaleString("en-AU")} rows. Only Failure mode is
            required; a missing Function or Functional failure column puts everything under “Imported”.
          </p>
          <SheetColumnMapper fields={table.fields} columns={table.columns} mapping={mapping}
                             onChange={setMapping} rows={table.rows} />

          {unmapped.length > 0 && (
            <div className="xl-extras">
              <label className="ds-check">
                <input type="checkbox" checked={extrasOn} onChange={(e) => setExtrasOn(e.target.checked)} />
                <span>
                  Keep other columns in each failure mode's notes (e.g. “Severity 8 · Occurrence 4 · RPN 96”)
                  — Reliafy has no FMEA scoring yet.
                </span>
              </label>
              {extrasOn && (
                <div className="xl-chips">
                  {unmapped.map((c) => (
                    <label key={c} className={"xl-chip" + (extras.includes(c) ? " on" : "")}>
                      <input type="checkbox" checked={extras.includes(c)}
                             onChange={(e) => setExtras((cur) => e.target.checked ? [...cur, c] : cur.filter((x) => x !== c))} />
                      {c}
                    </label>
                  ))}
                </div>
              )}
            </div>
          )}

          {previewError && <div className="error">{previewError}</div>}
          {preview && (
            <>
              <ValueMap title="Consequence values" items={preview.values.consequence} choices={CONSEQUENCES}
                        map={consequenceMap} setMap={setConsequenceMap} />
              <ValueMap
                title={preview.outcome_source === "task" ? "Decision type — read from the Task column" : "Decision type values"}
                items={preview.values.outcome} choices={OUTCOMES} map={outcomeMap} setMap={setOutcomeMap} />
              <PositionResult preview={preview} summary={summary} name={position.name} />
            </>
          )}
        </div>
      )}
      {error && <div className="error" ref={errorRef}>{error}</div>}
    </Modal>
  );
}

// Distinct cell values -> Reliafy categories. Unlisted values use the server's
// guess (shown as "auto"); "Leave unset" keeps the mode undecided.
function ValueMap({ title, items, choices, map, setMap }) {
  if (!items?.length) return null;
  const options = [{ value: "", label: "Leave unset" }, ...choices.map(([value, label]) => ({ value, label }))];
  const unmappedCount = items.filter((it) => !(map[it.value] ?? it.guess)).length;
  return (
    <div className="xl-valuemap">
      <div className="ds-section-h">
        {title}
        {unmappedCount > 0 && <span className="xl-dim"> · {unmappedCount} not mapped</span>}
      </div>
      <div className="xl-valuemap-grid">
        {items.map((it) => {
          const value = map[it.value] ?? it.guess ?? "";
          const auto = !(it.value in map) && it.guess;
          return (
            <div key={it.value} className={"xl-value" + (value ? "" : " unset")}>
              <span className="xl-value-raw" title={it.value}>
                {it.value} <span className="xl-dim">×{it.count}</span>
              </span>
              <Select value={value} onChange={(v) => setMap((m) => ({ ...m, [it.value]: v }))} options={options} />
              {auto && <span className="xl-auto">Auto</span>}
              {!value && it.hint && <span className="xl-value-hint">{it.hint}</span>}
            </div>
          );
        })}
      </div>
    </div>
  );
}

const clip = (text, max = 60) => (String(text || "").length > max ? `${String(text).slice(0, max - 1)}…` : String(text || ""));

// What the worksheet adds to the position (the preview: nothing written yet),
// what's there already, and any rows in error (then nothing can be added).
function PositionResult({ preview, summary, name }) {
  const notes = [...(preview.notes || []), ...(preview.warnings || [])];
  return (
    <div className="xl-summary" data-testid="rcm-import-result">
      <div className="ds-section-h">What this adds to {clip(name)}</div>
      <p>
        {summary.nothing ? <b>Nothing new: it's all on {clip(name)} already.</b>
          : <>Adds {summary.adds.map((t, i) => <span key={t}>{i ? " · " : ""}<b>{t}</b></span>)}</>}
      </p>
      {summary.there.length > 0 && (
        <p className="xl-dim">Already there, left as they are: {summary.there.join(" · ")}.</p>
      )}
      {preview.functions.length > 0 && (
        <ul className="xl-tree">
          {preview.functions.slice(0, 4).map((f, i) => (
            <li key={i}>
              <b>{f.text}</b>{!f.new && <span className="xl-dim"> (there already)</span>}
              <ul>
                {f.failures.slice(0, 3).map((x, j) => (
                  <li key={j}>
                    {x.text}
                    <span className="xl-dim"> — {x.modes ? `${x.modes} new failure mode${x.modes === 1 ? "" : "s"}` : "no new failure modes"}</span>
                  </li>
                ))}
                {f.failures.length > 3 && <li className="xl-dim">+ {f.failures.length - 3} more</li>}
              </ul>
            </li>
          ))}
          {preview.functions.length > 4 && <li className="xl-dim">+ {preview.functions.length - 4} more functions</li>}
        </ul>
      )}
      {preview.errors?.length > 0 && (
        <div className="error" role="alert">
          <p style={{ margin: 0 }}>
            {preview.errors.length === 1 ? "One row needs fixing" : `${preview.counts.errors} rows need fixing`} before
            anything can be added:
          </p>
          <ul>{preview.errors.map((e, i) => <li key={i}>{e}</li>)}</ul>
        </div>
      )}
      {notes.map((w, i) => <p key={i} className="xl-note">{w}</p>)}
    </div>
  );
}
