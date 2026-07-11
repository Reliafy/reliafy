import { useEffect, useMemo, useRef, useState } from "react";
import {
  getColumns,
  getDataset,
  getDegradationOptions,
  fitDegradation,
  listDatasets,
} from "../api.js";
import Modal from "./Modal.jsx";
import PreviewTable from "./PreviewTable.jsx";

// Three-step modal for fitting a degradation model, mirroring UploadModal:
// (1) pick a source (upload / saved dataset), (2) map item/time/measurement
// columns + set the failure threshold, (3) choose path model + options → fit.
const STEPS = ["Source", "Data", "Model"];

export default function DegradationNewModal({ onClose, onFitted }) {
  const [step, setStep] = useState(1);
  const [file, setFile] = useState(null);
  const [datasetId, setDatasetId] = useState(null);
  const [sourceName, setSourceName] = useState("");
  const [csv, setCsv] = useState(null); // { columns, preview, n_rows }
  const [mapping, setMapping] = useState({ i: "", x: "", y: "" });
  const [threshold, setThreshold] = useState("");
  const [unit, setUnit] = useState("");
  const [measurementUnit, setMeasurementUnit] = useState("");
  const [options, setOptions] = useState({ paths: [], distributions: [], population_methods: [] });
  const [path, setPath] = useState("best");
  const [distribution, setDistribution] = useState("weibull");
  const [populationMethod, setPopulationMethod] = useState("moments");
  const [datasets, setDatasets] = useState([]);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef(null);

  useEffect(() => {
    getDegradationOptions().then(setOptions).catch(() => {});
    listDatasets().then((d) => setDatasets(d.datasets)).catch(() => setDatasets([]));
  }, []);

  // Rough distinct-count of the mapped item column from the preview rows, as a
  // sanity hint (the fit needs at least 2 items).
  const itemHint = useMemo(() => {
    if (!csv || !mapping.i) return null;
    const idx = csv.columns.indexOf(mapping.i);
    if (idx === -1) return null;
    const distinct = new Set((csv.preview || []).map((row) => row[idx]));
    return distinct.size;
  }, [csv, mapping.i]);

  const pickFile = async (f) => {
    if (!f) return;
    setFile(f);
    setDatasetId(null);
    setSourceName(f.name);
    setError(null);
    setLoading(true);
    try {
      const cols = await getColumns(f);
      setCsv(cols);
      setMapping({ i: cols.columns[0] || "", x: cols.columns[1] || "", y: cols.columns[2] || "" });
      setStep(2);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const pickDataset = async (d) => {
    setFile(null);
    setDatasetId(d.id);
    setSourceName(d.name);
    setError(null);
    setLoading(true);
    try {
      const full = await getDataset(d.id);
      const columns = full.preview_columns || [];
      setCsv({ columns, preview: full.preview || [], n_rows: full.n_rows });
      setMapping({ i: columns[0] || "", x: columns[1] || "", y: columns[2] || "" });
      setStep(2);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const onDrop = (e) => {
    e.preventDefault();
    setDragging(false);
    pickFile(e.dataTransfer.files?.[0]);
  };

  const mappingValid =
    mapping.i && mapping.x && mapping.y &&
    new Set([mapping.i, mapping.x, mapping.y]).size === 3 &&
    threshold !== "" && Number.isFinite(Number(threshold));

  const onFit = async () => {
    if (!file && !datasetId) return;
    setLoading(true);
    setError(null);
    const fit = {
      datasetId,
      mapping,
      threshold: Number(threshold),
      path,
      distribution,
      populationMethod,
      unit,
      measurementUnit,
    };
    try {
      const result = await fitDegradation(file, fit);
      onFitted({ result, fit: { ...fit, file, datasetId: result.dataset_id } });
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const goBack = () => {
    setError(null);
    setStep((s) => Math.max(1, s - 1));
  };

  const stepper = (
    <div className="steps">
      {STEPS.map((label, i) => {
        const n = i + 1;
        return (
          <span className="step-wrap" key={label}>
            {i > 0 && <span className="sep" />}
            <span className={`step${step === n ? " active" : ""}`}>
              <span className="dot">{n}</span>
              {label}
            </span>
          </span>
        );
      })}
    </div>
  );

  let footer;
  if (step === 1) {
    footer = (
      <>
        {stepper}
        <span className="hint">Upload a CSV or pick a dataset to continue</span>
      </>
    );
  } else if (step === 2) {
    footer = (
      <>
        {stepper}
        <div className="row" style={{ margin: 0 }}>
          <button className="secondary" onClick={goBack} disabled={loading}>Back</button>
          <button onClick={() => setStep(3)} disabled={!mappingValid}>Next</button>
        </div>
      </>
    );
  } else {
    footer = (
      <>
        {stepper}
        <div className="row" style={{ margin: 0 }}>
          <button className="secondary" onClick={goBack} disabled={loading}>Back</button>
          <button onClick={onFit} disabled={loading}>
            {loading ? "Fitting…" : "Fit degradation model"}
          </button>
        </div>
      </>
    );
  }

  const select = (label, value, onChange, opts, disabledIds = []) => (
    <label className="login-field" style={{ flex: 1 }}>
      <span>{label}</span>
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        {opts.map((o) => (
          <option key={o.id} value={o.id} disabled={disabledIds.includes(o.id)}>{o.name}</option>
        ))}
      </select>
    </label>
  );

  const colSelect = (label, key) => (
    <label className="login-field" style={{ flex: 1 }}>
      <span>{label}</span>
      <select value={mapping[key]} onChange={(e) => setMapping({ ...mapping, [key]: e.target.value })}>
        <option value="">—</option>
        {csv.columns.map((c) => <option key={c} value={c}>{c}</option>)}
      </select>
    </label>
  );

  return (
    <Modal title="Fit a degradation model" onClose={onClose} locked={loading} footer={footer}>
      {step === 1 && (
        <>
          <div
            className={`dropzone${dragging ? " dragging" : ""}`}
            onClick={() => inputRef.current?.click()}
            onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
          >
            <span className="dz-ic">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 16V4m0 0 4 4m-4-4-4 4" />
                <path d="M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3" />
              </svg>
            </span>
            {loading ? (
              <span className="dz-big">Reading file…</span>
            ) : file ? (
              <span className="dz-big filename">{file.name}</span>
            ) : (
              <span className="dz-big">Drop a CSV here or <strong>click to browse</strong></span>
            )}
            <span className="dz-hint">long format: item id · time · measurement (one row per reading)</span>
            <input ref={inputRef} type="file" accept=".csv,text/csv" hidden onChange={(e) => pickFile(e.target.files?.[0])} />
          </div>

          {datasets.length > 0 && (
            <div className="recent">
              <div className="recent-h">Or use a saved dataset</div>
              {datasets.slice(0, 5).map((d) => (
                <button key={d.id} type="button" className="recent-row" disabled={loading} onClick={() => pickDataset(d)}>
                  <span className="recent-ic">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M14 3v5h5M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8z" />
                    </svg>
                  </span>
                  <span className="recent-name">{d.name}</span>
                  <span className="recent-meta">{d.n_rows.toLocaleString()} rows · {d.n_columns} cols</span>
                </button>
              ))}
            </div>
          )}
        </>
      )}

      {step === 2 && csv && (
        <>
          <p className="muted-line" style={{ marginTop: 0 }}>
            {sourceName} · {csv.n_rows} rows · {csv.columns.length} columns
          </p>
          <PreviewTable columns={csv.columns} rows={csv.preview} />
          <div className="row" style={{ gap: "0.8rem" }}>
            {colSelect("Item id column", "i")}
            {colSelect("Time column", "x")}
            {colSelect("Measurement column", "y")}
          </div>
          <div className="row" style={{ gap: "0.8rem" }}>
            <label className="login-field" style={{ flex: 1 }}>
              <span>Failure threshold *</span>
              <input type="number" step="any" value={threshold} placeholder="e.g. 8.0"
                     onChange={(e) => setThreshold(e.target.value)} />
            </label>
            <label className="login-field" style={{ flex: 1 }}>
              <span>Time unit</span>
              <input type="text" value={unit} placeholder="hours" onChange={(e) => setUnit(e.target.value)} />
            </label>
            <label className="login-field" style={{ flex: 1 }}>
              <span>Measurement unit</span>
              <input type="text" value={measurementUnit} placeholder="mm" onChange={(e) => setMeasurementUnit(e.target.value)} />
            </label>
          </div>
          {itemHint !== null && itemHint < 2 && (
            <p className="hint">Only {itemHint} distinct item id in the preview — the fit needs at least 2 items.</p>
          )}
          {!mappingValid && (
            <p className="hint" style={{ marginTop: "0.6rem" }}>
              Map three different columns and set a numeric threshold.
            </p>
          )}
        </>
      )}

      {step === 3 && (
        <>
          <p className="muted-line" style={{ marginTop: 0 }}>
            The path model describes how the measurement evolves with time.
            "Best" tries all nine and picks the lowest AICc (a few seconds).
          </p>
          <div className="row" style={{ gap: "0.8rem" }}>
            {select("Degradation path", path, setPath, options.paths)}
            {select("Life distribution", distribution, setDistribution, options.distributions)}
            {select("Population method", populationMethod, setPopulationMethod, options.population_methods)}
          </div>
        </>
      )}

      {error && <div className="error">{error}</div>}
    </Modal>
  );
}
