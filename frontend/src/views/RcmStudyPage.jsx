import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import RcmTree from "../components/RcmTree.jsx";
import DecisionModal from "../components/DecisionModal.jsx";
import { RollupBadges } from "../components/RcmStatusBadge.jsx";
import { ShareButton } from "../components/ShareDialog.jsx";
import { getRcmStudy, getRcmOptions, putRcmTree, renameRcmStudy } from "../api.js";

const csvCell = (v) => {
  const s = String(v ?? "");
  return /[",\n]/.test(s) ? `"${s.replaceAll('"', '""')}"` : s;
};

function exportCsv(study, functions) {
  const header = [
    "function", "functional_failure", "failure_mode", "effects", "consequence",
    "outcome", "rtf_basis", "task", "interval", "interval_unit",
    "evidence_type", "evidence_name", "evidence_status", "evidence_detail",
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
        ]);
      }
    }
  }
  const csv = rows.map((r) => r.map(csvCell).join(",")).join("\n");
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
  const navigate = useNavigate();
  const [study, setStudy] = useState(null);
  const [functions, setFunctions] = useState([]);
  const [options, setOptions] = useState(null);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [editTarget, setEditTarget] = useState(null); // { fnId, failId, mode }

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
      const fresh = await putRcmTree(id, functions);
      setStudy(fresh);
      setFunctions(fresh.functions || []);
      setDirty(false);
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
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
      <header>
        <div>
          <div className="crumb">
            <button className="crumb-link" onClick={() => navigate("/rcm")}>RCM</button> /{" "}
            <button className="crumb-link" onClick={() => navigate("/rcm/studies")}>Studies</button> /{" "}
            <b>{study.name}</b>
          </div>
          <h1>
            {study.name}
            {study.is_sample && <span className="sample-tag">Sample</span>}
            {study.shared_by && <span className="sample-tag shared" title={`Shared by ${study.shared_by}`}>Shared</span>}
            {dirty && <span className="dirty-tag">unsaved</span>}
          </h1>
          {(study.system || study.description) && (
            <p>{[study.system, study.description].filter(Boolean).join(" — ")}</p>
          )}
          <RollupBadges rollup={study.rollup} />
        </div>
        <div className="head-actions">
          <ShareButton
            collection="rcm_studies"
            artifactId={study.id}
            name={study.name}
            readOnly={readOnly}
          />
          {!readOnly && (
            <button className="secondary" onClick={onRename}>Rename</button>
          )}
          <button className="secondary" onClick={() => exportCsv(study, functions)}>
            Export CSV
          </button>
          {!readOnly && (
            <button onClick={onSave} disabled={saving || !dirty}>
              {saving ? "Saving…" : dirty ? "Save study" : "Saved"}
            </button>
          )}
        </div>
      </header>

      {error && <div className="card error">{error}</div>}
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
