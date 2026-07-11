import { useNavigate } from "react-router-dom";
import FailureFinding from "../components/FailureFinding.jsx";

export default function StrategyFailureFinding() {
  const navigate = useNavigate();
  return (
    <div className="app">
      <header>
        <div>
          <div className="crumb">
            <button className="crumb-link" onClick={() => navigate("/strategy")}>Strategy</button> / <b>Failure finding</b>
          </div>
          <h1>Failure-finding interval</h1>
          <p>
            How often to check a hidden function — a protective device whose
            failure only shows when it's demanded — to keep its availability
            above target.
          </p>
        </div>
      </header>
      <div className="card">
        <FailureFinding />
      </div>
    </div>
  );
}
