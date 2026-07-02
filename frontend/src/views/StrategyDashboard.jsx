import DashboardSection from "../components/DashboardSection.jsx";
import { CostIcon, CompareIcon } from "../components/icons.jsx";

export default function StrategyDashboard() {
  // The strategy tools are stateless (they work on data you provide), so the
  // overview is action cards rather than a stat strip.
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
