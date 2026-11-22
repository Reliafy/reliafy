// "Show all rows" on the dataset page: the rows come in windows from the
// server (GET /api/datasets/:id/rows), and the table numbers them the way the
// app names a row everywhere else (data rows from 1, under the header).

// Rows asked for at a time: a screenful or so, small enough to be quick on a
// dataset of tens of thousands of rows.
export const ROWS_PAGE = 200;

// The columns with a "#" first, and each row with its number first, for a
// window starting at `offset` (0-based).
export function numberedRows(columns, rows, offset = 0) {
  return {
    columns: ["#", ...columns],
    rows: rows.map((r, i) => [offset + i + 1, ...r]),
  };
}

// How many more the next window brings: a full page, or what is left.
export function nextWindow(loaded, total, page = ROWS_PAGE) {
  return Math.max(0, Math.min(page, total - loaded));
}
