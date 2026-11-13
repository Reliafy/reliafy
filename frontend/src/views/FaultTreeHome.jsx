import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { deleteFaultTree, importFaultTreeFile, listFaultTrees, renameFaultTree } from "../api.js";
import { relativeTime } from "../instrument.js";
import Chip from "../components/ui/Chip.jsx";
import { SectionHeader, SectionList } from "../components/SectionPage.jsx";
import { PlusIcon, RowActions, RowLink, itemName, rowOpen } from "../components/LibRows.jsx";
import { useAskText, useConfirm } from "../components/ConfirmProvider.jsx";
import { changedText, deleteOrRemoveConfirm, renamePrompt } from "../confirm.js";
import { FAULT_TREES_PATH, FAULT_TREES_TITLE } from "../navigation.js";
import { StorageCapNotice } from "../components/StorageCap.jsx";

const HELP = { guide: "build-a-fault-tree" };

const PencilIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M17 3a2.8 2.8 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z" />
  </svg>
);
const ImportIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 16V4m0 0 4 4m-4-4-4 4" /><path d="M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3" />
  </svg>
);

// Modelling › System models › Fault trees: the saved fault trees; open one or build a new one.
export default function FaultTreeHome() {
  const navigate = useNavigate();
  const [trees, setTrees] = useState(null);
  const [error, setError] = useState(null);
  const [importing, setImporting] = useState(false);
  const [imported, setImported] = useState(null); // {file, trees} when a file holds several
  const fileRef = useRef(null);
  const confirm = useConfirm();
  const askText = useAskText();

  const refresh = useCallback(() => {
    listFaultTrees().then((d) => setTrees(d.fault_trees)).catch((e) => setError(e.message));
  }, []);
  useEffect(() => refresh(), [refresh]);

  // An imported tree opens in the editor, unsaved (its Save keeps it).
  const openImported = (t) => navigate(`${FAULT_TREES_PATH}/new`, { state: { imported: t } });

  const onImportFile = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setError(null);
    setImporting(true);
    try {
      const { trees: found } = await importFaultTreeFile(file);
      const ok = found.filter((t) => t.tree);
      if (found.length === 1 && ok.length === 1) openImported(ok[0]);
      else if (!ok.length) setError(found[0]?.error || "No fault tree in this file could be imported.");
      else setImported({ file: file.name, trees: found });
    } catch (err) {
      setError(err.message);
    } finally {
      setImporting(false);
    }
  };

  const onDelete = async (t) => {
    if (!(await confirm(deleteOrRemoveConfirm(t, "fault tree", { name: itemName(t) })))) return;
    try {
      await deleteFaultTree(t.id);
      refresh();
    } catch (err) {
      setError(err.message);
    }
  };

  const pathOf = (id) => `${FAULT_TREES_PATH}/${id}`;
  const newTree = <button onClick={() => navigate(`${FAULT_TREES_PATH}/new`)}><PlusIcon /> New fault tree</button>;

  return (
    <div className="app">
      <input ref={fileRef} type="file" accept=".xml,.opsa,.dft,.json" hidden onChange={onImportFile} />
      <SectionHeader
        section="systems"
        title={FAULT_TREES_TITLE}
        purpose="Start from what must not happen and work down to its causes: how likely it is, which failures combine to cause it, and which matter most."
        help={HELP}
        actions={
          <button className="secondary" disabled={importing} onClick={() => fileRef.current?.click()}
                  title="Import a fault tree from Open-PSA XML or a Galileo .dft file">
            <ImportIcon /> {importing ? "Importing…" : "Import"}
          </button>
        }
        primary={newTree}
      />

      {error && <div className="card error">{error}</div>}
      <StorageCapNotice kind="fault_trees" one="saved fault tree" many="saved fault trees" refreshKey={trees} />

      {imported && (
        <div className="card">
          <div style={{ display: "flex", alignItems: "baseline", gap: "0.75rem", flexWrap: "wrap" }}>
            <h2 style={{ margin: 0 }}>Fault trees in {imported.file}</h2>
            <span style={{ flex: 1 }} />
            <button className="link" onClick={() => setImported(null)}>Cancel</button>
          </div>
          <p>This file holds {imported.trees.length} top events. Pick one to open — it opens unsaved, so save it to keep it.</p>
          <div className="maint-scroll">
            <table className="lib-table">
              <tbody>
                {imported.trees.map((t, i) => (
                  <tr key={i} className={t.tree ? "lib-row" : undefined} onClick={t.tree ? () => openImported(t) : undefined}>
                    <td><div className="lib-name">{t.name}</div></td>
                    <td className="lib-n">{t.tree ? `${t.n_gates} gates, ${t.n_events} events` : ""}</td>
                    <td className="lib-date">{t.error || (t.notes?.length ? `${t.notes.length} note${t.notes.length > 1 ? "s" : ""}` : "")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <SectionList
        rows={trees}
        noun={["fault tree", "fault trees"]}
        help={HELP}
        empty={{
          title: "No fault trees yet",
          body: (
            <>
              Start from the top event (what must not happen) and add the gates and basic events beneath it, or import
              one from Open-PSA or Galileo.
            </>
          ),
          action: newTree,
        }}
        head={[
          <th key="n" style={{ width: "48%" }}>Fault tree</th>,
          <th key="g" className="lib-opt" style={{ width: 80 }}>Gates</th>,
          <th key="e" className="lib-opt" style={{ width: 110 }}>Basic events</th>,
          <th key="s" className="lib-opt">Saved</th>,
          <th key="a"><span className="sr-only">Actions</span></th>,
        ]}
        render={(t) => (
          <tr key={t.id} className="lib-row" onClick={rowOpen(navigate, pathOf(t.id))}>
            <td>
              <div className="lib-name">
                <RowLink to={pathOf(t.id)}>{itemName(t)}</RowLink>
                {t.placeholders > 0 && <Chip title="Some basic events use guessed data">Placeholders</Chip>}
              </div>
            </td>
            <td className="lib-n lib-opt">{t.n_gates}</td>
            <td className="lib-n lib-opt">{t.n_events}</td>
            <td className="lib-date lib-opt">{relativeTime(t.updated_at || t.created_at)}</td>
            <RowActions item={t} to={pathOf(t.id)} onDelete={() => onDelete(t)}>
              {!t.read_only && (
                <button className="act" title="Rename" aria-label="Rename" onClick={async (e) => {
                  e.stopPropagation();
                  const name = changedText(await askText(renamePrompt({ kind: "fault tree", name: t.name })), t.name);
                  if (!name) return;
                  try {
                    await renameFaultTree(t.id, name);
                    refresh();
                  } catch (err) {
                    setError(err.message);
                  }
                }}>
                  <PencilIcon />
                </button>
              )}
            </RowActions>
          </tr>
        )}
      />
    </div>
  );
}
