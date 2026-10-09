import { useState } from "react";
import { useNavigate } from "react-router-dom";
import ModelLibrary from "./ModelLibrary.jsx";
import { useModels } from "../useModels.js";
import { deleteModel } from "../api.js";
import { FirstRunStrip } from "../components/FirstRun.jsx";
import { useFirstRun } from "../firstRun.js";
import PageHeader from "../components/ui/PageHeader.jsx";
import { PlusIcon, itemName } from "../components/LibRows.jsx";

// The life-data models list.
export default function ModellingHome() {
  const navigate = useNavigate();
  const { models, loading, refresh } = useModels();
  const [error, setError] = useState(null);
  // No models, datasets or diagrams of their own yet (samples don't count).
  const firstRun = useFirstRun(loading ? undefined : models.some((m) => !m.is_sample));

  const onDelete = async (m) => {
    const msg = m.is_sample
      ? `Remove the sample “${itemName(m)}” from your workspace? It stays available to other users and you won't see it again.`
      : `Delete “${m.name}”?`;
    if (!window.confirm(msg)) return;
    try {
      await deleteModel(m.id);
      refresh();
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <div className="app">
      <PageHeader
        crumbs={[{ label: "Modelling", to: "/modelling" }]}
        title="Life data models"
        meta="Fitted life distributions and proportional-hazards models."
        primary={<button onClick={() => navigate("/modelling/new")}><PlusIcon /> New model</button>}
      />

      <FirstRunStrip info={firstRun} />

      {error && <div className="card error">{error}</div>}

      <ModelLibrary
        models={models}
        loading={loading}
        onOpen={(id) => navigate(`/modelling/m/${id}`)}
        onDelete={onDelete}
      />
    </div>
  );
}
