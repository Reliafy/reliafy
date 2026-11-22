# RBD editor toolbar

The one toolbar above the RBD builder's canvas, wherever the builder shows: the RBD page and the Explorer's table area beside the tree (the same `RbdEditor`). One row of `control-sm` controls (`control-lg` on a phone), tokens only.

## Layout

Left to right, in three groups. The toolbar is **one row at every width and never wraps** (see Running short):

1. **Tools**: **+ Add block ▾**, the one primary button (building is the job here); **Undo** and **Redo**, ghost icon buttons; the **Diagram settings** trigger; the common-cause chip when the diagram has groups.
2. **What an action did** ("Added Pump B alongside Pump A", "Undone."): bold `accent-text` words filling the gap, two lines at most. On a narrow builder it floats under the row while it shows, so the row never grows.
3. **State and the rest**, pushed right: the save status, the check's chip, the explicit **Save** (only when autosave isn't saving this diagram), **Full screen** (an icon; "Exit full screen" is spelt out), **⋯**, and × in the Explorer's pane.

There is nothing floating over the canvas except the common-cause button while blocks are selected. The diagram's name isn't in the toolbar: the page title names it, and beside the tree it is the pane's title over the tabs. In full screen (the title out of sight) it shows at the start of the right-hand group, and gives way on a narrow builder.

## Running short

By the builder's own width (`rbdEditorLayout.js`), in this order; nothing wraps:

1. **Under 660 px:** "+ Add block ▾" becomes the **+** alone, still the primary button, still opening the same menu, with the accessible name and tooltip "Add block".
2. **Under 580 px:** the save status and the check show their icon alone (the count stays on the check), and **Full screen** moves into **⋯** (Exit full screen stays on the toolbar while in it).
3. **Under 400 px (a phone):** **Undo** and **Redo** move into **⋯**.

**+ Add** and **Diagram settings** are always on the row. Wider builders keep the words.

## Diagram settings

The diagram's properties, not actions, in one popover (`role="dialog"`) off a secondary trigger that reads what they are now ("Hours · Repairable · Safety function"; the icon alone on a narrow builder):

- **Time unit**: a `Field` with a `TextInput` (suggestions from a datalist).
- **Kind**: `ChoiceChips` (Non-repairable, Repairable, Network), as it's a saved value, with one line of help saying what the chosen kind analyses.
- **Safety function**: a `Switch` (applies at once), with the target SIL `Chip` beside it when on.
- **Show the maintenance plan**: a `Switch`, on a repairable diagram.

Only a click outside or Escape closes it, so the mouse drifting away while typing doesn't. It stays inside the window at 400 px.

## Saving

- **Autosave** (the default): a diagram the user can write, once named, saves itself 1.2 s after the last change, one save at a time (`rbdAutosave.js`). The status reads **Saving…**, **Saved**, or **Couldn't save** with a **Retry** link (or **Save a copy…** when someone else saved it meanwhile). Closing the pane or the page saves what's waiting.
- **Not saved yet / a sample**: the status says so and **Save…** / **Save a copy…** asks for a name.
- **Autosave off** (Settings › Editing, or ⋯ › Autosave; one account setting): **Save** and **Unsaved changes** as before, and leaving asks first (the pane's discard question, a link away, or the browser's own prompt on closing the tab).
- **Save as new…** is in ⋯.
- The status is an icon and words: a tick (saved), a spinner (saving), a warning triangle (couldn't save; Retry stays tappable) or a dot. On a phone the words go and the icon stays, with the words as its accessible name and tooltip, so colour and shape are never the only signal.

## Undo and Redo

Every edit (blocks, connections and the diagram's settings) is a step, a drag one step where it's let go (`rbdHistory.js`, the last 100). Ctrl/⌘-Z, Ctrl/⌘-Shift-Z and Ctrl-Y, or the buttons. In a text box the box's own undo works instead. The stack is per session: it starts when the diagram opens and doesn't survive a reload (RBDs keep no saved versions).

## The check

Validation runs by itself 0.8 s after each change; there is no Validate button. Its answer is a chip toned by the worst item ("✓ Valid", "! 2 warnings", "✕ 3 problems", "Checking…" meanwhile) that opens the full list with **Check again**. On a phone only its icon shows, with the count beside it when there are issues; its accessible name and tooltip say it in words ("Diagram valid", "3 problems"). It never stops a save.

Source: `frontend/src/components/RbdEditor.jsx` (`ToolbarMenu`, `DiagramSettings`, `ValidationStatus`); styles in `frontend/src/index.css` ("The RBD builder's toolbar").
