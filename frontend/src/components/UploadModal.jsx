import { useEffect, useMemo, useRef, useState } from "react";
import {
  getColumns,
  getDistributions,
  fitModel,
  listDatasets,
  getDataset,
} from "../api.js";
import Modal from "./Modal.jsx";
import ColumnMapper from "./ColumnMapper.jsx";
import Covariates from "./Covariates.jsx";
import Units from "./Units.jsx";
import PreviewTable from "./PreviewTable.jsx";
import DistributionStep from "./DistributionStep.jsx";

const EMPTY_MAPPING = { x: "", c: "", n: "", xl: "", xr: "", tl: "", tr: "" };
const STEPS = ["Source", "Data", "Model"];

// Three-step modal flow: (1) pick a data source — upload a CSV or choose a
// saved dataset, (2) map columns + add covariates, (3) pick a model (filtered
// by whether covariates were provided) and fit.
export default function UploadModal({ onClose, onFitted }) {
  const [step, setStep] = useState(1);
  const [file, setFile] = useState(null);
  const [datasetId, setDatasetId] = useState(null);
  const [sourceName, setSourceName] = useState("");
  const [csv, setCsv] = useState(null); // { columns, preview, n_rows }
  const [mapping, setMapping] = useState(EMPTY_MAPPING);
  const [unit, setUnit] = useState("");
  const [covariates, setCovariates] = useState([]);
  const [advanced, setAdvanced] = useState(false);
  const [formula, setFormula] = useState("");
  const [distributions, setDistributions] = useState([]);
  const [distribution, setDistribution] = useState("weibull");
  const [fitOpts, setFitOpts] = useState({});
  const [datasets, setDatasets] = useState([]);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef(null);

  useEffect(() => {
    getDistributions()
      .then((d) => setDistributions(d.distributions))
      .catch(() =>
        setDistributions([{ id: "weibull", name: "Weibull", covariates: false }])
      );
    listDatasets()
      .then((d) => setDatasets(d.datasets))
      .catch(() => setDatasets([]));
  }, []);

  // Whether the data implies a proportional-hazards model.
  const hasCovariates = advanced ? formula.trim() !== "" : covariates.length > 0;

  // Model options filtered by the data that was entered.
  const options = useMemo(
    () => distributions.filter((d) => !!d.covariates === hasCovariates),
    [distributions, hasCovariates]
  );

  // Keep the selected model valid for the current filtered list.
  useEffect(() => {
    if (options.length && !options.some((o) => o.id === distribution)) {
      setDistribution(options[0].id);
    }
  }, [options, distribution]);

  const distName =
    distribution === "best"
      ? "best model"
      : distributions.find((d) => d.id === distribution)?.name || "model";

  const pickFile = async (f) => {
    if (!f) return;
    // Server enforces the same ceiling; fail fast before uploading.
    if (f.size > 5 * 1024 * 1024) {
      setError(`That file is ${(f.size / (1024 * 1024)).toFixed(1)} MB — the limit is 5 MB. Try trimming unused columns or rows.`);
      return;
    }
    setFile(f);
    setDatasetId(null);
    setSourceName(f.name);
    setError(null);
    setLoading(true);
    try {
      const cols = await getColumns(f);
      setCsv(cols);
      setMapping({ ...EMPTY_MAPPING, x: cols.columns[0] || "" });
      setCovariates([]);
      setStep(2);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  // Use an already-saved dataset as the source — no re-upload needed.
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
      setMapping({ ...EMPTY_MAPPING, x: columns[0] || "" });
      setCovariates([]);
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

  const toggleCovariate = (col) =>
    setCovariates((prev) =>
      prev.includes(col) ? prev.filter((c) => c !== col) : [...prev, col]
    );

  // Use 'x' alone, or both interval bounds 'xl'/'xr' — never together.
  const mappingValid = mapping.x
    ? !mapping.xl && !mapping.xr
    : !!mapping.xl && !!mapping.xr;

  const onFit = async () => {
    if (!file && !datasetId) return;
    setLoading(true);
    setError(null);
    try {
      const opts = {
        unit,
        ...(datasetId ? { datasetId } : {}),
        ...(hasCovariates ? (advanced ? { formula } : { covariates }) : {}),
        ...(hasCovariates ? {} : { fitOptions: fitOpts }),
      };
      const result = await fitModel(distribution, file, mapping, opts);
      // Pass the fit context too, so the result can be saved without re-entry.
      onFitted({
        result,
        fit: {
          file,
          datasetId,
          sourceName,
          distribution,
          mapping,
          unit,
          covariates: opts.covariates || [],
          formula: opts.formula || null,
          fitOptions: opts.fitOptions || null,
        },
      });
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
          <button className="secondary" onClick={goBack} disabled={loading}>
            Back
          </button>
          <button onClick={() => setStep(3)} disabled={!mappingValid}>
            Next
          </button>
        </div>
      </>
    );
  } else {
    footer = (
      <>
        {stepper}
        <div className="row" style={{ margin: 0 }}>
          <button className="secondary" onClick={goBack} disabled={loading}>
            Back
          </button>
          <button onClick={onFit} disabled={!distribution || loading}>
            {loading ? "Fitting…" : `Fit ${distName}`}
          </button>
        </div>
      </>
    );
  }

  return (
    <Modal
      title="Fit a parametric model"
      onClose={onClose}
      locked={loading}
      footer={footer}
    >
      {step === 1 && (
        <>
          <div
            className={`dropzone${dragging ? " dragging" : ""}`}
            onClick={() => inputRef.current?.click()}
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
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
              <span className="dz-big">
                Drop a CSV here or <strong>click to browse</strong>
              </span>
            )}
            <span className="dz-hint">columns: time · censored · covariates</span>
            <input
              ref={inputRef}
              type="file"
              accept=".csv,text/csv"
              hidden
              onChange={(e) => pickFile(e.target.files?.[0])}
            />
          </div>

          {datasets.length > 0 && (
            <div className="recent">
              <div className="recent-h">Or use a saved dataset</div>
              {datasets.slice(0, 5).map((d) => (
                <button
                  key={d.id}
                  type="button"
                  className="recent-row"
                  disabled={loading}
                  onClick={() => pickDataset(d)}
                >
                  <span className="recent-ic">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M14 3v5h5M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8z" />
                    </svg>
                  </span>
                  <span className="recent-name">{d.name}</span>
                  <span className="recent-meta">
                    {d.n_rows.toLocaleString()} rows · {d.n_columns} cols
                  </span>
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
          <ColumnMapper
            columns={csv.columns}
            mapping={mapping}
            onChange={setMapping}
          />
          <Units value={unit} onChange={setUnit} />
          <Covariates
            columns={csv.columns}
            selected={covariates}
            onToggle={toggleCovariate}
            advanced={advanced}
            onSetAdvanced={setAdvanced}
            formula={formula}
            onSetFormula={setFormula}
          />
          {!mappingValid && (
            <p className="hint" style={{ marginTop: "1rem" }}>
              Map a column to <code>x</code>, or to both <code>xl</code> and{" "}
              <code>xr</code>.
            </p>
          )}
        </>
      )}

      {step === 3 && (
        <>
          <p className="muted-line" style={{ marginTop: 0 }}>
            {hasCovariates
              ? "Covariates detected — choose a proportional-hazards model."
              : "No covariates — choose a distribution."}
          </p>
          <DistributionStep
            options={options}
            value={distribution}
            onChange={(id) => {
              setDistribution(id);
              setFitOpts({}); // options are per-distribution (params differ)
            }}
            fitOpts={fitOpts}
            onFitOpts={setFitOpts}
          />
        </>
      )}

      {error && <div className="error">{error}</div>}
    </Modal>
  );
}
