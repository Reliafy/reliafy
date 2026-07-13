import { useMemo, useState } from "react";
import Modal from "./Modal.jsx";
import PreviewTable from "./PreviewTable.jsx";
import { pasteDataset } from "../api.js";

// Quick client-side sniff for the live preview only — the server does the
// authoritative parse. Picks whichever delimiter yields the most columns.
function sniff(text) {
  const firstLine = (text.split(/\r?\n/).find((l) => l.trim()) || "");
  const counts = { "\t": (firstLine.match(/\t/g) || []).length,
                   ",": (firstLine.match(/,/g) || []).length,
                   ";": (firstLine.match(/;/g) || []).length };
  const delim = Object.entries(counts).sort((a, b) => b[1] - a[1])[0];
  return delim[1] > 0 ? delim[0] : ",";
}

function parsePreview(text, rows = 5) {
  const lines = text.split(/\r?\n/).filter((l) => l.trim());
  if (lines.length < 2) return null;
  const d = sniff(text);
  const split = (l) => l.split(d).map((c) => c.trim());
  const columns = split(lines[0]);
  const preview = lines.slice(1, rows + 1).map(split);
  return { columns, preview, nRows: lines.length - 1, nCols: columns.length };
}

// Paste tabular data (CSV or copied straight from a spreadsheet) to create a
// dataset — no file needed.
export default function PasteDataModal({ onClose, onCreated }) {
  const [name, setName] = useState("");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const preview = useMemo(() => parsePreview(text), [text]);
  const valid = name.trim() && preview && preview.nCols > 1;

  const onSave = async () => {
    setBusy(true);
    setError(null);
    try {
      const ds = await pasteDataset(name.trim(), text);
      onCreated(ds);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      title="Paste data"
      onClose={onClose}
      locked={busy}
      footer={
        <div className="row" style={{ margin: 0, marginLeft: "auto" }}>
          <button className="secondary" onClick={onClose} disabled={busy}>Cancel</button>
          <button onClick={onSave} disabled={!valid || busy}>{busy ? "Creating…" : "Create dataset"}</button>
        </div>
      }
    >
      <div className="fit-step">
        <p className="muted-line">
          Paste rows from a spreadsheet or a CSV — include a header row. Columns
          can be separated by commas or tabs.
        </p>
        <label className="login-field">
          <span>Dataset name</span>
          <input type="text" autoFocus value={name} placeholder="e.g. Pump bearing lives"
                 onChange={(e) => setName(e.target.value)} />
        </label>
        <label className="login-field">
          <span>Data</span>
          <textarea
            className="paste-area"
            value={text}
            placeholder={"hours,failed\n1240,1\n980,1\n1500,0"}
            spellCheck={false}
            onChange={(e) => setText(e.target.value)}
          />
        </label>
        {preview ? (
          <div>
            <div className="ds-section-h">
              Preview · {preview.nRows} row{preview.nRows === 1 ? "" : "s"} · {preview.nCols} column{preview.nCols === 1 ? "" : "s"}
            </div>
            <PreviewTable columns={preview.columns} rows={preview.preview} />
            {preview.nCols === 1 && (
              <p className="hint">Only one column detected — check the values are comma- or tab-separated.</p>
            )}
          </div>
        ) : text.trim() ? (
          <p className="hint">Add a header row and at least one data row.</p>
        ) : null}
        {error && <div className="error">{error}</div>}
      </div>
    </Modal>
  );
}
