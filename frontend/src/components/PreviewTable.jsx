// Compact preview of the first rows of the uploaded CSV. ``types`` (column →
// a word such as "integer" or "text") puts each column's type under its name.
export default function PreviewTable({ columns, rows, types = null, className = "" }) {
  if (!rows?.length) return null;
  return (
    <div className={"preview-wrap" + (className ? " " + className : "")}>
      <table className="preview-table">
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c}>
                {c}
                {types?.[c] && <span className="pv-type">{types[c]}</span>}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i}>
              {row.map((cell, j) => (
                <td key={j}>{cell === null ? "" : String(cell)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
