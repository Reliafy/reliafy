import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import Select from "../components/Select.jsx";
import RecurrentResultView from "../components/RecurrentResultView.jsx";
import {
  getRecurrentOptions,
  listRecurrentModels,
  getColumns,
  fitRecurrent,
  saveRecurrentModel,
  deleteRecurrentModel,
} from "../api.js";

// Recurrent-event (repairable-system) modelling: fit a repairable fleet's
// failure history to an MCF + Crow-AMSAA reliability-growth model. Saved models
// are listed; the "new" flow uploads event data, maps columns, fits, and saves.
export default function RecurrentHome() {
  const navigate = useNavigate();
  const [models, setModels] = useState(null);
  const [modelOpts, setModelOpts] = useState([]);
  const [error, setError] = useState(null);

  // New-model flow.
  const [file, setFile] = useState(null);
  const [columns, setColumns] = useState([]);
  const [map, setMap] = useState({ i: "", x: "", t: "" });
  const [model, setModel] = useState("crow_amsaa");
  const [unit, setUnit] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null); // { dataset_id, results }
  const [name, setName] = useState("");

  const refresh = () => listRecurrentModels().then((r) => setModels(r.models)).catch((e) => setError(e.message));
  useEffect(() => {
    getRecurrentOptions().then((o) => setModelOpts(o.models)).catch(() => {});
    refresh();
  }, []);

  const onFile = async (f) => {
    setFile(f); setResult(null); setError(null);
    if (!f) return;
    try {
      const { columns: cols } = await getColumns(f);
      setColumns(cols);
      setMap({ i: cols[0] || "", x: cols[1] || "", t: "" });
    } catch (e) { setError(e.message); }
  };

  const onFit = async () => {
    setBusy(true); setError(null);
    try {
      const res = await fitRecurrent(file, { mapping: map, model, unit });
      setResult(res);
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

  const onDelete = async (m) => {
    if (!window.confirm(`Delete "${m.name}"?`)) return;
    await deleteRecurrentModel(m.id);
    refresh();
  };

  const colOpts = columns.map((c) => ({ value: c, label: c }));
  const canFit = file && map.i && map.x && map.i !== map.x && !busy;

  return (
    <div className="app">
      <header>
        <div>
          <div className="crumb">
            <button className="crumb-link" onClick={() => navigate("/modelling")}>Modelling</button> /{" "}
            <b>Recurrent</b>
          </div>
          <h1>Recurrent events</h1>
          <p>Repairable systems — is the fleet getting better or worse, and how often will it fail?</p>
        </div>
      </header>

      {error && <div className="card error">{error}</div>}

      <div className="card">
        <h2 style={{ marginTop: 0 }}>New recurrent model</h2>
        <p className="muted-line" style={{ marginTop: 0 }}>
          Upload long-format event data — one row per failure/repair: a system id,
          the event time, and (optionally) each system's observation window.
        </p>
        <div className="row" style={{ gap: "0.6rem", flexWrap: "wrap", alignItems: "flex-end" }}>
          <label className="login-field">
            <span>Event data (CSV)</span>
            <input type="file" accept=".csv,text/csv" onChange={(e) => onFile(e.target.files?.[0] || null)} />
          </label>
        </div>

        {columns.length > 0 && (
          <>
            <div className="row" style={{ gap: "0.7rem", flexWrap: "wrap", marginTop: "0.8rem" }}>
              <label className="dist-field" style={{ width: 170 }}>
                <span className="dist-label">System (id)</span>
                <Select value={map.i} onChange={(v) => setMap((m) => ({ ...m, i: v }))} options={colOpts} />
              </label>
              <label className="dist-field" style={{ width: 170 }}>
                <span className="dist-label">Event time</span>
                <Select value={map.x} onChange={(v) => setMap((m) => ({ ...m, x: v }))} options={colOpts} />
              </label>
              <label className="dist-field" style={{ width: 190 }}>
                <span className="dist-label">Observation window (optional)</span>
                <Select value={map.t} onChange={(v) => setMap((m) => ({ ...m, t: v }))}
                        options={[{ value: "", label: "— none (until last event)" }, ...colOpts]} />
              </label>
              <label className="dist-field" style={{ width: 170 }}>
                <span className="dist-label">Model</span>
                <Select value={model} onChange={setModel} options={modelOpts.map((m) => ({ value: m.id, label: m.name }))} />
              </label>
              <label className="login-field" style={{ width: 120 }}>
                <span>Time unit</span>
                <input type="text" value={unit} placeholder="e.g. hours" onChange={(e) => setUnit(e.target.value)} />
              </label>
              <button onClick={onFit} disabled={!canFit}>{busy && !result ? "Fitting…" : "Fit"}</button>
            </div>

            {result && (
              <div style={{ marginTop: "1rem" }}>
                <RecurrentResultView results={result.results} />
                <div className="row" style={{ gap: "0.6rem", alignItems: "flex-end", marginTop: "1rem" }}>
                  <label className="login-field" style={{ flex: 1, maxWidth: 320 }}>
                    <span>Model name</span>
                    <input type="text" value={name} placeholder="e.g. Delivery trucks — engines"
                           onChange={(e) => setName(e.target.value)} />
                  </label>
                  <button onClick={onSave} disabled={!name.trim() || busy}>{busy ? "Saving…" : "Save model"}</button>
                </div>
              </div>
            )}
          </>
        )}
      </div>

      <div className="card" style={{ marginTop: "1rem" }}>
        <h2 style={{ marginTop: 0 }}>Saved recurrent models</h2>
        {models === null ? (
          <p className="muted-line">Loading…</p>
        ) : models.length === 0 ? (
          <div className="empty" style={{ padding: "1.4rem" }}><p>No recurrent models yet.</p></div>
        ) : (
          <table className="lib-table">
            <thead><tr><th>Name</th><th>Model</th><th>Systems</th><th>Growth</th><th /></tr></thead>
            <tbody>
              {models.map((m) => (
                <tr key={m.id} className="lib-row" onClick={() => navigate(`/modelling/recurrent/${m.id}`)}>
                  <td><Link to={`/modelling/recurrent/${m.id}`} className="lib-name" onClick={(e) => e.stopPropagation()}>{m.name}</Link></td>
                  <td className="lib-n">{m.model}</td>
                  <td className="lib-n">{m.n_systems}</td>
                  <td className="lib-n">{m.growth || "—"}</td>
                  <td className="lib-actions">
                    {!m.read_only && (
                      <button className="act del" title="Delete" onClick={(e) => { e.stopPropagation(); onDelete(m); }}>
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M4 7h16M9 7V5h6v2M7 7l1 13h8l1-13" /></svg>
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
