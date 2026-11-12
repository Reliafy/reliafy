import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import ErrorBoundary from "../components/ErrorBoundary.jsx";
import ModelNotFound, { ModelDrawFailed } from "../components/ModelNotFound.jsx";
import AltResultView from "../components/AltResultView.jsx";
import { ShareButton } from "../components/ShareDialog.jsx";
import { getAltModel, deleteAltModel, downloadModelPython, renameAltModel } from "../api.js";
import { relativeTime } from "../instrument.js";
import Chip from "../components/ui/Chip.jsx";
import ModelFrame from "../components/model/ModelFrame.jsx";
import DownloadPythonItem from "../components/model/DownloadPythonItem.jsx";
import useTabParam from "../components/model/useTabParam.js";
import { altAnswerParts } from "../altFrame.js";
import { itemName } from "../components/LibRows.jsx";
import { altPlanLink, altPrefill } from "../testPlanning.js";
import { useAskText, useConfirm } from "../components/ConfirmProvider.jsx";
import { changedText, deleteOrRemoveConfirm, renamePrompt } from "../confirm.js";
import { PageTitle } from "../components/usePageTitle.js";

// A saved accelerated life model in the model frame: the answer line, the
// result's tabs (Life-stress, Probability plot, Calculator, Diagnostics,
// Data), Share, and the ⋯ menu (Download as Python, plan the next test, rename, delete).
export default function AltModelPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [model, setModel] = useState(null);
  const [error, setError] = useState(null);
  // Not on this list (404): ModelNotFound looks in the others.
  const [missing, setMissing] = useState(false);
  const [tab, setTab] = useTabParam();
  // The use stress entered on the page (the model's units), for "Plan the next test".
  const [useStress, setUseStress] = useState(null);

  useEffect(() => {
    setModel(null);
    setMissing(false);
    getAltModel(id).then(setModel).catch((e) => (e.status === 404 ? setMissing(true) : setError(e.message)));
  }, [id]);

  const confirm = useConfirm();
  const askText = useAskText();
  const onDelete = async () => {
    if (!(await confirm(deleteOrRemoveConfirm(model, "model", { name: itemName(model) })))) return;
    try {
      await deleteAltModel(id);
      navigate("/models/alt");
    } catch (e) { setError(e.message); }
  };
  const onRename = async () => {
    const name = changedText(await askText(renamePrompt({ kind: "model", name: model.name })), model.name);
    if (!name) return;
    try {
      const saved = await renameAltModel(id, name);
      setModel((m) => ({ ...m, ...saved, results: m.results }));
    } catch (e) { setError(e.message); }
  };

  const r = model?.results || {};
  return (
    <ModelFrame
      className="model-page"
      crumbs={[{ label: "Models", to: "/models" }, { label: "Accelerated life", to: "/models/alt" }]}
      title={model ? itemName(model) : "Model"}
      badges={model?.is_sample && <Chip>Sample</Chip>}
      answer={model ? altAnswerParts(r, { saved: `saved ${relativeTime(model.created_at)}` }) : null}
      id={model?.id}
      actions={model && (
        <ShareButton collection="alt_models" artifactId={model.id} name={model.name} readOnly={model.read_only} />
      )}
      menu={model && (
        <>
          <DownloadPythonItem download={() => downloadModelPython("alt", model.id)} onError={setError} />
          {altPrefill(r) && (
            <Link className="ovm-item" to={altPlanLink(model.id, useStress)}
                  title="The stresses, the units at each and the failures to expect, from this fit">
              Plan the next test
            </Link>
          )}
          {!model.read_only && <button type="button" className="ovm-item" onClick={onRename}>Rename</button>}
          <button type="button" className="ovm-item danger" onClick={onDelete}>
            {model.read_only ? "Remove from my view" : "Delete"}
          </button>
        </>
      )}
      notice={error && <div className="card error mf-notice" role="alert">{error}</div>}
    >
      {model ? (
        // A model this page can't draw shows a card here, not the whole-app error page.
        <ErrorBoundary key={model.id} fallback={<ModelDrawFailed />}>
          <AltResultView results={model.results} modelId={model.id} name={model.name} datasetId={model.dataset_id}
                         tab={tab} onTab={(t) => setTab(t, "life")} onUseStress={setUseStress} />
        </ErrorBoundary>
      ) : missing ? <ModelNotFound id={id} kind="alt" />
        : !error && <div className="mf-body mf-single"><p className="muted-line">Loading…</p></div>}
      <PageTitle name={model && itemName(model)} />
    </ModelFrame>
  );
}
