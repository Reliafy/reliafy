import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { createApiToken, listApiTokens, revokeApiToken } from "../api.js";
import { relativeTime } from "../instrument.js";

// What a token may do. Each token carries a subset; a token created before
// scopes existed carries all three.
const SCOPES = [
  { id: "ingest", label: "Push data", hint: "the /api/ingest endpoints and model import: meter readings, measurements, failure data" },
  { id: "read", label: "Read", hint: "read your models, datasets, diagrams and forecasts; run calculations" },
  { id: "write", label: "Write", hint: "create, change and delete items, and create share links (API and MCP)" },
];
const SCOPE_LABEL = Object.fromEntries(SCOPES.map((s) => [s.id, s.label]));

// Personal API tokens for the ingestion API, plus the endpoint reference.
// Rendered as a section of the Settings page (no page chrome of its own). The
// raw token is shown exactly once at creation; only a hash is stored
// server-side. Pro-only on the cloud.
export default function ApiAccessPanel() {
  const [tokens, setTokens] = useState(null);
  const [allowed, setAllowed] = useState(true);
  const [name, setName] = useState("");
  const [scopes, setScopes] = useState(["ingest"]);
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
      const t = await createApiToken(name.trim() || "API token", scopes);
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
    <div className="set-section">
      <p className="muted-line" style={{ marginTop: 0 }}>
        Personal tokens for scripts, cron jobs and AI agents — pushing meter
        readings, degradation measurements and new failure data, or reading and
        changing your work through the API and MCP. Give each token only what
        it needs: a token that only pushes data can't read your analyses.
      </p>

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
          <button onClick={onCreate} disabled={busy || !allowed || scopes.length === 0}>
            {busy ? "Creating…" : "Create token"}
          </button>
        </div>
        <fieldset className="token-scopes" disabled={!allowed}>
          <legend>This token can</legend>
          {SCOPES.map((s) => (
            <label key={s.id} className="token-scope">
              <input
                type="checkbox"
                checked={scopes.includes(s.id)}
                onChange={(e) =>
                  setScopes((cur) =>
                    e.target.checked ? [...cur, s.id] : cur.filter((x) => x !== s.id)
                  )
                }
              />
              <span><b>{s.label}</b> — {s.hint}</span>
            </label>
          ))}
          {scopes.length === 0 && <p className="muted-line">Pick at least one.</p>}
        </fieldset>
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
                <th style={{ width: 170 }}>Can</th>
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
                  <td className="lib-date">
                    {(t.scopes || []).map((s) => SCOPE_LABEL[s] || s).join(", ")}
                  </td>
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

      <p className="muted-line" style={{ marginTop: "1rem" }}>
        Ready to send data? See the{" "}
        <Link className="evidence-link" to="/api-docs">API reference</Link>{" "}
        for authentication, request bodies and every endpoint with copyable
        examples.
      </p>
    </div>
  );
}
