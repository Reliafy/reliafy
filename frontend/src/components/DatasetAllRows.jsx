import { useEffect, useState } from "react";
import { getDatasetRows } from "../api.js";
import { ROWS_PAGE, nextWindow, numberedRows } from "../datasetRows.js";
import PreviewTable from "./PreviewTable.jsx";

// Every row of a dataset's table, a window at a time, numbered from 1 so a row
// can be named ("row 7"). The dataset page shows the first few rows; this is
// how to find one value among hundreds. The table scrolls inside its own
// frame, its header kept in view.
//
//   datasetId, part   what to read (part: "life" or "measurements")
//   nRows             the table's row count (what "all" means)
//   types             column → type word, shown under each column's name
//   onClose           back to the short preview
export default function DatasetAllRows({ datasetId, part, nRows, types, onClose }) {
  const [columns, setColumns] = useState(null);
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const load = (offset) => {
    setLoading(true);
    setError(null);
    getDatasetRows(datasetId, { part, offset, limit: ROWS_PAGE })
      .then((out) => {
        setColumns(out.columns);
        setRows((prev) => (offset === 0 ? out.rows : [...prev, ...out.rows]));
      })
      .catch((e) => setError(e.message || "The rows couldn't be loaded."))
      .finally(() => setLoading(false));
  };

  // First window on open; the open table starts over for another dataset or part.
  useEffect(() => {
    setColumns(null);
    setRows([]);
    load(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [datasetId, part]);

  const numbered = columns ? numberedRows(columns, rows, 0) : null;
  const more = nextWindow(rows.length, nRows);

  return (
    <div className="ds-allrows-wrap">
      {numbered && (
        <PreviewTable columns={numbered.columns} rows={numbered.rows} types={types} className="ds-allrows" />
      )}
      {error && <p className="error" role="alert">{error}</p>}
      <div className="ds-allrows-foot">
        <span className="muted" role="status">
          {loading && !rows.length ? "Loading the rows…" : `Showing 1–${rows.length.toLocaleString()} of ${nRows.toLocaleString()} rows`}
        </span>
        {more > 0 && (
          <button type="button" className="secondary" onClick={() => load(rows.length)} disabled={loading}>
            {loading ? "Loading…" : `Show ${more.toLocaleString()} more`}
          </button>
        )}
        <button type="button" className="link" onClick={onClose}>Show fewer rows</button>
      </div>
    </div>
  );
}
