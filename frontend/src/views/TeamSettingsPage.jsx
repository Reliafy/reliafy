import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../AuthProvider.jsx";
import { useWorkspace } from "../WorkspaceProvider.jsx";
import {
  getTeam,
  renameTeam,
  deleteTeam,
  inviteTeamMember,
  removeTeamMember,
  removeTeamInvite,
  leaveTeam,
} from "../api.js";
import Modal from "../components/Modal.jsx";

const TrashIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M4 7h16M9 7V5h6v2M7 7l1 13h8l1-13" />
  </svg>
);

// Settings for the active team workspace: members, invites, rename,
// leave/delete. Only reachable while a team workspace is selected.
export default function TeamSettingsPage() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const { workspace, setWorkspaceId, refreshTeams } = useWorkspace();
  const [team, setTeam] = useState(null);
  const [error, setError] = useState(null);
  const [email, setEmail] = useState("");
  const [inviting, setInviting] = useState(false);
  const [inviteNote, setInviteNote] = useState(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleteName, setDeleteName] = useState("");
  const [deleting, setDeleting] = useState(false);

  const refresh = useCallback(() => {
    if (workspace === "personal") return;
    getTeam(workspace)
      .then(setTeam)
      .catch((e) => setError(e.message));
  }, [workspace]);
  useEffect(() => refresh(), [refresh]);

  if (workspace === "personal") {
    return (
      <div className="app">
        <header><h1>Team settings</h1></header>
        <div className="card empty">
          <p>Switch to a team workspace (sidebar, top left) to manage it.</p>
        </div>
      </div>
    );
  }
  if (error && !team) return <div className="app"><div className="card error">{error}</div></div>;
  if (!team) return <div className="app"><div className="card empty">Loading…</div></div>;

  const isOwner = team.role === "owner";

  const onInvite = async () => {
    if (!email.trim()) return;
    setInviting(true);
    setError(null);
    setInviteNote(null);
    try {
      const result = await inviteTeamMember(team.id, email.trim());
      setInviteNote(
        result.status === "added"
          ? `${email.trim()} added to the team.`
          : `${email.trim()} doesn't have an account yet — they'll join automatically when they sign up.`
      );
      setEmail("");
      refresh();
      refreshTeams();
    } catch (err) {
      setError(err.message);
    } finally {
      setInviting(false);
    }
  };

  const onRename = async () => {
    const name = window.prompt("Team name", team.name);
    if (!name || !name.trim() || name.trim() === team.name) return;
    try {
      await renameTeam(team.id, name.trim());
      refresh();
      refreshTeams();
    } catch (err) {
      setError(err.message);
    }
  };

  const onRemoveMember = async (m) => {
    if (!window.confirm(`Remove ${m.email || m.name} from the team?`)) return;
    try {
      await removeTeamMember(team.id, m.uid);
      refresh();
    } catch (err) {
      setError(err.message);
    }
  };

  const onLeave = async () => {
    if (!window.confirm("Leave this team? You'll lose access to its workspace.")) return;
    try {
      await leaveTeam(team.id);
      setWorkspaceId("personal");
      refreshTeams();
      navigate("/modelling");
    } catch (err) {
      setError(err.message);
    }
  };

  const onDelete = async () => {
    setDeleting(true);
    try {
      await deleteTeam(team.id);
      setWorkspaceId("personal");
      refreshTeams();
      navigate("/modelling");
    } catch (err) {
      setError(err.message);
      setDeleting(false);
      setConfirmDelete(false);
    }
  };

  return (
    <div className="app">
      <header>
        <div>
          <div className="crumb"><b>Team settings</b></div>
          <h1>{team.name}</h1>
          <p>
            {team.members.length} member{team.members.length === 1 ? "" : "s"} — everyone
            can view and edit everything in this workspace.
          </p>
          {team.frozen && (
            <p className="muted-line" style={{ color: "#9a6b0c" }}>
              The team owner's Pro plan has lapsed — the workspace is read-only until it's renewed.
            </p>
          )}
        </div>
        <div className="head-actions">
          {isOwner && <button className="secondary" onClick={onRename}>Rename</button>}
          {isOwner ? (
            <button className="secondary danger" onClick={() => { setDeleteName(""); setConfirmDelete(true); }}>
              Delete team
            </button>
          ) : (
            <button className="secondary danger" onClick={onLeave}>Leave team</button>
          )}
        </div>
      </header>

      {error && <div className="card error">{error}</div>}

      <div className="card">
        <div className="bill-head">
          <h2 style={{ margin: 0 }}>Members</h2>
        </div>
        {isOwner && (
          <div className="row" style={{ gap: "0.6rem", alignItems: "flex-end", marginBottom: "0.6rem" }}>
            <label className="login-field" style={{ flex: 1, maxWidth: 420 }}>
              <span>Invite by email</span>
              <input
                type="email"
                value={email}
                placeholder="colleague@company.com"
                onChange={(e) => setEmail(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && onInvite()}
              />
            </label>
            <button onClick={onInvite} disabled={inviting || !email.trim()}>
              {inviting ? "Inviting…" : "Invite"}
            </button>
          </div>
        )}
        {inviteNote && <p className="muted-line">{inviteNote}</p>}

        <table className="lib-table">
          <thead>
            <tr>
              <th>Member</th>
              <th>Email</th>
              <th style={{ width: 100 }}>Role</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {team.members.map((m) => (
              <tr key={m.uid} className="lib-row">
                <td><div className="lib-name">{m.name || "—"}{m.uid === user?.uid ? " (you)" : ""}</div></td>
                <td className="lib-date">{m.email || "—"}</td>
                <td className="lib-date">{m.role}</td>
                <td className="lib-actions">
                  {isOwner && m.role !== "owner" && (
                    <div className="lib-acts">
                      <button className="act del" title="Remove member" onClick={() => onRemoveMember(m)}>
                        <TrashIcon />
                      </button>
                    </div>
                  )}
                </td>
              </tr>
            ))}
            {team.invites.map((i) => (
              <tr key={i.email} className="lib-row">
                <td><div className="lib-name" style={{ fontStyle: "italic" }}>Invited</div></td>
                <td className="lib-date">{i.email}</td>
                <td className="lib-date">pending</td>
                <td className="lib-actions">
                  {isOwner && (
                    <div className="lib-acts">
                      <button
                        className="act del"
                        title="Cancel invite"
                        onClick={() => removeTeamInvite(team.id, i.email).then(refresh)}
                      >
                        <TrashIcon />
                      </button>
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {confirmDelete && (
        <Modal
          title="Delete team?"
          className="modal-sm"
          locked={deleting}
          onClose={() => setConfirmDelete(false)}
          footer={
            <div style={{ display: "flex", gap: "0.6rem", marginLeft: "auto" }}>
              <button className="secondary" onClick={() => setConfirmDelete(false)} disabled={deleting}>
                Cancel
              </button>
              <button onClick={onDelete} disabled={deleting || deleteName !== team.name}>
                {deleting ? "Deleting…" : "Delete everything"}
              </button>
            </div>
          }
        >
          <p className="muted-line" style={{ marginTop: 0 }}>
            This permanently deletes the team and <b>every artifact in its
            workspace</b> — datasets, models, RBDs, degradation models, tracked
            items, analyses, and RCM studies — for all members. This can't be
            undone.
          </p>
          <label className="login-field">
            <span>Type the team name to confirm</span>
            <input
              type="text"
              value={deleteName}
              placeholder={team.name}
              onChange={(e) => setDeleteName(e.target.value)}
            />
          </label>
        </Modal>
      )}
    </div>
  );
}
