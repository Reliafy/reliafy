import { useCallback, useEffect, useState } from "react";
import { listOAuthGrants, revokeOAuthGrant } from "../api.js";
import { relativeTime } from "../instrument.js";
import { useCopyId } from "./CopyId.jsx";
import Button from "./ui/Button.jsx";
import Card, { CardHeader } from "./ui/Card.jsx";

// No app yet: how to connect Claude, with the MCP address to copy.
function ConnectClaude() {
  const origin = (typeof window !== "undefined" && window.location.origin) || "https://reliafy.com";
  const url = `${origin}/mcp`;
  const [copied, copy] = useCopyId(url);
  return (
    <div className="connect-empty">
      <p className="connect-lead">Connect Claude: add this address as a connector.</p>
      <div className="pl-link-url">
        <input type="text" readOnly value={url} aria-label="MCP address" onFocus={(e) => e.target.select()} />
        <button type="button" onClick={copy}>{copied ? "Copied ✓" : "Copy"}</button>
      </div>
      <ol className="connect-steps">
        <li>In Claude, open Customize → Connectors → Add custom connector.</li>
        <li>Paste the address above and add it.</li>
        <li>Sign in to Reliafy when asked and approve. The app then shows here.</li>
      </ol>
    </div>
  );
}

// Settings > Connected apps: the OAuth grants a user has approved (Claude on
// the web/desktop/mobile, Claude Code, other MCP clients), each revocable.
// Revoking kills the app's access and refresh tokens immediately; it has to
// be approved again to reconnect.
export default function ConnectedAppsPanel() {
  const [grants, setGrants] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState("");

  const refresh = useCallback(() => {
    listOAuthGrants()
      .then((d) => setGrants(d.grants))
      .catch((e) => setError(e.message));
  }, []);
  useEffect(() => refresh(), [refresh]);

  const onRevoke = async (g) => {
    if (!window.confirm(`Disconnect “${g.client_name}”? It will lose access to your Reliafy account straight away.`)) return;
    setBusy(g.id);
    setError(null);
    try {
      await revokeOAuthGrant(g.id);
      refresh();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy("");
    }
  };

  return (
    <div className="set-section">
      <p className="muted-line" style={{ marginTop: 0 }}>
        Apps you've allowed to use Reliafy on your behalf, such as Claude. They work with
        your account's access; disconnect one to cut it off straight away.
      </p>

      <Card>
        <CardHeader title="Connected apps" />
        {error && <div className="error" style={{ marginTop: 0 }}>{error}</div>}
        {grants === null ? (
          <p className="muted-line">Loading…</p>
        ) : grants.length === 0 ? (
          <ConnectClaude />
        ) : (
          <div className="usage-table-wrap">
            <table className="lib-table">
              <thead>
                <tr>
                  <th>App</th>
                  <th style={{ width: 150 }}>Connected</th>
                  <th style={{ width: 150 }}>Last used</th>
                  <th style={{ width: 110 }} />
                </tr>
              </thead>
              <tbody>
                {grants.map((g) => (
                  <tr key={g.id} className="lib-row">
                    <td>
                      {g.client_name}
                      {g.client_host && <span className="muted-line"> · {g.client_host}</span>}
                    </td>
                    <td className="lib-date">{relativeTime(g.created_at)}</td>
                    <td className="lib-date">{g.last_used_at ? relativeTime(g.last_used_at) : "never"}</td>
                    <td className="lib-actions">
                      <Button variant="ghost" size="sm" disabled={busy === g.id} onClick={() => onRevoke(g)}>
                        {busy === g.id ? "Disconnecting…" : "Disconnect"}
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
