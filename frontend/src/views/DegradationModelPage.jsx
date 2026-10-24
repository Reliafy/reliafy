import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import DegradationResultView from "../components/DegradationResultView.jsx";
import { ShareButton } from "../components/ShareDialog.jsx";
import { deleteDegradationModel, getDegradationModel, renameDegradationModel } from "../api.js";
import Chip from "../components/ui/Chip.jsx";
import ModelFrame from "../components/model/ModelFrame.jsx";
import useTabParam from "../components/model/useTabParam.js";
import { degradationAnswer } from "../degradationFrame.js";
import { itemName } from "../components/LibRows.jsx";
import { relativeTime } from "../instrument.js";
import { useAskText, useConfirm } from "../components/ConfirmProvider.jsx";
import { changedText, deleteOrRemoveConfirm, renamePrompt } from "../confirm.js";

// One saved degradation model in the model frame: the answer line, the
// result's tabs (in the address, ?tab=), "Track items" (the fleet of tracked
// items lives under Risk), Share, and the ⋯ menu (rename, delete).
export default function DegradationModelPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [model, setModel] = useState(null);
  const [error, setError] = useState(null);
  const [tab, setTab] = useTabParam();

  useEffect(() => {
    setModel(null);
    getDegradationModel(id).then(setModel).catch((e) => setError(e.message));
  }, [id]);

  const confirm = useConfirm();
  const askText = useAskText();
  const onDelete = async () => {
    if (!(await confirm(deleteOrRemoveConfirm(model, "model", { name: itemName(model), extra: "with its tracked items" })))) return;
    try {
      await deleteDegradationModel(id);
      navigate("/models/degradation");
    } catch (e) { setError(e.message); }
  };
  const onRename = async () => {
    const name = changedText(await askText(renamePrompt({ kind: "model", name: model.name })), model.name);
    if (!name) return;
    try {
      const saved = await renameDegradationModel(id, name);
      setModel((m) => ({ ...m, ...saved, name: saved?.name || name }));
    } catch (e) { setError(e.message); }
  };

  const nItems = (model?.items || []).length;
  return (
    <ModelFrame
      className="model-page"
      crumbs={[{ label: "Model", to: "/models" }, { label: "Degradation", to: "/models/degradation" }]}
      title={model ? itemName(model) : error ? "Degradation model" : "Model"}
      badges={model?.is_sample && <Chip>Sample</Chip>}
      answer={model ? degradationAnswer(model.results, { saved: `saved ${relativeTime(model.updated_at || model.created_at)}` }) : null}
      id={model?.id}
      primary={model && (
        <button type="button" onClick={() => navigate("/risk")}
                title="The items you track on this model, under Risk">
          Track items{nItems > 0 ? ` (${nItems})` : ""}
        </button>
      )}
      actions={model && (
        <ShareButton collection="degradation_models" artifactId={model.id} name={model.name} readOnly={model.read_only} />
      )}
      menu={model && (
        <>
          {!model.read_only && <button className="ovm-item" onClick={onRename}>Rename</button>}
          <button className="ovm-item danger" onClick={onDelete}>
            {model.read_only ? "Remove from my view" : "Delete"}
          </button>
        </>
      )}
      notice={error && <div className="card error mf-notice" role="alert">{error}</div>}
    >
      {model ? (
        <DegradationResultView results={model.results} modelId={model.id || id} name={model.name}
                               datasetId={model.dataset_id} tab={tab} onTab={(t) => setTab(t, "paths")} />
      ) : !error && <div className="mf-body mf-single"><p className="muted-line">Loading…</p></div>}
    </ModelFrame>
  );
}
