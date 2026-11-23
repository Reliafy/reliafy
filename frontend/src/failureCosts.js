// What a failure costs (backend/maintenance/failure_costs.py): its repair, its downtime and the
// cost of an hour down, on the failure mode (the RCM tab's step 2), else on its position's class.
// And what the forecast asks for (GET …/forecast `prompts`): tasks with no modelled effect,
// failure modes with no failure cost, checks with no P-F interval. Pure functions, tested on
// their own (failureCosts.test.js).
import { formatCost, workspaceCurrency } from "./money.js";

// The three figures, each with its unit in the workspace's currency.
export function costFields(sym = workspaceCurrency()) {
  return [
    { key: "failure_cost", label: "A failure costs", suffix: sym, help: "To put one failure right: the repair or replacement in the field, the parts, any damage." },
    { key: "downtime_hours", label: "Out of use per failure", suffix: "h", help: "How long one failure stops it." },
    { key: "downtime_rate", label: "An hour out of use costs", suffix: `${sym}/h`, help: "Lost work, a hired stand-in. Leave it empty if a failure's cost already covers it." },
  ];
}

const money = (v) => (Math.abs(v) >= 100 ? formatCost(Math.round(v), undefined, { sig: 15 }) : formatCost(v, undefined, { sig: 3 }));

export function figureText(key, v) {
  if (v == null) return "";
  if (key === "downtime_hours") return `${Number(Number(v).toPrecision(4)).toLocaleString("en-GB")} h`;
  return key === "downtime_rate" ? `${money(v)} an hour` : money(v);
}

// A field's placeholder: the corrective response's cost (failure cost only), else the class's figure,
// used while the mode has none of its own (a typed figure overrides both).
export function placeholderFor(key, costs) {
  const resp = costs?.responses?.failure;
  if (key === "failure_cost" && resp?.cost_each != null) return `From its response: ${figureText(key, resp.cost_each)}`;
  const cls = costs?.class_figures?.[key];
  if (cls != null) return `From its class (${costs.class}): ${figureText(key, cls)}`;
  return "Not set";
}

// A typed figure as sent: null clears it (the class's is used), else a number 0 or more.
export function checkFigure(key, raw) {
  const text = String(raw ?? "").trim().replace(/[$,\s]/g, "");
  if (text === "") return { value: null };
  const v = Number(text);
  if (!Number.isFinite(v) || v < 0) return { error: key === "downtime_hours" ? "Enter the hours out of use, 0 or more." : "Enter an amount, 0 or more." };
  return { value: v };
}

// The line under the fields: one failure all in, and where each figure comes from.
export function usedText(used) {
  if (!used) return "";
  if (used.per_failure == null) return "No failure cost yet: the forecast leaves these failures out of the unplanned cost.";
  const src = used.sources || {};
  if (!used.downtime_cost) {
    const down = used.downtime_hours ? ` It keeps it out of use ${figureText("downtime_hours", used.downtime_hours)} (${src.downtime_hours}); no cost an hour set.` : "";
    return `One failure, all in: ${money(used.per_failure)} (${src.failure_cost || "set here"}).${down}`;
  }
  return `One failure, all in: ${money(used.per_failure)}: ${used.text}.`;
}

// The forecast's "What to enter" groups, in the order they change the numbers most: failure
// costs, then P-F intervals, then tasks with no modelled effect. Empty groups are left out.
export function promptGroups(prompts) {
  const p = prompts || {};
  const groups = [];
  const costs = p.no_failure_cost || [];
  if (costs.length) {
    groups.push({
      id: "cost", title: `Failure modes with no failure cost (${costs.length})`,
      lead: "Enter what one failure costs, and how long it stops the asset, on what's done if it fails (its corrective task on the Maintenance tab).",
      items: costs.map((x) => ({
        key: x.mode ? `c-${x.mode.id}` : `c-${x.position.id}-${x.life}`,
        name: x.mode ? x.mode.text : x.life, where: x.position.name, link: x.link,
        why: x.mode ? (x.counted ? "Its failures are forecast here, at no cost." : "No life forecast for it yet.") : x.reason,
        action: "Enter the cost",
      })),
    });
  }
  const pf = p.no_pf || [];
  if (pf.length) {
    groups.push({
      id: "pf", title: `Checks with no P-F interval (${pf.length})`,
      lead: "A check counts once its failure mode's decision has a P-F calculation as its evidence.",
      items: pf.map((x) => ({ key: `p-${x.task.id}`, name: x.task.name, where: `${x.position.name} · ${x.mode.text}`, link: x.link,
        why: "Not counted: the forecast can't tell how many warnings it finds.", action: "Add the P-F interval" })),
    });
  }
  const effect = p.no_effect || [];
  if (effect.length) {
    groups.push({
      id: "effect", title: `Tasks with no modelled effect on failures (${effect.length})`,
      lead: "Their cost is counted; the failures are as they would be without them.",
      items: effect.map((x) => ({ key: `e-${x.task.id}`, name: x.task.name, where: x.position.name, link: x.link,
        why: x.reason.charAt(0).toUpperCase() + x.reason.slice(1) + ".", action: "Open the task" })),
    });
  }
  return groups;
}

// What the planned cost holds, in words, for the table's cell title.
export function plannedTitle(row) {
  if (!row) return "";
  const bits = [];
  if (row.labour_cost) bits.push(`labour ${money(row.labour_cost)}`);
  if (row.materials_cost) bits.push(`parts and consumables ${money(row.materials_cost)}`);
  if (row.visits_cost) bits.push(`visits' call-out and setup ${money(row.visits_cost)}`);
  if (row.other_planned_cost) bits.push(`other (a typed cost the LSA doesn't explain) ${money(row.other_planned_cost)}`);
  return bits.length ? `Planned: ${bits.join(", ")}` : "";
}

// A response is a task raised by its event (responses.py): its kind on the Maintenance tab (the
// table's Kind, the task panel's head) and the line under its name there.
export const RESPONSE_KIND = { failure: "Corrective: on failure", found: "Follow-on: when found" };
export const responseKindOf = (t) => (t?.trigger && RESPONSE_KIND[t.trigger.kind] ? t.trigger.kind : null);
export function responseTrigger(kind, mode) {
  const what = mode || "its failure mode";
  return kind === "failure" ? `Raised when ${what} fails` : `Raised when an inspection finds ${what}`;
}

// A response in one line on the RCM tab (ModeResponseLinks): {text, action, gap}. `used`: the failure
// cost in force (its all-in figure, said after a corrective response when it's more than the repair).
export function responseLine(kind, resp, used = null) {
  const lead = kind === "failure" ? "If it fails" : "If an inspection finds it";
  if (!resp) {
    return { text: kind === "failure" ? "No response if it fails" : "Nothing recorded for when it's found", action: "Add in Maintenance", gap: true };
  }
  const bits = [];
  if (resp.hours_each != null) bits.push(`${Number(Number(resp.hours_each).toPrecision(4)).toLocaleString("en-GB")} h`);
  if (resp.cost_each != null) bits.push(money(resp.cost_each));
  let text = `${lead}: ${resp.name}${bits.length ? ` (${bits.join(", ")})` : ""}`;
  if (kind === "failure" && used?.per_failure != null && used.per_failure !== resp.cost_each) text += `; a failure costs ${money(used.per_failure)} all in`;
  return { text, action: "Edit in Maintenance", gap: false };
}

