# ContextMenu

The right-click menu: a thing's own actions at the pointer — a row in the Explorer tree, a block or link on the RBD canvas, a node in the fault-tree outline, a list row. In code it is `RowMenu` (`components/RowMenu.jsx`), the one renderer, and what goes in it comes from the one builder, `menuStandard.js` (`buildMenu`, or `standardMenu` for a list of items). No surface writes its own separators or decides where Delete goes.

## The standard (Derryn, 23 Nov 2026)

"A general delete button at the bottom with a line separator, a general section at the top, and then a middle section, which is the contextual options." Every menu has three sections with a line between them:

1. **Top: general.** The same names in the same order on every row and every tab: **Open · Rename… · Move to… · Focus › · Pin this branch · Copy link**. A slot that doesn't apply to a row stays, greyed, with its reason. Focus › is one entry: its submenu has two sections under small labels, **What** (Focus <the kinds the tab shows inside the row>: Focus tasks, Focus packages; Focus functions, Focus failure modes, Focus tasks, Focus on incomplete rows on the RCM tab; Focus here where a tab has no kinds) and **Depth** (1 level, 2 levels… only as deep as the row goes), then a line and Clear focus. Pin this branch reads Show whole tree on the row pinned.
2. **Middle: contextual.** The tab's adds first (Add task…, New position inside, Life model ›), then the row's own actions (Optimise…, Open in ›, Decide…). A line between the two only when there are more than four.
   - **Open in ›** (the Explorer's Maintenance tab: a position, a task, a work package): a submenu of left-menu tools opened filled in from the row and everything below it: Optimise, Spares forecast, Hours forecast, Cost forecast. Nothing in the Explorer changes; the tool names where it came from, with a link back. Put it early in the middle (right after the row's first action) so the overflow into More › never takes it.
3. **Bottom: one destructive item**, always last, always after a line, always red, greyed with a reason rather than hidden:
   - **Delete…** for structure (positions, locations, functions, standards, functional failures, failure modes, missions, phases, rules, product structure): a counted dialog, then Undo.
   - **Retire…** for records with history (items, tasks, packages, measuring points, consumables).
   - **Unlink…** for a model on a position (the model stays in Models).
   - **Remove from…** for a link (Remove from this failure mode…, Remove from package…).
   - None on a row with nothing to remove (a group row): the line and the item are left out.

**The same kind of record has the same menu everywhere** (Derryn, 23 Nov 2026). A position is a position at every depth, whether it has positions, tasks or "N tasks here" under it, and whether it's drawn muted as context (a position above the place opened, `assetTree.js` VIA): the same general section, the tab's adds and actions, and Delete…. Greyed items appear only where the action exists but doesn't apply right now, with the reason; never a whole menu of greyed items. A row that is only a heading, not a record (No class, No home yet), has **no menu** of its own: a right-click there opens the tree's menu. An RCM placeholder (No functional failure yet) has only what it can do (its add).

Rules the builder keeps (and `menuProblems` checks in the tests):

