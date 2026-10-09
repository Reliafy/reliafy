import { useCallback, useEffect, useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import Modal from "../components/Modal.jsx";
import RcmImportModal from "../components/RcmImportModal.jsx";
import { RollupBadges } from "../components/RcmStatusBadge.jsx";
import { listRcmStudies, createRcmStudy, deleteRcmStudy } from "../api.js";
import ListSearch, { matches } from "../components/ListSearch.jsx";
import { relativeTime } from "../instrument.js";
import Chip from "../components/ui/Chip.jsx";
import PageHeader from "../components/ui/PageHeader.jsx";
import { PlusIcon, RowActions, SampleGroups, itemName } from "../components/LibRows.jsx";

const ImportIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 3v12M7 10l5 5 5-5M5 21h14" />
  </svg>
);

// RCM studies list: rollup badge strip per study, create modal, free-plan cap
// nudge on 402.
export default function RcmHome() {
  const navigate = useNavigate();
  const [studies, setStudies] = useState(null);
  const [query, setQuery] = useState("");
  const [error, setError] = useState(null);
  const [capHit, setCapHit] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [name, setName] = useState("");
  const [system, setSystem] = useState("");
  const [description, setDescription] = useState("");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState(null);
  const [importOpen, setImportOpen] = useState(false);

  const refresh = useCallback(() => {
    listRcmStudies()
      .then((d) => setStudies(d.studies || []))
      .catch((e) => setError(e.message));
  }, []);
  useEffect(() => refresh(), [refresh]);

  const onCreate = async () => {
    if (!name.trim()) return;
    setCreating(true);
    setCreateError(null);
    try {
      const study = await createRcmStudy(name.trim(), system.trim(), description.trim());
      navigate(`/rcm/studies/${study.id}`);
    } catch (err) {
      if (err.code === "cap") {
        setModalOpen(false);
        setCapHit(true);
      } else {
        setCreateError(err.message);
      }
    } finally {
      setCreating(false);
    }
  };

  const onDelete = async (s) => {
    const msg = s.is_sample
      ? `Remove the sample “${itemName(s)}” from your workspace? It stays available to other users and you won't see it again.`
      : `Delete study “${s.name}”?`;
    if (!window.confirm(msg)) return;
    try {
      await deleteRcmStudy(s.id);
      refresh();
    } catch (err) {
      setError(err.message);
    }
  };

  const open = (id) => navigate(`/rcm/studies/${id}`);
  const visible = (studies || []).filter((s) => matches(query, s.name, s.system, s.id));

  return (
    <div className="app">
      <PageHeader
        title="RCM studies"
        meta="Every maintenance decision links to the analysis behind it, re-checked each time you open the study."
        actions={
          <button className="secondary" onClick={() => setImportOpen(true)}
                  title="Create a study from an FMEA / RCM worksheet in Excel">
            <ImportIcon /> Import from Excel
          </button>
        }
        primary={<button onClick={() => { setCreateError(null); setModalOpen(true); }}><PlusIcon /> New study</button>}
      />

      {error && <div className="card error">{error}</div>}
      {capHit && (
        <div className="card upgrade-nudge">
          <p>
            You've reached the free-plan limit of 1 RCM study.{" "}
            <Link to="/billing">Upgrade to Pro</Link> for unlimited studies.
          </p>
        </div>
      )}

      {studies === null ? (
        <div className="card empty">Loading…</div>
      ) : studies.length === 0 ? (
        <div className="card empty">
          <h2>No RCM studies</h2>
          <p>Create one and build the function → failure → mode worksheet.</p>
          <button style={{ marginTop: "1rem" }} onClick={() => setModalOpen(true)}>
            <PlusIcon /> New study
          </button>
        </div>
      ) : (
        <>
          <div className="tablebar">
            <span className="count">{visible.length} of {studies.length} studies</span>
            <span className="grow" />
            <ListSearch value={query} onChange={setQuery} placeholder="Search studies…" />
          </div>
          <div className="lib">
            <table className="lib-table">
              <thead>
                <tr>
                  <th style={{ width: "34%" }}>Study</th>
                  <th className="lib-opt">System</th>
                  <th>Evidence</th>
                  <th className="lib-opt">Updated</th>
                  <th><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                <SampleGroups rows={visible} cols={5} render={(s) => (
                  <tr key={s.id} className="lib-row" onClick={() => open(s.id)}>
                    <td>
                      <div className="lib-name">
                        {itemName(s)}
                        {s.shared_by && <Chip title={`Shared by ${s.shared_by}`}>Shared</Chip>}
                      </div>
                    </td>
                    <td className="lib-date lib-opt">{s.system || "—"}</td>
                    <td>
                      {s.rollup?.decided ? (
                        <RollupBadges rollup={s.rollup} />
                      ) : (
                        <span className="lib-date">{s.rollup?.modes ? `${s.rollup.modes} modes` : "Empty"}</span>
                      )}
                    </td>
                    <td className="lib-date lib-opt">{relativeTime(s.updated_at || s.created_at)}</td>
                    <RowActions item={s} onOpen={() => open(s.id)} onDelete={() => onDelete(s)} />
                  </tr>
                )} />
              </tbody>
            </table>
          </div>
        </>
      )}

      {importOpen && (
        <RcmImportModal
          onClose={() => setImportOpen(false)}
          onImported={(study) => navigate(`/rcm/studies/${study.id}`)}
        />
      )}

      {modalOpen && (
        <Modal
          title="New RCM study"
          locked={creating}
          onClose={() => setModalOpen(false)}
          footer={
            <>
              <button className="secondary" onClick={() => setModalOpen(false)} disabled={creating}>
                Cancel
              </button>
              <button onClick={onCreate} disabled={creating || !name.trim()}>
                {creating ? "Creating…" : "Create study"}
              </button>
            </>
          }
        >
          {createError && <div className="card error">{createError}</div>}
          <div className="rcm-form">
            <label className="login-field">
              <span>Name</span>
              <input
                type="text"
                autoFocus
                value={name}
                placeholder="e.g. Conveyor line 2 — RCM"
                onChange={(e) => setName(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && onCreate()}
              />
            </label>
            <label className="login-field">
              <span>System (optional)</span>
              <input
                type="text"
                value={system}
                placeholder="e.g. Conveyor line 2"
                onChange={(e) => setSystem(e.target.value)}
              />
            </label>
            <label className="login-field">
              <span>Description (optional)</span>
              <textarea
                rows={2}
                value={description}
                placeholder="Scope, operating context, assumptions"
                onChange={(e) => setDescription(e.target.value)}
              />
            </label>
          </div>
        </Modal>
      )}
    </div>
  );
}
