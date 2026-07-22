import { Link } from "react-router-dom";
import PublicNav from "../components/PublicNav.jsx";
import PublicFooter from "../components/PublicFooter.jsx";
import ApiReference from "../components/ApiReference.jsx";

// Public, crawlable API reference for the Reliafy read/ingestion API. Prerendered
// to static HTML for search engines (see prerender-entry.jsx) and reachable
// without an account. Token management stays in-app under Settings › API access.
export default function ApiDocsPublicPage() {
  return (
    <div className="landing">
      <PublicNav />
      <article className="api-doc-page">
        <header className="blog-article-head">
          <h1>API reference</h1>
          <p>
            Read models &amp; reliability, create datasets and fit, read fleet
            forecasts, run strategy calculators, and push operational data — through
            the <b>reliafy-client</b> Python package or the raw <b>HTTP API</b>.{" "}
            <Link to="/login">Create a free account</Link>, then generate a token under
            Settings › API access.
          </p>
        </header>
        <ApiReference />
      </article>
      <PublicFooter />
    </div>
  );
}
