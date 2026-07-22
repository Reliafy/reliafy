import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import RecurrentResultView from "../components/RecurrentResultView.jsx";
import OverflowMenu from "../components/OverflowMenu.jsx";
import CopyId from "../components/CopyId.jsx";
import { ShareButton } from "../components/ShareDialog.jsx";
import { getRecurrentModel, deleteRecurrentModel } from "../api.js";
import { relativeTime } from "../instrument.js";

const GROWTH_COLOR = { improving: "#2faa6a", stable: "#6c727c", deteriorating: "#d05a5a" };

// A saved recurrent-event model — mirrors the life-data model page: title row
// with a growth pill + saved meta, and its MCF / Crow-AMSAA result view.
export default function RecurrentModelPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [model, setModel] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    setModel(null);
    getRecurrentModel(id).then(setModel).catch((e) => setError(e.message));
  }, [id]);

  const onDelete = async () => {
    if (!window.confirm(`Delete “${model.name}”?`)) return;
    await deleteRecurrentModel(id);
    navigate("/modelling/recurrent");
  };

  const r = model?.results || {};

  return (
    <div className="app model-page">
      <header>
        <div>
          <div className="crumb">
            <button className="crumb-link" onClick={() => navigate("/modelling")}>Modelling</button> /{" "}
            <button className="crumb-link" onClick={() => navigate("/modelling/recurrent")}>Recurrent events</button> /{" "}
            <b>{model ? model.name : "Model"}</b>
          </div>
          <div className="title-row">
            <h1>{model ? model.name : "Model"}</h1>
            {model && (
              <span className="dpill">
                <span className="dot" style={{ background: GROWTH_COLOR[r.growth] || "#6c727c" }} />
                {r.model?.name || "Recurrent"}
              </span>
            )}
            {model && (
              <span className="page-meta">
                Saved {relativeTime(model.created_at)}
                {r.unit ? ` · ${r.unit}` : ""}
              </span>
            )}
          </div>
          {model && <CopyId id={model.id} />}
        </div>
        {model && (
          <div className="head-actions">
            <OverflowMenu>
              <ShareButton
                collection="recurrent_models"
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
          <RecurrentResultView results={model.results} />
        </div>
      )}
    </div>
  );
}
