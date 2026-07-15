import { useEffect, useMemo, useRef, useState } from "react";
import {
  getColumns,
  getDistributions,
  fitModel,
  saveModel,
  listDatasets,
  getDataset,
} from "../api.js";
import ColumnMapper from "./ColumnMapper.jsx";
import Covariates from "./Covariates.jsx";
import PreviewTable from "./PreviewTable.jsx";
import DistributionStep from "./DistributionStep.jsx";
import ResultView from "./ResultView.jsx";

const EMPTY_MAPPING = { x: "", c: "", n: "", xl: "", xr: "", tl: "", tr: "" };
const STEPS = ["Source", "Data", "Model", "Result"];

// Fit flow rendered as a page panel: (1) pick a data source, (2) map columns
// (+ unit, covariates), (3) pick a model and fit, (4) review the fit, name it,
// and save — with Back to change anything and re-fit before saving. Calls
// ``onSaved`` with the saved model; ``onCancel`` backs out to the list.
export default function FitFlow({ onSaved, onCancel, onPerDemand }) {
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

  // Step 4 (Result): the fit, a name, and the save action.
  const [result, setResult] = useState(null);
  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);

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

  // Columns already claimed by a survival field (x/xl/xr/c/n/tl/tr) can't also
  // be covariates. Disable them in the picker and drop any that got mapped.
  const mappedColumns = useMemo(
    () => new Set(Object.values(mapping).filter(Boolean)),
    [mapping]
  );
  useEffect(() => {
    setCovariates((prev) =>
      prev.some((c) => mappedColumns.has(c)) ? prev.filter((c) => !mappedColumns.has(c)) : prev
    );
  }, [mappedColumns]);

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
      const res = await fitModel(distribution, file, mapping, opts);
      setResult(res);
      const src = file?.name || sourceName || "dataset";
      setName(`${res.distribution} — ${src.replace(/\.csv$/i, "")}`);
      setStep(4);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const onSave = async () => {
    if (!name.trim()) return;
    setSaving(true);
    setError(null);
    try {
      const saved = await saveModel(name.trim(), distribution, file, mapping, {
        unit,
        datasetId: datasetId || undefined,
        ...(hasCovariates ? (advanced ? { formula } : { covariates }) : { fitOptions: fitOpts }),
      });
      onSaved?.(saved);
    } catch (err) {
      setError(err.message);
      setSaving(false);
    }
  };

  // Back from step 1 leaves the flow entirely; from Result it returns to Model.
  const goBack = () => {
    setError(null);
    if (step === 1) return onCancel?.();
    setStep((s) => s - 1);
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

  let nav;
  if (step === 1) {
    nav = (
      <>
        <button className="secondary" onClick={goBack} disabled={loading}>Cancel</button>
        <span className="hint" style={{ margin: 0 }}>Upload a CSV or pick a dataset to continue</span>
      </>
    );
  } else if (step === 2) {
    nav = (
      <>
        <button className="secondary" onClick={goBack} disabled={loading}>Back</button>
        <button onClick={() => setStep(3)} disabled={!mappingValid}>Next</button>
      </>
    );
  } else if (step === 3) {
    nav = (
      <>
        <button className="secondary" onClick={goBack} disabled={loading}>Back</button>
        <button onClick={onFit} disabled={!distribution || loading}>
          {loading ? "Fitting…" : `Fit ${distName}`}
        </button>
      </>
    );
  } else {
    nav = (
      <>
        <button className="secondary" onClick={goBack} disabled={saving}>Back</button>
        <button onClick={onSave} disabled={!name.trim() || saving}>
          {saving ? "Saving…" : "Save model"}
        </button>
      </>
    );
  }

  return (
    <div className="card fit-flow">
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

          {onPerDemand && (
            <div className="perdemand-cta">
              <span className="muted-line" style={{ margin: 0 }}>
                Not time-to-failure data? Model one-shot / protective equipment:
              </span>
              <button type="button" className="secondary" onClick={onPerDemand}>
                Per-demand
              </button>
            </div>
          )}
        </>
      )}

      {step === 2 && csv && (
        <div className="fit-step">
          <p className="muted-line">
            {sourceName} · {csv.n_rows} rows · {csv.columns.length} columns
          </p>
          <PreviewTable columns={csv.columns} rows={csv.preview} />
          <ColumnMapper
            columns={csv.columns}
            mapping={mapping}
            onChange={setMapping}
            unit={unit}
            onUnitChange={setUnit}
          />
          <Covariates
            columns={csv.columns}
            selected={covariates}
            onToggle={toggleCovariate}
            advanced={advanced}
            onSetAdvanced={setAdvanced}
            formula={formula}
            onSetFormula={setFormula}
            disabledColumns={mappedColumns}
          />
          {!mappingValid && (
            <p className="hint">
              Map a column to <code>x</code>, or to both <code>xl</code> and{" "}
              <code>xr</code>.
            </p>
          )}
        </div>
      )}

      {step === 3 && (
        <div className="fit-step">
          <p className="muted-line">
            {hasCovariates
              ? "Covariates detected — choose a regression model (proportional-hazards or accelerated-failure-time)."
              : "Choose a parametric distribution or a non-parametric estimator."}
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
        </div>
      )}

      {step === 4 && result && (
        <div className="fit-step">
          <label className="login-field">
            <span>Model name</span>
            <input
              type="text"
              autoFocus
              value={name}
              placeholder="Model name"
              onChange={(e) => setName(e.target.value)}
            />
          </label>
          <p className="muted-line" style={{ margin: 0 }}>
            Review the fit below. Go <b>Back</b> to change the mapping or model
            and re-fit, or save it.
          </p>
          <ResultView result={result} />
        </div>
      )}

      {error && <div className="error">{error}</div>}

      <div className="fit-flow-foot">
        {stepper}
        <div className="row" style={{ margin: 0 }}>{nav}</div>
      </div>
    </div>
  );
}
