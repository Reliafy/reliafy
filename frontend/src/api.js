// Thin wrappers around the backend endpoints.
import { auth } from "./firebase.js";
import { trackEvent } from "./telemetry.js";

// Activation milestones: fire a product event when the promise resolves.
// These are the funnel steps between "signed up" and "getting value" —
// visible in /admin traffic so acquisition posts can be judged on
// activation, not just signups.
function withEvent(promise, name) {
  return promise.then((result) => {
    trackEvent(name);
    return result;
  });
}

// Attach the current user's Firebase ID token (auto-refreshed by the SDK) to
// every request. `auth` is null when auth is disabled for local dev.
async function authHeaders(forceRefresh = false) {
  const token = await auth?.currentUser?.getIdToken(forceRefresh);
  return token ? { Authorization: `Bearer ${token}` } : {};
}

// Active workspace ("personal" or a team id). Sent on every request so the
// backend scopes reads/writes to the right principal.
const WORKSPACE_KEY = "reliafy.workspace";
// localStorage is absent during SSG prerendering (Node) — default to personal.
const _storage = typeof localStorage === "undefined" ? null : localStorage;
let workspaceId = _storage?.getItem(WORKSPACE_KEY) || "personal";

export function getWorkspace() {
  return workspaceId;
}

export function setWorkspace(id) {
  workspaceId = id || "personal";
  _storage?.setItem(WORKSPACE_KEY, workspaceId);
}

function workspaceHeaders() {
  return workspaceId && workspaceId !== "personal"
    ? { "X-Workspace-Id": workspaceId }
    : {};
}

async function request(url, opts = {}) {
  const send = async (forceRefresh) => {
    const headers = {
      ...(opts.headers || {}),
      ...workspaceHeaders(),
      ...(await authHeaders(forceRefresh)),
    };
    return fetch(url, { ...opts, headers });
  };
  let res = await send(false);
  // On a 401, the token may have just expired/been revoked — refresh once and
  // retry before giving up.
  if (res.status === 401 && auth?.currentUser) {
    res = await send(true);
  }
  // A 403 on the workspace header means the stored team no longer exists (or
  // we were removed). Self-heal: fall back to the personal workspace and
  // retry once instead of stranding every page on an error.
  if (res.status === 403 && workspaceId !== "personal") {
    const probe = await res.clone().json().catch(() => ({}));
    if (String(probe.detail || "").includes("not a member")) {
      setWorkspace("personal");
      res = await send(false);
    }
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new Error(
      data.detail || (res.status === 401 ? "Not authenticated" : `Request failed (${res.status})`)
    );
    err.status = res.status;
    if (data.code) err.code = data.code;
    throw err;
  }
  return data;
}

// The signed-in user's profile (also upserts it on the backend).
export function getMe() {
  return request("/api/me");
}

// Deployment capabilities (public, no auth): { auth, ai, billing }.
export function getAppConfig() {
  return request("/api/config");
}

// List the distributions the backend can fit.
export function getDistributions() {
  return request("/api/distributions");
}

// Upload a CSV and get back its columns + a preview of the first rows.
export function getColumns(file) {
  const form = new FormData();
  form.append("file", file);
  return request("/api/columns", { method: "POST", body: form });
}

// Fit a model: distribution id, a data source (an uploaded `file` or a saved
// `datasetId`), a column mapping ({ x, c, n, xl, xr, tl, tr } -> column name or
// ""), and optional covariates (array of column names) or a formula string for
// proportional-hazards models.
export function fitModel(distribution, file, mapping, { covariates, formula, unit, datasetId } = {}) {
  const form = new FormData();
  if (datasetId) form.append("dataset_id", datasetId);
  else if (file) form.append("file", file);
  for (const [field, column] of Object.entries(mapping)) {
    if (column) form.append(field, column);
  }
  if (unit) form.append("unit", unit);
  if (formula) {
    form.append("formula", formula);
  } else if (covariates) {
    for (const col of covariates) form.append("z", col);
  }
  return withEvent(
    request(`/api/fit/${distribution}`, { method: "POST", body: form }),
    "model_fit"
  );
}

// ---- Strategy / decision support ------------------------------------------

// Fit and rank every parametric distribution against a dataset (with the
// non-parametric empirical estimate). ``mapping`` is { x, c, n, xl, xr, tl, tr }.
export function compareModels(file, mapping, unit, datasetId) {
  const form = new FormData();
  if (datasetId) form.append("dataset_id", datasetId);
  else if (file) form.append("file", file);
  for (const [field, column] of Object.entries(mapping)) {
    if (column) form.append(field, column);
  }
  if (unit) form.append("unit", unit);
  return request("/api/strategy/compare", { method: "POST", body: form });
}

