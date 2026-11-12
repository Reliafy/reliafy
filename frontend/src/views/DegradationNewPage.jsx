import { useEffect, useMemo, useRef, useState } from "react";
import { useDatasetSplit } from "../components/DatasetSplit.jsx";
import { useNavigate, useSearchParams } from "react-router-dom";
import { DataSourceStep } from "../components/DatasetPicker.jsx";
import { ErrorNotice } from "../components/StorageCap.jsx";
import {
  getColumns,
  getDataset,
  getDegradationOptions,
  listDatasets,
  saveDegradationModel,
  SPREADSHEET_ACCEPT,
} from "../api.js";
import {
  DEGRADATION_KEYS, DEGRADATION_ROWS, DEGRADATION_WORDS, degradationIssues, guessDegradationColumns, guessDirection,
  guessMeasurementUnit, guessTimeUnit, thresholdProblem, usableForDegradation,
} from "../degradation.js";
import ColumnMapper from "../components/ColumnMapper.jsx";
import SegmentedControl from "../components/ui/SegmentedControl.jsx";
import { useSpreadsheet } from "../components/ExcelSheetPicker.jsx";
import Select from "../components/Select.jsx";
import PreviewTable from "../components/PreviewTable.jsx";
import HeaderNote, { detectHeader } from "../components/HeaderNote.jsx";

// New degradation model (/models/degradation/new) — a three-step page like the
// accelerated-life one: (1) pick a source (upload / saved dataset), (2) map
// the columns (i, x, m: the shared selectors), (3) the model's own inputs:
// the failure threshold and the path model, then fit and save in one go and
// open the saved model's page (the confidence inputs need a saved model).
const STEPS = ["Source", "Data", "Model"];
// The fit needs an item id, a time and a measurement column: in the readings (the measurements
// part, when the dataset has one), the table the fit reads.
const degradationRule = (d) => (usableForDegradation(d.measurements || d)
  ? null : "Needs an item id, a time and a measurement column.");

// "Brake pad wear (sample)" / "wear.csv" → "Brake pad wear" / "wear".
const baseName = (s) => String(s || "").replace(/\s*\(sample\)\s*$/i, "").replace(/\.(csv|xlsx?|xlsm)$/i, "").trim();

