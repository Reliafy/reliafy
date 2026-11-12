import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import ErrorBoundary from "../components/ErrorBoundary.jsx";
import ModelNotFound, { ModelDrawFailed } from "../components/ModelNotFound.jsx";
import RecurrentResultView from "../components/RecurrentResultView.jsx";
import { ShareButton } from "../components/ShareDialog.jsx";
import { getRecurrentModel, deleteRecurrentModel, downloadModelPython, renameRecurrentModel } from "../api.js";
import { relativeTime } from "../instrument.js";
import Chip from "../components/ui/Chip.jsx";
import ModelFrame from "../components/model/ModelFrame.jsx";
import DownloadPythonItem from "../components/model/DownloadPythonItem.jsx";
import useTabParam from "../components/model/useTabParam.js";
import { itemName } from "../components/LibRows.jsx";
import { useAskText, useConfirm } from "../components/ConfirmProvider.jsx";
import { changedText, deleteOrRemoveConfirm, renamePrompt } from "../confirm.js";
import { recurrentAnswer, recurrentTabs } from "../recurrentResults.js";
import { PageTitle } from "../components/usePageTitle.js";

// A saved repairable (recurrent-event) model in the model frame: the answer
// line, Share, the ⋯ menu (Download as Python, rename, delete) and the result's tabs, the open one in
// the address (?tab=).
export default function RecurrentModelPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [model, setModel] = useState(null);
  const [error, setError] = useState(null);
  // Not on this list (404): ModelNotFound looks in the others.
  const [missing, setMissing] = useState(false);
  const [tab, setTab] = useTabParam();

  useEffect(() => {
    setModel(null);
    setError(null);
    setMissing(false);
    getRecurrentModel(id).then(setModel).catch((e) => (e.status === 404 ? setMissing(true) : setError(e.message)));
  }, [id]);

  const confirm = useConfirm();
  const askText = useAskText();
  const onRename = async () => {
    const name = changedText(await askText(renamePrompt({ kind: "model", name: model.name })), model.name);
    if (!name) return;
    try {
      const renamed = await renameRecurrentModel(id, name);
      setModel((m) => ({ ...m, name: renamed?.name || name }));
    } catch (e) { setError(e.message); }
  };
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
      crumbs={[{ label: "Models", to: "/models" }, { label: "Repairable", to: "/models/recurrent" }]}
      title={model ? itemName(model) : "Model"}
      badges={model?.is_sample && <Chip>Sample</Chip>}
      answer={model ? recurrentAnswer(r, { saved: `saved ${relativeTime(model.created_at)}` }) : null}
      id={model?.id}
      actions={model && (
        <ShareButton collection="recurrent_models" artifactId={model.id} name={model.name} readOnly={model.read_only} />
      )}
      menu={model && (
        <>
          <DownloadPythonItem download={() => downloadModelPython("recurrent", model.id)} onError={setError} />
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
          <RecurrentResultView results={r} name={model.name} modelId={model.id} paramsOnly={paramsOnly}
                               datasetId={model.dataset_id || null} tab={tab} onTab={(t) => setTab(t, first)} />
        </ErrorBoundary>
      ) : missing ? <ModelNotFound id={id} kind="recurrent" />
        : !error && <div className="mf-body mf-single"><p className="muted-line">Loading…</p></div>}
      <PageTitle name={model && itemName(model)} />
    </ModelFrame>
  );
}
