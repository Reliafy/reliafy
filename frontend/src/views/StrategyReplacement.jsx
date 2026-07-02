import OptimalReplacement from "../components/OptimalReplacement.jsx";

// Strategy › Optimal replacement.
export default function StrategyReplacement() {
  return (
    <div className="app">
      <header>
        <div>
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
