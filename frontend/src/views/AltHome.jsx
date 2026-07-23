import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { listAltModels, deleteAltModel } from "../api.js";
import { relativeTime } from "../instrument.js";

// Accelerated Life Testing models home — mirrors the recurrent/life-data homes:
// header + "New model" button, then the saved-model library. The fit flow lives
// on its own page (/modelling/alt/new).
export default function AltHome() {
  const navigate = useNavigate();
  const [models, setModels] = useState(null);

  const refresh = () => listAltModels().then((r) => setModels(r.models)).catch(() => setModels([]));
  useEffect(() => { refresh(); }, []);

  const onDelete = async (e, m) => {
    e.stopPropagation();
    const msg = m.is_sample ? `Remove the sample “${m.name}”?` : `Delete “${m.name}”?`;
    if (!window.confirm(msg)) return;
    await deleteAltModel(m.id);
    refresh();
  };

  const rows = models || [];
  return (
    <div className="app">
      <header>
        <div>
          <div className="crumb">
            <button className="crumb-link" onClick={() => navigate("/modelling")}>Modelling</button> / <b>Accelerated life</b>
          </div>
          <h1>Accelerated life (ALT)</h1>
          <p>
            Fit failure times gathered at elevated stresses (temperature, voltage,
            load) with a life-stress relationship — then extrapolate to your
            use-level stress and read the acceleration factor.
          </p>
        </div>
        <div className="row" style={{ margin: 0, gap: "0.5rem" }}>
          <button onClick={() => navigate("/modelling/alt/new")}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 5v14M5 12h14" />
            </svg>
            New model
          </button>
        </div>
      </header>

      {models === null ? (
        <div className="card"><p className="muted-line">Loading…</p></div>
      ) : rows.length === 0 ? (
        <div className="card empty-note">
          <p>No accelerated-life models yet.</p>
          <p className="muted-line">
            Start from a CSV of failure times with one or two stress columns —
            e.g. hours-to-failure at 320 K / 340 K / 360 K.
          </p>
          <button onClick={() => navigate("/modelling/alt/new")}>Fit your first ALT model</button>
        </div>
      ) : (
        <div className="card lib">
          <table className="lib-table">
            <thead>
              <tr><th>Name</th><th>Model</th><th>Stresses</th><th>n</th><th>Saved</th><th /></tr>
            </thead>
            <tbody>
              {rows.map((m) => (
                <tr key={m.id} className="lib-row" onClick={() => navigate(`/modelling/alt/${m.id}`)}>
                  <td>{m.name}{m.is_sample && <span className="sample-tag">Sample</span>}</td>
                  <td>{m.distribution} · {m.life_model}</td>
                  <td>{m.n_stresses}</td>
                  <td>{m.n}</td>
                  <td className="muted">{relativeTime(m.created_at)}</td>
                  <td>
                    <button className="act danger" onClick={(e) => onDelete(e, m)}>
                      {m.read_only ? "Remove" : "Delete"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
