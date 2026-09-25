import { useEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import Logo from "../components/Logo.jsx";
import { unsubscribeEmail, resubscribeEmail } from "../api.js";

// One-click unsubscribe from product-update emails. The link in each email
// carries a signed token (?t=); opening the page unsubscribes straight away —
// no sign-in — and offers an undo. Not prerendered, not in the sitemap, and
// marked noindex (the URL is personal).
export default function Unsubscribe() {
  const { search } = useLocation();
  const token = new URLSearchParams(search).get("t") || "";

  // loading | unsubscribed | resubscribed | invalid | error
  const [state, setState] = useState(token ? "loading" : "invalid");
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const started = useRef(false);

  useEffect(() => {
    const meta = document.createElement("meta");
    meta.name = "robots";
    meta.content = "noindex";
    document.head.appendChild(meta);
    const previous = document.title;
    document.title = "Email preferences — Reliafy";
    return () => {
      meta.remove();
      document.title = previous;
    };
  }, []);

  useEffect(() => {
    // Unsubscribing is idempotent, but don't fire twice (StrictMode remounts).
    if (!token || started.current) return;
    started.current = true;
    unsubscribeEmail(token)
      .then((r) => {
        setEmail(r.email || "");
        setState("unsubscribed");
      })
      .catch((e) => setState(e.status === 404 ? "invalid" : "error"));
  }, [token]);

  const onResubscribe = async () => {
    setBusy(true);
    setError("");
    try {
      const r = await resubscribeEmail(token);
      if (r.email) setEmail(r.email);
      setState("resubscribed");
    } catch (e) {
      setError(e.message || "Couldn't resubscribe — please try again.");
    } finally {
      setBusy(false);
    }
  };

  const settingsLink = <Link to="/settings">Settings</Link>;

  return (
    <div className="login-wrap">
      <div className="login-card">
        <Link className="login-brand" to="/" style={{ textDecoration: "none", color: "inherit" }}>
          <Logo size={34} />
          <span className="brand-name">Reliafy</span>
        </Link>

        {state === "loading" && (
          <>
            <h1 className="login-h1">Updating your preferences…</h1>
            <p className="login-sub">One moment.</p>
          </>
        )}

        {state === "unsubscribed" && (
          <>
            <h1 className="login-h1">You're unsubscribed</h1>
            <p className="login-sub">
              You've been unsubscribed from Reliafy product updates
              {email ? <> (<strong>{email}</strong>)</> : null}. You'll still get
              emails you trigger yourself, like team invites and shares.
            </p>
            {error && <div className="error" style={{ marginTop: 0, marginBottom: 12 }}>{error}</div>}
            <button
              type="button"
              className="secondary"
              onClick={onResubscribe}
              disabled={busy}
              style={{ width: "100%", justifyContent: "center" }}
            >
              {busy ? "Resubscribing…" : "Resubscribe"}
            </button>
          </>
        )}

        {state === "resubscribed" && (
          <>
            <h1 className="login-h1">You're subscribed again.</h1>
            <p className="login-sub">
              We'll keep sending Reliafy product updates
              {email ? <> to <strong>{email}</strong></> : null} — a short
              monthly note on what's new. You can turn them off any time in{" "}
              {settingsLink}.
            </p>
          </>
        )}

        {state === "invalid" && (
          <>
            <h1 className="login-h1">This link doesn't work</h1>
            <p className="login-sub">
              We couldn't match this unsubscribe link to an account — it may be
              incomplete or out of date. Sign in and turn product-update emails
              off in {settingsLink} instead.
            </p>
          </>
        )}

        {state === "error" && (
          <>
            <h1 className="login-h1">Something went wrong</h1>
            <p className="login-sub">
              We couldn't update your preferences just now. Try the link again in
              a moment, or sign in and turn product-update emails off in{" "}
              {settingsLink}.
            </p>
          </>
        )}

        <p className="login-legal">
          <Link to="/whats-new">What's new</Link> · <Link to="/privacy">Privacy Policy</Link>
        </p>
      </div>
    </div>
  );
}
