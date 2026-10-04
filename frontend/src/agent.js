// The Reliafy assistant's tool executor: runs the tools the model calls
// against the app. The prompt and tool definitions live on the server;
// transport to the LLM providers lives in llm.js. Provider-agnostic.
import {
  listDatasets,
  listModels,
  getModel,
  evaluateAt,
  getDistributions,
  pasteDataset,
  saveModel,
  listRbds,
  saveRbd,
  validateRbd,
  optimalReplacement,
  compareTwoModels,
  failureFinding,
  saveStrategyAnalysis,
  listStrategyAnalyses,
  listDegradationModels,
  getDegradationModel,
  saveDegradationModel,
  createTrackedItem,
  addTrackedMeasurement,
  listRcmStudies,
  createRcmStudy,
  getRcmStudy,
  putRcmTree,
  createShare,
  getDataset,
  getRbd,
  getStrategyAnalysis,
  listFleets,
  getFleet,
  getRecurrentModel,
  createFleet,
  putFleetItems,
} from "./api.js";
import { getRbdCanvas, waitForRbdCanvas } from "./rbdBridge.js";
import { normalizeRbdGraph, compactGraph } from "./rbdGraph.js";

// Linear interpolation of a reliability curve y at time xq (mirrors the
// calculator's read-off). null y points are gaps; returns null outside the
// grid or across a gap, and rounds to a readable precision.
function interpCurve(x, y, xq) {
  if (!x || !y || xq < x[0] || xq > x[x.length - 1]) return null;
  for (let i = 1; i < x.length; i++) {
    if (xq <= x[i]) {
      const y0 = y[i - 1], y1 = y[i];
      if (y0 == null || y1 == null) return null;
      const x0 = x[i - 1], x1 = x[i];
      const v = x1 === x0 ? y0 : y0 + ((xq - x0) / (x1 - x0)) * (y1 - y0);
      return v == null ? null : Number(v.toPrecision(5));
    }
  }
  return null;
}

// The assistant's system prompt and tool definitions are the server's
// (backend/services/assistant_spec.py) — the backend sends them with every
// step, so a client can't change them. This file runs the tools: each tool
// defined there needs a case in makeExecutor below (a backend test checks).

// Only let the assistant route to real in-app pages.
const NAV_PREFIXES = [
  "/modelling", "/rbds", "/datasets", "/strategy", "/fleet", "/rcm", "/team",
];
export function isAllowedPath(path) {
  return typeof path === "string" && path.startsWith("/") && NAV_PREFIXES.some(
    (p) => path === p || path.startsWith(p + "/")
  );
}

function columnNames(cols) {
  return (cols || []).map((c) => (typeof c === "string" ? c : c.name));
}

// Compact per-item prediction summary for tool results (keeps tokens down).
function itemSummary(it) {
  const p = it.prediction || {};
  return {
    id: it.id,
    name: it.name,
    n_measurements: it.n_measurements ?? (it.measurements || []).length,
    last_reading: it.measurements?.length
      ? it.measurements[it.measurements.length - 1]
      : null,
    remaining_life: p.rul ?? null,
    remaining_life_interval: p.rul_interval ?? null,
    predicted_crossing: p.failure_time ?? null,
    prob_failed: p.prob_failed ?? null,
    prediction_issue: p.method === "error" ? p.detail : undefined,
    read_only: !!it.read_only,
  };
}

// Compact per-decision summary of a resolved RCM tree.
function rcmTreeSummary(functions) {
  return (functions || []).map((fn) => ({
    id: fn.id,
    text: fn.text,
    failures: (fn.failures || []).map((f) => ({
      id: f.id,
      text: f.text,
      modes: (f.modes || []).map((m) => ({
        id: m.id,
        text: m.text,
        effects: m.effects,
        consequence: m.consequence,
        decision: m.decision
          ? {
              outcome: m.decision.outcome,
              rtf_basis: m.decision.rtf_basis,
              task: m.decision.task,
              interval: m.decision.interval,
              interval_unit: m.decision.interval_unit,
              evidence: m.decision.evidence,
              status: m.decision.status,
              summary: m.decision.summary || m.decision.reason,
            }
          : null,
      })),
    })),
  }));
}

