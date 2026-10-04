import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import ApiReference, { McpDocs } from "../components/ApiReference.jsx";

// Standalone in-app reference for the ingestion API. Token management lives in
// Settings (/settings?tab=api); this page is the endpoint documentation.
export default function ApiDocsPage() {
  const navigate = useNavigate();
  // Links such as /api-docs#mcp land on the section: the page renders after the
  // browser's own fragment scroll, so do it once mounted.
  useEffect(() => {
    const id = decodeURIComponent(window.location.hash.slice(1));
    if (id) document.getElementById(id)?.scrollIntoView();
  }, []);
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
            Read models &amp; reliability, create datasets and fit, read fleet
            forecasts, run strategy calculators, and push operational data —
            through the <b>reliafy-client</b> Python package or the raw{" "}
            <b>HTTP API</b>. Create a token under{" "}
            <button className="crumb-link" onClick={() => navigate("/settings?tab=api")}>
              Settings › API access
            </button>
            . To connect Claude (claude.ai, the desktop and mobile apps, or Claude
            Code) to your account — no token needed, you just sign in — see{" "}
            <a className="crumb-link" href="#mcp">Use Reliafy from Claude (MCP)</a>.
          </p>
        </div>
      </header>
      <ApiReference />
      <McpDocs
        tokenNote={
          <>
            create one under{" "}
            <button className="crumb-link" onClick={() => navigate("/settings?tab=api")}>
              Settings › API access
            </button>
            .
          </>
        }
      />
    </div>
  );
}
