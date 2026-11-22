# WhereItLives

Where a rolled-up record lives, in one table cell. The Explorer rolls up: a tab on a tree node lists the records on that node **and on everything below it**, at any depth (the server's `Maintenance.subtree_ids`, cut to the asset opened by `?root=`). A tree-table (Maintenance › Tasks, Measurements, Models) says where each row is by its nesting; a flat table in the panel needs this cell instead.

`frontend/src/components/ui/WhereItLives.jsx`.

## What it shows

- **First line:** the position's (or place's) name, in the table's own size and `text`.
- **Second line:** `fs-12`, `text-secondary`: **This position** on the node's own records, else what the position sits in, its nearest parents top first (*Pump 2 › Drive motor*), so twins can be told apart.
- **Hover:** the whole path.

Both lines are cut with an ellipsis rather than wrapping, so rows keep one height.

## Props

`rec` (a record with `subject: {id, name, within}`, as the server's roll-ups give it), `here` (the node's id: its own records say so), `own` (the words for those, default "This position"), `className`.

## Use with it

- Put the node's own records first, then the rest in the table's order.
- One cell per row, in a column named for what it is ("Position"). Never a link that leaves the tab: the tree beside it is how you go there (a button that picks the row in the tree is fine).

Used by the Condition monitoring table on a node with positions below it (Monitoring › Life left).
