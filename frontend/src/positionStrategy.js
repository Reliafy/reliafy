// A model's Strategy on a position (the Explorer's Modelling tab; Derryn, 16 Nov 2026: "each model
// for a position needs a sub item which is 'strategy'", and then "Strategy is optional"). A model
// row gets a Strategy item under it only once a strategy has been saved for it there; until then
// its menu offers a quiet "Add a strategy…". Either opens the table pane beside the tree with the
// strategy tools that fit the model's type, pre-filled with the model and the position's class
// costs where known. Pure functions, tested in positionStrategy.test.js.

import { tabPlace } from "./explorerTabs.js";

// The strategy tools, each the shared Strategy component (one per job) shown in the pane.
export const STRATEGY_CHOICES = {
  replacement: { id: "replacement", label: "Optimal replacement", kind: "optimal_replacement",
    words: "The replacement age with the lowest long-run cost, against running to failure." },
  calendar: { id: "calendar", label: "Shutdown replacement", kind: "calendar_replacement",
    words: "When replacing at a shutdown costs less than between shuts." },
  failureFinding: { id: "failureFinding", label: "Failure finding", kind: "failure_finding",
    words: "How often to test it, if its failure is hidden until it's needed (a protective device)." },
  overhaulReplace: { id: "overhaulReplace", label: "Overhaul and replace", kind: "overhaul_replace",
    words: "Overhaul every X, replace after N overhauls: the cheapest rule for a repairable unit." },
  overhaul: { id: "overhaul", label: "Optimal overhaul", kind: null,
    words: "The overhaul interval alone, each overhaul as good as new." },
  conditionRisk: { id: "conditionRisk", label: "Risk now", kind: null, link: true,
    words: "Each unit's chance of failing soon from its latest readings, on the model's page." },
  conditionMonitoring: { id: "conditionMonitoring", label: "Condition monitoring", kind: null, link: true,
    words: `This position's condition, remaining life and alarms (${tabPlace("condition")}).` },
};

// The kinds a saved strategy analysis can have here (those with a kind).
export const STRATEGY_KINDS = new Set(Object.values(STRATEGY_CHOICES).map((c) => c.kind).filter(Boolean));

const minimalRepair = (kind) => /\b(NHPP)\b/i.test(kind || "");

// The strategy tools that apply to a model row's link, in order, with why none do when none do:
// {choices: [...], none: "…"}.
export function strategiesFor(link) {
  const m = link?.model;
  if (!link || !m) return { choices: [], none: "The model isn't there any more." };
  const pick = (...ids) => ({ choices: ids.map((id) => STRATEGY_CHOICES[id]), none: "" });
  if (link.model_type === "recurrent_model") {
    if (minimalRepair(m.kind)) return pick("overhaulReplace", "overhaul");
    return { choices: [], none: "Overhaul and replace needs a minimal-repair model (Crow-AMSAA, Duane, HPP or "
      + "Cox-Lewis): an imperfect-repair or covariate model can't say how often an overhauled unit fails." };
  }
  if (link.model_type === "model") {
    if (m.family === "condition") return pick("conditionRisk", "conditionMonitoring");
    if (link.role === "prediction") return pick("failureFinding");
    if ((m.covariates || []).length || m.kind === "Competing risks") {
      return { choices: [], none: "The strategy tools take a plain life distribution: fix this model's covariates "
        + "or choose a failure mode's model." };
    }
    if (m.family === "life") return pick("replacement", "calendar", "failureFinding");
  }
  return { choices: [], none: "No strategy tool takes this kind of model yet." };
}

// The saved strategy analyses by the model row they were saved for ({link id: [analysis]}), newest first.
export function strategiesByLink(analyses = []) {
  const out = {};
  for (const a of analyses) {
    if (!a?.position_link_id || !STRATEGY_KINDS.has(a.kind)) continue;
    (out[a.position_link_id] ||= []).push(a);
  }
  for (const list of Object.values(out)) {
    list.sort((a, b) => String(b.updated_at || b.created_at || "").localeCompare(String(a.updated_at || a.created_at || "")));
  }
  return out;
}

// A Strategy row's key in the tree (beside its model row's L:<link id>).
export const strategyKey = (linkId) => `S:${linkId}`;
export const isStrategyRow = (r) => !!r?.ref?.strategy;

// The Strategy row's headline: its saved strategies' answers in a few words.
export function strategyHeadline(saved = []) {
  if (!saved.length) return "";
  const first = saved[0].headline || saved[0].name || "";
  return saved.length === 1 ? first : `${first} · ${saved.length - 1} more`;
}

// The class costs a strategy tool starts from ({planned, unplanned, target, replace}), from the
// position's class (GET /api/maintenance/classes/one): what a planned replacement and a failure cost,
// the hidden function's availability target (as a percentage) and the replacement cost.
export function classPresets(cls) {
  const c = cls?.costs || {};
  const pct = c.availability_target != null ? Number((c.availability_target * 100).toPrecision(10)) : null;
  const replace = cls?.replacement_cost?.amount ?? null;
  return { planned: c.planned_cost ?? null, unplanned: c.failure_cost ?? null, target: pct, replace };
}

// What a Save from the pane keeps with the analysis: the model row it's for.
export const rowInputs = (link) => ({ position_link_id: link.id, position_id: link.position_id });
