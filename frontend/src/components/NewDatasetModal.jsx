import { useEffect, useMemo, useRef, useState } from "react";
import { LibraryChoice, libraryChoiceReady, resolveLibraryChoice } from "./LibraryParts.jsx";
import Modal from "./Modal.jsx";
import { ErrorNotice } from "./StorageCap.jsx";
import PreviewTable from "./PreviewTable.jsx";
import { useSpreadsheet } from "./ExcelSheetPicker.jsx";
import {
  SPREADSHEET_ACCEPT, excelToCsvFile, isSpreadsheetFile, pasteDataset, uploadDataset, uploadSplitDatasets,
} from "../api.js";
import { useDatasetSplit } from "./DatasetSplit.jsx";
import { sourceStem } from "../datasetSplit.js";
import SegmentedControl from "./ui/SegmentedControl.jsx";
import DatasetPartInput, { EMPTY_PART, PART_WORDS, partHasData, submitPart } from "./DatasetPartInput.jsx";
import { fileStem, firstRowIsData, parsePreview } from "../datasetGuess.js";
import ReadingEditor, { readingWaiting } from "./ReadingEditor.jsx";
import { useUploadReading } from "../useUploadReading.js";
import { emptyReading, readingPayload, withoutColumn } from "../datasetReading.js";
import "./Datasets.css";

// ---- structured form fields (SurPyval survival inputs, no covariates) --------
// One comma-separated value list per field. Canonical column order for the CSV.
const FIELD_ORDER = ["x", "xl", "xr", "c", "n", "tl", "tr"];
// Plain labels; the CSV keeps SurPyval's column names (x, c, n, …).
const FIELDS = {
  x: { label: "Times", title: "One time per unit: when it failed, or how long it has run" },
  c: { label: "Censor flag 0/1", title: "Per time: 0 failed · 1 still running · -1 failed before · 2 interval" },
  n: { label: "Count", title: "How many units share each value (blank: one each)" },
  xl: { label: "Interval from", title: "Interval lower bounds (with Interval to)" },
  xr: { label: "Interval to", title: "Interval upper bounds (with Interval from)" },
  tl: { label: "Observed from", title: "Left truncation: a single value applies to every row" },
  tr: { label: "Observed until", title: "Right truncation: a single value applies to every row" },
};
const splitList = (s) => String(s || "").split(",").map((v) => v.trim());
const listLen = (s) => {
  const parts = splitList(s);
  while (parts.length && parts[parts.length - 1] === "") parts.pop();
  return parts.length;
};

// One labelled comma-separated value list for a survival field. When
// ``broadcast`` is set, a single value is treated as applying to every row.
// ``bad`` (its count doesn't match the times') shows the count in red.
function ListField({ f, v, onChange, disabled, placeholder, broadcast, bad }) {
  const n = disabled ? 0 : listLen(v || "");
  const count = n === 0 ? "" : broadcast && n === 1 ? "all rows" : `${n} value${n === 1 ? "" : "s"}`;
  const id = `ds-field-${f}`;
  return (
    <div className={"ds-fieldwrap" + (disabled ? " disabled" : "")}>
      <label className="ds-flabel" htmlFor={id} title={FIELDS[f].title}>
        <span>{FIELDS[f].label}</span>
        <span className={"ds-listcount" + (bad ? " bad" : "")}>{count}</span>
      </label>
      <div className={"ds-listfield" + (disabled ? " disabled" : "")}>
        <input id={id} type="text" className="ds-listinput" value={v || ""} disabled={disabled}
               placeholder={placeholder} spellCheck={false} aria-invalid={bad || undefined}
               onChange={(e) => onChange(f, e.target.value)} />
      </div>
    </div>
  );
}

