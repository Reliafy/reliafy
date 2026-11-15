// The rows of an RBD's "Block importance" table, from an availability result:
// one per block, by its label, with the exact measures and (when the
// simulation ran) the simulated criticality.

// A block's name from anywhere the result gives one; never its raw id.
function blockLabel(result, id) {
  const imp = result.importance?.[id];
  if (imp && typeof imp === "object" && imp.label) return imp.label;
  if (result.criticality?.[id]?.label) return result.criticality[id].label;
  const lists = [result.exact?.blocks_by_downtime, result.exact?.per_node, result.per_node,
    result.costs?.blocks];
  for (const list of lists) {
    const hit = (list || []).find((n) => n && String(n.id) === String(id) && n.label);
    if (hit) return hit.label;
  }
  // Last resort: the id as words ("fuel-pump" → "fuel pump").
  return String(id).replace(/[-_]+/g, " ").trim() || "Block";
}

export function importanceRows(result) {
  const imp = result?.importance || {};
  const crit = result?.criticality || {};
  const rows = Object.keys(imp).map((id) => {
    const raw = imp[id];
    // A block with no exact measures (the API says which way it can be had,
    // e.g. "simulation"): named, with a note, never a raw id.
    const i = raw && typeof raw === "object" ? raw : {};
    const c = crit[id] || {};
    return {
      id,
      label: blockLabel(result, id),
      note: raw && typeof raw !== "object" ? "Needs a simulation" : null,
      pinned: i.pinned || null,
      birnbaum: i.birnbaum,
      // Never fall back to the library's success-oriented criticality: under
      // this column's name it would show 100% for every series block.
      crit: i.unavailability_criticality,
      risk_achievement_worth: i.risk_achievement_worth,
      structural: i.structural,
      // No simulation entry means the block never tripped/restored the system.
      failure_criticality: crit[id] ? c.failure_criticality : null,
      restoration_criticality: crit[id] ? c.restoration_criticality : null,
    };
  });
  rows.sort((a, b) => (b.crit ?? -1) - (a.crit ?? -1) || String(a.label).localeCompare(String(b.label)));
  return rows;
}
