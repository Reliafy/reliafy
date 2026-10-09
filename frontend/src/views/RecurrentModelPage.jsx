import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import RecurrentResultView from "../components/RecurrentResultView.jsx";
import RecurrentOverhaul from "../components/RecurrentOverhaul.jsx";
import RecurrentProjection from "../components/RecurrentProjection.jsx";
import { ShareButton } from "../components/ShareDialog.jsx";
import { getRecurrentModel, deleteRecurrentModel } from "../api.js";
import { relativeTime } from "../instrument.js";
import Chip from "../components/ui/Chip.jsx";
import PageHeader from "../components/ui/PageHeader.jsx";

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
      <PageHeader
        crumbs={[{ label: "Modelling", to: "/modelling" }, { label: "Recurrent events", to: "/modelling/recurrent" }]}
        title={model ? model.name : "Model"}
        badges={model && <Chip dot={GROWTH_COLOR[r.growth] || "#6c727c"}>{r.model?.name || "Recurrent"}</Chip>}
        meta={model && <>Saved {relativeTime(model.created_at)}{r.unit ? ` · ${r.unit}` : ""}</>}
        id={model?.id}
        menu={model && (
          <>
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
          </>
        )}
      />

      {error && <div className="card error">{error}</div>}
      {model && (
        <div className="card">
          <RecurrentResultView results={model.results} name={model.name} />
        </div>
      )}
      {model && (
        <div className="card">
          <RecurrentOverhaul modelId={model.id} unit={r.unit} name={model.name} />
        </div>
      )}
      {model && !model.spec?.params_only && (
        <div className="card">
          <RecurrentProjection modelId={model.id} unit={r.unit} />
        </div>
      )}
    </div>
  );
}
