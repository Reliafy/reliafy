import { useNavigate } from "react-router-dom";
import ModelComparison from "../components/ModelComparison.jsx";

// Modelling › Model comparison: fit every distribution to a dataset and rank
// them against the non-parametric estimate to choose the best life model.
export default function ModellingCompare() {
  const navigate = useNavigate();
  return (
    <div className="app">
      <header>
        <div>
          <button className="back-link" onClick={() => navigate("/modelling")}>
            ← Modelling
          </button>
          <h1>Model comparison</h1>
          <p>
            Fit every parametric distribution to a dataset, overlay them on the
            non-parametric (Kaplan–Meier) estimate, and rank by AIC to choose
            the best-fitting life model.
          </p>
        </div>
      </header>
      <div className="card">
        <ModelComparison />
      </div>
    </div>
  );
}
