import { useMemo, useRef, useState } from "react";
import Modal from "./Modal.jsx";
import PreviewTable from "./PreviewTable.jsx";
import { pasteDataset, uploadDataset } from "../api.js";

// ---- paste preview (client-side sniff, server does the authoritative parse) --
function sniff(text) {
  const first = text.split(/\r?\n/).find((l) => l.trim()) || "";
  const counts = { "\t": (first.match(/\t/g) || []).length, ",": (first.match(/,/g) || []).length, ";": (first.match(/;/g) || []).length };
  const best = Object.entries(counts).sort((a, b) => b[1] - a[1])[0];
  return best[1] > 0 ? best[0] : ",";
}
function parsePreview(text, rows = 5) {
  const lines = text.split(/\r?\n/).filter((l) => l.trim());
  if (lines.length < 2) return null;
  const d = sniff(text);
  const split = (l) => l.split(d).map((c) => c.trim());
  return { columns: split(lines[0]), preview: lines.slice(1, rows + 1).map(split), nRows: lines.length - 1, nCols: split(lines[0]).length };
}

// ---- structured form fields (SurPyval survival inputs, no covariates) --------
const FIELDS = {
  x: "Observed value (exact or censored)",
  c: "Censor flag: 0 exact · 1 right · -1 left · 2 interval",
  n: "Count of identical observations",
  xl: "Interval lower bound (with xr)",
  xr: "Interval upper bound (with xl)",
  tl: "Left truncation bound",
  tr: "Right truncation bound",
};
const ALL_FIELDS = ["x", "c", "n", "xl", "xr", "tl", "tr"];
const emptyRows = (n = 4) => Array.from({ length: n }, () => ({}));

