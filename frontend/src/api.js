// Thin wrappers around the backend endpoints.
import { loadAuth } from "./firebase.js";
import { trackEvent } from "./telemetry.js";

// SSE streaming (the metered assistant) is served straight from Cloud Run to
// bypass Firebase Hosting's CDN, which buffers Server-Sent Events. Cross-origin
// to the run.app host (allowed via backend CORS). Same-origin everywhere the CDN
// isn't in front: self-host (auth disabled) and local dev (no VITE_STREAM_ORIGIN).
const STREAM_ORIGIN =
  import.meta.env.VITE_AUTH_DISABLED === "true"
    ? ""
    : (import.meta.env.VITE_STREAM_ORIGIN || "").replace(/\/+$/, "");

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

// The signed-in Firebase user, or null (signed out, or auth disabled for local
// dev). The SDK is loaded on demand; by the time a request runs it's normally
// already in memory (AuthProvider loads it on mount).
async function currentUser() {
  const mod = await loadAuth().catch(() => null);
  return mod?.auth?.currentUser || null;
}

// Attach the current user's Firebase ID token (auto-refreshed by the SDK) to
// every request.
async function authHeaders(forceRefresh = false) {
  const token = await (await currentUser())?.getIdToken(forceRefresh);
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

// fetch() with the auth + workspace headers and the same retry/self-heal as
// every JSON call; resolves to the raw Response (for non-JSON downloads).
async function authedFetch(url, opts = {}) {
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
  if (res.status === 401 && (await currentUser())) {
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
  return res;
}

async function request(url, opts = {}) {
  return readJson(await authedFetch(url, opts));
}

// Share-link endpoints that need no account: a plain fetch, with no auth
// headers and no refresh-and-retry on a 401 (which there means "password
// needed", and on an unlock would spend a second attempt).
async function publicRequest(url, opts = {}) {
  return readJson(await fetch(url, opts));
}

async function readJson(res) {
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new Error(
      data.detail || (res.status === 401 ? "Not authenticated" : `Request failed (${res.status})`)
    );
    err.status = res.status;
    if (data.code) err.code = data.code;
    err.data = data;
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
// inflation, limited failure population, fixed parameter values, and a mixture
// component count (mutually exclusive with the rest — see normalize_options),
// the fit method, Best fit's "consider two-mode mixtures" (#236) and Cox PH's
// tie method, strata and cluster columns (#61).
function appendFitOptions(form, { offset, zi, lfp, fixed, mixture, mixture_distribution, how,
                                  include_mixtures, cox } = {}) {
  if (offset) form.append("offset", "true");
  if (zi) form.append("zi", "true");
  if (lfp) form.append("lfp", "true");
  if (fixed && Object.keys(fixed).length) form.append("fixed", JSON.stringify(fixed));
  if (Number(mixture) > 1) form.append("mixture", String(Number(mixture)));
  if (mixture_distribution) form.append("mixture_distribution", mixture_distribution);
  if (how) form.append("how", how);
  if (include_mixtures) form.append("include_mixtures", "true");
  const coxSet = cox && Object.fromEntries(Object.entries(cox).filter(([, v]) => v));
  if (coxSet && Object.keys(coxSet).length) form.append("cox", JSON.stringify(coxSet));
}

// Column mapping -> form fields. ``mapping`` is { x, c, n, xl, xr, tl, tr }
// -> column name or "", plus the boolean ``c_invert`` (the c column uses
// 1 = failed and must be flipped), sent as "1"/"0" whenever c is mapped, and
// ``c_map`` ({"Failed": 0, "Running": 1}: a status column of words), sent as
// JSON when it has entries (#291).
function appendMapping(form, mapping) {
  const { c_invert, c_map, ...columns } = mapping || {};
  for (const [field, column] of Object.entries(columns)) {
    if (column) form.append(field, column);
  }
  if (columns.c) form.append("c_invert", c_invert ? "1" : "0");
  if (columns.c && c_map && Object.keys(c_map).length) form.append("c_map", JSON.stringify(c_map));
}

// Fit a model: distribution id, a data source (an uploaded `file` or a saved
// `datasetId`), a column mapping (see appendMapping), and optional covariates
// (array of column names) or a formula string for proportional-hazards models.
// Optional covariate units (#265): {column: unit}, sent as JSON with only the
// ticked covariates that have one.
function appendCovariateUnits(form, covariates, units) {
  const picked = Object.fromEntries(
    (covariates || []).map((c) => [c, String((units || {})[c] || "").trim()]).filter(([, u]) => u)
  );
  if (Object.keys(picked).length) form.append("covariate_units", JSON.stringify(picked));
}

export function fitModel(distribution, file, mapping, { covariates, covariateUnits, formula, unit, datasetId, fitOptions } = {}) {
  const form = new FormData();
  if (datasetId) form.append("dataset_id", datasetId);
  else if (file) form.append("file", file);
  appendMapping(form, mapping);
  if (unit) form.append("unit", unit);
  if (formula) {
    form.append("formula", formula);
  } else if (covariates) {
    for (const col of covariates) form.append("z", col);
    appendCovariateUnits(form, covariates, covariateUnits);
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

// B-lives and MTTF with one-sided lower bounds (#288). ``path`` comes from the
// result payload (functions.life_path); ``body`` is { confidence } or, for the
// time at a reliability, { reliability: [R], confidence, bound }.
export function lifeAt(path, body) {
  return request(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

// ---- Saved models ----------------------------------------------------------

// Best fit's ranking of every distribution on a saved model's data (#293).
export function compareModel(id) {
  return request(`/api/models/${id}/compare`, { method: "POST" });
}

export function listModels() {
  return request("/api/models");
}

export function getModel(id) {
  return request(`/api/models/${id}`);
}

// A regression model's "how good is this model?" scores (#176). Stored at fit
// time; for a model saved before that, computed (and cached) on request.
export function getModelValidation(id) {
  return request(`/api/models/${id}/validation`);
}

// A regression model's checks (#61): the proportional-hazards test, robust
// standard errors, ties and strata. Stored at fit time; for a model saved
// before them, computed (and cached) on request.
export function getModelDiagnostics(id) {
  return request(`/api/models/${id}/diagnostics`);
}

// The residuals behind the proportional-hazards test, for plotting. ``path``
// comes from the result payload (functions.residuals_path).
export function getResiduals(path) {
  return request(path);
}

// Persist a fit. Same form fields as fitModel, plus a name.
export function saveModel(
  name,
  distribution,
  file,
  mapping,
  { covariates, covariateUnits, formula, unit, datasetId, fitOptions } = {}
) {
  const form = new FormData();
  if (datasetId) form.append("dataset_id", datasetId);
  else if (file) form.append("file", file);
  form.append("name", name);
  form.append("distribution", distribution);
  appendMapping(form, mapping);
  if (unit) form.append("unit", unit);
  if (formula) {
    form.append("formula", formula);
  } else if (covariates) {
    for (const col of covariates) form.append("z", col);
    appendCovariateUnits(form, covariates, covariateUnits);
  }
  appendFitOptions(form, fitOptions);
  return withEvent(request("/api/models", { method: "POST", body: form }), "model_save");
}

export function deleteModel(id) {
  return request(`/api/models/${id}`, { method: "DELETE" });
}

// Create a per-demand (Binomial) model. ``source`` is one of
// { batches: [{label, demands, failures}] } (one row = one count) or
// { dataset_id, demands_column, failures_column, batch_column? }; the bounds
// are exact at ``confidence`` (#233).
export function createPerDemandModel(name, source, confidence = 0.95) {
  return withEvent(
    request("/api/models/per-demand", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, ...source, confidence: Number(confidence) }),
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
export function updateModelFit(id, { distribution, mapping, covariates, covariateUnits, formula, unit, fitOptions } = {}) {
  const { c_invert, c_map, ...columns } = mapping || {};
  // Covariate units (#265): omitted keeps the model's own.
  const units = covariateUnits === undefined ? undefined : Object.fromEntries(
    (covariates || []).map((c) => [c, String(covariateUnits[c] || "").trim()]).filter(([, u]) => u)
  );
  return request(`/api/models/${id}/fit`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      distribution,
      mapping: columns,
      c_invert: !!(columns.c && c_invert),
      c_map: columns.c && c_map && Object.keys(c_map).length ? c_map : null,
      covariates: covariates || [],
      formula: formula || null,
      unit: unit || null,
      offset: !!fitOptions?.offset,
      mixture: Number(fitOptions?.mixture) > 1 ? Number(fitOptions.mixture) : 0,
      mixture_distribution: fitOptions?.mixture_distribution || null,
      zi: !!fitOptions?.zi,
      lfp: !!fitOptions?.lfp,
      fixed: fitOptions?.fixed && Object.keys(fitOptions.fixed).length ? fitOptions.fixed : null,
      how: fitOptions?.how || null,
      include_mixtures: !!fitOptions?.include_mixtures,
      cox: fitOptions?.cox && Object.values(fitOptions.cox).some(Boolean) ? fitOptions.cox : null,
      ...(units !== undefined ? { covariate_units: units } : {}),
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

// Split a dataset by a column and compare the groups (log-rank, RMST, Gray's).
// ``body`` = { time_column, group_column, censor_column?, count_column?,
// cause_column?, c_invert?, groups?, reference?, tau?, unit? }.
export function compareGroups(datasetId, body) {
  return request(`/api/datasets/${datasetId}/compare-groups`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

// Upload a CSV as a standalone dataset (deduped by content on the server).
// An Excel workbook works too: ``excel`` = { sheet, headerRow } picks the
// sheet and header row (headerRow 0 = none), converted to CSV server-side.
export function uploadDataset(file, name, noHeader = false, excel = null) {
  const form = new FormData();
  form.append("file", file);
  if (name) form.append("name", name);
  if (noHeader) form.append("no_header", "true");
  if (excel?.sheet) form.append("sheet", excel.sheet);
  if (excel && excel.headerRow != null) form.append("header_row", String(excel.headerRow));
  return withEvent(request("/api/datasets", { method: "POST", body: form }), "dataset_upload");
}

// ---- Excel workbooks (.xlsx) -------------------------------------------------
// Parsed server-side; the frontend picks a sheet + header row, then either
// maps columns (RCM, RBD) or converts the sheet to CSV (life data).

export const SPREADSHEET_ACCEPT = ".xlsx,.xlsm,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
// Also catches formats the server refuses with a "save it as .xlsx" message.
export const isSpreadsheetFile = (file) => /\.(xlsx|xlsm|xltx|xltm|xls|xlsb|ods)$/i.test(file?.name || "");

function excelForm(file, sheet, headerRow, extra = {}) {
  const form = new FormData();
  form.append("file", file);
  if (sheet) form.append("sheet", sheet);
  if (headerRow != null && headerRow !== "") form.append("header_row", String(headerRow));
  for (const [k, v] of Object.entries(extra)) {
    if (v != null && v !== "") form.append(k, typeof v === "string" ? v : JSON.stringify(v));
  }
  return form;
}

// Sheets, a preview of each, and the guessed header row.
export function inspectExcel(file) {
  return request("/api/excel/inspect", { method: "POST", body: excelForm(file) });
}

// One sheet's columns + first rows; with ``target`` ("rcm", "rbd_blocks",
// "rbd_connections") also that importer's fields and a guessed mapping.
export function excelTable(file, sheet, headerRow, target) {
  return request("/api/excel/table", {
    method: "POST",
    body: excelForm(file, sheet, headerRow, { target }),
  });
}

// One sheet as a CSV File, ready for any CSV upload path.
export async function excelToCsvFile(file, sheet, headerRow) {
  const res = await authedFetch("/api/excel/csv", {
    method: "POST",
    body: excelForm(file, sheet, headerRow),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || `Couldn't read the workbook (${res.status})`);
  }
  const text = await res.text();
  const stem = (file.name || "workbook").replace(/\.[^.]+$/, "");
  return new File([text], `${stem}${sheet ? ` - ${sheet}` : ""}.csv`, { type: "text/csv" });
}

// Create a dataset from pasted tabular text (CSV or TSV; delimiter sniffed
// server-side). Used by the paste-data form and the assistant.
export function pasteDataset(name, content, noHeader = false) {
  return withEvent(
    request("/api/datasets/paste", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: name || "", content: content || "", no_header: !!noHeader }),
    }),
    "dataset_upload"
  );
}

export function deleteDataset(id) {
  return request(`/api/datasets/${id}`, { method: "DELETE" });
}

export function renameDataset(id, name) {
  return request(`/api/datasets/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
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

// Parse another tool's diagram file (BlockSim, Open-PSA, Galileo, RePyability JSON, Excel) into
// builder graphs. Nothing is saved: the builder opens the chosen one unsaved.
// ``mapping`` (Excel only) names the sheets/columns when the workbook doesn't
// follow the template — the server answers code "excel_mapping" when needed.
export function importRbdFile(file, mapping) {
  const form = new FormData();
  form.append("file", file);
  if (mapping) form.append("mapping", JSON.stringify(mapping));
  return withEvent(request("/api/rbds/import", { method: "POST", body: form }), "rbd_import");
}

// The Excel template for RBD import (README + Blocks + Connections example).
export function downloadRbdTemplate() {
  return downloadFile("/api/rbds/import/template.xlsx", "reliafy-rbd-template.xlsx");
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

// A copy of a saved diagram (#290), saved under ``name``: the list row's
// Duplicate. Plan limits apply as for any save.
export async function duplicateRbd(id, name) {
  const full = await getRbd(id);
  return saveRbd(name, full.graph, null, null);
}

// A block's model from its mean (#299): ``{distribution_id, mean, given}``
// (given: the shape or spread, by SurPyval name) or ``{distribution_id,
// params}``; returns {params, mean, median} — SurPyval's.
export function rbdBlockModel(body) {
  return request("/api/rbd-blocks/model", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

// Which distributions take a mean, and what else each needs (cached).
let meanForms = null;
export function rbdMeanForms() {
  if (!meanForms) {
    meanForms = request("/api/rbd-blocks/mean-forms").then((d) => d.forms).catch((e) => {
      meanForms = null;
      throw e;
    });
  }
  return meanForms;
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
  return subscribe("pro");
}

// A grandfathered subscriber to the retired Agent plan moving to Pro is
// switched on their existing subscription server-side; { url } is then just
// the billing page.
function subscribe(plan) {
  return request("/api/billing/subscribe", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ plan }),
  });
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

// Advance the assistant one provider round-trip. Only the message history is
// sent — the server owns the system prompt and the tool definitions. Returns
// the native assistant message, token usage, the metered cost, and the new
// credit balance.
export function assistantStep(messages) {
  return request("/api/assistant/step", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ messages }),
  });
}

// Streaming variant of assistantStep. `onDelta(text)` fires for each chunk of
// assistant text as it's written; resolves to the final payload
// ({ message, stop_reason, usage, credit_cents, ... }) — identical to what
// assistantStep returns — so the caller can continue the tool loop. Throws on a
// non-2xx response (credit/availability errors) or a mid-stream provider error.
export async function assistantStepStream(messages, { onDelta, signal } = {}) {
  const headers = {
    "Content-Type": "application/json",
    ...workspaceHeaders(),
    ...(await authHeaders()),
  };
  const res = await fetch(STREAM_ORIGIN + "/api/assistant/stream", {
    method: "POST",
    headers,
    body: JSON.stringify({ messages }),
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
export function listAgentSessions() {
  return request("/api/reliability-agent/sessions");
}

export function getAgentSession(id) {
  return request(`/api/reliability-agent/sessions/${id}`);
}

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
//
// Repairable graphs run the availability simulation, a paid feature: pass
// ``rbdId`` (the saved diagram being edited) so a saved result can be served
// and stored, and ``force`` to re-run even when one matches. A user without
// the entitlement gets a 402 with ``code: "pro_required"`` unless a saved
// result matches; results carry ``cached`` and ``computed_at``.
// `band` ({ level }) adds a confidence band from the fitted blocks' uncertainty.
// Repairable diagrams (#154/#155): ``simulate`` false gets the exact figures
// (free) without running the paid simulation, true asks for it;
// ``currentState`` ({nodeId: {down: true, since} | {age}}) starts the figures
// from now; ``exact`` computes the figures over time of a large diagram;
// ``quick`` asks for a free, time-capped simulation (users without Pro, #147).
// With the compute queue (#146) the simulation may come back as a job: a 202
// with the exact figures and ``job: {job_id, status, queue_position}`` to poll
// with getRbdJob, whose ``result`` (when done) is the whole payload.
// Non-repairable (#173): ``currentState`` ({nodeId: {failed: true} | {age}})
// analyses the diagram as of now; ``targetReliability`` (e.g. 0.9) adds the
// design life, the time the system reliability falls to it.
export function analyzeRbd(
  graph, tMax, covariates, conditionalAge,
  { rbdId = null, force = false, band = null, simulate = null, currentState = null, exact = false,
    targetReliability = null, quick = false } = {}
) {
  return request("/api/rbds/analyze", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      graph,
      t_max: tMax ?? null,
      covariates: covariates || {},
      conditional_age: conditionalAge ?? null,
      rbd_id: rbdId || null,
      force: !!force,
      ...(band ? { band } : {}),
      ...(simulate != null ? { simulate } : {}),
      ...(currentState ? { current_state: currentState } : {}),
      ...(exact ? { exact: true } : {}),
      ...(targetReliability != null ? { target_reliability: targetReliability } : {}),
      ...(quick ? { quick: true } : {}),
    }),
  });
}

// The node covariate modal's live preview (#52): each covariate's stair-step
// path and the block's R(t) along it, for a saved regression model.
// ``schedules`` {name: {expression} | {table, period?}}, ``constants`` the
// other covariates' values, ``tMax`` the window (null: the model's own).
export function previewRbdSchedule({ modelId, schedules, constants, tMax = null }) {
  return request("/api/rbds/tvc-preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model_id: modelId, schedules: schedules || {}, constants: constants || {}, t_max: tMax }),
  });
}

// An analysis job: {job_id, status: queued|running|done|failed,
// queue_position, result (done), error (failed)}.
export function getRbdJob(jobId) {
  return request(`/api/rbd-jobs/${encodeURIComponent(jobId)}`);
}

// The newest in-flight job for a diagram ({job: null} when none), so a
// reloaded page picks up a simulation still queued or running.
export function getActiveRbdJob(rbdId, kind = null) {
  const k = kind ? `&kind=${encodeURIComponent(kind)}` : "";
  return request(`/api/rbd-jobs?rbd_id=${encodeURIComponent(rbdId)}${k}`);
}

// What to improve (#225): a repairable diagram's levers ranked by what a step
// of each gains. ``costs`` maps lever ids to the cost of making that change;
// ``order`` "benefit" ranks by gain alone, "benefit_per_cost" puts the costed
// levers first by gain per unit spent; ``window`` ranks by the mean over
// [0, window) instead of the long run; ``simulate`` runs the simulated route
// where the diagram needs it (Pro). 200 with the ranked levers (or a
// ``status`` saying why not yet), or 202 with ``job`` to poll at getRbdJob.
export function rbdSensitivity({ graph, rbdId = null, window = null, step = null, rankBy = null, costs = null,
                                 order = null, simulate = false, limits = null }) {
  return request("/api/rbds/sensitivity", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      graph,
      rbd_id: rbdId,
      window,
      step,
      rank_by: rankBy,
      costs,
      order,
      simulate,
      // {lever id: {min, max}} in the values shown (#324).
      ...(limits ? { limits } : {}),
    }),
  });
}

// What to improve's other measures (#225, #325): ``measure`` "over_time",
// "shares" (``groupBy`` "block" | "kind"), "joint", "rate" or "uncertainty"
// (``method`` "delta" | "sobol", ``times`` for the availability at several
// times). 200 with the figures, or 202 with ``job`` to poll at getRbdJob
// (Sobol and times: Pro).
export function rbdMeasures({ graph, rbdId = null, measure, window = null, groupBy = null, method = null,
                              times = null, level = null }) {
  return request("/api/rbds/measures", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      graph,
      rbd_id: rbdId,
      measure,
      window,
      group_by: groupBy,
      method,
      times,
      level,
    }),
  });
}

// Maintenance and proof-test intervals chosen together (#172, #228):
// ``schedule`` "replacement" (age-replacement intervals) or "proof_test";
// one target at most — ``minAvailability``, ``maxPfd``, ``targetSil`` or
// ``maxCostRate`` (none: the lowest cost); ``allowed`` the proof-test
// intervals to choose from (null: a monthly-to-four-yearly calendar);
// ``stagger`` chooses the first tests' times too; ``assumeUnlimitedCrews``
// chooses as if no repair waits for a crew (needed with limited crews).
// Free (exact). 200 with the plan, or 202 with ``job`` to poll at getRbdJob.
export function optimiseIntervals({ graph, rbdId = null, schedule = null, blocks = null, minAvailability = null,
                                    maxPfd = null, targetSil = null, maxCostRate = null, allowed = null,
                                    stagger = false, assumeUnlimitedCrews = false }) {
  return request("/api/rbds/intervals", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      graph,
      rbd_id: rbdId,
      schedule,
      blocks,
      min_availability: minAvailability,
      max_pfd: maxPfd,
      target_sil: targetSil,
      max_cost_rate: maxCostRate,
      allowed,
      stagger,
      assume_unlimited_crews: assumeUnlimitedCrews,
    }),
  });
}

// Compare two repairable designs (#104): ``graph`` (A, the diagram in the
// builder) against the saved diagram ``otherId`` (B). Returns the simulated
// difference in the window's mean availability (B − A) with its interval, from
// common random numbers, plus both exact long-run availabilities. Paid like
// the availability simulation (402 ``pro_required``).
export function compareRbds(graph, otherId, { name = null, otherName = null, tMax = null } = {}) {
  return request("/api/rbds/compare", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      graph,
      other_id: otherId,
      name,
      other_name: otherName,
      t_max: tMax ?? null,
    }),
  });
}

// Check by simulation (#326): a standby or load-sharing block's exact mean
// life beside its simulated mean and 95% interval. ``node`` is the block as
// the builder stores it ({type, data}). Quick and free.
export function checkBlockMean(node, unit = "") {
  return request("/api/rbds/check-block-mean", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ node, unit }),
  });
}

// The cheapest design of a repairable diagram (#99): how many copies of each
// priced block own it for ``horizon`` at the lowest total cost, optionally at
// least ``minAvailability`` available. Returns { current, design, graph, ... };
// ``graph`` has the copies drawn on it (nothing is saved). Paid (402).
// trains: [{name, blocks: [ids]}] copied whole (#227); blocks: [] with them
// copies the trains alone.
export function cheapestRbdDesign({ graph, horizon = null, minAvailability = null, discountRate = null, trains = null, blocks = null }) {
  return withEvent(
    request("/api/rbds/design/cheapest", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ graph, horizon, min_availability: minAvailability, discount_rate: discountRate, trains, blocks }),
    }),
    "rbd_design_cheapest"
  );
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

// The fault tree of an (unsaved) graph (#101): gates over basic events, the
// top event probability at ``t`` and ranked cut sets. ``t`` null = the
// calculator's importance time; repairable graphs are at steady state.
export function rbdFaultTree(graph, t = null, tMax = null) {
  return request("/api/rbds/fault-tree", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ graph, t: t ?? null, t_max: tMax ?? null }),
  });
}

// A phased mission (#160): the (unsaved) graph's phases worked out — mission
// reliability, each phase's failure probability, the riskiest phase.
export function rbdPhases(graph) {
  return request("/api/rbds/phases", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ graph }),
  });
}

// A network's two-terminal reliability (#160) at ``t`` (null = where it's
// about 90%), with ``tMax`` the curve's end (null = automatic).
export function rbdNetwork(graph, t = null, tMax = null) {
  return request("/api/rbds/network", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ graph, t: t ?? null, t_max: tMax ?? null }),
  });
}

// Redundancy design (non-repairable graphs): how many copies of each block.
// ``blocks`` = [{id, cost, weight?, volume?, max_copies, required, strategy,
// switching, name, types: [{name, model, cost, ...}]}]; give ``budget``
// ({cost?, weight?, volume?}) or ``target`` (reliability at ``t``). Returns
// { current, design, front, ... }. Nothing is saved.
export function designRbd({ graph, t, blocks, budget = null, target = null, mixing = true }) {
  return withEvent(
    request("/api/rbds/design", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ graph, t, blocks, budget, target, mixing }),
    }),
    "rbd_design"
  );
}

// The graph with one design (a result's ``design.blocks``) drawn on it, and
// its R(t). The builder puts it on the canvas unsaved.
export function applyRbdDesign({ graph, blocks, design, t }) {
  return request("/api/rbds/design/apply", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ graph, blocks, design, t }),
  });
}

// What each block needs for the system to meet a target (#53): a reliability
// at ``t`` (non-repairable) or a long-run availability (repairable). A 422
// for an unreachable target carries ``err.data.reachable``.
export function allocateRbd({ graph, target, method, t = null, options = {} }) {
  return request("/api/rbds/allocate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ graph, target, method, t, options }),
  });
}

// The production availability (#122): the capacity distribution and the
// share of the demand delivered — ``{production: null}`` without capacities.
export function rbdProduction(graph, t = null) {
  return request("/api/rbds/production", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ graph, t }),
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

function recurrentForm(file, { datasetId, mapping, model, unit, name, options, windows } = {}) {
  const form = new FormData();
  if (name) form.append("name", name);
  if (datasetId) form.append("dataset_id", datasetId);
  else if (file) form.append("file", file);
  form.append("i", mapping.i);
  form.append("x", mapping.x);
  // Optional modifiers, matching the life-data column surface.
  // ``mode`` is each failure's mode (or cause): a growth projection (#232)
  // and the MCF by cause (#65); ``ws``/``we`` observation-window columns.
  ["c", "n", "tl", "tr", "t", "mode", "ws", "we"].forEach((k) => { if (mapping[k]) form.append(k, mapping[k]); });
  // #65: covariate columns, a model's options, windows entered by hand.
  (mapping.z || []).forEach((col) => form.append("z", col));
  if (options?.baseline) form.append("baseline", options.baseline);
  if (options?.m != null && options.m !== "") form.append("m", String(options.m));
  if (windows && String(windows).trim()) form.append("windows", windows);
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

// Optimal overhaul interval (minimal repair between overhauls) — read-only.
export function recurrentOverhaul(id, costRepair, costOverhaul) {
  return request(`/api/recurrent/models/${id}/overhaul`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ cost_repair: costRepair, cost_overhaul: costOverhaul }),
  });
}

// Reliability growth projection (AMSAA-Crow, #232): the panel's inputs (the
// dataset's columns and the failure modes in the chosen column, plus the saved
// settings and result), and a run — saved with the model when you can edit it.
export function getRecurrentProjection(id, modeColumn) {
  const q = modeColumn ? `?mode_column=${encodeURIComponent(modeColumn)}` : "";
  return request(`/api/recurrent/models/${id}/projection${q}`);
}

export function runRecurrentProjection(id, { fef, bc, testEnd, modeColumn, save = true } = {}) {
  return request(`/api/recurrent/models/${id}/projection`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ fef, bc, test_end: testEnd ?? null, mode_column: modeColumn || null, save }),
  });
}

// ---- Accelerated Life Testing (ALT) ----------------------------------------
export function getAltOptions() {
  return request("/api/alt/options");
}

function altForm(file, { datasetId, mapping, stress, distribution, lifeModel, unit, name } = {}) {
  const form = new FormData();
  if (name) form.append("name", name);
  if (datasetId) form.append("dataset_id", datasetId);
  else if (file) form.append("file", file);
  // The failure time x, or inspection data's interval xl / xr (#237).
  ["x", "xl", "xr", "c", "n", "tl", "tr"].forEach((k) => { if (mapping[k]) form.append(k, mapping[k]); });
  // stress = [{col,label}, …]; s1 required, s2 optional.
  if (stress[0]) { form.append("s1", stress[0].col); if (stress[0].label) form.append("s1_label", stress[0].label); }
  if (stress[1]) { form.append("s2", stress[1].col); if (stress[1].label) form.append("s2_label", stress[1].label); }
  // Optional stress units, e.g. "K" or "kV" (#265).
  if (stress[0]?.unit?.trim()) form.append("s1_unit", stress[0].unit.trim());
  if (stress[1]?.unit?.trim()) form.append("s2_unit", stress[1].unit.trim());
  if (distribution) form.append("distribution", distribution);
  if (lifeModel) form.append("life_model", lifeModel);
  if (unit) form.append("unit", unit);
  return form;
}

export function fitAlt(file, opts) {
  return request("/api/alt/fit", { method: "POST", body: altForm(file, opts) });
}

export function saveAltModel(name, file, opts) {
  return withEvent(
    request("/api/alt/models", { method: "POST", body: altForm(file, { ...opts, name }) }),
    "alt_save"
  );
}

export function listAltModels() {
  return request("/api/alt/models");
}

export function getAltModel(id) {
  return request(`/api/alt/models/${id}`);
}

export function renameAltModel(id, name) {
  return request(`/api/alt/models/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
}

export function deleteAltModel(id) {
  return request(`/api/alt/models/${id}`, { method: "DELETE" });
}

// Use-level reliability with its Wald confidence bounds (#231). ``opts``:
// { missionTime, confidence }.
export function evaluateAlt(id, useStress, refStress, opts = {}) {
  return request(`/api/alt/models/${id}/evaluate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      use_stress: useStress,
      ...(refStress ? { ref_stress: refStress } : {}),
      ...(opts.missionTime != null ? { mission_time: opts.missionTime } : {}),
      ...(opts.confidence != null ? { confidence: opts.confidence } : {}),
    }),
  });
}

// Confidence bounds at a use stress by method (wald | lr | bootstrap, #231):
// the bounds, or (bootstrap with the compute queue) ``{ job }`` to poll at
// getRbdJob. A 402 (code pro_required) means bootstrap needs Pro or credits.
export function altBounds(id, { useStress, method, confidence, missionTime, tMax }) {
  return request(`/api/alt/models/${id}/bounds`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      use_stress: useStress,
      method,
      ...(confidence != null ? { confidence } : {}),
      ...(missionTime != null ? { mission_time: missionTime } : {}),
      ...(tMax != null ? { t_max: tMax } : {}),
    }),
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

// The failure-time distribution the path model induces (Lu-Meeker, #63):
// its curve, mean and median; ``body`` may ask { times: [t] } for the
// reliability at each and { reliability: [R] } for the time each is reached.
export function degradationInducedLife(id, body = {}) {
  return request(`/api/degradation/models/${id}/induced-life`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
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

// Plan a reliability demonstration test (units, test time, allowed failures).
export function demonstrationTest(body) {
  return request("/api/strategy/demonstration-test", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
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

// What an FMEA / RCM spreadsheet would import as (nothing saved): the tree,
// counts, warnings and the consequence / decision values found.
// ``options`` = { mapping, consequence_map, outcome_map, extra_columns }.
export function previewRcmImport(file, sheet, headerRow, options) {
  return request("/api/rcm/import/preview", {
    method: "POST",
    body: excelForm(file, sheet, headerRow, { options }),
  });
}

// Import the worksheet: a new study (``target.name``) or an existing one
// (``target.studyId`` with mode "append" | "replace").
export function importRcmWorksheet(file, sheet, headerRow, options, target) {
  return withEvent(
    request("/api/rcm/import", {
      method: "POST",
      body: excelForm(file, sheet, headerRow, {
        options,
        study_id: target.studyId,
        mode: target.mode,
        expected_updated_at: target.expectedUpdatedAt,
        name: target.name,
        system: target.system,
        description: target.description,
      }),
    }),
    "rcm_import"
  );
}

// A study's tasks as a repairable RBD block's maintenance (#100): what each
// would fill in a diagram in `unit` (scheduled replacement or proof test), or
// why it can't.
export function getRcmMaintenanceTasks(id, unit) {
  return request(`/api/rcm/studies/${id}/maintenance-tasks?unit=${encodeURIComponent(unit || "")}`);
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

// A new link (an artifact can have several). ``options``: { label,
// expires_in_days, password, generate_password }. A generated passphrase
// comes back once, as ``passphrase``.
export function createPublicLink(collection, artifactId, options = {}) {
  return request("/api/public-links", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ collection, artifact_id: artifactId, ...options }),
  });
}

// Every live link to an artifact, newest first: { links: [...] }.
export function listPublicLinks(collection, artifactId) {
  const q = new URLSearchParams({ collection, artifact_id: artifactId });
  return request(`/api/public-links?${q}`);
}

// Relabel, or set / rotate / remove the password: { label } |
// { password } | { generate_password: true } | { remove_password: true }.
export function updatePublicLink(token, changes) {
  return request(`/api/public-links/${encodeURIComponent(token)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(changes),
  });
}

export function revokePublicLink(token) {
  return request(`/api/public-links/${encodeURIComponent(token)}`, { method: "DELETE" });
}

// The header that carries a password-protected link's unlock token.
const UNLOCK_HEADER = "X-Share-Unlock";
const unlockHeaders = (unlock) => (unlock ? { [UNLOCK_HEADER]: unlock } : {});

// Unauthenticated: resolve a public link to its artifact payload. A
// protected link without a valid unlock token rejects with status 401 and
// ``passwordRequired`` set.
export async function getPublicArtifact(token, unlock) {
  try {
    return await publicRequest(`/api/public/${encodeURIComponent(token)}`, { headers: unlockHeaders(unlock) });
  } catch (err) {
    if (err.status === 401) err.passwordRequired = true;
    throw err;
  }
}

// Trade a protected link's password for an unlock token:
// { unlock_token, expires_at }.
export function unlockPublicLink(token, password) {
  return publicRequest(`/api/public/${encodeURIComponent(token)}/unlock`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ password }),
  });
}

// ---- File downloads -----------------------------------------------------------

// The file name from a Content-Disposition header (plain or RFC 5987 form).
function dispositionFilename(header, fallback) {
  if (!header) return fallback;
  const star = /filename\*\s*=\s*(?:UTF-8'')?([^;]+)/i.exec(header);
  if (star) {
    try {
      return decodeURIComponent(star[1].trim().replace(/^"|"$/g, ""));
    } catch {
      /* fall through to the plain form */
    }
  }
  const plain = /filename\s*=\s*"?([^";]+)"?/i.exec(header);
  return plain ? plain[1].trim() : fallback;
}

// Fetch a file with the auth header and hand it to the browser as a download.
async function downloadFile(url, fallbackName, opts = {}, fetcher = authedFetch) {
  const res = await fetcher(url, opts);
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    const err = new Error(data.detail || `Download failed (${res.status})`);
    err.status = res.status;
    throw err;
  }
  const blob = await res.blob();
  const name = dispositionFilename(res.headers.get("Content-Disposition"), fallbackName);
  const href = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = href;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  // Give the browser a moment to start the download before revoking.
  setTimeout(() => URL.revokeObjectURL(href), 1000);
  return name;
}

export const PYTHON_EXPORT_TIP =
  "A standalone script that rebuilds this diagram with SurPyval + RePyability and runs it locally.";

// "Download as Python": a standalone SurPyval + RePyability script that
// rebuilds a saved RBD and runs the same calculation locally. Free for every
// viewer of the diagram.
export function downloadRbdPython(id) {
  return withEvent(
    downloadFile(`/api/rbds/${encodeURIComponent(id)}/export.py`, "rbd.py"),
    "rbd_export_python"
  );
}

export const JSON_EXPORT_TIP =
  "The diagram in RePyability's JSON format: load it in Python with rbd_from_json, or import it back into Reliafy.";

// "Download as RePyability JSON" (#174): the saved diagram as RePyability's
// to_json document (plus Reliafy's labels and layout, which RePyability
// ignores). Free for every viewer, like the Python download.
export function downloadRbdJson(id) {
  return withEvent(
    downloadFile(`/api/rbds/${encodeURIComponent(id)}/export.json`, "rbd.json"),
    "rbd_export_json"
  );
}

// The same download for a publicly linked RBD (no sign-in needed; a
// protected link sends its unlock token).
export function downloadPublicRbdPython(token, unlock) {
  return downloadFile(`/api/public/${encodeURIComponent(token)}/export.py`, "rbd.py", {
    headers: unlockHeaders(unlock),
  }, (u, o) => fetch(u, o));
}

// ---- Personal API tokens ------------------------------------------------------

export function listApiTokens() {
  return request("/api/tokens");
}

// ``scopes``: any of "ingest", "read", "write".
export function createApiToken(name, scopes) {
  return request("/api/tokens", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, scopes }),
  });
}

export function revokeApiToken(id) {
  return request(`/api/tokens/${id}`, { method: "DELETE" });
}

// ---- OAuth: connecting Claude (and other MCP clients) --------------------------

// The pending authorization request behind /oauth/consent?request=<handle>:
// client name, where the browser will be sent back to, loopback or not.
export function getOAuthRequest(handle) {
  return request(`/oauth/authorize/request?request=${encodeURIComponent(handle)}`);
}

// Approve or deny it as the signed-in user; resolves to { redirect_to }.
export function decideOAuthRequest(handle, approve) {
  return request("/oauth/authorize/decision", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ request: handle, approve }),
  });
}

