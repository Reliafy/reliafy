import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import DegradationResultView from "../components/DegradationResultView.jsx";
import { ShareButton } from "../components/ShareDialog.jsx";
import { getDegradationModel } from "../api.js";
import Chip from "../components/ui/Chip.jsx";
import PageHeader from "../components/ui/PageHeader.jsx";

// One saved degradation model: the fitted paths + life model. The fleet of
// tracked items lives under Fleet → Degradation tracking.
export default function DegradationModelPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [model, setModel] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    getDegradationModel(id)
      .then(setModel)
      .catch((e) => setError(e.message));
  }, [id]);

  if (error) {
    return (
      <div className="app">
        <header><h1>Degradation model</h1></header>
        <div className="card error">{error}</div>
      </div>
    );
  }
  if (!model) return <div className="app"><div className="card empty">Loading…</div></div>;

  const unit = model.results?.unit || "";
  const mUnit = model.results?.measurement_unit || "";
  const nItems = (model.items || []).length;

  return (
    <div className="app">
      <PageHeader
        crumbs={[{ label: "Modelling", to: "/modelling" }, { label: "Degradation", to: "/modelling/degradation" }]}
        title={model.name}
        badges={model.is_sample && <Chip>Sample</Chip>}
        meta={
          <>
            {model.path_model} degradation toward {model.threshold}
            {mUnit ? ` ${mUnit}` : ""} · {model.n_units} historical items
            {unit ? ` · time in ${unit}` : ""}
          </>
        }
        primary={
          <button onClick={() => navigate("/fleet/tracking")}>
            Track items{nItems > 0 ? ` (${nItems})` : ""}
          </button>
        }
        id={model.id || id}
        menu={
          <ShareButton
            collection="degradation_models"
            artifactId={model.id}
            name={model.name}
            readOnly={model.read_only}
            className="ovm-item"
          />
        }
      />

      <DegradationResultView results={model.results} modelId={model.id || id} name={model.name} />

      <p className="muted-line" style={{ marginTop: "1rem" }}>
        Monitor individual assets against this model under{" "}
        <Link to="/fleet/tracking" className="evidence-link">
          Fleet → Degradation tracking
        </Link>
        .
      </p>
    </div>
  );
}
