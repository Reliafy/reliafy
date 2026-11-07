import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import LoadFailed from "../components/LoadFailed.jsx";
import PageHeader from "../components/ui/PageHeader.jsx";
import Chip from "../components/ui/Chip.jsx";
import PredictionResult from "../components/PredictionResult.jsx";
import { itemName } from "../components/LibRows.jsx";
import { PageTitle } from "../components/usePageTitle.js";
import { useConfirm } from "../components/ConfirmProvider.jsx";
import { useAppConfig } from "../ConfigProvider.jsx";
import { deletePrediction, getPrediction } from "../api.js";
import { deleteOrRemoveConfirm } from "../confirm.js";
import { PREDICTIONS_LABEL, PREDICTIONS_PATH, newPredictionPath } from "../predictions.js";
import { productPath } from "../products.js";
import "./Predictions.css";

// A saved reliability prediction, read from its stored results (computed
// when it was saved; Edit computes them again).
export default function ReliabilityPredictionPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const confirm = useConfirm();
  const { maintenance } = useAppConfig();
  const [doc, setDoc] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    setDoc(null);
    getPrediction(id).then(setDoc).catch((e) => setError(e.message));
  }, [id]);

  const onDelete = async () => {
    if (!(await confirm(deleteOrRemoveConfirm(doc, "prediction", { name: itemName(doc) })))) return;
    try {
      await deletePrediction(doc.id);
      navigate(PREDICTIONS_PATH);
    } catch (e) {
      setError(e.message);
    }
  };

  if (error) {
    return (
      <div className="app">
        <PageHeader crumbs={[{ label: PREDICTIONS_LABEL, to: PREDICTIONS_PATH }]} title="Prediction" />
        <LoadFailed error={error} to={PREDICTIONS_PATH} label="See all predictions" notFound="Prediction not found." />
      </div>
    );
  }
  if (!doc) return <div className="app"><div className="card empty">Loading…</div></div>;

  const env = doc.results?.environment;
  const product = doc.inputs?.product;
  const counts = doc.results?.counts || {};
  return (
    <div className="app">
      <PageTitle name={itemName(doc)} />
      <PageHeader
        crumbs={[{ label: PREDICTIONS_LABEL, to: PREDICTIONS_PATH }]}
        title={itemName(doc)}
        badges={doc.is_sample ? <Chip>Sample</Chip> : null}
        meta={[
          env ? `${env.name} (${env.code})` : null,
          `${counts.lines ?? 0} ${counts.lines === 1 ? "line" : "lines"}`,
          "results as computed when it was saved",
        ].filter(Boolean).join(" · ")}
        id={doc.id}
        primary={<button onClick={() => navigate(newPredictionPath({ from: doc.id }))}>{doc.read_only ? "Edit a copy" : "Edit"}</button>}
        menu={
          <button type="button" className="ovm-item" onClick={onDelete}>
            {doc.read_only ? "Remove from my view" : "Delete"}
          </button>
        }
      >
        {product?.name && (
          <p className="hint">
            For the product <b>{product.name}</b>{product.rev ? `, rev ${product.rev}` : ""}{product.part_number ? ` (part ${product.part_number})` : ""}
            {product.id && maintenance ? <> · <Link to={productPath(product.id)}>open the product</Link></> : null}.
          </p>
        )}
        {doc.inputs?.notes && <p className="hint pred-notes">{doc.inputs.notes}</p>}
      </PageHeader>

      <div className="card">
        <PredictionResult results={doc.results} name={itemName(doc)} />
      </div>
    </div>
  );
}