// Settings > Connected apps.
export function listOAuthGrants() {
  return request("/api/me/oauth-grants");
}

export function revokeOAuthGrant(id) {
  return request(`/api/me/oauth-grants/${encodeURIComponent(id)}`, { method: "DELETE" });
}

// Operator-only stats (403 for regular accounts).
export function getAdminStats() {
  return request("/api/admin/stats");
}

// Operator-only: new accounts in the last `days` days, and the latest few.
export function getAdminSignups(days = 7) {
  return request(`/api/admin/signups?days=${days}`);
}

// Operator-only first-party traffic analytics.
export function getAdminTraffic(days = 14) {
  return request(`/api/admin/traffic?days=${days}`);
}

// Operator-only: what each update / lifecycle email brought in (#269).
export function getAdminEmailCampaigns(days = 90) {
  return request(`/api/admin/email-campaigns?days=${days}`);
}

// Operator-only product usage (app / MCP / API, the MCP plan wall).
export function getAdminUsage(days = 30, includeAdmin = false) {
  return request(`/api/admin/usage?days=${days}${includeAdmin ? "&include_admin=true" : ""}`);
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

// ``modelKind``: what ``modelId`` is — "life" (a saved life model; the server
// stores "regression" when it's a regression model, #234), "alt" (an ALT
// model, #234) or "recurrent" (a recurrent-event model — repairable items,
// every failure counted; #235).
export function createFleet(name, modelId, modelKind = "life") {
  return request("/api/fleet/fleets", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, model_id: modelId, model_kind: modelKind }),
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

// Alerts on a fleet's expected failures (evaluated when usage arrives via the API).
export function listFleetAlerts(id) {
  return request(`/api/fleet/fleets/${id}/alerts`);
}

export function createFleetAlert(id, rule) {
  return request(`/api/fleet/fleets/${id}/alerts`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(rule),
  });
}

