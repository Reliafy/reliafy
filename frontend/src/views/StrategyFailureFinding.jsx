import PageHeader from "../components/ui/PageHeader.jsx";
import Card from "../components/ui/Card.jsx";
import FailureFinding from "../components/FailureFinding.jsx";

// Strategy › Failure finding.
export default function StrategyFailureFinding() {
  return (
    <div className="app">
      <PageHeader
        crumbs={[{ label: "Strategy", to: "/strategy" }]}
        title="Failure-finding interval"
        meta="How often to check a hidden function — a protective device whose failure only shows when it's demanded — to keep its availability above target."
      />
      <Card>
        <FailureFinding />
      </Card>
    </div>
  );
}
