import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { listRbds, deleteRbd, renameRbd, importRbdFile, downloadRbdTemplate } from "../api.js";
import ShareDialog from "../components/ShareDialog.jsx";
import RbdExcelImportModal from "../components/RbdExcelImportModal.jsx";
import { useWorkspace } from "../WorkspaceProvider.jsx";
import ListSearch, { matches } from "../components/ListSearch.jsx";
import { relativeTime } from "../instrument.js";
import { FirstRunStrip } from "../components/FirstRun.jsx";
import { useFirstRun } from "../firstRun.js";
import Chip from "../components/ui/Chip.jsx";

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
const ImportIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 3v12M7 10l5 5 5-5M5 21h14" />
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
  // No models, datasets or diagrams of their own yet (samples don't count).
  const firstRun = useFirstRun(rbds ? rbds.some((r) => !r.is_sample) : undefined);
  const [query, setQuery] = useState("");
  const [error, setError] = useState(null);
  const [sharing, setSharing] = useState(null); // rbd being shared
  const { workspace } = useWorkspace();
  const fileRef = useRef(null);
  const [importing, setImporting] = useState(false);
  const [imported, setImported] = useState(null); // {file, diagrams} when a file holds several
  const [excelMapping, setExcelMapping] = useState(null); // {file, message}: a workbook to map by hand

  // Open an imported diagram in the builder, unsaved (the builder's Save keeps it).
  const openImported = (d) => navigate("/rbds/b", { state: { imported: d } });

  const onImportFile = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setError(null);
    setImporting(true);
    try {
      showImported(file, await importRbdFile(file));
    } catch (err) {
      // An Excel workbook not laid out like the template: map its columns.
      if (err.code === "excel_mapping") setExcelMapping({ file, message: err.message });
      else setError(err.message);
    } finally {
      setImporting(false);
    }
  };

  const showImported = (file, { diagrams }) => {
    const ok = diagrams.filter((d) => d.graph);
    if (diagrams.length === 1 && ok.length === 1) openImported(ok[0]);
    else if (!ok.length) setError(diagrams[0]?.error || "No diagram in this file could be imported.");
    else setImported({ file: file.name, diagrams });
  };

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
        <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
          <input
            ref={fileRef}
            type="file"
            accept=".rsgz9,.rsgz10,.rsgz11,.rsgz20,.rsgz21,.rsgz22,.rsgz23,.rsgz24,.rsgz25,.rsr9,.rsr10,.rsr11,.rsr20,.rsr21,.rsr22,.rsr23,.rsr24,.rsr25,.rsrp,.xml,.opsa,.dft,.json,.xlsx,.xlsm"
            hidden
            onChange={onImportFile}
          />
          <button
            className="secondary"
            disabled={importing}
            title="Import a diagram from ReliaSoft BlockSim (.rsgz / .rsr), Open-PSA XML, Galileo .dft, RePyability JSON or an Excel workbook (.xlsx)"
            onClick={() => fileRef.current?.click()}
          >
            <ImportIcon /> {importing ? "Importing…" : "Import"}
          </button>
          <button
            className="secondary"
            title="An Excel template for building a diagram from a list of blocks and connections"
            onClick={() => downloadRbdTemplate().catch((err) => setError(err.message))}
          >
            Excel template
          </button>
          <button onClick={() => navigate("/rbds/b")}>
            <PlusIcon /> New RBD
          </button>
        </div>
      </header>

      <FirstRunStrip info={firstRun} />

      {error && <div className="card error">{error}</div>}

      {excelMapping && (
        <RbdExcelImportModal
          file={excelMapping.file}
          message={excelMapping.message}
          onClose={() => setExcelMapping(null)}
          onImported={(result) => {
            const file = excelMapping.file;
            setExcelMapping(null);
            showImported(file, result);
          }}
        />
      )}

      {imported && (
        <div className="card">
          <div style={{ display: "flex", alignItems: "baseline", gap: "0.75rem" }}>
            <h2 style={{ margin: 0 }}>Diagrams in {imported.file}</h2>
            <span className="grow" style={{ flex: 1 }} />
            <button className="link" onClick={() => setImported(null)}>Cancel</button>
          </div>
          <p>This file holds {imported.diagrams.length} diagrams. Pick one to open — it opens unsaved, so save it to keep it.</p>
          <table className="lib-table">
            <tbody>
              {imported.diagrams.map((d, i) => (
                <tr key={i} className={d.graph ? "lib-row" : undefined} onClick={d.graph ? () => openImported(d) : undefined}>
                  <td><div className="lib-name">{d.name}</div></td>
                  <td className="lib-n">{d.graph ? `${d.n_nodes} nodes` : ""}</td>
                  <td className="lib-date">
                    {d.error ? d.error : d.warnings?.length ? `${d.warnings.length} note${d.warnings.length > 1 ? "s" : ""}` : ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

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
                    <td><div className="lib-name">{r.name}{r.is_sample && <Chip>Sample</Chip>}{r.shared_by && <Chip title={`Shared by ${r.shared_by}`}>Shared</Chip>}</div></td>
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
