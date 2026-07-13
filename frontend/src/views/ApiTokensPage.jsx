import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import ApiReference from "../components/ApiReference.jsx";
import { createApiToken, listApiTokens, revokeApiToken } from "../api.js";
import { relativeTime } from "../instrument.js";

// Personal API tokens for the ingestion API. The raw token is shown exactly
// once at creation; only a hash is stored server-side. Pro-only on the cloud.
export default function ApiTokensPage() {
  const [tokens, setTokens] = useState(null);
  const [allowed, setAllowed] = useState(true);
  const [name, setName] = useState("");
  const [minted, setMinted] = useState(null); // {name, token} — show-once
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [copied, setCopied] = useState(false);

  const refresh = useCallback(() => {
    listApiTokens()
      .then((d) => {
        setTokens(d.tokens);
        setAllowed(d.allowed !== false);
      })
      .catch((e) => setError(e.message));
  }, []);
  useEffect(() => refresh(), [refresh]);

  const onCreate = async () => {
    setBusy(true);
    setError(null);
    try {
      const t = await createApiToken(name.trim() || "API token");
      setMinted(t);
      setName("");
      refresh();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const onRevoke = async (t) => {
    if (!window.confirm(`Revoke “${t.name}” (${t.prefix}…)? Scripts using it will stop working.`)) return;
    await revokeApiToken(t.id);
    refresh();
  };

  const onCopy = async () => {
    try {
      await navigator.clipboard.writeText(minted.token);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch { /* selectable field remains */ }
  };

  const origin = (typeof window !== "undefined" && window.location.origin) || "https://reliafy.com";
  const curl = minted
    ? `curl -X POST ${origin}/api/ingest/fleets/<fleet-id>/usage \\\n  -H "Authorization: Bearer ${minted.token}" \\\n  -H "Content-Type: text/csv" --data-binary @usage.csv`
    : "";

  return (
    <div className="app">
      <header>
        <div>
          <div className="crumb"><b>API access</b></div>
          <h1>API access</h1>
          <p>
            Personal tokens for pushing data into Reliafy from scripts and cron
            jobs — meter readings, degradation measurements, new failure data.
            Tokens are write-only: they work on the ingestion endpoints and
            nothing else.
          </p>
        </div>
      </header>

      {!allowed && (
        <div className="card note">
          <p style={{ marginTop: 0 }}>
            <b>The programmatic API is a Pro feature.</b> Upgrade to create
            tokens and push meter readings, measurements, and failure data to
            Reliafy from your own scripts and cron jobs.
          </p>
          <Link className="cta cta-solid" to="/billing">Upgrade to Pro</Link>
        </div>
      )}

      <div className="card">
        <div className="row" style={{ gap: "0.6rem", alignItems: "flex-end" }}>
          <label className="login-field" style={{ flex: 1, maxWidth: 340 }}>
            <span>Token name</span>
            <input
              type="text"
              value={name}
              placeholder="e.g. CMMS nightly export"
              disabled={!allowed}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && allowed && onCreate()}
            />
          </label>
          <button onClick={onCreate} disabled={busy || !allowed}>
            {busy ? "Creating…" : "Create token"}
          </button>
        </div>
        {error && <div className="error" style={{ marginTop: "0.6rem" }}>{error}</div>}

        {minted && (
          <div className="card note" style={{ marginTop: "0.9rem" }}>
            <p style={{ marginTop: 0 }}>
              <b>{minted.name}</b> — copy it now; it won't be shown again.
            </p>
            <div className="row" style={{ gap: "0.5rem" }}>
              <input type="text" readOnly value={minted.token} style={{ flex: 1 }}
                     onFocus={(e) => e.target.select()} />
              <button onClick={onCopy}>{copied ? "Copied ✓" : "Copy"}</button>
            </div>
            <pre style={{ marginTop: "0.8rem", overflowX: "auto" }}><code>{curl}</code></pre>
            <p className="muted-line" style={{ marginBottom: 0 }}>
              Full endpoint reference:{" "}
              <a className="evidence-link" href="https://github.com/Reliafy/reliafy/blob/main/docs/api.md" target="_blank" rel="noreferrer">
                docs/api.md
              </a>
            </p>
          </div>
        )}
      </div>

      <div className="card" style={{ marginTop: "1rem" }}>
        <h2>Your tokens</h2>
        {tokens === null ? (
          <p className="muted-line">Loading…</p>
        ) : tokens.length === 0 ? (
          <p className="muted-line">No tokens yet.</p>
        ) : (
          <table className="lib-table">
            <thead>
              <tr>
                <th>Name</th>
                <th style={{ width: 130 }}>Token</th>
                <th style={{ width: 150 }}>Created</th>
                <th style={{ width: 150 }}>Last used</th>
                <th style={{ width: 90 }} />
              </tr>
            </thead>
            <tbody>
              {tokens.map((t) => (
                <tr key={t.id} className="lib-row">
                  <td>{t.name}</td>
                  <td className="lib-date"><code>{t.prefix}…</code></td>
                  <td className="lib-date">{relativeTime(t.created_at)}</td>
                  <td className="lib-date">{t.last_used_at ? relativeTime(t.last_used_at) : "never"}</td>
                  <td className="lib-actions">
                    <button className="act del" title="Revoke" onClick={() => onRevoke(t)}>✕</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <ApiReference />
    </div>
  );
}
