# WhereItLives

Where a rolled-up record lives, in one table cell. The Explorer rolls up: a tab on a tree node lists the records on that node **and on everything below it**, at any depth (the server's `Maintenance.subtree_ids`, cut to the asset opened by `?root=`). Each row then needs to say where it is.

`frontend/src/components/ui/WhereItLives.jsx`, with its helpers in `frontend/src/subtree.js`.

## What it shows

- **First line:** the position's (or place's) name, in the table's own size and `text`.
- **Second line:** `fs-12`, `text-secondary`: **This position** on the node's own records, else what the position sits in, its nearest parents top first (*Pump 2 › Drive motor*), so twins can be told apart.
- **Hover:** the whole path.

Both lines are cut with an ellipsis rather than wrapping, so rows keep one height.

## Props

`rec` (a record with `subject: {id, name, within}`, as the server's roll-ups give it), `here` (the node's id: its own records say so), `own` (the words for those, default "This position"), `className`.

## Use with it

- Put the node's own records first when no sort is picked (`hereFirst(key)` from `subtree.js`), then the rest by `wherePath`, so twins sit beside their parents.
- Say how many are the node's own beside the count (`hereCount`): "7 tasks · 2 on this position".
- Make the path searchable: a search for a parent's name finds what's inside it.
- One cell per row, in a column named for what it is ("Position"). Never a link that leaves the tab: the tree beside it is how you go there.

First used by the Maintenance tab's tasks (Assets › Explorer › Maintenance › Tasks).
