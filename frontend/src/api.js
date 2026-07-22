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


// Advanced fit options shared by fit + save: offset (3-parameter), zero
// inflation, limited failure population, and fixed parameter values.
function appendFitOptions(form, { offset, zi, lfp, fixed } = {}) {
  if (offset) form.append("offset", "true");
  if (zi) form.append("zi", "true");
  if (lfp) form.append("lfp", "true");
  if (fixed && Object.keys(fixed).length) form.append("fixed", JSON.stringify(fixed));
}

// Fit a model: distribution id, a data source (an uploaded `file` or a saved
// `datasetId`), a column mapping ({ x, c, n, xl, xr, tl, tr } -> column name or
// ""), and optional covariates (array of column names) or a formula string for
// proportional-hazards models.
export function fitModel(distribution, file, mapping, { covariates, formula, unit, datasetId, fitOptions } = {}) {
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
  appendFitOptions(form, fitOptions);
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
export function optimalReplacement(distributionId, params, plannedCost, unplannedCost, unit, extras) {
  return request("/api/strategy/optimal-replacement", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      distribution_id: distributionId,
      params,
      planned_cost: plannedCost,
      unplanned_cost: unplannedCost,
      unit: unit || null,
      extras: extras || null,
    }),
  });
}

// Re-evaluate a fitted model's functions at covariate values. ``path`` comes
// from the result payload (functions.evaluate_path) and differs for unsaved
// (in-memory) vs saved (re-fit) models.
// Optional { xMin, xMax } recompute the curves over a custom x-axis range.
function rangeQuery({ xMin, xMax } = {}) {
  const q = [];
  if (xMin != null) q.push(`x_min=${xMin}`);
  if (xMax != null) q.push(`x_max=${xMax}`);
  return q.length ? `?${q.join("&")}` : "";
}

export function evaluateAt(path, values, range) {
  return request(path + rangeQuery(range), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(values),
  });
}

// Confidence bounds of a fitted model's function. ``path`` comes from the
// result payload (functions.confidence_path); params are { on, alpha_ci, bound }.
export function confidenceAt(path, params, range) {
  return request(path + rangeQuery(range), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
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
  { covariates, formula, unit, datasetId, fitOptions } = {}
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
  appendFitOptions(form, fitOptions);
  return withEvent(request("/api/models", { method: "POST", body: form }), "model_save");
}

export function deleteModel(id) {
  return request(`/api/models/${id}`, { method: "DELETE" });
}

// Create a per-demand (Binomial) model from demands + failures counts.
export function createPerDemandModel(name, demands, failures, confidence = 0.95) {
  return withEvent(
    request("/api/models/per-demand", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, demands: Number(demands), failures: Number(failures), confidence: Number(confidence) }),
    }),
    "model_save"
  );
}

// Create a model from parameters alone (no data): functions & life metrics,
// no probability plot. ``params`` is [{name, value}]; ``extras`` may hold
// gamma/p/f0 for offset/LFP/zero-inflated models.
export function createModelFromParams(name, distribution, params, { unit, extras } = {}) {
  return withEvent(
    request("/api/models/from-params", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, distribution, params, unit: unit || null, extras: extras || null }),
    }),
    "model_save"
  );
}

// Refit a saved model in place with an edited spec (same dataset, same id --
// everything referencing the model sees the updated fit).
export function updateModelFit(id, { distribution, mapping, covariates, formula, unit, fitOptions } = {}) {
  return request(`/api/models/${id}/fit`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      distribution,
      mapping: mapping || {},
      covariates: covariates || [],
      formula: formula || null,
      unit: unit || null,
      offset: !!fitOptions?.offset,
      zi: !!fitOptions?.zi,
      lfp: !!fitOptions?.lfp,
      fixed: fitOptions?.fixed && Object.keys(fitOptions.fixed).length ? fitOptions.fixed : null,
    }),
  });
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

// Create a dataset from pasted tabular text (CSV or TSV; delimiter sniffed
// server-side). Used by the paste-data form and the assistant.
export function pasteDataset(name, content) {
  return withEvent(
    request("/api/datasets/paste", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: name || "", content: content || "" }),
    }),
    "dataset_upload"
  );
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

// Streaming variant of assistantStep. `onDelta(text)` fires for each chunk of
// assistant text as it's written; resolves to the final payload
// ({ message, stop_reason, usage, credit_cents, ... }) — identical to what
// assistantStep returns — so the caller can continue the tool loop. Throws on a
// non-2xx response (credit/availability errors) or a mid-stream provider error.
export async function assistantStepStream(system, messages, tools, { onDelta, signal } = {}) {
  const headers = {
    "Content-Type": "application/json",
    ...workspaceHeaders(),
    ...(await authHeaders()),
  };
  const res = await fetch("/api/assistant/stream", {
    method: "POST",
    headers,
    body: JSON.stringify({ system, messages, tools }),
    signal,
  });
  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    let code;
    try { const j = await res.json(); detail = j.detail || detail; code = j.code; } catch { /* non-JSON */ }
    const err = new Error(detail); err.status = res.status; err.code = code;
    throw err;
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let final = null;
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let sep;
    while ((sep = buffer.indexOf("\n\n")) !== -1) {
      const frame = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      const line = frame.split("\n").find((l) => l.startsWith("data:"));
      if (!line) continue;
      let ev;
      try { ev = JSON.parse(line.slice(5).trim()); } catch { continue; }
      if (ev.type === "delta") onDelta?.(ev.text);
      else if (ev.type === "final") final = ev;
      else if (ev.type === "error") { const e = new Error(ev.detail || "Assistant error"); e.code = ev.code; throw e; }
    }
  }
  if (!final) throw new Error("The assistant stream ended without a result.");
  return final;
}

