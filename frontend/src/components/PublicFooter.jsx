import { Link } from "react-router-dom";
import { AUTH_DISABLED } from "../firebase.js";

// Shared footer for all public pages. The software links double as sitewide
// internal links to the SEO product pages. With sign-in off only the guides
// are routed here, so the footer keeps to them.
export default function PublicFooter() {
  if (AUTH_DISABLED) {
    return (
      <footer className="landing-foot foot-stack">
        <div className="foot-row">
          <span>© Reliafy</span>
          <span className="foot-links">
            <Link to="/guides">Guides</Link>
            <a href="https://github.com/Reliafy/reliafy" target="_blank" rel="noreferrer">GitHub</a>
          </span>
        </div>
      </footer>
    );
  }
  return (
    <footer className="landing-foot foot-stack">
      <nav className="foot-products" aria-label="Software">
        <Link to="/weibull-analysis-software">Weibull analysis software</Link>
        <Link to="/rcm-software">RCM software</Link>
        <Link to="/reliability-block-diagram-software">RBD software</Link>
        <Link to="/reliability-analysis-software">Reliability analysis software</Link>
      </nav>
      <div className="foot-row">
        <span>© Reliafy</span>
        <span className="foot-links">
          <Link to="/guides">Guides</Link>
          <Link to="/reference">Reference</Link>
          <Link to="/blog">Blog</Link>
          <Link to="/whats-new">What's new</Link>
          <Link to="/api-docs">API docs</Link>
          <Link to="/terms">Terms</Link>
          <Link to="/privacy">Privacy</Link>
          <a href="https://github.com/Reliafy/reliafy" target="_blank" rel="noreferrer">GitHub</a>
        </span>
      </div>
    </footer>
  );
}
