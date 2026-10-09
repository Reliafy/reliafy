import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import DegradationNewModal from "../components/DegradationNewModal.jsx";
import DegradationResultView from "../components/DegradationResultView.jsx";
import { listDegradationModels, saveDegradationModel, deleteDegradationModel } from "../api.js";
import ListSearch, { matches } from "../components/ListSearch.jsx";
import { relativeTime } from "../instrument.js";
import { FirstRunStrip } from "../components/FirstRun.jsx";
import { useFirstRun } from "../firstRun.js";
import Chip from "../components/ui/Chip.jsx";
import PageHeader from "../components/ui/PageHeader.jsx";
import { PlusIcon, RowActions, SampleGroups, itemName } from "../components/LibRows.jsx";

// Landing page for degradation models: list, create (3-step modal + save bar),
// open, delete. Lives inside the Modelling section.
export default function DegradationHome() {
  const navigate = useNavigate();
  const [models, setModels] = useState(null);
  // No models, datasets or diagrams of their own yet (samples don't count).
  const firstRun = useFirstRun(models ? models.some((m) => !m.is_sample) : undefined);
  const [query, setQuery] = useState("");
  const [modalOpen, setModalOpen] = useState(false);
  const [pending, setPending] = useState(null); // { result, fit }
  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  const refresh = useCallback(() => {
    listDegradationModels()
      .then((d) => setModels(d.models))
      .catch((e) => setError(e.message));
  }, []);
  useEffect(() => refresh(), [refresh]);

  const onFitted = ({ result, fit }) => {
    setPending({ result, fit });
    setName(`Degradation — ${result.results.path_model.name.toLowerCase()} to ${result.results.threshold}${result.results.measurement_unit ? " " + result.results.measurement_unit : ""}`);
    setError(null);
    setModalOpen(false);
  };

  const onSave = async () => {
    if (!name.trim() || !pending) return;
    setSaving(true);
    setError(null);
    try {
      const { fit } = pending;
      const saved = await saveDegradationModel(name.trim(), fit.file, fit);
      navigate(`/modelling/degradation/${saved.id}`);
    } catch (err) {
      setError(err.code === "cap" ? err.message : err.message);
    } finally {
      setSaving(false);
    }
  };

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

      <FirstRunStrip info={firstRun} />

      {error && <div className="card error">{error}</div>}

      {pending ? (
        <div className="card">
          <div className="save-bar">
            <input
              className="save-name"
              type="text"
              value={name}
              placeholder="Model name"
              onChange={(e) => setName(e.target.value)}
            />
            <button onClick={onSave} disabled={saving || !name.trim()}>
              {saving ? "Saving…" : "Save model"}
            </button>
            <button className="secondary" onClick={() => setPending(null)}>Discard</button>
          </div>
          <DegradationResultView results={pending.result.results} />
        </div>
      ) : models === null ? (
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
        <DegradationNewModal onClose={() => setModalOpen(false)} onFitted={onFitted} />
      )}
    </div>
  );
}
