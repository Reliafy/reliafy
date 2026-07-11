import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { useAuth } from "./AuthProvider.jsx";
import { getWorkspace, setWorkspace as persistWorkspace, listTeams } from "./api.js";

const WorkspaceContext = createContext({
  workspace: "personal",
  setWorkspaceId: () => {},
  teams: [],
  activeTeam: null,
  refreshTeams: () => {},
});

// Active workspace (Personal or a team) + the user's team list. The chosen
// workspace persists in localStorage (via api.js, which also stamps it on
// every request) and is validated against the team list on load so a stale
// id can't strand the user in a 403ing workspace.
export function WorkspaceProvider({ children }) {
  const { user } = useAuth();
  const [workspace, setWorkspaceState] = useState(getWorkspace());
  const [teams, setTeams] = useState([]);

  const refreshTeams = useCallback(() => {
    if (!user) return;
    listTeams()
      .then((d) => setTeams(d.teams || []))
      .catch(() => setTeams([]));
  }, [user]);
  useEffect(() => refreshTeams(), [refreshTeams]);

  // Drop a stored workspace the user no longer belongs to.
  useEffect(() => {
    if (!user || workspace === "personal" || teams.length === 0) return;
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
    teams,
    activeTeam: teams.find((t) => t.id === workspace) || null,
    refreshTeams,
  }), [workspace, setWorkspaceId, teams, refreshTeams]);

  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}

export function useWorkspace() {
  return useContext(WorkspaceContext);
}
