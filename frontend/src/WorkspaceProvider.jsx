import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { useAuth } from "./AuthProvider.jsx";
import { getWorkspace, setWorkspace as persistWorkspace, listTeams, listTeamInvites } from "./api.js";

const WorkspaceContext = createContext({
  workspace: "personal",
  setWorkspaceId: () => {},
  teams: [],
  activeTeam: null,
  refreshTeams: () => {},
  invites: [],
  refreshInvites: () => {},
});

// Active workspace (Personal or a team) + the user's team list. The chosen
// workspace persists in localStorage (via api.js, which also stamps it on
// every request) and is validated against the team list on load so a stale
// id can't strand the user in a 403ing workspace.
export function WorkspaceProvider({ children }) {
  const { user } = useAuth();
  const [workspace, setWorkspaceState] = useState(getWorkspace());
  // null = not fetched yet; [] = fetched, no teams. The distinction matters:
  // a stored workspace must be dropped even when the user has NO teams left
  // (e.g. the team was deleted, or a fresh local database forgot it).
  const [teams, setTeams] = useState(null);

  // Resolves once the list is in, so a caller can switch to a team it just
  // created (switching first would be undone by the check below).
  const refreshTeams = useCallback(() => {
    if (!user) return Promise.resolve();
    return listTeams()
      .then((d) => setTeams(d.teams || []))
      .catch(() => setTeams([]));
  }, [user]);
  useEffect(() => {
    refreshTeams();
  }, [refreshTeams]);

  // Team invitations waiting for this user's answer (accept or decline).
  const [invites, setInvites] = useState([]);
  const refreshInvites = useCallback(() => {
    if (!user) return Promise.resolve();
    return listTeamInvites()
      .then((d) => setInvites(d.invites || []))
      .catch(() => setInvites([]));
  }, [user]);
  useEffect(() => {
    refreshInvites();
  }, [refreshInvites]);

  // Drop a stored workspace the user no longer belongs to.
  useEffect(() => {
    if (!user || teams === null || workspace === "personal") return;
    if (!teams.some((t) => t.id === workspace)) {
      persistWorkspace("personal");
      setWorkspaceState("personal");
    }
  }, [user, teams, workspace]);

  const setWorkspaceId = useCallback((id) => {
    persistWorkspace(id);
    setWorkspaceState(id || "personal");
  }, []);

  const value = useMemo(() => ({
    workspace,
    setWorkspaceId,
    teams: teams || [],
    activeTeam: (teams || []).find((t) => t.id === workspace) || null,
    refreshTeams,
    invites,
    refreshInvites,
  }), [workspace, setWorkspaceId, teams, refreshTeams, invites, refreshInvites]);

  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}

export function useWorkspace() {
  return useContext(WorkspaceContext);
}
