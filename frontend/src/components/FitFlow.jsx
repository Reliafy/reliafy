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

const EMPTY_MAPPING = { x: "", c: "", n: "", xl: "", xr: "", tl: "", tr: "", c_invert: false };
const STEPS = ["Source", "Data", "Model", "Result"];

// Prefill the column mapping: the first column is the observed value, and a
// column literally named like a censoring flag (``censored``, ``c``) is mapped
// to ``c``. Anything else (``failed``, ``status``…) is left for the user — its
// convention can't be assumed.
const CENSOR_NAMES = /^(c|cens|censor|censored|censoring)$/i;
function guessMapping(columns) {
  const x = columns[0] || "";
  const c = columns.find((col) => col !== x && CENSOR_NAMES.test(String(col).trim())) || "";
  return { ...EMPTY_MAPPING, x, c };
}

// Turn pasted values into CSV text. Accepts one value per line, or values
// separated by commas / spaces / tabs / semicolons on any number of lines. When
// every line carries exactly two numbers the second is read as the censoring
// flag (0 = failed, 1 = still running; -1 left, 2 interval also pass). A
// leading non-numeric line (a header) is ignored. Returns { csv, rows, cols }
// or throws with a message fit to show inline.
export function parsePastedValues(text) {
  const lines = String(text || "")
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter(Boolean);
  if (lines.length && !/[0-9]/.test(lines[0])) lines.shift();
  if (!lines.length) throw new Error("Paste at least a few values first.");
  const rows = lines.map((l) => l.split(/[\s,;]+/).filter(Boolean));
  const num = (t) => {
    const v = Number(t);
    return Number.isFinite(v) ? v : null;
  };
  const twoCols = rows.every((r) => r.length === 2);
  if (twoCols) {
    const out = [];
    for (let i = 0; i < rows.length; i++) {
      const [t, c] = rows[i];
      const tv = num(t);
      const cv = num(c);
      if (tv === null) throw new Error(`Line ${i + 1}: "${t}" isn't a number.`);
      if (cv === null || ![-1, 0, 1, 2].includes(cv)) {
        throw new Error(`Line ${i + 1}: censoring flag "${c}" should be 0 (failed) or 1 (still running).`);
      }
      out.push(`${tv},${cv}`);
    }
    return { csv: `time,censored\n${out.join("\n")}\n`, rows: out.length, cols: 2 };
  }
  // Mixed line shapes (some "t c", some "t") are ambiguous — point at the
  // first line that breaks the pattern of the first one.
  const bad = rows.findIndex((r) => r.length !== rows[0].length);
  if (bad !== -1 && rows.length > 1 && rows[0].length <= 2) {
    const n = rows[bad].length;
    throw new Error(
      `Line ${bad + 1} has ${n} value${n === 1 ? "" : "s"} — use one value per line, or two per line as "time censored".`
    );
  }
  const values = rows.flat();
  const out = [];
  for (const t of values) {
    const tv = num(t);
    if (tv === null) throw new Error(`"${t}" isn't a number.`);
    out.push(String(tv));
  }
  if (out.length < 2) throw new Error("Paste at least two values.");
  return { csv: `time\n${out.join("\n")}\n`, rows: out.length, cols: 1 };
}

