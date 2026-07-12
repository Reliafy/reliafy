import { useEffect, useState } from "react";
import DashboardSection from "../components/DashboardSection.jsx";
import { DegradeIcon, CompareIcon } from "../components/icons.jsx";
import { listFleets, listDegradationModels } from "../api.js";

export default function FleetDashboard() {
  const [fleets, setFleets] = useState(null);
  const [tracked, setTracked] = useState(null);

  useEffect(() => {
    listFleets().then((d) => setFleets(d.fleets || [])).catch(() => setFleets([]));
    listDegradationModels()
      .then((d) => setTracked((d.models || [])
        .filter((m) => !m.is_sample)
        .reduce((s, m) => s + (m.n_items || 0), 0)))
      .catch(() => setTracked(0));
  }, []);

  const expected = (fleets || []).reduce(
    (s, f) => s + (f.forecast_status === "ok" ? f.expected || 0 : 0), 0
  );
  const stats = fleets === null ? [] : [
    { k: "Forecasts", v: fleets.length },
    { k: "Items in forecasts", v: fleets.reduce((s, f) => s + (f.n_items || 0), 0) },
    { k: "Expected failures (horizons)", v: expected.toFixed(1) },
    { k: "Tracked items (degradation)", v: tracked ?? "…" },
  ];

  const cards = [
    {
      to: "/fleet/forecasts",
      icon: <CompareIcon />,
      title: "Failure forecasts",
      body: "How many failures should you expect next quarter or next year? Enter each item's usage and let your life model answer — with replacement, for spares planning.",
      cta: "Open",
    },
    {
      to: "/fleet/tracking",
      icon: <DegradeIcon />,
      title: "Degradation tracking",
      body: "Monitor individual assets against a degradation model and predict when each will cross its failure threshold.",
      cta: "Open",
    },
  ];

  return (
    <DashboardSection
      crumb={<>Fleet / <b>Overview</b></>}
      title="Fleet"
      subtitle="Your in-service assets: remaining-life tracking and fleet-level failure forecasting from your own models."
      stats={stats}
      cards={cards}
    />
  );
}
