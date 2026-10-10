import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { listRbds, deleteRbd, duplicateRbd, renameRbd, importRbdFile, downloadRbdTemplate } from "../api.js";
import ShareDialog from "../components/ShareDialog.jsx";
import RbdExcelImportModal from "../components/RbdExcelImportModal.jsx";
import { useWorkspace } from "../WorkspaceProvider.jsx";
import ListSearch, { matches } from "../components/ListSearch.jsx";
import { relativeTime } from "../instrument.js";
import { FirstRunStrip } from "../components/FirstRun.jsx";
import { useFirstRun } from "../firstRun.js";
import Chip from "../components/ui/Chip.jsx";
import PageHeader from "../components/ui/PageHeader.jsx";
import SafetyStarterCard from "../components/RbdSafetyStarter.jsx";
import { PlusIcon, RowActions, SampleGroups, itemName } from "../components/LibRows.jsx";

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
const CopyIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <rect x="8" y="8" width="13" height="13" rx="2" /><path d="M16 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h3" />
  </svg>
);
const ImportIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 3v12M7 10l5 5 5-5M5 21h14" />
  </svg>
);

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

  const onDelete = async (r) => {
    const msg = r.is_sample
      ? `Remove the sample “${itemName(r)}” from your workspace? It stays available to other users and you won't see it again.`
      : `Delete RBD “${r.name}”?`;
    if (!window.confirm(msg)) return;
    try {
      await deleteRbd(r.id);
      refresh();
    } catch (err) {
      setError(err.message);
    }
  };

  // Duplicate (#290): a copy of the diagram, saved as "<name> (copy)" — a
  // sample's copy is the user's own to edit.
  const [duplicating, setDuplicating] = useState(null);
  const onDuplicate = async (r) => {
    setError(null);
    setDuplicating(r.id);
    try {
      await duplicateRbd(r.id, `${itemName(r)} (copy)`);
      refresh();
    } catch (err) {
      setError(err.message);
    } finally {
      setDuplicating(null);
    }
  };

  const open = (id) => navigate(`/rbds/b/${id}`);
  const loading = rbds === null;
  const visible = (rbds || []).filter((r) => matches(query, r.name, r.id));

  return (
    <div className="app">
      <input
        ref={fileRef}
        type="file"
        accept=".rsgz9,.rsgz10,.rsgz11,.rsgz20,.rsgz21,.rsgz22,.rsgz23,.rsgz24,.rsgz25,.rsr9,.rsr10,.rsr11,.rsr20,.rsr21,.rsr22,.rsr23,.rsr24,.rsr25,.rsrp,.xml,.opsa,.dft,.json,.xlsx,.xlsm"
        hidden
        onChange={onImportFile}
      />
      <PageHeader
        title="RBDs"
        meta="Reliability block diagrams: system reliability, availability and importance."
        actions={
          <button
            className="secondary"
            disabled={importing}
            title="Import a diagram from ReliaSoft BlockSim (.rsgz / .rsr), Open-PSA XML, Galileo .dft, RePyability JSON or an Excel workbook (.xlsx)"
            onClick={() => fileRef.current?.click()}
          >
            <ImportIcon /> {importing ? "Importing…" : "Import"}
          </button>
        }
        primary={<button onClick={() => navigate("/rbds/b")}><PlusIcon /> New diagram</button>}
        menu={
          <button
            className="ovm-item"
            title="An Excel template for building a diagram from a list of blocks and connections"
            onClick={() => downloadRbdTemplate().catch((err) => setError(err.message))}
          >
            Download Excel template
          </button>
        }
      />

      <FirstRunStrip info={firstRun} />

      <SafetyStarterCard />

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
            <PlusIcon /> New diagram
          </button>
        </div>
      ) : (
        <>
          <div className="tablebar">
            <span className="count">{visible.length} of {rbds.length} diagrams</span>
            <span className="grow" />
            <ListSearch value={query} onChange={setQuery} placeholder="Search diagrams…" />
          </div>

          <div className="lib">
            <table className="lib-table">
              <thead>
                <tr>
                  <th style={{ width: "44%" }}>Diagram</th>
                  <th className="lib-opt" style={{ width: 90 }}>Blocks</th>
                  <th className="lib-opt" style={{ width: 110 }}>Connections</th>
                  <th className="lib-opt">Saved</th>
                  <th><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                <SampleGroups rows={visible} cols={5} render={(r) => (
                  <tr key={r.id} className="lib-row" onClick={() => open(r.id)}>
                    <td>
                      <div className="lib-name">
                        {itemName(r)}
                        {r.shared_by && <Chip title={`Shared by ${r.shared_by}`}>Shared</Chip>}
                      </div>
                    </td>
                    <td className="lib-n lib-opt">{(r.n_nodes ?? 0).toLocaleString()}</td>
                    <td className="lib-n lib-opt">{(r.n_edges ?? 0).toLocaleString()}</td>
                    <td className="lib-date lib-opt">{relativeTime(r.updated_at || r.created_at)}</td>
                    <RowActions item={r} onOpen={() => open(r.id)} onDelete={() => onDelete(r)}>
                      <button className="act" title="Duplicate" aria-label="Duplicate" disabled={duplicating === r.id}
                              onClick={(e) => { e.stopPropagation(); onDuplicate(r); }}>
                        <CopyIcon />
                      </button>
                      {!r.read_only && (
                        <button className="act" title="Rename" aria-label="Rename" onClick={async (e) => {
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
                        <button className="act" title="Share" aria-label="Share" onClick={(e) => { e.stopPropagation(); setSharing(r); }}>
                          <ShareIcon />
                        </button>
                      )}
                    </RowActions>
                  </tr>
                )} />
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
