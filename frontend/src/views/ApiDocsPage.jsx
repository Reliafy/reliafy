import { useNavigate } from "react-router-dom";
import ApiReference from "../components/ApiReference.jsx";

// Standalone in-app reference for the ingestion API. Token management lives in
// Settings (/settings?tab=api); this page is the endpoint documentation.
export default function ApiDocsPage() {
  const navigate = useNavigate();
  return (
    <div className="app">
      <header>
        <div>
          <div className="crumb">
            <button className="crumb-link" onClick={() => navigate("/settings?tab=api")}>
              API access
            </button>{" "}
            / <b>Reference</b>
          </div>
          <h1>API reference</h1>
          <p>
            Two ways to get data and models into Reliafy: the{" "}
            <b>reliafy-client</b> Python package for pushing SurPyval fits, and
            the raw <b>HTTP API</b> for scripts, cron jobs and CMMS integrations.
            Create a token under{" "}
            <button className="crumb-link" onClick={() => navigate("/settings?tab=api")}>
              Settings › API access
            </button>
            .
          </p>
        </div>
      </header>
      <ApiReference />
    </div>
  );
}
