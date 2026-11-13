import { useEffect, useMemo, useRef, useState } from "react";
import { DataSourceStep } from "../components/DatasetPicker.jsx";
import { useNavigate, useSearchParams } from "react-router-dom";
import Select from "../components/Select.jsx";
import SegmentedControl from "../components/ui/SegmentedControl.jsx";
import { ResultDetails } from "../components/ui/ResultSummary.jsx";
import RefLink from "../components/RefLink.jsx";
import NewDatasetModal from "../components/NewDatasetModal.jsx";
import ReadingSummary, { ReadingChange } from "../components/ReadingSummary.jsx";
import { useDatasetReading } from "../useDatasetReading.js";
import RecurrentMore from "../components/RecurrentMore.jsx";
import RecurrentParamsPanel from "../components/RecurrentParamsPanel.jsx";
import RecurrentResultView from "../components/RecurrentResultView.jsx";
import ModelFrame, { AnswerLine } from "../components/model/ModelFrame.jsx";
import { recurrentAnswer } from "../recurrentResults.js";
import {
  readingWithRecurrentMapping, recurrentIssues, recurrentMappingFromReading, recurrentWithCovariates,
  savedRecurrentMapping,
} from "../recurrentMapping.js";
import { codedStatusNote } from "../readingCodes.js";
import { fileStem } from "../datasetGuess.js";
import {
  getRecurrentOptions,
  listDatasets,
  getDataset,
  fitRecurrent,
  saveRecurrentModel,
  SPREADSHEET_ACCEPT,
} from "../api.js";
import { ErrorNotice } from "../components/StorageCap.jsx";

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

const STEPS = ["Source", "Model", "Result"];
// What a repairable fit takes from a dataset's reading (the rest shown quieter).
const USES = ["x", "c", "n", "tl", "tr", "i", "e"];

