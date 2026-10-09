// Deployment capabilities from the public /api/config endpoint, as plain
// functions so the routing rule can be tested without React.

// Defaults hide the optional features (AI assistant, billing) so a self-hosted
// build never flashes affordances that can't work there; on cloud they appear
// as soon as the fetch resolves. `loaded` is false until it has (or has
// finally failed).
export const DEFAULT_CONFIG = { auth: true, ai: false, billing: false, reliability_agent: false, loaded: false };

// The config once the fetch has settled: the server's flags over the
// defaults, or the defaults alone when it failed.
export function settledConfig(fetched) {
  return { ...DEFAULT_CONFIG, ...(fetched || {}), loaded: true };
}

// What the app shell does with a path no route matched. Routes gated on the
// config (/billing, /agent) aren't registered until it loads, so redirecting
// before then would send a direct load of /billing to /modelling.
export function unmatchedRoute(config) {
  return config.loaded ? "redirect" : "wait";
}
