import DashboardSection from "../components/DashboardSection.jsx";
import { CostIcon, CompareIcon, ListIcon, StrategyIcon } from "../components/icons.jsx";

export default function StrategyDashboard() {
  // The strategy tools work on data you provide; saved analyses persist their
  // outputs so RCM decisions can cite them as evidence.
  const cards = [
    {
      to: "/strategy/replacement",
      icon: <CostIcon />,
      title: "Optimal replacement",
      body: "Find the cost-optimal preventive-replacement interval for a fitted distribution.",
      cta: "Open",
    },
    {
      to: "/strategy/compare",
      icon: <CompareIcon />,
      title: "Compare two models",
      body: "Compare two designs head-to-head to see which item is more reliable over time.",
      cta: "Open",
    },
    {
      to: "/strategy/failure-finding",
      icon: <StrategyIcon />,
      title: "Failure finding",
      body: "Set the inspection interval that keeps a hidden protective function available.",
      cta: "Open",
    },
    {
      to: "/strategy/analyses",
      icon: <ListIcon />,
      title: "Saved analyses",
      body: "Persisted calculations — replacement and failure-finding results are citable RCM evidence.",
      cta: "View all",
    },
  ];

  return (
    <DashboardSection
      crumb={<>Strategy / <b>Overview</b></>}
      title="Strategy"
      subtitle="Turn fitted models into maintenance decisions — replacement intervals and design comparisons."
      cards={cards}
    />
  );
}
