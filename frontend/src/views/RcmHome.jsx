import { useCallback, useEffect, useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import Modal from "../components/Modal.jsx";
import { RollupBadges } from "../components/RcmStatusBadge.jsx";
import { listRcmStudies, createRcmStudy, deleteRcmStudy } from "../api.js";
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
const TrashIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M4 7h16M9 7V5h6v2M7 7l1 13h8l1-13" />
  </svg>
);

// RCM studies list: rollup badge strip per study, create modal, free-plan cap
// nudge on 402.
export default function RcmHome() {
  const navigate = useNavigate();
  const [studies, setStudies] = useState(null);
  const [error, setError] = useState(null);
  const [capHit, setCapHit] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [name, setName] = useState("");
  const [system, setSystem] = useState("");
  const [description, setDescription] = useState("");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState(null);

  const refresh = useCallback(() => {
    listRcmStudies()
      .then((d) => setStudies(d.studies))
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
      ? `Remove the sample “${s.name}” from your workspace? It stays available to other users.`
      : `Delete study “${s.name}”?`;
    if (!window.confirm(msg)) return;
    await deleteRcmStudy(s.id);
    refresh();
  };

  return (
    <div className="app">
      <header>
        <div>
          <div className="crumb">
            <button className="crumb-link" onClick={() => navigate("/rcm")}>RCM</button> / <b>Studies</b>
          </div>
          <h1>RCM studies</h1>
          <p>
            Every maintenance decision links to the analysis that justifies it,
            and the link is re-checked each time you open the study.
          </p>
        </div>
        <button onClick={() => { setCreateError(null); setModalOpen(true); }}>
          <PlusIcon /> New study
        </button>
      </header>

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
        <div className="lib">
          <table className="lib-table">
            <thead>
              <tr>
                <th style={{ width: "30%" }}>Study</th>
                <th>System</th>
                <th>Evidence</th>
                <th>Updated</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {studies.map((s) => (
                <tr key={s.id} className="lib-row" onClick={() => navigate(`/rcm/studies/${s.id}`)}>
                  <td>
                    <div className="lib-name">
                      {s.name}
                      {s.is_sample && <span className="sample-tag">Sample</span>}
                    </div>
                  </td>
                  <td className="lib-date">{s.system || "—"}</td>
                  <td>
                    {s.rollup?.decided ? (
                      <RollupBadges rollup={s.rollup} />
                    ) : (
                      <span className="lib-date">{s.rollup?.modes ? `${s.rollup.modes} modes` : "Empty"}</span>
                    )}
                  </td>
                  <td className="lib-date">{relativeTime(s.updated_at || s.created_at)}</td>
                  <td className="lib-actions">
                    <div className="lib-acts">
                      <button className="act" title="Open" onClick={(e) => { e.stopPropagation(); navigate(`/rcm/studies/${s.id}`); }}>
                        <OpenIcon />
                      </button>
                      <button className="act del" title="Delete" onClick={(e) => { e.stopPropagation(); onDelete(s); }}>
                        <TrashIcon />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
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
