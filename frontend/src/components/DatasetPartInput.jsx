import { useMemo, useRef, useState } from "react";
import Modal from "./Modal.jsx";
import PreviewTable from "./PreviewTable.jsx";
import { useSpreadsheet } from "./ExcelSheetPicker.jsx";
import { SPREADSHEET_ACCEPT, isSpreadsheetFile, pasteDatasetPart, uploadDatasetPart } from "../api.js";
import { firstRowIsData, parsePreview } from "../datasetGuess.js";
import "./Datasets.css";

// One table for a dataset's part (its measurements, or life data for a
// dataset of readings alone): a file dropped or chosen (CSV or an Excel
// sheet), or text pasted, previewed before it goes. The value is plain state
// the caller keeps: { file, excel, text, headerChoice }, empty = EMPTY_PART.
export const EMPTY_PART = { file: null, excel: null, text: "", headerChoice: null };

export const partHasData = (v) => !!(v?.file || (v?.text || "").trim());

// Send a part's value to the server: the file (an Excel sheet converted
// there), or the pasted text. Answers the dataset's detail.
export function submitPart(datasetId, part, value) {
  const noHeader = value.headerChoice ?? (value.text && !value.file ? firstRowIsData(value.text) : null);
  if (value.file) {
    return uploadDatasetPart(datasetId, part, value.file, value.excel ? false : (value.headerChoice ?? null), value.excel || null);
  }
  return pasteDatasetPart(datasetId, part, value.text, noHeader);
}

export default function DatasetPartInput({ value, onChange, placeholder, label = "readings", disabled = false }) {
  const [mode, setMode] = useState(value?.text ? "paste" : "file"); // file | paste
  const [dragging, setDragging] = useState(false);
  const fileRef = useRef(null);
  const { chooseSheet, modal: sheetModal } = useSpreadsheet();
  const v = value || EMPTY_PART;
  const set = (patch) => onChange({ ...v, ...patch });

  const shownText = mode === "paste" ? v.text : v.file && v.excel == null ? v.fileText ?? null : null;
  const guessedNoHeader = useMemo(() => shownText != null && !!shownText.trim() && firstRowIsData(shownText), [shownText]);
  const noHeader = v.headerChoice ?? guessedNoHeader;
  const preview = useMemo(
    () => (shownText != null && shownText.trim() ? parsePreview(shownText, { noHeader }) : null),
    [shownText, noHeader]
  );

  const onFile = async (file) => {
    if (!file) return;
    if (isSpreadsheetFile(file)) {
      const excel = await chooseSheet(file);
      if (!excel) return;
      set({ file, excel, text: "", fileText: null });
      return;
    }
    let fileText = null;
    try { fileText = await file.text(); } catch { fileText = null; }
    set({ file, excel: null, text: "", fileText });
  };

  return (
    <div className="ds-part-input">
      <div className="ds-part-modes" role="tablist" aria-label={`How to give the ${label}`}>
        <button type="button" role="tab" aria-selected={mode === "file"} className={"tab" + (mode === "file" ? " active" : "")}
          onClick={() => setMode("file")} disabled={disabled}>File</button>
        <button type="button" role="tab" aria-selected={mode === "paste"} className={"tab" + (mode === "paste" ? " active" : "")}
          onClick={() => setMode("paste")} disabled={disabled}>Paste</button>
      </div>
      {mode === "file" ? (
        !v.file ? (
          <div
            className={"dropzone ds-part-drop" + (dragging ? " dragging" : "")}
            role="button"
            tabIndex={0}
            aria-label={`Choose a file of ${label}`}
            onClick={() => !disabled && fileRef.current?.click()}
            onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fileRef.current?.click(); } }}
            onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => { e.preventDefault(); setDragging(false); onFile(e.dataTransfer.files?.[0]); }}
          >
            <span className="dz-big">Drop a CSV or Excel file of {label} here or <strong>click to browse</strong></span>
          </div>
        ) : (
          <div className="ds-file-line">
            <span className="ds-file-name">{v.file.name}</span>
            {preview && (
              <span className="muted">{preview.nRows.toLocaleString()} row{preview.nRows === 1 ? "" : "s"} · {preview.nCols} column{preview.nCols === 1 ? "" : "s"}</span>
            )}
            {v.excel?.sheet && <span className="muted">Sheet “{v.excel.sheet}”</span>}
            <button type="button" className="link" disabled={disabled}
              onClick={() => set({ file: null, excel: null, fileText: null, headerChoice: null })}>
              Choose another file
            </button>
          </div>
        )
      ) : (
        <label className="login-field">
          <span>{label[0].toUpperCase() + label.slice(1)}</span>
          <textarea className="paste-area" value={v.text} spellCheck={false} disabled={disabled}
                    placeholder={placeholder || "unit,age,value\nP1,0,2.1\nP1,10,2.4"}
                    onChange={(e) => set({ text: e.target.value, file: null, excel: null, fileText: null })} />
        </label>
      )}
      {preview && <PreviewTable columns={preview.columns} rows={preview.preview} />}
      {shownText != null && shownText.trim() && (
        <>
          {v.headerChoice === null && guessedNoHeader && (
            <p className="ds-header-note" role="status">
              <span>The first row looks like data, so it's treated as data.</span>
              <button type="button" className="link" onClick={() => set({ headerChoice: false })}>Undo</button>
            </p>
          )}
          <label className="ds-check">
            <input type="checkbox" checked={noHeader} disabled={disabled} onChange={(e) => set({ headerChoice: e.target.checked })} />
            <span>No header row — the first row is data. Columns are named <code>col 1</code>, <code>col 2</code>, …</span>
          </label>
        </>
      )}
      <input ref={fileRef} type="file" accept={`.csv,text/csv,${SPREADSHEET_ACCEPT}`} hidden
             onChange={(e) => { onFile(e.target.files?.[0]); e.target.value = ""; }} />
      {sheetModal}
    </div>
  );
}

