import { createContext, useContext, useEffect, useState } from "react";
import { getAppConfig } from "./api.js";

// Deployment capabilities, fetched once from the public /api/config endpoint.
// Defaults hide the optional features (AI assistant, billing) so a self-hosted
// build never flashes affordances that can't work there; on cloud they appear
// as soon as the fetch resolves.
const DEFAULT = { auth: true, ai: false, billing: false, reliability_agent: false };

const ConfigContext = createContext(DEFAULT);

export function ConfigProvider({ children }) {
  const [config, setConfig] = useState(DEFAULT);

  useEffect(() => {
    let cancelled = false;
    const load = (retry) =>
      getAppConfig()
        .then((c) => { if (!cancelled) setConfig({ ...DEFAULT, ...c }); })
        .catch(() => { if (!cancelled && retry) setTimeout(() => load(false), 1500); });
    load(true);
    return () => { cancelled = true; };
  }, []);

  return <ConfigContext.Provider value={config}>{children}</ConfigContext.Provider>;
}

export function useAppConfig() {
  return useContext(ConfigContext);
}
