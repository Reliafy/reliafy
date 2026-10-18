import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import JointResultView from "../components/JointResultView.jsx";
import { ShareButton } from "../components/ShareDialog.jsx";
import { deleteJointModel, downloadJointPython, getJointModel, updateJointModel } from "../api.js";
import { relativeTime } from "../instrument.js";
import Chip from "../components/ui/Chip.jsx";
import PageHeader from "../components/ui/PageHeader.jsx";
import { itemName } from "../components/LibRows.jsx";
import { useConfirm } from "../components/ConfirmProvider.jsx";
import { deleteOrRemoveConfirm } from "../confirm.js";

// A saved condition monitoring model: the result view, Download as Python,
// rename, share and delete.
export default function JointModelPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [model, setModel] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    setModel(null);
    getJointModel(id).then(setModel).catch((e) => setError(e.message));
  }, [id]);

  const confirm = useConfirm();
  const onDelete = async () => {
    if (!(await confirm(deleteOrRemoveConfirm(model, "model", { name: itemName(model) })))) return;
    try {
      await deleteJointModel(id);
      navigate("/modelling/joint");
    } catch (e) { setError(e.message); }
  };

  const onRename = async () => {
    const name = window.prompt("Rename the model", model.name);
    if (!name || !name.trim() || name.trim() === model.name) return;
    try { setModel(await updateJointModel(id, { name: name.trim() })); } catch (e) { setError(e.message); }
  };

  const onPython = async () => {
    try { await downloadJointPython(id); } catch (e) { setError(e.message); }
  };

  const r = model?.results || {};
  return (
    <div className="app model-page">
      <PageHeader
        crumbs={[{ label: "Modelling", to: "/modelling" }, { label: "Condition monitoring", to: "/modelling/joint" }]}
        title={model ? itemName(model) : "Model"}
        badges={model?.is_sample && <Chip>Sample</Chip>}
        meta={model && <>Saved {relativeTime(model.created_at)}{r.unit ? ` · ${r.unit}` : ""} · condition monitoring</>}
        id={model?.id}
        actions={model && (
          <button type="button" className="secondary" onClick={onPython}
                  title="A script that refits this model with SurPyval from the data it was fitted to">
            Download as Python
          </button>
        )}
        menu={model && (
          <>
            {!model.read_only && <button className="ovm-item" onClick={onRename}>Rename</button>}
            <ShareButton collection="models" artifactId={model.id} name={model.name}
                         readOnly={model.read_only} className="ovm-item" />
            <button className="ovm-item danger" onClick={onDelete}>
              {model.read_only ? "Remove from my view" : "Delete"}
            </button>
          </>
        )}
      />
      {error && <div className="card error" role="alert">{error}</div>}
      {model && <JointResultView results={model.results} modelId={model.id} name={model.name} />}
    </div>
  );
}
