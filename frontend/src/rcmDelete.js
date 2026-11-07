// Delete… on a row of a position's RCM (the RCM and FME(C)A tabs): a
// function, a performance standard, a functional failure or a failure mode
// goes with everything under it, as a position does (treeDelete.js). The
// dialog's words come from the counts the server gives (a dry run of the
// delete with cascade); Undo (restoreRcm) brings the whole lot back. Pure
// functions, tested in rcmDelete.test.js.

// The tree's row types to the server's kinds.
export const RCM_DELETE_KIND = { fn: "function", std: "standard", fail: "functional_failure", mode: "failure_mode" };

const WHAT = {
  function: "function", standard: "performance standard", functional_failure: "functional failure",
  failure_mode: "failure mode",
};

// Whether a row is deleted this way: the old single standard text (legacy)
// isn't a row of its own, so its menu clears the text instead.
export function deletesWithCascade(r) {
  return !!r && !!RCM_DELETE_KIND[r.type] && !(r.type === "std" && r.ref?.legacy);
}

// The id the server knows the row by (a standard's row is keyed by its function too).
export function rcmDeleteId(r) {
  return r.type === "std" ? r.ref.standard_id : r.ref.id;
}

const n = (count, one, many = `${one}s`) => `${Number(count || 0).toLocaleString("en-AU")} ${count === 1 ? one : many}`;
const quoted = (s) => {
  const text = String(s || "it").replace(/\s+/g, " ").trim();
  return `“${text.slice(0, 80)}${text.length > 80 ? "…" : ""}”`;
};
const under = (c) => (c.standards || 0) + (c.functional_failures || 0) + (c.failure_modes || 0) + (c.tasks || 0);

// "Delete “Pump water” and everything under it?" (just "Delete “Seal leaks”?"
// when nothing is under it).
export function rcmDeleteTitle(c) {
  return `Delete ${quoted(c.name)}${under(c) ? " and everything under it" : ""}?`;
}

// What goes, in one line: "2 functional failures, 5 failure modes, 3 tasks."
// (empty when nothing is under it).
export function rcmDeleteCounts(c) {
  const parts = [];
  if (c.standards) parts.push(n(c.standards, "performance standard"));
  if (c.functional_failures) parts.push(n(c.functional_failures, "functional failure"));
  if (c.failure_modes) parts.push(n(c.failure_modes, "failure mode"));
  if (c.tasks) parts.push(n(c.tasks, "task"));
  return parts.length ? `${parts.join(", ")}.` : "";
}

// What else happens, one line each (only the ones there are).
export function rcmDeleteLines(c) {
  const out = [];
  if (c.tasks) out.push(`${n(c.tasks, "task")}: no longer scheduled`);
  if (c.tasks_kept) {
    out.push(`${n(c.tasks_kept, "task")} shared with other failure modes: kept for ${c.tasks_kept === 1 ? "them" : "those"}`);
  }
  if (c.links) out.push(`${n(c.links, "link")} to functional failures on other positions: unlinked`);
  if (c.documents) out.push(`${n(c.documents, "document")} on it: taken off`);
  return out;
}

// The one sentence under the list.
export const RCM_DELETE_NOTE = "Failures already recorded against these failure modes keep them in their history. "
  + "You can undo it straight after.";

// The confirm button: "Delete the function".
export function rcmDeleteButton(c) {
  return `Delete the ${WHAT[c.kind] || "row"}`;
}

// The toast after it's done.
export function rcmDeletedText(c) {
  return `Deleted ${quoted(c.name)}${under(c) ? " and everything under it" : ""}.`;
}

// After Undo: what came back, and anything that had changed meanwhile.
export function rcmUndoneText(answer) {
  const skipped = answer?.skipped || [];
  return `Undone: ${quoted(answer?.name)} and everything under it are back.${skipped.length ? ` ${skipped.join(" ")}` : ""}`;
}

// A position's row on the RCM and FME(C)A tabs: Delete… as on the Summary tab
// (the position with everything inside it), danger, last.
export function withPositionDelete(actions, { viewOnly = null } = {}) {
  return [...actions, { id: "tree-delete", label: "Delete…", danger: true, ...(viewOnly ? { disabled: true, reason: viewOnly } : {}) }];
}
