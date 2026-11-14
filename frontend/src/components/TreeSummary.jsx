import { useMemo, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import Chip from "./ui/Chip.jsx";
import Section, { AddRow } from "./ui/Section.jsx";
import ClampLines from "./ui/ClampLines.jsx";
import { fmtDate, fmtDated } from "./MaintenanceParts.jsx";
import { RowIcon } from "./TreePane.jsx";
import OperatingContextCard from "./OperatingContextCard.jsx";
import { byName, insideWords, statusWords } from "../assetTree.js";
import { safeHref } from "../maintenanceFields.js";
import { taskDueText } from "../taskTrigger.js";
import { annualLsa, annualText, nextVisit } from "../lsaTab.js";
import { explorerHere } from "../products.js";

// The Explorer's Summary tab (#UI, the RCM details panel's patterns): one
// column, a readable width at most. Status chips and the description first,
// then sections 16 px apart: Facts (a label/value card), Work (rows with
// chips), Operating context (edited in place), Directly inside (rows, sorted
// as you choose, ending in "+ New position inside"), Measurements and
// Documents when there are any, then a footer with the row's own changes
// (Delete… in red). Everything links on: an item, a work order, a row inside.
//
// A product's design (`design`) has no maintenance done to it: no status
// chips, nothing fitted or located, no work, measurements or due dates, only
// its class, where it's placed in the product's layout, operating context,
// what's inside and its documents; a design location (the layout's rows) says
// what it is and what's placed there. A product's
// own row passes its facts (`facts`) and its sections (`children`: the items
// built, their failure reports, its analyses) in their place.

const OPEN = new Set(["open", "planned", "in_progress", "waiting"]);
const STATUS = { open: "Open", planned: "Planned", in_progress: "In progress", waiting: "Waiting" };
const n = (k, one, many = `${one}s`) => `${k.toLocaleString("en-AU")} ${k === 1 ? one : many}`;
const quiet = (text) => <span className="td-quiet">{text}</span>;

function StatusChips({ r }) {
  const words = statusWords(r);
  return (
    <div className="chip-row td-status">
      {words.length ? words.map((w, i) => <Chip key={i} tone={w.kind === "open" ? "accent" : "danger"}>{w.text}</Chip>)
        : <Chip tone="success">✓ Nothing overdue, no open work and no alarms{r.kids.length ? ", here or inside" : ""}</Chip>}
    </div>
  );
}

function Facts({ r, display, fittedFrom, design = false }) {
  const p = r.ref;
  const rows = [];
  if (r.type === "pos" && design) {
    rows.push(["Position class", p.position_class || quiet("None")]);
    // Where it sits in the product's layout (its design locations), set here or from what it's inside.
    rows.push(["Placed at", p.location ? (
      <>{p.location.name}{p.location.inherited && <span className="td-quiet td-sub">From what it's inside</span>}</>
    ) : quiet("Not placed in the layout")]);
  }
  if (r.type === "loc" && design) {
    rows.push(["What", "Part of the product's physical layout: where its positions sit. Items built from it carry a copy."]);
  }
  if (r.type === "pos" && !design) {
    rows.push(["Position class", p.position_class || quiet("None")]);
    rows.push(["Fitted", p.item ? (
      <>
        <Link to={`/asset-register/items/${p.item.id}`}>{p.item.name}</Link>
        {(p.item.serial || fittedFrom?.from) && (
          <span className="td-quiet td-sub">
            {[p.item.serial && `Serial ${p.item.serial}`,
              fittedFrom?.from && `fitted since ${fmtDated(fittedFrom.from, fittedFrom.from_precision)}`].filter(Boolean).join(" · ")}
          </span>
        )}
      </>
    ) : quiet(p.position_class ? "Nothing fitted (an empty slot)" : "Nothing fitted")]);
    if (p.carried_by) {
      rows.push(["Carried by", <><Link to={`/asset-register/items/${p.carried_by.id}`}>{p.carried_by.name}</Link><span className="td-quiet td-sub">It moves with the item</span></>]);
    }
    rows.push(["Location", p.location ? (
      <><Link to={`/asset-register/locations/${p.location.id}`}>{p.location.name}</Link>
        {p.location.inherited && <span className="td-quiet td-sub">From what it's inside</span>}</>
    ) : quiet("Not at a location yet")]);
  }
  if (r.type === "item") {
    const atRow = p.location_id && display.rows.get(p.location_id);
    const at = p.place || (atRow && { id: atRow.key, name: atRow.ref.name });
    rows.push(["Serial", p.serial || quiet("None")]);
    if (p.item_class) rows.push(["Item class", p.item_class.name]);
    const make = [p.manufacturer, p.model].filter(Boolean).join(" ");
    if (make) rows.push(["Make and model", make]);
    if (p.fitted_to) {
      rows.push(["Fitted to", <Link to={`/asset-register/positions/${p.fitted_to.id}`}>{p.fitted_to.name}</Link>]);
      if (at) rows.push(["Location", <><Link to={`/asset-register/locations/${at.id}`}>{at.name}</Link><span className="td-quiet td-sub">Where its position is</span></>]);
    } else {
      rows.push(["Where", at ? <>Placed at <Link to={`/asset-register/locations/${at.id}`}>{at.name}</Link></>
        : quiet("Not fitted and not placed anywhere")]);
    }
  }
  if (r.type === "group" && p.note) rows.push(["What", p.note]);
  if (r.kids.length) rows.push(["Inside", insideWords(r) || quiet("No positions")]);
  if (!rows.length) return null;
  return (
    <Section title="Facts">
      <dl className="td-kv">
        {rows.map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}
      </dl>
    </Section>
  );
}

// A row of a list: an icon or nothing, the title, a meta line, chips at the right.
function Row({ lead = null, title, meta, chips, onClick, className = "" }) {
  return (
    <li className={"td-row" + (onClick ? " is-go" : "") + (className ? ` ${className}` : "")} onClick={onClick}>
      {lead}
      <span className="td-row-main">
        <span className="td-row-title">{title}</span>
        {meta && <span className="td-row-meta">{meta}</span>}
      </span>
      {chips && <span className="chip-row td-row-chips">{chips}</span>}
    </li>
  );
}

const SHOWN_TASKS = 8;

// "Log an event…" (the row's action, when it has one) sits at the foot of Work:
// tasks waiting for an event are raised from here.
function Work({ r, state, today, fullPage, logEvent = null }) {
  // The LSA links stay in the tree on show (one asset open on its own stays so).
  const { pathname, search } = useLocation();
  const { data, error } = state;
  let body;
  let count = null;
  if (error) body = <p className="field-error" role="alert">Couldn't load its work: {error} Try again in a moment.</p>;
  else if (!data) body = <p className="td-quiet">Loading…</p>;
  else {
    const tasks = [...(data.tasks || []), ...(data.item_tasks || []).map((t) => ({ ...t, onItem: true }))]
      .sort((a, b) => (b.overdue - a.overdue) || (a.next_due || "9999").localeCompare(b.next_due || "9999"));
    const wos = (data.work_orders || []).filter((w) => OPEN.has(w.status))
      .sort((a, b) => (a.due || "9999").localeCompare(b.due || "9999"));
    count = tasks.length + wos.length;
    // In a work package: the next visit that does any of its tasks.
    const visit = nextVisit(data.tasks || []);
    // Its tasks' LSA over a year (hours × 365.25 ÷ interval; event and by-use tasks left out, and said).
    const annual = annualText(annualLsa(tasks));
    if (!count) {
      body = <p className="td-quiet">No tasks or open work on this position itself.{r.kids.length ? " What's inside it has its own: see Directly inside." : ""}</p>;
    } else {
      body = (
        <>
          {wos.length > 0 && (
            <div className="td-group">
              <h4 className="td-sublabel">Open work orders</h4>
              <ul className="td-rows">
                {wos.map((w) => {
                  const late = w.due && today && w.due < today;
                  return (
                    <Row key={w.id}
                         title={<Link to={`/maintenance/work-orders/${w.id}`}>#{w.number} {w.title}</Link>}
                         meta={w.due ? `Due ${fmtDate(w.due)}` : "No due date"}
                         chips={<>
                           {late && <Chip tone="danger">Overdue</Chip>}
                           <Chip tone={w.status === "in_progress" ? "accent" : "neutral"}>{STATUS[w.status] || w.status}</Chip>
                         </>} />
                  );
                })}
              </ul>
            </div>
          )}
          {visit && (
            <p className="td-quiet td-next-visit">
              Next visit: <Link to={explorerHere(pathname, search, { sel: r.key, tab: "lsa", package: visit.id })}>{visit.name}</Link> on {fmtDate(visit.on)}
            </p>
          )}
          {annual && (
            <p className="td-quiet td-annual" title="Each task's labour hours × 365.25 ÷ its interval in days, added up. Tasks raised by an event or counted by use have no yearly count.">
              <Link to={explorerHere(pathname, search, { sel: r.key, tab: "lsa" })}>{annual}</Link>
            </p>
          )}
          {tasks.length > 0 && (
            <div className="td-group">
              <h4 className="td-sublabel">Tasks</h4>
              <ul className="td-rows">
                {tasks.slice(0, SHOWN_TASKS).map((t) => {
                  const note = (t.limits || []).map((l) => l.note).find(Boolean);
                  return (
                    <Row key={`${t.onItem ? "i" : "p"}${t.id}`} title={t.name}
                         meta={taskDueText(t, fmtDate, note)}
                         chips={(t.overdue || t.onItem || t.on_event) ? <>
                           {t.overdue && <Chip tone="danger">Overdue</Chip>}
                           {t.on_event && <Chip>On event</Chip>}
                           {t.onItem && <Chip>On the item</Chip>}
                         </> : null} />
                  );
                })}
              </ul>
              {tasks.length > SHOWN_TASKS && fullPage && (
                <Link className="td-more" to={fullPage}>{n(tasks.length - SHOWN_TASKS, "more task")} on its page</Link>
              )}
            </div>
          )}
        </>
      );
    }
  }
  return (
    <Section title="Work" count={count || null}>
      {body}
      {logEvent && (
        <button type="button" className="link td-more" disabled={logEvent.disabled} title={logEvent.reason || undefined}
                onClick={logEvent.onSelect}>
          {logEvent.label}
        </button>
      )}
    </Section>
  );
}


// What's directly inside, as rows: the counts (overdue, open work, alarms)
// take in everything inside each row. Sorted as the tree has them, or by
// what needs attention.
const SORTS = [
  { id: "tree", label: "As in the tree" },
  { id: "name", label: "Name" },
  { id: "overdue", label: "Most overdue", get: (r) => r.sum.overdue, desc: true },
  { id: "open", label: "Most open work", get: (r) => r.sum.open_work, desc: true },
  { id: "alarms", label: "Most alarms", get: (r) => r.sum.alarms, desc: true },
  { id: "due", label: "Next due first", get: (r) => r.sum.next_due || "￿" },
  { id: "inside", label: "Most positions inside", get: (r) => r.sum.positions, desc: true, positionsOnly: true },
];
const SHOWN_INSIDE = 500;
const where = (r) => r.ref.fitted_to?.name || (r.ref.place ? `At ${r.ref.place.name}` : "");

function insideChips(k) {
  const s = k.sum;
  if (!s.overdue && !s.open_work && !s.alarms) return null;
  return (
    <>
      {s.overdue > 0 && <Chip tone="danger">{s.overdue.toLocaleString("en-AU")} overdue</Chip>}
      {s.open_work > 0 && <Chip tone="accent">{s.open_work.toLocaleString("en-AU")} open</Chip>}
      {s.alarms > 0 && <Chip tone="danger">{n(s.alarms, "alarm")}</Chip>}
    </>
  );
}

function Inside({ r, display, onSelect, add, here = null, design = false }) {
  const [sort, setSort] = useState("tree");
  const ofItems = r.kids.length > 0 && r.kids.every((k) => display.rows.get(k).type === "item");
  const sorts = SORTS.filter((s) => !(ofItems && s.positionsOnly) && !(design && s.get && !s.positionsOnly));
  const kids = useMemo(() => {
    const rows = r.kids.map((k) => display.rows.get(k));
    const s = SORTS.find((x) => x.id === sort);
    if (!s || s.id === "tree") return rows;
    if (s.id === "name") return [...rows].sort(byName);
    const cmp = s.desc ? (a, b) => s.get(b) - s.get(a) : (a, b) => String(s.get(a)).localeCompare(String(s.get(b)));
    return [...rows].sort((a, b) => cmp(a, b) || byName(a, b));
  }, [r, display, sort]);
  if (!r.kids.length && !add && !here) return null;
  const metaOf = (k) => {
    if (ofItems) return [k.ref.serial && `Serial ${k.ref.serial}`, where(k) || "No home yet"].filter(Boolean).join(" · ");
    const s = k.sum;
    if (design) return [k.ref.position_class, s.positions ? `${n(s.positions, "position")} inside` : null].filter(Boolean).join(" · ");
    return [
      k.ref.item?.name || (k.type === "pos" && k.ref.position_class ? "Nothing fitted" : null),
      s.positions ? `${n(s.positions, "position")} inside` : null,
      s.next_due ? `next due ${fmtDate(s.next_due)}` : null,
    ].filter(Boolean).join(" · ");
  };
  return (
    <Section title="Directly inside" count={r.kids.length ? r.kids.length.toLocaleString("en-AU") : null}
             tip={ofItems || !r.kids.length ? null : "Each row's counts take in everything inside it. Pick a row to go to it."}
             aside={r.kids.length > 1 && (
               <label className="td-sort">
                 <span className="sr-only">Sort what's inside</span>
                 <select className="ctl td-sort-sel" value={sort} onChange={(e) => setSort(e.target.value)}>
                   {sorts.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
                 </select>
               </label>
             )}>
      {r.kids.length === 0 && <p className="td-quiet">Nothing inside yet.</p>}
      {r.kids.length > 0 && (
        <ul className="td-rows">
          {kids.slice(0, SHOWN_INSIDE).map((k) => (
            <Row key={k.key} lead={<RowIcon r={k} />} onClick={() => onSelect(k.key)}
                 title={(
                   <button type="button" className="link td-go" onClick={(e) => { e.stopPropagation(); onSelect(k.key); }}>
                     {k.ref.name || "(no name)"}
                   </button>
                 )}
                 meta={metaOf(k)} chips={design ? null : insideChips(k)} />
          ))}
        </ul>
      )}
      {kids.length > SHOWN_INSIDE && (
        <p className="td-quiet">Showing the first {SHOWN_INSIDE} of {kids.length.toLocaleString("en-AU")}. Filter the tree to find the rest.</p>
      )}
      {here && (
        <AddRow onClick={here.onSelect} disabled={here.disabled}>
          {here.label}{here.disabled && here.reason ? <span className="sr-only">: {here.reason}</span> : null}
        </AddRow>
      )}
      {add && (
        <AddRow onClick={add.onSelect} disabled={add.disabled}>
          {add.label}{add.disabled && add.reason ? <span className="sr-only">: {add.reason}</span> : null}
        </AddRow>
      )}
    </Section>
  );
}

const SHOWN_POINTS = 6;
const ALARM = { low: "Below its alarm limit", high: "Above its alarm limit" };

function Measurements({ data, fullPage }) {
  const points = (data?.measurements || []).filter((m) => !m.retired);
  if (!points.length) return null;
  const sorted = [...points].sort((a, b) => ((b.status !== "ok") - (a.status !== "ok")));
  const alarms = points.filter((m) => m.status && m.status !== "ok").length;
  return (
    <Section title="Measurements" count={points.length}>
      <ul className="td-rows">
        {sorted.slice(0, SHOWN_POINTS).map((m) => (
          <Row key={m.id} title={m.name}
               meta={m.reading != null
                 ? `${m.reading.toLocaleString("en-AU")} ${m.unit || ""}`.trim() + (m.read_at ? ` · read ${fmtDated(m.read_when || m.read_at, m.read_precision)}` : "")
                 : "No reading yet"}
               chips={m.status && m.status !== "ok" ? <Chip tone="danger">{ALARM[m.status] || m.status}</Chip> : null} />
        ))}
      </ul>
      {(points.length > SHOWN_POINTS || alarms > 0) && fullPage && (
        <Link className="td-more" to={fullPage}>
          {points.length > SHOWN_POINTS ? `${n(points.length - SHOWN_POINTS, "more measurement")} on its page` : "Readings and trends on its page"}
        </Link>
      )}
    </Section>
  );
}

function Documents({ data, fullPage }) {
  const docs = data?.documents || [];
  const photos = data?.photos || [];
  if (!docs.length && !photos.length) return null;
  return (
    <Section title="Documents and photos" count={docs.length + photos.length}>
      {docs.length > 0 && (
        <ul className="td-rows">
          {docs.slice(0, 5).map((d) => {
            const href = d.stored ? null : safeHref(d.url);
            return (
              <Row key={d.id}
                   title={href ? <a href={href} target="_blank" rel="noopener noreferrer">{d.title}</a>
                     : fullPage ? <Link to={fullPage}>{d.title}</Link> : d.title}
                   meta={[d.kind && d.kind[0].toUpperCase() + d.kind.slice(1), d.stored ? "PDF" : "Link"].filter(Boolean).join(" · ")} />
            );
          })}
        </ul>
      )}
      {(docs.length > 5 || photos.length > 0) && fullPage && (
        <Link className="td-more" to={fullPage}>
          {[docs.length > 5 && n(docs.length - 5, "more document"), photos.length > 0 && n(photos.length, "photo")].filter(Boolean).join(" and ")} on its page
        </Link>
      )}
    </Section>
  );
}

// The row's own changes, at the foot: Rename and Move as small buttons,
// Delete… as red text. Each is greyed with its reason where it can't be done.
function Footer({ actions }) {
  if (!actions.length) return null;
  return (
    <div className="td-foot">
      {actions.map((a) => (
        <button key={a.id} type="button" className={"sm " + (a.danger ? "ghost td-danger" : "secondary")}
                disabled={a.disabled} title={a.reason || undefined} onClick={a.onSelect}>
          {a.label}
          {a.disabled && a.reason && <span className="sr-only">: {a.reason}</span>}
        </button>
      ))}
    </div>
  );
}

// `actions`: the row's changes from the tree's row menu, [{id, label, danger?,
// disabled?, reason?, onSelect}]; "tree-new" becomes the add row ending
// Directly inside, the rest the footer.
export default function TreeSummary({
  row, display, today, onSelect, position, fullPage, onContextSaved, actions = [], design = false, facts = null, children = null,
}) {
  const add = actions.find((a) => a.id === "tree-new") || null;
  const logEvent = actions.find((a) => a.id === "event-log") || null;
  // A place: New position here, an add row of its own above New location inside.
  const here = actions.find((a) => a.id === "pos-here") || null;
  const rest = actions.filter((a) => a.id !== "tree-new" && a.id !== "event-log" && a.id !== "pos-here");
  return (
    <div className="td-sum">
      {!design && <StatusChips r={row} />}
      {row.type === "pos" && position.data?.description && (
        <ClampLines className="td-desc" text={position.data.description} what="the description" />
      )}
      {facts || <Facts r={row} display={display} design={design} fittedFrom={row.type === "pos" ? position.data?.fitted : null} />}
      {children}
      {row.type === "pos" && !design && <Work r={row} state={position} today={today} fullPage={fullPage} logEvent={logEvent} />}
      {row.type === "pos" && (
        <OperatingContextCard positionId={row.key} state={position} onSaved={onContextSaved} />
      )}
      <Inside r={row} display={display} onSelect={onSelect} add={add} here={here} design={design} />
      {row.type === "pos" && !design && <Measurements data={position.data} fullPage={fullPage} />}
      {row.type === "pos" && <Documents data={position.data} fullPage={fullPage} />}
      <Footer actions={rest} />
    </div>
  );
}
