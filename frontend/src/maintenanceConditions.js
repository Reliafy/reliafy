// Conditions (Reliafy Maintenance): what locations, positions, items and connections
// are exposed to, and how a condition, its value and where it comes from read.

// "Outdoor", "Ambient temperature: 45 °C".
export function conditionText(entry) {
  if (!entry) return "";
  const c = entry.condition || entry;
  const value = entry.value;
  if (value === null || value === undefined || value === "") return c.display || c.name;
  const n = Number(value);
  const shown = Number.isFinite(n) ? (Number.isInteger(n) ? n : Number(n.toPrecision(6))) : value;
  return `${c.display || c.name}: ${shown}${c.unit ? ` ${c.unit}` : ""}`;
}

// What a condition is in the register: "presence", or "value in °C".
export function conditionKindText(c) {
  if (!c) return "";
  if (c.kind !== "value") return "applies or not";
  return c.unit ? `value in ${c.unit}` : "value";
}

// The page of the node a condition comes from.
export function sourcePath(source) {
  if (!source) return null;
  const base = { Location: "locations", Position: "positions", Item: "items" }[source.kind];
  return base ? `/asset-register/${base}/${source.id}` : null;
}

// Where a condition that applies, or is excluded, comes from: "set here", "from Site".
export function sourceText(entry) {
  if (!entry) return "";
  if (entry.own) return entry.excluded ? "excluded here" : "set here";
  return `${entry.excluded ? "excluded at" : "from"} ${entry.source?.name || "?"}`;
}

// An import result in a sentence.
export function conditionImportSummary(result) {
  if (!result) return "";
  const c = result.counts || {};
  const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
  if (c.errors) return `${plural(c.errors, "error")}: nothing ${result.dry_run ? "would be" : "was"} imported.`;
  const parts = [`${result.dry_run ? "It would add" : "Added"} ${plural(c.create || 0, "condition")}`];
  if (c.update) parts.push(`${result.dry_run ? "fill in" : "filled in"} ${plural(c.update, "condition")}`);
  if (c.unchanged) parts.push(`${c.unchanged} already there`);
  if (c.conflicts) parts.push(`${plural(c.conflicts, "conflict")} left as they are`);
  return `${parts.join(", ")}.`;
}

// The conditions a picker offers for a target: live ones not already set on it.
export function pickable(conditions = [], view = {}) {
  const own = new Set([...(view.conditions || []), ...(view.excluded_conditions || [])]
    .filter((e) => e.own).map((e) => e.condition.id));
  return conditions.filter((c) => !own.has(c.id));
}
