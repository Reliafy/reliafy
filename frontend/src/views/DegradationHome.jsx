import { useCallback, useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import DegradationNewModal from "../components/DegradationNewModal.jsx";
import { listDegradationModels, deleteDegradationModel } from "../api.js";
import { relativeTime } from "../instrument.js";
import Chip from "../components/ui/Chip.jsx";
import { PlusIcon, RowActions, itemName } from "../components/LibRows.jsx";
import { SectionHeader, SectionList } from "../components/SectionPage.jsx";

const HELP = { guide: "degradation-modelling" };

// Modelling › Degradation: list, create (a 3-step modal that
// fits, saves and opens the new model's page), open, delete. Lives inside the
// Modelling section.
export default function DegradationHome() {
  const navigate = useNavigate();
  const [models, setModels] = useState(null);
  const [params, setParams] = useSearchParams();
  // ?dataset= (the Data list's Fit menu) opens the new-model flow on that dataset.
  const fromData = params.get("dataset");
  const [modalOpen, setModalOpen] = useState(Boolean(fromData));
  const [error, setError] = useState(null);

  const refresh = useCallback(() => {
    listDegradationModels()
      .then((d) => setModels(d.models))
      .catch((e) => setError(e.message));
  }, []);
  useEffect(() => refresh(), [refresh]);


  const onDelete = async (m) => {
    const msg = m.is_sample
      ? `Remove the sample “${itemName(m)}” from your workspace? It stays available to other users and you won't see it again.`
      : `Delete “${m.name}” and its tracked items?`;
    if (!window.confirm(msg)) return;
    try {
      await deleteDegradationModel(m.id);
      refresh();
    } catch (err) {
      setError(err.message);
    }
  };

  const open = (id) => navigate(`/modelling/degradation/${id}`);
  const newModel = <button onClick={() => setModalOpen(true)}><PlusIcon /> New model</button>;

  return (
    <div className="app">
      <SectionHeader
        section="modelling"
        title="Degradation models"
        purpose="How assets wear toward a failure threshold. Track individual items under Fleet."
        help={HELP}
        primary={newModel}
      />

      {error && <div className="card error">{error}</div>}

      <SectionList
        rows={models}
        noun={["model", "models"]}
        fields={(m) => [m.name, m.path_model]}
        help={HELP}
        empty={{
          title: "No degradation models yet",
          body: "Fit one from measurement histories to start predicting remaining useful life.",
          action: newModel,
        }}
        head={[
          <th key="m" style={{ width: "36%" }}>Model</th>,
          <th key="p">Path</th>,
          <th key="t" className="lib-opt" style={{ width: 110 }}>Threshold</th>,
          <th key="u" className="lib-opt" style={{ width: 80 }}>Items</th>,
          <th key="k" className="lib-opt" style={{ width: 90 }}>Tracked</th>,
          <th key="s" className="lib-opt">Saved</th>,
          <th key="a"><span className="sr-only">Actions</span></th>,
        ]}
        render={(m) => (
          <tr key={m.id} className="lib-row" onClick={() => open(m.id)}>
            <td>
              <div className="lib-name">
                {itemName(m)}
                {m.shared_by && <Chip title={`Shared by ${m.shared_by}`}>Shared</Chip>}
              </div>
            </td>
            <td>{m.path_model || "—"}</td>
            <td className="lib-n lib-opt">{m.threshold}{m.measurement_unit ? ` ${m.measurement_unit}` : ""}</td>
            <td className="lib-n lib-opt">{m.n_units}</td>
            <td className="lib-n lib-opt">{m.n_items}</td>
            <td className="lib-date lib-opt">{relativeTime(m.updated_at || m.created_at)}</td>
            <RowActions item={m} onOpen={() => open(m.id)} onDelete={() => onDelete(m)} />
          </tr>
        )}
      />

      {modalOpen && (
        <DegradationNewModal
          initialDataset={fromData ? { id: fromData, name: "" } : null}
          onClose={() => { setModalOpen(false); if (fromData) setParams({}, { replace: true }); }}
          onSaved={(m) => open(m.id)}
        />
      )}
    </div>
  );
}
