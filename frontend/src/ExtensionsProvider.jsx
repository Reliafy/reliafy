import { createContext, useContext, useEffect, useState } from "react";
import { getExtensionMounts } from "./api.js";
import { useAuth } from "./AuthProvider.jsx";

// The pages optional extensions add that this user may see (extensions.js),
// fetched once per signed-in user. `loaded` is false until the list has
// arrived (or failed: then there are none), so the shell can wait before
// treating an extension page's URL as unknown.
const ExtensionsContext = createContext({ mounts: [], loaded: false });

export function ExtensionsProvider({ children }) {
  const { user } = useAuth();
  const uid = user?.uid || null;
  const [state, setState] = useState({ mounts: [], loaded: false });

  useEffect(() => {
    let alive = true;
    setState({ mounts: [], loaded: false });
    if (!uid) {
      setState({ mounts: [], loaded: true });
      return undefined;
    }
    getExtensionMounts()
      .then((d) => alive && setState({ mounts: Array.isArray(d?.mounts) ? d.mounts : [], loaded: true }))
      .catch(() => alive && setState({ mounts: [], loaded: true }));
    return () => {
      alive = false;
    };
  }, [uid]);

  return <ExtensionsContext.Provider value={state}>{children}</ExtensionsContext.Provider>;
}

export function useExtensions() {
  return useContext(ExtensionsContext);
}
