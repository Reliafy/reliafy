import assert from "node:assert/strict";
import { test } from "node:test";
import { countActions, toolsFromSpec } from "./apiSpec.js";

const op = (tool, action, summary, schema, extra = {}) => ({
  post: {
    summary,
    "x-reliafy-tool": tool,
    "x-reliafy-action": action,
    "x-reliafy-scope": tool === "models" ? "write" : "read",
    requestBody: { content: { "application/json": { schema } } },
    ...extra,
  },
});

const SPEC = {
  paths: {
    "/api/v1/guide": op("guide", null, "Short how-tos. Read one first.", { properties: { topic: {} } }),
    "/api/v1/life_data_analysis/fit": op("life_data_analysis", "fit", "Fit a life distribution. More detail",
      { properties: { distribution: {}, data: {}, censored: {} } },
      { "x-reliafy-pro-only": true, "x-reliafy-heavy": true }),
    "/api/v1/models/save": op("models", "save", "Save a model",
      { properties: { name: {}, distribution: {}, params: {} }, required: ["name", "distribution"] }),
    "/api/v1/life_data_analysis/compare_groups": op("life_data_analysis", "compare_groups", "Is A better than B?", {}),
    "/api/v1/maintenance_items/create": op("maintenance_items", "create", "An item.", { properties: { name: {} } }),
    "/api/v1/maintenance/photos": { post: { summary: "A photo.", tags: ["rest_only"], "x-reliafy-rest-only": true } },
    "/api/uploads/{upload_id}": { put: { summary: "Bytes." } },
  },
};

test("tools are grouped with their actions, in the spec's order", () => {
  const tools = toolsFromSpec(SPEC);
  assert.deepEqual(tools.map((t) => t.name), ["guide", "life_data_analysis", "models"]);
  assert.deepEqual(tools[1].actions.map((a) => a.action), ["fit", "compare_groups"]);
  assert.equal(countActions(tools), 4);
});

test("each action has a one-line summary, its path and its arguments", () => {
  const [guide, lda, models] = toolsFromSpec(SPEC);
  assert.deepEqual(guide.actions[0], {
    action: null, path: "/api/v1/guide", summary: "Short how-tos.", required: [], optional: ["topic"],
    pro: false, heavy: false,
  });
  const fit = lda.actions[0];
  assert.equal(fit.summary, "Fit a life distribution.");
  assert.deepEqual(fit.optional, ["distribution", "data", "censored"]);
  assert.ok(fit.pro && fit.heavy);
  assert.equal(lda.actions[1].summary, "Is A better than B?");
  assert.deepEqual(lda.actions[1].optional, []);
  assert.deepEqual(models.actions[0].required, ["name", "distribution"]);
  assert.deepEqual(models.actions[0].optional, ["params"]);
  assert.equal(models.scope, "write");
  assert.equal(lda.scope, "read");
});

test("Maintenance tools and the API-only operations aren't listed", () => {
  const names = toolsFromSpec(SPEC).map((t) => t.name);
  assert.ok(!names.some((n) => n.startsWith("maintenance")));
});

test("a missing or broken spec gives an empty list, not an error", () => {
  assert.deepEqual(toolsFromSpec(null), []);
  assert.deepEqual(toolsFromSpec({}), []);
  assert.deepEqual(toolsFromSpec({ paths: { "/x": null } }), []);
});
