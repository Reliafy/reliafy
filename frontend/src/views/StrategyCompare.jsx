import CompareTwoModels from "../components/CompareTwoModels.jsx";

// Strategy › Compare two models: which item is more reliable?
export default function StrategyCompare() {
  return (
    <div className="app">
      <header>
        <div>
          <h1>Compare two models</h1>
          <p>
            Put two items head-to-head — a fitted distribution or raw
            (non-parametric) data on each side — to see which is more reliable.
          </p>
        </div>
      </header>
      <div className="card">
        <CompareTwoModels />
      </div>
    </div>
  );
}
