import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { SectionHeader, ShowMe } from "./SectionPage.jsx";
import ListSearch, { matches } from "./ListSearch.jsx";
import "./RegisterList.css";

// The landing page of a register: Assets (the places you look after) and
// Products (what you design and build) share it, so the two look and work the
// same. The section header (title, one-line purpose, "Show me how", the main
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
export default function RegisterList({
  title, purpose, help, primary, menu, error, rows, noun, count, search, placeholder, columns, name, after = null, empty,
  className = "",
}) {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const all = rows || [];
  const visible = all.filter((r) => matches(query, ...search(r)));
  const [one, many] = noun;
  return (
    <div className={"app reg-page" + (className ? ` ${className}` : "")}>
      <SectionHeader title={title} purpose={purpose} help={help} primary={primary} menu={menu} />
      {error && <div className="card error">{error}</div>}
      {rows === null ? (
        !error && <div className="card empty">Loading…</div>
      ) : all.length === 0 && !after ? (
        <div className="card empty section-empty">
          <h2>{empty.title}</h2>
          <p>{empty.text}</p>
          <div className="section-empty-action">{primary}{empty.sample}</div>
          <p className="section-empty-more">
            {empty.more}{empty.more && help ? " " : ""}
            {help && <ShowMe help={help}>{empty.guide || "Show me how"}</ShowMe>}
          </p>
        </div>
      ) : (
        <>
          <div className="tablebar section-tablebar">
            <span className="count">{query ? `${visible.length} of ${all.length} ${many}` : count}</span>
            <span className="grow" />
            <ListSearch value={query} onChange={setQuery} placeholder={`Search ${many}…`} />
          </div>
          <div className="lib maint-scroll">
            <table className="lib-table reg-table">
              <colgroup>
                <col className="reg-col-name" />
                {columns.map((c) => <col key={c.key} className="reg-col" />)}
              </colgroup>
              <thead>
                <tr>
                  <th>{one[0].toUpperCase() + one.slice(1)}</th>
                  {columns.map((c) => <th key={c.key} className={c.num ? "num" : undefined}>{c.label}</th>)}
                </tr>
              </thead>
              <tbody>
                {visible.map((r) => {
                  const n = name(r);
                  return (
                    <tr key={r.id} className="lib-row" onClick={() => navigate(n.to)}>
                      <td>
                        <Link to={n.to} className="lib-name maint-node-name" onClick={(e) => e.stopPropagation()}>{n.label}</Link>
                        {n.sub && <div className="lib-date">{n.sub}</div>}
                      </td>
                      {columns.map((c) => (
                        <td key={c.key} className={c.num ? "num" : undefined} data-label={c.label}>{c.cell(r)}</td>
                      ))}
                    </tr>
                  );
                })}
                {!query && after}
              </tbody>
            </table>
            {!visible.length && query && <p className="section-nomatch">No {one} matches.</p>}
          </div>
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
