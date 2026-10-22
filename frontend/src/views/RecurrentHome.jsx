import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import RecurrentLibrary from "./RecurrentLibrary.jsx";
import { listRecurrentModels, deleteRecurrentModel } from "../api.js";
import { PlusIcon, itemName } from "../components/LibRows.jsx";
import { SectionHeader } from "../components/SectionPage.jsx";
import { useConfirm } from "../components/ConfirmProvider.jsx";
import { deleteOrRemoveConfirm } from "../confirm.js";

const HELP = { guide: "recurrent-events" };

// Modelling › Recurrent: repairable-system models. The fit flow lives on its
// own page (/modelling/recurrent/new).
export default function RecurrentHome() {
  const navigate = useNavigate();
  const [models, setModels] = useState(null);
  const [error, setError] = useState(null);

  const refresh = () => listRecurrentModels().then((r) => setModels(r.models)).catch(() => setModels([]));
  useEffect(() => { refresh(); }, []);

  const confirm = useConfirm();
  const onDelete = async (m) => {
    if (!(await confirm(deleteOrRemoveConfirm(m, "model", { name: itemName(m) })))) return;
    try {
      await deleteRecurrentModel(m.id);
      refresh();
    } catch (err) {
      setError(err.message);
    }
  };

  const newModel = <button onClick={() => navigate("/modelling/recurrent/new")}><PlusIcon /> New model</button>;
  return (
    <div className="app">
      <SectionHeader
        section="modelling"
        title="Repairable models"
        purpose="Repairable systems: is the failure rate improving or worsening?"
        help={HELP}
        primary={newModel}
      />

      {error && <div className="card error">{error}</div>}

      <RecurrentLibrary
        models={models}
        onOpen={(id) => navigate(`/modelling/recurrent/${id}`)}
        onDelete={onDelete}
        help={HELP}
        empty={{
          title: "No recurrent models yet",
          body: "Fit one from each system's repair or failure times and save it to see it here.",
          action: newModel,
        }}
      />
    </div>
  );
}