- **One name per action**, the whole app: Open (not Open…, Open in the mission editor), Rename… (not Edit description), Move to… (not Move…), Delete… (not Delete function…).
- **A greyed item always says why**: `reason`, shown as help text under it and as its `aria-describedby`; never `title` alone.
- **At most 10 items at each level.** The middle's overflow folds into **More ›** (a submenu folded there gives up its items in place, between lines).
- **Several rows picked**: the labels count them ("Package 3 tasks…"); an action that works on one row only is greyed with the reason.
- **A section label in a submenu** (`{heading: true, label}`, Focus ›'s What and Depth) always has an item under it; a label with nothing under it is left out (`tidy`).
- An area that isn't a row (a column header, empty space under the rows, a heading row like "No class") has its own menu from the same builder: the tree's actions (New position at the top level, Open to a level ›, Clear focus, Show whole tree). The browser's own menu opens only inside a field being typed in.

## How it opens

Right-click, the row's ⋯ button (`MoreMenu`), a long press on a phone, or Shift+F10 / the Menu key on a focused row: all four open the same menu. Every action in it must also be reachable another way (a ⋯ button or a toolbar); the right-click is a shortcut, never the only door.

A long press (500 ms) opens the menu under the finger; lifting the finger leaves it open (no click or mouse event follows from that touch). Rows set `-webkit-touch-callout: none` and `user-select: none` on touch screens, so iOS shows no text callout or selection over the menu; fields in a row keep theirs.

## Props

- `items` — `[{id, label, danger?, disabled?, reason?, pro?, items?, checked?} | {separator: true} | {heading: true, label}]`.
  - `pro` — a Pro-only action (making libraries, for example): the small `pro-tag` after its label, shown only to users without Pro (`ProTag`). The item still opens; what it opens explains Pro.
  - `danger` — a destructive action in `danger-text`, last in the menu.
  - `disabled` + `reason` — the item stays in the menu, greyed, with the reason in `help` type under it (and as its description to a screen reader). Don't hide what can't be used now; say why.
  - `items` — a submenu ("Focus to a depth ›"). It opens beside the menu on a wide screen, in place under its item on a phone.
  - `checked` (true | false) — a radio in a submenu, ticked with ✓.
  - `separator` — a `border` line between groups; the arrow keys pass over it.
  - `heading` — a section's small label (`help` size, `fs-12`/`lh-12` at 500 in `text-secondary`, `.row-menu-heading`): not an item, never focused or chosen; the arrow keys and type-to-jump pass over it. Use it in a submenu with two or more sections (Focus ›: What, Depth), each after a line.
- `at` — `{x, y}`, the pointer or the corner of what opened it. The menu moves in to stay on screen, at least 8 px from every edge: it is measured at its full width (hidden, top left) before it is placed, so items that wrap near an edge never make it spill off.
- `label` — the menu's name ("Actions for Feed pump").
- `anchorId` — the row it belongs to: a scroll that moves the row away closes the menu.
- `onChoose(id)` — runs after the menu has closed.
- `onClose()` — puts the focus back on the row.

The same menu lists the tabs folded into a tab row's "⋯ N" (`Tabs` with `overflow`).

## On a list row

Every saved-item list (Data, models, RBDs, fault trees, forecasts, strategy, RCM studies, the registers) ends each row with one ⋯ button: `RowActions` in `components/LibRows.jsx`, which opens this menu through `MoreMenu`. A `MoreMenu` item may carry `items`, a submenu (the failure ranking's **Open in › Failure reports**); choosing a submenu item runs its own `onSelect`.

- Pass `to` (or `onOpen`) for Open, `actions` for the row's own actions (`[{id, label, onSelect, disabled?, reason?}]`; falsy entries are skipped, so `!r.read_only && {…}` works), and `onDelete`.
- The menu reads: Open, the actions, a line, then "Delete…" (or "Remove from my view" for a shared sample or an item shared with you).
- A row with Open as its only action keeps a plain Open button rather than a menu of one.
- The button is named "Actions for <row name>". The row's name stays a link, and a click on the row still opens it.
- Never put icon buttons (copy, edit, share, a delete bin) in the row itself. A form's own editable rows (a line in a parts list) may keep a single remove button; that's editing the form, not a list row's actions.

The menu's look lives in `index.css` (`.ovm-menu.row-menu`), not with any page, so it is styled wherever it opens.

## Look

- A `bg-surface` card with a 1px `border`, `radius-lg`, `shadow-lg` and 4px padding. 200px at least.
- Items are `fs-13` at 500 in `text`, `radius-md`, 7px × 10px padding.
- Hover and keyboard focus show `accent-subtle` with `accent-text`. Danger items hover in `danger-bg`.
- An open submenu's item stays tinted. The submenu sits 4px beside it.

## Keyboard

The first item takes focus. ↑ ↓ Home End move, Enter or Space chooses, → opens a submenu and ← or Esc goes back to its item. Typing a letter jumps to the next item starting with it (letters typed together within 0.7 s spell a word). Esc or Tab closes the menu, and the focus goes back to what opened it (the row, the ⋯ button).

## Focus and Pin

Focus › is the fourth general item on every row that can be focused. Its submenu: **What** (the tab's kinds inside the row: Focus tasks, Focus packages, Focus functions, Focus failure modes, Focus measurements, Focus models, Focus missions; or Focus here), a line, **Depth** (1 level … as deep as the row goes), then Clear focus while a focus is on. A row with nothing inside it has just Focus here, no labels. **Pin this branch** follows it. See `TreeTable`.

## Order

Top (general), middle (adds, then actions), bottom (the one destructive item after a line). Labels are verbs in sentence case; "…" when the item opens a dialog. Build a menu with `buildMenu({general, adds, actions, destroy})`, or pass a list to `standardMenu(items, {reasons})`, which sorts each item into its section by id (`SLOT_OF`, `DESTROY_OF`).
