// Item classes and the manufacturer register (Reliafy Maintenance): how classes,
// attributes and import results read, and the attribute editor's rows.

export const ATTRIBUTE_KINDS = [
  { id: "number", label: "Number" },
  { id: "text", label: "Text" },
  { id: "choice", label: "Choice" },
];

// "Flow (m3/h)", "Stages", "Shaft seal: mechanical seal / packing".
export function attributeText(a) {
  if (!a) return "";
  const unit = a.unit ? ` (${a.unit})` : "";
  return a.kind === "choice" ? `${a.name}${unit}: ${(a.options || []).join(" / ")}` : `${a.name}${unit}`;
}

// A value as it reads: "45 m3/h", "mechanical seal", or "—" when not set.
export function attributeValueText(a) {
  if (!a || a.value === null || a.value === undefined || a.value === "") return "—";
  if (a.kind === "number") {
    const n = Number(a.value);
    return `${Number.isInteger(n) ? n : Number(n.toPrecision(6))}${a.unit ? ` ${a.unit}` : ""}`;
  }
  return String(a.value);
}

// The tree as one list, parents first, each with its depth (for a picker).
export function flattenClasses(tree = [], depth = 0, out = []) {
  for (const c of tree) {
    out.push({ ...c, depth });
    flattenClasses(c.children || [], depth + 1, out);
  }
  return out;
}

// A class and every class inside it (their ids): what a move can't go under.
export function subtreeIds(tree = [], id) {
  const all = flattenClasses(tree);
  const ids = new Set([id]);
  let grew = true;
  while (grew) {
    grew = false;
    for (const c of all) {
      for (const k of c.children || []) {
        if (ids.has(c.id) && !ids.has(k.id)) { ids.add(k.id); grew = true; }
      }
    }
  }
  return ids;
}

// The attribute editor's rows (options typed as "a | b | c") from a class's own attributes.
export function attributeRows(attrs = []) {
  return attrs.map((a) => ({ name: a.name, unit: a.unit || "", kind: a.kind, options: (a.options || []).join(" | ") }));
}

// ...and back to what the API takes (blank rows dropped).
export function attributesBody(rows = []) {
  return rows.filter((r) => r.name.trim()).map((r) => ({
    name: r.name.trim(), unit: r.unit.trim(), kind: r.kind,
    options: r.kind === "choice" ? r.options.split("|").map((o) => o.trim()).filter(Boolean) : [],
  }));
}

// An import or starter result in a sentence.
export function importSummary(result) {
  if (!result) return "";
  const c = result.counts || {};
  const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "es"}`;
  const parts = [];
  if (c.errors) return `${c.errors} error${c.errors === 1 ? "" : "s"}: nothing ${result.dry_run ? "would be" : "was"} imported.`;
  parts.push(`${result.dry_run ? "It would add" : "Added"} ${plural(c.create || 0, "class")}`);
  if (c.update) parts.push(`${result.dry_run ? "fill in" : "filled in"} ${plural(c.update, "class")}`);
  if (c.unchanged) parts.push(`${c.unchanged} already there`);
  if (c.conflicts) parts.push(`${c.conflicts} conflict${c.conflicts === 1 ? "" : "s"} left as they are`);
  return `${parts.join(", ")}.`;
}

// Where an item's class or manufacturer comes from: its own, or its part's.
export function viaText(via) {
  return via === "part" ? "from its part" : "";
}