// The words for each part: what it is and what a row holds.
export const PART_WORDS = {
  measurements: {
    title: "Add measurements",
    replace: "Replace measurements",
    label: "readings",
    hint: "One row per reading: the unit's id, its age when read (since new, in the life data's time unit) and the value read. More reading columns are fine.",
    placeholder: "pump,age_days,vibration_mm_s\nP-01,0,2.1\nP-01,10,2.4",
  },
  life: {
    title: "Add life data",
    replace: "Add life data",
    label: "life data",
    hint: "One row per unit: its id, its age at failure (or now, if still running), whether it failed (0 = failed, 1 = still running) and any covariates. The readings this dataset holds become its measurements.",
    placeholder: "pump,age_days,running,load\nP-01,69.5,0,1\nP-02,120,1,0",
  },
};

// A small dialog around the input: add or replace one part of a dataset.
export function DatasetPartModal({ datasetId, part = "measurements", replacing = false, onClose, onDone }) {
  const words = PART_WORDS[part];
  const [value, setValue] = useState(EMPTY_PART);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const run = async () => {
    setBusy(true); setError(null);
    try { onDone(await submitPart(datasetId, part, value)); }
    catch (e) { setError(e.message); } finally { setBusy(false); }
  };
  const footer = (
    <button className="ds-foot-primary" onClick={run} disabled={!partHasData(value) || busy}>
      {busy ? "Adding…" : replacing ? "Replace" : "Add"}
    </button>
  );
  return (
    <Modal title={replacing ? words.replace : words.title} className="ds-new" onClose={onClose} locked={busy} footer={footer}>
      <div className="fit-step">
        <p className="hint" style={{ marginTop: 0 }}>{words.hint}</p>
        <DatasetPartInput value={value} onChange={setValue} label={words.label} placeholder={words.placeholder} disabled={busy} />
        {error && <div className="error">{error}</div>}
      </div>
    </Modal>
  );
}
