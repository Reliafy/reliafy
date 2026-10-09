import PageHeader from "../components/ui/PageHeader.jsx";
import Card from "../components/ui/Card.jsx";
import OptimalReplacement from "../components/OptimalReplacement.jsx";

// Strategy › Optimal replacement.
export default function StrategyReplacement() {
  return (
    <div className="app">
      <PageHeader
        crumbs={[{ label: "Strategy", to: "/strategy" }]}
        title="Optimal replacement"
        meta="The age-based preventive-replacement interval that minimises the long-run cost rate, versus running to failure."
      />
      <Card>
        <OptimalReplacement />
      </Card>
    </div>
  );
}
