// What gave a saved Strategy analysis its answer: the inputs as rows a
// reviewer reads ("Planned replacement cost: $2,500"), and a link that opens
// the tool again on the same model and figures, to rerun with a new price.
// Pure functions (node --test covers them).
import { formatNumber, formatTarget } from "./format.js";
import { formatCost } from "./money.js";

const blank = (v) => v === null || v === undefined || v === "";

// The saved model a tool ran on, as inputs it keeps beside the figures (the
// server ignores them; the saved page shows them and reopens the tool).
export function savedInputs(model) {
  if (model?.source !== "saved" || !model.modelId) return {};
  return { model_id: model.modelId, model_name: model.name || "" };
}

// The model in words: its saved name, else the distribution and parameters.
export function modelText(inputs) {
  if (!inputs) return "—";
  if (inputs.model_name) return inputs.model_name;
  const params = (inputs.params || [])
    .map((p) => (p && typeof p === "object" ? `${p.name} ${formatNumber(p.value, { sig: 4 })}` : formatNumber(p, { sig: 4 })))
    .join(", ");
  const dist = String(inputs.distribution_id || "model");
  return params ? `${dist[0].toUpperCase()}${dist.slice(1)} (${params})` : dist;
}

const withUnit = (v, unit) => (blank(v) ? null : `${formatNumber(v, { sig: 4 })}${unit ? ` ${unit}` : ""}`);

function shutText(s, currency) {
  const price = formatCost(s.cost, currency);
  if (Array.isArray(s.dates) && s.dates.length) return `${s.name}: ${price}, on ${s.dates.join(", ")}`;
  const every = blank(s.every) ? "" : `, every ${formatNumber(s.every)} ${s.every_unit || "days"}`;
  return `${s.name}: ${price}${every}${s.start ? ` from ${s.start}` : ""}`;
}

