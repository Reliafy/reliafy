import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import LoadFailed from "../components/LoadFailed.jsx";
import MaintainabilityResult from "../components/MaintainabilityResult.jsx";
import Chip from "../components/ui/Chip.jsx";
import PageHeader from "../components/ui/PageHeader.jsx";
import { itemName } from "../components/LibRows.jsx";
import { PageTitle } from "../components/usePageTitle.js";
import { useAskText, useConfirm } from "../components/ConfirmProvider.jsx";
import { changedText, deleteOrRemoveConfirm, renamePrompt } from "../confirm.js";
import {
  deleteMaintainabilityPrediction, getMaintainabilityPrediction, renameMaintainabilityPrediction,
} from "../api.js";
import { MAINTAINABILITY_PATH } from "../maintainability.js";
import "./Maintainability.css";

// A saved maintainability prediction, read-only from its stored results.
// "Edit a copy" opens the calculator with its lines, to change and save anew.
export default function MaintainabilityPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [doc, setDoc] = useState(null);
  const [error, setError] = useState(null);
  const confirm = useConfirm();
  const askText = useAskText();

  useEffect(() => {
    setDoc(null);
    getMaintainabilityPrediction(id).then(setDoc).catch((e) => setError(e.message));
  }, [id]);

  if (error) {
    return (
      <div className="app">
        <PageHeader crumbs={[{ label: "Maintainability prediction", to: MAINTAINABILITY_PATH }]} title="Prediction" />
        <LoadFailed error={error} to={MAINTAINABILITY_PATH} label="See all predictions" notFound="Prediction not found." />
      </div>
    );
  }
  if (!doc) return <div className="app"><div className="card empty">Loading…</div></div>;

  const onRename = async () => {
    const name = changedText(await askText(renamePrompt({ kind: "prediction", name: doc.name })), doc.name);
    if (!name) return;
    try {
      const updated = await renameMaintainabilityPrediction(id, name);
      setDoc((d) => ({ ...d, name: updated.name }));
    } catch (e) {
      setError(e.message);
    }
  };
  const onDelete = async () => {
    if (!(await confirm(deleteOrRemoveConfirm(doc, "prediction", { name: itemName(doc) })))) return;
    try {
      await deleteMaintainabilityPrediction(id);
      navigate(MAINTAINABILITY_PATH);
    } catch (e) {
      setError(e.message);
    }
  };
  const editCopy = () => navigate(`${MAINTAINABILITY_PATH}/new`, { state: { inputs: doc.inputs, name: `${doc.name} (copy)` } });

  const r = doc.results || {};
  const meta = [
    r.product?.name ? `Product: ${r.product.name}` : null,
    `${r.counts?.lines ?? "?"} ${r.counts?.lines === 1 ? "line" : "lines"}`,
    `times in ${r.unit || "hours"}`,
    r.weights?.parts_count?.taken && !r.weights?.as_saved
      ? "failure rates follow the parts count" : "results as computed when it was saved",
  ].filter(Boolean).join(" · ");

  return (
    <div className="app">
      <PageTitle name={itemName(doc)} />
      <PageHeader
        crumbs={[{ label: "Maintainability prediction", to: MAINTAINABILITY_PATH }]}
        title={itemName(doc)}
        badges={
          <>
            {doc.is_sample && <Chip>Sample</Chip>}
            {doc.shared_by && <Chip title={`Shared by ${doc.shared_by}`}>Shared</Chip>}
          </>
        }
        meta={meta}
        id={doc.id}
        primary={<button onClick={editCopy}>Edit a copy</button>}
        menu={
          <>
            {!doc.read_only && <button type="button" className="ovm-item" onClick={onRename}>Rename</button>}
            <button type="button" className="ovm-item danger" onClick={onDelete}>
              {doc.read_only ? "Remove from my list" : "Delete"}
            </button>
          </>
        }
      />
      <div className="card">
        <MaintainabilityResult result={doc.results} />
      </div>
    </div>
  );
}
