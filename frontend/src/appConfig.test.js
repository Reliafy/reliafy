import test from "node:test";
import assert from "node:assert/strict";
import { DEFAULT_CONFIG, settledConfig, unmatchedRoute } from "./appConfig.js";

test("unknown paths wait for the config instead of redirecting", () => {
  // A direct load of /billing: billing isn't registered yet, so don't redirect.
  assert.equal(unmatchedRoute(DEFAULT_CONFIG), "wait");
  assert.equal(DEFAULT_CONFIG.billing, false);
});

test("once the config has loaded, unknown paths redirect", () => {
  const cfg = settledConfig({ auth: true, ai: false, billing: true, reliability_agent: false });
  assert.equal(cfg.billing, true);
  assert.equal(unmatchedRoute(cfg), "redirect");
});

test("a failed config fetch still settles, with the safe defaults", () => {
  const cfg = settledConfig(null);
  assert.equal(cfg.loaded, true);
  assert.equal(cfg.billing, false);
  assert.equal(unmatchedRoute(cfg), "redirect");
});

test("the MCP connector counts as on until the server says it's off", () => {
  assert.equal(DEFAULT_CONFIG.mcp, true);
  assert.equal(settledConfig(null).mcp, true);
  assert.equal(settledConfig({ mcp: false }).mcp, false);
});

test("unknown paths also wait for the list of extension pages", () => {
  const cfg = settledConfig({ auth: true });
  assert.equal(unmatchedRoute(cfg, false), "wait");
  assert.equal(unmatchedRoute(cfg, true), "redirect");
});
