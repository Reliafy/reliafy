import { useState } from "react";
import { useNavigate } from "react-router-dom";
import ModelLibrary from "./ModelLibrary.jsx";
import { useModels } from "../useModels.js";
import { deleteModel } from "../api.js";
import { PlusIcon, itemName } from "../components/LibRows.jsx";
import { SectionHeader } from "../components/SectionPage.jsx";
import UnsavedFitReminder from "../components/UnsavedFitReminder.jsx";

const HELP = { walkthrough: "fit", guide: "fit-your-first-model" };

// Modelling › Non-repairable models: the life-data models list.
export default function ModellingHome() {
  const navigate = useNavigate();
  const { models, loading, refresh } = useModels();
  const [error, setError] = useState(null);

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

  const newModel = <button onClick={() => navigate("/modelling/new")}><PlusIcon /> New model</button>;
  return (
    <div className="app">
      <SectionHeader
        section="modelling"
        title="Non-repairable models"
        purpose="Life distributions and proportional-hazards models fitted to failure and running times."
        help={HELP}
        primary={newModel}
      />

      <UnsavedFitReminder />

      {error && <div className="card error">{error}</div>}

      <ModelLibrary
        models={loading ? null : models}
        onOpen={(id) => navigate(`/modelling/m/${id}`)}
        onDelete={onDelete}
        help={HELP}
        empty={{
          title: "No non-repairable models yet",
          body: "Upload or paste failure times, fit a distribution and save it to see it here.",
          action: newModel,
        }}
      />
    </div>
  );
}