export default function NewDatasetModal({ onClose, onCreated }) {
  const [step, setStep] = useState("choose"); // choose | upload | enter
  const [enterMode, setEnterMode] = useState("paste"); // paste | form
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const fileRef = useRef(null);

  // paste
  const [text, setText] = useState("");
  const preview = useMemo(() => parsePreview(text), [text]);

  // form
  const [cols, setCols] = useState(["x", "c"]);
  const [rows, setRows] = useState(emptyRows());

  const reset = () => { setError(null); };
  const back = () => { reset(); setStep("choose"); };

  // --- upload ---
  const onFile = async (file) => {
    if (!file) return;
    setBusy(true); setError(null);
    try {
      const ds = await uploadDataset(file, name.trim() || undefined);
      onCreated(ds);
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  };

  // --- paste ---
  const pasteValid = name.trim() && preview && preview.nCols > 1;
  const onPaste = async () => {
    setBusy(true); setError(null);
    try { onCreated(await pasteDataset(name.trim(), text)); }
    catch (e) { setError(e.message); } finally { setBusy(false); }
  };

  // --- form ---
  const toggleCol = (f) => {
    setCols((cur) => {
      let next;
      if (cur.includes(f)) next = cur.filter((c) => c !== f);
      else next = [...cur, f];
      // x is mutually exclusive with the xl/xr interval pair.
      if (f === "x" && next.includes("x")) next = next.filter((c) => c !== "xl" && c !== "xr");
      if ((f === "xl" || f === "xr") && next.includes(f)) next = next.filter((c) => c !== "x");
      return ALL_FIELDS.filter((k) => next.includes(k)); // keep canonical order
    });
  };
  const setCell = (i, f, v) => setRows((rs) => rs.map((r, idx) => (idx === i ? { ...r, [f]: v } : r)));
  const formMapping = cols.includes("x") ? !!cols.length : cols.includes("xl") && cols.includes("xr");
  const dataRows = rows.filter((r) => cols.some((c) => String(r[c] ?? "").trim() !== ""));
  const formValid = name.trim() && cols.length && formMapping && dataRows.length > 0;

  const onForm = async () => {
    setBusy(true); setError(null);
    try {
      const csv = [cols.join(","), ...dataRows.map((r) => cols.map((c) => String(r[c] ?? "").trim()).join(","))].join("\n");
      const file = new File([csv], `${name.trim() || "dataset"}.csv`, { type: "text/csv" });
      onCreated(await uploadDataset(file, name.trim() || undefined));
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  };

  // ---- footer per step ----
  let footer = null;
  if (step === "enter") {
    const valid = enterMode === "paste" ? pasteValid : formValid;
    const run = enterMode === "paste" ? onPaste : onForm;
    footer = (
      <div className="row" style={{ margin: 0, width: "100%" }}>
        <button className="secondary" onClick={back} disabled={busy}>Back</button>
        <span className="grow" />
        <button onClick={run} disabled={!valid || busy}>{busy ? "Creating…" : "Create dataset"}</button>
      </div>
    );
  } else if (step === "upload") {
    footer = <button className="secondary" onClick={back} disabled={busy}>Back</button>;
  }

  return (
    <Modal title="New dataset" onClose={onClose} locked={busy} footer={footer}>
      {step === "choose" && (
        <div className="ds-choose">
          <button className="ds-choice" onClick={() => { reset(); setStep("upload"); }}>
            <span className="ds-choice-h">Upload a CSV</span>
            <span className="ds-choice-b">Drop or browse for a .csv file.</span>
          </button>
          <button className="ds-choice" onClick={() => { reset(); setStep("enter"); }}>
            <span className="ds-choice-h">Enter data</span>
            <span className="ds-choice-b">Paste from a spreadsheet, or type it into a form.</span>
          </button>
        </div>
      )}

      {step === "upload" && (
        <div className="fit-step">
          <label className="login-field">
            <span>Dataset name (optional)</span>
            <input type="text" value={name} placeholder="Defaults to the file name"
                   onChange={(e) => setName(e.target.value)} />
          </label>
          <div className="dropzone" onClick={() => fileRef.current?.click()}
               onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); onFile(e.dataTransfer.files?.[0]); }}>
            <span className="dz-ic">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 16V4m0 0 4 4m-4-4-4 4" /><path d="M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3" />
              </svg>
            </span>
            <span className="dz-big">{busy ? "Reading…" : <>Drop a CSV here or <strong>click to browse</strong></>}</span>
            <input ref={fileRef} type="file" accept=".csv,text/csv" hidden onChange={(e) => onFile(e.target.files?.[0])} />
          </div>
          {error && <div className="error">{error}</div>}
        </div>
      )}

      {step === "enter" && (
        <div className="fit-step">
          <div className="seg" style={{ alignSelf: "flex-start" }}>
            <button className={"seg-btn" + (enterMode === "paste" ? " active" : "")} onClick={() => setEnterMode("paste")}>Paste</button>
            <button className={"seg-btn" + (enterMode === "form" ? " active" : "")} onClick={() => setEnterMode("form")}>Form</button>
          </div>
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
            </>
          ) : (
            <div className="ds-form">
              <div className="ds-form-cols">
                <span className="dist-label">Columns</span>
                <div className="ds-chips">
                  {ALL_FIELDS.map((f) => (
                    <button key={f} type="button" title={FIELDS[f]}
                            className={"ds-chip" + (cols.includes(f) ? " on" : "")}
                            onClick={() => toggleCol(f)}>{f}</button>
                  ))}
                </div>
                <p className="muted-line" style={{ margin: "0.3rem 0 0" }}>
                  Use <code>x</code> for values, or <code>xl</code>+<code>xr</code> for intervals.
                  {" "}<code>c</code> censoring, <code>n</code> counts, <code>tl</code>/<code>tr</code> truncation. Leave a cell blank for its default.
                </p>
              </div>
              {cols.length > 0 && (
                <div className="ds-grid-wrap">
                  <table className="ds-grid">
                    <thead><tr>{cols.map((c) => <th key={c}>{c}</th>)}<th /></tr></thead>
                    <tbody>
                      {rows.map((r, i) => (
                        <tr key={i}>
                          {cols.map((c) => (
                            <td key={c}>
                              <input type="number" step="any" value={r[c] ?? ""}
                                     onChange={(e) => setCell(i, c, e.target.value)} />
                            </td>
                          ))}
                          <td className="ds-grid-x">
                            {rows.length > 1 && (
                              <button type="button" title="Remove row"
                                      onClick={() => setRows((rs) => rs.filter((_, idx) => idx !== i))}>✕</button>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <button className="secondary" style={{ marginTop: "0.5rem" }}
                          onClick={() => setRows((rs) => [...rs, {}])}>+ Add row</button>
                </div>
              )}
              {!formMapping && <p className="hint">Include an <code>x</code> column, or both <code>xl</code> and <code>xr</code>.</p>}
            </div>
          )}
          {error && <div className="error">{error}</div>}
        </div>
      )}
    </Modal>
  );
}
