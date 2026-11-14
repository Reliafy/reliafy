# HelpLink

A page's help, offered quietly: a small ghost button that says what it does — "Take the tour" or "Read the guide" — beside the section's purpose line.

## Kinds

- **tour** — starts a walkthrough on a sample, which takes over the screen. Label "Take the tour", play icon.
- **guide** — opens a how-to in the Help drawer, something to read. Label "Read the guide", book icon.

Name the kind in the label so nobody is surprised; never a generic "Show me how" or "Learn more".

## Props

`kind` ("tour" | "guide"), `onClick`, `children` (an optional label in place of the default), `className`.

## Placement and look

- In a `SectionHeader`, after the purpose. The purpose wraps to two lines at most (its full text on hover), never cut mid-sentence on one line.
- The link sits beside the purpose while there's room, else on its own line. Its padding bleeds left (`margin-inline-start: -space-2`), so the icon lines up with the text above.
- `text-secondary` at `fs-13`/500, icon `text-tertiary`. On hover it turns `accent-text` on `accent-wash`. No underline: it is a button, not running text.
- Never as loud as the primary action. One help link per header.
- Inside a sentence (an empty state's "…or show me how"), keep an inline text link instead.

Source: `frontend/src/components/ui/HelpLink.jsx`, used by `SectionHeader` (`components/SectionPage.jsx`).