// What each shareable collection is called, and how to read one item's name.
const ARTIFACTS = {
  datasets: ["dataset", getDataset],
  models: ["model", getModel],
  rbds: ["RBD", getRbd],
  degradation_models: ["degradation model", getDegradationModel],
  strategy_analyses: ["strategy analysis", getStrategyAnalysis],
  rcm_studies: ["RCM study", getRcmStudy],
  fleets: ["failure forecast", getFleet],
  recurrent_models: ["recurrent-event model", getRecurrentModel],
};

async function artifactName(collection, id) {
  const get = ARTIFACTS[collection]?.[1];
  if (!get || !id) return null;
  try {
    const doc = await get(id);
    return doc?.name || null;
  } catch {
    return null;
  }
}

// Ask the person before an action that shares their work or replaces saved
// content. Only their click in the app's dialog counts — the model can't
// answer it — and with no way to ask, the action doesn't happen.
async function userConfirms(confirm, request) {
  if (typeof confirm !== "function") return false;
  try {
    return (await confirm(request)) === true;
  } catch {
    return false;
  }
}

const DECLINED = {
  ok: false,
  declined: true,
  error: "The user declined this in the confirmation dialog. Don't retry unless they ask again.",
};

const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

// Build the tool executor. `navigate` is react-router's navigate; `onChange`
// is an optional callback fired after a mutating action (so the UI can
// refresh); `confirm({ title, body, confirmLabel })` shows the user a dialog
// and resolves true only when they click to go ahead. Sharing and replacing
// saved content (an existing RBD, an RCM worksheet, a fleet's items) always
// go through it.
export function makeExecutor({ navigate, onChange, confirm }) {
  return async function execute(name, input = {}) {
    switch (name) {
      case "list_datasets": {
        const { datasets } = await listDatasets();
        return datasets.map((d) => ({
          id: d.id, name: d.name, n_rows: d.n_rows,
          columns: columnNames(d.columns), is_sample: !!d.is_sample,
        }));
      }
      case "list_models": {
        const { models } = await listModels();
        return models.map((m) => ({
          id: m.id, name: m.name, distribution: m.distribution,
          n: m.n, is_sample: !!m.is_sample,
          randomness: m.randomness?.verdict || null,
        }));
      }
      case "list_distributions": {
        const { distributions } = await getDistributions();
        return distributions.map((d) => ({ id: d.id, name: d.name, covariates: !!d.covariates }));
      }
      case "save_dataset": {
        const csv = String(input.csv ?? "");
        if (!csv.trim()) throw new Error("csv is empty");
        const ds = await pasteDataset(input.name || "Dataset", csv);
        onChange?.();
        return { id: ds.id, name: ds.name, n_rows: ds.n_rows, columns: columnNames(ds.columns) };
      }
      case "create_model": {
        if (!input.dataset_id) throw new Error("dataset_id is required (save a dataset first)");
        const mapping = input.mapping || {};
        const m = await saveModel(
          input.name || "Model",
          input.distribution,
          null,
          mapping,
          { datasetId: input.dataset_id, unit: input.unit, covariates: input.covariates }
        );
        onChange?.();
        return {
          id: m.id, name: m.name,
          distribution: m.distribution || input.distribution,
          randomness: m.randomness?.verdict || null,
        };
      }
      case "get_model": {
        if (!input.model_id) throw new Error("model_id is required");
        const m = await getModel(input.model_id);
        const r = m.results || {};
        const cov = r.functions?.covariates;
        return {
          id: m.id,
          name: m.name,
          distribution: r.distribution || m.distribution,
          distribution_id: r.distribution_id,
          kind: m.kind,
          unit: r.unit || m.unit || "",
          n: r.n ?? m.n ?? null,
          params: (r.params || []).map((p) => ({ name: p.name, value: p.value, ci: p.ci || null })),
          coefficients: (r.coefficients || []).map((c) => ({
            name: c.name, value: c.value, hazard_ratio: c.hazard_ratio,
          })),
          metrics: r.metrics || null,
          goodness_of_fit: (r.gof || []).map((g) => ({ id: g.id, label: g.label, value: g.value })),
          randomness: r.randomness?.verdict || null,
          // For PH models: the covariate inputs evaluate_reliability accepts.
          covariates: cov ? cov.map((c) => ({
            name: c.name, type: c.type, default: c.default, options: c.options,
          })) : null,
        };
      }
      case "evaluate_reliability": {
        if (!input.model_id) throw new Error("model_id is required");
        const m = await getModel(input.model_id);
        const r = m.results || {};
        const fns = r.functions;
        if (!fns?.curves) {
          throw new Error("This model has no reliability functions to evaluate (e.g. a per-demand model).");
        }
        const unit = r.unit || m.unit || "";
        // PH models re-evaluate at a covariate combination; others use the
        // fitted curves directly (they don't depend on covariates).
        const hasCov = (fns.covariates || []).length > 0 && !!fns.evaluate_path;
        let curves = fns.curves;
        let covariatesUsed = null;
        if (hasCov) {
          const values = { ...Object.fromEntries((fns.covariates || []).map((c) => [c.name, c.default])), ...(input.covariates || {}) };
          const res = await evaluateAt(fns.evaluate_path, values);
          curves = res.curves;
          covariatesUsed = values;
        }
        const out = {
          model: m.name,
          unit,
          metrics: r.metrics || null,
          covariates: covariatesUsed,
        };
        if (input.t != null) {
          const t = Number(input.t);
          out.at = {
            t,
            reliability: interpCurve(curves.x, curves.sf, t),
            failure_probability: interpCurve(curves.x, curves.ff, t),
            hazard: interpCurve(curves.x, curves.hf, t),
            cumulative_hazard: interpCurve(curves.x, curves.Hf, t),
            density: interpCurve(curves.x, curves.df, t),
          };
        } else {
          // No time given: a few reference reliability points across the range.
          const xs = curves.x || [];
          const lo = xs[0], hi = xs[xs.length - 1];
          out.reference_points = [0.25, 0.5, 0.75].map((f) => {
            const t = lo + f * (hi - lo);
            return { t: Number(t.toPrecision(4)), reliability: interpCurve(xs, curves.sf, t) };
          });
        }
        return out;
      }
      case "list_rbds": {
        const { rbds } = await listRbds();
        return rbds.map((r) => ({ id: r.id, name: r.name, n_nodes: r.n_nodes, n_edges: r.n_edges, is_sample: !!r.is_sample }));
      }
      case "get_current_rbd": {
        const canvas = getRbdCanvas();
        if (!canvas) return { open: false, message: "The RBD builder isn't open. Navigate to /rbds/b (or use set_current_rbd, which opens it)." };
        return { open: true, graph: compactGraph(canvas.getGraph()) };
      }
      case "set_current_rbd": {
        let canvas = getRbdCanvas();
        if (!canvas) {
          navigate("/rbds/b");
          canvas = await waitForRbdCanvas();
        }
        if (!canvas) return { ok: false, error: "Couldn't open the RBD builder." };
        canvas.applyGraph({ nodes: input.nodes || [], edges: input.edges || [], unit: input.unit });
        onChange?.();
        return { ok: true, n_nodes: (input.nodes || []).length, n_edges: (input.edges || []).length };
      }
      case "save_rbd": {
        if (input.id) {
          const current = await artifactName("rbds", input.id);
          if (!current) return { ok: false, error: `RBD not found: ${input.id}` };
          const renamed = input.name && input.name !== current ? ` (renamed “${input.name}”)` : "";
          const ok = await userConfirms(confirm, {
            title: "Replace a saved RBD?",
            body: `The assistant wants to overwrite the saved RBD “${current}” with a new diagram${renamed}. Anyone who can see it will see the change.`,
            confirmLabel: "Replace",
          });
          if (!ok) return DECLINED;
        }
        // Keep the unit: a saved diagram with a blank unit reads its parameters
        // in nothing. Fall back to whatever the open canvas has.
        const unit = input.unit ?? getRbdCanvas()?.getGraph()?.unit;
        const graph = normalizeRbdGraph({ nodes: input.nodes || [], edges: input.edges || [], unit });
        const r = await saveRbd(input.name || "Diagram", graph, input.id);
        onChange?.();
        return { id: r.id, name: r.name, n_nodes: r.n_nodes, n_edges: r.n_edges };
      }
      case "validate_rbd": {
        const graph = normalizeRbdGraph({ nodes: input.nodes || [], edges: input.edges || [] });
        const v = await validateRbd(graph);
        return { valid: v.valid, can_calculate: v.can_calculate, errors: v.errors || [], warnings: v.warnings || [] };
      }
      case "optimal_replacement": {
        return await optimalReplacement(
          input.distribution_id, input.params,
          input.planned_cost, input.unplanned_cost, input.unit
        );
      }
      case "compare_two_models": {
        return await compareTwoModels(input.a, input.b, input.unit);
      }
      case "failure_finding_interval": {
        return await failureFinding(
          input.distribution_id, input.params, input.target_availability, input.unit
        );
      }
      case "save_strategy_analysis": {
        const doc = await saveStrategyAnalysis(input.name, input.kind, input.inputs || {});
        onChange?.();
        return { id: doc.id, name: doc.name, kind: doc.kind, headline: doc.headline };
      }
      case "list_strategy_analyses": {
        const { analyses } = await listStrategyAnalyses();
        return analyses.map((a) => ({
          id: a.id, name: a.name, kind: a.kind,
          headline: a.headline, is_sample: !!a.is_sample,
        }));
      }
      case "create_degradation_model": {
        if (!input.dataset_id) throw new Error("dataset_id is required (save a dataset first)");
        const doc = await saveDegradationModel(input.name || "Degradation model", null, {
          datasetId: input.dataset_id,
          mapping: input.mapping,
          threshold: input.threshold,
          path: input.path,
          distribution: input.distribution,
          unit: input.unit,
          measurementUnit: input.measurement_unit,
        });
        onChange?.();
        return {
          id: doc.id, name: doc.name,
          path_model: doc.path_model, threshold: doc.threshold,
          n_units: doc.n_units,
          mean_life: doc.results?.life_model?.mean ?? null,
        };
      }
      case "list_degradation_models": {
        const { models } = await listDegradationModels();
        return models.map((m) => ({
          id: m.id, name: m.name, path_model: m.path_model,
          threshold: m.threshold, measurement_unit: m.measurement_unit,
          unit: m.unit, n_items: m.n_items, is_sample: !!m.is_sample,
        }));
      }
      case "get_degradation_model": {
        const doc = await getDegradationModel(input.id);
        return {
          id: doc.id, name: doc.name, path_model: doc.path_model,
          threshold: doc.threshold, measurement_unit: doc.measurement_unit,
          unit: doc.unit, n_units: doc.n_units, read_only: !!doc.read_only,
          items: (doc.items || []).map(itemSummary),
        };
      }
      case "register_tracked_item": {
        const item = await createTrackedItem(input.model_id, {
          name: input.name, measurements: input.measurements || [],
        });
        onChange?.();
        return itemSummary(item);
      }
      case "add_measurement": {
        const item = await addTrackedMeasurement(input.model_id, input.item_id, input.t, input.y);
        onChange?.();
        return itemSummary(item);
      }
      case "list_rcm_studies": {
        const { studies } = await listRcmStudies();
        return studies.map((s) => ({
          id: s.id, name: s.name, system: s.system,
          rollup: s.rollup, is_sample: !!s.is_sample,
        }));
      }
      case "get_rcm_study": {
        const s = await getRcmStudy(input.id);
        return {
          id: s.id, name: s.name, system: s.system, rollup: s.rollup,
          read_only: !!s.read_only,
          functions: rcmTreeSummary(s.functions),
        };
      }
      case "create_rcm_study": {
        const s = await createRcmStudy(input.name, input.system || "", input.description || "");
        onChange?.();
        return { id: s.id, name: s.name };
      }
      case "set_rcm_tree": {
        const study = await artifactName("rcm_studies", input.study_id);
        if (!study) return { ok: false, error: `RCM study not found: ${input.study_id}` };
        const ok = await userConfirms(confirm, {
          title: "Replace an RCM worksheet?",
          body: `The assistant wants to replace the whole worksheet of the RCM study “${study}” with ${plural((input.functions || []).length, "function")}.`,
          confirmLabel: "Replace",
        });
        if (!ok) return DECLINED;
        const s = await putRcmTree(input.study_id, input.functions || []);
        onChange?.();
        return { id: s.id, rollup: s.rollup, functions: rcmTreeSummary(s.functions) };
      }
      case "list_fleets": {
        const { fleets } = await listFleets();
        return fleets.map((f) => ({
          id: f.id, name: f.name, n_items: f.n_items,
          headline: f.headline, is_sample: !!f.is_sample,
        }));
      }
      case "get_fleet_forecast": {
        const f = await getFleet(input.id);
        return {
          id: f.id, name: f.name, model_id: f.model_id, settings: f.settings,
          items: f.items, forecast: f.forecast, read_only: !!f.read_only,
        };
      }
      case "create_fleet_forecast": {
        const f = await createFleet(input.name, input.model_id);
        onChange?.();
        return { id: f.id, name: f.name };
      }
      case "set_fleet_items": {
        const fleet = await artifactName("fleets", input.fleet_id);
        if (!fleet) return { ok: false, error: `Failure forecast not found: ${input.fleet_id}` };
        const ok = await userConfirms(confirm, {
          title: "Replace a forecast's items?",
          body: `The assistant wants to replace the settings and every item of the failure forecast “${fleet}” with ${plural((input.items || []).length, "item")}.`,
          confirmLabel: "Replace",
        });
        if (!ok) return DECLINED;
        const f = await putFleetItems(input.fleet_id, input.settings || {}, input.items || []);
        onChange?.();
        return { id: f.id, forecast: f.forecast };
      }
      case "share_artifact": {
        const noun = ARTIFACTS[input.collection]?.[0];
        if (!noun) return { ok: false, error: `Unknown collection: ${input.collection}` };
        const email = String(input.email || "").trim();
        if (!email) return { ok: false, error: "email is required" };
        const artifact = await artifactName(input.collection, input.artifact_id);
        if (!artifact) return { ok: false, error: `Not found: ${input.artifact_id}` };
        const ok = await userConfirms(confirm, {
          title: "Share with another account?",
          body: `Share the ${noun} “${artifact}” with ${email}? They'll be able to view it.`,
          confirmLabel: "Share",
        });
        if (!ok) return DECLINED;
        const r = await createShare(input.collection, input.artifact_id, email);
        return { ok: true, shared_with: r.email };
      }
      case "navigate": {
        if (!isAllowedPath(input.path)) {
          return { ok: false, error: `Not an allowed path: ${input.path}` };
        }
        navigate(input.path);
        return { ok: true, path: input.path };
      }
      default:
        return { error: `Unknown tool: ${name}` };
    }
  };
}
