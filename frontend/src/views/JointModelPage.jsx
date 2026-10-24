import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import JointResultView from "../components/JointResultView.jsx";
import { ShareButton } from "../components/ShareDialog.jsx";
import { deleteJointModel, downloadJointPython, getJointModel, updateJointModel } from "../api.js";
import { relativeTime } from "../instrument.js";
import Chip from "../components/ui/Chip.jsx";
import ModelFrame from "../components/model/ModelFrame.jsx";
import useTabParam from "../components/model/useTabParam.js";
import { answerParts } from "../modelFrame.js";
import { itemName } from "../components/LibRows.jsx";
import { useAskText, useConfirm } from "../components/ConfirmProvider.jsx";
import { changedText, deleteOrRemoveConfirm, renamePrompt } from "../confirm.js";

// A saved condition and life model in the model frame: the answer line, the
// result's tabs, Share, and the ⋯ menu (Download as Python, rename, delete).
export default function JointModelPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [model, setModel] = useState(null);
  const [error, setError] = useState(null);
  const [tab, setTab] = useTabParam();

  useEffect(() => {
    setModel(null);
    getJointModel(id).then(setModel).catch((e) => setError(e.message));
  }, [id]);

  const confirm = useConfirm();
  const askText = useAskText();
  const onDelete = async () => {
    if (!(await confirm(deleteOrRemoveConfirm(model, "model", { name: itemName(model) })))) return;
    try {
      await deleteJointModel(id);
      navigate("/models/joint");
    } catch (e) { setError(e.message); }
  };

  const onRename = async () => {
    const name = changedText(await askText(renamePrompt({ kind: "model", name: model.name })), model.name);
    if (!name) return;
    try { setModel(await updateJointModel(id, { name })); } catch (e) { setError(e.message); }
  };

  const onPython = async () => {
    try { await downloadJointPython(id); } catch (e) { setError(e.message); }
  };

  const r = model?.results || {};
  return (
    <ModelFrame
      className="model-page"
      crumbs={[{ label: "Model", to: "/models" }, { label: "Condition and life", to: "/models/joint" }]}
      title={model ? itemName(model) : "Model"}
      badges={model?.is_sample && <Chip>Sample</Chip>}
      answer={model ? answerParts({ ...r, kind: "joint" }, { saved: `saved ${relativeTime(model.created_at)}` }) : null}
      id={model?.id}
      actions={model && (
        <ShareButton collection="models" artifactId={model.id} name={model.name} readOnly={model.read_only} />
      )}
      menu={model && (
        <>
          <button type="button" className="ovm-item" onClick={onPython}
                  title="A script that refits this model with SurPyval from the data it was fitted to">
            Download as Python
          </button>
          {!model.read_only && <button className="ovm-item" onClick={onRename}>Rename</button>}
          <button className="ovm-item danger" onClick={onDelete}>
            {model.read_only ? "Remove from my view" : "Delete"}
          </button>
        </>
      )}
      notice={error && <div className="card error mf-notice" role="alert">{error}</div>}
    >
      {model ? (
        <JointResultView results={model.results} modelId={model.id} name={model.name}
                         tab={tab} onTab={(t) => setTab(t, "risk")} />
      ) : !error && <div className="mf-body mf-single"><p className="muted-line">Loading…</p></div>}
    </ModelFrame>
  );
}
