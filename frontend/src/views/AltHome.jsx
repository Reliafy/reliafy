import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import AltLibrary from "./AltLibrary.jsx";
import { listAltModels, deleteAltModel } from "../api.js";

// Accelerated life (ALT) models — mirrors the life-data and recurrent homes:
// header + "New model" button, then the saved-model library. The fit flow lives
// on its own page (/modelling/alt/new).
export default function AltHome() {
  const navigate = useNavigate();
  const [models, setModels] = useState(null);

  const refresh = () => listAltModels().then((r) => setModels(r.models)).catch(() => setModels([]));
  useEffect(() => { refresh(); }, []);

  const onDelete = async (m) => {
    const msg = m.is_sample
      ? `Remove the sample “${m.name}” from your workspace?`
      : `Delete “${m.name}”?`;
    if (!window.confirm(msg)) return;
    await deleteAltModel(m.id);
    refresh();
  };

  return (
    <div className="app">
      <header>
        <div>
          <div className="crumb">
            <button className="crumb-link" onClick={() => navigate("/modelling")}>Modelling</button> / <b>Accelerated life</b>
          </div>
          <h1>Accelerated life</h1>
          <p>
            Fit failure times gathered at elevated stresses — temperature,
            voltage, load — with a life-stress relationship, then extrapolate to
            your use level and read the acceleration factor.
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

      <AltLibrary
        models={models || []}
        loading={models === null}
        onOpen={(id) => navigate(`/modelling/alt/${id}`)}
        onDelete={onDelete}
      />
    </div>
  );
}
