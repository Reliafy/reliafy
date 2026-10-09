import { useEffect, useRef, useState } from "react";
import {
  getColumns,
  getDataset,
  getDegradationOptions,
  listDatasets,
  saveDegradationModel,
  SPREADSHEET_ACCEPT,
} from "../api.js";
import { TIME_UNITS, distinctCount, guessMeasurementUnit, guessTimeUnit, usableForDegradation } from "../degradation.js";
import { useSpreadsheet } from "./ExcelSheetPicker.jsx";
import Modal from "./Modal.jsx";
import Select from "./Select.jsx";
import PreviewTable from "./PreviewTable.jsx";

// Three-step modal for fitting a degradation model, mirroring the FitFlow steps:
// (1) pick a source (upload / saved dataset), (2) map item/time/measurement
// columns + set the failure threshold, (3) choose path model + options, then
// fit and save in one go: ``onSaved(model)`` gets the saved model, so the
// caller can open its page (the confidence inputs need a saved model).
const STEPS = ["Source", "Data", "Model"];

// "Brake pad wear (sample)" / "wear.csv" → "Brake pad wear" / "wear".
const baseName = (s) => String(s || "").replace(/\s*\(sample\)\s*$/i, "").replace(/\.(csv|xlsx?|xlsm)$/i, "").trim();

