import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { listRbds, deleteRbd, duplicateRbd, renameRbd, importRbdFile, downloadRbdTemplate } from "../api.js";
import ShareDialog from "../components/ShareDialog.jsx";
import RbdExcelImportModal from "../components/RbdExcelImportModal.jsx";
import { useWorkspace } from "../WorkspaceProvider.jsx";
import { relativeTime } from "../instrument.js";
import Chip from "../components/ui/Chip.jsx";
import { missionRbdLine } from "../rbdMission.js";
import { nestRbds, rbdNames } from "../rbdList.js";
import { SectionHeader, SectionList } from "../components/SectionPage.jsx";
import SafetyStarterCard from "../components/RbdSafetyStarter.jsx";
import { PlusIcon, RowActions, RowLink, itemName, rowOpen } from "../components/LibRows.jsx";
import { useAskText, useConfirm } from "../components/ConfirmProvider.jsx";
import { changedText, deleteOrRemoveConfirm, renamePrompt } from "../confirm.js";
import { RBDS_TITLE } from "../navigation.js";
import { ErrorNotice, StorageCapNotice } from "../components/StorageCap.jsx";
import { isCapRefusal } from "../plan.js";

const HELP = { walkthrough: "rbd", guide: "build-an-rbd" };

const ImportIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    {/* An upload arrow (into Reliafy), not a download one. */}
    <path d="M12 16V4m0 0 4 4m-4-4-4 4" /><path d="M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3" />
  </svg>
);

// Modelling › System models › RBDs: the saved block diagrams; open one or create a new one.
export default function RbdHome() {
  const navigate = useNavigate();
  const [rbds, setRbds] = useState(null);
  const [error, setError] = useState(null);
  const [sharing, setSharing] = useState(null); // rbd being shared
  const { workspace } = useWorkspace();
  const fileRef = useRef(null);
  const [importing, setImporting] = useState(false);
  const [imported, setImported] = useState(null); // {file, diagrams} when a file holds several
  const [excelMapping, setExcelMapping] = useState(null); // {file, message}: a workbook to map by hand

  // Open an imported diagram in the builder, unsaved (the builder's Save keeps it).
  const openImported = (d) => navigate("/systems/b", { state: { imported: d } });

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

  const [loadError, setLoadError] = useState(null);
  const refresh = useCallback(() => {
    setLoadError(null);
    listRbds()
      .then((d) => setRbds(d.rbds))
      .catch(setLoadError);
  }, []);

  useEffect(() => refresh(), [refresh]);

  const confirm = useConfirm();
  const askText = useAskText();
  const onDelete = async (r) => {
    if (!(await confirm(deleteOrRemoveConfirm(r, "diagram", { name: itemName(r) })))) return;
    try {
      await deleteRbd(r.id);
      refresh();
    } catch (err) {
      setError(err.message);
    }
  };

  const onRename = async (r) => {
    const name = changedText(await askText(renamePrompt({ kind: "diagram", name: r.name })), r.name);
    if (!name) return;
    try {
      await renameRbd(r.id, name);
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
      setError(err); // past the Free limit: the upgrade card
    } finally {
      setDuplicating(null);
    }
  };

  const pathOf = (id) => `/systems/b/${id}`;
  // A diagram built for another (a part's, or a mission's copy) is listed under that one.
  const nested = useMemo(() => (rbds ? nestRbds(rbds) : rbds), [rbds]);
  const parentName = (r) => rbds?.find((x) => x.id === r.parent_id)?.name || "";
  const newDiagram = <button onClick={() => navigate("/systems/b")}><PlusIcon /> New diagram</button>;

  return (
    <div className="app">
      <input
        ref={fileRef}
        type="file"
        accept=".rsgz9,.rsgz10,.rsgz11,.rsgz20,.rsgz21,.rsgz22,.rsgz23,.rsgz24,.rsgz25,.rsr9,.rsr10,.rsr11,.rsr20,.rsr21,.rsr22,.rsr23,.rsr24,.rsr25,.rsrp,.xml,.opsa,.dft,.json,.xlsx,.xlsm"
        hidden
        onChange={onImportFile}
      />
      <SectionHeader
        title={RBDS_TITLE}
        purpose="Your systems as block diagrams: reliability, availability and what matters most."
        help={HELP}
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
        primary={newDiagram}
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

      <SafetyStarterCard />

      <ErrorNotice error={error} className="card error" />
      {/* At the Free limit: what it is and the upgrade link (the refusal card
          above says the same after a refused copy, so one card at a time). */}
      {!isCapRefusal(error) && (
        <StorageCapNotice kind="rbds" one="saved RBD" many="saved RBDs" refreshKey={rbds} />
      )}

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

      <SectionList
        loadError={loadError}
        onRetry={refresh}
        rows={nested}
        noun={["diagram", "diagrams"]}
        fields={rbdNames}
        // Missions add a diagram each: a filter keeps them apart (shown once both kinds are there).
        types={[{ value: "diagram", label: "Diagrams" }, { value: "mission", label: "Missions" }]}
        typeOf={(r) => (r.mission ? "mission" : "diagram")}
        help={HELP}
        empty={{
          title: "No diagrams yet",
          body: "Lay out blocks in series and parallel, or import one from BlockSim, Open-PSA, Galileo or Excel.",
          action: newDiagram,
        }}
        head={[
          <th key="d" style={{ width: "44%" }}>Diagram</th>,
          <th key="b" className="lib-opt" style={{ width: 90 }}>Blocks</th>,
          <th key="c" className="lib-opt" style={{ width: 110 }}>Connections</th>,
          <th key="s" className="lib-opt">Saved</th>,
          <th key="a"><span className="sr-only">Actions</span></th>,
        ]}
        render={function renderRow(r) {
          return (
          <Fragment key={r.id}>
          <tr className={"lib-row" + (r.depth ? " lib-row-under" : "")} onClick={rowOpen(navigate, pathOf(r.id))}
              style={r.depth ? { "--under": Math.min(r.depth, 4) } : undefined}>
            <td>
              <div className="lib-name">
                <RowLink to={pathOf(r.id)}>{itemName(r)}</RowLink>
                {r.shared_by && <Chip title={`Shared by ${r.shared_by}`}>Shared</Chip>}
                {r.mission && <Chip tone="accent" title="A mission's own RBD, built on its position (Assets › Explorer › Models, under the model it is flown on)">Mission</Chip>}
              </div>
              {r.mission && <div className="rim-tquiet lib-mission">{missionRbdLine(r)}</div>}
              {r.depth > 0 && !r.mission && <div className="rim-tquiet lib-mission">Part of {parentName(r)}</div>}
            </td>
            <td className="lib-n lib-opt">{(r.n_nodes ?? 0).toLocaleString()}</td>
            <td className="lib-n lib-opt">{(r.n_edges ?? 0).toLocaleString()}</td>
            <td className="lib-date lib-opt">{relativeTime(r.updated_at || r.created_at)}</td>
            <RowActions item={r} to={pathOf(r.id)} onDelete={() => onDelete(r)} actions={[
              { id: "duplicate", label: "Duplicate", disabled: duplicating === r.id, onSelect: () => onDuplicate(r) },
              !r.read_only && { id: "rename", label: "Rename…", onSelect: () => onRename(r) },
              !r.read_only && workspace === "personal" && { id: "share", label: "Share…", onSelect: () => setSharing(r) },
            ]} />
          </tr>
          {(r.children || []).map(renderRow)}
          </Fragment>
          );
        }}
      />

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
