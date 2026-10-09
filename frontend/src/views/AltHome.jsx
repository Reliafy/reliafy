import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import AltLibrary from "./AltLibrary.jsx";
import { listAltModels, deleteAltModel } from "../api.js";
import { FirstRunStrip } from "../components/FirstRun.jsx";
import { useFirstRun } from "../firstRun.js";
import PageHeader from "../components/ui/PageHeader.jsx";
import { PlusIcon, itemName } from "../components/LibRows.jsx";

// Accelerated life (ALT) models — mirrors the life-data and recurrent lists:
// header + "New model", then the saved-model list. The fit flow lives on its
// own page (/modelling/alt/new).
export default function AltHome() {
  const navigate = useNavigate();
  const [models, setModels] = useState(null);
  const [error, setError] = useState(null);
  // No models, datasets or diagrams of their own yet (samples don't count).
  const firstRun = useFirstRun(models ? models.some((m) => !m.is_sample) : undefined);

  const refresh = () => listAltModels().then((r) => setModels(r.models)).catch(() => setModels([]));
  useEffect(() => { refresh(); }, []);

  const onDelete = async (m) => {
    const msg = m.is_sample
      ? `Remove the sample “${itemName(m)}” from your workspace? It stays available to other users and you won't see it again.`
      : `Delete “${m.name}”?`;
    if (!window.confirm(msg)) return;
    try {
      await deleteAltModel(m.id);
      refresh();
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <div className="app">
      <PageHeader
        crumbs={[{ label: "Modelling", to: "/modelling" }]}
        title="Accelerated life"
        meta="Failure times at elevated stress, extrapolated to your use level."
        primary={<button onClick={() => navigate("/modelling/alt/new")}><PlusIcon /> New model</button>}
      />

      <FirstRunStrip info={firstRun} />

      {error && <div className="card error">{error}</div>}

      <AltLibrary
        models={models || []}
        loading={models === null}
        onOpen={(id) => navigate(`/modelling/alt/${id}`)}
        onDelete={onDelete}
      />
    </div>
  );
}
