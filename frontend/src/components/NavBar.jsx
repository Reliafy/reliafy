import { useState } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import Logo from "./Logo.jsx";
import Modal from "./Modal.jsx";
import { useWorkspace } from "../WorkspaceProvider.jsx";
import { createTeam } from "../api.js";

// Instrument top bar: cobalt mark + wordmark on the left, the workspace
// (Personal/team) selector on the right. Section navigation lives in the
// sidebar.
const GearIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <circle cx="12" cy="12" r="3.2" />
    <path d="M19.4 15a1.7 1.7 0 0 0 .34 1.87l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.7 1.7 0 0 0-1.87-.34 1.7 1.7 0 0 0-1.03 1.56V21a2 2 0 1 1-4 0v-.09A1.7 1.7 0 0 0 8.98 19.3a1.7 1.7 0 0 0-1.87.34l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.7 1.7 0 0 0 .34-1.87 1.7 1.7 0 0 0-1.56-1.03H3a2 2 0 1 1 0-4h.09A1.7 1.7 0 0 0 4.7 8.98a1.7 1.7 0 0 0-.34-1.87l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.7 1.7 0 0 0 1.87.34H9a1.7 1.7 0 0 0 1.03-1.56V3a2 2 0 1 1 4 0v.09c0 .68.4 1.3 1.03 1.56a1.7 1.7 0 0 0 1.87-.34l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.7 1.7 0 0 0-.34 1.87V9c.26.63.88 1.03 1.56 1.03H21a2 2 0 1 1 0 4h-.09c-.68 0-1.3.4-1.51.97Z" />
  </svg>
);

// Modal to create a team. Pro-gating happens server-side: a 402 shows an
// upgrade nudge instead of the generic error.
function CreateTeamModal({ onClose, onCreated }) {
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [needsPro, setNeedsPro] = useState(false);

  const onCreate = async () => {
    if (!name.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const team = await createTeam(name.trim());
      onCreated(team);
    } catch (err) {
      if (err.code === "pro_required") setNeedsPro(true);
      else setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      title="New team"
      className="modal-sm"
      locked={busy}
      onClose={onClose}
      footer={
        <div style={{ display: "flex", gap: "0.6rem", marginLeft: "auto" }}>
          <button className="secondary" onClick={onClose} disabled={busy}>Cancel</button>
          {needsPro ? (
            <button onClick={() => { onClose(); navigate("/billing"); }}>Upgrade to Pro</button>
          ) : (
            <button onClick={onCreate} disabled={busy || !name.trim()}>
              {busy ? "Creating…" : "Create team"}
            </button>
          )}
        </div>
      }
    >
      {needsPro ? (
        <p className="muted-line" style={{ margin: 0 }}>
          Teams are a Pro feature: creating a team and editing in its
          workspace need a Pro plan. Free accounts can join and view
          everything.
        </p>
      ) : (
        <>
          <label className="login-field">
            <span>Team name</span>
            <input
              type="text"
              autoFocus
              value={name}
              placeholder="e.g. Reliability squad"
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && onCreate()}
            />
          </label>
          <p className="muted-line">
            Everyone you invite can view everything in the team workspace —
            editing needs their own Pro plan. Your personal workspace stays
            private.
          </p>
          {error && <div className="error">{error}</div>}
        </>
      )}
    </Modal>
  );
}

export default function NavBar() {
  const { workspace, setWorkspaceId, teams, activeTeam, refreshTeams } = useWorkspace();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const [creatingTeam, setCreatingTeam] = useState(false);

  const onSwitch = (value) => {
    if (value === "__create__") {
      setCreatingTeam(true);
      return;
    }
    setWorkspaceId(value);
    if (pathname === "/team" && value === "personal") navigate("/modelling");
  };

  return (
    <nav className="navbar">
      <div className="navbar-inner">
        <NavLink className="brand" to="/modelling">
          <Logo size={30} />
          <span className="brand-name">Reliafy</span>
        </NavLink>
        <div className="nav-workspace">
          {activeTeam && (activeTeam.frozen || activeTeam.can_edit === false) && (
            <span
              className="health-badge health-amber"
              title={activeTeam.frozen
                ? "The team owner's Pro plan has lapsed — the workspace is read-only until it's renewed."
                : "You can view everything in this team. Editing needs a Pro plan."}
            >
              view-only
            </span>
          )}
          <select
            value={workspace}
            onChange={(e) => onSwitch(e.target.value)}
            title="Active workspace"
          >
            <option value="personal">Personal</option>
            {teams.map((t) => (
              <option key={t.id} value={t.id}>{t.name}</option>
            ))}
            <option value="__create__">＋ New team…</option>
          </select>
          {activeTeam && (
            <NavLink
              to="/team"
              className={({ isActive }) => "nav-team-settings" + (isActive ? " active" : "")}
              title="Team settings"
            >
              <GearIcon />
            </NavLink>
          )}
        </div>
      </div>

      {creatingTeam && (
        <CreateTeamModal
          onClose={() => setCreatingTeam(false)}
          onCreated={(team) => {
            setCreatingTeam(false);
            refreshTeams();
            setWorkspaceId(team.id);
            navigate("/team");
          }}
        />
      )}
    </nav>
  );
}