export function updateFleetAlert(id, alertId, changes) {
  return request(`/api/fleet/fleets/${id}/alerts/${alertId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(changes),
  });
}

export function deleteFleetAlert(id, alertId) {
  return request(`/api/fleet/fleets/${id}/alerts/${alertId}`, { method: "DELETE" });
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

// ---- Product-update emails ------------------------------------------------------

// Unsubscribe links carry a signed token (?t=) and work signed-out, so these
// need no user — request() simply sends no Authorization header then.
// Each returns { email (masked), subscribed }; an unknown token is a 404.
function emailTokenUrl(path, token) {
  return `/api/email/${path}?t=${encodeURIComponent(token)}`;
}

export function unsubscribeEmail(token) {
  return request(emailTokenUrl("unsubscribe", token), { method: "POST" });
}

export function resubscribeEmail(token) {
  return request(emailTokenUrl("resubscribe", token), { method: "POST" });
}

// The signed-in user's email preferences: { updates: bool }.
export function getEmailPreferences() {
  return request("/api/me/email-preferences");
}

export function setEmailPreferences(prefs) {
  return request("/api/me/email-preferences", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(prefs),
  });
}

// ---- Outage logs: an RBD's observed history (issue #159) -------------------

function outageJson(method, url, body) {
  return request(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
}

export function listOutageLogs(rbdId) {
  return request(`/api/rbds/${rbdId}/outage-logs`);
}

// Check a log before saving: headers, detected mapping, parsed outages or
// every error (ok: false). Body: { csv, mapping?, unit?, window_start?,
// window_end?, date_order?, asset_map? }.
export function previewOutageLog(rbdId, body) {
  return outageJson("POST", `/api/rbds/${rbdId}/outage-logs/preview`, body);
}

export function saveOutageLog(rbdId, body) {
  return outageJson("POST", `/api/rbds/${rbdId}/outage-logs`, body);
}

export function updateOutageLog(rbdId, logId, body) {
  return outageJson("PATCH", `/api/rbds/${rbdId}/outage-logs/${logId}`, body);
}

export function deleteOutageLog(rbdId, logId) {
  return request(`/api/rbds/${rbdId}/outage-logs/${logId}`, { method: "DELETE" });
}

export function getOutageHistory(rbdId, logId) {
  return request(`/api/rbds/${rbdId}/outage-logs/${logId}/history`);
}

export function fitOutageModels(rbdId, logId, body) {
  return outageJson("POST", `/api/rbds/${rbdId}/outage-logs/${logId}/fit`, body);
}
