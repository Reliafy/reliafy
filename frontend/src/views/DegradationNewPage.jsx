import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { DataSourceStep } from "../components/DatasetPicker.jsx";
import { ErrorNotice } from "../components/StorageCap.jsx";
import {
  getDataset,
  getDegradationOptions,
  listDatasets,
  saveDegradationModel,
  SPREADSHEET_ACCEPT,
} from "../api.js";
import {
  degradationIssues, degradationMappingFromReading, guessDirection, thresholdProblem, usableForDegradation,
} from "../degradation.js";
import { emptyReading } from "../datasetReading.js";
import { useDatasetReading } from "../useDatasetReading.js";
import { columnFacts } from "../lifeData.js";
import ReadingSummary, { ReadingChange } from "../components/ReadingSummary.jsx";
import MeasurementsReadingChange from "../components/MeasurementsReadingChange.jsx";
import NewDatasetModal from "../components/NewDatasetModal.jsx";
import SegmentedControl from "../components/ui/SegmentedControl.jsx";
import Select from "../components/Select.jsx";

// New degradation model (/models/degradation/new) — a two-step page: (1) pick
// a saved dataset, or upload a file (saved first as a dataset, with how its
// columns are read, through the Data library's own dialog); (2) the model: the
// dataset's reading in one line (i, x and m, with Change), then the failure
// threshold and the path model; fit and save in one go and open the saved
// model's page (the confidence inputs need a saved model). The columns are
// never asked again: they come from the dataset's reading
// (degradationMappingFromReading).
const STEPS = ["Source", "Model"];
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
  // A file to save as a dataset first (the upload screen), then fit from.
  const [pending, setPending] = useState(null);
  const [datasetId, setDatasetId] = useState(null);
  const [detail, setDetail] = useState(null); // the dataset's detail (getDataset)
  const [sourceName, setSourceName] = useState("");
  const [threshold, setThreshold] = useState("");
  // Which way m goes to failure: a check on the threshold (the fit reads each item's path).
  const [direction, setDirection] = useState(null);
  const [nameTyped, setNameTyped] = useState(null);
  const [measEditing, setMeasEditing] = useState(false);
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

  // How the dataset is read (kept with it): the readings are its measurements
  // part when it has one, else its one table.
  const rd = useDatasetReading(detail);
  const hasPart = !!detail?.measurements;
  // The measurements' reading comes with every detail (kept, or guessed by the server).
  const meas = rd.reading?.measurements || detail?.reading?.measurements || null;
  const reading = hasPart ? { ...(rd.reading || emptyReading()), measurements: meas || {} } : rd.reading;
  const derived = reading ? degradationMappingFromReading(reading) : null;
  const mapping = derived?.mapping || { i: "", x: "", y: "" };
  const unit = derived?.unit || "";
  const measurementUnit = derived?.measurementUnit || "";
  // The table the fit reads, in /api/columns' shape, for the checks.
  const csv = useMemo(() => {
    const table = detail ? (detail.measurements || detail) : null;
    if (!table) return null;
    return { columns: table.preview_columns || [], preview: table.preview || [], n_rows: table.n_rows,
             n_unique: table.n_unique, dtypes: table.dtypes, values: table.values, blanks: table.blanks,
             whole: table.whole };
  }, [detail]);
  const measFacts = useMemo(() => (hasPart && csv ? columnFacts(csv) : {}), [hasPart, csv]);
  const pathName = (options.paths || []).find((p) => p.id === path)?.name;
  const name = nameTyped ?? `${baseName(sourceName) || "Degradation"} — ${
    path !== "best" && pathName ? `${pathName.toLowerCase()} degradation` : "degradation"}`;

  // What stops the Data step, beside its selector (at least 2 items, each read twice).
  const dataIssues = derived?.missing ? [] : csv ? degradationIssues(csv, mapping) : [];
  const way = direction ?? guessDirection(csv, mapping);

  // A file is saved as a dataset first (with how its columns are read), then used.
  const pickFile = (picked) => {
    if (!picked) return;
    setError(null);
    setPending(picked);
  };

  const pickDataset = async (d) => {
    setDatasetId(d.id);
    setSourceName(d.name);
    setNameTyped(null);
    setDirection(null);
    setMeasEditing(false);
    setError(null);
    setLoading(true);
    try {
      const full = await getDataset(d.id);
      if (!d.name) setSourceName(full.name || "");
      setDetail(full);
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

  const mappingValid = !!derived && !derived.missing && dataIssues.length === 0;
  const thresholdWhy = csv ? thresholdProblem(csv, mapping, threshold, way, measurementUnit) : null;
  // A number is required; the first-reading check is said, not blocking (one item may start past it).
  const thresholdBlocks = threshold === "" || !Number.isFinite(Number(threshold));

  const onFit = async () => {
    if (!datasetId || !name.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const saved = await saveDegradationModel(name.trim(), null, {
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
  } else {
    const editing = rd.editing || measEditing;
    const why = editing ? "First save or cancel the change to the reading."
      : !mappingValid ? "First settle what the reading lacks (above)."
        : thresholdBlocks ? "First enter the failure threshold." : null;
    nav = (<><button className="secondary" onClick={goBack} disabled={loading}>Back</button>
      {why && <span className="hint ds-next-why" role="status" style={{ margin: 0 }}>{why}</span>}
      <button onClick={onFit} disabled={loading || !name.trim() || !!why}>
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

  // Change: the main reading (one table), or the measurements part's own.
  const startChange = () => (hasPart ? setMeasEditing(true) : rd.startChange());
  const keepMeasurements = async (next) => {
    if (await rd.keepMeasurements(next)) setMeasEditing(false);
  };
  const summaryReading = hasPart ? { ...emptyReading(), ...(meas || {}) } : rd.reading;
  const summarySource = hasPart ? (meas?.source === "saved" ? "saved" : "guessed") : rd.source;
  const problems = derived?.missing ? [derived.missing] : dataIssues.map((i) => i.text);

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
              ) : pending ? (
                <span className="dz-big filename">{pending.name}</span>
              ) : (
                <span className="dz-big">Drop a CSV or Excel file here or <strong>click to browse</strong></span>
              )}
              <span className="dz-hint">long format: item id · time · measurement (one row per reading)</span>
              <input ref={inputRef} type="file" accept={`.csv,text/csv,${SPREADSHEET_ACCEPT}`} hidden
                     onChange={(e) => { pickFile(e.target.files?.[0]); e.target.value = ""; }} />
            </div>
                </>
              )}
            />
          </>
        )}

        {step === 2 && detail && (
          <>
            <p className="muted-line" style={{ marginTop: 0 }}>
              {sourceName} · {(csv?.n_rows ?? 0).toLocaleString()} {hasPart ? "readings (its measurements)" : "rows"}
            </p>
            {!rd.editing && !measEditing && (
              <ReadingSummary
                name={sourceName}
                reading={summaryReading}
                source={summarySource}
                use={["i", "x", "m"]}
                note={hasPart ? "These are its measurements: the readings on each item over time." : null}
                onChange={startChange}
                onConfirm={hasPart ? () => keepMeasurements({ ...(meas || {}), source: "saved" }) : rd.confirm}
                confirming={rd.saving}
                readOnly={rd.readOnly}
              />
            )}
            {!rd.editing && !measEditing && problems.length > 0 && (
              <div className="xcn-below" role="status">
                {problems.map((t) => <p key={t} className="xcn-issue">{t}</p>)}
                <button type="button" className="link" onClick={startChange}>Change the reading</button>
              </div>
            )}
            <ReadingChange name={sourceName} rd={rd} />
            {measEditing && (
              <MeasurementsReadingChange
                name={sourceName}
                columns={csv?.columns || []}
                facts={measFacts}
                value={meas}
                onKeep={keepMeasurements}
                onCancel={() => setMeasEditing(false)}
                saving={rd.saving}
                error={rd.error}
                readOnly={rd.readOnly}
              />
            )}
          </>
        )}

        {step === 2 && detail && !rd.editing && !measEditing && (
          <>
            <label className="login-field">
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
      {pending && (
        <NewDatasetModal
          initialFile={pending}
          initialName={baseName(pending.name)}
          title="Save the readings as a dataset"
          withMeasurements={false}
          onClose={() => setPending(null)}
          onCreated={(ds) => {
            setPending(null);
            listDatasets().then((d) => setDatasets(d.datasets || [])).catch(() => {});
            pickDataset({ id: ds.id, name: ds.name || "" });
          }}
        />
      )}
    </div>
  );
}
