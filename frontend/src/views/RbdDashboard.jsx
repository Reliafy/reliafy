import { useEffect, useState } from "react";
import DashboardSection from "../components/DashboardSection.jsx";
import { listRbds } from "../api.js";
import { ListIcon, PlusIcon } from "../components/icons.jsx";

export default function RbdDashboard() {
  const [rbds, setRbds] = useState([]);

  useEffect(() => {
    listRbds().then((d) => setRbds(d.rbds)).catch(() => setRbds([]));
  }, []);

  const own = rbds.filter((r) => !r.is_sample);
  const components = own.reduce((s, r) => s + (r.n_nodes || 0), 0);
  const connections = own.reduce((s, r) => s + (r.n_edges || 0), 0);
  const stats = [
    { k: "Saved RBDs", v: own.length },
    { k: "Components", v: components.toLocaleString() },
    { k: "Connections", v: connections.toLocaleString() },
  ];

  const cards = [
    {
      to: "/rbds/list",
      icon: <ListIcon />,
      title: "Saved diagrams",
      body: "Open a saved reliability block diagram to edit or compute system reliability.",
      cta: "View all",
    },
    {
      to: "/rbds/b",
      icon: <PlusIcon />,
      title: "New RBD",
      body: "Build a diagram on a drag-and-drop canvas and wire components in series or parallel.",
      cta: "Start",
    },
  ];

  return (
    <DashboardSection
      crumb={<>RBDs / <b>Overview</b></>}
      title="RBDs"
      subtitle="Build reliability block diagrams and compute system reliability, MTTF, and importances."
      stats={stats}
      cards={cards}
    />
  );
}
