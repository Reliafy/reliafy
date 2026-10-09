// Shared pieces of the saved-item lists (#312): the row actions, and the
// "Samples" group that replaces a "(sample)" suffix plus a chip on every row.

export const OpenIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M7 17 17 7M9 7h8v8" />
  </svg>
);
export const TrashIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M4 7h16M9 7V5h6v2M7 7l1 13h8l1-13" />
  </svg>
);
export const PlusIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 5v14M5 12h14" />
  </svg>
);

// Shared samples are stored as "Bearing life — Weibull (sample)"; the group
// heading (or a Sample chip on a detail page) says so instead, once.
export function itemName(item) {
  const name = item?.name || "";
  return item?.is_sample ? name.replace(/\s*\(sample\)\s*$/i, "") : name;
}

// Table rows: the user's own items first, then the shared samples under one
// "Samples" heading row. ``cols`` is the table's column count.
export function SampleGroups({ rows, cols, render }) {
  const own = rows.filter((r) => !r.is_sample);
  const samples = rows.filter((r) => r.is_sample);
  return (
    <>
      {own.map(render)}
      {samples.length > 0 && (
        <tr className="lib-group">
          <th colSpan={cols} scope="colgroup">Samples</th>
        </tr>
      )}
      {samples.map(render)}
    </>
  );
}

// The actions cell every list row ends with: Open, any extras, then Delete
// (which, for a shared sample or an item shared with you, hides it from your
// view). Clicks don't reach the row's own open handler.
export function RowActions({ item, onOpen, onDelete, children }) {
  const stop = (fn) => (e) => {
    e.stopPropagation();
    fn(e);
  };
  return (
    <td className="lib-actions">
      <div className="lib-acts">
        <button className="act act-open" title="Open" aria-label="Open" onClick={stop(onOpen)}>
          <OpenIcon />
        </button>
        {children}
        {onDelete && (
          <button
            className="act del"
            title={item?.read_only ? "Remove from my view" : "Delete"}
            aria-label={item?.read_only ? "Remove from my view" : "Delete"}
            onClick={stop(onDelete)}
          >
            <TrashIcon />
          </button>
        )}
      </div>
    </td>
  );
}
