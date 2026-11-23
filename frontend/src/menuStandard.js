// The one standard for every row menu in the app (Derryn, 23 Nov 2026: "a general delete button at
// the bottom with a line separator, a general section at the top, and then a middle section, which
// is the contextual options"). Every surface that shows a thing's own actions feeds this: a tree
// row (right-click, its ⋯, Shift+F10, a long press), the panel heading's ⋯, a list row's ⋯, the RBD
// canvas and the fault-tree outline. RowMenu draws what it returns.
//
// Three sections, a line between them:
//   top     the general actions, the same names in the same order on every row and every tab:
//           Open · Rename… · Move to… · Focus › · Pin this branch · Copy link. One that doesn't
//           apply to a row stays, greyed, with the reason (never hidden).
//   middle  the contextual: the tab's adds first, then the row's own actions (a line between
//           them when there are more than four).
//   bottom  exactly one destructive item, red, always last: Delete… (structure, with Undo),
//           Retire… (records with history), Unlink… (a model on a position) or Remove from…
//           (a link). Greyed with the reason rather than hidden; none on a row with nothing to
//           remove (a group row, a forecast row).
// At most MAX_ITEMS items at each level: the middle's overflow folds into "More ›".
//
// Pure functions (no React), tested in menuStandard.test.js.

export const MAX_ITEMS = 10;

// The general section's slots, in order, with their one name each.
export const GENERAL = ["open", "rename", "move", "focus", "pin", "copy"];
export const GENERAL_LABEL = {
  open: "Open", rename: "Rename…", move: "Move to…", focus: "Focus", pin: "Pin this branch", copy: "Copy link",
};
// The synthetic ids, for a slot a builder didn't fill (its handler is the surface's own).
export const GENERAL_ID = {
  open: "row-open", rename: "row-rename", move: "row-move", focus: "focus", pin: "row-pin", copy: "row-copy-link",
};
export const OPEN = GENERAL_ID.open;
export const COPY_LINK = GENERAL_ID.copy;
export const MORE = "more";

// The one destructive item, by kind.
export const DESTROY = ["delete", "retire", "unlink", "remove"];
export const DESTROY_LABEL = { delete: "Delete…", retire: "Retire…", unlink: "Unlink…", remove: "Remove from…" };

// Why a general slot is greyed when a row has nothing for it (a builder's own reason wins).
export const GENERAL_REASON = {
  open: "A heading for the rows under it: there's nothing to open.",
  rename: "Its name comes from what it shows: there's nothing to rename here.",
  move: "It stays where it is: it moves with the row it belongs to.",
  focus: "Nothing inside it to focus on: focus the row it sits under.",
  pin: "Only a position or a place can be pinned: pin the one it sits under.",
  copy: "There's no page to link to for this row.",
};

// Existing item ids to their general slot (so every builder's Open, Rename and the rest land in the
// top section with the one name). An item may also say `slot` itself.
export const SLOT_OF = {
  "row-open": "open", open: "open", "mtask-open": "open", "mpkg-open": "open", "mfc-open": "open",
  "model-open": "open", "model-rbd-pane": "open", "model-strategy-open": "open",
  "mission-open": "open", "mission-phase-open": "open", "meas-page": "open", "node-open": "open",
  "row-rename": "rename", "tree-rename": "rename", rename: "rename", "node-rename": "rename",
  "row-move": "move", "tree-move": "move", "move-to": "move", "meas-move": "move",
  "row-pin": "pin", pin: "pin", unpin: "pin",
  "row-copy-link": "copy",
};
// Existing ids of a destructive item, to its kind (a `danger` item with none of these is read by its
// label: Retire…, Unlink…, Remove…, else Delete…).
export const DESTROY_OF = {
  "tree-delete": "delete", delete: "delete", "mission-delete": "delete", "mission-phase-delete": "delete",
  "mission-rule-delete": "delete", "node-delete": "delete", "edge-delete": "delete",
  "meas-retire": "retire", "mtask-retire": "retire", "mpkg-retire": "retire", retire: "retire",
  "model-unlink": "unlink", unlink: "remove", "mpref-remove": "remove",
};
const isFocus = (id) => typeof id === "string" && (id === "focus" || id.startsWith("isolate") || id === "focus-clear");

const kindOf = (it) => {
  if (it.destroy && DESTROY.includes(it.destroy)) return it.destroy;
  if (DESTROY_OF[it.id]) return DESTROY_OF[it.id];
  const l = String(it.label || "");
  if (/^Retire/.test(l)) return "retire";
  if (/^Unlink/.test(l)) return "unlink";
  if (/^Remove/.test(l)) return "remove";
  return "delete";
};
// The bottom item's words: the kind's one name, except a Remove, which says from what
// ("Remove from this failure mode…").
export function destroyLabel(it, kind = kindOf(it)) {
  if (kind === "remove" && /^Remove /.test(String(it.label || ""))) return it.label;
  return DESTROY_LABEL[kind];
}

