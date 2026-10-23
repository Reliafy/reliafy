import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { useLocation } from "react-router-dom";
import { dismissRolesOffer, getMaintenanceAccess, getMyRoles, setMyRoles } from "./api.js";
import { useAppConfig } from "./ConfigProvider.jsx";
import { useWorkspace } from "./WorkspaceProvider.jsx";
import { buildMenu, crumbsFor, liveEntries } from "./navigation.js";

const RolesContext = createContext({
  roles: [],
  loaded: false,
  offer: false,
  saveRoles: () => Promise.resolve(),
  dismissOffer: () => Promise.resolve(),
  has: {},
  noteUse: () => {},
  live: liveEntries({}),
  menu: { main: liveEntries({}), more: [] },
});

// The user's roles, saved on their profile, and the menu they make: shared by
// the sidebar, section headers, Home and the Settings picker. `has` is what
// this workspace has (navigation.js `needs`); `live` is every entry it has,
// whatever the roles (for breadcrumbs and in-page tabs).
//
// `uses` is what the active workspace has used, for entries it sees only then
// (Risk: tracked items, degradation or condition-and-life models); it comes
// with the roles and is fetched again on a workspace switch. A page that
// makes the first such thing calls `noteUse("risk")` so the entry appears
// without a reload.
export function RolesProvider({ children }) {
  const { workspace } = useWorkspace();
  const [state, setState] = useState({ roles: [], offer: false, loaded: false });
  const [uses, setUses] = useState({});
  useEffect(() => {
    let alive = true;
    getMyRoles()
      .then((d) => {
        if (!alive) return;
        setState({ roles: d.roles || [], offer: !!d.offer, loaded: true });
        setUses(d.uses || {});
      })
      .catch(() => alive && setState({ roles: [], offer: false, loaded: true }));
    return () => {
      alive = false;
    };
  }, [workspace]);
  const noteUse = useCallback((key) => setUses((u) => (u[key] ? u : { ...u, [key]: true })), []);

  const { reliability_agent: agentEnabled, maintenance: maintenanceEnabled, menu_preview: previewOn } = useAppConfig();
  // Reliafy Maintenance is for its operators only: the same check its pages make.
  const [maintenanceAllowed, setMaintenanceAllowed] = useState(false);
  useEffect(() => {
    if (!maintenanceEnabled) return undefined;
    let alive = true;
    getMaintenanceAccess()
      .then((a) => alive && setMaintenanceAllowed(!!a.allowed))
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [maintenanceEnabled]);

  const saveRoles = useCallback(
    (roles) => setMyRoles(roles).then((d) => setState({ roles: d.roles || [], offer: false, loaded: true })),
    [],
  );
  const dismissOffer = useCallback(() => {
    setState((s) => ({ ...s, offer: false }));
    return dismissRolesOffer().catch(() => {});
  }, []);

  const value = useMemo(() => {
    const has = {
      maintenance: !!(maintenanceEnabled && maintenanceAllowed), agent: !!agentEnabled, preview: !!previewOn,
      risk: !!(uses.risk || previewOn),
    };
    return {
      ...state, saveRoles, dismissOffer, has, noteUse,
      live: liveEntries(has),
      menu: buildMenu({ roles: state.roles, has }),
    };
  }, [state, saveRoles, dismissOffer, noteUse, uses, maintenanceEnabled, maintenanceAllowed, agentEnabled, previewOn]);
  return <RolesContext.Provider value={value}>{children}</RolesContext.Provider>;
}

export function useRoles() {
  return useContext(RolesContext);
}

// The breadcrumbs for the page shown: its menu entry, and (`childTo`) the
// entry's child it sits under, each linked; nothing for the entry's own
// landing page. From the live menu, so the labels match it and every link is
// a page this user has.
export function useNavCrumbs(entryId, childTo = null) {
  const { live } = useRoles();
  const { pathname } = useLocation();
  return crumbsFor(live, entryId, pathname, childTo);
}
