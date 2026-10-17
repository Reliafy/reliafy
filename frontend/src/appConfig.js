// Deployment capabilities from the public /api/config endpoint, as plain
// functions so the routing rule can be tested without React.

// Defaults hide the optional features (AI assistant, billing) so a self-hosted
// build never flashes affordances that can't work there; on cloud they appear
// as soon as the fetch resolves. `loaded` is false until it has (or has
// finally failed). `mcp` is the MCP connector's switch: on unless the server
// says it's off (it's on for every self-hosted install by default).
export const DEFAULT_CONFIG = {
  auth: true, ai: false, billing: false, reliability_agent: false, mcp: true, loaded: false,
};

// Who to ask for the MCP connector while it's switched off.
export const MCP_CONTACT = "hello@reliafy.com";

// The config once the fetch has settled: the server's flags over the
// defaults, or the defaults alone when it failed.
export function settledConfig(fetched) {
  return { ...DEFAULT_CONFIG, ...(fetched || {}), loaded: true };
}

// What the app shell does with a path no route matched. Routes gated on the
// config (/billing, /agent) aren't registered until it loads, nor extension
// pages until their list has (`extensionsLoaded`), so redirecting before then
// would send a direct load of /billing to /modelling.
export function unmatchedRoute(config, extensionsLoaded = true) {
  return config.loaded && extensionsLoaded ? "redirect" : "wait";
}
