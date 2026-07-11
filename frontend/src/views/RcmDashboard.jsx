import { useEffect, useState } from "react";
import DashboardSection from "../components/DashboardSection.jsx";
import { ListIcon, RcmIcon } from "../components/icons.jsx";
import { listRcmStudies } from "../api.js";

export default function RcmDashboard() {
  const [studies, setStudies] = useState(null);
  useEffect(() => {
    listRcmStudies().then((d) => setStudies(d.studies || [])).catch(() => setStudies([]));
  }, []);

  const totals = (studies || []).reduce(
    (acc, s) => {
      const r = s.rollup || {};
      acc.decided += r.decided || 0;
      acc.supported += r.supported || 0;
      acc.contradicted += r.contradicted || 0;
      return acc;
    },
    { decided: 0, supported: 0, contradicted: 0 }
  );

  const stats = studies === null ? [] : [
    { k: "Studies", v: studies.length },
    { k: "Decisions", v: totals.decided },
    { k: "Supported by evidence", v: totals.supported },
    { k: "Contradicted", v: totals.contradicted },
  ];

  const cards = [
    {
      to: "/rcm/studies",
      icon: <ListIcon />,
      title: "Studies",
      body: "Function → failure → mode worksheets where every decision links to the analysis that justifies it.",
      cta: "View all",
    },
    {
      to: "/strategy",
      icon: <RcmIcon />,
      title: "Build the evidence",
      body: "Fit life models, run replacement and failure-finding analyses, and save them as linkable evidence.",
      cta: "Open Strategy",
    },
  ];

  return (
    <DashboardSection
      crumb={<>RCM / <b>Overview</b></>}
      title="Reliability Centred Maintenance"
      subtitle="Evidence-linked RCM: decisions are validated live against your models — and flagged when the data stops supporting them."
      stats={stats}
      cards={cards}
    />
  );
}
