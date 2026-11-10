// The Explorer's row menu on the Summary tab (right-click a row, its ⋯
// button, or Shift+F10): changing the tree itself. New position (or location)
// inside, Add failure report… (a position: a report sits at a position),
// Rename, Move to… and Delete…, beside Focus › and Pin this branch. The RCM
// tab's rows keep their own menu (explorerRcm.js rowActions).
//
// On every other tab a row's menu starts with what that tab keeps under it
// (Derryn, 10 Nov 2026: "The relevant 'add' should be the top item"): New
// position inside is first on the Summary tab only. Elsewhere the tab's adds
// come first, then a line, then these items (addsFirst, tabMenu): Failure
// reports puts Add failure report… first; the LSA tab Package the tasks here…
// (lsaLead: the drafts open in the panel beside the tree); Measurements its
// four adds (explorerMeasurements.js measAddActions); RCM, FME(C)A, Modelling
// and Missions build their own menus (explorerRcm.js, explorerFmea.js,
// explorerModels.js, explorerMissions.js). Where a tab has nothing of its own
// for a row (a design's row on the LSA tab: a design has no packages; a place
// on Failure reports), the changes to the tree go last, after Focus and Pin
// this branch (tabMenu).
//
// A position can be renamed, moved (PATCH parent_id) and deleted; a location
// renamed, moved and deleted; an item renamed (never deleted from the tree:
// a delete keeps every item, and items are retired on the Items pages).
// Delete… is never greyed for what's inside (a delete takes everything below
// it, items kept, and Undo brings it back: treeDelete.js); only a team that's
// view only greys the changes, with the reason.
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

// What a row's menu offers on the Summary tab, in this arrangement (mode):
// [{id, label, danger?, disabled?, reason?}]. `viewOnly`: the reason the
// workspace can't be changed (every change greyed), else null. Pin this
// branch is added by the page.
const DELETE = { id: "tree-delete", label: "Delete…", danger: true };
export function summaryActions(r, { mode, viewOnly = null } = {}) {
  if (!r) return [];
  const out = [];
  if (r.type === "pos") {
    out.push(write({ id: "tree-new", label: "New position inside" }, viewOnly));
    out.push(write({ id: "report-new", label: "Add failure report…" }, viewOnly));
    // Something that happened there (a storm, a lightning strike): tasks triggered by it raise their work.
    out.push(write({ id: "event-log", label: "Log an event…" }, viewOnly));
    out.push(write({ id: "tree-rename", label: "Rename…" }, viewOnly));
    // Its place in the positions tree (in Locations, a position's place is
    // where it is, set on its own page).
    if (mode === "positions" || mode === "flat") {
      out.push(write({ id: "tree-move", label: "Move to…" },
        viewOnly || (r.ref.carried_by ? "It sits on an item and moves with it: fit the item elsewhere to move it." : null)));
    }
    out.push(write(DELETE, viewOnly));
  } else if (r.type === "loc") {
    out.push(write({ id: "tree-new", label: "New location inside" }, viewOnly));
    out.push(write({ id: "tree-rename", label: "Rename…" }, viewOnly));
    out.push(write({ id: "tree-move", label: "Move to…" }, viewOnly));
    out.push(write(DELETE, viewOnly));
  } else if (r.type === "item") {
    out.push(write({ id: "tree-rename", label: "Rename…" }, viewOnly));
  }
  return out;
}

// A tab's own adds first, then a line, then the rest (the rest alone with no adds).
export function addsFirst(adds, rest) {
  return adds?.length ? [...adds, { separator: true }, ...rest] : rest;
}
// What a tab puts first on the Summary menu's rows (the tabs drawn as the plain
// tree, not a tree-table): ids, in order.
export const TAB_LEADS = { reports: ["report-new"] };

// The LSA tab's own for a row: Package the tasks here… (drafts packages from
// the tasks there and below in no package; they open in the panel beside the
// tree, never a dialog). A position or a place only, and never a design's (a
// design's tasks are packaged on the items built from it).
export const LSA_PACKAGE = { id: "lsa-package", label: "Package the tasks here…" };
export function lsaLead(r, { design = false, viewOnly = null } = {}) {
  if (!r || design || (r.type !== "pos" && r.type !== "loc")) return [];
  return [write(LSA_PACKAGE, viewOnly)];
}

// The menu with Pin this branch (or Show whole tree) added: after the
// changes, before Delete.
export function withPin(items, pin) {
  const at = items.findIndex((i) => i.danger);
  if (at < 0) return [...items, ...pin];
  return [...items.slice(0, at), ...pin, ...items.slice(at)];
}

// The tree's quiet last row ("+ New position inside …") follows the same rule
// as the row menu: adding to the tree belongs to the Summary tab. On every
// other tab the tree ends at its last row.
export const showsAddRow = (tab) => !tab || tab === "summary";

// A row's menu on a tab drawn as the plain tree. `items`: the Summary menu
// (summaryActions); `lead`: what the tab itself offers for the row (lsaLead);
// `pin`: Focus and Pin this branch.
//   Summary: the changes to the tree, Focus and Pin before Delete….
//   A tab with something of its own for the row: that first, a line, then the
//   Summary menu.
//   A tab with nothing of its own for it: New … inside, Rename…, Move to… and
//   Delete… go last, after Focus and Pin (they change the tree, not what the
//   tab shows), so the tab never opens on New position inside.
const TREE_CHANGES = ["tree-new", "tree-rename", "tree-move", "tree-delete"];
export function tabMenu(tab, items, { lead = [], pin = [] } = {}) {
  if (!tab || tab === "summary") return withPin(items, pin);
  const ids = TAB_LEADS[tab] || [];
  const first = [...lead, ...items.filter((i) => ids.includes(i.id))];
  const rest = items.filter((i) => !ids.includes(i.id));
  if (first.length) return withPin(addsFirst(first, rest), pin);
  const tree = rest.filter((i) => TREE_CHANGES.includes(i.id));
  const before = [...rest.filter((i) => !TREE_CHANGES.includes(i.id)), ...pin];
  return before.length && tree.length ? [...before, { separator: true }, ...tree] : [...before, ...tree];
}

// A row's Isolate (closes the rest of the tree, opens this row so far): a
// submenu, "with 1 level open", "2 levels open", "3 levels open", "everything
// open" (ids isolate:1, isolate:2, isolate:3, isolate:all); a row with nothing
// inside it has just "Isolate" (it closes the rest; there's nothing to open).
// `can`: whether this row can be isolated (treeIsolate.canIsolate). `levels`:
// how many levels there are below it (treeIsolate.levelsBelow), given on the
// RCM tab, where a row can go five deep (down to the tasks): "With 4 levels
// open" and "With 5 levels open" are offered there when the rows go that deep.
export function isolateItems(r, { can, levels = 0 } = {}) {
  if (!r || !can) return [];
  if (!r.kids?.length) return [{ id: "isolate:1", label: "Focus" }];
  const deeper = [4, 5].filter((n) => levels >= n).map((n) => ({ id: `isolate:${n}`, label: `With ${n} levels open` }));
  return [{
    id: "isolate", label: "Focus",
    items: [
      { id: "isolate:1", label: "With 1 level open" },
      { id: "isolate:2", label: "With 2 levels open" },
      { id: "isolate:3", label: "With 3 levels open" },
      ...deeper,
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
