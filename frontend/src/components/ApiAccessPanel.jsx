import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { createApiToken, listApiTokens, revokeApiToken } from "../api.js";
import { useAppConfig } from "../ConfigProvider.jsx";
import { relativeTime } from "../instrument.js";
import Button from "./ui/Button.jsx";
import Card, { CardHeader } from "./ui/Card.jsx";

// What a token may do. Each token carries a subset; a token created before
// scopes existed carries all three.
const SCOPES = [
  { id: "ingest", label: "Push data", hint: "the /api/ingest endpoints and model import: meter readings, measurements, failure data" },
  { id: "read", label: "Read", hint: "read your models, datasets, diagrams and forecasts; run calculations" },
  { id: "write", label: "Write", hint: "create, change and delete items, and create share links (API and MCP)" },
];
const SCOPE_LABEL = Object.fromEntries(SCOPES.map((s) => [s.id, s.label]));

// A first request for a new token, matching what it may do: pushing usage
// for a token that can push data, else listing models, else creating a
// dataset.
function exampleCurl(origin, token, scopes) {
  const auth = `-H "Authorization: Bearer ${token}"`;
  if (scopes.includes("ingest")) {
    return `curl -X POST ${origin}/api/ingest/fleets/<fleet-id>/usage \\\n  ${auth} \\\n  -H "Content-Type: text/csv" --data-binary @usage.csv`;
  }
  if (scopes.includes("read")) {
    return `curl ${origin}/api/v1/models \\\n  ${auth}`;
  }
  return `curl -X POST ${origin}/api/v1/datasets \\\n  ${auth} \\\n  -H "Content-Type: application/json" \\\n  -d '{"name": "Pump failures", "data": {"hours": [120, 340, 510], "failed": [1, 0, 1]}}'`;
}

// Personal API tokens: the list first, a "New token" button that opens the
// form, and the new token shown exactly once (only a hash is stored
// server-side). Rendered as a section of the Settings page. Pro-only on the
// cloud.
export default function ApiAccessPanel() {
  const { billing } = useAppConfig();
  const [tokens, setTokens] = useState(null);
  const [allowed, setAllowed] = useState(true);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [scopes, setScopes] = useState(["ingest"]);
  const [minted, setMinted] = useState(null); // {name, token, scopes} — show-once
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
      setCreating(false);
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

  return (
    <div className="set-section">
      <p className="muted-line" style={{ marginTop: 0 }}>
        Personal tokens for scripts, cron jobs and AI agents. Give each token only what it
        needs: a token that only pushes data can't read your analyses. The{" "}
        <Link className="evidence-link" to="/api-docs">API reference</Link> has every
        endpoint with copyable examples.
      </p>

      {!allowed && (
        <div className="card note">
          <p>
            <b>The programmatic API is a Pro feature.</b> Upgrade to create
            tokens and push meter readings, measurements, and failure data to
            Reliafy from your own scripts and cron jobs.
          </p>
          {billing && <Link className="cta cta-solid" to="/billing" style={{ marginTop: "0.8rem" }}>Upgrade to Pro</Link>}
        </div>
      )}

      {minted && (
        <Card className="token-minted">
          <CardHeader
            title={`${minted.name} is ready`}
            subtitle="Copy it now; it won't be shown again."
            actions={<Button variant="ghost" size="sm" onClick={() => setMinted(null)}>Done</Button>}
          />
          <div className="pl-link-url">
            <input type="text" readOnly value={minted.token} aria-label="New token"
                   onFocus={(e) => e.target.select()} />
            <button type="button" onClick={onCopy}>{copied ? "Copied ✓" : "Copy"}</button>
          </div>
          <pre className="token-curl"><code>{exampleCurl(origin, minted.token, minted.scopes || scopes)}</code></pre>
        </Card>
      )}

      <Card>
        <CardHeader
          title="Your tokens"
          actions={!creating && allowed && (
            <Button variant={tokens?.length === 0 && !minted ? "primary" : "secondary"} size="sm"
                    onClick={() => setCreating(true)}>
              New token
            </Button>
          )}
        />

        {creating && (
          <div className="token-form">
            <label className="login-field">
              <span>Token name</span>
              <input
                type="text"
                autoFocus
                value={name}
                placeholder="e.g. CMMS nightly export"
                onChange={(e) => setName(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && scopes.length > 0 && onCreate()}
              />
            </label>
            <fieldset className="token-scopes">
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
            <div className="row token-form-acts">
              <Button onClick={onCreate} disabled={busy || scopes.length === 0}>
                {busy ? "Creating…" : "Create token"}
              </Button>
              <Button variant="secondary" onClick={() => { setCreating(false); setError(null); }} disabled={busy}>
                Cancel
              </Button>
            </div>
          </div>
        )}
        {error && <div className="error" style={{ marginTop: "0.6rem" }}>{error}</div>}

        {tokens === null ? (
          <p className="muted-line">Loading…</p>
        ) : tokens.length === 0 ? (
          !creating && <p className="muted-line">No tokens yet.</p>
        ) : (
          <div className="usage-table-wrap">
            <table className="lib-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th style={{ width: 130 }}>Token</th>
                  <th style={{ width: 170 }}>Can</th>
                  <th style={{ width: 130 }}>Created</th>
                  <th style={{ width: 130 }}>Last used</th>
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
                      <Button variant="ghost" size="sm" title={`Revoke ${t.name}`} onClick={() => onRevoke(t)}>
                        Revoke
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
