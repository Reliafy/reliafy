import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import Select from "../components/Select.jsx";
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
} from "../api.js";

// Short blurbs under the model dropdown (keyed by recurrent model id).
const MODEL_DESC = {
  crow_amsaa: "NHPP power-law (Crow-AMSAA) — the standard reliability-growth model. β < 1 improving, β > 1 worsening.",
  duane: "Duane growth model — a log–log fit of cumulative MTBF against cumulative time.",
  hpp: "Homogeneous Poisson — a constant failure rate with no trend; the null model.",
};

const STEPS = ["Source", "Data", "Model", "Result"];

// New recurrent-event (repairable-system) model, as a 4-step wizard that mirrors
// the life-data fit flow: (1) pick a data source, (2) preview + map columns,
// (3) choose a growth model and fit, (4) review the fit, name it, and save.
export default function RecurrentNewPage() {
  const navigate = useNavigate();
  const [mode, setMode] = useState(null); // null | "data" | "params"
  const [step, setStep] = useState(1);

  const [modelOpts, setModelOpts] = useState([]);
  const [datasets, setDatasets] = useState([]);

  const [file, setFile] = useState(null);
  const [datasetId, setDatasetId] = useState(null);
  const [sourceName, setSourceName] = useState("");
  const [csv, setCsv] = useState(null); // { columns, preview, n_rows }
  const [map, setMap] = useState({ i: "", x: "", c: "", n: "", tl: "", tr: "" });
  const [model, setModel] = useState("crow_amsaa");
  const [unit, setUnit] = useState("");

  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef(null);

  const [result, setResult] = useState(null); // { dataset_id, results }
  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    getRecurrentOptions().then((o) => setModelOpts(o.models || [])).catch(() => {});
    listDatasets().then((d) => setDatasets(d.datasets)).catch(() => setDatasets([]));
  }, []);

  const modelName = modelOpts.find((m) => m.id === model)?.name || "model";

  const pickFile = async (f) => {
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
      setMap({ i: cols.columns[0] || "", x: cols.columns[1] || "", c: "", n: "", tl: "", tr: "" });
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
      setCsv({ columns, preview: full.preview || [], n_rows: full.n_rows });
      setMap({ i: columns[0] || "", x: columns[1] || "", c: "", n: "", tl: "", tr: "" });
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

  // System id and event time are required and must be different columns.
  const mappingValid = map.i && map.x && map.i !== map.x;

  const onFit = async () => {
    if (!file && !datasetId) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fitRecurrent(datasetId ? null : file, { datasetId, mapping: map, model, unit });
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
        datasetId: result.dataset_id, mapping: map, model, unit,
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
        <button onClick={onFit} disabled={loading}>{loading ? "Fitting…" : `Fit ${modelName}`}</button>
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
                fit an MCF and a Crow-AMSAA / Duane growth model with a trend test.
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
                <span className="dz-big">Drop a CSV here or <strong>click to browse</strong></span>
              )}
              <span className="dz-hint">long format — one row per event: system id · event time · window</span>
              <input ref={inputRef} type="file" accept=".csv,text/csv" hidden
                     onChange={(e) => pickFile(e.target.files?.[0])} />
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
            <p className="muted-line">Choose a recurrent-event growth model to fit to the fleet's event history.</p>
            <label className="dist-field" style={{ width: 280 }}>
              <span className="dist-label">Model</span>
              <Select value={model} onChange={setModel}
                      options={modelOpts.map((m) => ({ value: m.id, label: m.name }))} />
            </label>
            {MODEL_DESC[model] && <p className="muted-line" style={{ margin: 0 }}>{MODEL_DESC[model]}</p>}
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
