import { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import Select from "../components/Select.jsx";
import SegmentedControl from "../components/ui/SegmentedControl.jsx";
import { ResultDetails } from "../components/ui/ResultSummary.jsx";
import RefLink from "../components/RefLink.jsx";
import PreviewTable from "../components/PreviewTable.jsx";
import RecurrentColumnMapper from "../components/RecurrentColumnMapper.jsx";
import RecurrentParamsPanel from "../components/RecurrentParamsPanel.jsx";
import RecurrentResultView from "../components/RecurrentResultView.jsx";
import {
  getRecurrentOptions,
  getColumns,
  listDatasets,
  getDataset,
  fitRecurrent,
  saveRecurrentModel,
  SPREADSHEET_ACCEPT,
} from "../api.js";
import { useSpreadsheet } from "../components/ExcelSheetPicker.jsx";

// The model families (#65): minimal repair (Poisson processes), covariates on
// the repair rate, and imperfect repair.
const FAMILIES = [
  { value: "nhpp", label: "Minimal repair" },
  { value: "regression", label: "Covariates" },
  { value: "renewal", label: "Imperfect repair" },
];
const FAMILY_DESC = {
  nhpp: "Each repair puts the system back as it was just before the failure (as bad as old): the trend is in the failure rate over time.",
  regression: "The failure rate differs between systems by their covariates (site, duty, operating condition).",
  renewal: "Each repair restores part of the system's age (between as good as new and as bad as old): how much is estimated.",
};
const MEMORY = [
  { value: "1", label: "The last repair" },
  { value: "2", label: "The last 2 repairs" },
  { value: "3", label: "The last 3 repairs" },
  { value: "all", label: "Every repair" },
];

// Short blurbs under the model dropdown (keyed by recurrent model id).
const MODEL_DESC = {
  crow_amsaa: "NHPP power-law (Crow-AMSAA) — the standard reliability-growth model. β < 1 improving, β > 1 worsening.",
  duane: "Duane growth model — a log–log fit of cumulative MTBF against cumulative time.",
  hpp: "Homogeneous Poisson — a constant failure rate with no trend; the null model.",
  cox_lewis: "Cox-Lewis log-linear NHPP — the rate changes by a fixed proportion per unit time. β > 0 worsening, β < 0 improving.",
};

const STEPS = ["Source", "Data", "Model", "Result"];

// New recurrent-event (repairable-system) model, as a 4-step wizard that mirrors
// the life-data fit flow: (1) pick a data source, (2) preview + map columns,
// (3) choose a growth model and fit, (4) review the fit, name it, and save.
// A column that looks like each failure's mode (for a growth projection, #232).
const guessModeColumn = (columns) =>
  (columns || []).find((c) => /^(failure[ _-]?)?mode$|^cause$|^failure[ _-]?cause$/i.test(String(c).trim())) || "";

export default function RecurrentNewPage() {
  const navigate = useNavigate();
  const [mode, setMode] = useState(null); // null | "data" | "params"
  const [step, setStep] = useState(1);
  // An Excel workbook becomes a CSV of the chosen sheet before anything else.
  const { toCsv, modal: sheetModal } = useSpreadsheet();

  const [modelOpts, setModelOpts] = useState([]);
  const [datasets, setDatasets] = useState([]);

  const [file, setFile] = useState(null);
  const [datasetId, setDatasetId] = useState(null);
  const [sourceName, setSourceName] = useState("");
  const [csv, setCsv] = useState(null); // { columns, preview, n_rows }
  const [map, setMap] = useState({ i: "", x: "", c: "", n: "", tl: "", tr: "" });
  const [model, setModel] = useState("crow_amsaa");
  const [baselines, setBaselines] = useState([]);
  const [options, setOptions] = useState({});
  const [windows, setWindows] = useState("");
  const [unit, setUnit] = useState("");

  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef(null);

  const [result, setResult] = useState(null); // { dataset_id, results }
  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    getRecurrentOptions().then((o) => {
      setModelOpts(o.models || []);
      setBaselines(o.baselines || []);
    }).catch(() => {});
    listDatasets().then((d) => setDatasets(d.datasets)).catch(() => setDatasets([]));
  }, []);

  const modelEntry = modelOpts.find((m) => m.id === model);
  const modelName = modelEntry?.name || "model";
  const family = modelEntry?.family || "nhpp";
  const pickFamily = (fam) => {
    const first = modelOpts.find((m) => (m.family || "nhpp") === fam);
    if (first) setModel(first.id);
    setOptions({});
  };
  // Proportional intensity needs covariates; gaps only the Poisson processes.
  const hasWindows = !!(map.ws && map.we) || !!windows.trim();
  const modelBlock = family === "regression" && !(map.z || []).length
    ? "Choose at least one covariate column on the Data step (Back)."
    : family !== "nhpp" && hasWindows
    ? "Observation windows work with the minimal-repair models only: clear them on the Data step, or pick one of those."
    : null;

  const pickFile = async (picked) => {
    if (!picked) return;
    const f = await toCsv(picked);
    if (!f) return;
    if (f.size > 5 * 1024 * 1024) {
      setError(`That file is ${(f.size / (1024 * 1024)).toFixed(1)} MB — the limit is 5 MB. Try trimming unused columns or rows.`);
      return;
    }
    setFile(f);
    setDatasetId(null);
    setSourceName(f.name);
    setResult(null);
    setError(null);
    setLoading(true);
    try {
      const cols = await getColumns(f);
      setCsv(cols);
      setMap({ i: cols.columns[0] || "", x: cols.columns[1] || "", c: "", n: "", tl: "", tr: "", mode: guessModeColumn(cols.columns) });
      setWindows("");
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
    setResult(null);
    setError(null);
    setLoading(true);
    try {
      const full = await getDataset(d.id);
      const columns = full.preview_columns || [];
      if (!d.name) setSourceName(full.name || "dataset");
      setCsv({ columns, preview: full.preview || [], n_rows: full.n_rows });
      setMap({ i: columns[0] || "", x: columns[1] || "", c: "", n: "", tl: "", tr: "", mode: guessModeColumn(columns) });
      setWindows("");
      setStep(2);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  // ?dataset=<id> (a dataset page's "Fit a recurrent model") starts on that
  // dataset, at the column mapping.
  const [params] = useSearchParams();
  const startDataset = params.get("dataset");
  const started = useRef(false);
  useEffect(() => {
    if (!startDataset || started.current) return;
    started.current = true;
    setMode("data");
    pickDataset({ id: startDataset, name: "" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [startDataset]);

  const onDrop = (e) => {
    e.preventDefault();
    setDragging(false);
    pickFile(e.dataTransfer.files?.[0]);
  };

  // System id and event time are required and must be different columns.
  const mappingValid = map.i && map.x && map.i !== map.x;

  const onFit = async () => {
    if (!file && !datasetId) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fitRecurrent(datasetId ? null : file, { datasetId, mapping: map, model, unit, options, windows });
      setResult(res);
      const src = (file?.name || sourceName || "dataset").replace(/\.csv$/i, "");
      setName(`${res.results?.model?.name || modelName} — ${src}`);
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
      const saved = await saveRecurrentModel(name.trim(), null, {
        datasetId: result.dataset_id, mapping: map, model, unit, options, windows,
      });
      navigate(`/modelling/recurrent/${saved.id}`);
    } catch (err) {
      setError(err.message);
      setSaving(false);
    }
  };

  // Back from step 1 returns to the build-mode choice; from Result to Model.
  const goBack = () => {
    setError(null);
    if (step === 1) return setMode(null);
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
        <span className="hint" style={{ margin: 0 }}>Upload a CSV or Excel file, or pick a dataset, to continue</span>
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
        <button onClick={onFit} disabled={loading || !!modelBlock}>{loading ? "Fitting…" : `Fit ${modelEntry?.short || modelName}`}</button>
      </>
    );
  } else {
    nav = (
      <>
        <button className="secondary" onClick={goBack} disabled={saving}>Back</button>
        <button onClick={onSave} disabled={!name.trim() || saving}>{saving ? "Saving…" : "Save model"}</button>
      </>
    );
  }

  return (
    <div className="app">
      <header>
        <div>
          <div className="crumb">
            <button className="crumb-link" onClick={() => navigate("/modelling")}>Modelling</button> /{" "}
            <button className="crumb-link" onClick={() => navigate("/modelling/recurrent")}>Recurrent events</button> /{" "}
            <b>New model</b>
          </div>
          <h1>
            {mode === "data" ? "Fit to event data"
              : mode === "params" ? "From parameters"
              : "New recurrent model"}
          </h1>
          <p>
            {mode === "data" ? "Pick a repairable fleet's event history, map columns, fit a growth model, then review and save."
              : mode === "params" ? "Build a simple model from known parameters — for repair-vs-replace decisions."
              : "How do you want to build the model?"}
          </p>
        </div>
      </header>

      {mode === null && (
        <div className="card">
          <div className="ds-choose">
            <button className="ds-choice" onClick={() => setMode("data")}>
              <span className="ds-choice-h">Fit to event data</span>
              <span className="ds-choice-b">
                Upload or pick a saved dataset of a repairable fleet's failure history —
                fit an MCF and a growth model with confidence bounds, trend tests and a goodness-of-fit test.
              </span>
            </button>
            <button className="ds-choice" onClick={() => setMode("params")}>
              <span className="ds-choice-h">From parameters</span>
              <span className="ds-choice-b">
                No data — enter a growth model's parameters (α, β) directly. A simple model
                for reliability-growth planning and repair-vs-replace decisions.
              </span>
            </button>
          </div>
        </div>
      )}

      {mode === "params" && (
        <RecurrentParamsPanel
          onCreated={(m) => navigate(`/modelling/recurrent/${m.id}`)}
          onBack={() => setMode(null)}
        />
      )}

      {mode === "data" && (
      <div className="card fit-flow">
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
              <span className="dz-hint">long format — one row per event: system id · event time · window</span>
              <input ref={inputRef} type="file" accept={`.csv,text/csv,${SPREADSHEET_ACCEPT}`} hidden
                     onChange={(e) => { pickFile(e.target.files?.[0]); e.target.value = ""; }} />
              {sheetModal}
            </div>

            {datasets.length > 0 && (
              <div className="recent">
                <div className="recent-h">Or use a saved dataset</div>
                {datasets.slice(0, 5).map((d) => (
                  <button key={d.id} type="button" className="recent-row" disabled={loading}
                          onClick={() => pickDataset(d)}>
                    <span className="recent-ic">
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M14 3v5h5M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8z" />
                      </svg>
                    </span>
                    <span className="recent-name">{d.name}</span>
                    <span className="recent-meta">{(d.n_rows ?? 0).toLocaleString()} rows · {d.n_columns} cols</span>
                  </button>
                ))}
              </div>
            )}
          </>
        )}

        {step === 2 && csv && (
          <div className="fit-step">
            <p className="muted-line">{sourceName} · {csv.n_rows} rows · {csv.columns.length} columns</p>
            <PreviewTable columns={csv.columns} rows={csv.preview} />
            <RecurrentColumnMapper
              columns={csv.columns}
              mapping={map}
              onChange={setMap}
              unit={unit}
              onUnitChange={setUnit}
              windows={windows}
              onWindowsChange={setWindows}
            />
            <p className="muted-line" style={{ margin: 0 }}>
              Long format — one row per failure/repair: a system id and event time, plus optional
              counts, censoring, and each system's observation window (<code>tr</code>).
            </p>
            {!mappingValid && (
              <p className="hint">Map different columns to <code>i</code> and <code>x</code>.</p>
            )}
          </div>
        )}

        {step === 3 && (
          <div className="fit-step">
            <p className="muted-line">Choose how repairs work, then the model to fit to the fleet's event history.</p>
            <SegmentedControl options={FAMILIES} value={family} onChange={pickFamily} label="Kind of model"
                              style={{ alignSelf: "flex-start", maxWidth: "100%" }} />
            <p className="muted-line" style={{ margin: 0 }}>{FAMILY_DESC[family]}</p>
            <div className="dist-field" style={{ width: 320, maxWidth: "100%" }}>
              <span className="dist-label">Model</span>
              <Select value={model} onChange={(v) => { setModel(v); setOptions({}); }}
                      options={modelOpts.filter((m) => (m.family || "nhpp") === family)
                        .map((m) => ({ value: m.id, label: m.name }))} />
            </div>
            {(MODEL_DESC[model] || modelEntry?.desc) && (
              <p className="muted-line" style={{ margin: 0 }}>
                {MODEL_DESC[model] || modelEntry.desc}
                {MODEL_DESC[model] && <RefLink entryId={model} label="What is this growth model?" />}
              </p>
            )}
            {(model === "pi_nhpp" || model === "ari" || model === "ara") && (
              <ResultDetails summary="Advanced">
                <div className="row" style={{ gap: 12, flexWrap: "wrap", margin: 0 }}>
                  {(model === "pi_nhpp" || model === "ari") && (
                    <div className="dist-field" style={{ width: 220 }}>
                      <span className="dist-label">Baseline failure rate</span>
                      <Select value={options.baseline || "crow_amsaa"}
                              onChange={(v) => setOptions((o) => ({ ...o, baseline: v }))}
                              options={baselines.map((b) => ({ value: b.id, label: b.name }))} />
                    </div>
                  )}
                  {(model === "ara" || model === "ari") && (
                    <div className="dist-field" style={{ width: 220 }}>
                      <span className="dist-label">Each repair acts on</span>
                      <Select value={String(options.m ?? (model === "ara" ? "2" : "1"))}
                              onChange={(v) => setOptions((o) => ({ ...o, m: v }))} options={MEMORY} />
                    </div>
                  )}
                </div>
              </ResultDetails>
            )}
            {modelBlock && <p className="hint" style={{ margin: 0 }}>{modelBlock}</p>}
          </div>
        )}

        {step === 4 && result && (
          <div className="fit-step">
            <label className="login-field">
              <span>Model name</span>
              <input type="text" autoFocus value={name} placeholder="e.g. Delivery trucks — engines"
                     onChange={(e) => setName(e.target.value)} />
            </label>
            <p className="muted-line" style={{ margin: 0 }}>
              Review the fit below. Go <b>Back</b> to change the mapping or model and re-fit, or save it.
            </p>
            <RecurrentResultView results={result.results} />
          </div>
        )}

        {error && <div className="error">{error}</div>}

        <div className="fit-flow-foot">
          {stepper}
          <div className="row" style={{ margin: 0 }}>{nav}</div>
        </div>
      </div>
      )}
    </div>
  );
}
