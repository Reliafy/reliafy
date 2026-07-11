import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import DegradationNewModal from "../components/DegradationNewModal.jsx";
import DegradationResultView from "../components/DegradationResultView.jsx";
import { listDegradationModels, saveDegradationModel, deleteDegradationModel } from "../api.js";
import { relativeTime } from "../instrument.js";

const PlusIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 5v14M5 12h14" />
  </svg>
);
const OpenIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M7 17 17 7M9 7h8v8" />
  </svg>
);
const TrashIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M4 7h16M9 7V5h6v2M7 7l1 13h8l1-13" />
  </svg>
);

// Landing page for degradation models: list, create (3-step modal + save bar),
// open, delete. Lives inside the Modelling section.
export default function DegradationHome() {
  const navigate = useNavigate();
  const [models, setModels] = useState(null);
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
      ? `Remove the sample “${m.name}” from your workspace? It stays available to other users.`
      : `Delete “${m.name}” and its tracked items?`;
    if (!window.confirm(msg)) return;
    await deleteDegradationModel(m.id);
    refresh();
  };

  return (
    <div className="app">
      <header>
        <div>
          <div className="crumb">
            <button className="crumb-link" onClick={() => navigate("/modelling")}>Modelling</button> / <b>Degradation</b>
          </div>
          <h1>Degradation &amp; RUL</h1>
          <p>
            Model how your assets wear toward a failure threshold. Individual
            items are monitored under Strategy → Item tracking.
          </p>
        </div>
        <button onClick={() => setModalOpen(true)}>
          <PlusIcon /> New degradation model
        </button>
      </header>

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
            <PlusIcon /> New degradation model
          </button>
        </div>
      ) : (
        <div className="lib">
          <table className="lib-table">
            <thead>
              <tr>
                <th style={{ width: "34%" }}>Model</th>
                <th>Path</th>
                <th style={{ width: 100 }}>Threshold</th>
                <th style={{ width: 80 }}>Items</th>
                <th style={{ width: 100 }}>Tracked</th>
                <th>Saved</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {models.map((m) => (
                <tr key={m.id} className="lib-row" onClick={() => navigate(`/modelling/degradation/${m.id}`)}>
                  <td>
                    <div className="lib-name">
                      {m.name}
                      {m.is_sample && <span className="sample-tag">Sample</span>}
                    </div>
                  </td>
                  <td>{m.path_model || "—"}</td>
                  <td className="lib-n">{m.threshold}{m.measurement_unit ? ` ${m.measurement_unit}` : ""}</td>
                  <td className="lib-n">{m.n_units}</td>
                  <td className="lib-n">{m.n_items}</td>
                  <td className="lib-date">{relativeTime(m.updated_at || m.created_at)}</td>
                  <td className="lib-actions">
                    <div className="lib-acts">
                      <button className="act" title="Open" onClick={(e) => { e.stopPropagation(); navigate(`/modelling/degradation/${m.id}`); }}>
                        <OpenIcon />
                      </button>
                      <button className="act del" title="Delete" onClick={(e) => { e.stopPropagation(); onDelete(m); }}>
                        <TrashIcon />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {modalOpen && (
        <DegradationNewModal onClose={() => setModalOpen(false)} onFitted={onFitted} />
      )}
    </div>
  );
}
