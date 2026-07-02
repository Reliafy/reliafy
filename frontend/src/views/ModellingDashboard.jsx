import DashboardSection from "../components/DashboardSection.jsx";
import { useModels } from "../useModels.js";
import { WaveIcon, PlusIcon, CompareIcon } from "../components/icons.jsx";

export default function ModellingDashboard() {
  const { models } = useModels();
  const observations = models.reduce((s, m) => s + (m.n || 0), 0);
  const distributions = new Set(
    models.map((m) => String(m.distribution || "").split(/[\s(]/)[0])
  ).size;

  const stats = [
    { k: "Saved models", v: models.length },
    { k: "Observations", v: observations.toLocaleString() },
    { k: "Distributions", v: distributions },
  ];

  const cards = [
    {
      to: "/modelling/models",
      icon: <WaveIcon />,
      title: "Saved models",
      body: "Browse, reopen, and manage your fitted life-distribution and PH models.",
      cta: "View all",
    },
    {
      to: "/modelling/models",
      state: { openNew: true },
      icon: <PlusIcon />,
      title: "New model",
      body: "Fit a distribution or proportional-hazards model from a CSV or a saved dataset.",
      cta: "Start",
    },
    {
      to: "/modelling/compare",
      icon: <CompareIcon />,
      title: "Model comparison",
      body: "Rank every candidate distribution against your data with the empirical fit.",
      cta: "Open",
    },
  ];

  return (
    <DashboardSection
      crumb={<>Modelling / <b>Overview</b></>}
      title="Modelling"
      subtitle="Fit, compare, and manage life-distribution and proportional-hazards models."
      stats={stats}
      cards={cards}
    />
  );
}