// Compare two models' reliability. Each side is a spec: a parametric model
// ({ kind:"parametric", distribution_id, params, label }) or a non-parametric
// Kaplan-Meier fit of raw data ({ kind:"nonparametric", x:[...], c:[...], label }).
export function compareTwoModels(a, b, unit) {
  return request("/api/strategy/compare-two", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ a, b, unit: unit || null }),
  });
}

// Compute the cost-optimal preventive-replacement interval for a distribution.
export function optimalReplacement(distributionId, params, plannedCost, unplannedCost, unit) {
  return request("/api/strategy/optimal-replacement", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      distribution_id: distributionId,
      params,
      planned_cost: plannedCost,
      unplanned_cost: unplannedCost,
      unit: unit || null,
    }),
  });
}

// Re-evaluate a fitted model's functions at covariate values. ``path`` comes
// from the result payload (functions.evaluate_path) and differs for unsaved
// (in-memory) vs saved (re-fit) models.
export function evaluateAt(path, values) {
  return request(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(values),
  });
}

// ---- Saved models ----------------------------------------------------------

export function listModels() {
  return request("/api/models");
}

export function getModel(id) {
  return request(`/api/models/${id}`);
}

// Persist a fit. Same form fields as fitModel, plus a name.
export function saveModel(
  name,
  distribution,
  file,
  mapping,
  { covariates, formula, unit, datasetId } = {}
) {
  const form = new FormData();
  if (datasetId) form.append("dataset_id", datasetId);
  else if (file) form.append("file", file);
  form.append("name", name);
  form.append("distribution", distribution);
  for (const [field, column] of Object.entries(mapping)) {
    if (column) form.append(field, column);
  }
  if (unit) form.append("unit", unit);
  if (formula) {
    form.append("formula", formula);
  } else if (covariates) {
    for (const col of covariates) form.append("z", col);
  }
  return withEvent(request("/api/models", { method: "POST", body: form }), "model_save");
}

export function deleteModel(id) {
  return request(`/api/models/${id}`, { method: "DELETE" });
}

// ---- Datasets --------------------------------------------------------------

export function listDatasets() {
  return request("/api/datasets");
}

export function getDataset(id) {
  return request(`/api/datasets/${id}`);
}

// Upload a CSV as a standalone dataset (deduped by content on the server).
export function uploadDataset(file, name) {
  const form = new FormData();
  form.append("file", file);
  if (name) form.append("name", name);
  return withEvent(request("/api/datasets", { method: "POST", body: form }), "dataset_upload");
}

export function deleteDataset(id) {
  return request(`/api/datasets/${id}`, { method: "DELETE" });
}

// ---- Saved RBDs ------------------------------------------------------------

export function listRbds() {
  return request("/api/rbds");
}

export function getRbd(id) {
  return request(`/api/rbds/${id}`);
}

export function saveRbd(name, graph, id, expectedUpdatedAt) {
  return withEvent(
    request("/api/rbds", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, graph, id: id || null, expected_updated_at: expectedUpdatedAt || null }),
    }),
    "rbd_save"
  );
}