// New recurrent-event (repairable-system) model, as a 3-step wizard that mirrors
// the life-data fit flow: (1) pick a saved dataset, or upload a file (saved as
// a dataset first, with how its columns are read), (2) choose a growth model
// and fit, the columns read as the dataset's reading says, (3) review the
// fit, name it, and save.
export default function RecurrentNewPage() {
  const navigate = useNavigate();
  const [mode, setMode] = useState(null); // null | "data" | "params"
  const [step, setStep] = useState(1);

  const [modelOpts, setModelOpts] = useState([]);
  const [datasets, setDatasets] = useState(null); // null while the list loads

  // An uploaded file, while it is saved as a dataset (NewDatasetModal).
  const [file, setFile] = useState(null);
  const [datasetId, setDatasetId] = useState(null);
  const [sourceName, setSourceName] = useState("");
  const [detail, setDetail] = useState(null); // the dataset (getDataset)
  const [model, setModel] = useState("crow_amsaa");
  const [baselines, setBaselines] = useState([]);
  const [options, setOptions] = useState({});
  // Observation gaps: window columns (ws, we) or windows typed in (#65).
  const [gaps, setGaps] = useState({ ws: "", we: "" });
  const [windows, setWindows] = useState("");

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
    listDatasets().then((d) => setDatasets(d.datasets || [])).catch(() => setDatasets([]));
  }, []);

  // How the dataset's columns are read (kept with it): the fit's columns come
  // from there. A dataset saved before readings whose newest repairable model
  // read its columns starts from that model's columns.
  const rd = useDatasetReading(detail);
  const kept = useMemo(
    () => (detail && rd.source !== "saved" && !detail.reading_kept ? savedRecurrentMapping(detail.last_recurrent_mapping, rd.cols?.columns) : null),
    [detail, rd.source, rd.cols],
  );
  const reading = useMemo(
    () => (kept ? readingWithRecurrentMapping(rd.reading, kept, rd.facts, rd.nRows) : rd.reading),
    [kept, rd.reading, rd.facts, rd.nRows],
  );
  const derived = useMemo(
    () => recurrentMappingFromReading(reading, rd.facts, rd.nRows),
    [reading, rd.facts, rd.nRows],
  );
  const unit = derived?.unit || "";

  const modelEntry = modelOpts.find((m) => m.id === model);
  const modelName = modelEntry?.name || "model";
  const family = modelEntry?.family || "nhpp";
  const pickFamily = (fam) => {
    const first = modelOpts.find((m) => (m.family || "nhpp") === fam);
    if (first) setModel(first.id);
    setOptions({});
  };
  // What's sent: the reading's columns; its covariates (Z) for the covariate
  // models only; the gaps, when given.
  const map = useMemo(() => {
    if (!derived) return { i: "", x: "" };
    const m = family === "regression" ? recurrentWithCovariates(derived.mapping, reading) : derived.mapping;
    return { ...m, ...(gaps.ws ? { ws: gaps.ws } : {}), ...(gaps.we ? { we: gaps.we } : {}) };
  }, [derived, family, reading, gaps]);
  // Proportional intensity needs covariates; gaps only the Poisson processes.
  const hasWindows = !!(map.ws && map.we) || !!windows.trim();
  const modelBlock = family === "regression" && !(map.z || []).length
    ? "This dataset's reading has no covariates (Z) for the failure rate to depend on: Change the reading to add them."
    : family !== "nhpp" && hasWindows
    ? "Observation windows work with the minimal-repair models only: clear them under Gaps in the records, or pick one of those."
    : null;

  // An uploaded file is saved as a dataset first, through the upload's own
  // screen (how its columns are read), then the fit goes on from it.
  const pickFile = (picked) => {
    if (!picked) return;
    setError(null);
    setFile(picked);
  };
  const onCreated = (ds) => {
    setFile(null);
    if (!ds?.id) return;
    setDatasets((cur) => [ds, ...(cur || []).filter((d) => d.id !== ds.id)]);
    pickDataset(ds);
  };

  const pickDataset = async (d) => {
    setDatasetId(d.id);
    setSourceName(d.name);
    setResult(null);
    setError(null);
    setLoading(true);
    try {
      const full = await getDataset(d.id);
      if (!d.name) setSourceName(full.name || "dataset");
      setDetail(full);
      setGaps({ ws: "", we: "" });
      setWindows("");
      setStep(2);
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  };

  // ?dataset=<id> (a dataset page's "Fit a repairable model") starts on that
  // dataset, at the Model step.
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

  // What the reading lacks for this model (no i), else the fit's own checks
  // on its columns; the missing end of record is said without stopping it.
  const missing = derived?.missing || null;
  const mapIssues = missing ? [] : recurrentIssues(map, windows);
  const blocking = mapIssues.filter((i) => !i.note);
  const readingValid = !!derived && !missing && blocking.length === 0;
  const fitBlock = !readingValid
    ? "First fix how the columns are read: Change the reading."
    : rd.editing ? "First save or cancel the change to the reading."
    : modelBlock;

  const onFit = async () => {
    if (!datasetId || fitBlock) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fitRecurrent(null, { datasetId, mapping: map, model, unit, options, windows });
      setResult(res);
      const src = (sourceName || "dataset").replace(/\.csv$/i, "");
      setName(`${res.results?.model?.name || modelName} — ${src}`);
      setStep(3);
    } catch (err) {
      setError(err);
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
        datasetId: result.dataset_id || datasetId, mapping: map, model, unit, options, windows,
      });
      navigate(`/models/recurrent/${saved.id}`);
    } catch (err) {
      setError(err);
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
        <span className="hint" style={{ margin: 0 }}>Pick a saved dataset, or upload a CSV or Excel file, to continue</span>
      </>
    );
  } else if (step === 2) {
    nav = (
      <>
        <button className="secondary" onClick={goBack} disabled={loading}>Back</button>
        <button onClick={onFit} disabled={loading || !!fitBlock}>{loading ? "Fitting…" : `Fit ${modelEntry?.short || modelName}`}</button>
        {fitBlock && !loading && <span className="hint ds-next-why" role="status" style={{ margin: 0 }}>{fitBlock}</span>}
        {loading && model !== "crow_amsaa" && (
          <span className="hint" role="status" style={{ margin: 0 }}>
            The fit check refits this model up to 200 times: allow 10–30 seconds.
          </span>
        )}
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
            <button className="crumb-link" onClick={() => navigate("/models")}>Model</button> /{" "}
            <button className="crumb-link" onClick={() => navigate("/models/recurrent")}>Repairable</button> /{" "}
            <b>New model</b>
          </div>
          <h1>
            {mode === "data" ? "Fit to event data"
              : mode === "params" ? "From parameters"
              : "New repairable model"}
          </h1>
          <p>
            {mode === "data" ? "Pick a repairable fleet's event history, fit a growth model, then review and save."
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
          onCreated={(m) => navigate(`/models/recurrent/${m.id}`)}
          onBack={() => setMode(null)}
        />
      )}

      {mode === "data" && (
      <div className="card fit-flow">
        <div className="fit-flow-head">{stepper}</div>
        {step === 1 && (
          <>
            <DataSourceStep
              kind="repairable"
              datasets={datasets}
              onUse={pickDataset}
              busy={loading}
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
                <span className="dz-big">Reading the dataset…</span>
              ) : file ? (
                <span className="dz-big filename">{file.name}</span>
              ) : (
                <span className="dz-big">Drop a CSV or Excel file here or <strong>click to browse</strong></span>
              )}
              <span className="dz-hint">one row per failure: system · its age at the failure · optional end of record</span>
              <input ref={inputRef} type="file" accept={`.csv,text/csv,${SPREADSHEET_ACCEPT}`} hidden
                     onChange={(e) => { pickFile(e.target.files?.[0]); e.target.value = ""; }} />
            </div>
                </>
              )}
            />
          </>
        )}

        {file && (
          <NewDatasetModal title="Save the file as a dataset" initialFile={file} initialName={fileStem(file.name)}
                           withMeasurements={false} onCreated={onCreated} onClose={() => setFile(null)} />
        )}

        {step === 2 && detail && reading && (
          <div className="fit-step">
            <ReadingSummary name={sourceName} reading={reading} source={rd.source}
                            use={family === "regression" ? [...USES, "z"] : USES}
                            note={codedStatusNote(derived?.status)}
                            onChange={rd.editing ? null : () => rd.setDraft(reading)}
                            onConfirm={() => rd.keep(reading)} confirming={rd.saving} readOnly={rd.readOnly} />
            <ReadingChange name={sourceName} rd={rd} />
            {!rd.editing && <ErrorNotice error={rd.error} />}
            {missing ? (
              <div className="xcn-below" role="status">
                <p className="xcn-issue" style={{ margin: 0 }}>{missing}</p>
                {!rd.editing && (
                  <button type="button" className="secondary" style={{ alignSelf: "flex-start" }}
                          onClick={() => rd.setDraft(reading)}>Change the reading</button>
                )}
              </div>
            ) : mapIssues.length > 0 && (
              <div className="xcn-below">
                {mapIssues.map((i) => (
                  <p key={i.text} className={"xcn-issue" + (i.note ? " xcn-note" : "")} role="status">
                    {i.text}{!i.note && " Change the reading to fix it."}
                  </p>
                ))}
              </div>
            )}
            {!missing && !rd.editing && (
              <>
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
            {(model === "ara" || model === "ari") && (
              <p className="muted-line" style={{ margin: 0 }}>
                Each repair acts on{" "}
                <b>{(MEMORY.find((m) => m.value === String(options.m ?? (model === "ara" ? "2" : "1")))?.label || "").toLowerCase()}</b>
                {options.m == null ? " (the default)" : ""}: change it under Advanced.
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
            <ResultDetails summary="Gaps in the records (optional)" open={!!(gaps.ws || gaps.we) || !!windows.trim()}>
              <RecurrentMore columns={rd.cols?.columns || []} mapping={{ ...map, ...gaps }} covariates={false}
                             onChange={(m) => setGaps({ ws: m.ws || "", we: m.we || "" })}
                             windows={windows} onWindowsChange={setWindows} />
            </ResultDetails>
            {modelBlock && <p className="hint" style={{ margin: 0 }}>{modelBlock}</p>}
              </>
            )}
          </div>
        )}

        {step === 3 && result && (
          <div className="fit-step">
            <label className="login-field">
              <span>Model name</span>
              <input type="text" autoFocus value={name} placeholder="e.g. Delivery trucks — engines"
                     onChange={(e) => setName(e.target.value)} />
            </label>
            <p className="muted-line" style={{ margin: 0 }}>
              Review the fit below. Go <b>Back</b> to change the model or how the columns are read and fit again, or save it.
            </p>
            {/* The model page's frame, inside the wizard: the answer line over the tabs. */}
            <ModelFrame embedded notice={<div className="mf-wizard-head"><AnswerLine parts={recurrentAnswer(result.results)} /></div>}>
              <RecurrentResultView results={result.results} name={name || null} />
            </ModelFrame>
          </div>
        )}

        <ErrorNotice error={error} />

        <div className="fit-flow-foot">
          <div className="row" style={{ margin: 0 }}>{nav}</div>
        </div>
      </div>
      )}
    </div>
  );
}
