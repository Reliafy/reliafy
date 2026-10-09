import PageHeader from "../components/ui/PageHeader.jsx";
import Card from "../components/ui/Card.jsx";
import CompareTwoModels from "../components/CompareTwoModels.jsx";

// Strategy › Compare two models: which item is more reliable?
export default function StrategyCompare() {
  return (
    <div className="app">
      <PageHeader
        crumbs={[{ label: "Strategy", to: "/strategy" }]}
        title="Compare two models"
        meta="Put two items head-to-head — a fitted distribution or raw (non-parametric) data on each side — to see which is more reliable."
      />
      <Card>
        <CompareTwoModels />
      </Card>
    </div>
  );
}
