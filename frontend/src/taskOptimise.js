// Optimise… on a maintenance task (TaskOptimisePane.jsx; the server's task_optimise.py): how often
// to do it, from the life model of each failure mode it prevents (Derryn, 22 Nov 2026: strategy
// "links the life model and the task… it needs to be on both places"). The words the pane, the
// task's panel and a model's "Sets the interval of" share. Pure functions, tested beside it.

import { num } from "./rcmIntervals.js";
import { explorerPath } from "./assetTree.js";
import { explorerHere } from "./products.js";

const SHORT = { hours: "h", hour: "h", h: "h" };

// "96 h", "3 months", "1 week": an interval as the task's plan shows it.
export function every(value, unit) {
  const u = String(unit || "").trim();
  const short = SHORT[u.toLowerCase()];
  if (short) return `${num(value)} ${short}`;
  const one = Number(value) === 1 && /s$/.test(u);
  return `${num(value)} ${one ? u.slice(0, -1) : u}`.trim();
}

// The button that uses an answer: "Use every 96 h".
export const useLabel = (use) => (use ? `Use every ${every(use.value, use.unit)}` : "Use");

// Where the model a mode's interval rests on came from, in words.
export function modelSource(model) {
  if (!model) return "";
  switch (model.source) {
    case "chosen": return "Chosen here.";
    case "optimised": return "The model the interval was last optimised on.";
    case "evidence": return "The RCM decision's evidence.";
    case "position": return "This failure mode's model on the position.";
    case "analysis": return model.note || "";
    default: return "";
  }
}

// What a model is, in a few words: "Weibull · hours", "time to the limit (25 A/cm), Lognormal · hours".
export const modelWords = (model) => [model?.words, model?.unit].filter(Boolean).join(" · ");

// The body sent for one mode: what the user changed in its inputs (blank boxes left out, so the
// server starts from its own figures), the model chosen and the mode.
export function bodyFor(modeId, edits = {}, model = null) {
  const out = { failure_mode_id: modeId };
  for (const k of ["planned_cost", "unplanned_cost", "pf_interval", "act_time"]) {
    const v = edits[k];
    if (v !== undefined && v !== "" && v !== null && Number.isFinite(Number(v))) out[k] = Number(v);
  }
  if (edits.pf_unit) out.pf_unit = edits.pf_unit;
  if (edits.target !== undefined && edits.target !== "" && Number.isFinite(Number(edits.target))) {
    out.target_unavailability = Number(edits.target) / 100;
  }
  if (model?.id) {
    out.model_type = model.type || "model";
    out.model_id = model.id;
  }
  return out;
}

// An input box's starting text: the figure the server started from ("" when it has none).
export const startText = (input) => (input?.value == null ? "" : String(Number(Number(input.value).toPrecision(6))));

// A model row's "Sets the interval of": "Replace spark plugs (every 96 h)".
export const setsLine = (t) => `${t.name}${t.interval != null ? ` (every ${every(t.interval, t.unit)})` : ""}`;

// The Used by cell's words for the tasks a model sets: "sets 1 task's interval".
export function setsCount(tasks = []) {
  const n = tasks.length;
  return n ? `sets ${n} task${n === 1 ? "'s" : "s'"} interval` : "";
}

// After Use: what changed, in one line.
export function usedText(out) {
  const status = out.evidence_status === "supported" ? " The evidence reads supported."
    : out.evidence_status ? ` The evidence check reads ${String(out.evidence_status).replace(/_/g, " ")}.` : "";
  const linked = out.evidence_linked ? "" : out.evidence_not_linked ? ` ${out.evidence_not_linked}` : "";
  return `Set to every ${every(out.interval, out.unit)}, the calculation saved as its evidence.${status}${linked}`;
}

// A task's interval basis line for its panel: "Every 96 h rests on Spark plug life (Weibull)".
export function basisText(row) {
  const name = row.model?.name || row.analysis?.name || "a saved analysis";
  return `${row.use ? `Every ${every(row.use.value, row.use.unit)}` : "Its interval"} rests on ${name}`;
}

// Where a task's Optimise opens: the Explorer's Maintenance tab, on its asset (?root=), the pane
// beside the tree (?optimise=<task>&on=<position>). From inside the Explorer, `here` ({pathname,
// search}) keeps the asset open (a product's design keeps its own page).
export function optimisePath(t, here = null) {
  const extra = { sel: t.position_id, tab: "maintenance", optimise: t.task_id, on: t.position_id };
  if (here) return explorerHere(here.pathname, here.search, extra);
  return explorerPath("positions", { ...(t.root ? { root: t.root } : {}), ...extra });
}
