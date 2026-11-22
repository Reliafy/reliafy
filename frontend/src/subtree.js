// The Explorer's roll-up (Derryn, 22 Nov 2026: "at any level, you should see all the stuff from
// underneath it aggregated"). A tab on a tree node lists the records on the node and on everything
// below it, at any depth; the server gives them in one read (Maintenance.subtree_ids, inside the
// asset opened: ?root=). Each record carries `subject` ({id, name, within}: where it lives, with
// its nearest parents so twins can be told apart). These say where a record lives and put the
// node's own first; the shared cell that shows it is ui/WhereItLives.jsx.

// Whether a record is on the node itself (`key`: the node's id).
export function isHere(rec, key) {
  return !!key && rec?.subject?.id === key;
}

// Where a record is, to tell twins apart: "Station 2 › Pump 3 › Drive motor".
export function wherePath(rec) {
  return [rec?.subject?.within, rec?.subject?.name].filter(Boolean).join(" › ");
}

// The second line under its position: "This position" on the node's own, else what it sits in.
export function whereNote(rec, key, own = "This position") {
  return isHere(rec, key) ? own : rec?.subject?.within || "";
}

// How many of the records are on the node itself, as people read it ("1,204").
export function hereCount(recs, key) {
  return recs.filter((r) => isHere(r, key)).length.toLocaleString("en-AU");
}

// A comparator: the node's own records first (0 when both or neither are).
export function hereFirst(key) {
  return (a, b) => Number(isHere(b, key)) - Number(isHere(a, key));
}
