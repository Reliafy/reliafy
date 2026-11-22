import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { SectionHeader, ShowMe } from "./SectionPage.jsx";
import ListSearch, { matches } from "./ListSearch.jsx";
import { RowActions } from "./LibRows.jsx";
import MoreMenu from "./ui/MoreMenu.jsx";
import LoadFailed from "./LoadFailed.jsx";
import "./RegisterList.css";
import Loading from "./ui/Loading.jsx";

// The landing page of a register: Assets (the places you look after) and
// Products (what you design and build) share it, so the two look and work the
// same. The section header (title, one-line purpose, "Read the guide", the main
// action top right, a ⋯ menu); the counts line with one search box; one table:
// the name with a quiet line under it, then the numbers, each column the same
// width on both pages; the same empty state (what it is, the main action, the
// sample, the guide). Opening a row opens its tree.
//
// `rows`: null while loading. `columns`: [{ key, label, num?, cell(row) }]
// after the name. `name(row)`: { to, label, sub }. `search(row)`: the texts a
// query matches. `count`: the counts line with no query. `after`: rows after
// the list (Assets' "Not at a place yet"), given the same columns.
// `empty`: { title, text, sample (a button), more (a line under it) }.
// `onDelete(row)`: a bin at the end of each row (Delete…); the `after` rows
// then end in an empty cell of their own. `pane`: work opened from the header's
// ⋯ menu (Assets' Excel import and export), drawn under the header, above the list.
// `rowMenu(row)`: a ⋯ menu at the end of each row in place of the bin ([{id,
// label, danger?, onSelect}]: Assets' Merge into another asset… and Delete…).
// `loadError`: the list's read failed (the Error or its message): the shared
// LoadFailed card in place of the list, with Try again from `onRetry`. `error`
// stays for a failed action (a delete), shown above the list.
// `found(query, shown)`: what else the query finds, drawn under the list while
// there's a query (Assets: the positions and items inside the assets); it then
// says "nothing matches" itself, with `shown` the rows the list kept.
export default function RegisterList({
  title, purpose, help, primary, actions = null, menu, error, rows, noun, count, search, placeholder, columns, name, after = null, empty,
  className = "", onDelete = null, pane = null, rowMenu = null, loadError = null, onRetry = null, found = null,
}) {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const all = rows || [];
  const visible = all.filter((r) => matches(query, ...search(r)));
  const [one, many] = noun;
  return (
    <div className={"app reg-page" + (className ? ` ${className}` : "")}>
      <SectionHeader title={title} purpose={purpose} help={help} primary={primary} actions={actions} menu={menu} />
      {pane}
      {error && <div className="card error">{error}</div>}
      {loadError ? (
        <LoadFailed what={`Couldn't load your ${many}.`} error={loadError} onRetry={onRetry} />
      ) : rows === null ? (
        !error && <Loading card />
      ) : all.length === 0 && !after ? (
        <div className="card empty section-empty">
          <h2>{empty.title}</h2>
          <p>{empty.text}</p>
          <div className="section-empty-action">{primary}{empty.sample}</div>
          <p className="section-empty-more">
            {empty.more}{empty.more && help ? " " : ""}
            {help && <ShowMe help={help}>{empty.guide}</ShowMe>}
          </p>
        </div>
      ) : (
        <>
          <div className="tablebar section-tablebar">
            <span className="count">{query ? `${visible.length} of ${all.length} ${many}` : count}</span>
            <span className="grow" />
            <ListSearch value={query} onChange={setQuery} placeholder={placeholder || `Search ${many}…`} />
          </div>
          {!(found && query.trim() && !visible.length) && <div className="lib maint-scroll">
            <table className="lib-table reg-table">
              <colgroup>
                <col className="reg-col-name" />
                {columns.map((c) => <col key={c.key} className="reg-col" />)}
                {(onDelete || rowMenu) && <col className="reg-col-act" />}
              </colgroup>
              <thead>
                <tr>
                  <th>{one[0].toUpperCase() + one.slice(1)}</th>
                  {columns.map((c) => <th key={c.key} className={c.num ? "num" : undefined}>{c.label}</th>)}
                  {(onDelete || rowMenu) && <th><span className="sr-only">Actions</span></th>}
                </tr>
              </thead>
              <tbody>
                {visible.map((r) => {
                  const n = name(r);
                  return (
                    <tr key={r.id} className="lib-row" onClick={() => navigate(n.to)}>
                      <td>
                        <Link to={n.to} className="lib-name maint-node-name" onClick={(e) => e.stopPropagation()}>{n.label}</Link>
                        {n.sub && <div className="lib-date reg-sub" title={typeof n.sub === "string" ? n.sub : undefined}>{n.sub}</div>}
                      </td>
                      {columns.map((c) => (
                        <td key={c.key} className={c.num ? "num" : undefined} data-label={c.label}>{c.cell(r)}</td>
                      ))}
                      {rowMenu ? (
                        // The menu's clicks stay in the menu (the row itself opens the asset).
                        <td className="lib-actions" onClick={(e) => e.stopPropagation()}>
                          <MoreMenu label={`Actions for ${n.label}`} items={rowMenu(r)} />
                        </td>
                      ) : onDelete && <RowActions item={r} onDelete={() => onDelete(r)} />}
                    </tr>
                  );
                })}
                {!query && after}
              </tbody>
            </table>
            {!visible.length && query && !found && <p className="section-nomatch">No {one} matches.</p>}
          </div>}
          {query.trim() && found && found(query.trim(), visible.length)}
        </>
      )}
    </div>
  );
}

// A count that links on when there's something to open, a quiet 0 when not.
export function CountCell({ n, to, label }) {
  if (!(n > 0)) return <span className="lib-date">0</span>;
  if (!to) return n;
  return <Link to={to} onClick={(e) => e.stopPropagation()} aria-label={label}>{n}</Link>;
}
