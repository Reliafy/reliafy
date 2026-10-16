import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { dismissRolesOffer, getMaintenanceAccess, getMyRoles, setMyRoles } from "./api.js";
import { useAppConfig } from "./ConfigProvider.jsx";
import { buildMenu } from "./navigation.js";

const RolesContext = createContext({
  roles: [],
  loaded: false,
  offer: false,
  saveRoles: () => Promise.resolve(),
  dismissOffer: () => Promise.resolve(),
  has: {},
  menu: { main: [], more: [] },
});

// The user's roles (#438), saved on their profile, and the menu they make:
// shared by the sidebar, Home, the Maintenance tabs and the Settings picker.
// `has` is what this workspace has (navigation.js `needs`).
export function RolesProvider({ children }) {
  const [state, setState] = useState({ roles: [], offer: false, loaded: false });
  useEffect(() => {
    let alive = true;
    getMyRoles()
      .then((d) => alive && setState({ roles: d.roles || [], offer: !!d.offer, loaded: true }))
      .catch(() => alive && setState({ roles: [], offer: false, loaded: true }));
    return () => {
      alive = false;
    };
  }, []);

  const { reliability_agent: agentEnabled, maintenance: maintenanceEnabled } = useAppConfig();
  const [maintenanceAllowed, setMaintenanceAllowed] = useState(false);
  useEffect(() => {
    if (!maintenanceEnabled) return;
    getMaintenanceAccess().then((a) => setMaintenanceAllowed(!!a.allowed));
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
    const has = { maintenance: !!(maintenanceEnabled && maintenanceAllowed), agent: !!agentEnabled };
    return { ...state, saveRoles, dismissOffer, has, menu: buildMenu({ roles: state.roles, has }) };
  }, [state, saveRoles, dismissOffer, maintenanceEnabled, maintenanceAllowed, agentEnabled]);
  return <RolesContext.Provider value={value}>{children}</RolesContext.Provider>;
}

export function useRoles() {
  return useContext(RolesContext);
}
