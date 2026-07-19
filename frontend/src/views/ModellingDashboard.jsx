import { useState } from "react";
import { Link } from "react-router-dom";
import DashboardSection from "../components/DashboardSection.jsx";
import { useModels } from "../useModels.js";
import { WaveIcon, PlusIcon, CompareIcon, DegradeIcon } from "../components/icons.jsx";

export default function ModellingDashboard() {
  const { models } = useModels();
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
      to: "/modelling/degradation",
      icon: <DegradeIcon />,
      title: "Degradation models",
      body: "Model wear toward a failure threshold — then monitor your fleet under Fleet → Degradation tracking.",
      cta: "Open",
    },
    {
      to: "/modelling/recurrent",
      icon: <DegradeIcon />,
      title: "Recurrent events",
      body: "Repairable systems — fit an MCF and Crow-AMSAA growth model to a fleet's failure history. Is it improving or worsening?",
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

  const [showIntro, setShowIntro] = useState(
    () => localStorage.getItem("reliafy_intro_dismissed") !== "1"
  );
  const dismissIntro = () => {
    localStorage.setItem("reliafy_intro_dismissed", "1");
    setShowIntro(false);
  };

  return (
    <>
      {showIntro && (
        <div className="intro-card">
          <div className="intro-head">
            <h3>New here? Three steps with the sample data</h3>
            <button className="modal-close" onClick={dismissIntro} aria-label="Dismiss">×</button>
          </div>
          <ol className="intro-steps">
            <li>
              <Link to="/modelling/m/sample-model-bearings-weibull">Open the bearing Weibull</Link>{" "}
              — a fitted life model with confidence bounds and a randomness verdict.
            </li>
            <li>
              <Link to="/strategy/replacement">Find its optimal replacement interval</Link>{" "}
              — pick “Saved model”, choose the bearing, add costs.
            </li>
            <li>
              <Link to="/rcm/studies/sample-rcm-truck">See the RCM demo study</Link>{" "}
              — every decision linked to evidence, one deliberately contradicted.
            </li>
          </ol>
        </div>
      )}
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
