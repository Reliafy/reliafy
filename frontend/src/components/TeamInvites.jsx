import { useState } from "react";
import { useWorkspace } from "../WorkspaceProvider.jsx";
import { acceptTeamInvite, declineTeamInvite } from "../api.js";
import Button from "./ui/Button.jsx";
import Card, { CardHeader } from "./ui/Card.jsx";

// Team invitations waiting for the signed-in user's answer. Membership starts
// only on Accept; Decline removes the invitation. Renders nothing when there
// are none.
export default function TeamInvites({ style }) {
  const { invites, refreshInvites, refreshTeams, setWorkspaceId } = useWorkspace();
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);
  if (!invites || invites.length === 0) return null;

  const answer = async (invite, accept) => {
    setBusy(invite.team_id);
    setError(null);
    try {
      if (accept) {
        await acceptTeamInvite(invite.team_id);
        await refreshTeams();
        setWorkspaceId(invite.team_id);
      } else {
        await declineTeamInvite(invite.team_id);
      }
      await refreshInvites();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(null);
    }
  };

  return (
    <Card style={style}>
      <CardHeader
        title="Team invitations"
        subtitle="You join a team only if you accept. Everyone in a team sees everything in its workspace."
      />
      {error && <p className="muted-line warn">{error}</p>}
      {invites.map((invite) => (
        <div key={invite.team_id} className="row" style={{ gap: "0.6rem", alignItems: "center", marginBottom: "0.5rem" }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div className="lib-name">{invite.team_name}</div>
            {invite.invited_by && <div className="muted-line">Invited by {invite.invited_by}</div>}
          </div>
          <Button onClick={() => answer(invite, true)} disabled={busy === invite.team_id}>
            Accept
          </Button>
          <Button variant="secondary" onClick={() => answer(invite, false)} disabled={busy === invite.team_id}>
            Decline
          </Button>
        </div>
      ))}
    </Card>
  );
}
