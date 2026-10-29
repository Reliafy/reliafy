// The Explorer's row menu on the Summary tab (right-click a row, its ⋯
// button, or Shift+F10): changing the tree itself. New position (or location)
// inside, Rename, Move to… and Retire, beside Isolate › and Pin this branch. The RCM tab's
// rows keep their own menu (explorerRcm.js rowActions).
//
// Each item is offered only where the server allows it: a position can be
// renamed, moved (PATCH parent_id) and retired; a location renamed and moved
// (there's no retiring a location); an item renamed. An item the server
// would refuse, when the tree already says so (something fitted, positions
// inside, open work, a team that's view only), is shown greyed with the
// reason, so the menu never offers what can't be done. The server checks
// again, and its reason shows if it still refuses.
//
// Pure functions (no React), tested in treeRowMenu.test.js.

const write = (item, blocked) => (blocked ? { ...item, disabled: true, reason: blocked } : item);

// Why a team's workspace can't be changed by this user (null: it can). The
// same words as the "View only" chip in the top bar.
export function viewOnlyReason(team) {
  if (!team) return null;
  if (team.frozen) return "View only: the team's Pro plan has lapsed.";
  if (team.can_edit === false) return "View only: editing this team needs a Pro plan.";
  return null;
}

// Why a position can't be retired now, from what the tree knows (null: try).
// The server's rules: nothing fitted, no position inside still in use, no
// open work order.
export function retireBlock(r, liveKids = 0) {
  if (r.ref.item) return "Something is fitted here. Remove it or fit it elsewhere first.";
  if (liveKids > 0) return `${liveKids === 1 ? "A position is" : `${liveKids} positions are`} inside it. Move or retire ${liveKids === 1 ? "it" : "them"} first.`;
  if (r.ref.status?.open_work > 0) return "It has open work orders. Close or cancel them first.";
  return null;
}

// What a row's menu offers on the Summary tab, in this arrangement (mode):
// [{id, label, danger?, disabled?, reason?}]. `viewOnly`: the reason the
// workspace can't be changed (every change greyed), else null. `kidsOf(id)`:
// how many live positions sit directly inside a position (from the tree's
// rows, whatever the arrangement shows). Pin this branch is added by the page.
export function summaryActions(r, { mode, viewOnly = null, kidsOf = () => 0 } = {}) {
  if (!r) return [];
  const out = [];
  if (r.type === "pos") {
    out.push(write({ id: "tree-new", label: "New position inside" }, viewOnly));
    out.push(write({ id: "tree-rename", label: "Rename…" }, viewOnly));
    // Its place in the positions tree (in Locations, a position's place is
    // where it is, set on its own page).
    if (mode === "positions" || mode === "flat") {
      out.push(write({ id: "tree-move", label: "Move to…" },
        viewOnly || (r.ref.carried_by ? "It sits on an item and moves with it: fit the item elsewhere to move it." : null)));
    }
    out.push(write({ id: "tree-retire", label: "Retire…", danger: true }, viewOnly || retireBlock(r, kidsOf(r.key))));
  } else if (r.type === "loc") {
    out.push(write({ id: "tree-new", label: "New location inside" }, viewOnly));
    out.push(write({ id: "tree-rename", label: "Rename…" }, viewOnly));
    out.push(write({ id: "tree-move", label: "Move to…" }, viewOnly));
  } else if (r.type === "item") {
    out.push(write({ id: "tree-rename", label: "Rename…" }, viewOnly));
  }
  return out;
}

// The menu with Pin this branch (or Show whole tree) added: after the
// changes, before Retire.
export function withPin(items, pin) {
  const at = items.findIndex((i) => i.danger);
  if (at < 0) return [...items, ...pin];
  return [...items.slice(0, at), ...pin, ...items.slice(at)];
}

// A row's Isolate (closes the rest of the tree, opens this row so far): a
// submenu, "with 1 level open", "2 levels open", "3 levels open", "everything
// open" (ids isolate:1, isolate:2, isolate:3, isolate:all); a row with nothing
// inside it has just "Isolate" (it closes the rest; there's nothing to open).
// `can`: whether this row can be isolated (treeIsolate.canIsolate).
export function isolateItems(r, { can } = {}) {
  if (!r || !can) return [];
  if (!r.kids?.length) return [{ id: "isolate:1", label: "Isolate" }];
  return [{
    id: "isolate", label: "Isolate",
    items: [
      { id: "isolate:1", label: "With 1 level open" },
      { id: "isolate:2", label: "With 2 levels open" },
      { id: "isolate:3", label: "With 3 levels open" },
      { id: "isolate:all", label: "With everything open" },
    ],
  }];
}

// How many live positions sit directly inside each position (the tree's rows).
export function liveKids(positions) {
  const n = new Map();
  for (const p of positions || []) if (p.parent_id) n.set(p.parent_id, (n.get(p.parent_id) || 0) + 1);
  return n;
}

// Where a position or location can move to: every one of its kind, depth
// first, A to Z, but never itself nor anything inside it (the server refuses
// a thing inside itself). [{id, name, depth}]; the current parent stays in
// the list (picking it changes nothing).
export function moveTargets(things, id) {
  const kids = new Map();
  const byId = new Map((things || []).map((t) => [t.id, t]));
  for (const t of things || []) {
    const k = t.parent_id && byId.has(t.parent_id) ? t.parent_id : null;
    if (!kids.has(k)) kids.set(k, []);
    kids.get(k).push(t);
  }
  const collator = new Intl.Collator("en", { numeric: true, sensitivity: "base" });
  for (const list of kids.values()) list.sort((a, b) => collator.compare(a.name || "", b.name || ""));
  const out = [];
  const stack = [...(kids.get(null) || [])].reverse().map((t) => [t, 0]);
  while (stack.length) {
    const [t, depth] = stack.pop();
    if (t.id === id) continue; // itself and everything inside it
    out.push({ id: t.id, name: t.name || "(no name)", depth });
    for (const c of [...(kids.get(t.id) || [])].reverse()) stack.push([c, depth + 1]);
  }
  return out;
}
