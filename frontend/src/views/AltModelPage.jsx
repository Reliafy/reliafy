import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import AltResultView from "../components/AltResultView.jsx";
import { ShareButton } from "../components/ShareDialog.jsx";
import { getAltModel, deleteAltModel, renameAltModel } from "../api.js";
import { relativeTime } from "../instrument.js";
import Chip from "../components/ui/Chip.jsx";
import ModelFrame from "../components/model/ModelFrame.jsx";
import useTabParam from "../components/model/useTabParam.js";
import { altAnswerParts } from "../altFrame.js";
import { itemName } from "../components/LibRows.jsx";
import { altPlanLink, altPrefill } from "../testPlanning.js";
import { useAskText, useConfirm } from "../components/ConfirmProvider.jsx";
import { changedText, deleteOrRemoveConfirm, renamePrompt } from "../confirm.js";

// A saved accelerated life model in the model frame: the answer line, the
// result's tabs (Life-stress, Probability plot, Calculator, Diagnostics,
// Data), Share, and the ⋯ menu (plan the next test, rename, delete).
export default function AltModelPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [model, setModel] = useState(null);
  const [error, setError] = useState(null);
  const [tab, setTab] = useTabParam();

  useEffect(() => {
    setModel(null);
    getAltModel(id).then(setModel).catch((e) => setError(e.message));
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
      crumbs={[{ label: "Model", to: "/models" }, { label: "Accelerated life", to: "/models/alt" }]}
      title={model ? itemName(model) : "Model"}
      badges={model?.is_sample && <Chip>Sample</Chip>}
      answer={model ? altAnswerParts(r, { saved: `saved ${relativeTime(model.created_at)}` }) : null}
      id={model?.id}
      actions={model && (
        <ShareButton collection="alt_models" artifactId={model.id} name={model.name} readOnly={model.read_only} />
      )}
      menu={model && (
        <>
          {altPrefill(r) && (
            <Link className="ovm-item" to={altPlanLink(model.id)}
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
        <AltResultView results={model.results} modelId={model.id} name={model.name} datasetId={model.dataset_id}
                       tab={tab} onTab={(t) => setTab(t, "life")} />
      ) : !error && <div className="mf-body mf-single"><p className="muted-line">Loading…</p></div>}
    </ModelFrame>
  );
}
