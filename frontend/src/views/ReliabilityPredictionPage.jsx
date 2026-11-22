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
import { createModelFromParams, deletePrediction, getPrediction, listModels } from "../api.js";
import { deleteOrRemoveConfirm } from "../confirm.js";
import { PREDICTIONS_LABEL, PREDICTIONS_PATH, newPredictionPath, predictionAsModel } from "../predictions.js";
import { productPath } from "../products.js";
import { tabPlace } from "../explorerTabs.js";
import "./Predictions.css";
import Loading from "../components/ui/Loading.jsx";

// A saved reliability prediction, read from its stored results (computed
// when it was saved; Edit computes them again).
export default function ReliabilityPredictionPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const confirm = useConfirm();
  const { maintenance } = useAppConfig();
  const [doc, setDoc] = useState(null);
  const [error, setError] = useState(null);

  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    setDoc(null);
    setError(null);
    getPrediction(id).then(setDoc).catch((e) => setError(e.message));
  }, [id, attempt]);

  // Spares from this rate: the rate as a constant-rate model (the one made
  // before, if there is one), then a new fleet forecast on it, where the
  // fleet, its hours and the lead time give how many to hold.
  const [sizing, setSizing] = useState(false);
  const [sizeError, setSizeError] = useState(null);
  const onSpares = async () => {
    const spec = predictionAsModel(doc);
    if (!spec) return;
    setSizing(true);
    setSizeError(null);
    try {
      const have = ((await listModels())?.models || []).find((x) => x.name === spec.name && String(x.distribution).toLowerCase() === "exponential" && !x.read_only);
      const model = have || await createModelFromParams(spec.name, spec.distribution, spec.params, { unit: spec.unit });
      navigate(`/forecasts?new=1&model=${encodeURIComponent(model.id)}`);
    } catch (e) {
      setSizeError(e.message);
      setSizing(false);
    }
  };

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
        <LoadFailed onRetry={() => setAttempt((n) => n + 1)} error={error} to={PREDICTIONS_PATH} label="See all predictions" notFound="Prediction not found." />
      </div>
    );
  }
  if (!doc) return <div className="app"><Loading card /></div>;

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
        {doc.inputs?.position?.id && maintenance && (
          <p className="hint">
            The parts count of <b>{doc.inputs.position.name}</b>, made on its {tabPlace("models")} ·{" "}
            <Link to={`/asset-register/explorer?arrange=positions&sel=${encodeURIComponent(doc.inputs.position.id)}&tab=models`}>Open on the asset</Link>.
          </p>
        )}
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
        {predictionAsModel(doc) && (
          <div className="row" style={{ gap: "0.8rem", alignItems: "center", flexWrap: "wrap" }} data-testid="prediction-spares">
            <button className="secondary" onClick={onSpares} disabled={sizing}>
              {sizing ? "Opening…" : "Forecast spares from this rate"}
            </button>
            <span className="muted-line" style={{ margin: 0, flex: "1 1 260px" }}>
              Uses the rate as a constant failure rate (a model named “{predictionAsModel(doc).name}”), then asks for the
              fleet, its hours and the lead time: the forecast gives the failures a year and how many to hold.
            </span>
          </div>
        )}
        {sizeError && <p className="hint fleet-alert-warn" role="alert">{sizeError}</p>}
      </div>
    </div>
  );
}
