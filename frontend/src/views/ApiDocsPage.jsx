import { Link, useNavigate } from "react-router-dom";
import ApiDocs from "../components/ApiReference.jsx";
import { useAppConfig } from "../ConfigProvider.jsx";
import { apiDocsPage, apiDocsPath } from "../apiDocsPages.js";

// The API docs inside the app (self-hosted, single-user builds; cloud builds
// show the public pages): one route per page (apiDocsPages.js). Token
// management lives in Settings (/settings?tab=api).
export default function ApiDocsPage({ page = "" }) {
  const navigate = useNavigate();
  const { mcp: mcpOn } = useAppConfig();
  const meta = apiDocsPage(page);
  const toSettings = (
    <button className="crumb-link" onClick={() => navigate("/settings?tab=api")}>
      Settings › API access
    </button>
  );
  const header = (
    <header>
      <div>
        <div className="crumb">
          <button className="crumb-link" onClick={() => navigate("/settings?tab=api")}>
            API access
          </button>{" "}
          / {page ? <><Link className="crumb-link" to={apiDocsPath("")}>Reference</Link> / <b>{meta.label}</b></> : <b>Reference</b>}
        </div>
        <h1>{meta.heading}</h1>
        {page === "" && (
          <p>
            Everything Reliafy’s Claude connector can do — fit, analyse RBDs, plan
            tests, run strategy calculators, save and share — over plain HTTPS, from
            the <b>reliafy</b> command line or the <b>reliafy-client</b> Python
            package, plus pushing data and sending files. Create a token under{" "}
            {toSettings}.{" "}
            {mcpOn ? (
              <>
                To connect Claude (claude.ai, the desktop and mobile apps, or Claude
                Code) to your account — no token needed, you just sign in — see{" "}
              </>
            ) : (
              <>Claude can also connect over MCP, available on request — see </>
            )}
            <Link className="crumb-link" to={apiDocsPath("mcp")}>Use Reliafy from Claude (MCP)</Link>.
          </p>
        )}
      </div>
    </header>
  );
  return (
    <div className="app">
      <ApiDocs
        page={page}
        header={header}
        tokenNote={<>create one under {toSettings}.</>}
      />
    </div>
  );
}
