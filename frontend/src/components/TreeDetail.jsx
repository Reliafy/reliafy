import { forwardRef, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { getMaintenancePosition } from "../api.js";
import PageHeader from "./ui/PageHeader.jsx";
import Tabs from "./ui/Tabs.jsx";
import ClampText from "./ClampText.jsx";
import PositionRcm from "./PositionRcm.jsx";
import { DueChip, fmtDate, fmtDated } from "./MaintenanceParts.jsx";
import { ancestorsOf, byName, insideWords, statusWords } from "../assetTree.js";
import { shownTab, tabsFor } from "../explorerTabs.js";

// The panel beside the asset tree: what the selected row is, in a glance. A
// position: where it sits, what's fitted, its status in words, its work
// (overdue first), its class and location, and what's directly inside it. An
// item: its serial, class, make and model, and where it is (the position it's
// fitted to, or the place it's kept). "Open the full page" goes to the row's
// own page, where it's edited (an item's history and fitments are there).
//
// The panel has tabs (explorerTabs.js): Summary (the above) for every row, and
// RCM for a position (its functions, functional failures, failure modes and
// decisions, read from and written to the tree itself).

const OPEN = new Set(["open", "planned", "in_progress", "waiting"]);
const KIND = { pos: "Position", loc: "Location", item: "Item", group: "" };

export function fullPagePath(r) {
  if (r.type === "pos") return `/asset-register/positions/${r.key}`;
  if (r.type === "loc") return `/asset-register/locations/${r.key}`;
  if (r.type === "item") return `/asset-register/items/${r.key}`;
  return null;
}

// What a position page fetch gives the panel (tasks, work orders, since when
// fitted): fetched a moment after the selection settles, so arrowing down the
// tree doesn't fetch every row on the way.
function usePosition(id, version) {
  const [state, setState] = useState({ id: null, data: null, error: null });
  useEffect(() => {
    if (!id) return undefined;
    let live = true;
    const t = setTimeout(() => {
      getMaintenancePosition(id)
        .then((data) => live && setState({ id, data, error: null }))
        .catch((e) => live && setState({ id, data: null, error: e.message }));
    }, 180);
    return () => {
      live = false;
      clearTimeout(t);
    };
  }, [id, version]);
  return state.id === id ? state : { id, data: null, error: null };
}

function StatusLine({ r }) {
  const words = statusWords(r);
  if (!words.length) return <p className="td-status td-ok">Nothing overdue, no open work and no alarms{r.kids.length ? ", here or inside" : ""}.</p>;
  return (
    <p className="td-status">
      {words.map((w, i) => <span key={i} className={`td-pill ${w.kind}`}>{w.text}</span>)}
    </p>
  );
}

function Facts({ r, display }) {
  const p = r.ref;
  const rows = [];
  if (r.type === "pos") {
    rows.push(["Class", p.position_class || "None"]);
    rows.push(["Fitted", p.item ? (
      <><Link to={`/asset-register/items/${p.item.id}`}>{p.item.name}</Link>{p.item.serial && <span className="lib-date"> · serial {p.item.serial}</span>}</>
    ) : <span className="lib-date">{p.position_class ? "Nothing fitted (an empty slot)" : "Nothing fitted"}</span>]);
    if (p.carried_by) {
      rows.push(["Carried by", <><Link to={`/asset-register/items/${p.carried_by.id}`}>{p.carried_by.name}</Link><span className="lib-date"> (it moves with the item)</span></>]);
    }
    rows.push(["Location", p.location ? (
      <><Link to={`/asset-register/locations/${p.location.id}`}>{p.location.name}</Link>
        {p.location.inherited && <span className="lib-date"> (from what it's inside)</span>}</>
    ) : <span className="lib-date">Not at a location yet</span>]);
  }
  if (r.type === "item") {
    const atRow = p.location_id && display.rows.get(p.location_id);
    const at = p.place || (atRow && { id: atRow.key, name: atRow.ref.name });
    rows.push(["Serial", p.serial || <span className="lib-date">None</span>]);
    if (p.item_class) rows.push(["Class", p.item_class.name]);
    const make = [p.manufacturer, p.model].filter(Boolean).join(" ");
    if (make) rows.push(["Make and model", make]);
    if (p.fitted_to) {
      rows.push(["Fitted to", <Link to={`/asset-register/positions/${p.fitted_to.id}`}>{p.fitted_to.name}</Link>]);
      if (at) rows.push(["Location", <><Link to={`/asset-register/locations/${at.id}`}>{at.name}</Link><span className="lib-date"> (where its position is)</span></>]);
    } else {
      rows.push(["Where", at ? <>Placed at <Link to={`/asset-register/locations/${at.id}`}>{at.name}</Link></>
        : <span className="lib-date">Not fitted and not placed anywhere</span>]);
    }
  }
  if (r.type === "group" && p.note) rows.push(["What", p.note]);
  const inside = insideWords(r);
  if (r.kids.length) rows.push(["Inside", inside || <span className="lib-date">No positions</span>]);
  return (
    <section className="card td-card">
      <h3>Facts</h3>
      <dl className="td-facts">
        {rows.map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}
      </dl>
    </section>
  );
}

function Work({ r, state }) {
  const { data, error } = state;
  const kids = r.kids.length > 0;
  let body;
  if (error) body = <p className="lib-date">Couldn't load its work: {error} Try again in a moment.</p>;
  else if (!data) body = <p className="lib-date">Loading…</p>;
  else {
    const tasks = [...(data.tasks || []), ...(data.item_tasks || []).map((t) => ({ ...t, onItem: true }))]
      .sort((a, b) => (b.overdue - a.overdue) || (a.next_due || "9999").localeCompare(b.next_due || "9999"));
    const wos = (data.work_orders || []).filter((w) => OPEN.has(w.status));
    if (!tasks.length && !wos.length) {
      body = <p className="lib-date">No tasks or open work on this position itself.{kids ? " See what's inside below." : ""}</p>;
    } else {
      body = (
        <>
          {data.fitted?.from && (
            <p className="lib-date td-since">Fitted since {fmtDated(data.fitted.from, data.fitted.from_precision)}</p>
          )}
          {wos.length > 0 && (
            <ul className="td-list">
              {wos.map((w) => (
                <li key={w.id}>
                  <Link to={`/maintenance/work-orders/${w.id}`}>#{w.number} {w.title}</Link>
                  <span className="lib-date"> · {w.status.replace("_", " ")}{w.due ? ` · due ${fmtDate(w.due)}` : ""}</span>
                </li>
              ))}
            </ul>
          )}
          {tasks.length > 0 && (
            <ul className="td-list">
              {tasks.slice(0, 8).map((t) => (
                <li key={t.id}>
                  {t.name}{t.onItem && <span className="maint-badge">on the item</span>}
                  <span className="td-due"> <DueChip task={t} /></span>
                </li>
              ))}
              {tasks.length > 8 && <li className="lib-date">and {tasks.length - 8} more on its page</li>}
            </ul>
          )}
        </>
      );
    }
  }
  return (
    <section className="card td-card">
      <h3>Work</h3>
      {body}
    </section>
  );
}

// What's directly inside, as a small table you can sort: the totals (Σ) count
// everything inside each row.
const COLUMNS = [
  { id: "name", label: "Name", get: (r) => r.ref.name || "" },
  { id: "item", label: "Fitted item", get: (r) => r.ref.item?.name || "" },
  { id: "overdue", label: "Overdue Σ", num: true, get: (r) => r.sum.overdue },
  { id: "open", label: "Open work Σ", num: true, get: (r) => r.sum.open_work },
  { id: "alarms", label: "Alarms Σ", num: true, get: (r) => r.sum.alarms },
  { id: "due", label: "Next due Σ", get: (r) => r.sum.next_due || "" },
  { id: "inside", label: "Positions inside", num: true, get: (r) => r.sum.positions },
];

// For a list of items (the Items arrangement's groups): what the old Items
// list showed, and their own status.
const where = (r) => r.ref.fitted_to?.name || (r.ref.place ? `at ${r.ref.place.name}` : "");
const ITEM_COLUMNS = [
  { id: "name", label: "Name", get: (r) => r.ref.name || "" },
  { id: "serial", label: "Serial", get: (r) => r.ref.serial || "" },
  { id: "where", label: "Fitted to or kept at", get: where },
  ...COLUMNS.slice(2, 6).map((c) => ({ ...c, label: c.label.replace(" Σ", "") })),
];

function Inside({ r, display, today, onSelect }) {
  const [sort, setSort] = useState({ id: null, desc: false });
  const ofItems = r.kids.every((k) => display.rows.get(k).type === "item");
  const columns = ofItems ? ITEM_COLUMNS : COLUMNS;
  const kids = useMemo(() => {
    const rows = r.kids.map((k) => display.rows.get(k));
    const col = columns.find((c) => c.id === sort.id);
    if (!col) return rows;
    const cmp = col.num ? (a, b) => col.get(a) - col.get(b)
      : col.id === "name" ? byName : (a, b) => String(col.get(a) || "￿").localeCompare(String(col.get(b) || "￿"));
    const out = [...rows].sort(cmp);
    return sort.desc ? out.reverse() : out;
  }, [r, display, sort, columns]);
  if (!r.kids.length) return null;
  const toggle = (id) => setSort((s) => (s.id === id ? { id, desc: !s.desc } : { id, desc: columns.find((c) => c.id === id).num }));
  return (
    <section className="card td-card">
      <div className="td-inside-head">
        <h3>Directly inside <span className="td-n">{r.kids.length.toLocaleString("en-AU")}</span></h3>
        <span className="lib-date">{ofItems ? "Pick a row to go to it." : "Totals (Σ) count everything inside each row. Pick a row to go to it."}</span>
      </div>
      <div className="maint-scroll">
        <table className="lib-table td-table">
          <thead>
            <tr>
              {columns.map((c) => (
                <th key={c.id} className={c.num ? "num" : undefined}
                    aria-sort={sort.id === c.id ? (sort.desc ? "descending" : "ascending") : undefined}>
                  <button type="button" className="td-sort" onClick={() => toggle(c.id)}>{c.label}</button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {kids.slice(0, 500).map((k) => (
              <tr key={k.key} className="lib-row" onClick={() => onSelect(k.key)}>
                <td><button type="button" className="link td-go" onClick={(e) => { e.stopPropagation(); onSelect(k.key); }}>{k.ref.name}</button></td>
                {ofItems ? (
                  <>
                    <td className="lib-date">{k.ref.serial || ""}</td>
                    <td>{where(k) || <span className="lib-date">no home yet</span>}</td>
                  </>
                ) : (
                  <td>{k.ref.item?.name || <span className="lib-date">{k.type === "pos" && k.ref.position_class ? "empty" : ""}</span>}</td>
                )}
                <td className="num">{k.sum.overdue ? <span className="maint-overdue">{k.sum.overdue}</span> : ""}</td>
                <td className="num">{k.sum.open_work || ""}</td>
                <td className="num">{k.sum.alarms ? <span className="maint-overdue">{k.sum.alarms}</span> : ""}</td>
                <td className={k.sum.next_due && k.sum.next_due < today ? "maint-overdue" : "lib-date"}>{k.sum.next_due ? fmtDate(k.sum.next_due) : ""}</td>
                {!ofItems && <td className="num">{k.sum.positions || ""}</td>}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {kids.length > 500 && <p className="lib-date">Showing the first 500 of {kids.length.toLocaleString("en-AU")}. Filter the tree to find the rest.</p>}
    </section>
  );
}

function Summary({ row, display, today, onSelect, version }) {
  const position = usePosition(row.type === "pos" ? row.key : null, version);
  return (
    <>
      <StatusLine r={row} />
      {row.type === "pos" && position.data?.description && (
        <ClampText className="td-desc" text={position.data.description} title="Description" />
      )}
      <div className="td-grid">
        <Facts r={row} display={display} />
        {row.type === "pos" && <Work r={row} state={position} />}
      </div>
      <Inside r={row} display={display} today={today} onSelect={onSelect} />
    </>
  );
}

const WideIcon = ({ on }) => (
  <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.8"
       strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {on ? <path d="M9 5v14M4 9l3 3-3 3M20 5v14" /> : <path d="M4 5v14M20 5v14M9 12h6M12 9l3 3-3 3" />}
  </svg>
);

const TreeDetail = forwardRef(function TreeDetail({
  display, row, today, onSelect, back, version, empty, tab, onTab, inside, onInside, phone, wide, onWide,
  fullScreenButton, onTreeChanged,
}, headingRef) {
  if (!row) return <div className="td">{back}{empty}</div>;
  const crumbs = ancestorsOf(display, row.key).map((k) => ({ label: display.rows.get(k).ref.name, onClick: () => onSelect(k) }));
  const full = fullPagePath(row);
  const p = row.ref;
  const meta = [KIND[row.type], p.tag && <code key="tag">{p.tag}</code>].filter(Boolean);
  const tabs = tabsFor(row);
  const shown = shownTab(tab, row);
  const rcm = shown === "rcm";
  return (
    <div className={"td" + (rcm ? " td-fit" : "")}>
      {back}
      <PageHeader
        className="td-header"
        crumbs={crumbs}
        title={<span ref={headingRef} tabIndex={-1} className="td-title">{p.name || "(no name)"}</span>}
        meta={meta.length ? meta.reduce((acc, m, i) => (i ? [...acc, " · ", m] : [m]), []) : null}
        actions={(
          <>
            {rcm && !phone && onWide && (
              <button type="button" className="secondary sm td-wide" aria-pressed={wide} onClick={() => onWide(!wide)}
                      title={wide ? "Show the tree again" : "Fold the tree away and give the RCM the width"}>
                <WideIcon on={wide} /> {wide ? "Show the tree" : "Full width"}
              </button>
            )}
            {fullScreenButton}
          </>
        )}
        primary={full && <Link className="td-open" to={full}>Open the full page</Link>}
      />
      {tabs.length > 1 && (
        <Tabs tabs={tabs} value={shown} onChange={onTab} label="What to show for this row" idPrefix="td" className="td-tabs" />
      )}
      <div className="td-body" role={tabs.length > 1 ? "tabpanel" : undefined} id={tabs.length > 1 ? "td-panel" : undefined}
           aria-labelledby={tabs.length > 1 ? `td-tab-${shown}` : undefined}>
        {rcm ? (
          <PositionRcm position={{ id: row.key, name: p.name }} inside={inside} onInside={onInside} phone={phone}
                       onChanged={onTreeChanged} />
        ) : (
          <Summary row={row} display={display} today={today} onSelect={onSelect} version={version} />
        )}
      </div>
    </div>
  );
});

export default TreeDetail;
