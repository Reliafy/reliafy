// Block capacities and the production figures (#122): the shapes the block
// dialog edits and the sentences the Calculator's Production section shows.
// No reliability maths here: the figures come from the backend (RePyability).
import { formatNumber } from "./format.js";

// A probability near 1 as a percentage with the decimals that show its gap to
// 100% (to two figures): 0.99598 → "99.60%", 0.9999 → "99.990%", 0.646 → "64.6%".
export function pctNear1(v) {
  if (v == null || !Number.isFinite(v)) return "—";
  const gap = (1 - v) * 100;
  const digits = gap > 0 ? Math.min(6, Math.max(1, Math.ceil(-Math.log10(gap) - 1e-9) + 1)) : 1;
  return `${(v * 100).toFixed(digits)}%`;
}

// A stored capacity (a number, or [{value, probability}]) as the dialog's
// rows: [{value, share}] with the share in percent, as typed text.
export function capacityRows(capacity) {
  if (capacity == null || capacity === "") return [];
  if (Array.isArray(capacity)) {
    return capacity.map((l) => ({
      value: String(l.value),
      share: String(Number((Number(l.probability) * 100).toPrecision(6))),
    }));
  }
  return [{ value: String(capacity), share: "100" }];
}

// The dialog's rows as a stored capacity: {value, valid, error}. Empty rows
// mean no capacity; one level is stored as its number.
export function capacityFromRows(rows) {
  // A row is a level once it has a capacity (a share alone is a level not
  // yet typed in, as the one-value field's preset 100% is).
  const filled = rows.filter((r) => String(r.value ?? "").trim() !== "");
  if (!filled.length) return { value: null, valid: true };
  const levels = [];
  for (const r of filled) {
    const value = Number(r.value);
    const share = Number(r.share);
    if (String(r.value).trim() === "" || !Number.isFinite(value) || value <= 0) {
      return { value: null, valid: false, error: "Each capacity must be a positive number." };
    }
    if (String(r.share).trim() === "" || !Number.isFinite(share) || share <= 0 || share > 100) {
      return { value: null, valid: false, error: "Each share of up time must be above 0% and at most 100%." };
    }
    levels.push({ value, probability: share / 100 });
  }
  const total = levels.reduce((s, l) => s + l.probability, 0);
  if (Math.abs(total - 1) > 1e-6) {
    return {
      value: null,
      valid: false,
      error: `The shares must add up to 100% (they add up to ${formatNumber(total * 100)}%).`,
    };
  }
  if (levels.length === 1) return { value: levels[0].value, valid: true };
  return { value: levels.sort((a, b) => a.value - b.value), valid: true };
}

// "none" · "250" · "2 levels, up to 250" — the dialog's folded summary and
// the canvas hint.
export function capacitySummary(capacity, unit = "") {
  const u = unit ? ` ${unit}` : "";
  if (capacity == null || capacity === "") return "none";
  if (Array.isArray(capacity)) {
    const top = Math.max(...capacity.map((l) => Number(l.value)));
    return `${capacity.length} levels, up to ${formatNumber(top)}${u}`;
  }
  return `${formatNumber(Number(capacity))}${u}`;
}

// Whether any block of a graph carries a capacity.
export function hasCapacity(graph) {
  return (graph?.nodes || []).some((n) => {
    const c = n.data?.capacity;
    return c != null && c !== "" && !(Array.isArray(c) && !c.length);
  });
}

// The Production section's answer sentence, with **…** around the numbers
// to show in bold (see ``boldParts``). The numbers are the backend's.
export function productionSentence(p, timeUnit = "") {
  if (!p) return null;
  const cu = p.capacity_unit ? ` ${p.capacity_unit}` : "";
  if (p.production_availability == null) {
    return `The system delivers **${formatNumber(p.mean_capacity)}${cu}** on average${
      p.kind === "repairable" ? " in the long run" : ""
    }. Set a demand to see the share of it delivered.`;
  }
  const share = pctNear1(p.production_availability);
  const plain = pctNear1(p.availability);
  const demand = `**${formatNumber(p.demand)}${cu}**`;
  if (p.kind === "repairable") {
    return `In the long run the system delivers **${share}** of the ${demand} demand, against **${plain}** plain availability.`;
  }
  const at = `${formatNumber(p.t)}${timeUnit ? ` ${timeUnit.toLowerCase()}` : ""}`;
  return `At ${at} the system can deliver **${share}** of the ${demand} demand, on average.`;
}

// "a **b** c" → [["a ", false], ["b", true], [" c", false]].
export function boldParts(text) {
  return String(text ?? "").split("**").map((s, i) => [s, i % 2 === 1]).filter(([s]) => s);
}
