import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import RecurrentLibrary from "./RecurrentLibrary.jsx";
import { listRecurrentModels, deleteRecurrentModel } from "../api.js";

// Recurrent-event (repairable-system) models — mirrors the life-data models
// home: header + "New model" button, then the saved-model library. The fit
// flow lives on its own page (/modelling/recurrent/new).
export default function RecurrentHome() {
  const navigate = useNavigate();
  const [models, setModels] = useState(null);

  const refresh = () => listRecurrentModels().then((r) => setModels(r.models)).catch(() => setModels([]));
  useEffect(() => { refresh(); }, []);

  const onDelete = async (m) => {
    const msg = m.is_sample
      ? `Remove the sample “${m.name}” from your workspace?`
      : `Delete “${m.name}”?`;
    if (!window.confirm(msg)) return;
    await deleteRecurrentModel(m.id);
    refresh();
  };

  return (
    <div className="app">
      <header>
        <div>
          <div className="crumb">
            <button className="crumb-link" onClick={() => navigate("/modelling")}>Modelling</button> / <b>Recurrent events</b>
          </div>
          <h1>Recurrent events</h1>
          <p>
            Repairable systems — fit a fleet's failure history to an MCF and
            Crow-AMSAA growth model. Is it improving or worsening, and how often
            will it fail?
          </p>
        </div>
        <div className="row" style={{ margin: 0, gap: "0.5rem" }}>
          <button onClick={() => navigate("/modelling/recurrent/new")}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 5v14M5 12h14" />
            </svg>
            New model
          </button>
        </div>
      </header>

      <RecurrentLibrary
        models={models || []}
        loading={models === null}
        onOpen={(id) => navigate(`/modelling/recurrent/${id}`)}
        onDelete={onDelete}
      />
    </div>
  );
}
