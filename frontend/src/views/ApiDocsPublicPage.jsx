import { Link } from "react-router-dom";
import PublicNav from "../components/PublicNav.jsx";
import PublicFooter from "../components/PublicFooter.jsx";
import ApiDocs from "../components/ApiReference.jsx";
import { useAppConfig } from "../ConfigProvider.jsx";
import { apiDocsPage, apiDocsPath } from "../apiDocsPages.js";

// Public, crawlable API docs (tools, CLI, client, files, MCP, ingest): one
// route per page (apiDocsPages.js). Prerendered to static HTML for search
// engines (see prerender-entry.jsx) and reachable without an account. Token
// management stays in-app under Settings › API access.
export default function ApiDocsPublicPage({ page = "" }) {
  const { mcp: mcpOn } = useAppConfig();
  const meta = apiDocsPage(page);
  const header = (
    <header className="blog-article-head api-docs-head">
      <h1>{meta.heading}</h1>
      {page === "" && (
        <p>
          Everything Reliafy’s Claude connector can do — fit, analyse RBDs, plan tests,
          run strategy calculators, save and share — over plain HTTPS, from the{" "}
          <b>reliafy</b> command line or the <b>reliafy-client</b> Python package, plus
          pushing data and sending files. <Link to="/login">Create an account</Link>, then
          create a token under Settings › API access (Pro).{" "}
          {mcpOn ? (
            <>
              Claude (claude.ai, desktop, mobile, Claude Code) can connect to your account
              by signing in, no token needed —{" "}
            </>
          ) : (
            <>Claude can also connect over MCP, available on request — </>
          )}
          see <Link to={apiDocsPath("mcp")}>Use Reliafy from Claude (MCP)</Link>.
        </p>
      )}
    </header>
  );
  return (
    <div className="landing">
      <PublicNav />
      <article className="api-doc-page">
        <ApiDocs
          page={page}
          header={header}
          tokenNote={
            <>
              <Link to="/login">sign in</Link> and create one under Settings › API access.
            </>
          }
        />
      </article>
      <PublicFooter />
    </div>
  );
}
