import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import Select from "../components/Select.jsx";
import RecurrentResultView from "../components/RecurrentResultView.jsx";
import {
  getRecurrentOptions,
  getColumns,
  listDatasets,
  getDataset,
  fitRecurrent,
  saveRecurrentModel,
} from "../api.js";

// Dedicated page for building a new recurrent-event model — mirrors the life-
// data "New model" flow: pick a source (upload or a saved dataset), map
// columns, fit, review, save.
export default function RecurrentNewPage() {
  const navigate = useNavigate();
  const [modelOpts, setModelOpts] = useState([]);
  const [datasets, setDatasets] = useState([]);
  const [error, setError] = useState(null);

  const [file, setFile] = useState(null);
  const [datasetId, setDatasetId] = useState(null); // set when a saved dataset is chosen
  const [sourceName, setSourceName] = useState("");
  const [columns, setColumns] = useState([]);
  const [map, setMap] = useState({ i: "", x: "", t: "" });
  const [model, setModel] = useState("crow_amsaa");
  const [unit, setUnit] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null); // { dataset_id, results }
  const [name, setName] = useState("");

  useEffect(() => {
    getRecurrentOptions().then((o) => setModelOpts(o.models)).catch(() => {});
    listDatasets().then((d) => setDatasets(d.datasets)).catch(() => setDatasets([]));
  }, []);

  const onFile = async (f) => {
    setFile(f); setDatasetId(null); setResult(null); setError(null);
    if (!f) return;
    setSourceName(f.name);
    try {
      const { columns: cols } = await getColumns(f);
      setColumns(cols);
      setMap({ i: cols[0] || "", x: cols[1] || "", t: "" });
    } catch (e) { setError(e.message); }
  };

  const onDataset = async (d) => {
    setFile(null); setDatasetId(d.id); setResult(null); setError(null);
    setSourceName(d.name);
    try {
      const full = await getDataset(d.id);
      const cols = full.preview_columns || [];
      setColumns(cols);
      setMap({ i: cols[0] || "", x: cols[1] || "", t: "" });
    } catch (e) { setError(e.message); }
  };

  const onFit = async () => {
    setBusy(true); setError(null);
    try {
      setResult(await fitRecurrent(datasetId ? null : file, { datasetId, mapping: map, model, unit }));
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  };

  const onSave = async () => {
    if (!name.trim()) return;
    setBusy(true); setError(null);
    try {
      const saved = await saveRecurrentModel(name.trim(), null, {
        datasetId: result.dataset_id, mapping: map, model, unit,
      });
      navigate(`/modelling/recurrent/${saved.id}`);
    } catch (e) { setError(e.message); setBusy(false); }
  };

  const colOpts = columns.map((c) => ({ value: c, label: c }));
  const canFit = (file || datasetId) && map.i && map.x && map.i !== map.x && !busy;

  return (
    <div className="app">
      <header>
        <div>
          <div className="crumb">
            <button className="crumb-link" onClick={() => navigate("/modelling")}>Modelling</button> /{" "}
            <button className="crumb-link" onClick={() => navigate("/modelling/recurrent")}>Recurrent events</button> /{" "}
            <b>New model</b>
          </div>
          <h1>Fit to event data</h1>
          <p>Upload — or pick a saved dataset of — a repairable fleet's failure history, map columns, fit, then review and save.</p>
        </div>
      </header>

      {error && <div className="card error">{error}</div>}

      <div className="card">
        <p className="muted-line" style={{ marginTop: 0 }}>
          Long-format event data — one row per failure/repair: a system id, the
          event time, and (optionally) each system's observation window.
        </p>
        <label className="login-field" style={{ maxWidth: 360 }}>
          <span>Event data (CSV)</span>
          <input type="file" accept=".csv,text/csv" onChange={(e) => onFile(e.target.files?.[0] || null)} />
        </label>

        {datasets.length > 0 && (
          <div className="recent" style={{ marginTop: "0.8rem" }}>
            <div className="recent-h">Or use a saved dataset</div>
            {datasets.slice(0, 6).map((d) => (
              <button
                key={d.id}
                type="button"
                className={"recent-row" + (datasetId === d.id ? " selected" : "")}
                disabled={busy}
                onClick={() => onDataset(d)}
              >
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

        {sourceName && columns.length > 0 && (
          <p className="muted-line" style={{ margin: "0.8rem 0 0" }}>
            Source: <b>{sourceName}</b> · {columns.length} columns
          </p>
        )}

        {columns.length > 0 && (
          <div className="row" style={{ gap: "0.7rem", flexWrap: "wrap", marginTop: "0.8rem", alignItems: "flex-end" }}>
            <label className="dist-field" style={{ width: 170 }}>
              <span className="dist-label">System (id)</span>
              <Select value={map.i} onChange={(v) => setMap((m) => ({ ...m, i: v }))} options={colOpts} />
            </label>
            <label className="dist-field" style={{ width: 170 }}>
              <span className="dist-label">Event time</span>
              <Select value={map.x} onChange={(v) => setMap((m) => ({ ...m, x: v }))} options={colOpts} />
            </label>
            <label className="dist-field" style={{ width: 200 }}>
              <span className="dist-label">Observation window (optional)</span>
              <Select value={map.t} onChange={(v) => setMap((m) => ({ ...m, t: v }))}
                      options={[{ value: "", label: "— none (until last event)" }, ...colOpts]} />
            </label>
            <label className="dist-field" style={{ width: 190 }}>
              <span className="dist-label">Model</span>
              <Select value={model} onChange={setModel} options={modelOpts.map((m) => ({ value: m.id, label: m.name }))} />
            </label>
            <label className="login-field" style={{ width: 120 }}>
              <span>Time unit</span>
              <input type="text" value={unit} placeholder="e.g. hours" onChange={(e) => setUnit(e.target.value)} />
            </label>
            <button onClick={onFit} disabled={!canFit}>{busy && !result ? "Fitting…" : "Fit"}</button>
          </div>
        )}
      </div>

      {result && (
        <div style={{ marginTop: "1rem" }}>
          <RecurrentResultView results={result.results} />
          <div className="fit-flow-foot" style={{ marginTop: "1rem" }}>
            <span />
            <div className="row" style={{ margin: 0, gap: "0.6rem", alignItems: "flex-end" }}>
              <label className="login-field" style={{ width: 280 }}>
                <span>Model name</span>
                <input type="text" value={name} placeholder="e.g. Delivery trucks — engines"
                       onChange={(e) => setName(e.target.value)} />
              </label>
              <button onClick={onSave} disabled={!name.trim() || busy}>{busy ? "Saving…" : "Save model"}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
