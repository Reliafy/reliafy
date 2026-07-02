import { useRef, useState } from "react";
import { getColumns, compareModels } from "../api.js";
import Modal from "./Modal.jsx";
import ColumnMapper from "./ColumnMapper.jsx";
import Units from "./Units.jsx";
import PreviewTable from "./PreviewTable.jsx";

const EMPTY_MAPPING = { x: "", c: "", n: "", xl: "", xr: "", tl: "", tr: "" };

// Upload a CSV and map columns, then fit + rank every parametric distribution.
export default function CompareModal({ onClose, onCompared }) {
  const [step, setStep] = useState(1);
  const [file, setFile] = useState(null);
  const [csv, setCsv] = useState(null);
  const [mapping, setMapping] = useState(EMPTY_MAPPING);
  const [unit, setUnit] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef(null);

  const pickFile = async (f) => {
    if (!f) return;
    setFile(f);
    setError(null);
    setLoading(true);
    try {
      const cols = await getColumns(f);
      setCsv(cols);
      setMapping({ ...EMPTY_MAPPING, x: cols.columns[0] || "" });
      setStep(2);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const mappingValid = mapping.x
    ? !mapping.xl && !mapping.xr
    : !!mapping.xl && !!mapping.xr;

  const onCompare = async () => {
    if (!file) return;
    setLoading(true);
    setError(null);
    try {
      const result = await compareModels(file, mapping, unit);
      onCompared(result);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const footer =
    step === 1 ? (
      <span className="hint">Upload a CSV of failure/censored times to continue</span>
    ) : (
      <div className="row" style={{ margin: 0 }}>
        <button
          className="secondary"
          onClick={() => setStep(1)}
          disabled={loading}
        >
          Back
        </button>
        <button onClick={onCompare} disabled={!mappingValid || loading}>
          {loading ? "Comparing…" : "Compare distributions"}
        </button>
      </div>
    );

  return (
    <Modal title="Compare distributions" onClose={onClose} locked={loading} footer={footer}>
      {step === 1 && (
        <div
          className={`dropzone${dragging ? " dragging" : ""}`}
          onClick={() => inputRef.current?.click()}
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragging(false);
            pickFile(e.dataTransfer.files?.[0]);
          }}
        >
          {loading ? (
            <span>Reading file…</span>
          ) : file ? (
            <span className="filename">{file.name}</span>
          ) : (
            <span>
              Drop a CSV here or <strong>click to browse</strong>
            </span>
          )}
          <input
            ref={inputRef}
            type="file"
            accept=".csv,text/csv"
            hidden
            onChange={(e) => pickFile(e.target.files?.[0])}
          />
        </div>
      )}

      {step === 2 && csv && (
        <>
          <p className="muted-line" style={{ marginTop: 0 }}>
            {file?.name} · {csv.n_rows} rows · {csv.columns.length} columns
          </p>
          <PreviewTable columns={csv.columns} rows={csv.preview} />
          <ColumnMapper columns={csv.columns} mapping={mapping} onChange={setMapping} />
          <Units value={unit} onChange={setUnit} />
          {!mappingValid && (
            <p className="hint" style={{ marginTop: "1rem" }}>
              Map a column to <code>x</code>, or to both <code>xl</code> and{" "}
              <code>xr</code>.
            </p>
          )}
        </>
      )}

      {error && <div className="error">{error}</div>}
    </Modal>
  );
}
