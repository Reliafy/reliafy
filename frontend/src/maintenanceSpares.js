// A position's parts list (Reliafy Maintenance): how its entries read, and the
// parts a work order offers first.

export const PART_ROLES = [
  { id: "replacement", label: "Replacement (replaces what's fitted)" },
  { id: "component", label: "Component (used in its maintenance)" },
  { id: "consumable", label: "Consumable (filter, oil…)" },
];

export function roleLabel(role) {
  return { replacement: "Replacement", component: "Component", consumable: "Consumable" }[role] || role;
}

// "3 on hand · Store A: 2, Van: 1", or "none in stock".
export function stockText(part) {
  if (!part) return "";
  const where = (part.stock || []).filter((s) => s.quantity).map((s) => `${s.location.name}: ${s.quantity}`);
  if (!part.on_hand) return "none in stock";
  return `${part.on_hand} on hand${where.length ? ` · ${where.join(", ")}` : ""}`;
}

// The parts to pick from on a work order: the position's parts list first
// (replacement first; a superseded part's successor before it, then its
// alternatives), then the rest of the catalogue. Each listed choice carries the
// quantity a job takes.
export function partChoices(suggested = [], catalogue = []) {
  const listed = [];
  const seen = new Set();
  const add = (part, note, quantity) => {
    if (!part || seen.has(part.id)) return;
    seen.add(part.id);
    listed.push({ ...part, note, quantity });
  };
  for (const entry of suggested) {
    const q = entry.quantity;
    if (entry.use_instead) add(entry.use_instead, `use instead of ${entry.part.part_number}`, q);
    add(entry.part, entry.use_instead ? "superseded" : entry.role, q);
    for (const alt of entry.alternatives || []) add(alt, `alternative to ${entry.part.part_number}`, q);
  }
  return { listed, others: catalogue.filter((p) => !seen.has(p.id)) };
}

// What an entry says about its part beyond the name: per job, critical minimum.
export function entryText(entry) {
  const bits = [`${entry.quantity} per job`];
  if (entry.critical) bits.push(`critical: keep ${entry.min_on_hand ?? 0}`);
  return bits.join(" · ");
}
