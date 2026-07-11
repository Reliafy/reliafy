// Thin wrappers around the backend endpoints.
import { auth } from "./firebase.js";

// Attach the current user's Firebase ID token (auto-refreshed by the SDK) to
// every request. `auth` is null when auth is disabled for local dev.
async function authHeaders(forceRefresh = false) {
  const token = await auth?.currentUser?.getIdToken(forceRefresh);
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function request(url, opts = {}) {
  const send = async (forceRefresh) => {
    const headers = { ...(opts.headers || {}), ...(await authHeaders(forceRefresh)) };
    return fetch(url, { ...opts, headers });
  };
  let res = await send(false);
  // On a 401, the token may have just expired/been revoked — refresh once and
  // retry before giving up.
  if (res.status === 401 && auth?.currentUser) {
    res = await send(true);
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
  return request(`/api/fit/${distribution}`, { method: "POST", body: form });
}

// ---- Strategy / decision support ------------------------------------------

// Fit and rank every parametric distribution against a dataset (with the
// non-parametric empirical estimate). ``mapping`` is { x, c, n, xl, xr, tl, tr }.
export function compareModels(file, mapping, unit) {
  const form = new FormData();
  form.append("file", file);
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
  return request("/api/models", { method: "POST", body: form });
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
  return request("/api/datasets", { method: "POST", body: form });
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

export function saveRbd(name, graph, id) {
  return request("/api/rbds", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, graph, id: id || null }),
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
  return request("/api/degradation/models", {
    method: "POST",
    body: degradationForm(file, { ...opts, name }),
  });
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
export function createTrackedItem(modelId, { name, measurements, meta } = {}) {
  return request(`/api/degradation/models/${modelId}/items`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, measurements, meta: meta || {} }),
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
  return request("/api/rcm/studies", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, system: system || "", description: description || "" }),
  });
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
export function putRcmTree(id, functions) {
  return request(`/api/rcm/studies/${id}/tree`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ functions }),
  });
}