export default function DegradationNewModal({ onClose, onSaved }) {
  const [step, setStep] = useState(1);
  // An Excel workbook becomes a CSV of the chosen sheet before anything else.
  const { toCsv, modal: sheetModal } = useSpreadsheet();
  const [file, setFile] = useState(null);
  const [datasetId, setDatasetId] = useState(null);
  const [sourceName, setSourceName] = useState("");
  const [csv, setCsv] = useState(null); // { columns, preview, n_rows }
  const [mapping, setMapping] = useState({ i: "", x: "", y: "" });
  const [threshold, setThreshold] = useState("");
  // null until typed: then the units read from the mapped columns' names
  // ("hours" → Hours, "wear_mm" → mm) fill the fields.
  const [unitTyped, setUnitTyped] = useState(null);
  const [measurementUnitTyped, setMeasurementUnitTyped] = useState(null);
  const [nameTyped, setNameTyped] = useState(null);
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

  const unit = unitTyped ?? guessTimeUnit(mapping.x);
  const measurementUnit = measurementUnitTyped ?? guessMeasurementUnit(mapping.y);
  const pathName = (options.paths || []).find((p) => p.id === path)?.name;
  const name = nameTyped ?? `${baseName(sourceName) || "Degradation"} — ${
    path !== "best" && pathName ? `${pathName.toLowerCase()} degradation` : "degradation"}`;
  // Only the saved datasets the fit can use: item id, time and measurement.
  const usable = datasets.filter(usableForDegradation);

  // Distinct ids in the mapped item column over every row (the fit needs at
  // least 2 items); null when unknown, and then the wizard says nothing.
  const itemCount = distinctCount(csv, mapping.i);

  // A new source starts with units and name read afresh.
  const resetTyped = () => {
    setUnitTyped(null);
    setMeasurementUnitTyped(null);
    setNameTyped(null);
  };

  const pickFile = async (picked) => {
    if (!picked) return;
    const f = await toCsv(picked);
    if (!f) return;
    setFile(f);
    setDatasetId(null);
    setSourceName(f.name);
    resetTyped();
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
    resetTyped();
    setError(null);
    setLoading(true);
    try {
      const full = await getDataset(d.id);
      const columns = full.preview_columns || [];
      setCsv({ columns, preview: full.preview || [], n_rows: full.n_rows, n_unique: full.n_unique });
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
    threshold !== "" && Number.isFinite(Number(threshold)) &&
    !(itemCount !== null && itemCount < 2);

  const onFit = async () => {
    if ((!file && !datasetId) || !name.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const saved = await saveDegradationModel(name.trim(), file, {
        datasetId,
        mapping,
        threshold: Number(threshold),
        path,
        distribution,
        populationMethod,
        unit: unit.trim(),
        measurementUnit: measurementUnit.trim(),
      });
      onSaved(saved);
    } catch (err) {
      setError(err.message);
      setLoading(false);
    }
  };

  const goBack = () => {
    setError(null);
    setStep((s) => Math.max(1, s - 1));
  };

  const stepper = (
    <div className="steps" style={{ flexWrap: "wrap", rowGap: 6 }}>
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

  // The stepper sits under the title; the footer holds only the next step.
  let footer;
  if (step === 1) {
    footer = <span className="hint">Upload a CSV or Excel file, or pick a dataset, to continue</span>;
  } else if (step === 2) {
    footer = (
      <div className="row" style={{ margin: "0 0 0 auto" }}>
        <button className="secondary" onClick={goBack} disabled={loading}>Back</button>
        <button onClick={() => setStep(3)} disabled={!mappingValid}>Next</button>
      </div>
    );
  } else {
    footer = (
      <div className="row" style={{ margin: "0 0 0 auto" }}>
        <button className="secondary" onClick={goBack} disabled={loading}>Back</button>
        <button onClick={onFit} disabled={loading || !name.trim()}>
          {loading ? "Fitting…" : "Fit and save"}
        </button>
      </div>
    );
  }

  const select = (label, value, onChange, opts, disabledIds = []) => (
    <label className="login-field" style={{ flex: 1 }}>
      <span>{label}</span>
      <Select
        value={value}
        onChange={onChange}
        options={opts.map((o) => ({ value: o.id, label: o.name, disabled: disabledIds.includes(o.id) }))}
      />
    </label>
  );

  const colSelect = (label, key) => (
    <label className="login-field" style={{ flex: 1 }}>
      <span>{label}</span>
      <Select
        value={mapping[key]}
        onChange={(v) => setMapping({ ...mapping, [key]: v })}
        options={[{ value: "", label: "—" }, ...csv.columns]}
      />
    </label>
  );

  return (
    <Modal title="Fit a degradation model" onClose={onClose} locked={loading} footer={footer}>
      <div style={{ marginBottom: 20 }}>{stepper}</div>
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
              <span className="dz-big">Drop a CSV or Excel file here or <strong>click to browse</strong></span>
            )}
            <span className="dz-hint">long format: item id · time · measurement (one row per reading)</span>
            <input ref={inputRef} type="file" accept={`.csv,text/csv,${SPREADSHEET_ACCEPT}`} hidden
                   onChange={(e) => { pickFile(e.target.files?.[0]); e.target.value = ""; }} />
            {sheetModal}
          </div>

          {usable.length > 0 && (
            <div className="recent">
              <div className="recent-h">Or use a saved dataset</div>
              {usable.slice(0, 5).map((d) => (
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
              <input type="text" list="deg-time-units" value={unit} placeholder="e.g. Hours"
                     onChange={(e) => setUnitTyped(e.target.value)} />
              <datalist id="deg-time-units">
                {TIME_UNITS.map((u) => <option value={u} key={u} />)}
              </datalist>
            </label>
            <label className="login-field" style={{ flex: 1 }}>
              <span>Measurement unit</span>
              <input type="text" value={measurementUnit} placeholder="e.g. mm"
                     onChange={(e) => setMeasurementUnitTyped(e.target.value)} />
            </label>
          </div>
          {itemCount !== null && itemCount < 2 ? (
            <p className="hint">
              The item id column has {itemCount === 1 ? "only 1 distinct value" : "no values"}: the fit needs at least 2 items.
            </p>
          ) : !mappingValid && (
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
          <label className="login-field">
            <span>Model name</span>
            <input type="text" value={name} onChange={(e) => setNameTyped(e.target.value)} />
          </label>
        </>
      )}

      {error && <div className="error">{error}</div>}
    </Modal>
  );
}
