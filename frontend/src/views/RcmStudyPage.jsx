import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import RcmTree from "../components/RcmTree.jsx";
import DecisionModal from "../components/DecisionModal.jsx";
import RcmImportModal from "../components/RcmImportModal.jsx";
import { RollupBadges } from "../components/RcmStatusBadge.jsx";
import { ShareButton } from "../components/ShareDialog.jsx";
import { getRcmStudy, getRcmOptions, putRcmTree, renameRcmStudy } from "../api.js";
import { toCsv } from "../csv.js";
import Chip from "../components/ui/Chip.jsx";
import PageHeader from "../components/ui/PageHeader.jsx";
import { itemName } from "../components/LibRows";

function exportCsv(study, functions) {
  const header = [
    "function", "functional_failure", "failure_mode", "effects", "consequence",
    "outcome", "rtf_basis", "task", "interval", "interval_unit",
    "evidence_type", "evidence_name", "evidence_status", "evidence_detail", "notes",
  ];
  const rows = [header];
  for (const fn of functions) {
    for (const fail of fn.failures || []) {
      for (const mode of fail.modes || []) {
        const d = mode.decision || {};
        rows.push([
          fn.text, fail.text, mode.text, mode.effects || "", mode.consequence || "",
          d.outcome || "", d.rtf_basis || "", d.task || "", d.interval ?? "", d.interval_unit || "",
          d.evidence?.type || "", d.artifact_name || "", d.status || "", d.summary || d.reason || "",
          mode.notes || "",
        ]);
      }
    }
  }
  const csv = toCsv(rows);
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${study.name.replace(/[^\w\- ]+/g, "").trim() || "rcm-study"}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

// One RCM study: the worksheet tree lives in local state while editing; Save
// PUTs the whole tree and comes back with freshly resolved evidence statuses.
export default function RcmStudyPage() {
  const { id } = useParams();
  const [study, setStudy] = useState(null);
  const [functions, setFunctions] = useState([]);
  const [options, setOptions] = useState(null);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [editTarget, setEditTarget] = useState(null); // { fnId, failId, mode }
  const [conflict, setConflict] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [imported, setImported] = useState(null); // { counts, warnings } of the last import

  useEffect(() => {
    getRcmStudy(id)
      .then((s) => {
        if (!s?.id) throw new Error("Unexpected response from the server.");
        setStudy(s);
        setFunctions(s.functions || []);
      })
      .catch((e) => setError(e.message));
    getRcmOptions().then(setOptions).catch(() => {});
  }, [id]);

  const onTreeChange = (next) => { setFunctions(next); setDirty(true); };

  const onDecisionSave = ({ consequence, decision }) => {
    const { fnId, failId, mode } = editTarget;
    setFunctions((fns) => fns.map((f) =>
      f.id !== fnId ? f : {
        ...f,
        failures: f.failures.map((x) =>
          x.id !== failId ? x : {
            ...x,
            modes: x.modes.map((m) => (m.id === mode.id ? { ...m, consequence, decision } : m)),
          }
        ),
      }
    ));
    setDirty(true);
    setEditTarget(null);
  };

  const onSave = async () => {
    setSaving(true);
    setError(null);
    try {
      const fresh = await putRcmTree(id, functions, study.updated_at);
      setStudy(fresh);
      setFunctions(fresh.functions || []);
      setDirty(false);
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

  const onImported = (fresh) => {
    setStudy(fresh);
    setFunctions(fresh.functions || []);
    setDirty(false);
    setError(null);
    setImported(fresh.imported || null);
    setImportOpen(false);
  };

  const onReload = () => {
    setConflict(false);
    setError(null);
    setDirty(false);
    getRcmStudy(id)
      .then((s) => { setStudy(s); setFunctions(s.functions || []); })
      .catch((e) => setError(e.message));
  };

  const onRename = async () => {
    const name = window.prompt("Study name", study.name);
    if (!name || !name.trim() || name.trim() === study.name) return;
    try {
      const updated = await renameRcmStudy(id, name.trim());
      setStudy((s) => ({ ...s, name: updated.name }));
    } catch (err) {
      setError(err.message);
    }
  };

  if (error && !study) return <div className="app"><div className="card error">{error}</div></div>;
  if (!study) return <div className="app"><div className="card empty">Loading…</div></div>;

  const readOnly = study.read_only ?? study.is_sample;

  return (
    <div className="app">
      <PageHeader
        crumbs={[{ label: "RCM", to: "/rcm" }]}
        title={itemName(study)}
        badges={
          <>
            {study.is_sample && <Chip>Sample</Chip>}
            {study.shared_by && <Chip title={`Shared by ${study.shared_by}`}>Shared</Chip>}
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
        menu={
          <>
            <ShareButton
              collection="rcm_studies"
              artifactId={study.id}
              name={study.name}
              readOnly={readOnly}
              className="ovm-item"
            />
            {!readOnly && <button className="ovm-item" onClick={onRename}>Rename</button>}
            {!readOnly && (
              <button
                className="ovm-item"
                onClick={() => setImportOpen(true)}
                disabled={dirty}
                title={dirty ? "Save or discard your edits first" : "Append or replace the worksheet from an FMEA / RCM spreadsheet"}
              >
                Import from Excel
              </button>
            )}
          </>
        }
      >
        {study.rollup && <div className="ph-chips"><RollupBadges rollup={study.rollup} /></div>}
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
      {imported && (
        <div className="card note xl-imported">
          <p>
            Imported {imported.counts.modes} failure mode{imported.counts.modes === 1 ? "" : "s"} under{" "}
            {imported.counts.functions} function{imported.counts.functions === 1 ? "" : "s"}
            {imported.counts.decisions ? ` (${imported.counts.decisions} with a decision)` : ""} — saved.
            <button className="link" style={{ marginLeft: "0.6rem" }} onClick={() => setImported(null)}>Dismiss</button>
          </p>
          {imported.warnings.map((w, i) => <p key={i}>{w}</p>)}
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
          {study.shared_by
            ? `Shared with you by ${study.shared_by} — read-only. Evidence links open the analyses behind each decision.`
            : "This study is read-only in your current workspace."}
        </div>
      )}

      <div className="card">
        <RcmTree
          functions={functions}
          readOnly={readOnly}
          onChange={onTreeChange}
          onEditDecision={(fnId, failId, mode) => setEditTarget({ fnId, failId, mode })}
        />
      </div>

      {importOpen && (
        <RcmImportModal study={{ ...study, functions }} onClose={() => setImportOpen(false)} onImported={onImported} />
      )}

      {editTarget && options && (
        <DecisionModal
          options={options}
          mode={editTarget.mode}
          onSave={onDecisionSave}
          onClose={() => setEditTarget(null)}
        />
      )}
    </div>
  );
}