// An adding item (the tab's adds go first in the middle): Add…, New…, Build an item…, Import….
// Not "Add to library…" or "Add to package…" (doing something with the row, not adding inside it).
export const isAdd = (it) => !!it && !it.separator && (it.add === true
  || (it.add !== false && /^(Add|New|Build an item|Import)\b/.test(String(it.label || "")) && !/^Add (to|\d)/.test(String(it.label || ""))));

const off = (reason) => ({ disabled: true, reason });
const greyed = (slot, reason) => ({ id: GENERAL_ID[slot], label: GENERAL_LABEL[slot], slot, ...off(reason || GENERAL_REASON[slot]) });

// Focus ›: one entry. Its submenu holds "Focus <what the tab shows>", the depths (flattened from
// "Focus to a depth ›"), Focus on incomplete rows, then a line and Clear focus.
export function focusMenu(items) {
  const flat = [];
  for (const it of items || []) {
    if (!it || it.separator) continue;
    if (it.items) flat.push(...it.items.filter((s) => !s.separator));
    else flat.push(it);
  }
  const clear = flat.filter((it) => it.id === "focus-clear");
  const rest = flat.filter((it) => it.id !== "focus-clear");
  const sub = [...rest, ...(rest.length && clear.length ? [{ separator: true }] : []), ...clear];
  return sub.length ? { id: GENERAL_ID.focus, label: GENERAL_LABEL.focus, slot: "focus", items: sub } : null;
}

// Drop a line at either end, and two in a row.
export function tidy(items) {
  const out = [];
  for (const it of items) {
    if (!it) continue;
    if (it.separator && (!out.length || out[out.length - 1].separator)) continue;
    out.push(it);
  }
  while (out.length && out[out.length - 1].separator) out.pop();
  return out;
}

// The menu, from its three sections. `general`: {open, rename, move, focus, pin, copy}, each an item,
// a reason string (the slot greyed with it), or null/undefined (left out: an area's menu, which has
// no row). `adds`, `actions`: the middle. `destroy`: {id, kind, label?, disabled?, reason?} or null.
// Returns RowMenu's items, the lines placed, at most `max` at the top level.
export function buildMenu({ general = {}, adds = [], actions = [], destroy = null, max = MAX_ITEMS } = {}) {
  const top = [];
  for (const slot of GENERAL) {
    const g = general[slot];
    if (g == null || g === false) continue;
    if (typeof g === "string") top.push(greyed(slot, g));
    else if (slot === "focus" && !g.items && !g.id) top.push(greyed("focus", g.reason));
    else top.push({ ...g, label: slot === "move" && /^Move \d/.test(String(g.label || "")) ? g.label
      : slot === "pin" && g.id === "unpin" ? g.label || "Show whole tree" : GENERAL_LABEL[slot], slot });
  }
  const a = (adds || []).filter((it) => it && !it.separator);
  const b = (actions || []).filter((it) => it && !it.separator);
  const end = destroy ? [{ ...destroy, label: destroyLabel(destroy, destroy.kind || kindOf(destroy)), destroy: destroy.kind || kindOf(destroy), danger: true }] : [];
  let middle = [...a, ...(a.length && b.length && a.length + b.length > 4 ? [{ separator: true }] : []), ...b];
  const room = max - top.length - end.length;
  const count = middle.filter((it) => !it.separator).length;
  if (count > room) {
    const keep = Math.max(0, room - 1);
    // What stays at the top: the first `keep` items that can be used now (a greyed one folds first),
    // in their own order.
    const real = middle.filter((it) => !it.separator);
    const stay = new Set([...real.filter((it) => !it.disabled), ...real.filter((it) => it.disabled)].slice(0, keep));
    const kept = [];
    const folded = [];
    middle.forEach((it, i) => {
      if (!it.separator) { (stay.has(it) ? kept : folded).push(it); return; }
      // A line stays only between two items that both stay.
      const next = middle.slice(i + 1).find((x) => !x.separator);
      (kept.length && next && stay.has(next) ? kept : folded).push(it);
    });
    // A submenu folded into More › gives up its items in place (two levels at most).
    const more = [];
    for (const it of folded) {
      if (it.separator) { more.push(it); continue; }
      if (it.items) more.push({ separator: true }, ...it.items, { separator: true });
      else more.push(it);
    }
    middle = [...kept, { id: MORE, label: "More", items: tidy(more) }];
  }
  return tidy([...top, { separator: true }, ...middle, { separator: true }, ...end]);
}

