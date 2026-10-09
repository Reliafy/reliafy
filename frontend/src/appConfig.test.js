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
