import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import DegradationResultView from "../components/DegradationResultView.jsx";
import { ShareButton } from "../components/ShareDialog.jsx";
import { getDegradationModel } from "../api.js";

// One saved degradation model: the fitted paths + life model. The fleet of
// tracked items lives under Strategy → Degradation tracking.
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
      <header>
        <div>
          <div className="crumb">
            <button className="crumb-link" onClick={() => navigate("/modelling")}>Modelling</button> /{" "}
            <button className="crumb-link" onClick={() => navigate("/modelling/degradation")}>Degradation</button> /{" "}
            <b>{model.name}</b>
          </div>
          <h1>
            {model.name}
            {model.is_sample && <span className="sample-tag" style={{ verticalAlign: "middle" }}>Sample</span>}
          </h1>
          <p>
            {model.path_model} degradation toward {model.threshold}
            {mUnit ? ` ${mUnit}` : ""} · {model.n_units} historical items
            {unit ? ` · time in ${unit}` : ""}
          </p>
        </div>
        <div className="head-actions">
          <ShareButton
            collection="degradation_models"
            artifactId={model.id}
            name={model.name}
            readOnly={model.read_only}
          />
          <button onClick={() => navigate(`/strategy/tracking/${model.id}`)}>
            Track items{nItems > 0 ? ` (${nItems})` : ""}
          </button>
        </div>
      </header>

      <DegradationResultView results={model.results} />

      <p className="muted-line" style={{ marginTop: "1rem" }}>
        Monitor individual assets against this model under{" "}
        <Link to={`/strategy/tracking/${model.id}`} className="evidence-link">
          Strategy → Degradation tracking
        </Link>
        .
      </p>
    </div>
  );
}