export function renameRbd(id, name) {
  return request(`/api/rbds/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
}

export function deleteRbd(id) {
  return request(`/api/rbds/${id}`, { method: "DELETE" });
}

// ---- Billing & AI credits --------------------------------------------------

// Plan/credit status + caps/usage + available packs.
export function getBilling() {
  return request("/api/billing");
}

// Start a Stripe Checkout for a one-time credit pack; returns { url }.
export function buyCredits(packId) {
  return request("/api/billing/checkout", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pack_id: packId }),
  });
}

// Start a Stripe Checkout for the Pro subscription; returns { url }.
export function subscribePro() {
  return request("/api/billing/subscribe", { method: "POST" });
}

// Open the Stripe billing portal; returns { url }.
export function billingPortal() {
  return request("/api/billing/portal", { method: "POST" });
}

// ---- Assistant (server-side, metered) --------------------------------------

// Whether the AI is configured, which provider, and the current credit balance.
export function getAssistantInfo() {
  return request("/api/assistant/info");
}

// Advance the assistant one provider round-trip. Returns the native assistant
// message, token usage, the metered cost, and the new credit balance.
export function assistantStep(system, messages, tools) {
  return request("/api/assistant/step", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ system, messages, tools }),
  });
}

// Analyse an (unsaved) RBD graph with RePyability: returns the system
// reliability over time, per-node reliability, MTTF, importances, and the
// minimal path/cut sets. ``tMax`` sets the upper limit of the time axis;
// ``covariates`` maps node id -> covariate values for proportional-hazards
// nodes; ``conditionalAge`` conditions the curves on having survived to that
// age (conditional survival).
export function analyzeRbd(graph, tMax, covariates, conditionalAge) {
  return request("/api/rbds/analyze", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      graph,
      t_max: tMax ?? null,
      covariates: covariates || {},
      conditional_age: conditionalAge ?? null,
    }),
  });
}

// Analyse a saved RBD by id (sub-systems are resolved server-side).
export function analyzeSavedRbd(id, tMax) {
  const q = tMax != null ? `?t_max=${encodeURIComponent(tMax)}` : "";
  return request(`/api/rbds/${id}/analyze${q}`);
}

// Check whether an (unsaved) graph is a valid, analytically solvable RBD.
// Returns { valid, analytic, can_calculate, errors, warnings,
// non_analytic_nodes }.
export function validateRbd(graph) {
  return request("/api/rbds/validate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ graph }),
  });
}


// ---- Degradation & RUL -------------------------------------------------------

export function getDegradationOptions() {
  return request("/api/degradation/options");
}

function degradationForm(file, { datasetId, mapping, threshold, path, distribution, populationMethod, unit, measurementUnit, name } = {}) {
  const form = new FormData();
  if (name) form.append("name", name);
  if (datasetId) form.append("dataset_id", datasetId);
  else if (file) form.append("file", file);
  form.append("i", mapping.i);
  form.append("x", mapping.x);
  form.append("y", mapping.y);
  form.append("threshold", threshold);
  if (path) form.append("path", path);
  if (distribution) form.append("distribution", distribution);
  if (populationMethod) form.append("population_method", populationMethod);
  if (unit) form.append("unit", unit);
  if (measurementUnit) form.append("measurement_unit", measurementUnit);
  return form;
}

// Fit a degradation model for preview (nothing saved except an uploaded CSV).
export function fitDegradation(file, opts) {
  return request("/api/degradation/fit", { method: "POST", body: degradationForm(file, opts) });
}

// Fit and persist a degradation model.
export function saveDegradationModel(name, file, opts) {
  return withEvent(
    request("/api/degradation/models", {
      method: "POST",
      body: degradationForm(file, { ...opts, name }),
    }),
    "degradation_save"
  );
}

export function listDegradationModels() {
  return request("/api/degradation/models");
}

export function getDegradationModel(id) {
  return request(`/api/degradation/models/${id}`);
}

export function renameDegradationModel(id, name) {
  return request(`/api/degradation/models/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
}

export function deleteDegradationModel(id) {
  return request(`/api/degradation/models/${id}`, { method: "DELETE" });
}

// Tracked items: register an asset against a degradation model, append
// measurements over time, and read back its threshold-crossing prediction.
export function createTrackedItem(modelId, { name, measurements, meta, fleetId } = {}) {
  return request(`/api/degradation/models/${modelId}/items`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ fleet_id: fleetId || null, name, measurements, meta: meta || {} }),
  });
}

export function listTrackedItems(modelId) {
  return request(`/api/degradation/models/${modelId}/items`);
}

export function addTrackedMeasurement(modelId, itemId, t, y) {
  return request(`/api/degradation/models/${modelId}/items/${itemId}/measurements`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ t, y }),
  });
}

export function deleteTrackedItem(modelId, itemId) {
  return request(`/api/degradation/models/${modelId}/items/${itemId}`, { method: "DELETE" });
}

// ---- Strategy: failure finding + saved analyses ------------------------------

// Failure-finding interval for a hidden function (protective device).
export function failureFinding(distributionId, params, targetAvailability, unit) {
  return request("/api/strategy/failure-finding", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      distribution_id: distributionId,
      params,
      target_availability: targetAvailability,
      unit: unit || null,
    }),
  });
}

// Persist a strategy analysis (results recomputed server-side from inputs).
export function saveStrategyAnalysis(name, kind, inputs) {
  return request("/api/strategy/analyses", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, kind, inputs }),
  });
}

export function listStrategyAnalyses() {
  return request("/api/strategy/analyses");
}