// [{ label, value }] for a saved analysis' inputs; [] for a kind it doesn't know.
export function inputRows(kind, inputs, currency = "$") {
  const i = inputs || {};
  const unit = String(i.unit || "").toLowerCase();
  const rows = [];
  const add = (label, value) => { if (!blank(value)) rows.push({ label, value }); };
  if (kind === "optimal_replacement") {
    add("Model", modelText(i));
    add("Time unit", i.unit);
    add("Planned replacement cost", blank(i.planned_cost) ? null : formatCost(i.planned_cost, currency));
    add("Unplanned (failure) cost", blank(i.unplanned_cost) ? null : formatCost(i.unplanned_cost, currency));
    add("Use a year, per unit", withUnit(i.use_per_year, unit));
    add("Units", blank(i.units) ? null : formatNumber(i.units, { sig: 6 }));
  } else if (kind === "failure_finding") {
    add("Model", modelText(i));
    add("Time unit", i.unit);
    add("Target availability", blank(i.target_availability) ? null : formatTarget(i.target_availability));
    add("Each test takes", withUnit(i.test_duration, unit));
    add("Cost per test", blank(i.test_cost) ? null : formatCost(i.test_cost, currency));
    add("Each test", i.renewed_at_test === false ? "leaves a working device as it was" : "renews the device");
  } else if (kind === "overhaul_replace") {
    add("Model", i.model_name || modelText({ distribution_id: i.form, params: i.params }));
    add("Time unit", i.unit);
    add("Repair cost, per failure", blank(i.cost_repair) ? null : formatCost(i.cost_repair, currency));
    add("Overhaul cost", blank(i.cost_overhaul) ? null : formatCost(i.cost_overhaul, currency));
    add("Replacement cost", blank(i.cost_replace) ? null : formatCost(i.cost_replace, currency));
    add("An overhaul takes off", blank(i.overhaul_restores) ? null : `${formatNumber(i.overhaul_restores, { sig: 4 })}% of its age`);
    add("Hours down per repair", blank(i.downtime_repair) ? null : formatNumber(i.downtime_repair, { sig: 4 }));
    add("Hours down per overhaul", blank(i.downtime_overhaul) ? null : formatNumber(i.downtime_overhaul, { sig: 4 }));
    add("Hours down per replacement", blank(i.downtime_replace) ? null : formatNumber(i.downtime_replace, { sig: 4 }));
    add("Cost of an hour down", blank(i.downtime_cost) ? null : formatCost(i.downtime_cost, currency));
    add("Most overhauls searched", blank(i.max_overhauls) ? null : formatNumber(i.max_overhauls, { sig: 4 }));
  } else if (kind === "calendar_replacement") {
    add("Model", modelText(i));
    add("Time unit", i.unit);
    add("Today (time 0)", i.today);
    (i.opportunities || []).forEach((s, k) => add(k === 0 ? "Shuts" : "", shutText(s, currency)));
    add("Failure (unplanned) cost", blank(i.failure_cost) ? null : formatCost(i.failure_cost, currency));
    add("Replacing between shuts costs", blank(i.anytime_cost) ? "not allowed" : formatCost(i.anytime_cost, currency));
  } else if (kind === "sequential_test") {
    const pct = (v) => (blank(v) ? null : `${formatNumber(v * 100, { sig: 4 })}%`);
    if (i.method === "attribute") {
      add("Test type", "Pass/fail (failures against units)");
      add("Reliability to demonstrate", pct(i.reliability));
      add("A good design's reliability", pct(i.good_reliability));
    } else {
      add("Test type", "MTBF (failures against test time)");
      add("MTBF to demonstrate", withUnit(i.mtbf, unit));
      add("A good design's MTBF", withUnit(i.good_mtbf, unit));
    }
    add("Confidence", pct(i.confidence));
    add("Producer's risk", pct(i.producer_risk));
    add("Failures so far", blank(i.failures_seen) ? null : formatNumber(i.failures_seen));
    // A count kept as entered (a record of the test), not rounded to 4 figures.
    add("Total test time so far", blank(i.time_seen) ? null : `${formatNumber(i.time_seen, { sig: 9 })}${unit ? ` ${unit}` : ""}`);
    add("Units tested so far", blank(i.units_seen) ? null : formatNumber(i.units_seen, { sig: 7 }));
  }
  return rows;
}

// The tool again with these inputs ({ to, label }), or null when the
// analysis isn't on a saved model (typed parameters have no id to reopen).
export function reopenLink(kind, inputs) {
  const i = inputs || {};
  if (!i.model_id) return null;
  const q = new URLSearchParams({ model: i.model_id });
  if (kind === "optimal_replacement") {
    if (!blank(i.planned_cost)) q.set("planned", String(i.planned_cost));
    if (!blank(i.unplanned_cost)) q.set("unplanned", String(i.unplanned_cost));
    if (!blank(i.use_per_year)) q.set("use", String(i.use_per_year));
    if (!blank(i.units)) q.set("units", String(i.units));
    return { to: `/strategy/replacement?${q}`, label: "Open in Optimal replacement" };
  }
  if (kind === "failure_finding") {
    if (!blank(i.target_availability)) q.set("target", String(Number((i.target_availability * 100).toPrecision(10))));
    return { to: `/strategy/failure-finding?${q}`, label: "Open in Failure finding" };
  }
  if (kind === "overhaul_replace") {
    for (const [k, key] of [["cost_repair", "repair"], ["cost_overhaul", "overhaul"], ["cost_replace", "replace"], ["overhaul_restores", "restores"]]) {
      if (!blank(i[k])) q.set(key, String(i[k]));
    }
    return { to: `/strategy/overhaul-replace?${q}`, label: "Open in Overhaul and replace" };
  }
  if (kind === "calendar_replacement") {
    q.set("mode", "calendar");
    return { to: `/strategy/replacement?${q}`, label: "Open in Shutdown calendar" };
  }
  return null;
}
