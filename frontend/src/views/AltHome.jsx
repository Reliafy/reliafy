import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import AltLibrary from "./AltLibrary.jsx";
import { listAltModels, deleteAltModel } from "../api.js";
import { PlusIcon, itemName } from "../components/LibRows.jsx";
import { SectionHeader } from "../components/SectionPage.jsx";

const HELP = { guide: "accelerated-life-testing" };

// Modelling › Accelerated life: ALT models. The fit flow lives on its own
// page (/modelling/alt/new).
export default function AltHome() {
  const navigate = useNavigate();
  const [models, setModels] = useState(null);
  const [error, setError] = useState(null);

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

  const newModel = <button onClick={() => navigate("/modelling/alt/new")}><PlusIcon /> New model</button>;
  return (
    <div className="app">
      <SectionHeader
        section="modelling"
        title="Accelerated life"
        purpose={<>Failure times at elevated stress, extrapolated to your use level. Planning a test first?{" "}
          <Link to="/strategy/test-planning/accelerated">Plan an accelerated test</Link>.</>}
        help={HELP}
        actions={null}
        primary={newModel}
      />

      {error && <div className="card error">{error}</div>}

      <AltLibrary
        models={models}
        onOpen={(id) => navigate(`/modelling/alt/${id}`)}
        onDelete={onDelete}
        help={HELP}
        empty={{
          title: "No accelerated-life models yet",
          body: "Fit one from failure times at two or more stress levels and save it to see it here.",
          action: newModel,
        }}
      />
    </div>
  );
}
