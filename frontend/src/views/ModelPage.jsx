import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import ResultView from "../components/ResultView.jsx";
import EditFitModal from "../components/EditFitModal.jsx";
import { ShareButton } from "../components/ShareDialog.jsx";
import { getModel, deleteModel } from "../api.js";
import { distColor, relativeTime } from "../instrument.js";

// Compact overflow ("…") menu for secondary actions. Closes on outside click.
function OverflowMenu({ children }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return;
    const onDoc = (e) => { if (!ref.current?.contains(e.target)) setOpen(false); };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);
  return (
    <div className="ovm" ref={ref}>
      <button
        className="secondary ovm-trigger"
        aria-label="More actions"
        title="More actions"
        onClick={() => setOpen((o) => !o)}
      >
        <svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor">
          <circle cx="5" cy="12" r="1.8" /><circle cx="12" cy="12" r="1.8" /><circle cx="19" cy="12" r="1.8" />
        </svg>
      </button>
      {open && (
        <div className="ovm-menu" onClick={() => setOpen(false)}>
          {children}
        </div>
      )}
    </div>
  );
}

// Reopen a saved model by id and render its cached results.
export default function ModelPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [model, setModel] = useState(null);
  const [error, setError] = useState(null);
  const [editing, setEditing] = useState(false);

  useEffect(() => {
    setModel(null);
    setError(null);
    getModel(id)
      .then(setModel)
      .catch((err) => setError(err.message));
  }, [id]);

  const onDelete = async () => {
    if (!window.confirm(`Delete “${model.name}”?`)) return;
    await deleteModel(id);
    navigate("/modelling/models");
  };

  const canEdit = model && !model.read_only && model.dataset_id;

  return (
    <div className="app model-page">
      <header>
        <div>
          <div className="crumb">
            <button className="crumb-link" onClick={() => navigate("/modelling")}>Modelling</button> /{" "}
            <button className="crumb-link" onClick={() => navigate("/modelling/models")}>Models</button> /{" "}
            <b>{model ? model.name : "Model"}</b>
          </div>
          <div className="title-row">
            <h1>{model ? model.name : "Model"}</h1>
            {model && (
              <span className="dpill">
                <span className="dot" style={{ background: distColor(model.results?.distribution) }} />
                {model.results?.distribution}
              </span>
            )}
            {model && (
              <span className="page-meta">
                Saved {relativeTime(model.created_at)}
                {model.unit ? ` · ${model.unit}` : ""}
              </span>
            )}
          </div>
        </div>
        {model && (
          <div className="head-actions">
            {canEdit && <button onClick={() => setEditing(true)}>Edit fit</button>}
            <OverflowMenu>
              <ShareButton
                collection="models"
                artifactId={model.id}
                name={model.name}
                readOnly={model.read_only}
                className="ovm-item"
              />
              <button className="ovm-item danger" onClick={onDelete}>
                {model.read_only ? "Remove from my view" : "Delete"}
              </button>
            </OverflowMenu>
          </div>
        )}
      </header>

      {error && <div className="card error">{error}</div>}
      {model && (
        <div className="card">
          <ResultView result={model.results} hideHead />
        </div>
      )}
      {editing && model && (
        <EditFitModal
          model={model}
          onClose={() => setEditing(false)}
          onUpdated={(updated) => {
            setModel(updated);
            setEditing(false);
          }}
        />
      )}
    </div>
  );
}
