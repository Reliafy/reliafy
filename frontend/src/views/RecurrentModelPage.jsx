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
import { itemName } from "../components/LibRows.jsx";

// A saved recurrent-event model, laid out like the life model page (#65): title
// and saved meta, then one card of tabs: the MCF plot with its panel, the
// calculator, the model's own views, the overhaul interval and the growth
// projection.
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
  // The saved model's own tools, as tabs after its results (#65): the overhaul
  // interval needs a minimal-repair model; a growth projection needs data.
  const tools = model ? [
    (r.family || "nhpp") === "nhpp" && {
      id: "overhaul", label: "Overhaul",
      render: () => <RecurrentOverhaul modelId={model.id} unit={r.unit} name={model.name} />,
    },
    !model.spec?.params_only && {
      id: "projection", label: "Growth projection",
      render: () => <RecurrentProjection modelId={model.id} unit={r.unit} />,
    },
  ].filter(Boolean) : [];

  return (
    <div className="app model-page">
      <PageHeader
        crumbs={[{ label: "Modelling", to: "/modelling" }, { label: "Recurrent events", to: "/modelling/recurrent" }]}
        title={model ? itemName(model) : "Model"}
        badges={model?.is_sample && <Chip>Sample</Chip>}
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
          <RecurrentResultView results={model.results} name={model.name} extraTabs={tools} />
        </div>
      )}
    </div>
  );
}
