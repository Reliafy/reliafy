import { Link } from "react-router-dom";
import PublicNav from "../components/PublicNav.jsx";
import PublicFooter from "../components/PublicFooter.jsx";
import ApiReference, { McpDocs } from "../components/ApiReference.jsx";
import { useAppConfig } from "../ConfigProvider.jsx";

// Public, crawlable API reference for the Reliafy API (tools, CLI, client, ingest). Prerendered
// to static HTML for search engines (see prerender-entry.jsx) and reachable
// without an account. Token management stays in-app under Settings › API access.
export default function ApiDocsPublicPage() {
  const { mcp: mcpOn } = useAppConfig();
  return (
    <div className="landing">
      <PublicNav />
      <article className="api-doc-page">
        <header className="blog-article-head">
          <h1>API reference</h1>
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
            see <a href="#mcp">Use Reliafy from Claude (MCP)</a>.
          </p>
        </header>
        <ApiReference />
        <McpDocs
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