// ``withMeasurements``: also offer the dataset's measurements (readings on
// the same units), added to the dataset right after it is created. ``open``
// starts with that section open (the condition and life page). ``onSplit``:
// offer "Split into datasets by" for an uploaded file (the Data section), and
// call it once the datasets are saved (the modal then lists them).
// ``initialFile``: a file (or pasted values made a file) to start from, as a
// fit flow's upload or paste does: saved as a dataset here, then the flow goes
// on from it (``onCreated``). ``initialName``: its default name.
//
// After the file (and sheet, header row) the modal asks how the columns are
// read for modelling (ReadingEditor: x with its range, c, n, tl, tr, i, m,
// the failure mode, and Z), and keeps that reading with the dataset (or every
// dataset of a split), so building a model from it asks nothing about columns.
export default function NewDatasetModal({
  onClose, onCreated, onSplit = null, withMeasurements = true, measurementsOpen = false,
  initialFile = null, initialName = "", title = "New dataset", libraryChoice = false, libraryId: presetLibrary = null,
}) {
  // Opens on the dropzone; "paste or type" switches to entering data.
  const [step, setStep] = useState("upload"); // upload | enter
  const [enterMode, setEnterMode] = useState("paste"); // paste | form
  const [name, setName] = useState(initialName);
  // No header row: the user's choice, or null to guess from the data (#434:
  // a first row of only numbers is data).
  const [headerChoice, setHeaderChoice] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [dragging, setDragging] = useState(false);
  const fileRef = useRef(null);
  const { chooseSheet, modal: sheetModal } = useSpreadsheet();
  // The measurements, when given: added once the dataset exists. If that
  // second step fails the dataset still exists, so the error says so and the
  // button opens it.
  const [measurements, setMeasurements] = useState(EMPTY_PART);
  const [measOpen, setMeasOpen] = useState(measurementsOpen);
  const [created, setCreated] = useState(null);
  // "Also add to library" (``libraryChoice``: the Data section and a library's Upload data…): every
  // dataset made goes into it as a snapshot, in the same save. A new library is made just before.
  const [library, setLibrary] = useState({ libraryId: presetLibrary || "", newName: "" });
  const libraryTarget = async () => {
    if (!libraryChoice) return null;
    const id = await resolveLibraryChoice(library);
    if (id && library.libraryId === "new") setLibrary({ libraryId: id, newName: "" });
    return id;
  };
  const libraryBox = libraryChoice && (
    <LibraryChoice value={library} onChange={setLibrary} disabled={busy} />
  );
  const addMeasurements = async (ds, typedName) => {
    if (!withMeasurements || !partHasData(measurements)) return onCreated(ds, typedName);
    try {
      onCreated(await submitPart(ds.id, "measurements", measurements), typedName);
    } catch (e) {
      setCreated({ ds, typedName });
      throw new Error(`The dataset was created, but its measurements weren't added: ${e.message}`);
    }
  };

  // upload: the picked file, previewed before it's created. A CSV keeps its
  // text for the preview; an Excel workbook its chosen sheet (the sheet picker
  // already showed its rows).
  const [picked, setPicked] = useState(null); // { file, text?, excel? }
  // An Excel sheet as CSV, for the split's preview and save: { file, text }
  // (read only when the split is offered; the plain upload sends the workbook).
  const [sheetCsv, setSheetCsv] = useState(null);
  useEffect(() => {
    setSheetCsv(null);
    if (!onSplit || !picked?.excel) return undefined;
    let live = true;
    excelToCsvFile(picked.file, picked.excel.sheet, picked.excel.headerRow)
      .then(async (file) => { const text = await file.text(); if (live) setSheetCsv({ file, text }); })
      .catch(() => {});
    return () => { live = false; };
  }, [picked, onSplit]);
  // paste
  const [text, setText] = useState("");

  // The data on show (the picked CSV, or the paste) and whether its first row
  // looks like data; the guess holds until the user says otherwise.
  const shownText = step === "enter" ? (enterMode === "paste" ? text : null) : picked?.text ?? null;
  const guessedNoHeader = useMemo(() => shownText != null && firstRowIsData(shownText), [shownText]);
  const noHeader = headerChoice ?? guessedNoHeader;
  const filePreview = useMemo(
    () => (picked?.text != null ? parsePreview(picked.text, { noHeader }) : null),
    [picked, noHeader]
  );
  const preview = useMemo(() => parsePreview(text, { noHeader }), [text, noHeader]);

  // "Split into datasets by": an uploaded file only (DatasetSplit.jsx).
  const split = useDatasetSplit({
    enabled: !!onSplit && step === "upload" && !!picked,
    text: picked?.excel ? sheetCsv?.text ?? null : picked?.text ?? null,
    noHeader: picked?.excel ? false : noHeader,
    source: sourceStem(picked?.file?.name),
  });
  // How the columns are read (useUploadReading): the file's or the paste's
  // columns as they will be stored, guessed first, checked by the user.
  const readingSource = useMemo(() => {
    if (step === "upload" && picked) return { file: picked.file, noHeader: picked.excel ? null : noHeader, excel: picked.excel || null };
    if (step === "enter" && enterMode === "paste" && text.trim()) return { text, noHeader };
    return null;
  }, [step, picked, noHeader, enterMode, text]);
  const up = useUploadReading(readingSource);
  // The split column has no role: it's left out of every dataset.
  const splitCol = split.active ? split.column : "";
  const lastSplit = useRef("");
  useEffect(() => {
    if (lastSplit.current === splitCol) return;
    const back = lastSplit.current;
    lastSplit.current = splitCol;
    up.setReading((cur) => (cur ? withoutColumn(cur, splitCol, up.facts, up.nRows, back) : cur));
  }, [splitCol]); // eslint-disable-line react-hooks/exhaustive-deps
  const readingCols = (up.cols?.columns || []).filter((c) => c !== splitCol);
  const reading = up.reading;
  const readingWait = reading ? readingWaiting(reading, up.facts, up.nRows)
    : up.error ? "The columns couldn't be read." : readingSource ? "Reading the columns…" : null;
  const readingBox = (readingSource || up.reading) && (
    <section className="ds-reading" aria-label="How the columns are read">
      <div className="ds-section-h">How the columns are read for modelling</div>
      <p className="hint" style={{ margin: 0 }}>
        Checked once, here: every model built from this dataset reads it this way. You can change it later.
      </p>
      {up.loading && !reading && <p className="muted-line" role="status">Reading the columns…</p>}
      <ErrorNotice error={up.error} />
      {reading && (
        <ReadingEditor columns={readingCols} facts={up.facts} nRows={up.nRows} reading={reading}
                       onChange={up.setReading} disabled={busy || split.saving} />
      )}
    </section>
  );
  const payload = reading ? readingPayload(reading) : null;

  const onSaveSplit = () => split.save(async (column) => {
    const libId = await libraryTarget();
    const out = picked.excel
      ? await uploadSplitDatasets(sheetCsv.file, sourceStem(picked.file.name), column, false, payload, libId)
      : await uploadSplitDatasets(picked.file, sourceStem(picked.file.name), column, noHeader, payload, libId);
    onSplit?.(out);
    return out;
  });

  // form — one comma-separated value list per field
  const [vals, setVals] = useState({});
  const setVal = (f, v) => setVals((cur) => ({ ...cur, [f]: v }));

  const go = (next) => { setError(null); setStep(next); };

  // --- upload ---
  const onFile = async (file) => {
    if (!file) return;
    setError(null);
    let next = { file };
    if (isSpreadsheetFile(file)) {
      // An Excel workbook: pick the sheet and header row; the server converts
      // that sheet to CSV and stores it exactly as the CSV would be.
      const excel = await chooseSheet(file);
      if (!excel) return;
      next = { file, excel };
    } else {
      try {
        next = { file, text: await file.text() };
      } catch {
        next = { file };
      }
    }
    setPicked(next);
    // The file's name is the default; one typed already stands.
    if (!name.trim() && !initialName) setName(fileStem(file.name));
  };
  // A fit flow's file or pasted values: straight to the reading.
  const started = useRef(false);
  useEffect(() => {
    if (!initialFile || started.current) return;
    started.current = true;
    onFile(initialFile);
  }, [initialFile]); // eslint-disable-line react-hooks/exhaustive-deps
  const onUpload = async () => {
    setBusy(true); setError(null);
    try {
      const { file, excel } = picked;
      const libId = await libraryTarget();
      await addMeasurements(await uploadDataset(file, name.trim() || undefined, excel ? false : noHeader, excel || null,
                                                payload, libId), name.trim());
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  // --- paste ---
  const pasteValid = name.trim() && preview && preview.nCols > 1;
  const onPaste = async () => {
    setBusy(true); setError(null);
    try {
      const libId = await libraryTarget();
      await addMeasurements(await pasteDataset(name.trim(), text, noHeader, payload, libId), name.trim());
    }
    catch (e) { setError(e); } finally { setBusy(false); }
  };

  // --- form ---
  const usingX = listLen(vals.x) > 0;
  const usingInterval = listLen(vals.xl) > 0 || listLen(vals.xr) > 0;
  const fieldDisabled = (f) =>
    (f === "x" && usingInterval) || ((f === "xl" || f === "xr") && usingX);

  // Fields with content, in canonical order. Truncation (tl/tr) may be a single
  // value that broadcasts to every row (a uniform truncation window).
  const active = FIELD_ORDER.filter((f) => !fieldDisabled(f) && listLen(vals[f]) > 0);
  const broadcastable = (f) => f === "tl" || f === "tr";
  const isBroadcast = (f) => broadcastable(f) && listLen(vals[f]) === 1;
  // c (censor flag) and n (count) are optional: for plain x data, a blank field
  // is written as 0 (all exact) / 1 (one each) so the dataset is explicit.
  const DEFAULTS = { c: "0", n: "1" };
  const isDefaulted = (f) => usingX && f in DEFAULTS && listLen(vals[f]) === 0;
  // Row count comes from the per-observation value fields, not truncation.
  const rowCount = usingX
    ? listLen(vals.x)
    : Math.max(listLen(vals.xl), listLen(vals.xr));
  const hasValue = usingX || (listLen(vals.xl) > 0 && listLen(vals.xr) > 0);
  const mismatched = (f) => active.includes(f) && !isBroadcast(f) && listLen(vals[f]) !== rowCount;
  const lengthsMatch = !active.some(mismatched);
  const formValid = name.trim() && hasValue && rowCount > 0 && lengthsMatch;
  // "More fields" opens by itself when one of them holds something.
  const moreUsed = ["n", "xl", "xr", "tl", "tr"].some((f) => listLen(vals[f]) > 0);

  const onForm = async () => {
    setBusy(true); setError(null);
    try {
      // Output columns: the filled-in fields plus defaulted c/n for x data.
      const outFields = FIELD_ORDER.filter(
        (f) => !fieldDisabled(f) && (listLen(vals[f]) > 0 || isDefaulted(f))
      );
      const header = outFields.join(",");
      const lists = Object.fromEntries(outFields.map((f) => {
        if (isDefaulted(f)) return [f, Array(rowCount).fill(DEFAULTS[f])];
        const parts = splitList(vals[f]);
        while (parts.length && parts[parts.length - 1] === "") parts.pop();
        return [f, isBroadcast(f) ? Array(rowCount).fill(parts[0]) : parts];
      }));
      const rows = Array.from({ length: rowCount }, (_, i) =>
        outFields.map((f) => (lists[f][i] ?? "").trim()).join(",")
      );
      const csv = [header, ...rows].join("\n");
      const file = new File([csv], `${name.trim() || "dataset"}.csv`, { type: "text/csv" });
      // The fields name their roles, so the reading is theirs: x (or its range), c, n, tl, tr.
      const typed = { ...emptyReading(), ...Object.fromEntries(outFields.map((f) => [f, f])) };
      const libId = await libraryTarget();
      await addMeasurements(await uploadDataset(file, name.trim() || undefined, null, null, readingPayload(typed), libId),
                            name.trim());
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  // ---- footer: Back on the left (entering data), the one primary on the right ----
  const enter = step === "enter";
  // The reading must be settled (x and c at least) before a file or paste is saved.
  const needsReading = !(enter && enterMode === "form");
  const valid = (enter ? (enterMode === "paste" ? pasteValid : formValid) : !!picked) && (!needsReading || !readingWait)
    && (!libraryChoice || libraryChoiceReady(library));
  const run = enter ? (enterMode === "paste" ? onPaste : onForm) : onUpload;
  const footer = split.saved ? (
    <button className="ds-foot-primary" onClick={onClose}>Done</button>
  ) : split.active ? (
    <>
      {(split.waitingFor || readingWait) && (
        <span className="hint ds-next-why" role="status" style={{ margin: 0 }}>{split.waitingFor || readingWait}</span>
      )}
      <button className="ds-foot-primary" onClick={onSaveSplit}
              disabled={!split.canSave || !!readingWait || (libraryChoice && !libraryChoiceReady(library))}>{split.saveLabel}</button>
    </>
  ) : created ? (
    <button className="ds-foot-primary" onClick={() => onCreated(created.ds, created.typedName)}>Open the dataset</button>
  ) : (
    <>
      {enter && <button className="secondary" onClick={() => go("upload")} disabled={busy}>Back</button>}
      {needsReading && readingWait && (step === "upload" ? !!picked : true) && (
        <span className="hint ds-next-why" role="status" style={{ margin: 0 }}>{readingWait}</span>
      )}
      <button className="ds-foot-primary" onClick={run} disabled={!valid || busy}>
        {busy ? "Creating…" : "Create dataset"}
      </button>
    </>
  );

  // The optional second table: readings on the dataset's units.
  const measurementsBox = withMeasurements && (
    <details className="ds-more ds-meas" open={measOpen || partHasData(measurements) || undefined}
             onToggle={(e) => setMeasOpen(e.target.open)}>
      <summary>Add measurements for these units (optional)</summary>
      <div className="ds-more-body">
        <p className="hint" style={{ margin: 0 }}>{PART_WORDS.measurements.hint}</p>
        <DatasetPartInput value={measurements} onChange={setMeasurements} label="readings"
                          placeholder={PART_WORDS.measurements.placeholder} disabled={busy} />
      </div>
    </details>
  );

  const noHeaderBox = (excelNote) => (
    <>
      {headerChoice === null && guessedNoHeader && shownText != null && (
        <p className="ds-header-note" role="status">
          <span>Your first row looks like data, so we've treated it as data.</span>
          <button type="button" className="link" onClick={() => setHeaderChoice(false)}>Undo</button>
        </p>
      )}
      <label className="ds-check">
        <input type="checkbox" checked={noHeader} onChange={(e) => setHeaderChoice(e.target.checked)} />
        <span>
          No header row — the first row is data. Columns are named <code>col 1</code>, <code>col 2</code>, …
          {excelNote && " (for an Excel file you choose the header row next)"}
        </span>
      </label>
    </>
  );

  return (
    <Modal title={title} className="ds-new" onClose={onClose} locked={busy || split.saving} footer={footer}>
      {split.saved && <div className="fit-step">{split.savedList}</div>}
      {step === "upload" && !split.saved && (
        <div className="fit-step">
          {!picked ? (
            <>
              <div
                className={"dropzone" + (dragging ? " dragging" : "")}
                role="button"
                tabIndex={0}
                onClick={() => fileRef.current?.click()}
                onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fileRef.current?.click(); } }}
                onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
                onDragLeave={() => setDragging(false)}
                onDrop={(e) => { e.preventDefault(); setDragging(false); onFile(e.dataTransfer.files?.[0]); }}
              >
                <span className="dz-ic">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M12 16V4m0 0 4 4m-4-4-4 4" /><path d="M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3" />
                  </svg>
                </span>
                <span className="dz-big">Drop a CSV or Excel file here or <strong>click to browse</strong></span>
              </div>
              <p className="ds-new-alt">
                No file? <button className="link" onClick={() => go("enter")}>Paste or type the data</button>
              </p>
              {noHeaderBox(true)}
            </>
          ) : (
            <>
              <div className="ds-file-line">
                <span className="ds-file-name">{picked.file.name}</span>
                {filePreview && (
                  <span className="muted">
                    {filePreview.nRows.toLocaleString()} row{filePreview.nRows === 1 ? "" : "s"} ·{" "}
                    {filePreview.nCols} column{filePreview.nCols === 1 ? "" : "s"}
                  </span>
                )}
                {picked.excel?.sheet && <span className="muted">Sheet “{picked.excel.sheet}”</span>}
                <button className="link" onClick={() => { setPicked(null); setHeaderChoice(null); setError(null); }}
                        disabled={busy || split.saving}>
                  Choose another file
                </button>
              </div>
              {!split.active && (
                <label className="login-field">
                  <span>Dataset name</span>
                  <input type="text" value={name} placeholder="e.g. Pump bearing lives"
                         onChange={(e) => setName(e.target.value)} />
                </label>
              )}
              {filePreview ? <PreviewTable columns={filePreview.columns} rows={filePreview.preview} />
                : up.cols ? <PreviewTable columns={up.cols.columns} rows={(up.cols.preview || []).slice(0, 5)} /> : null}
              {picked.text != null && noHeaderBox(false)}
              {split.picker}
              {split.summary}
              {readingBox}
              {libraryBox}
              {!split.active && measurementsBox}
            </>
          )}
          <input ref={fileRef} type="file" accept={`.csv,text/csv,${SPREADSHEET_ACCEPT}`} hidden
                 onChange={(e) => { onFile(e.target.files?.[0]); e.target.value = ""; }} />
          <ErrorNotice error={error} />
          {sheetModal}
        </div>
      )}

      {step === "enter" && (
        <div className="fit-step">
          <SegmentedControl
            label="Entry"
            value={enterMode}
            onChange={setEnterMode}
            style={{ alignSelf: "flex-start" }}
            options={[
              { value: "paste", label: "Paste" },
              { value: "form", label: "Type it in" },
            ]}
          />
          <label className="login-field">
            <span>Dataset name</span>
            <input type="text" autoFocus value={name} placeholder="e.g. Pump bearing lives"
                   onChange={(e) => setName(e.target.value)} />
          </label>

          {enterMode === "paste" ? (
            <>
              <label className="login-field">
                <span>Data</span>
                <textarea className="paste-area" value={text} spellCheck={false}
                          placeholder={"hours,failed\n1240,1\n980,1\n1500,0"}
                          onChange={(e) => setText(e.target.value)} />
              </label>
              {preview ? (
                <div>
                  <div className="ds-section-h">Preview · {preview.nRows} row{preview.nRows === 1 ? "" : "s"} · {preview.nCols} column{preview.nCols === 1 ? "" : "s"}</div>
                  <PreviewTable columns={preview.columns} rows={preview.preview} />
                  {preview.nCols === 1 && <p className="hint">Only one column detected — separate columns with commas or tabs.</p>}
                </div>
              ) : text.trim() ? <p className="hint">Add a header row and at least one data row.</p> : null}
              {noHeaderBox(false)}
              {readingBox}
              {libraryBox}
              {measurementsBox}
            </>
          ) : (
            <div className="ds-form">
              <p className="muted-line" style={{ margin: 0 }}>
                One value per unit, separated by commas.
              </p>
              <ListField f="x" v={vals.x} onChange={setVal} disabled={fieldDisabled("x")}
                         placeholder="1240, 980, 1500, 2100" bad={mismatched("x")} />
              <ListField f="c" v={vals.c} onChange={setVal} placeholder="0 failed · 1 still running (blank: all failed)"
                         bad={mismatched("c")} />
              <details className="ds-more" open={moreUsed || undefined}>
                <summary>More fields</summary>
                <div className="ds-more-body">
                  <ListField f="n" v={vals.n} onChange={setVal} placeholder="blank: one each" bad={mismatched("n")} />
                  <div className="ds-pair">
                    <ListField f="xl" v={vals.xl} onChange={setVal} disabled={fieldDisabled("xl")} placeholder="100, 200"
                               bad={mismatched("xl")} />
                    <ListField f="xr" v={vals.xr} onChange={setVal} disabled={fieldDisabled("xr")} placeholder="150, 250"
                               bad={mismatched("xr")} />
                  </div>
                  <div className="ds-pair">
                    <ListField f="tl" v={vals.tl} onChange={setVal} placeholder="one value, or one per unit" broadcast
                               bad={mismatched("tl")} />
                    <ListField f="tr" v={vals.tr} onChange={setVal} placeholder="optional" broadcast bad={mismatched("tr")} />
                  </div>
                </div>
              </details>
              {hasValue && !lengthsMatch && (
                <p className="hint">Each list needs one value per unit: {rowCount} here.</p>
              )}
              {libraryBox}
              {measurementsBox}
            </div>
          )}
          <ErrorNotice error={error} />
        </div>
      )}
    </Modal>
  );
}
