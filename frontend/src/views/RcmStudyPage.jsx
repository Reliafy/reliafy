import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import RcmTree from "../components/RcmTree.jsx";
import RcmStudyWorksheet from "../components/RcmStudyWorksheet.jsx";
import RcmStudyDecisionModal from "../components/RcmStudyDecisionModal.jsx";
import { RollupBadges } from "../components/RcmStatusBadge.jsx";
import { useAskText } from "../components/ConfirmProvider.jsx";
import { changedText, renamePrompt } from "../confirm.js";
import { getRcmStudy, getRcmStudyOptions, putRcmTree, renameRcmStudy } from "../api.js";
import { toCsv } from "../csv.js";
import Chip from "../components/ui/Chip.jsx";
import PageHeader from "../components/ui/PageHeader.jsx";
import Tabs from "../components/ui/Tabs.jsx";
import { worksheetCsvRows } from "../rcmStudyWorksheet.js";
import usePhone from "../usePhone.js";
import { itemName } from "../components/LibRows";
import { useNavCrumbs } from "../RolesProvider.jsx";

function exportCsv(study, functions) {
  const rows = worksheetCsvRows(functions);
  const csv = toCsv(rows);
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${study.name.replace(/[^\w\- ]+/g, "").trim() || "rcm-study"}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

// The views of a study: the worksheet (an outline grid, the main view) and
// the tree (the nested editor, as before). The address says which (?tab=tree).
const TABS = [
  { id: "worksheet", label: "Worksheet", title: "The worksheet as a table: the study's tree with its columns beside it" },
  { id: "tree", label: "Tree", title: "The functions, failures and modes as a nested list, each with its evidence" },
];
const UNDO_DEPTH = 50;

// One RCM study: the worksheet lives in local state while editing; Save PUTs
// the whole tree and comes back with freshly resolved evidence statuses. On a
// desktop the page fits the window, the worksheet scrolling inside its card.
export default function RcmStudyPage() {
  // Maintenance › RCM studies (or, without Reliafy Maintenance, Maintenance alone: it is the RCM studies).
  const crumbs = useNavCrumbs("maintenance", "/maintenance/rcm");
  const { id } = useParams();
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") === "tree" ? "tree" : "worksheet";
  const setTab = (t) => {
    const next = new URLSearchParams(params);
    if (t === "worksheet") next.delete("tab");
    else next.set("tab", t);
    setParams(next, { replace: true });
  };
  const phone = usePhone();
  const [study, setStudy] = useState(null);
  const [functions, setFunctions] = useState([]);
  const [options, setOptions] = useState(null);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [editTarget, setEditTarget] = useState(null); // { at: [fi, xi, mi], mode }
  const [conflict, setConflict] = useState(false);
  const askText = useAskText();
  // Undo: the worksheet as it was before each change since the last save.
  const history = useRef([]);
  const [, setUndoCount] = useState(0);
  const resetHistory = () => { history.current = []; setUndoCount(0); };

  useEffect(() => {
    getRcmStudy(id)
      .then((s) => {
        if (!s?.id) throw new Error("Unexpected response from the server.");
        setStudy(s);
        setFunctions(s.functions || []);
      })
      .catch((e) => setError(e.message));
    getRcmStudyOptions().then(setOptions).catch(() => {});
  }, [id]);

  const current = useRef(functions);
  current.current = functions;
  const onTreeChange = useCallback((next) => {
    history.current = [...history.current, current.current].slice(-UNDO_DEPTH);
    current.current = next;
    setFunctions(next);
    setUndoCount(history.current.length);
    setDirty(true);
  }, []);

  const onUndo = useCallback(() => {
    const prev = history.current.pop();
    if (!prev) return;
    current.current = prev;
    setFunctions(prev);
    setUndoCount(history.current.length);
    setDirty(true);
  }, []);

  // Ctrl+Z (⌘Z) undoes the last change to the worksheet, unless you're typing.
  useEffect(() => {
    const onKey = (e) => {
      if (e.key.toLowerCase() !== "z" || !(e.ctrlKey || e.metaKey) || e.shiftKey || e.altKey) return;
      if (e.target.closest?.("input, textarea, select, [contenteditable='true']")) return;
      if (!history.current.length) return;
      e.preventDefault();
      onUndo();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onUndo]);

  // The decision dialog for a failure mode (from the worksheet or the tree).
  const openDecision = (at, mode) => setEditTarget({ at, mode });
  const onDecisionSave = ({ consequence, decision }) => {
    const [fi, xi, mi] = editTarget.at;
    onTreeChange(functions.map((f, i) =>
      i !== fi ? f : {
        ...f,
        failures: f.failures.map((x, j) =>
          j !== xi ? x : { ...x, modes: x.modes.map((m, k) => (k === mi ? { ...m, consequence, decision } : m)) }
        ),
      }
    ));
    setEditTarget(null);
  };
  // The tree names a mode by its function's and failure's ids.
  const treeDecision = (fnId, failId, mode) => {
    const fi = functions.findIndex((f) => f.id === fnId);
    const xi = fi < 0 ? -1 : functions[fi].failures.findIndex((x) => x.id === failId);
    const mi = xi < 0 ? -1 : functions[fi].failures[xi].modes.findIndex((m) => m.id === mode.id);
    if (mi >= 0) openDecision([fi, xi, mi], mode);
  };

  const onSave = async () => {
    setSaving(true);
    setError(null);
    try {
      const fresh = await putRcmTree(id, functions, study.updated_at);
      setStudy(fresh);
      setFunctions(fresh.functions || []);
      setDirty(false);
      resetHistory();
    } catch (err) {
      if (err.code === "conflict") {
        setError(err.message + " Use Reload below to fetch the latest version (your unsaved edits will be lost).");
        setConflict(true);
      } else {
        setError(err.message);
      }
    } finally {
      setSaving(false);
    }
  };

  const onReload = () => {
    setConflict(false);
    setError(null);
    setDirty(false);
    resetHistory();
    getRcmStudy(id)
      .then((s) => { setStudy(s); setFunctions(s.functions || []); })
      .catch((e) => setError(e.message));
  };

  const onRename = async () => {
    const name = changedText(await askText(renamePrompt({ kind: "study", name: study.name })), study.name);
    if (!name) return;
    try {
      const updated = await renameRcmStudy(id, name);
      setStudy((s) => ({ ...s, name: updated.name }));
    } catch (err) {
      setError(err.message);
    }
  };

  if (error && !study) return <div className="app"><div className="card error">{error}</div></div>;
  if (!study) return <div className="app"><div className="card empty">Loading…</div></div>;

  const readOnly = study.read_only ?? study.is_sample;

  return (
    <div className="app rcm-frame">
      <PageHeader
        crumbs={crumbs}
        title={itemName(study)}
        badges={
          <>
            {study.is_sample && <Chip>Sample</Chip>}
            {dirty && <Chip tone="warning">Unsaved</Chip>}
          </>
        }
        meta={
          (study.system || study.description || study.updated_by) && (
            <>
              {[study.system, study.description].filter(Boolean).join(" — ")}
              {study.updated_by && <>{study.system || study.description ? " · " : ""}Last edited by {study.updated_by}</>}
            </>
          )
        }
        actions={
          <button className="secondary" onClick={() => exportCsv(study, functions)}>
            Export CSV
          </button>
        }
        primary={!readOnly && (
          <button onClick={onSave} disabled={saving || !dirty}>
            {saving ? "Saving…" : dirty ? "Save study" : "Saved"}
          </button>
        )}
        id={study.id}
        menu={!readOnly && <button className="ovm-item" onClick={onRename}>Rename</button>}
      >
        {study.rollup && <div className="ph-chips" data-wt="rcm-checks"><RollupBadges rollup={study.rollup} /></div>}
      </PageHeader>

      {error && (
        <div className="card error">
          {error}
          {conflict && (
            <div style={{ marginTop: "0.6rem" }}>
              <button className="secondary" onClick={onReload}>Reload latest version</button>
            </div>
          )}
        </div>
      )}
      {readOnly && study.is_sample && (
        <div className="card note">
          This is a shared sample — explore how decisions link to evidence
          (including the intentionally contradicted run-to-failure call), then
          create your own study to edit.
        </div>
      )}
      {readOnly && !study.is_sample && (
        <div className="card note">
          This study is read-only in your current workspace.
        </div>
      )}

      <Tabs tabs={TABS} value={tab} onChange={setTab} label="Views of the study" idPrefix="rcm" />
      <div className="rcm-body" role="tabpanel" id="rcm-panel" aria-labelledby={`rcm-tab-${tab}`}>
        {tab === "worksheet" ? (
          <div className="card rsw-card">
            <RcmStudyWorksheet
              studyId={study.id}
              functions={functions}
              readOnly={readOnly}
              phone={phone}
              onChange={onTreeChange}
              onDecision={(r) => openDecision(r.at, r.ref)}
              onUndo={onUndo}
              canUndo={history.current.length > 0}
            />
          </div>
        ) : (
          <div className="card rcm-tree-card">
            <RcmTree
              functions={functions}
              readOnly={readOnly}
              onChange={onTreeChange}
              onEditDecision={treeDecision}
            />
          </div>
        )}
      </div>

      {editTarget && options && (
        <RcmStudyDecisionModal
          options={options}
          mode={editTarget.mode}
          onSave={onDecisionSave}
          onClose={() => setEditTarget(null)}
        />
      )}
    </div>
  );
}
