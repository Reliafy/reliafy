import { useEffect, useState } from "react";
import { viewReport } from "../api.js";
import ReportView from "../views/PublicReport.jsx";
import { Body } from "../views/PublicArtifact.jsx";
import "./ReportComposer.css";

// A saved report read inside the app (Reports › a report › View): the same
// page its share link shows, section by section, read in this workspace, so a
// team's report (which has no public link yet) can be read and printed here.
// Print prints the report alone: the app's menu and bars are left off paper.
export default function ReportPreview({ id }) {
  const [report, setReport] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    let live = true;
    setReport(null);
    setError(null);
    viewReport(id).then((r) => live && setReport(r), (e) => live && setError(e.message));
    return () => { live = false; };
  }, [id]);

  // While it shows, printing prints the report only.
  useEffect(() => {
    document.body.classList.add("printing-report");
    return () => document.body.classList.remove("printing-report");
  }, []);

  if (error) return <div className="card error" role="alert">{error}</div>;
  if (!report) return <div className="card empty">Loading the report…</div>;
  return (
    <div className="rc-view">
      <ReportView report={report} sharedBy={null} Item={Body} />
    </div>
  );
}
