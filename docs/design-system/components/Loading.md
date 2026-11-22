# Loading

What sits where something will be while it loads. It is the one loading state, so a page never shows a bare "Loading…" card, a spinner of its own, or the empty sentence ("Nothing here yet") before the answer is in.

## Forms

- **Block** (the default): quiet grey rows in the shape of what's coming. Use it for a whole list, card, panel, tab or page.
  - `shape="list"` (the default): a row with a kind, a name and a line of detail, sized like a list row, so the card barely moves when the list arrives.
  - `shape="fields"`: a form, each row a short label bar over a control-high box (a details panel loading).
  - `card`: drawn in its own card, in place of a card that will load (a page's content, a list card).
- **Inline**: a quiet "Loading…" in `text-secondary` at `fs-13`, for a spot inside a sentence, a field, a small summary card or a cell. `as="p"` where it stands as a line of its own.

Where the words themselves are the control's label (a button reading "Loading…" while more rows come, a count line, a select's first `<option>`), keep the plain text: an `<option>` and a `placeholder` can't hold a component, and a button already says it's busy.

## Props

`inline`, `as` (inline only: `span` or `p`), `label`, `shape`, `rows` (3), `card`, `className`.

## Words

- Block: `label` is what a screen reader hears, through `role="status"`. Say what is loading when you know: "Loading the task…", "Loading the trade rates…". The default is "Loading…". Pass `null` when a parent already says the page is loading.
- Inline: the label is the visible text; keep it "Loading…" unless the spot needs the thing named.
- Sentence case, the single ellipsis character (…), never "Please wait" or "Fetching".

## Behaviour

- Both forms carry `view-loading`, the mark the smoke suite waits on: a page counts as settled only once its loading states are gone. Don't put it on anything that stays.
- The bars pulse gently; with reduced motion they hold still.
- Tokens only: bars `border` and `border-subtle`, rows `space-3`/`space-4`, the field box `control-md` with `radius-md`.
- **Never "Loading…" under a LoadFailed card.** When the read fails, `LoadFailed` takes the loader's place: show one or the other, never both.

Source: `frontend/src/components/ui/Loading.jsx` and `Loading.css`.
