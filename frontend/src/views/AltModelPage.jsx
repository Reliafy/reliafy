import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import AltResultView from "../components/AltResultView.jsx";
import OverflowMenu from "../components/OverflowMenu.jsx";
import CopyId from "../components/CopyId.jsx";
import { ShareButton } from "../components/ShareDialog.jsx";
import { getAltModel, deleteAltModel } from "../api.js";
import { relativeTime } from "../instrument.js";

// A saved Accelerated Life model — mirrors the other model pages: title row with
// a model pill + saved meta, then the life-stress result view with the use-level
// calculator.
export default function AltModelPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [model, setModel] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    setModel(null);
    getAltModel(id).then(setModel).catch((e) => setError(e.message));
  }, [id]);

  const onDelete = async () => {
    if (!window.confirm(`Delete “${model.name}”?`)) return;
    await deleteAltModel(id);
    navigate("/modelling/alt");
  };

  const r = model?.results || {};

  return (
    <div className="app model-page">
      <header>
        <div>
          <div className="crumb">
            <button className="crumb-link" onClick={() => navigate("/modelling")}>Modelling</button> /{" "}
            <button className="crumb-link" onClick={() => navigate("/modelling/alt")}>Accelerated life</button> /{" "}
            <b>{model ? model.name : "Model"}</b>
          </div>
          <div className="title-row">
            <h1>{model ? model.name : "Model"}</h1>
            {model && (
              <span className="dpill">
                <span className="dot" style={{ background: "#2f6df6" }} />
                {r.distribution} · {r.life_model}
              </span>
            )}
            {model && (
              <span className="page-meta">
                Saved {relativeTime(model.created_at)}{r.unit ? ` · ${r.unit}` : ""}
              </span>
            )}
          </div>
          {model && <CopyId id={model.id} />}
        </div>
        {model && (
          <div className="head-actions">
            <OverflowMenu>
              <ShareButton
                collection="alt_models"
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
          <AltResultView results={model.results} modelId={model.id} />
        </div>
      )}
    </div>
  );
}
