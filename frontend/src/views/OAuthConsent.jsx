import { useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import Logo from "../components/Logo.jsx";
import { useAuth } from "../AuthProvider.jsx";
import { decideOAuthRequest, getOAuthRequest } from "../api.js";

// OAuth consent: an app (Claude on the web/desktop/mobile, Claude Code, or
// another MCP client) asks to use Reliafy on the user's behalf. The backend
// validated the request and parked it; this page only holds an opaque handle
// (?request=), shows who is asking and where the browser will be sent back to,
// and posts the user's decision. Public route (so a signed-out user can sign
// in and come back here), noindex, never in the sitemap or prerendered.
export default function OAuthConsent() {
  const { search, pathname } = useLocation();
  const handle = new URLSearchParams(search).get("request") || "";
  const { user, loading, signOut } = useAuth();

  const [info, setInfo] = useState(null);
  const [state, setState] = useState(handle ? "loading" : "invalid"); // loading | ready | invalid | leaving
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const meta = document.createElement("meta");
    meta.name = "robots";
    meta.content = "noindex";
    document.head.appendChild(meta);
    const previous = document.title;
    document.title = "Connect an app — Reliafy";
    return () => {
      meta.remove();
      document.title = previous;
    };
  }, []);

  useEffect(() => {
    if (!handle) return;
    let alive = true;
    getOAuthRequest(handle)
      .then((d) => {
        if (!alive) return;
        setInfo(d);
        setState("ready");
      })
      .catch(() => alive && setState("invalid"));
    return () => {
      alive = false;
    };
  }, [handle]);

  const decide = async (approve) => {
    setBusy(true);
    setError("");
    try {
      const { redirect_to } = await decideOAuthRequest(handle, approve);
      setState("leaving");
      window.location.assign(redirect_to);
    } catch (e) {
      setError(e.message || "Something went wrong — please try again.");
      setBusy(false);
    }
  };

  const next = encodeURIComponent(pathname + search);
  const brand = (
    <div className="login-brand">
      <Logo size={34} />
      <span className="brand-name">Reliafy</span>
    </div>
  );

  if (state === "invalid") {
    return (
      <div className="login-wrap">
        <div className="login-card">
          {brand}
          <h1 className="login-h1">This request has expired</h1>
          <p className="login-sub">
            Connection requests are valid for 10 minutes and can be used once.
            Go back to the app you were connecting (for example Claude) and
            start again.
          </p>
          <Link to="/">Go to Reliafy</Link>
        </div>
      </div>
    );
  }

  if (state === "loading" || loading || !info) {
    return <div className="auth-loading">Loading…</div>;
  }

  const name = info.client_name;
  const hostLabel = info.hosted_claude ? "claude.ai" : info.redirect_host;

  return (
    <div className="login-wrap">
      <div className="login-card consent-card">
        {brand}
        <h1 className="login-h1">
          {name} wants to access your Reliafy account
        </h1>

        {/* Where the browser goes next is the one thing Reliafy can vouch
            for, so it comes first — before the app's self-chosen name. */}
        <div className={"consent-redirect consent-redirect-top" + (info.loopback ? " warn" : "")}>
          {info.loopback ? (
            <>
              <div className="consent-redirect-label">You'll be sent back to an app on this computer</div>
              <div className="consent-redirect-host">{info.redirect_host}</div>
              <p>
                Only approve if you just started this from Claude Code (or
                another tool) on this computer. Any program running locally
                can ask for access this way.
              </p>
            </>
          ) : (
            <>
              <div className="consent-redirect-label">After you decide, you'll be sent back to</div>
              <div className="consent-redirect-host">{hostLabel}</div>
              {info.hosted_claude && info.redirect_host && info.redirect_host !== hostLabel && (
                <p>Address: <code>{info.redirect_host}</code></p>
              )}
            </>
          )}
        </div>

        <p className="login-sub">
          {info.client_kind === "cimd" && info.client_host ? (
            <>App identity published by <b>{info.client_host}</b>.</>
          ) : (
            <>“{name}” is the name this app gave itself — Reliafy can't verify it.
              Only approve if you recognise <b>{info.loopback ? info.redirect_host : hostLabel}</b> above.</>
          )}
        </p>

        <div className="consent-scope">
          <b>If you approve, {name} can, on your behalf:</b>
          <ul>
            <li>read your models, datasets, RBDs and fleet forecasts (and the shared samples)</li>
            <li>fit models and run reliability, RBD and maintenance calculations</li>
            <li>create, edit and delete models, datasets and RBDs in your workspace</li>
            <li>create read-only share links to your items</li>
          </ul>
          <p className="muted-line">
            It can't see your password or change your plan or billing.
            Disconnect it any time in Settings → Connected apps.
          </p>
        </div>

        {user ? (
          <>
            <p className="consent-who">
              Signed in as <b>{user.email || user.displayName}</b>
              {" · "}
              <button type="button" className="consent-link" onClick={() => signOut()}>
                Not you?
              </button>
            </p>
            {error && <div className="error" style={{ marginTop: 0 }}>{error}</div>}
            <p className="consent-who">
              Approving sends you to <b className="consent-host-inline">{info.loopback ? info.redirect_host : hostLabel}</b>.
            </p>
            <div className="consent-actions">
              <button type="button" className="secondary" disabled={busy} onClick={() => decide(false)}>
                Deny
              </button>
              <button type="button" disabled={busy} onClick={() => decide(true)}>
                {state === "leaving" ? "Returning…" : busy ? "Please wait…" : "Approve"}
              </button>
            </div>
          </>
        ) : (
          <>
            <p className="consent-who">Sign in to Reliafy to continue.</p>
            <div className="consent-actions">
              <Link className="cta cta-solid" to={`/login?next=${next}`}>Sign in</Link>
              <Link className="cta cta-ghost" to={`/login?signup&next=${next}`}>Create an account</Link>
            </div>
          </>
        )}

        <p className="login-legal">
          See how Reliafy handles your data in the <Link to="/privacy">Privacy Policy</Link>.
        </p>
      </div>
    </div>
  );
}
