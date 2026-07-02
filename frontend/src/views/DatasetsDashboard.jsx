import { useEffect, useState } from "react";
import DashboardSection from "../components/DashboardSection.jsx";
import { listDatasets } from "../api.js";
import { ListIcon, UploadIcon } from "../components/icons.jsx";

export default function DatasetsDashboard() {
  const [datasets, setDatasets] = useState([]);

  useEffect(() => {
    listDatasets().then((d) => setDatasets(d.datasets)).catch(() => setDatasets([]));
  }, []);

  const rows = datasets.reduce((s, d) => s + (d.n_rows || 0), 0);
  const linked = datasets.reduce((s, d) => s + (d.n_models || 0), 0);
  const stats = [
    { k: "Datasets", v: datasets.length },
    { k: "Total rows", v: rows.toLocaleString() },
    { k: "Linked models", v: linked },
  ];

  const cards = [
    {
      to: "/datasets/list",
      icon: <ListIcon />,
      title: "All datasets",
      body: "Browse your uploaded CSVs, preview rows, and see which models use them.",
      cta: "View all",
    },
    {
      to: "/datasets/list",
      state: { openUpload: true },
      icon: <UploadIcon />,
      title: "Upload a dataset",
      body: "Add a CSV that you can reuse across models without re-uploading.",
      cta: "Upload",
    },
  ];

  return (
    <DashboardSection
      crumb={<>Datasets / <b>Overview</b></>}
      title="Datasets"
      subtitle="Uploaded CSVs, stored once and shared across the models fitted from them."
      stats={stats}
      cards={cards}
    />
  );
}