export function getStrategyAnalysis(id) {
  return request(`/api/strategy/analyses/${id}`);
}

export function renameStrategyAnalysis(id, name) {
  return request(`/api/strategy/analyses/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
}

export function deleteStrategyAnalysis(id) {
  return request(`/api/strategy/analyses/${id}`, { method: "DELETE" });
}

// ---- RCM ---------------------------------------------------------------------

export function getRcmOptions() {
  return request("/api/rcm/options");
}

export function listRcmStudies() {
  return request("/api/rcm/studies");
}

export function createRcmStudy(name, system, description) {
  return withEvent(
    request("/api/rcm/studies", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, system: system || "", description: description || "" }),
    }),
    "rcm_create"
  );
}

export function getRcmStudy(id) {
  return request(`/api/rcm/studies/${id}`);
}

export function renameRcmStudy(id, name) {
  return request(`/api/rcm/studies/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
}

export function deleteRcmStudy(id) {
  return request(`/api/rcm/studies/${id}`, { method: "DELETE" });
}

// Replace the whole worksheet tree; returns the study with fresh evidence
// statuses resolved.
export function putRcmTree(id, functions, expectedUpdatedAt) {
  return request(`/api/rcm/studies/${id}/tree`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ functions, expected_updated_at: expectedUpdatedAt || null }),
  });
}

// ---- Teams -------------------------------------------------------------------

export function listTeams() {
  return request("/api/teams");
}

export function createTeam(name) {
  return request("/api/teams", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
}

export function getTeam(id) {
  return request(`/api/teams/${id}`);
}

export function renameTeam(id, name) {
  return request(`/api/teams/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
}

export function deleteTeam(id) {
  return request(`/api/teams/${id}`, { method: "DELETE" });
}

export function inviteTeamMember(id, email) {
  return request(`/api/teams/${id}/members`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email }),
  });
}

export function removeTeamMember(id, uid) {
  return request(`/api/teams/${id}/members/${uid}`, { method: "DELETE" });
}

export function removeTeamInvite(id, email) {
  return request(`/api/teams/${id}/invites/${encodeURIComponent(email)}`, { method: "DELETE" });
}

export function leaveTeam(id) {
  return request(`/api/teams/${id}/leave`, { method: "POST" });
}

// ---- Direct sharing ------------------------------------------------------------

export function createShare(collection, artifactId, email) {
  return request("/api/shares", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ collection, artifact_id: artifactId, email }),
  });
}

export function listShares(collection, artifactId) {
  return request(`/api/shares?collection=${collection}&artifact_id=${artifactId}`);
}

export function revokeShare(shareId) {
  return request(`/api/shares/${shareId}`, { method: "DELETE" });
}

// Operator-only stats (403 for regular accounts).
export function getAdminStats() {
  return request("/api/admin/stats");
}

// Operator-only first-party traffic analytics.
export function getAdminTraffic(days = 14) {
  return request(`/api/admin/traffic?days=${days}`);
}

// Un-hide all dismissed sample artifacts.
export function restoreSamples() {
  return request("/api/samples/restore", { method: "POST" });
}

// ---- Fleet failure forecasting ---------------------------------------------------

export function listFleets() {
  return request("/api/fleet/fleets");
}

export function createFleet(name, modelId) {
  return request("/api/fleet/fleets", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, model_id: modelId }),
  });
}

export function getFleet(id) {
  return request(`/api/fleet/fleets/${id}`);
}

export function renameFleet(id, name) {
  return request(`/api/fleet/fleets/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
}

export function deleteFleet(id) {
  return request(`/api/fleet/fleets/${id}`, { method: "DELETE" });
}

export function putFleetItems(id, settings, items, expectedUpdatedAt) {
  return request(`/api/fleet/fleets/${id}/items`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ settings, items, expected_updated_at: expectedUpdatedAt || null }),
  });
}

// ---- Tracked fleets (degradation tracking groups) --------------------------------

export function listTrackedFleets() {
  return request("/api/fleet/tracked");
}

export function createTrackedFleet(name, modelId) {
  return request("/api/fleet/tracked", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, model_id: modelId }),
  });
}

export function getTrackedFleet(id) {
  return request(`/api/fleet/tracked/${id}`);
}

export function renameTrackedFleet(id, name) {
  return request(`/api/fleet/tracked/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
}

export function deleteTrackedFleet(id) {
  return request(`/api/fleet/tracked/${id}`, { method: "DELETE" });
}
