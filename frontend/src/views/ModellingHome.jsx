import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import UploadModal from "../components/UploadModal.jsx";
import ResultView from "../components/ResultView.jsx";
import ModelLibrary from "./ModelLibrary.jsx";
import { useModels } from "../useModels.js";
import { saveModel, deleteModel } from "../api.js";

export default function ModellingHome() {
  const navigate = useNavigate();
  const location = useLocation();
  const { models, loading, refresh } = useModels();
  const [modalOpen, setModalOpen] = useState(false);

  // Open the new-model flow directly when arriving from the dashboard card.
  useEffect(() => {
    if (location.state?.openNew) {
      setModalOpen(true);
      window.history.replaceState({}, "");
    }
  }, [location.state]);
  const [pending, setPending] = useState(null); // { result, fit }
  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  const onFitted = ({ result, fit }) => {
    setPending({ result, fit });
    setName(`${result.distribution} — ${fit.file.name.replace(/\.csv$/i, "")}`);
    setError(null);
    setModalOpen(false);
  };

  const onSave = async () => {
    if (!name.trim()) return;
    setSaving(true);
    setError(null);
    try {
      const { fit } = pending;
      const saved = await saveModel(name.trim(), fit.distribution, fit.file, fit.mapping, {
        covariates: fit.covariates,
        formula: fit.formula,
        unit: fit.unit,
        datasetId: fit.datasetId,
      });
      await refresh();
      navigate(`/modelling/m/${saved.id}`);
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  };

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
            <button className="crumb-link" onClick={() => navigate("/modelling")}>Modelling</button> / <b>Saved models</b>
          </div>
          <h1>Models</h1>
          <p>
            Fitted life-distribution and proportional-hazards models. Reopen to
            inspect, predict, or export.
          </p>
        </div>
        <button onClick={() => setModalOpen(true)}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 5v14M5 12h14" />
          </svg>
          New model
        </button>
      </header>

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
            <button className="secondary" onClick={() => setPending(null)}>
              Discard
            </button>
          </div>
          {error && <div className="error">{error}</div>}
          <ResultView result={pending.result} />
        </div>
      ) : (
        <ModelLibrary
          models={models}
          loading={loading}
          onOpen={(id) => navigate(`/modelling/m/${id}`)}
          onDelete={onDelete}
        />
      )}

      {modalOpen && (
        <UploadModal onClose={() => setModalOpen(false)} onFitted={onFitted} />
      )}
    </div>
  );
}
