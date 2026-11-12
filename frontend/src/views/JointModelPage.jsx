import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import ErrorBoundary from "../components/ErrorBoundary.jsx";
import ModelNotFound, { ModelDrawFailed } from "../components/ModelNotFound.jsx";
import JointResultView from "../components/JointResultView.jsx";
import { ShareButton } from "../components/ShareDialog.jsx";
import { deleteJointModel, downloadJointPython, getJointModel, listPositionModels, updateJointModel } from "../api.js";
import { usedOnPositions } from "../joint.js";
import { relativeTime } from "../instrument.js";
import Chip from "../components/ui/Chip.jsx";
import ModelFrame from "../components/model/ModelFrame.jsx";
import DownloadPythonItem from "../components/model/DownloadPythonItem.jsx";
import useTabParam from "../components/model/useTabParam.js";
import { answerParts } from "../modelFrame.js";
import { itemName } from "../components/LibRows.jsx";
import { useAskText, useConfirm } from "../components/ConfirmProvider.jsx";
import { changedText, deleteOrRemoveConfirm, renamePrompt } from "../confirm.js";
import { PageTitle } from "../components/usePageTitle.js";
import { useRoles } from "../RolesProvider.jsx";

// A saved condition and life model in the model frame: the answer line, the
// result's tabs, Share, and the ⋯ menu (Download as Python, rename, delete).
export default function JointModelPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [model, setModel] = useState(null);
  const [error, setError] = useState(null);
  // Not on this list (404): ModelNotFound looks in the others.
  const [missing, setMissing] = useState(false);
  const [tab, setTab] = useTabParam();
  // Risk now (the model's own running units) is always here. Where the account has the asset
  // tree and a position uses this model, a line also links to the Explorer's class fleet.
  const { has } = useRoles();
  const [onPositions, setOnPositions] = useState(false);
  useEffect(() => {
    setOnPositions(false);
    if (!has.maintenance) return undefined;
    let live = true;
    listPositionModels().then((r) => live && setOnPositions(usedOnPositions(r?.links, id))).catch(() => {});
    return () => { live = false; };
  }, [id, has.maintenance]);

  useEffect(() => {
    setModel(null);
    setMissing(false);
    getJointModel(id).then(setModel).catch((e) => (e.status === 404 ? setMissing(true) : setError(e.message)));
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

  const r = model?.results || {};
  return (
    <ModelFrame
      className="model-page"
      crumbs={[{ label: "Models", to: "/models" }, { label: "Condition and life", to: "/models/joint" }]}
      title={model ? itemName(model) : "Model"}
      badges={model?.is_sample && <Chip>Sample</Chip>}
      answer={model ? answerParts({ ...r, kind: "joint" }, { saved: `saved ${relativeTime(model.created_at)}` }) : null}
      id={model?.id}
      actions={model && (
        <ShareButton collection="models" artifactId={model.id} name={model.name} readOnly={model.read_only} />
      )}
      menu={model && (
        <>
          <DownloadPythonItem download={() => downloadJointPython(id)} onError={setError} />
          {!model.read_only && <button className="ovm-item" onClick={onRename}>Rename</button>}
          <button className="ovm-item danger" onClick={onDelete}>
            {model.read_only ? "Remove from my view" : "Delete"}
          </button>
        </>
      )}
      notice={error && <div className="card error mf-notice" role="alert">{error}</div>}
    >
      {model ? (
        // A model this page can't draw shows a card here, not the whole-app error page.
        <ErrorBoundary key={model.id} fallback={<ModelDrawFailed />}>
          <JointResultView results={model.results} modelId={model.id} name={model.name}
                           tab={tab} onTab={(t) => setTab(t, "risk")} onPositions={onPositions} />
        </ErrorBoundary>
      ) : missing ? <ModelNotFound id={id} kind="joint" />
        : !error && <div className="mf-body mf-single"><p className="muted-line">Loading…</p></div>}
      <PageTitle name={model && itemName(model)} />
    </ModelFrame>
  );
}
