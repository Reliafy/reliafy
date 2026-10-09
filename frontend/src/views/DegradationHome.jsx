import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import DegradationNewModal from "../components/DegradationNewModal.jsx";
import { listDegradationModels, deleteDegradationModel } from "../api.js";
import ListSearch, { matches } from "../components/ListSearch.jsx";
import { relativeTime } from "../instrument.js";
import Chip from "../components/ui/Chip.jsx";
import PageHeader from "../components/ui/PageHeader.jsx";
import { PlusIcon, RowActions, SampleGroups, itemName } from "../components/LibRows.jsx";

// Landing page for degradation models: list, create (a 3-step modal that
// fits, saves and opens the new model's page), open, delete. Lives inside the
// Modelling section.
export default function DegradationHome() {
  const navigate = useNavigate();
  const [models, setModels] = useState(null);
  const [query, setQuery] = useState("");
  const [modalOpen, setModalOpen] = useState(false);
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
  const visible = (models || []).filter((m) => matches(query, m.name, m.path_model, m.id));

  return (
    <div className="app">
      <PageHeader
        crumbs={[{ label: "Modelling", to: "/modelling" }]}
        title="Degradation models"
        meta="How assets wear toward a failure threshold. Track individual items under Fleet."
        primary={<button onClick={() => setModalOpen(true)}><PlusIcon /> New model</button>}
      />

      {error && <div className="card error">{error}</div>}

      {models === null ? (
        <div className="card empty">Loading…</div>
      ) : models.length === 0 ? (
        <div className="card empty">
          <h2>No degradation models</h2>
          <p>Fit one from measurement histories to start predicting remaining useful life.</p>
          <button style={{ marginTop: "1rem" }} onClick={() => setModalOpen(true)}>
            <PlusIcon /> New model
          </button>
        </div>
      ) : (
        <>
          <div className="tablebar">
            <span className="count">{visible.length} of {models.length} models</span>
            <span className="grow" />
            <ListSearch value={query} onChange={setQuery} placeholder="Search models…" />
          </div>
          <div className="lib">
            <table className="lib-table">
              <thead>
                <tr>
                  <th style={{ width: "36%" }}>Model</th>
                  <th>Path</th>
                  <th className="lib-opt" style={{ width: 110 }}>Threshold</th>
                  <th className="lib-opt" style={{ width: 80 }}>Items</th>
                  <th className="lib-opt" style={{ width: 90 }}>Tracked</th>
                  <th className="lib-opt">Saved</th>
                  <th><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                <SampleGroups rows={visible} cols={7} render={(m) => (
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
                )} />
              </tbody>
            </table>
          </div>
        </>
      )}

      {modalOpen && (
        <DegradationNewModal onClose={() => setModalOpen(false)} onSaved={(m) => open(m.id)} />
      )}
    </div>
  );
}