// A builder's flat list (the menus written before the standard) sorted into the three sections:
// each item to its slot by id (SLOT_OF) or `slot`, the Focus items into Focus ›, the destructive one
// (DESTROY_OF, or `danger`) to the bottom, the rest to the middle, adds first.
//   reasons   {slot: reason}: why a slot this row has nothing for is greyed (GENERAL_REASON else)
//   general   {slot: item}: a slot's item, where the builder has none (a synthetic Open)
//   skip      slots to leave out altogether (an area's menu)
//   group     {id, label, test(it)}: the middle items that pass `test` go in one submenu (the four
//             adds on the Monitoring tab: Add ›)
export function standardMenu(items, { reasons = {}, general: given = {}, skip = [], group = null, max = MAX_ITEMS } = {}) {
  const slots = {};
  const focus = [];
  const middle = [];
  const destroys = [];
  for (const it of items || []) {
    if (!it || it.separator) continue;
    if (isFocus(it.id) || it.id === "isolate") { focus.push(it); continue; }
    const slot = it.slot || SLOT_OF[it.id];
    if (slot && GENERAL.includes(slot) && !slots[slot]) { slots[slot] = it; continue; }
    if (it.danger || it.destroy || DESTROY_OF[it.id]) { destroys.push(it); continue; }
    middle.push(it);
  }
  // One destructive item: any others (there shouldn't be) stay, in the middle, not red.
  const [destroy, ...extra] = destroys;
  for (const it of extra) middle.push({ ...it, danger: false });
  const general = {};
  for (const slot of GENERAL) {
    if (skip.includes(slot)) continue;
    if (slot === "focus") {
      const f = focusMenu(focus);
      general.focus = f || given.focus || reasons.focus || GENERAL_REASON.focus;
      continue;
    }
    general[slot] = slots[slot] || given[slot] || reasons[slot] || GENERAL_REASON[slot];
  }
  let mid = middle;
  if (group) {
    const inside = middle.filter(group.test);
    if (inside.length > 1) {
      const at = middle.indexOf(inside[0]);
      const rest = middle.filter((it) => !group.test(it));
      rest.splice(at, 0, { id: group.id, label: group.label, add: group.add, items: inside });
      mid = rest;
    }
  }
  const lead = [];
  let i = 0;
  while (i < mid.length && (isAdd(mid[i]) || (mid[i].items && mid[i].add !== false && (mid[i].add || mid[i].items.some(isAdd))))) lead.push(mid[i++]);
  return buildMenu({ general, adds: lead, actions: mid.slice(i), destroy: destroy || null, max });
}

// What's wrong with a menu against the standard (empty: nothing). For tests, on every builder.
//   - at most `max` items at each level;
//   - a disabled item says why (`reason`, not `title` alone);
//   - at most one danger item, last, after a line;
//   - no line at either end or two in a row.
export function menuProblems(items, { max = MAX_ITEMS } = {}) {
  const out = [];
  const level = (list, where) => {
    const real = list.filter((it) => !it.separator);
    if (real.length > max) out.push(`${where}: ${real.length} items (at most ${max})`);
    list.forEach((it, i) => {
      if (it.separator && (i === 0 || i === list.length - 1 || list[i - 1]?.separator)) out.push(`${where}: a stray line at ${i}`);
      if (!it.separator && it.disabled && !it.reason) out.push(`${where}: “${it.label}” is greyed with no reason`);
      if (it.items) level(it.items, `${where} › ${it.label}`);
    });
    const dangers = list.map((it, i) => (it.danger ? i : -1)).filter((i) => i >= 0);
    if (dangers.length > 1) out.push(`${where}: ${dangers.length} red items (one at most)`);
    if (dangers.length === 1 && where === "menu") {
      const d = dangers[0];
      if (d !== list.length - 1) out.push(`${where}: the red item isn't last`);
      if (d > 0 && !list[d - 1].separator) out.push(`${where}: no line before the red item`);
    }
  };
  level(items || [], "menu");
  return out;
}

// "Package 3 tasks…": a label for an action on several rows picked together (`n` > 1), the noun
// after the verb. `one`: the label for one row.
export function counted(one, n, noun = "tasks") {
  if (!(n > 1)) return one;
  const verb = String(one).replace(/…$/, "");
  return `${verb} ${n.toLocaleString("en-AU")} ${noun}${String(one).endsWith("…") ? "…" : ""}`;
}

// The ids every surface handles the same way, whatever the row: Copy link puts `url` on the
// clipboard. Resolves to true when it was copied.
export async function copyLink(url) {
  try {
    await navigator.clipboard.writeText(url);
    return true;
  } catch {
    return false;
  }
}

// The address that opens a row: the page's own, with `sel` (and any `extra`) set.
export function rowLink(href, sel, extra = {}) {
  try {
    const u = new URL(href);
    if (sel != null) u.searchParams.set("sel", sel);
    for (const [k, v] of Object.entries(extra)) if (v != null) u.searchParams.set(k, v);
    return u.toString();
  } catch {
    return href;
  }
}