// ---- Reliability Agent (Anthropic Managed Agents) --------------------------
// Separate from the assistant above, with its own metering; runs Python (with
// surpyval) in Anthropic's managed sandbox and streams its work back.
export function reliabilityAgentInfo() {
  return request("/api/reliability-agent/info");
}

// Upload a CSV into the agent's sandbox; returns { file_id, filename }.
export function reliabilityAgentUpload(file) {
  const form = new FormData();
  form.append("file", file);
  return request("/api/reliability-agent/upload", { method: "POST", body: form });
}

// Run one agent turn, streaming Server-Sent Events. `onEvent(ev)` is called for
// each parsed event (text / tool_use / tool_result / image / status / error /
// done). Pass `sessionId` to continue an existing conversation (the `done`
// event carries the session_id to reuse). Resolves when the stream ends.
export async function reliabilityAgentStream(message, { fileId, sessionId, approved, onEvent, signal } = {}) {
  const headers = {
    "Content-Type": "application/json",
    ...workspaceHeaders(),
    ...(await authHeaders()),
  };
  const res = await fetch("/api/reliability-agent/run", {
    method: "POST",
    headers,
    body: JSON.stringify({ message, file_id: fileId || null, session_id: sessionId || null, approved: !!approved }),
    signal,
  });
  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try { detail = (await res.json()).detail || detail; } catch { /* non-JSON */ }
    throw new Error(detail);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    // SSE frames are separated by a blank line.
    let sep;
    while ((sep = buffer.indexOf("\n\n")) !== -1) {
      const frame = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      const line = frame.split("\n").find((l) => l.startsWith("data:"));
      if (!line) continue;
      try { onEvent?.(JSON.parse(line.slice(5).trim())); } catch { /* skip */ }
    }
  }
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

// ---- Recurrent-event (repairable-system) models ----------------------------
export function getRecurrentOptions() {
  return request("/api/recurrent/options");
}

function recurrentForm(file, { datasetId, mapping, model, unit, name } = {}) {
  const form = new FormData();
  if (name) form.append("name", name);
  if (datasetId) form.append("dataset_id", datasetId);
  else if (file) form.append("file", file);
  form.append("i", mapping.i);
  form.append("x", mapping.x);
  // Optional modifiers, matching the life-data column surface.
  ["c", "n", "tl", "tr", "t"].forEach((k) => { if (mapping[k]) form.append(k, mapping[k]); });
  if (model) form.append("model", model);
  if (unit) form.append("unit", unit);
  return form;
}

export function fitRecurrent(file, opts) {
  return request("/api/recurrent/fit", { method: "POST", body: recurrentForm(file, opts) });
}

export function saveRecurrentModel(name, file, opts) {
  return request("/api/recurrent/models", { method: "POST", body: recurrentForm(file, { ...opts, name }) });
}

// Build a recurrent model from known parameters (no dataset) — a "simple model"
// for repairable-system decisions (e.g. optimal repairs before replacement).
export function createRecurrentFromParams(name, model, { alpha, beta, horizon, unit } = {}) {
  const form = new FormData();
  form.append("name", name);
  form.append("model", model);
  form.append("alpha", alpha);
  form.append("beta", beta);
  form.append("horizon", horizon);
  if (unit) form.append("unit", unit);
  return request("/api/recurrent/from-params", { method: "POST", body: form });
}

export function listRecurrentModels() {
  return request("/api/recurrent/models");
}

export function getRecurrentModel(id) {
  return request(`/api/recurrent/models/${id}`);
}

export function deleteRecurrentModel(id) {
  return request(`/api/recurrent/models/${id}`, { method: "DELETE" });
}

export function predictRecurrent(id, horizon) {
  return request(`/api/recurrent/models/${id}/predict`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ horizon }),
  });
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

// Population reliability curve (sf) with two-stage confidence bounds at a
// chosen confidence level. Refits the live model on demand.
export function degradationReliability(id, confidence) {
  return request(`/api/degradation/models/${id}/reliability?confidence=${confidence}`);
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

// Recompute one item's crossing prediction at a chosen confidence (view-only).
export function getItemPrediction(modelId, itemId, confidence) {
  return request(`/api/degradation/models/${modelId}/items/${itemId}/prediction?confidence=${confidence}`);
}

// ---- Strategy: failure finding + saved analyses ------------------------------

// Failure-finding interval for a hidden function (protective device).
export function failureFinding(distributionId, params, targetAvailability, unit, extras) {
  return request("/api/strategy/failure-finding", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      distribution_id: distributionId,
      params,
      target_availability: targetAvailability,
      unit: unit || null,
      extras: extras || null,
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

// ---- Public share links -----------------------------------------------------

export function createPublicLink(collection, artifactId) {
  return request("/api/public-links", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ collection, artifact_id: artifactId }),
  });
}

export function getPublicLink(collection, artifactId) {
  return request(`/api/public-links?collection=${collection}&artifact_id=${artifactId}`);
}

export function revokePublicLink(token) {
  return request(`/api/public-links/${token}`, { method: "DELETE" });
}

// Unauthenticated: resolve a public link to its artifact payload.
export function getPublicArtifact(token) {
  return request(`/api/public/${encodeURIComponent(token)}`);
}

// ---- Personal API tokens ------------------------------------------------------

export function listApiTokens() {
  return request("/api/tokens");
}

export function createApiToken(name) {
  return request("/api/tokens", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
}

export function revokeApiToken(id) {
  return request(`/api/tokens/${id}`, { method: "DELETE" });
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

// Hide every shared sample for this user (inverse of restoreSamples).
export function removeSamples() {
  return request("/api/samples/remove", { method: "POST" });
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
