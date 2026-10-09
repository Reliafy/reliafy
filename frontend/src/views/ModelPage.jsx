import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import ResultView from "../components/ResultView.jsx";
import EditFitModal from "../components/EditFitModal.jsx";
import { ShareButton } from "../components/ShareDialog.jsx";
import { getModel, deleteModel } from "../api.js";
import { relativeTime } from "../instrument.js";
import Chip from "../components/ui/Chip.jsx";
import PageHeader from "../components/ui/PageHeader.jsx";
import { itemName } from "../components/LibRows.jsx";

// Reopen a saved model by id and render its cached results. The answer card
// names the distribution, so the header doesn't.
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
    navigate("/modelling/life");
  };

  const canEdit = model && !model.read_only && model.dataset_id;

  return (
    <div className="app model-page">
      <PageHeader
        crumbs={[{ label: "Modelling", to: "/modelling" }, { label: "Life data models", to: "/modelling/life" }]}
        title={model ? itemName(model) : "Model"}
        badges={model?.is_sample && <Chip>Sample</Chip>}
        meta={model && <>Saved {relativeTime(model.created_at)}{model.unit ? ` · ${model.unit}` : ""}</>}
        actions={canEdit && <button className="secondary" onClick={() => setEditing(true)}>Edit fit</button>}
        id={model?.id}
        menu={model && (
          <>
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
          </>
        )}
      />

      {error && <div className="card error">{error}</div>}
      {model && (
        <div className="card">
          <ResultView result={model.results} modelId={model.id} name={model.name} />
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
