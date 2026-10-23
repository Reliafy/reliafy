import { useState } from "react";
import { useNavigate } from "react-router-dom";
import ModelLibrary from "./ModelLibrary.jsx";
import { useModels } from "../useModels.js";
import { deleteModel } from "../api.js";
import { PlusIcon, itemName } from "../components/LibRows.jsx";
import { SectionHeader } from "../components/SectionPage.jsx";
import UnsavedFitReminder from "../components/UnsavedFitReminder.jsx";
import { useConfirm } from "../components/ConfirmProvider.jsx";
import { deleteOrRemoveConfirm } from "../confirm.js";

const HELP = { walkthrough: "fit", guide: "fit-your-first-model" };

// Model › Non-repairable: the life-data models list.
export default function ModellingHome() {
  const navigate = useNavigate();
  const { models, loading, refresh } = useModels();
  const [error, setError] = useState(null);

  const confirm = useConfirm();
  const onDelete = async (m) => {
    if (!(await confirm(deleteOrRemoveConfirm(m, "model", { name: itemName(m) })))) return;
    try {
      await deleteModel(m.id);
      refresh();
    } catch (err) {
      setError(err.message);
    }
  };

  const newModel = <button onClick={() => navigate("/models/new")}><PlusIcon /> New model</button>;
  return (
    <div className="app">
      <SectionHeader
        section="models"
        title="Non-repairable models"
        purpose="Life distributions and proportional-hazards models fitted to failure and running times."
        help={HELP}
        primary={newModel}
      />

      <UnsavedFitReminder />

      {error && <div className="card error">{error}</div>}

      <ModelLibrary
        models={loading ? null : models}
        onOpen={(id) => navigate(`/models/m/${id}`)}
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
