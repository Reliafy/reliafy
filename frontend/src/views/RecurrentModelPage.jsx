import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import RecurrentResultView from "../components/RecurrentResultView.jsx";
import { ShareButton } from "../components/ShareDialog.jsx";
import { getRecurrentModel, deleteRecurrentModel } from "../api.js";
import { relativeTime } from "../instrument.js";
import Chip from "../components/ui/Chip.jsx";
import ModelFrame from "../components/model/ModelFrame.jsx";
import useTabParam from "../components/model/useTabParam.js";
import { itemName } from "../components/LibRows.jsx";
import { useConfirm } from "../components/ConfirmProvider.jsx";
import { deleteOrRemoveConfirm } from "../confirm.js";
import { recurrentAnswer, recurrentTabs } from "../recurrentResults.js";

// A saved repairable (recurrent-event) model in the model frame: the answer
// line, Share, the ⋯ menu (delete) and the result's tabs, the open one in
// the address (?tab=).
export default function RecurrentModelPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [model, setModel] = useState(null);
  const [error, setError] = useState(null);
  const [tab, setTab] = useTabParam();

  useEffect(() => {
    setModel(null);
    setError(null);
    getRecurrentModel(id).then(setModel).catch((e) => setError(e.message));
  }, [id]);

  const confirm = useConfirm();
  const onDelete = async () => {
    if (!(await confirm(deleteOrRemoveConfirm(model, "model", { name: itemName(model) })))) return;
    try {
      await deleteRecurrentModel(id);
      navigate("/models/recurrent");
    } catch (e) { setError(e.message); }
  };

  const r = model?.results || {};
  const paramsOnly = !!model?.spec?.params_only;
  const first = model ? recurrentTabs(r, { modelId: model.id, paramsOnly })[0]?.id : null;
  return (
    <ModelFrame
      className="model-page"
      crumbs={[{ label: "Model", to: "/models" }, { label: "Repairable", to: "/models/recurrent" }]}
      title={model ? itemName(model) : "Model"}
      badges={model?.is_sample && <Chip>Sample</Chip>}
      answer={model ? recurrentAnswer(r, { saved: `saved ${relativeTime(model.created_at)}` }) : null}
      id={model?.id}
      actions={model && (
        <ShareButton collection="recurrent_models" artifactId={model.id} name={model.name} readOnly={model.read_only} />
      )}
      menu={model && (
        <button className="ovm-item danger" onClick={onDelete}>
          {model.read_only ? "Remove from my view" : "Delete"}
        </button>
      )}
      notice={error && <div className="card error mf-notice" role="alert">{error}</div>}
    >
      {model ? (
        <RecurrentResultView results={r} name={model.name} modelId={model.id} paramsOnly={paramsOnly}
                             datasetId={model.dataset_id || null} tab={tab} onTab={(t) => setTab(t, first)} />
      ) : !error && <div className="mf-body mf-single"><p className="muted-line">Loading…</p></div>}
    </ModelFrame>
  );
}
