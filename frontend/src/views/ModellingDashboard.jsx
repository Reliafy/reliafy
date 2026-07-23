import DashboardSection from "../components/DashboardSection.jsx";
import GettingStarted from "../components/GettingStarted.jsx";
import { useModels } from "../useModels.js";
import { WaveIcon, PlusIcon, CompareIcon, DegradeIcon, RecurrentIcon } from "../components/icons.jsx";

export default function ModellingDashboard() {
  const { models, loading } = useModels();
  // Stats reflect the user's own work — shared samples would inflate them.
  const own = models.filter((m) => !m.is_sample);
  const observations = own.reduce((s, m) => s + (m.n || 0), 0);
  const distributions = new Set(
    own.map((m) => String(m.distribution || "").split(/[\s(]/)[0])
  ).size;

  const stats = [
    { k: "Saved models", v: own.length },
    { k: "Observations", v: observations.toLocaleString() },
    { k: "Distributions", v: distributions },
  ];

  const cards = [
    {
      to: "/modelling/models",
      icon: <WaveIcon />,
      title: "Saved models",
      body: "Every saved model — life-data and degradation — in one list.",
      cta: "View all",
    },
    {
      to: "/modelling/new",
      icon: <PlusIcon />,
      title: "New model",
      body: "Fit a distribution or proportional-hazards model from a CSV or a saved dataset.",
      cta: "Start",
    },
    {
      to: "/modelling/life",
      icon: <WaveIcon />,
      title: "Life data models",
      body: "Fitted life-distribution and proportional-hazards models.",
      cta: "Open",
    },
    {
      to: "/modelling/recurrent",
      icon: <RecurrentIcon />,
      title: "Recurrent events",
      body: "Repairable systems — fit an MCF and Crow-AMSAA growth model to a fleet's failure history. Is it improving or worsening?",
      cta: "Open",
    },
    {
      to: "/modelling/degradation",
      icon: <DegradeIcon />,
      title: "Degradation models",
      body: "Model wear toward a failure threshold — then monitor your fleet under Fleet → Degradation tracking.",
      cta: "Open",
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
    <>
      <GettingStarted own={own} loading={loading} />
      <DashboardSection
      crumb={<>Modelling / <b>Overview</b></>}
      title="Modelling"
      subtitle="Fit, compare, and manage life-distribution and proportional-hazards models."
      stats={stats}
      cards={cards}
      />
    </>
  );
}
