# LoadFailed

What a page, or a part of one, shows when its read failed: the reason in words, and a way on. It is the one error state for a load, so a failure never falls back to an empty or first-run message ("Nothing here yet", "Nothing needs you right now"), which would be a guess.

## Kinds

- **Missing** (the message says "not found"): a neutral card with `role="status"`. It says the item may have been deleted or the link mistyped, and links back to its list.
- **Failed** (anything else: the server, the connection): the red error card (`danger-text` on `danger-bg`) with `role="alert"`. It offers **Try again** when the caller can load again, and a link back to the list when there is one.

## Props

`error` (the message, said first: "Couldn't load what needs you."), `to` and `label` (the list to go back to), `notFound` (what to say instead when the item is missing), `header` (adds a page header on a page without one), `onRetry` (shows a secondary "Try again" button that loads again), `className`.

## Placement and look

- A whole page: in place of the page's content, under its header.
- Part of a page (a Home list, the Explorer's tree): in place of that part's card, under its heading; whatever else on the page loaded stays.
- "Try again" is a secondary button under the reason, `space-3` above it, 40px tall on a phone. One per card.
- Words: what didn't load, then what to do. No raw error codes on their own.

Source: `frontend/src/components/LoadFailed.jsx`; used by the detail pages, Home's lists and the Explorer's tree.
