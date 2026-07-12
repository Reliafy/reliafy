import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import ResultView from "../components/ResultView.jsx";
import EditFitModal from "../components/EditFitModal.jsx";
import { ShareButton } from "../components/ShareDialog.jsx";
import { getModel, deleteModel } from "../api.js";
import { distColor } from "../instrument.js";

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

  return (
    <div className="app">
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
          </div>
          {model && (
            <p>
              Saved {new Date(model.created_at).toLocaleString()}
              {model.unit ? ` · unit: ${model.unit}` : ""}
            </p>
          )}
        </div>
        {model && (
          <div className="head-actions">
            {!model.read_only && (
              <button className="secondary" onClick={() => setEditing(true)}>
                Edit fit
              </button>
            )}
            <ShareButton
              collection="models"
              artifactId={model.id}
              name={model.name}
              readOnly={model.read_only}
            />
            <button className="secondary" onClick={onDelete}>
              {model.read_only ? "Remove from my view" : "Delete"}
            </button>
          </div>
        )}
      </header>

      {error && <div className="card error">{error}</div>}
      {model && (
        <div className="card">
          <ResultView result={model.results} />
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
