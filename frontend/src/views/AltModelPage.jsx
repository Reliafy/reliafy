import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import AltResultView from "../components/AltResultView.jsx";
import { ShareButton } from "../components/ShareDialog.jsx";
import { getAltModel, deleteAltModel } from "../api.js";
import { relativeTime } from "../instrument.js";
import Chip from "../components/ui/Chip.jsx";
import PageHeader from "../components/ui/PageHeader.jsx";
import { itemName } from "../components/LibRows.jsx";

// A saved Accelerated Life model — mirrors the other model pages: title and
// saved meta, then the result view (answer card, life-stress plot, use-level
// calculator).
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
      <PageHeader
        crumbs={[{ label: "Modelling", to: "/modelling" }, { label: "Accelerated life", to: "/modelling/alt" }]}
        title={model ? itemName(model) : "Model"}
        badges={model?.is_sample && <Chip>Sample</Chip>}
        meta={model && <>Saved {relativeTime(model.created_at)}{r.unit ? ` · ${r.unit}` : ""}</>}
        id={model?.id}
        menu={model && (
          <>
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
          </>
        )}
      />

      {error && <div className="card error">{error}</div>}
      {model && (
        <div className="card">
          <AltResultView results={model.results} modelId={model.id} />
        </div>
      )}
    </div>
  );
}
