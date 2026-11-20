// Shared pieces of the saved-item lists (#312): the row actions, and the
// "Samples" group that replaces a "(sample)" suffix plus a chip on every row.

import { Link, useNavigate } from "react-router-dom";
import MoreMenu from "./ui/MoreMenu.jsx";
import { rowOpen } from "../rowLinks.js";

export { rowOpen };

// The name cell's link: a real <a href>, so a row can be opened in a new tab,
// middle-clicked or its address copied, and reached with Tab. The click stops
// here, so the row's own click handler doesn't navigate a second time.
export function RowLink({ to, children, className = "", ...rest }) {
  return (
    <Link {...rest} className={`lib-link ${className}`.trim()} to={to} onClick={(e) => e.stopPropagation()}>
      {children}
    </Link>
  );
}

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

// Table rows: the user's own items first, under "Yours", then the shared
// samples under "Samples" (always labelled: they aren't the user's). "Yours"
// shows only above samples, where it tells the two apart. ``cols`` is the table's column count.
export function SampleGroups({ rows, cols, render }) {
  const own = rows.filter((r) => !r.is_sample);
  const samples = rows.filter((r) => r.is_sample);
  return (
    <>
      {own.length > 0 && samples.length > 0 && (
        <tr className="lib-group">
          <th colSpan={cols} scope="colgroup">Yours</th>
        </tr>
      )}
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

// The actions cell every list row ends with: one ⋯ button and the shared row
// menu (MoreMenu → RowMenu), in the design system's order: Open, the row's own
// actions (`actions`: [{id, label, onSelect, disabled?, reason?}]), then
// Delete after a line (for a shared sample or an item shared with you it
// reads "Remove from my view"). A row with Open as its only action keeps a
// plain Open button instead of a menu of one. Clicks don't reach the row's own
// open handler.
// ``to`` makes Open go to that address; ``onOpen`` alone runs it for rows that
// don't have one.
export function RowActions({ item, onOpen, to, onDelete, actions = [] }) {
  const navigate = useNavigate();
  const stop = (e) => e.stopPropagation();
  const open = to ? () => navigate(to) : onOpen;
  const items = [
    ...(open ? [{ id: "open", label: "Open", onSelect: open }] : []),
    ...actions.filter(Boolean),
    ...(onDelete
      ? [...(open || actions.length ? [{ separator: true }] : []),
         { id: "delete", label: item?.read_only ? "Remove from my view" : "Delete…", danger: true, onSelect: onDelete }]
      : []),
  ];
  const name = itemName(item);
  return (
    <td className="lib-actions" onClick={stop}>
      <div className="lib-acts">
        {items.length === 1 && items[0].id === "open" ? (
          to ? (
            <Link className="act act-open" to={to} title="Open" aria-label="Open">
              <OpenIcon />
            </Link>
          ) : (
            <button className="act act-open" title="Open" aria-label="Open" onClick={onOpen}>
              <OpenIcon />
            </button>
          )
        ) : items.length > 0 && (
          <MoreMenu label={name ? `Actions for ${name}` : "Actions"} items={items} />
        )}
      </div>
    </td>
  );
}
