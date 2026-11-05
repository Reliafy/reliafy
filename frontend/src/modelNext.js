// Next steps from a fitted non-repairable model (#294): which tools can take it, the
// links that open them with the model chosen, the model a Strategy tool
// starts on, a saved model as a picker / RBD block value, and the block a
// model becomes when it's added to a diagram. Pure functions (plus a guarded
// localStorage memo), so `node --test` covers them.

export const SAMPLE_SUFFIX = /\s*\(sample\)\s*$/i;

// A model's name without the shared samples' "(sample)" suffix.
export const plainName = (name) => String(name || "").replace(SAMPLE_SUFFIX, "").trim();

// The tools a model of this kind can be used in. ``result`` is the fit's
// results payload (``kind``, ``distribution_id``). Replacement needs one
// plain parametric distribution; a fleet forecast and an RBD block also take
// a regression model (each item or block at its own covariates).
export function nextStepsFor(result) {
  const kind = result?.kind || "distribution";
  const id = result?.distribution_id || "";
  const parametric = kind === "distribution" && id !== "mixture" && id !== "best";
  const block = kind === "distribution" || kind === "regression";
  return {
    replacement: parametric,
    fleet: block && !result?.tvc,
    test: kind === "distribution" || kind === "nonparametric" || kind === "flexible" || kind === "discrete",
    rbd: block && !result?.tvc,
  };
}

// Each tool's name, and what it gives you in a line (the "Use this model"
// dialog lists both), in the order they're offered.
export const STEP_LABELS = {
  replacement: "Find the best replacement interval",
  fleet: "Forecast a fleet",
  test: "Plan a demonstration test",
  rbd: "Add to an RBD",
};
export const STEP_WHAT = {
  replacement: "The age to replace at for the lowest cost, from this model and your planned and failure costs.",
  fleet: "How many failures a fleet will see over a horizon, and the spares to hold.",
  test: "How many units to test, and for how long, to show a reliability target.",
  rbd: "This model as a block in a reliability block diagram: a new one or one of yours.",
};

// The steps a result offers, in that order, less any in ``skip``.
export function stepsFor(result, skip = []) {
  const can = nextStepsFor(result);
  return Object.keys(STEP_LABELS).filter((s) => can[s] && !skip.includes(s));
}

const withModel = (path, id, extra = {}) => {
  const q = new URLSearchParams({ ...extra, model: id });
  return `${path}?${q.toString()}`;
};

// The tool pages, opened with the saved model ``id`` chosen.
export function nextStepLink(step, id, { unit = "" } = {}) {
  if (step === "replacement") return withModel("/strategy/replacement", id);
  if (step === "fleet") return withModel("/forecasts", id, { new: "1" });
  if (step === "test") return withModel("/strategy/test-planning", id, unit ? { unit } : {});
  return null;
}

// The model id a link carries (``?model=``), or null.
export function modelFromSearch(search) {
  const id = new URLSearchParams(search || "").get("model");
  return id && /^[\w.:-]{1,200}$/.test(id) ? id : null;
}

// The most recently used model, remembered per browser. Storage can be
// missing or throw (a private window): then nothing is remembered.
const RECENT_KEY = "reliafy:recent-model";

export function rememberModel(id) {
  if (!id) return;
  try {
    window.localStorage.setItem(RECENT_KEY, String(id));
  } catch {
    /* no storage: nothing to remember */
  }
}

export function recentModel() {
  try {
    return window.localStorage.getItem(RECENT_KEY) || null;
  } catch {
    return null;
  }
}

// The model a Strategy tool starts on, from the models it can use: the one
// the link asked for, else the one used most recently, else the newest of
// the user's own (a shared sample only when they have none).
export function preferredModel(models, { wanted = null, recent = null } = {}) {
  const list = models || [];
  const has = (id) => id && list.some((m) => m.id === id);
  if (has(wanted)) return wanted;
  if (has(recent)) return recent;
  const newest = (rows) => [...rows].sort((a, b) => String(b.created_at || "").localeCompare(String(a.created_at || "")))[0];
  const own = list.filter((m) => !m.is_sample);
  return (newest(own.length ? own : list) || {}).id || null;
}

// A saved model (``getModel``'s answer) as the value a model picker emits and
// an RBD block carries: the id, so the server reads the saved model, plus
// what the client shows and evaluates.
export function savedModelRef(full) {
  const r = full?.results || {};
  return {
    source: "saved",
    kind: full.kind,
    modelId: full.id,
    name: full.name,
    distribution: r.distribution,
    distribution_id: r.distribution_id,
    params: r.params || [],
    // Extra fitted quantities (offset/LFP/ZI) so calculators rebuild the
    // model exactly as it was fitted.
    extras: r.extras || null,
    // Covariate field definitions for proportional-hazards models; the RBD
    // calculator prompts for these values.
    covariates: (r.functions && r.functions.covariates) || [],
    unit: r.unit || "",
    // A mixture fit's modes follow this distribution (#318).
    ...(r.distribution_id === "mixture" ? { base_distribution_id: r.base_distribution_id || "weibull" } : {}),
  };
}

// A saved analysis' default name: "Replacement: Pump bearings", from the
// model's name; a model typed as parameters has none, so its distribution.
export function analysisName(what, model, fallback = "") {
  const name = model?.source === "saved" ? plainName(model.name) : "";
  const tail = name || fallback;
  return tail ? `${what}: ${tail}` : what;
}

const EDGE = { type: "smoothstep", markerEnd: { type: "arrowclosed", width: 18, height: 18 } };

// A diagram with a block for ``model`` (a savedModelRef) added: { graph,
// id, wired }. ``graph`` is a saved diagram's graph, or null for a new one. A
// new (or empty) diagram gets the block wired from Input to Output, and the
// model's unit when it has none; an existing one gets it below the blocks,
// not wired in: where it belongs is the user's call.
export function graphWithModel(graph, model) {
  const nodes = (graph?.nodes || []).map((n) => ({ ...n }));
  const edges = [...(graph?.edges || [])];
  const fresh = nodes.length === 0;
  if (fresh) {
    nodes.push(
      { id: "input", type: "input", data: { label: "Input" }, position: { x: 0, y: 120 } },
      { id: "output", type: "output", data: { label: "Output" }, position: { x: 520, y: 120 } },
    );
  }
  const nums = nodes.map((n) => parseInt(String(n.id).replace(/^\D+/, ""), 10)).filter((x) => !Number.isNaN(x));
  const id = `c${(nums.length ? Math.max(...nums) : 0) + 1}`;
  const empty = edges.length === 0 && nodes.every((n) => n.type === "input" || n.type === "output");
  const ys = nodes.map((n) => n.position?.y ?? 0);
  const xs = nodes.map((n) => n.position?.x ?? 0);
  const position = empty
    ? { x: 240, y: 120 }
    : { x: Math.round((Math.min(...xs) + Math.max(...xs)) / 2), y: Math.max(...ys) + 110 };
  nodes.push({
    id,
    type: "component",
    data: { label: plainName(model.name) || "Component", model },
    position,
    sourcePosition: "right",
    targetPosition: "left",
    selected: true,
  });
  if (empty) {
    edges.push({ id: `e-input-${id}`, source: "input", target: id, ...EDGE });
    edges.push({ id: `e-${id}-output`, source: id, target: "output", ...EDGE });
  }
  const unit = graph?.unit || (empty ? model.unit || "" : "");
  return { graph: { ...(graph || {}), nodes, edges, unit }, id, wired: empty };
}
