// Product structure (Reliafy Maintenance, #435): parts made of parts. How a line's
// quantity reads, the parts list as a forest of structures, and import and
// "positions from structure" results in a sentence.

const plural = (n, word, many = `${word}s`) => `${n} ${n === 1 ? word : many}`;

// A quantity without float noise: 2, 0.25, 1.5.
export function qtyNumber(q) {
  const n = Number(q);
  if (!Number.isFinite(n)) return "";
  return String(Number.isInteger(n) ? n : Number(n.toPrecision(6)));
}

// "× 2" for a line's quantity (nothing for the top of a tree).
export function qtyText(q) {
  return q === null || q === undefined ? "" : `× ${qtyNumber(q)}`;
}

// The parts catalogue as structures: each part at the top of one (it contains parts,
// and none contains it) with its components nested below, from the parts' own
// `components` (one level down each). A shared part appears under each assembly
// using it. Parts in no structure come back in `loose`.
export function partsForest(parts = [], maxDepth = 20) {
  const byId = new Map(parts.map((p) => [p.id, p]));
  const inside = new Set();
  for (const p of parts) for (const c of p.components || []) inside.add(c.id);
  const grow = (part, line, depth, path) => ({
    id: part.id, part_number: part.part_number, name: part.name, level: part.level || "",
    qty: line ? line.qty : null, ref: line ? line.ref || "" : "",
    key: [...path, part.id].join("/"),
    children: depth >= maxDepth ? [] : (part.components || [])
      .filter((c) => byId.has(c.id) && !path.includes(c.id))
      .map((c) => grow(byId.get(c.id), c, depth + 1, [...path, part.id])),
  });
  const roots = parts.filter((p) => (p.components || []).length > 0 && !inside.has(p.id) && !p.used_in);
  const loose = parts.filter((p) => !(p.components || []).length && !inside.has(p.id) && !p.used_in);
  return { roots: roots.map((p) => grow(p, null, 0, [])), loose };
}

// Every node's key in a tree (to expand them all).
export function treeKeys(node, path = "", out = []) {
  if (!node) return out;
  const key = path ? `${path}/${node.id}` : node.id;
  out.push(key);
  for (const c of node.children || []) treeKeys(c, key, out);
  return out;
}

// The indenture levels found in a structure tree, in the workspace list's order
// (levels not on it last); "" for parts with none is left out.
export function levelsIn(tree, list = []) {
  const found = new Set();
  const walk = (n) => { if (n.level) found.add(n.level); (n.children || []).forEach(walk); };
  if (tree) walk(tree);
  const order = (l) => { const i = list.indexOf(l); return i < 0 ? list.length : i; };
  return [...found].sort((a, b) => order(a) - order(b) || a.localeCompare(b));
}

// A BOM import's result in a sentence.
export function bomImportSummary(result) {
  if (!result) return "";
  const c = result.counts || {};
  if (c.errors) return `${plural(c.errors, "error")}: nothing ${result.dry_run ? "would be" : "was"} imported.`;
  const would = result.dry_run;
  const bits = [];
  if (c.parts_created) bits.push(`${would ? "add" : "added"} ${plural(c.parts_created, "part")}`);
  if (c.parts_updated) bits.push(`${would ? "fill in" : "filled in"} ${plural(c.parts_updated, "part")}`);
  if (c.lines_added) bits.push(`${would ? "add" : "added"} ${plural(c.lines_added, "structure line")}`);
  if (c.lines_changed) bits.push(`${would ? "change" : "changed"} ${plural(c.lines_changed, "line")}`);
  if (c.levels_added) bits.push(`${would ? "add" : "added"} ${plural(c.levels_added, "indenture level")}`);
  let text = bits.length ? `${would ? "It would " : ""}${bits.join(", ")}` : (would ? "Nothing would change" : "Nothing changed");
  text = text.charAt(0).toUpperCase() + text.slice(1);
  if (c.unchanged) text += `; ${plural(c.unchanged, "line")} already as the file says`;
  if (c.conflicts) text += `; ${plural(c.conflicts, "difference")} left as ${c.conflicts === 1 ? "it is" : "they are"}`;
  return `${text}.`;
}

// The BOM's format as the import read it: "Indented, by level number (column “Level”)."
export function bomFormatText(result) {
  const f = result && result.format;
  if (!f || !f.label) return "";
  return `${f.label}${f.column ? ` (column “${f.column}”)` : ""}.`;
}

// Whether a BOM import read the file as indented (a level on each row, no parent column).
export function bomIsIndented(result) {
  const id = result && result.format && result.format.id;
  return !!id && id !== "parent" && id !== "list";
}

// "Create positions from structure": what it would make, or made.
export function positionsPlanSummary(result) {
  if (!result) return "";
  const c = result.counts || {};
  const would = result.dry_run;
  const bits = [`${would ? "It would make" : "Made"} ${plural(c.create || 0, "position")}`];
  if (c.reuse) bits.push(`${would ? "use" : "used"} ${plural(c.reuse, "position")} already there`);
  if (c.parts_list) bits.push(`${would ? "put" : "put"} the part on ${plural(c.parts_list, "parts list")}`);
  let text = bits.join(", ");
  if (c.skipped) text += `; ${plural(c.skipped, "line")} with part quantities (a consumable?) left off`;
  return `${text}.`;
}
