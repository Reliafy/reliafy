import { useNavigate } from "react-router-dom";
import OptimalReplacement from "../components/OptimalReplacement.jsx";

// Strategy › Optimal replacement.
export default function StrategyReplacement() {
  const navigate = useNavigate();
  return (
    <div className="app">
      <header>
        <div>
          <div className="crumb">
            <button className="crumb-link" onClick={() => navigate("/strategy")}>Strategy</button> / <b>Optimal replacement</b>
          </div>
          <h1>Optimal replacement</h1>
          <p>
            The age-based preventive-replacement interval that minimises the
            long-run cost rate, versus running to failure.
          </p>
        </div>
      </header>
      <div className="card">
        <OptimalReplacement />
      </div>
    </div>
  );
}
