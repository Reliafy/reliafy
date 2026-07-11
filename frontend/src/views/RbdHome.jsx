import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { listRbds, deleteRbd, renameRbd } from "../api.js";
import ShareDialog from "../components/ShareDialog.jsx";
import { useWorkspace } from "../WorkspaceProvider.jsx";
import ListSearch, { matches } from "../components/ListSearch.jsx";
import { relativeTime } from "../instrument.js";

const PlusIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 5v14M5 12h14" />
  </svg>
);
const OpenIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M7 17 17 7M9 7h8v8" />
  </svg>
);
const PencilIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M17 3a2.8 2.8 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z" />
  </svg>
);
const ShareIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="6" cy="12" r="2.6" /><circle cx="17" cy="5.5" r="2.6" /><circle cx="17" cy="18.5" r="2.6" />
    <path d="m8.4 10.8 6.2-4M8.4 13.2l6.2 4" />
  </svg>
);
const TrashIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M4 7h16M9 7V5h6v2M7 7l1 13h8l1-13" />
  </svg>
);
const RbdGlyph = ({ color = "#2f6df6" }) => (
  <svg width="72" height="26" viewBox="0 0 72 26" fill="none" stroke={color} strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
    <rect x="4" y="9" width="14" height="8" rx="1.5" />
    <rect x="29" y="2" width="14" height="8" rx="1.5" />
    <rect x="29" y="16" width="14" height="8" rx="1.5" />
    <rect x="54" y="9" width="14" height="8" rx="1.5" />
    <path d="M18 13h4M22 13c0-7 7-7 7-7M22 13c0 7 7 7 7 7M43 6c0 7 7 7 7 7M43 20c0-7 7-7 7-7" />
  </svg>
);

// Derive the four header figures from the live saved-RBD list.
function summarise(rbds) {
  const components = rbds.reduce((s, r) => s + (r.n_nodes || 0), 0);
  const connections = rbds.reduce((s, r) => s + (r.n_edges || 0), 0);
  const latest = rbds.reduce(
    (a, r) => {
      const t = r.updated_at || r.created_at;
      return a && a > t ? a : t;
    },
    null
  );
  return {
    diagrams: rbds.length,
    components,
    connections,
    lastSaved: latest ? relativeTime(latest) : "—",
  };
}

// Landing page for the RBDs section: list saved diagrams, open or create new.
export default function RbdHome() {
  const navigate = useNavigate();
  const [rbds, setRbds] = useState(null);
  const [query, setQuery] = useState("");
  const [error, setError] = useState(null);
  const [sharing, setSharing] = useState(null); // rbd being shared
  const { workspace } = useWorkspace();

  const refresh = useCallback(() => {
    listRbds()
      .then((d) => setRbds(d.rbds))
      .catch((e) => setError(e.message));
  }, []);

  useEffect(() => refresh(), [refresh]);

  const onDelete = async (e, r) => {
    e.stopPropagation();
    const msg = r.is_sample
      ? `Remove the sample “${r.name}” from your workspace? It stays available to other users and you won't see it again.`
      : `Delete RBD “${r.name}”?`;
    if (!window.confirm(msg)) return;
    await deleteRbd(r.id);
    refresh();
  };

  const open = (id) => navigate(`/rbds/b/${id}`);
  const loading = rbds === null;
  const s = !loading ? summarise(rbds) : null;

  return (
    <div className="app">
      <header>
        <div>
          <div className="crumb">
            <button className="crumb-link" onClick={() => navigate("/rbds")}>RBDs</button> / <b>Saved diagrams</b>
          </div>
          <h1>RBDs</h1>
          <p>
            Reliability block diagrams. Open one to edit and compute system
            reliability, or start a new diagram from scratch.
          </p>
        </div>
        <button onClick={() => navigate("/rbds/b")}>
          <PlusIcon /> New RBD
        </button>
      </header>

      {error && <div className="card error">{error}</div>}

      {loading ? (
        <div className="card empty">Loading…</div>
      ) : rbds.length === 0 ? (
        <div className="card empty">
          <h2>No saved RBDs</h2>
          <p>Create a reliability block diagram and save it to see it here.</p>
          <button style={{ marginTop: "1rem" }} onClick={() => navigate("/rbds/b")}>
            <PlusIcon /> New RBD
          </button>
        </div>
      ) : (
        <>
          <div className="stats">
            <div className="stat"><div className="k">Saved RBDs</div><div className="v">{s.diagrams}</div></div>
            <div className="stat"><div className="k">Components</div><div className="v">{s.components.toLocaleString()}</div></div>
            <div className="stat"><div className="k">Connections</div><div className="v">{s.connections.toLocaleString()}</div></div>
            <div className="stat"><div className="k">Last saved</div><div className="v sm">{s.lastSaved}</div></div>
          </div>

          <div className="tablebar">
            <span className="count">{rbds.length} diagrams</span>
            <span className="grow" />
          </div>

          <div className="lib">
            <div className="tablebar">
              <span className="grow" />
              <ListSearch value={query} onChange={setQuery} placeholder="Search diagrams…" />
            </div>
            <table className="lib-table">
              <thead>
                <tr>
                  <th style={{ width: "36%" }}>Diagram</th>
                  <th style={{ width: 90 }}>Nodes</th>
                  <th style={{ width: 90 }}>Edges</th>
                  <th style={{ width: 100 }}>Structure</th>
                  <th>Saved</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {rbds.filter((r) => matches(query, r.name)).map((r) => (
                  <tr key={r.id} className="lib-row" onClick={() => open(r.id)}>
                    <td><div className="lib-name">{r.name}{r.is_sample && <span className="sample-tag">Sample</span>}{r.shared_by && <span className="sample-tag shared" title={`Shared by ${r.shared_by}`}>Shared</span>}</div></td>
                    <td className="lib-n">{(r.n_nodes ?? 0).toLocaleString()}</td>
                    <td className="lib-n">{(r.n_edges ?? 0).toLocaleString()}</td>
                    <td><RbdGlyph /></td>
                    <td className="lib-date">{relativeTime(r.updated_at || r.created_at)}</td>
                    <td className="lib-actions">
                      <div className="lib-acts">
                        <button className="act" title="Open" onClick={(e) => { e.stopPropagation(); open(r.id); }}>
                          <OpenIcon />
                        </button>
                        {!r.read_only && (
                          <button className="act" title="Rename" onClick={async (e) => {
                            e.stopPropagation();
                            const name = window.prompt("Diagram name", r.name);
                            if (name && name.trim() && name.trim() !== r.name) {
                              await renameRbd(r.id, name.trim());
                              refresh();
                            }
                          }}>
                            <PencilIcon />
                          </button>
                        )}
                        {!r.read_only && workspace === "personal" && (
                          <button className="act" title="Share" onClick={(e) => { e.stopPropagation(); setSharing(r); }}>
                            <ShareIcon />
                          </button>
                        )}
                        <button className="act del" title="Delete" onClick={(e) => onDelete(e, r)}>
                          <TrashIcon />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {sharing && (
        <ShareDialog
          collection="rbds"
          artifactId={sharing.id}
          name={sharing.name}
          onClose={() => setSharing(null)}
        />
      )}
    </div>
  );
}
