import { useMemo, useRef, useState } from "react";
import Modal from "./Modal.jsx";
import PreviewTable from "./PreviewTable.jsx";
import { useSpreadsheet } from "./ExcelSheetPicker.jsx";
import { SPREADSHEET_ACCEPT, isSpreadsheetFile, pasteDataset, uploadDataset } from "../api.js";
import SegmentedControl from "./ui/SegmentedControl.jsx";
import { fileStem, parsePreview } from "../datasetGuess.js";
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

export default function NewDatasetModal({ onClose, onCreated }) {
  // Opens on the dropzone; "paste or type" switches to entering data.
  const [step, setStep] = useState("upload"); // upload | enter
  const [enterMode, setEnterMode] = useState("paste"); // paste | form
  const [name, setName] = useState("");
  const [noHeader, setNoHeader] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [dragging, setDragging] = useState(false);
  const fileRef = useRef(null);
  const { chooseSheet, modal: sheetModal } = useSpreadsheet();

  // upload: the picked file, previewed before it's created. A CSV keeps its
  // text for the preview; an Excel workbook its chosen sheet (the sheet picker
  // already showed its rows).
  const [picked, setPicked] = useState(null); // { file, text?, excel? }
  const filePreview = useMemo(
    () => (picked?.text != null ? parsePreview(picked.text, { noHeader }) : null),
    [picked, noHeader]
  );

  // paste
  const [text, setText] = useState("");
  const preview = useMemo(() => parsePreview(text, { noHeader }), [text, noHeader]);

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
    if (!name.trim()) setName(fileStem(file.name));
  };
  const onUpload = async () => {
    setBusy(true); setError(null);
    try {
      const { file, excel } = picked;
      onCreated(await uploadDataset(file, name.trim() || undefined, excel ? false : noHeader, excel || null), name.trim());
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  };

  // --- paste ---
  const pasteValid = name.trim() && preview && preview.nCols > 1;
  const onPaste = async () => {
    setBusy(true); setError(null);
    try { onCreated(await pasteDataset(name.trim(), text, noHeader), name.trim()); }
    catch (e) { setError(e.message); } finally { setBusy(false); }
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
      onCreated(await uploadDataset(file, name.trim() || undefined), name.trim());
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  };

  // ---- footer: Back on the left (entering data), the one primary on the right ----
  const enter = step === "enter";
  const valid = enter ? (enterMode === "paste" ? pasteValid : formValid) : !!picked;
  const run = enter ? (enterMode === "paste" ? onPaste : onForm) : onUpload;
  const footer = (
    <>
      {enter && <button className="secondary" onClick={() => go("upload")} disabled={busy}>Back</button>}
      <button className="ds-foot-primary" onClick={run} disabled={!valid || busy}>
        {busy ? "Creating…" : "Create dataset"}
      </button>
    </>
  );

  const noHeaderBox = (excelNote) => (
    <label className="ds-check">
      <input type="checkbox" checked={noHeader} onChange={(e) => setNoHeader(e.target.checked)} />
      <span>
        No header row — the first row is data. Columns are named <code>col 1</code>, <code>col 2</code>, …
        {excelNote && " (for an Excel file you choose the header row next)"}
      </span>
    </label>
  );

  return (
    <Modal title="New dataset" className="ds-new" onClose={onClose} locked={busy} footer={footer}>
      {step === "upload" && (
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
                <button className="link" onClick={() => { setPicked(null); setError(null); }} disabled={busy}>
                  Choose another file
                </button>
              </div>
              <label className="login-field">
                <span>Dataset name</span>
                <input type="text" value={name} placeholder="e.g. Pump bearing lives"
                       onChange={(e) => setName(e.target.value)} />
              </label>
              {filePreview && <PreviewTable columns={filePreview.columns} rows={filePreview.preview} />}
              {picked.text != null && noHeaderBox(false)}
            </>
          )}
          <input ref={fileRef} type="file" accept={`.csv,text/csv,${SPREADSHEET_ACCEPT}`} hidden
                 onChange={(e) => { onFile(e.target.files?.[0]); e.target.value = ""; }} />
          {error && <div className="error">{error}</div>}
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
            </div>
          )}
          {error && <div className="error">{error}</div>}
        </div>
      )}
    </Modal>
  );
}
