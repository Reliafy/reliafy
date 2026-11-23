// The Explorer's row menus to the standard (menuStandard.js): what each tab's builder offers for a
// row, sorted into the three sections, with the general slots a row has nothing for greyed with a
// reason in its own words. Every tree row on every tab goes through `explorerRowMenu`, and so does
// the panel heading's ⋯ (the same list for the same row), and the tree's areas (`areaMenu`).
// Pure functions, tested in explorerMenu.test.js.
import { COPY_LINK, OPEN, standardMenu } from "./menuStandard.js";

const HEADING = "A heading for the rows under it.";
// A row with no record of its own: a group ("No class", "… (not at this place)"), the RCM's
// placeholders.
export const HEADING_TYPES = new Set(["group", "nostd", "unassigned", "nofail"]);

// Why a slot is greyed, by row type (the slot's general reason where a type has none).
export const REASONS = {
  rename: {
    item: "Rename the item on its page: Open.", cls: "A class is renamed in Classes.",
    mtask: "Rename the task in its details: Open.", task: "Rename the task in its details: Open.",
    mpkg: "Rename the package on its page: Open.", mpref: "It's a task listed in the package: rename the task itself.",
    pmodel: "A model keeps the name it was saved with: rename it in Models.",
    mission: "Rename it in the mission editor: Open.", phase: "Rename it in the mission editor: Open.",
    mcov: "Its name comes from the model.", mrule: "A rule is named by the block it sets.",
    meas: "Change its name with Edit….", cause: "A link to a row on another position: rename that row.",
  },
  move: {
    pos: "In Locations a position's place is where it is: set it on its page, or move it in Positions.",
    item: "An item moves by fitting it at another position.", cls: "A class is moved in Classes.",
    mtask: "A task stays on its position.", task: "A task stays with its failure mode: link it to another with Link to another failure mode….",
    mpkg: "A package sits where its tasks meet: it moves when they do.", mpref: "It's a task listed in the package.",
    pmodel: "A model stays on its position: unlink it and assign it to another.", mission: "A mission stays with its model.",
    phase: "Use Move earlier or Move later.", mcov: "It belongs to its phase.", mrule: "It belongs to its phase.",
    std: "Use Move up or Move down.", cause: "A link to a row on another position.",
  },
  pin: {},
  focus: {
    mtask: "Focus its position to see its tasks together.", mpref: "Nothing inside it: focus the package.",
    meas: "Nothing inside a measuring point: focus its position.",
  },
  open: {},
};
const reasonsFor = (type) => {
  const out = {};
  for (const slot of Object.keys(REASONS)) if (REASONS[slot][type]) out[slot] = REASONS[slot][type];
  if (HEADING_TYPES.has(type)) {
    for (const slot of ["open", "rename", "move", "copy"]) out[slot] = HEADING;
  }
  return out;
};

// The Monitoring tab's four adds in one submenu: Add › [Measuring point… · Setting… · Consumable… ·
// Sensor channel…].
const MEAS_ADD_GROUP = { id: "meas-add", label: "Add", add: true, test: (it) => /^meas-add-/.test(String(it.id)) };

// The tree's own actions a position or place keeps on every tab (Rename…, Move to…, Delete…): taken
// from the Summary tab's list when a tab's builder left them out. `tree`: summaryActions' items.
const TREE_IDS = ["tree-rename", "tree-move", "tree-delete"];
export function withTreeChanges(items, r, tree = []) {
  if (!r || (r.type !== "pos" && r.type !== "loc")) return items;
  const have = new Set(items.filter((it) => it && !it.separator).map((it) => it.id));
  const add = tree.filter((it) => TREE_IDS.includes(it.id) && !have.has(it.id));
  return [...items, ...add];
}

// A row's menu, to the standard. `items`: what the tab's builder gave; `tree`: the Summary list for
// the row (for Rename…, Move to…, Delete… on positions and places); `canOpen`: false where Open has
// nothing to show.
export function explorerRowMenu(r, items, { tree = [], canOpen = true, canLink = true } = {}) {
  if (!r) return [];
  const list = withTreeChanges(items || [], r, tree);
  const heading = HEADING_TYPES.has(r.type);
  const general = {};
  if (!heading && canOpen) general.open = { id: OPEN, label: "Open" };
  if (!heading && canLink) general.copy = { id: COPY_LINK, label: "Copy link" };
  return standardMenu(list, { reasons: reasonsFor(r.type), general, group: MEAS_ADD_GROUP });
}

// The tree's areas that aren't a row: the column headers, the empty space under the rows, the quiet
// "+ New position" row. The tree's own actions, from the same builder (no row slots).
//   add       {label, disabled?, reason?}: New position at the top level (the tree's add row)
//   levels    true: Open to a level › (1, 2, 3 levels; Close everything)
//   focused   a focus is on: Clear focus
//   pinned    a branch is pinned: Show whole tree
export function areaMenu({ add = null, levels = true, focused = false, pinned = false } = {}) {
  const items = [];
  if (add) items.push({ id: "area-add", label: add.label || "New position", add: true, ...(add.disabled ? { disabled: true, reason: add.reason || "You can't add here." } : {}) });
  if (levels) {
    items.push({ id: "area-levels", label: "Open to a level", items: [
      { id: "level:1", label: "1 level" }, { id: "level:2", label: "2 levels" }, { id: "level:3", label: "3 levels" },
      { separator: true }, { id: "level:0", label: "Close everything" },
    ] });
  }
  if (focused) items.push({ id: "focus-clear-area", label: "Clear focus" });
  if (pinned) items.push({ id: "unpin-area", label: "Show whole tree" });
  return standardMenu(items, { skip: ["open", "rename", "move", "focus", "pin", "copy"] });
}
