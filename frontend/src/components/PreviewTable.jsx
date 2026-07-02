// Compact preview of the first rows of the uploaded CSV.
export default function PreviewTable({ columns, rows }) {
  if (!rows?.length) return null;
  return (
    <div className="preview-wrap">
      <table className="preview-table">
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c}>{c}</th>
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
