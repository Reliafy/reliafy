import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../AuthProvider.jsx";
import { useWorkspace } from "../WorkspaceProvider.jsx";
import {
  getTeam,
  renameTeam,
  setTeamTimeZone,
  deleteTeam,
  inviteTeamMember,
  removeTeamMember,
  removeTeamInvite,
  leaveTeam,
} from "../api.js";
import Modal from "../components/Modal.jsx";
import TeamInvites from "../components/TeamInvites.jsx";
import TimeZonePicker from "../components/TimeZonePicker.jsx";
import { CreateTeamModal } from "../components/NavBar.jsx";
import Button from "../components/ui/Button.jsx";
import Chip from "../components/ui/Chip.jsx";
import Card, { CardHeader } from "../components/ui/Card.jsx";
import PageHeader from "../components/ui/PageHeader.jsx";
import { useAskText, useConfirm } from "../components/ConfirmProvider.jsx";
import { changedText, renamePrompt } from "../confirm.js";

const TrashIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M4 7h16M9 7V5h6v2M7 7l1 13h8l1-13" />
  </svg>
);

const CRUMBS = [{ label: "Settings", to: "/settings" }];

// /team in the personal workspace: switch to a team, or create one.
function NoTeam() {
  const { teams, setWorkspaceId, refreshTeams } = useWorkspace();
  const [creating, setCreating] = useState(false);
  return (
    <div className="app">
      <PageHeader crumbs={CRUMBS} title="Team" />
      <TeamInvites style={{ marginBottom: "1rem" }} />
      <Card className="team-empty">
        {teams.length === 0 ? (
          <p>No team yet. A team shares one workspace: everyone sees everything in it.</p>
        ) : (
          <>
            <p>You're in your personal workspace. Switch to a team to manage it.</p>
            <div className="row team-switch">
              {teams.map((t) => (
                <Button key={t.id} variant="secondary" onClick={() => setWorkspaceId(t.id)}>{t.name}</Button>
              ))}
            </div>
          </>
        )}
        <Button variant={teams.length === 0 ? "primary" : "link"} onClick={() => setCreating(true)}>
          Create a team
        </Button>
      </Card>
      {creating && (
        <CreateTeamModal
          onClose={() => setCreating(false)}
          onCreated={(team) => {
            setCreating(false);
            refreshTeams().then(() => setWorkspaceId(team.id));
          }}
        />
      )}
    </div>
  );
}

// Settings for the active team workspace: members, invites, rename,
// leave/delete. In the personal workspace, a way to a team instead.
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
  const confirm = useConfirm();
  const askText = useAskText();

  if (workspace === "personal") return <NoTeam />;
  if (error && !team) return <div className="app"><div className="card error">{error}</div></div>;
  if (!team) return <div className="app"><div className="card empty">Loading…</div></div>;

  const isOwner = team.role === "owner";

  const onInvite = async () => {
    if (!email.trim()) return;
    setInviting(true);
    setError(null);
    setInviteNote(null);
    try {
      await inviteTeamMember(team.id, email.trim());
      setInviteNote(
        `Invitation sent to ${email.trim()}. They join the team when they accept it, ` +
        "signed in to Reliafy with that address (or once they create an account with it)."
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
    const name = changedText(await askText(renamePrompt({ kind: "team", name: team.name })), team.name);
    if (!name) return;
    try {
      await renameTeam(team.id, name);
      refresh();
      refreshTeams();
    } catch (err) {
      setError(err.message);
    }
  };

  const onRemoveMember = async (m) => {
    if (!(await confirm({ title: "Remove from the team?", body: `${m.email || m.name} loses access to this team's workspace straight away. You can invite them again later.`, confirmLabel: "Remove member" }))) return;
    try {
      await removeTeamMember(team.id, m.uid);
      refresh();
    } catch (err) {
      setError(err.message);
    }
  };

  const onLeave = async () => {
    if (!(await confirm({ title: "Leave this team?", body: "You lose access to its workspace. Someone in the team has to invite you again to get back in.", confirmLabel: "Leave team" }))) return;
    try {
      await leaveTeam(team.id);
      setWorkspaceId("personal");
      refreshTeams();
      navigate("/home");
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
      navigate("/home");
    } catch (err) {
      setError(err.message);
      setDeleting(false);
      setConfirmDelete(false);
    }
  };

  return (
    <div className="app">
      <PageHeader
        crumbs={CRUMBS}
        title={team.name}
        meta={`${team.members.length} member${team.members.length === 1 ? "" : "s"} · everyone sees everything in this workspace; editing needs a Pro plan`}
        actions={isOwner && <Button variant="secondary" onClick={onRename}>Rename</Button>}
        menu={isOwner ? (
          <button className="ovm-item danger" onClick={() => { setDeleteName(""); setConfirmDelete(true); }}>
            Delete team
          </button>
        ) : (
          <button className="ovm-item danger" onClick={onLeave}>Leave team</button>
        )}
      >
        {team.frozen && (
          <p className="muted-line warn">
            The team owner's Pro plan has lapsed — the workspace is read-only until it's renewed.
          </p>
        )}
      </PageHeader>

      {error && <div className="card error">{error}</div>}

      <div className="card">
        <CardHeader title="Members" />
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
                <td className="lib-date">
                  {m.role}
                  {m.can_edit === false && (
                    <Chip style={{ marginLeft: 8 }} title="Free account — can view the workspace; editing needs Pro.">
                      View only
                    </Chip>
                  )}
                </td>
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
                <td className="lib-date">
                  <Chip title="They join when they accept the invitation.">Pending</Chip>
                </td>
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

      <div className="card" style={{ marginTop: "1rem" }}>
        <CardHeader
          title="Time zone"
          subtitle="Where the team's workspace is. Today, due dates and overdue follow its calendar for everyone in the team; not set, they follow UTC."
        />
        <TimeZonePicker
          value={team.time_zone}
          readOnly={!isOwner}
          onSave={(zone) => setTeamTimeZone(team.id, zone).then(() => { refresh(); refreshTeams(); })}
        />
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
            items, analyses and forecasts — for all members. This can't be
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