// Fit flow rendered as a page panel: (1) pick a data source, (2) map columns
// (+ unit, covariates), (3) pick a model and fit, (4) review the fit, name it,
// and save — with Back to change anything and re-fit before saving. Calls
// ``onSaved`` with the saved model; ``onCancel`` backs out to the list.
// ``initialSource`` opens the source step on "upload" (default) or "paste".
export default function FitFlow({ onSaved, onCancel, onPerDemand, initialDatasetId, autoFit, initialSource }) {
  const [step, setStep] = useState(1);
  // Source step: "upload" (dropzone) or "paste" (values typed / pasted in).
  const [source, setSource] = useState(initialSource === "paste" ? "paste" : "upload");
  const [pasted, setPasted] = useState("");
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
  const [fitMethods, setFitMethods] = useState([]);

  useEffect(() => {
    getDistributions()
      .then((d) => { setDistributions(d.distributions); setFitMethods(d.fit_methods || []); })
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
      setMapping(guessMapping(cols.columns));
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
      setMapping(guessMapping(columns));
      setCovariates([]);
      setStep(2);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  // Guided first-run: when handed a dataset id (e.g. the bearings sample), skip
  // the source step. Load its columns and jump to Data; with autoFit, fit a
  // Weibull straight away and land on the Result so a new user sees a finished
  // model — β verdict, curve, calculator — one save away from activation.
  const booted = useRef(false);
  useEffect(() => {
    if (!initialDatasetId || booted.current) return;
    booted.current = true;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const full = await getDataset(initialDatasetId);
        const columns = full.preview_columns || [];
        const map = guessMapping(columns);
        setFile(null);
        setDatasetId(initialDatasetId);
        setSourceName(full.name || "dataset");
        setCsv({ columns, preview: full.preview || [], n_rows: full.n_rows });
        setMapping(map);
        setCovariates([]);
        if (autoFit && map.x) {
          const res = await fitModel("weibull", null, map, { datasetId: initialDatasetId });
          setResult(res);
          setName(`${res.distribution} — ${(full.name || "dataset").replace(/\s*\(sample\)\s*$/i, "")}`);
          setStep(4);
        } else {
          setStep(2);
        }
      } catch (err) {
        setError(err.message);
        setStep(1);
      } finally {
        setLoading(false);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialDatasetId, autoFit]);

  const onDrop = (e) => {
    e.preventDefault();
    setDragging(false);
    pickFile(e.dataTransfer.files?.[0]);
  };

  // Pasted values become a small CSV file in the browser and go through the
  // same upload path as a real file (/api/columns, then the fit), so nothing
  // downstream changes.
  const usePasted = () => {
    let parsed;
    try {
      parsed = parsePastedValues(pasted);
    } catch (err) {
      setError(err.message);
      return;
    }
    pickFile(new File([parsed.csv], "pasted-values.csv", { type: "text/csv" }));
  };

  const toggleCovariate = (col) =>
    setCovariates((prev) =>
      prev.includes(col) ? prev.filter((c) => c !== col) : [...prev, col]
    );

  // Columns already claimed by a survival field (x/xl/xr/c/n/tl/tr) can't also
  // be covariates. Disable them in the picker and drop any that got mapped.
  const mappedColumns = useMemo(
    () => new Set(Object.values(mapping).filter((v) => typeof v === "string" && v)),
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
        <span className="hint" style={{ margin: 0 }}>
          {source === "paste"
            ? "Paste your values, or pick a dataset, to continue"
            : "Upload a CSV or pick a dataset to continue"}
        </span>
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
          <div className="source-toggle" role="tablist" aria-label="Data source">
            <button
              type="button"
              role="tab"
              aria-selected={source === "upload"}
              className={`source-tab${source === "upload" ? " active" : ""}`}
              onClick={() => { setSource("upload"); setError(null); }}
            >
              Upload a CSV
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={source === "paste"}
              className={`source-tab${source === "paste" ? " active" : ""}`}
              onClick={() => { setSource("paste"); setError(null); }}
            >
              Paste values
            </button>
          </div>

          {source === "paste" && (
            <div className="paste-source">
              <textarea
                className="paste-area"
                value={pasted}
                spellCheck={false}
                autoFocus
                disabled={loading}
                placeholder={"One value per line, e.g.\n312\n420\n506\n\nor with a censoring flag:\n120 0\n340 0\n500 1"}
                onChange={(e) => setPasted(e.target.value)}
              />
              <p className="hint" style={{ margin: 0 }}>
                Times to failure, one per line (or separated by commas / spaces).
                Add a second column for censoring: <b>0 = the unit failed</b>,{" "}
                <b>1 = it was still running</b> when observation stopped.
              </p>
              <div className="row" style={{ margin: 0 }}>
                <button type="button" onClick={usePasted} disabled={loading || !pasted.trim()}>
                  {loading ? "Reading values…" : "Use these values"}
                </button>
              </div>
            </div>
          )}

          {source === "upload" && (
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
          )}

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
            fitMethods={fitMethods}
            mapping={mapping}
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
