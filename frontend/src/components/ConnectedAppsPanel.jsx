import { useCallback, useEffect, useState } from "react";
import { listOAuthGrants, revokeOAuthGrant } from "../api.js";
import { relativeTime } from "../instrument.js";

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
        Apps you've allowed to use Reliafy on your behalf — for example Claude,
        added in Claude under Customize → Connectors → Add custom connector with{" "}
        <code>https://reliafy.com/mcp</code>. They can read your work and create
        models, datasets and RBDs; they can't delete anything.
      </p>

      <div className="card">
        <h2>Connected apps</h2>
        {error && <div className="error" style={{ marginTop: 0 }}>{error}</div>}
        {grants === null ? (
          <p className="muted-line">Loading…</p>
        ) : grants.length === 0 ? (
          <p className="muted-line">No apps connected.</p>
        ) : (
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
                    <button className="secondary" disabled={busy === g.id} onClick={() => onRevoke(g)}>
                      {busy === g.id ? "Revoking…" : "Revoke"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
