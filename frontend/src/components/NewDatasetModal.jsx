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
// One comma-separated value list per field. Canonical column order for the CSV.
const FIELD_ORDER = ["x", "xl", "xr", "c", "n", "tl", "tr"];
const FIELDS = {
  x: "Observed values (exact or censored)",
  c: "Censor flag per value: 0 exact · 1 right · -1 left · 2 interval",
  n: "Count of identical observations",
  xl: "Interval lower bounds (with xr)",
  xr: "Interval upper bounds (with xl)",
  tl: "Left truncation bounds",
  tr: "Right truncation bounds",
};
const splitList = (s) => String(s || "").split(",").map((v) => v.trim());
const listLen = (s) => {
  const parts = splitList(s);
  while (parts.length && parts[parts.length - 1] === "") parts.pop();
  return parts.length;
};

// One labelled comma-separated value list for a survival field. When
// ``broadcast`` is set, a single value is treated as applying to every row.
function ListField({ f, v, onChange, disabled, placeholder, broadcast }) {
  const n = disabled ? 0 : listLen(v || "");
  const label = n === 0 ? "" : broadcast && n === 1 ? "all rows" : `${n} value${n === 1 ? "" : "s"}`;
  return (
    <label className={"ds-listfield" + (disabled ? " disabled" : "")} title={FIELDS[f]}>
      <span className="ds-listbadge">{f}</span>
      <input type="text" className="ds-listinput" value={v || ""} disabled={disabled}
             placeholder={placeholder} spellCheck={false}
             onChange={(e) => onChange(f, e.target.value)} />
      <span className="ds-listcount">{label}</span>
    </label>
  );
}

export default function NewDatasetModal({ onClose, onCreated }) {
  const [step, setStep] = useState("choose"); // choose | upload | enter
  const [enterMode, setEnterMode] = useState("paste"); // paste | form
  const [name, setName] = useState("");
  const [noHeader, setNoHeader] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const fileRef = useRef(null);

  // paste
  const [text, setText] = useState("");
  const preview = useMemo(() => parsePreview(text), [text]);

  // form — one comma-separated value list per field
  const [vals, setVals] = useState({});
  const setVal = (f, v) => setVals((cur) => ({ ...cur, [f]: v }));

  const reset = () => { setError(null); };
  const back = () => { reset(); setStep("choose"); };

  // --- upload ---
  const onFile = async (file) => {
    if (!file) return;
    setBusy(true); setError(null);
    try {
      const ds = await uploadDataset(file, name.trim() || undefined, noHeader);
      onCreated(ds);
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  };

  // --- paste ---
  const pasteValid = name.trim() && preview && preview.nCols > 1;
  const onPaste = async () => {
    setBusy(true); setError(null);
    try { onCreated(await pasteDataset(name.trim(), text, noHeader)); }
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
  const lengthsMatch = active.every((f) => isBroadcast(f) || listLen(vals[f]) === rowCount);
  const formValid = name.trim() && hasValue && rowCount > 0 && lengthsMatch;

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
          <label className="ds-check">
            <input type="checkbox" checked={noHeader} onChange={(e) => setNoHeader(e.target.checked)} />
            <span>No header row — the first row is data. Columns are named <code>col 1</code>, <code>col 2</code>, …</span>
          </label>
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
              <label className="ds-check">
                <input type="checkbox" checked={noHeader} onChange={(e) => setNoHeader(e.target.checked)} />
                <span>No header row — the first row is data. Columns are named <code>col 1</code>, <code>col 2</code>, …</span>
              </label>
            </>
          ) : (
            <div className="ds-form">
              <p className="muted-line" style={{ marginTop: 0 }}>
                Enter each field as a comma-separated list — one value per
                observation, so every list has the same length. Use <code>x</code>{" "}
                for values, or <code>xl</code>+<code>xr</code> for intervals.
                <code>c</code> and <code>n</code> are optional (blank means all
                exact, one each); a single <code>tl</code>/<code>tr</code> applies
                to every row.
              </p>
              <ListField f="x" v={vals.x} onChange={setVal} disabled={fieldDisabled("x")}
                         placeholder="1240, 980, 1500, 2100" />
              <div className="ds-pair">
                <ListField f="xl" v={vals.xl} onChange={setVal} disabled={fieldDisabled("xl")} placeholder="100, 200" />
                <ListField f="xr" v={vals.xr} onChange={setVal} disabled={fieldDisabled("xr")} placeholder="150, 250" />
              </div>
              <ListField f="c" v={vals.c} onChange={setVal} placeholder="optional · 0 for all" />
              <ListField f="n" v={vals.n} onChange={setVal} placeholder="optional · 1 for all" />
              <div className="ds-pair">
                <ListField f="tl" v={vals.tl} onChange={setVal} placeholder="50 or per-row" broadcast />
                <ListField f="tr" v={vals.tr} onChange={setVal} placeholder="optional" broadcast />
              </div>
              {!hasValue && <p className="hint">Enter <code>x</code> values, or both <code>xl</code> and <code>xr</code>.</p>}
              {hasValue && !lengthsMatch && (
                <p className="hint">
                  Each list needs the same number of values (found{" "}
                  {active.filter((f) => !isBroadcast(f)).map((f) => `${f}: ${listLen(vals[f])}`).join(", ")}).
                </p>
              )}
            </div>
          )}
          {error && <div className="error">{error}</div>}
        </div>
      )}
    </Modal>
  );
}
