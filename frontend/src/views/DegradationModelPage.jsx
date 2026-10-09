import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import DegradationResultView from "../components/DegradationResultView.jsx";
import { ShareButton } from "../components/ShareDialog.jsx";
import { getDegradationModel } from "../api.js";
import Chip from "../components/ui/Chip.jsx";
import PageHeader from "../components/ui/PageHeader.jsx";
import { itemName } from "../components/LibRows.jsx";
import { relativeTime } from "../instrument.js";

// One saved degradation model, in the life model page's shape: the header,
// then one card with the tabs, each chart beside its side panel. The fleet of
// tracked items lives under Fleet → Degradation tracking ("Track items").
export default function DegradationModelPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [model, setModel] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    getDegradationModel(id)
      .then(setModel)
      .catch((e) => setError(e.message));
  }, [id]);

  if (error) {
    return (
      <div className="app">
        <header><h1>Degradation model</h1></header>
        <div className="card error">{error}</div>
      </div>
    );
  }
  if (!model) return <div className="app"><div className="card empty">Loading…</div></div>;

  const unit = model.results?.unit || "";
  const nItems = (model.items || []).length;

  return (
    <div className="app model-page">
      <PageHeader
        crumbs={[{ label: "Modelling", to: "/modelling" }, { label: "Degradation", to: "/modelling/degradation" }]}
        title={itemName(model)}
        badges={model.is_sample && <Chip>Sample</Chip>}
        meta={
          <>
            Saved {relativeTime(model.updated_at || model.created_at)}
            {unit ? ` · ${unit}` : ""}
          </>
        }
        primary={
          <button onClick={() => navigate("/fleet/tracking")}>
            Track items{nItems > 0 ? ` (${nItems})` : ""}
          </button>
        }
        id={model.id || id}
        menu={
          <ShareButton
            collection="degradation_models"
            artifactId={model.id}
            name={model.name}
            readOnly={model.read_only}
            className="ovm-item"
          />
        }
      />

      <div className="card">
        <DegradationResultView results={model.results} modelId={model.id || id} name={model.name} />
      </div>
    </div>
  );
}
