import { useNavigate } from "react-router-dom";
import DemonstrationTest from "../components/DemonstrationTest.jsx";

export default function StrategyDemonstration() {
  const navigate = useNavigate();
  return (
    <div className="app">
      <header>
        <div>
          <div className="crumb">
            <button className="crumb-link" onClick={() => navigate("/strategy")}>Strategy</button> / <b>Demonstration test</b>
          </div>
          <h1>Demonstration test</h1>
          <p>
            Plan a reliability demonstration test: how many units to test, for
            how long, and how many failures to allow, to show a reliability
            target at a confidence level.
          </p>
        </div>
      </header>
      <div className="card">
        <DemonstrationTest />
      </div>
    </div>
  );
}
