// Rows that give x and a range (xl to xr) both are left out of the fit: said
// loudly on the Data step's x row, never blocking Next. ``reading``: the
// server's reading of the rows (/api/data-reading), whose
// ``x_and_range_rows`` is { count, rows (1-based, the first few), warning }.
export default function XRangeWarning({ reading }) {
  const both = !reading?.error && reading?.x_and_range_rows;
  if (!both) return null;
  const one = both.count === 1;
  const more = both.count - both.rows.length;
  return (
    <div className="xcn-warning" role="alert">
      <b>
        {both.count.toLocaleString()} {one ? "row has" : "rows have"} x and a range (xl–xr) both filled,
        so {one ? "it is" : "they are"} left out of the fit.
      </b>
      <details>
        <summary>Which rows</summary>
        <span>
          {one ? "Row" : "Rows"} {both.rows.join(", ")}{more > 0 ? ` and ${more.toLocaleString()} more` : ""}, counted
          from the first row under the headings. Clear x or the range on each to use {one ? "it" : "them"}.
        </span>
      </details>
    </div>
  );
}
