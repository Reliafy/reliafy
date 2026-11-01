// A list's order after moving the item at `from` to `to` (a drag, or Move up /
// Move down): a new array, or null when nothing moves or either is out of range.
export function moveItem(list, from, to) {
  if (from === to || from < 0 || to < 0 || from >= list.length || to >= list.length) return null;
  const out = list.slice();
  const [it] = out.splice(from, 1);
  out.splice(to, 0, it);
  return out;
}
