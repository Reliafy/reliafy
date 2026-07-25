import { useEffect } from "react";
import DashboardSection from "../components/DashboardSection.jsx";
import { useModels } from "../useModels.js";
import { trackEvent } from "../telemetry.js";
import { WaveIcon, PlusIcon, DegradeIcon, RecurrentIcon, AltIcon } from "../components/icons.jsx";

const ACTIVATED_KEY = "reliafy_activated";

export default function ModellingDashboard() {
  const { models } = useModels();
  // Stats reflect the user's own work — shared samples would inflate them.
  const own = models.filter((m) => !m.is_sample);

  // Activation metric: fire once, the moment a workspace gains its first model
  // of its own. localStorage-guarded so it reports a browser's first activation.
  useEffect(() => {
    if (own.length > 0 && localStorage.getItem(ACTIVATED_KEY) !== "1") {
      localStorage.setItem(ACTIVATED_KEY, "1");
      trackEvent("activated");
    }
  }, [own.length]);

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
      to: "/modelling/alt",
      icon: <AltIcon />,
      title: "Accelerated life (ALT)",
      body: "Fit failure data from elevated-stress tests (temperature, voltage, load), then extrapolate to use level and read the acceleration factor.",
      cta: "Open",
    },
    {
      to: "/modelling/degradation",
      icon: <DegradeIcon />,
      title: "Degradation models",
      body: "Model wear toward a failure threshold — then monitor your fleet under Fleet → Degradation tracking.",
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