export default function DegradationNewPage() {
  const navigate = useNavigate();
  // ?dataset= (the Data list's Fit menu) starts the flow on that dataset.
  const [params] = useSearchParams();
  const fromData = params.get("dataset");
  const [step, setStep] = useState(1);
  // An Excel workbook becomes a CSV of the chosen sheet before anything else.
  const { toCsv, modal: sheetModal } = useSpreadsheet();
  const [file, setFile] = useState(null);
  const [headerNote, setHeaderNote] = useState(null); // a file with no header row (#434)
  const [datasetId, setDatasetId] = useState(null);
  const [sourceName, setSourceName] = useState("");
  const [csv, setCsv] = useState(null); // { columns, preview, n_rows }
  const [mapping, setMapping] = useState({ i: "", x: "", y: "" });
  const [threshold, setThreshold] = useState("");
  // Which way m goes to failure: a check on the threshold (the fit reads each item's path).
  const [direction, setDirection] = useState(null);
  // null until typed: then the units read from the mapped columns' names
  // ("hours" → Hours, "wear_mm" → mm) fill the fields.
  const [unitTyped, setUnitTyped] = useState(null);
  const [measurementUnitTyped, setMeasurementUnitTyped] = useState(null);
  const [nameTyped, setNameTyped] = useState(null);
  const [options, setOptions] = useState({ paths: [], distributions: [], population_methods: [] });
  const [path, setPath] = useState("best");
  const [distribution, setDistribution] = useState("weibull");
  const [populationMethod, setPopulationMethod] = useState("moments");
  const [datasets, setDatasets] = useState(null); // null while the list loads
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef(null);

  useEffect(() => {
    getDegradationOptions().then(setOptions).catch(() => {});
    listDatasets().then((d) => setDatasets(d.datasets || [])).catch(() => setDatasets([]));
  }, []);

  const unit = unitTyped ?? guessTimeUnit(mapping.x);
  const measurementUnit = measurementUnitTyped ?? guessMeasurementUnit(mapping.y);
  const pathName = (options.paths || []).find((p) => p.id === path)?.name;
  const name = nameTyped ?? `${baseName(sourceName) || "Degradation"} — ${
    path !== "best" && pathName ? `${pathName.toLowerCase()} degradation` : "degradation"}`;

  // What stops the Data step, beside its selector (at least 2 items, each read twice).
  const dataIssues = csv ? degradationIssues(csv, mapping) : [];
  const way = direction ?? guessDirection(csv, mapping);

  // A new source starts with units and name read afresh.
  const resetTyped = () => {
    setUnitTyped(null);
    setMeasurementUnitTyped(null);
    setNameTyped(null);
  };

  const pickFile = async (picked, { keepHeader = false } = {}) => {
    if (!picked) return;
    const csvFile = await toCsv(picked);
    if (!csvFile) return;
    const { file: f, note } = await detectHeader(picked, csvFile, { keepHeader });
    setHeaderNote(note);
    setFile(f);
    setDatasetId(null);
    setSourceName(f.name);
    resetTyped();
    setError(null);
    setLoading(true);
    try {
      const cols = await getColumns(f);
      setCsv(cols);
      setMapping(guessDegradationColumns(cols.columns));
      setStep(2);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const pickDataset = async (d) => {
    setFile(null);
    setHeaderNote(null);
    setDatasetId(d.id);
    setSourceName(d.name);
    resetTyped();
    setError(null);
    setLoading(true);
    try {
      const full = await getDataset(d.id);
      if (!d.name) setSourceName(full.name || "");
      // The readings: the dataset's measurements part when it has one, else its one table.
      const table = full.measurements || full;
      const columns = table.preview_columns || [];
      setCsv({ columns, preview: table.preview || [], n_rows: table.n_rows, n_unique: table.n_unique });
      setMapping(guessDegradationColumns(columns));
      setStep(2);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (fromData) pickDataset({ id: fromData, name: "" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fromData]);

  const onDrop = (e) => {
    e.preventDefault();
    setDragging(false);
    pickFile(e.dataTransfer.files?.[0]);
  };

  const mappingValid = dataIssues.length === 0;
  // "dataset": one sheet split into several datasets by a column (DatasetSplit.jsx).
  const splitSpec = useMemo(() => ({
    needs: [{ row: "i", col: mapping.i, number: false }, { row: "x", col: mapping.x }, { row: "m", col: mapping.y }],
    failed: false, items: mapping.i,
  }), [mapping]);
  const split = useDatasetSplit({
    file: datasetId ? null : file, columns: csv?.columns || [], mapping, spec: splitSpec,
    reading: { kind: "degradation", mapping, unit },
    fitTo: (id) => `/models/degradation/new?dataset=${encodeURIComponent(id)}`,
  });
  const thresholdWhy = csv ? thresholdProblem(csv, mapping, threshold, way, measurementUnit) : null;
  // A number is required; the first-reading check is said, not blocking (one item may start past it).
  const thresholdBlocks = threshold === "" || !Number.isFinite(Number(threshold));

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
      navigate(`/models/degradation/${saved.id}`);
    } catch (err) {
      setError(err);
      setLoading(false);
    }
  };

  const goBack = () => {
    setError(null);
    if (step === 1) return navigate("/models/degradation");
    setStep((s) => s - 1);
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

  // The foot holds the stepper and the next step, as on the accelerated-life page.
  let nav;
  if (step === 1) {
    nav = (<><button className="secondary" onClick={goBack} disabled={loading}>Cancel</button>
      <span className="hint" style={{ margin: 0 }}>Pick a dataset and press <b>Use this dataset</b>, or upload a CSV or Excel file</span></>);
  } else if (step === 2 && split.saved) {
    nav = <button className="secondary" onClick={() => navigate("/models/degradation")}>Done</button>;
  } else if (step === 2 && split.active) {
    const why = !mappingValid ? "First settle the notes beside the selectors." : split.waitingFor;
    nav = (<><button className="secondary" onClick={goBack} disabled={split.saving}>Back</button>
      {why && <span className="hint ds-next-why" role="status" style={{ margin: 0 }}>{why}</span>}
      <button onClick={split.save} disabled={!mappingValid || !split.canSave}>{split.saveLabel}</button></>);
  } else if (step === 2) {
    nav = (<><button className="secondary" onClick={goBack} disabled={loading}>Back</button>
      {!mappingValid && (
        <span className="hint ds-next-why" role="status" style={{ margin: 0 }}>
          First settle the note{new Set(dataIssues.map((i) => i.row)).size === 1 ? "" : "s"} beside {[...new Set(dataIssues.map((i) => i.row))].join(", ")}.
        </span>
      )}
      <button onClick={() => setStep(3)} disabled={!mappingValid}>Next</button></>);
  } else {
    nav = (<><button className="secondary" onClick={goBack} disabled={loading}>Back</button>
      {thresholdBlocks && <span className="hint ds-next-why" role="status" style={{ margin: 0 }}>First enter the failure threshold.</span>}
      <button onClick={onFit} disabled={loading || !name.trim() || thresholdBlocks}>
        {loading ? "Fitting…" : "Fit and save"}
      </button></>);
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
    <div className="app">
      <header>
        <div>
          <div className="crumb">
            <button className="crumb-link" onClick={() => navigate("/models")}>Model</button> /{" "}
            <button className="crumb-link" onClick={() => navigate("/models/degradation")}>Degradation</button> /{" "}
            <b>New model</b>
          </div>
          <h1>Fit a degradation model</h1>
        </div>
      </header>

      <div className="card fit-flow">
        <div className="fit-flow-head">{stepper}</div>
        {step === 1 && (
          <>
            <DataSourceStep
              kind="degradation"
              datasets={datasets}
              onUse={pickDataset}
              busy={loading}
              extra={degradationRule}
              part="measurements"
              upload={(
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
                </>
              )}
            />
          </>
        )}

        {step === 2 && split.saved && split.savedList}

        {step === 2 && csv && !split.saved && (
          <>
            <p className="muted-line" style={{ marginTop: 0 }}>
              {sourceName} · {csv.n_rows} rows
            </p>
            <HeaderNote note={headerNote} onPick={pickFile} disabled={loading} />
            <PreviewTable columns={csv.columns} rows={csv.preview} />
            <ColumnMapper
              columns={csv.columns}
              mapping={mapping}
              onChange={setMapping}
              unit={unit}
              onUnitChange={setUnitTyped}
              mUnit={measurementUnit}
              onMUnitChange={setMeasurementUnitTyped}
              rows={DEGRADATION_ROWS}
              range={false}
              keys={DEGRADATION_KEYS}
              words={DEGRADATION_WORDS}
              issues={[...dataIssues, ...split.issues]}
              top={split.picker}
            />
            {split.summary}
          </>
        )}

        {step === 3 && (
          <>
            <label className="login-field" style={{ marginTop: 0 }}>
              <span>Model name</span>
              <input type="text" value={name} onChange={(e) => setNameTyped(e.target.value)} />
            </label>
            {/* The model's own inputs: when an item counts as failed, and the path's shape. */}
            <div className="xcn">
              <div className="xcn-row">
                <span className="xcn-key"><code>Fixed inputs</code><span className="xcn-words">when an item counts as failed</span></span>
                <div className="xcn-fields">
                  <span className="xcn-words">Fails when <code>m</code></span>
                  <SegmentedControl size="sm" label="Which way m goes to failure" value={way} onChange={setDirection}
                                    options={[{ value: "falls", label: "falls to" }, { value: "rises", label: "rises to" }]} />
                  <input className="units-input deg-threshold" type="number" step="any" value={threshold}
                         aria-label="Failure threshold" placeholder="e.g. 3"
                         onChange={(e) => setThreshold(e.target.value)} />
                  <span className="xcn-words">{measurementUnit ? `(in ${measurementUnit})` : "(in m's unit)"}</span>
                </div>
                {thresholdWhy && <div className="xcn-below"><p className="xcn-issue" role="status">{thresholdWhy}</p></div>}
              </div>
              <div className="xcn-row">
                <span className="xcn-key"><code>Path</code><span className="xcn-words">the shape a reading follows on each item</span></span>
                <div className="xcn-fields">
                  <Select value={path} onChange={setPath} ariaLabel="Degradation path" className="xcn-pick"
                          options={(options.paths || []).map((o) => ({ value: o.id, label: o.name }))} />
                </div>
              </div>
            </div>
            <details className="deg-advanced" style={{ marginTop: "0.8rem" }}>
              <summary>Advanced (the defaults are fine)</summary>
              <div className="row" style={{ gap: "0.8rem" }}>
                {select("Life distribution", distribution, setDistribution, options.distributions)}
                {select("Population method", populationMethod, setPopulationMethod, options.population_methods)}
              </div>
              <ul className="hint deg-advanced-notes">
                <li><b>Life distribution</b>: the shape of the spread in when items reach the threshold.</li>
                <li><b>Population method</b>: how the items' paths are pooled into one model for the whole population.</li>
              </ul>
            </details>
          </>
        )}

        <ErrorNotice error={error} />

        <div className="fit-flow-foot">
          <div className="row" style={{ margin: 0 }}>{nav}</div>
        </div>
      </div>
    </div>
  );
}
