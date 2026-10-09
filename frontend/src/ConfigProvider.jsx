import { createContext, useContext, useEffect, useState } from "react";
import { getAppConfig } from "./api.js";
import { DEFAULT_CONFIG, settledConfig } from "./appConfig.js";

// Deployment capabilities, fetched once from the public /api/config endpoint
// (defaults and the `loaded` flag: appConfig.js).
const ConfigContext = createContext(DEFAULT_CONFIG);

export function ConfigProvider({ children }) {
  const [config, setConfig] = useState(DEFAULT_CONFIG);

  useEffect(() => {
    let cancelled = false;
    const load = (retry) =>
      getAppConfig()
        .then((c) => { if (!cancelled) setConfig(settledConfig(c)); })
        .catch(() => {
          if (cancelled) return;
          // One retry; after that settle on the defaults so routing unblocks.
          if (retry) setTimeout(() => load(false), 1500);
          else setConfig(settledConfig(null));
        });
    load(true);
    return () => { cancelled = true; };
  }, []);

  return <ConfigContext.Provider value={config}>{children}</ConfigContext.Provider>;
}

export function useAppConfig() {
  return useContext(ConfigContext);
}
