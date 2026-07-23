import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import Select from "../components/Select.jsx";
import PreviewTable from "../components/PreviewTable.jsx";
import AltResultView from "../components/AltResultView.jsx";
import {
  getAltOptions, getColumns, listDatasets, getDataset, fitAlt, saveAltModel,
} from "../api.js";

const STEPS = ["Source", "Model", "Data", "Result"];

// New Accelerated Life model — a 4-step wizard. Unlike the life-data flow the
// MODEL is chosen before the data, because the life-stress relationship decides
// how many stress columns must be mapped (one, or two).
export default function AltNewPage() {
  const navigate = useNavigate();
  const [step, setStep] = useState(1);

  const [lifeModels, setLifeModels] = useState([]);
  const [dists, setDists] = useState([]);
  const [datasets, setDatasets] = useState([]);

  const [file, setFile] = useState(null);
  const [datasetId, setDatasetId] = useState(null);
  const [sourceName, setSourceName] = useState("");
  const [csv, setCsv] = useState(null);

  const [distribution, setDistribution] = useState("weibull");
  const [lifeModel, setLifeModel] = useState("arrhenius");
  const [map, setMap] = useState({ x: "", c: "", n: "" });
  const [stress, setStress] = useState([{ col: "", label: "" }]);
  const [unit, setUnit] = useState("");

  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef(null);

  const [result, setResult] = useState(null);
  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    getAltOptions().then((o) => { setLifeModels(o.life_models || []); setDists(o.distributions || []); }).catch(() => {});
    listDatasets().then((d) => setDatasets(d.datasets)).catch(() => setDatasets([]));
  }, []);

  const lm = useMemo(() => lifeModels.find((m) => m.id === lifeModel), [lifeModels, lifeModel]);
  const nStress = lm?.n_stress || 1;

  // Keep the stress-column slots in sync with the chosen life model's arity.
  useEffect(() => {
    setStress((cur) => {
      const next = cur.slice(0, nStress);
      while (next.length < nStress) next.push({ col: "", label: "" });
      return next;
    });
  }, [nStress]);

  const loadColumns = (columns, preview, nRows) => {
    setCsv({ columns, preview: preview || [], n_rows: nRows });
    setMap({ x: columns[0] || "", c: "", n: "" });
    // Default the stress columns to the ones after the failure time.
    setStress(Array.from({ length: nStress }, (_, j) => ({ col: columns[j + 1] || "", label: "" })));
  };

  const pickFile = async (f) => {
    if (!f) return;
    if (f.size > 5 * 1024 * 1024) {
      setError(`That file is ${(f.size / (1024 * 1024)).toFixed(1)} MB — the limit is 5 MB.`);
      return;
    }
    setFile(f); setDatasetId(null); setSourceName(f.name); setResult(null); setError(null); setLoading(true);
    try {
      const cols = await getColumns(f);
      loadColumns(cols.columns, cols.preview, cols.n_rows);
      setStep(2);
    } catch (err) { setError(err.message); } finally { setLoading(false); }
  };

  const pickDataset = async (d) => {
    setFile(null); setDatasetId(d.id); setSourceName(d.name); setResult(null); setError(null); setLoading(true);
    try {
      const full = await getDataset(d.id);
      loadColumns(full.preview_columns || [], full.preview || [], full.n_rows);
      setStep(2);
    } catch (err) { setError(err.message); } finally { setLoading(false); }
  };

  const onDrop = (e) => { e.preventDefault(); setDragging(false); pickFile(e.dataTransfer.files?.[0]); };

  const stressCols = stress.slice(0, nStress).map((s) => s.col);
  const allMapped = map.x && stressCols.every(Boolean);
  const distinct = new Set([map.x, ...stressCols]).size === 1 + nStress;
  const mappingValid = allMapped && distinct;

  const setStressAt = (j, patch) =>
    setStress((cur) => cur.map((s, k) => (k === j ? { ...s, ...patch } : s)));

  const onFit = async () => {
    if (!mappingValid) return;
    setLoading(true); setError(null);
    try {
      const opts = {
        datasetId, mapping: map, stress: stress.slice(0, nStress),
        distribution, lifeModel, unit,
      };
      const res = await fitAlt(datasetId ? null : file, opts);
      setResult(res);
      const src = (file?.name || sourceName || "dataset").replace(/\.csv$/i, "");
      setName(`${dists.find((d) => d.id === distribution)?.name || "ALT"} — ${src}`);
      setStep(4);
    } catch (err) { setError(err.message); } finally { setLoading(false); }
  };

  const onSave = async () => {
    if (!name.trim()) return;
    setSaving(true); setError(null);
    try {
      const saved = await saveAltModel(name.trim(), null, {
        datasetId: result.dataset_id, mapping: map, stress: stress.slice(0, nStress),
        distribution, lifeModel, unit,
      });
      navigate(`/modelling/alt/${saved.id}`);
    } catch (err) { setError(err.message); setSaving(false); }
  };

  const goBack = () => { setError(null); if (step === 1) return navigate("/modelling/alt"); setStep((s) => s - 1); };

  const stepper = (
    <div className="steps">
      {STEPS.map((label, i) => {
        const n = i + 1;
        return (
          <span className="step-wrap" key={label}>
            {i > 0 && <span className="sep" />}
            <span className={`step${step === n ? " active" : ""}`}><span className="dot">{n}</span>{label}</span>
          </span>
        );
      })}
    </div>
  );

  let nav;
  if (step === 1) {
    nav = (<><button className="secondary" onClick={goBack} disabled={loading}>Cancel</button>
      <span className="hint" style={{ margin: 0 }}>Upload a CSV or pick a dataset to continue</span></>);
  } else if (step === 2) {
    nav = (<><button className="secondary" onClick={goBack} disabled={loading}>Back</button>
      <button onClick={() => setStep(3)}>Next</button></>);
  } else if (step === 3) {
    nav = (<><button className="secondary" onClick={goBack} disabled={loading}>Back</button>
      <button onClick={onFit} disabled={!mappingValid || loading}>{loading ? "Fitting…" : "Fit model"}</button></>);
  } else {
    nav = (<><button className="secondary" onClick={goBack} disabled={saving}>Back</button>
      <button onClick={onSave} disabled={!name.trim() || saving}>{saving ? "Saving…" : "Save model"}</button></>);
  }

  const colOpts = (csv?.columns || []).map((c) => ({ value: c, label: c }));

  return (
    <div className="app">
      <header>
        <div>
          <div className="crumb">
            <button className="crumb-link" onClick={() => navigate("/modelling")}>Modelling</button> /{" "}
            <button className="crumb-link" onClick={() => navigate("/modelling/alt")}>Accelerated life</button> /{" "}
            <b>New model</b>
          </div>
          <h1>New accelerated-life model</h1>
          <p>Pick data, choose a distribution and life-stress relationship, map the time and stress columns, then fit and save.</p>
        </div>
      </header>

      <div className="card fit-flow">
        {step === 1 && (
          <>
            <div className={`dropzone${dragging ? " dragging" : ""}`}
                 onClick={() => inputRef.current?.click()}
                 onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
                 onDragLeave={() => setDragging(false)} onDrop={onDrop}>
              <span className="dz-ic">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M12 16V4m0 0 4 4m-4-4-4 4" /><path d="M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3" />
                </svg>
              </span>
              {loading ? <span className="dz-big">Reading file…</span>
                : file ? <span className="dz-big filename">{file.name}</span>
                : <span className="dz-big">Drop a CSV here or <strong>click to browse</strong></span>}
              <span className="dz-hint">one row per unit: failure time · stress level(s) · optional censoring</span>
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
                    <span className="recent-meta">{(d.n_rows ?? 0).toLocaleString()} rows · {d.n_columns} cols</span>
                  </button>
                ))}
              </div>
            )}
          </>
        )}

        {step === 2 && (
          <div className="fit-step">
            <div className="alt-model-pick">
              <div className="dist-field" style={{ width: 260 }}>
                <span className="dist-label">Life distribution</span>
                <Select value={distribution} onChange={setDistribution}
                        options={dists.map((d) => ({ value: d.id, label: d.name }))} />
              </div>
              <div className="dist-field" style={{ width: 320 }}>
                <span className="dist-label">Life-stress relationship</span>
                <Select value={lifeModel} onChange={setLifeModel}
                        options={lifeModels.map((m) => ({ value: m.id, label: `${m.name} · ${m.n_stress} stress${m.n_stress > 1 ? "es" : ""}` }))} />
              </div>
            </div>
            {lm?.desc && <p className="muted-line" style={{ margin: 0 }}>{lm.desc}</p>}
            <p className="muted-line" style={{ margin: 0 }}>
              You'll map <b>{nStress}</b> stress column{nStress > 1 ? "s" : ""} on the next step.
            </p>
          </div>
        )}

        {step === 3 && csv && (
          <div className="fit-step">
            <p className="muted-line">{sourceName} · {csv.n_rows} rows · {csv.columns.length} columns</p>
            <PreviewTable columns={csv.columns} rows={csv.preview} />
            <div className="alt-map">
              <div className="alt-map-row">
                <span className="alt-map-k">Failure time (x)</span>
                <Select value={map.x} onChange={(v) => setMap((m) => ({ ...m, x: v }))} options={colOpts} placeholder="column…" />
              </div>
              {stress.slice(0, nStress).map((s, j) => (
                <div className="alt-map-row" key={j}>
                  <span className="alt-map-k">Stress {nStress > 1 ? j + 1 : ""}</span>
                  <Select value={s.col} onChange={(v) => setStressAt(j, { col: v })} options={colOpts} placeholder="column…" />
                  <input className="alt-map-label" type="text" placeholder="label (optional)"
                         value={s.label} onChange={(e) => setStressAt(j, { label: e.target.value })} />
                </div>
              ))}
              <div className="alt-map-row">
                <span className="alt-map-k">Censor flag (c) <span className="muted">optional</span></span>
                <Select value={map.c} onChange={(v) => setMap((m) => ({ ...m, c: v }))}
                        options={[{ value: "", label: "— none —" }, ...colOpts]} />
              </div>
              <div className="alt-map-row">
                <span className="alt-map-k">Count (n) <span className="muted">optional</span></span>
                <Select value={map.n} onChange={(v) => setMap((m) => ({ ...m, n: v }))}
                        options={[{ value: "", label: "— none —" }, ...colOpts]} />
              </div>
              <label className="alt-map-row">
                <span className="alt-map-k">Time unit <span className="muted">optional</span></span>
                <input className="alt-map-label" type="text" placeholder="e.g. hours"
                       value={unit} onChange={(e) => setUnit(e.target.value)} />
              </label>
            </div>
            {!mappingValid && (
              <p className="hint">Map a failure-time column and {nStress} distinct stress column{nStress > 1 ? "s" : ""}.</p>
            )}
          </div>
        )}

        {step === 4 && result && (
          <div className="fit-step">
            <label className="login-field">
              <span>Model name</span>
              <input type="text" autoFocus value={name} placeholder="e.g. Valve seal — Arrhenius"
                     onChange={(e) => setName(e.target.value)} />
            </label>
            <p className="muted-line" style={{ margin: 0 }}>
              Review the life-stress fit below. Go <b>Back</b> to change anything and re-fit, or save it — the
              use-level calculator is available once saved.
            </p>
            <AltResultView results={result.results} />
          </div>
        )}

        {error && <div className="error">{error}</div>}

        <div className="fit-flow-foot">
          {stepper}
          <div className="row" style={{ margin: 0 }}>{nav}</div>
        </div>
      </div>
    </div>
  );
}
