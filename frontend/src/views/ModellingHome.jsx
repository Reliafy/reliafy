import { useState } from "react";
import { useNavigate } from "react-router-dom";
import PerDemandModal from "../components/PerDemandModal.jsx";
import ModelLibrary from "./ModelLibrary.jsx";
import { useModels } from "../useModels.js";
import { deleteModel } from "../api.js";

export default function ModellingHome() {
  const navigate = useNavigate();
  const { models, loading, refresh } = useModels();
  const [perDemandOpen, setPerDemandOpen] = useState(false);

  const onDelete = async (m) => {
    const msg = m.is_sample
      ? `Remove the sample “${m.name}” from your workspace? It stays available to other users and you won't see it again.`
      : `Delete “${m.name}”?`;
    if (!window.confirm(msg)) return;
    await deleteModel(m.id);
    refresh();
  };

  return (
    <div className="app">
      <header>
        <div>
          <div className="crumb">
            <button className="crumb-link" onClick={() => navigate("/modelling")}>Modelling</button> / <b>Life data models</b>
          </div>
          <h1>Life data models</h1>
          <p>
            Fitted life-distribution and proportional-hazards models. Reopen to
            inspect, predict, or export.
          </p>
        </div>
        <div className="row" style={{ margin: 0, gap: "0.5rem" }}>
          <button className="secondary" onClick={() => setPerDemandOpen(true)}>
            Per-demand
          </button>
          <button onClick={() => navigate("/modelling/new")}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 5v14M5 12h14" />
            </svg>
            New model
          </button>
        </div>
      </header>

      <ModelLibrary
        models={models}
        loading={loading}
        onOpen={(id) => navigate(`/modelling/m/${id}`)}
        onDelete={onDelete}
      />

      {perDemandOpen && (
        <PerDemandModal
          onClose={() => setPerDemandOpen(false)}
          onCreated={(model) => {
            setPerDemandOpen(false);
            refresh();
            navigate(`/modelling/m/${model.id}`);
          }}
        />
      )}
    </div>
  );
}
