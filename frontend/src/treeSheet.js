// The asset tree in a spreadsheet, both ways (the Explorer's Import from Excel… and Export…):
// what the preview says about a file checked by the server (backend/maintenance/hierarchy.py).
// Pure functions, tested in treeSheet.test.js; TreeSheetPane.jsx shows them.

export const ACCEPT = ".xlsx,.xlsm,.csv";

const n = (count, one, many = `${one}s`) => `${Number(count || 0).toLocaleString("en-AU")} ${count === 1 ? one : many}`;

// The preview's count lines, in order, leaving out what's nought: [{key, text}].
export function previewLines(r) {
  if (!r) return [];
  const dry = r.dry_run !== false;
  const made = (one, many) => (c) => (dry ? `${n(c, `new ${one}`, `new ${many || one + "s"}`)}` : `${n(c, one, many)} made`);
  const lines = [
    ["positions_created", made("position")],
    ["positions_updated", (c) => `${n(c, "position")} updated`],
    ["positions_moved", (c) => `${n(c, "position")} moved`],
    ["locations_created", made("location")],
    ["classes_created", made("item class", "item classes")],
    ["items_created", (c) => `${n(c, dry ? "new item" : "item")} fitted`],
    ["items_updated", (c) => `${n(c, "item")} updated`],
  ];
  const out = [];
  for (const [key, text] of lines) {
    if (r[key]) out.push({ key, text: text(r[key]) });
  }
  if (r.positions_unchanged) out.push({ key: "positions_unchanged", text: `${n(r.positions_unchanged, "position")} already as the file has ${r.positions_unchanged === 1 ? "it" : "them"}` });
  return out;
}

// Positions under the file's top rows that the file leaves out: never deleted.
export function notInFileText(r) {
  const count = r?.not_in_file || 0;
  if (!count) return null;
  return `${n(count, "position")} in Reliafy under the file's rows ${count === 1 ? "isn't" : "aren't"} in the file. ${count === 1 ? "It stays" : "They stay"} as ${count === 1 ? "it is" : "they are"}: an import never deletes.`;
}

// How many lines fit in the workspace: "Room for 19,694 more positions." (the limit a problem when not).
export function roomText(r) {
  const lim = r?.limits?.positions;
  if (!lim) return null;
  const adding = lim.adding || 0;
  if (!adding) return null;
  return lim.fits
    ? `Fits: adds ${n(adding, "position")}, with room for ${(lim.room - adding).toLocaleString("en-AU")} more.`
    : `Doesn't fit: adds ${n(adding, "position")}, and there's room for ${lim.room.toLocaleString("en-AU")}.`;
}

// Where a problem or a note is: "Row 5", "Locations, row 3", or the file as a whole ("File").
export function whereText(p) {
  if (p.row == null) return p.sheet && p.sheet !== "Hierarchy" ? `${p.sheet} sheet` : "File";
  return p.sheet && p.sheet !== "Hierarchy" ? `${p.sheet}, row ${p.row}` : `Row ${p.row}`;
}

// Problems first by sheet (Hierarchy, then the others), then row: what the table lists.
export function sortedByRow(list) {
  const order = (p) => (p.sheet === "Hierarchy" || !p.sheet ? 0 : 1);
  return [...(list || [])].sort((a, b) => order(a) - order(b) || (a.row ?? -1) - (b.row ?? -1));
}

// The Import button: ready, or why not.
export function importBlocker(r, { viewOnly = null } = {}) {
  if (viewOnly) return viewOnly;
  if (!r) return "Check the file first.";
  if (r.problem_count || (r.problems || []).length) return "Fix the problems in the file, then check it again.";
  const changes = ["positions_created", "positions_updated", "positions_moved", "locations_created", "classes_created",
    "items_created", "items_updated", "locations_updated", "classes_updated"].some((k) => r[k]);
  if (!changes) return "Nothing to import: the tree already matches the file.";
  return null;
}

// What the toast says once it's in.
export const doneText = (r) => (r?.summary ? `Imported. ${r.summary}` : "Imported.");

// The export's choice: the whole tree, or the branch it was opened from. `whole`: false with
// one asset open (the Explorer's ?root=), where the whole register's tree isn't offered (and
// with no branch either, there's nothing to export: []).
export function exportChoices(branch, { whole = true } = {}) {
  return [...(whole ? [{ id: "all", label: "The whole tree" }] : []),
    ...(branch ? [{ id: "branch", label: `This branch: ${branch.name || "(no name)"}` }] : [])];
}
