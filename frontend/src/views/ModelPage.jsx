import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import ErrorBoundary from "../components/ErrorBoundary.jsx";
import ModelNotFound, { ModelDrawFailed } from "../components/ModelNotFound.jsx";
import ResultView from "../components/ResultView.jsx";
import EditFitModal from "../components/EditFitModal.jsx";
import { ShareButton } from "../components/ShareDialog.jsx";
import { compareModel, getModel, deleteModel } from "../api.js";
import { relativeTime } from "../instrument.js";
import Chip from "../components/ui/Chip.jsx";
import ModelFrame from "../components/model/ModelFrame.jsx";
import useTabParam from "../components/model/useTabParam.js";
import { itemName } from "../components/LibRows.jsx";
import ModelNextSteps from "../components/ModelNextSteps.jsx";
import { rememberModel } from "../modelNext.js";
import { otherModelPage } from "../modelRoute.js";
import { answerParts, modelTabs } from "../modelFrame.js";
import { useConfirm } from "../components/ConfirmProvider.jsx";
import { deleteOrRemoveConfirm } from "../confirm.js";
import { PageTitle } from "../components/usePageTitle.js";

const CRUMBS = [{ label: "Models", to: "/models" }, { label: "Non-repairable", to: "/models/life" }];

// Reopen a saved model by id and render its cached results in the model
// frame: the header (its name, the answer line, Use this model, Share and the
// ⋯ menu), then its tabs.
export default function ModelPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [model, setModel] = useState(null);
  const [error, setError] = useState(null);
  // Not on this list (404): ModelNotFound looks in the others.
  const [missing, setMissing] = useState(false);
  const [editing, setEditing] = useState(false);
  const [tab, setTab] = useTabParam();

  useEffect(() => {
    setModel(null);
    setError(null);
    setMissing(false);
    getModel(id)
      .then((m) => {
        // A condition and life model is stored with these: open its own page.
        const page = otherModelPage(m);
        if (page) return navigate(page.to, { replace: true });
        setModel(m);
        // The Strategy tools start on the model used last (#294).
        rememberModel(m.id);
      })
      .catch((err) => (err.status === 404 ? setMissing(true) : setError(err.message)));
  }, [id, navigate]);

  const confirm = useConfirm();
  const onDelete = async () => {
    if (!(await confirm(deleteOrRemoveConfirm(model, "model", { name: itemName(model) })))) return;
    await deleteModel(id);
    navigate("/models/life");
  };

  // A competing-risks fit (#177) is refitted from the wizard, not edited here.
  const canEdit = model && !model.read_only && model.dataset_id && model.kind !== "competing_risks";
  const results = model?.results;
  const split = results?.split || null;
  const title = model ? itemName(model) : "Model";
  const badges = model?.is_sample && <Chip>Sample</Chip>;
  const editModal = editing && model && (
    <EditFitModal
      model={model}
      onClose={() => setEditing(false)}
      onUpdated={(updated) => {
        setModel(updated);
        setEditing(false);
      }}
    />
  );

  const tabs = results ? modelTabs(results) || [] : [];
  return (
    <ModelFrame
      className="model-page"
      crumbs={CRUMBS}
      title={title}
      badges={badges}
      answer={results ? answerParts(results, { split, saved: `saved ${relativeTime(model.created_at)}` }) : null}
      primary={model && <ModelNextSteps result={results} modelId={model.id} variant="primary" />}
      actions={model && (
        <ShareButton collection="models" artifactId={model.id} name={model.name} readOnly={model.read_only} />
      )}
      id={model?.id}
      menu={model && (
        <>
          {canEdit && <button className="ovm-item" onClick={() => setEditing(true)}>Edit fit</button>}
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
          <ResultView
            result={results}
            modelId={model.id}
            name={model.name}
            split={split}
            datasetId={model.dataset_id || null}
            compare={["distribution", "flexible"].includes(model.kind) && model.dataset_id ? () => compareModel(model.id) : null}
            tab={tab}
            onTab={(t) => setTab(t, tabs[0]?.id)}
          />
        </ErrorBoundary>
      ) : missing ? <ModelNotFound id={id} kind="life" />
        : !error && <div className="mf-body mf-single"><p className="muted-line">Loading…</p></div>}
      {editModal}
      <PageTitle name={model && itemName(model)} />
    </ModelFrame>
  );
}
