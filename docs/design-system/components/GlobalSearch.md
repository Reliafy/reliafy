# GlobalSearch

The one search for everything: a box in the top bar, and **⌘K** (**Ctrl K**) from any page, open a search dialog over the page. It finds records (the register's assets, positions, items, parts, products and work orders for Reliafy Maintenance users; data, models, diagrams, fault trees, saved analyses, reports, libraries and their records), the app's pages and Explorer tabs by the words people use for them, and the how-to guides. It doesn't replace a page's own list search, which narrows the list you're looking at.

## Behaviour

- **A dialog, by the Modal's rules** (`Modal`): focus moves into the box, stays in the dialog, and goes back to whatever opened it; Escape closes it. On a phone (720px and under) it fills the screen.
- **Results grouped by kind**, the group with the best match first; in each group, best match first: an exact name, tag, serial or part number, then one that starts with what's typed, then whole words, then words inside, then a near spelling (one letter out; two in a long word). Codes (a word with a digit) and words under four letters match only as typed. Each group shows its first five, and says "first 5 of N" when there are more.
- **Each result** is its name, with the words typed in `semibold`, and one context line in `text-secondary`: what it is and where (an asset and the way down, a part's stock, a model's type), when it last changed, and "Sample" for a shared sample.
- **Keyboard:** the box keeps the focus; ↑ ↓ move one result (wrapping), Tab and Shift+Tab jump to the next or previous group's first result, Enter opens. Tab past the last group leaves the box, as it would anywhere.
- **Where a result opens:** a place, position or item in the Explorer on its own asset (`?root=`, the row picked); a design's position on its product's page; anything else on its own page; a page or tab on itself (a tab on the asset already open, else via the Assets list); a guide in the help drawer.
- **Only what the viewer can open:** the active workspace's records (and, in a personal workspace, the samples not hidden and items shared with you), Reliafy Maintenance's only for its users, work orders only with work management on, pages from the live menu.
- Pages and guides show as you type; records follow from the server (`GET /api/search`) with "Searching your records…" until they come.

## Look

The top bar's trigger reads as a search field: `control-md` tall, `border-control`, `radius-md`, placeholder text in `text-tertiary` and the shortcut in a `caption`-sized key. On a phone it's a 40px icon button. The active result has an `accent-wash` ground and a 2px `accent` bar on its left edge.

## Props

None: it reads the workspace, the live menu (`useRoles`) and the config itself. The ranking and the page list are `frontend/src/globalSearch.js`; the server's is `backend/services/global_search.py`, word for word.

Source: `frontend/src/components/GlobalSearch.jsx`.
